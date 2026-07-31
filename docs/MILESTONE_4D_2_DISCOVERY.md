# Milestone 4D-2 Discovery — Checklist Execution, Response and Immutable Snapshot Foundation

**Status: DESIGN REVIEW COMPLETE. All open questions resolved. Not approved for implementation.**

**Branch:** `regx/design/milestone-4d-2-discovery`
**Base SHA:** `453974a4cd40501479730a524fd1b6671a96d6fc` (Milestone 4D-1 merge)
**Remediation:** `docs/MILESTONE_4D_2_DESIGN_REMEDIATION.md` — all findings CLOSED

This document is the discovery gate for Milestone 4D-2. It proposes a
domain boundary, model relationships, lifecycle, snapshot semantics,
response storage, authorization shape, and API surface for the
**checklist execution and response foundation** that runs on top of the
`iig_checklist` definition-governance layer delivered by Milestone 4D-1.

Every proposal below is written to be reviewed and revised before an
implementation branch opens. Where a decision is genuinely unresolved,
it is marked **OPEN** with the competing options and the information
needed to close it. Where the approved Milestone 4D design document
already resolved a question, that resolution is quoted and marked
**APPROVED (4D design)** — it is not re-decided here.

---

## 1. Purpose

Milestone 4D-2 is the second of at least four implementation stages
under the approved Milestone 4D design
([MILESTONE_4D_DISCOVERY.md](MILESTONE_4D_DISCOVERY.md)):

- **4D-1 (CLOSED):** `ChecklistDefinition` governance —
  stable identity, versioned content, lifecycle, permissions, audit,
  platform-master authorization.
- **4D-2 (this document):** `ChecklistExecution`, `ChecklistResponse`,
  and `CalculationOutcome` — one tenant's use of a governed definition
  version against a specific formulation version, frozen at approval.
- **4D-3 (not started):** Draft-answer generation, automatic
  `FDA_DERIVED_DEFAULT` population, `SYSTEM_CALCULATED` computation,
  and recalculation.
- **4D-4 (not started):** Overrides/deviations, reviewer conclusion,
  controlled exports, and production checklist content.

4D-2 provides the structural foundation — execution identity, response
records, snapshot freezing, lifecycle transitions, tenant isolation,
and audit — on which 4D-3's automatic-answer generation and 4D-4's
export will build. It does **not** include draft-answer population,
calculation evaluation, override routing, export, or any real
regulatory checklist content.

---

## 2. Approved inputs

The following design decisions are already made and are not
re-opened here. Each is referenced with its source.

| Decision | Source |
|---|---|
| `ChecklistExecution` lives in `iig_checklist`, not in a new app | 4D design §1 (DECIDED DR-06) |
| One execution per `FormulationVersion`, not per excipient or per component | 4D design §8 open question 5 (RESOLVED) |
| `ChecklistExecution` status set: `draft`, `submitted_for_review`, `returned`, `approved`, `rejected`, `cancelled`, `superseded` | 4D design §8 / §8a (DR-05) |
| Transition table: exactly one authoritative table, structurally identical to `fda_data/mapping_transitions.py` | 4D design §14 |
| `ChecklistResponse` is immutable once `approved`; `full_clean()` must actually be invoked at every save attempt, not left as an unreachable model-level comment | 4D design §7 / §18 (DR-02) |
| `data_source_type_snapshot` frozen on `ChecklistResponse` at answer time | 4D design §7 / §18 |
| `checklist_definition` FK pinned to a specific `ChecklistVersion` — never "latest" | 4D design §8 |
| Self-approval blocked: actor who `submit_review`s cannot `approve` | 4D design §8 |
| `SYSTEM_CALCULATED` answers stored as `CalculationOutcome`, never bare values | 4D design §6 |
| `CalculationOutcome` mirrors `CalculationResult` fields verbatim | 4D design §9 (DR-04) |
| `is_not_applicable` / `not_applicable_reason` on `ChecklistResponse`; never represented as null/blank | 4D design §3a |
| Evidence attachments via `documents` app `storage_key` indirection | 4D design §15 |
| Scanner stub disclosure: production scanning not guaranteed | 4D design §15 (DR-07) |
| `cancelled` ≠ `rejected`; `superseded` is never automatic | 4D design §8a (DR-05) |
| Audit events follow `fda_data/audit_events.py` conventions; safe metadata only | 4D design §16 |
| No automatic safety or approval conclusion | 4D design §20 |
| No new calculation formulas; all six from `iid_assessment.calculations` reused unmodified | 4D design §20 |
| No override/deviation workflow in 4D-2 | 4D design §12 (deferred to 4D-4) |
| No controlled exports in 4D-2 | 4D design §17 (deferred to 4D-4) |
| No real regulatory checklist content | 4D design §20 |

---

## 3. Current architecture (relevant to 4D-2)

### 3a. `iig_checklist` (Milestone 4D-1, CLOSED)

The definition-governance domain delivered by 4D-1 and now present
in `regx-main`:

- `ChecklistDefinition` — stable identity (code + scope_type).
  `scope_type` is `platform_master` or `tenant`. No lifecycle status
  on the definition itself; versions carry status.
- `ChecklistVersion` — 8-status lifecycle (`draft`, `under_review`,
  `returned`, `approved`, `active`, `rejected`, `superseded`,
  `retired`). Immutable once outside `draft`/`returned`.
- `ChecklistSection` / `ChecklistQuestion` — structural content of
  a version. Immutable once the version leaves `draft`/`returned`.
- `ApplicabilityRule` — structured JSON condition tree scoped to
  a version. Validated, no `eval`/`exec`.
- `ChecklistDefinitionManager.visible_to(tenant)` — exposes
  `platform_master` rows plus the tenant's own rows. Critical: this
  visibility never grants mutation authority.
- Permissions: 11 codenames + `can_author_platform_master()` (superuser
  only). `can_mutate_definition_scope()` is the single authoritative
  object-scope mutation check for all definition-adjacent content.

**4D-2 dependency on 4D-1:** `ChecklistExecution` FKs to
`ChecklistVersion` (not `ChecklistDefinition`). The version must be
`active` at the time of execution creation. 4D-2 adds no models to
`ChecklistDefinition`, `ChecklistVersion`, `ChecklistSection`, or
`ChecklistQuestion`.

### 3b. `formulations`

- `ProductDevelopmentRecord` — tenant-scoped product identity.
- `FormulationVersion` — versioned formulation content, FK to
  `ProductDevelopmentRecord`. Statuses: `draft`, `under_review`,
  `approved`, `superseded`, `retired`. Immutable once `approved`,
  `superseded`, or `retired` (`IMMUTABLE_FORMULATION_STATUSES`).
- `FormulationComponent` — FK to `FormulationVersion`. Carries
  `resolved_ingredient_public_id` (UUID, not FK), `percentage_w_w_snapshot`,
  `quantity_per_dosage_unit`, `quantity_unit`.
- `DosingRegimen` — FK to `FormulationVersion`.
- No public manager with `visible_to()` equivalent — access is
  implicitly tenant-scoped by every view's tenant-context lookup.

**4D-2 dependency:** `ChecklistExecution` FKs to `FormulationVersion`
via a live Django FK with `on_delete=PROTECT` (Q1 resolved by DR-2-03;
see §7 and §12). The API exposes only `formulation_version.public_id`
(UUID); no internal numeric PK is serialized.

### 3c. `iid_assessment`

- `AssessmentSnapshot` — immutable once created. Stores
  `formulation_component_public_id`, `formulation_version_public_id`,
  all matching and calculation outputs as frozen fields (UUIDs for
  referenced platform rows, never live FKs into `fda_data`).
  `clean()` guard exists but is **not invoked** in the current request
  path — a known pre-existing defect that 4D-2's `ChecklistResponse`
  immutability enforcement must not repeat (this is a required
  implementation-phase acceptance criterion per the approved 4D
  design §7/§18).
- Calculation services in `calculations.py`: six functions
  (`calculate_percentage_w_w`, `calculate_daily_exposure`,
  `calculate_percentage_of_potency`, `calculate_difference_from_potency`,
  `calculate_percentage_of_mde`, `calculate_difference_from_mde`).
  Nine distinct `CalculationStatus` values. `CalculationResult`
  dataclass carries: `value`, `unit`, `status`, `formula_version`,
  `rounding_rule`, `reason_code`, `inputs`, `input_provenance`,
  `generated_at`. These are consumed by 4D-2's `CalculationOutcome`
  model — not duplicated.

### 3d. `documents`

- `DocumentVersion.storage_key` — the indirection used by evidence
  attachment references. Tenant isolation enforced at the `Document`
  level via `tenant` FK.
- `StubScanner` is the production default; `ClamAVScanner` requires
  a live clamd service not present in any configuration in this repo.
  4D-2 inherits this gap unchanged, identical to 4D-1.

### 3e. `common`

- `PublicIDModel` — UUID `public_id`, internal `BigAutoField` PK.
- `TimeStampedModel` — `created_at`, `updated_at`.
- All 4D-2 models must inherit both, following the pattern of every
  governed model in this codebase.

### 3f. `audit`

- `AuditEvent` — append-only, `ImmutableManager`. Fields: `actor_id`,
  `actor_email`, `tenant_id`, `event_type`, `resource_type`,
  `resource_id`, `payload` (JSON). No live FKs — denormalized strings
  and UUIDs only, so deletions never cascade into the audit trail.

### 3g. Import linter contract

`iig_checklist` may import from: `common`, `audit`, `authorization`,
`tenancy`, `identity`, `fda_data` (read-only services), `formulations`
(read-only), `iid_assessment` (read-only). None of those six domain
apps may import back into `iig_checklist`. The execution models live
in `iig_checklist`, so 4D-2 adds no new import-linter contracts beyond
what the approved design already specified.

---

## 4. Proposed domain boundary

All 4D-2 models live in the existing `iig_checklist` app. No new
Django app is created. The 4D-1 definition-governance code is
unchanged.

New models proposed:

| Model | Purpose |
|---|---|
| `ChecklistExecution` | One tenant's governed execution against a specific `ChecklistVersion` and `FormulationVersion` |
| `ChecklistResponse` | One question's answer within an execution |
| `CalculationOutcome` | Frozen output of one `iid_assessment` calculation, child of `ChecklistResponse` |

New migration: `0002_execution.py` (single migration covering all three
models and their constraints).

---

## 5. Candidate model relationships

```
ChecklistExecution
  public_id               UUID
  tenant                  FK → tenancy.Tenant (on_delete=PROTECT)
  checklist_version       FK → ChecklistVersion (on_delete=PROTECT)
  formulation_version     FK → formulations.FormulationVersion (on_delete=PROTECT)
  status                  draft | submitted_for_review | returned |
                          approved | rejected | cancelled | superseded
  created_by              FK → identity.User (on_delete=PROTECT)
  submitted_by            FK → identity.User (SET_NULL, nullable)
  submitted_at            DateTimeField (nullable)
  reviewed_by             FK → identity.User (SET_NULL, nullable)
  returned_by             FK → identity.User (SET_NULL, nullable)
  returned_at             DateTimeField (nullable)
  return_reason           TextField (blank=True)
  approved_by             FK → identity.User (SET_NULL, nullable)
  approved_at             DateTimeField (nullable)
  rejected_by             FK → identity.User (SET_NULL, nullable)
  rejected_at             DateTimeField (nullable)
  cancelled_by            FK → identity.User (SET_NULL, nullable)
  cancelled_at            DateTimeField (nullable)
  superseded_by           FK → self (SET_NULL, nullable)
  reviewer_conclusion_note  TextField (blank=True; required at approve
                            boundary, not at model level)

ChecklistResponse
  public_id               UUID
  execution               FK → ChecklistExecution (on_delete=PROTECT)
  question                FK → ChecklistQuestion (on_delete=PROTECT)
  data_source_type_snapshot  CharField — frozen copy of question's
                            data_source_classification at answer time
  raw_value               JSONField (nullable) — typed by answer_type
  is_not_applicable       BooleanField (default=False)
  not_applicable_reason   CharField (nullable) — structured rule ID,
                          never free text
  entered_by              FK → identity.User (SET_NULL, nullable)
  entered_at              DateTimeField (nullable)
  confirmed_by            FK → identity.User (SET_NULL, nullable) —
                          REVIEWER_CONFIRMED and FDA_DERIVED_DEFAULT
                          overrides only
  confirmed_at            DateTimeField (nullable)
  override_reason         TextField (blank=True)
  system_derived_value    JSONField (nullable) — original system value,
                          set only when override_reason is set
  version                 PositiveIntegerField (default=1) — incremented
                          on every raw_value write; used for optimistic
                          locking by enter_reviewer_conclusion() (DR-2-23)

ChecklistResponseHistory
  public_id               UUID
  response                FK → ChecklistResponse (on_delete=PROTECT)
                          — PROTECT prevents cascade deletion of governed
                            amendment records (DR-2-30)
  prior_raw_value         JSONField (nullable) — raw_value before amendment
  new_raw_value           JSONField (nullable) — raw_value written by amendment
  prior_is_not_applicable BooleanField — is_not_applicable before amendment
  new_is_not_applicable   BooleanField — is_not_applicable after amendment
  prior_not_applicable_reason CharField (nullable) — before amendment
  new_not_applicable_reason   CharField (nullable) — after amendment
  prior_entered_by        FK → identity.User (SET_NULL, nullable)
  prior_entered_at        DateTimeField (nullable)
  prior_version           PositiveIntegerField — response.version before increment
  new_version             PositiveIntegerField — response.version after increment
  correction_reason       TextField — required on all amendments
  amended_by              FK → identity.User (on_delete=PROTECT)
  amended_at              DateTimeField — server timestamp at amendment
  source_classification_snapshot  CharField — frozen copy of
                          data_source_type_snapshot at amendment time
  Append-only: model-level and queryset-level deletion and update are
  blocked by GovernedHistoryMutationForbidden (DR-2-30)

CalculationOutcome
  public_id               UUID
  response                FK → ChecklistResponse (on_delete=CASCADE)
  calculation_name        CharField — one of the six exact function names
  formula_version         CharField
  status                  CharField — one of nine CalculationStatus strings
  value                   DecimalField (nullable)
  unit                    CharField (blank=True)
  inputs                  JSONField (default=dict)
  input_provenance        JSONField (default=dict)
  rounding_rule           CharField (blank=True)
  reason_code             CharField (blank=True)
  generated_at            DateTimeField (nullable)
  source_assessment_snapshot_public_id  UUID (nullable) — points at
                          iid_assessment.AssessmentSnapshot when the
                          value came directly from a frozen snapshot
```

### Constraints

- `unique_response_per_question_per_execution`: `(execution, question)` —
  one response row per question per execution. Enforced by
  `UniqueConstraint`.
- `unique_active_or_submitted_execution_per_version`: Open — see §12 Q2.
- `ChecklistResponse.clean()` must enforce immutability once
  `execution.status` is `approved`. `full_clean()` must be called
  at every save path — not left as an unreachable model guard.

---

## 6. Lifecycle options

### 6a. Transition table (approved)

The approved 4D design specifies this table verbatim:

| Action | Legal from | Result |
|---|---|---|
| `submit_review` | `draft`, `returned` | `submitted_for_review` |
| `approve` | `submitted_for_review` | `approved` |
| `reject` | `draft`, `submitted_for_review` | `rejected` |
| `return` | `submitted_for_review` | `returned` |
| `cancel` | `draft`, `returned` | `cancelled` |
| `supersede` | `approved` | `superseded` |

`rejected`, `cancelled`, and `superseded` are terminal — never
re-opened. A corrected assessment always starts a new `ChecklistExecution`.

Implementation: `execution_transitions.py` — a single authoritative
dict `{action: (frozenset(legal_from), resulting_status)}`, structurally
identical to `iig_checklist/transitions.py` and `fda_data`'s equivalent.
Views call `validate_execution_transition()` before any mutation;
illegal transitions return structured 400 with no DB write and no
audit event.

### 6b. `approve` pre-conditions — RESOLVED (DR-2-05)

Completeness is enforced at **both** `submit_review` and `approve`.

`submit_review` pre-condition (structured 400):
- Every `required=True` question has a response with non-null `raw_value`
  OR `is_not_applicable=True` with `not_applicable_reason` set.
- Every `REVIEWER_CONFIRMED` question has `confirmed_by` set.

`approve` pre-condition (redundant safety re-check, structured 400):
- Same completeness check. If responses were modified between `return`
  and resubmission, this catches any gap introduced in the interim.

`submit_review` prevents empty executions entering the review queue (UX
protection). `approve` is the regulatory integrity check. Both gates
serve distinct purposes; both are mandatory.

**`reviewer_conclusion` answer types and the completeness gate:** Questions
with `answer_type = reviewer_conclusion` are **excluded from the
`submit_review` completeness gate**. A `reviewer_conclusion` value can only be
entered by an actor with `PERM_REVIEW_EXECUTION` while the execution is
`submitted_for_review` — it is structurally impossible to require this value
before that state. If any required `reviewer_conclusion` questions are present,
the `approve` gate checks that their `raw_value` is non-null, ensuring the
reviewer has recorded a conclusion before the execution is approved. No
circular dependency exists: the submission gate never requires a value that
cannot legally be entered until after submission.

### 6c. FormulationVersion status at execution creation — RESOLVED (DR-2-10)

`create_execution()` requires `FormulationVersion.status == "approved"`.
Error: `error_code = "formulation_version_not_approved"` / 400.
See DR-2-10 for rationale.

### 6e. Reviewer-conclusion entry and amendment — RESOLVED (DR-2-23)

**Entry:** `reviewer_conclusion` answers are entered through a dedicated
endpoint (`POST responses/<uuid>/reviewer-conclusion/`) by an actor with
`PERM_REVIEW_EXECUTION`, and only while `execution.status ==
submitted_for_review`. The ordinary response-update endpoint (`PATCH
responses/<uuid>/`) does **not** accept `reviewer_conclusion` raw values —
any attempt is rejected with `error_code = "reviewer_conclusion_wrong_answer_type"` /
400.

**First entry:** `raw_value` is set; `entered_by` and `entered_at` are
populated; `response.version` increments to 2.

**Amendment:** While execution remains `submitted_for_review`, the reviewer
may amend a previously saved conclusion. Amendment requires a non-empty
`correction_reason`. A `ChecklistResponseHistory` record is created **inside
the same database transaction, after the optimistic-version check passes and
after the response row is saved** (DR-2-27). The history row captures
`prior_raw_value`, `new_raw_value`, `prior_version`, `new_version`,
`prior_is_not_applicable`, `new_is_not_applicable`,
`prior_not_applicable_reason`, `new_not_applicable_reason`,
`prior_entered_by`, `prior_entered_at`, `correction_reason`, `amended_by`,
`amended_at`, and `source_classification_snapshot`. No history row is
created if the version check fails. `response.version` increments within
the same transaction. Silent overwrite without `correction_reason` is
rejected with `error_code = "reviewer_conclusion_correction_reason_required"`
/ 400.

**Optimistic locking:** The service accepts `expected_version` from the
client. If `response.version != expected_version`, the operation fails with
`error_code = "reviewer_conclusion_stale_version"` / 409.

**Immutability after review completion:** Once the execution leaves
`submitted_for_review` (approved, rejected, cancelled, or superseded), the
`reviewer_conclusion` is immutable — any write attempt returns
`error_code = "reviewer_conclusion_immutable"` / 409. If the execution is
`returned`, the conclusion is retained and read-only until the execution is
resubmitted; after resubmission, the reviewer may amend it with a
`correction_reason`.

**Clearing:** Clearing `raw_value` to null is prohibited through this
endpoint.

**No automated conclusion:** This endpoint stores reviewer-provided text only.
No safety, regulatory, or PASS/FAIL conclusion is generated by 4D-2.

**Provenance vocabulary:** The canonical provenance fields are `entered_by`
and `entered_at` — these are the same fields used by ordinary response entry.
`entered_by`/`entered_at` are updated on each write (initial or amendment),
always reflecting the most-recent actor and timestamp. Full prior-value history
lives in `ChecklistResponseHistory` rows.

### 6d. Recalculation semantics (approved)

Per 4D design §8b: while `status = draft`, editing a `USER_REQUIRED`
or `EVIDENCE_DERIVED` response re-triggers recomputation of every
`SYSTEM_CALCULATED` question whose binding depends on it. Once
`submit_review` succeeds, all responses lock until the execution is
explicitly `returned`. No recomputation occurs during review. **4D-2
implements the lock only** — recalculation (the population pass) is
4D-3 scope.

---

## 7. Snapshot semantics options

The approved design's reproducibility requirement (§18) means a
completed execution must redisplay correctly from its stored rows
without re-querying live FDA/formulation data. Three fields implement
this:

**`ChecklistResponse.data_source_type_snapshot`** — frozen copy of
the question's `data_source_classification` at answer time. This
ensures a later `ChecklistDefinition` revision that changes a question's
classification cannot retroactively reclassify an already-approved
answer's provenance.

**`CalculationOutcome.source_assessment_snapshot_public_id`** — when a
calculation outcome came directly from a frozen `AssessmentSnapshot`,
this UUID captures which snapshot. Populated by 4D-3 (the calculation
pass). In 4D-2, this field exists but is always null (no calculation
population yet).

**`ChecklistExecution.checklist_version` FK** — pinned to a specific
`ChecklistVersion` row, never a definition-level reference. A definition
revision that produces a new version has no effect on existing
executions.

**`ApplicabilityRule` implicit freeze:** `ApplicabilityRule` rows are
immutable once their `ChecklistVersion` leaves `draft`/`returned`
(4D-1 enforcement). Since executions can only be created against
`active` versions, all applicability rules are already stable when
execution creation runs. The `ChecklistResponse` rows created at
execution creation implicitly capture the applicability evaluation
result: a question has a response row if and only if it was applicable
at creation time. No additional snapshot field is needed (DR-2-11).

**Formulation version linkage — RESOLVED (DR-2-03):**
`ChecklistExecution.formulation_version` is a live Django FK to
`formulations.FormulationVersion` with `on_delete=PROTECT`.

Rationale: `PROTECT` is consistent with every other governed FK in
this codebase. `iig_checklist → formulations` is already permitted by
the import-linter contract. Live FK enables ORM joins and
`select_related()`. `FormulationVersion` is immutable once `approved`,
guaranteeing the linked rows never change content after linkage.

**FormulationVersion status requirement — RESOLVED (DR-2-10):**
Execution creation requires `FormulationVersion.status == "approved"`.
A `draft` or `under_review` version can change its components,
invalidating applicability evaluation. `superseded` or `retired` versions
are blocked with `error_code = "formulation_version_not_approved"`.

Cross-tenant protection: `create_execution()` verifies
`formulation_version.product_development_record.tenant == execution.tenant`
before writing the FK. Violation returns
`error_code = "formulation_version_tenant_mismatch"` / 400.

---

## 8. Response storage options

**`raw_value` as `JSONField` — RESOLVED (DR-2-12, DR-2-17):**

Single JSONField with strict serializer-level validation against
`answer_type`. The prior DR-2-12 table used names that do not match the
implemented `AnswerType` enum (`boolean`, `text`, `system_calculated` as
an answer type). DR-2-17 replaces it with the definitive table keyed by
the exact DB values in `backend/iig_checklist/enums.py`.

**Important distinction:** `system_calculated` is a
`DataSourceClassification` value, **not** an `AnswerType`. A question
whose `data_source_classification == DataSourceClassification.SYSTEM_CALCULATED`
may have `answer_type` of `calculated_value`, `calculated_status`,
`yes_no_na`, or `percentage` (per the compatibility matrix in
`MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §3d-i`). `CalculationOutcome`
placeholder creation is triggered by the classification, not by any
answer type named "system_calculated".

**Canonical `raw_value` shapes — DR-2-17 (all 18 `AnswerType` DB values):**

| `answer_type` DB value | Client input | Canonical `raw_value` shape | Size limit | Notes |
|---|---|---|---|---|
| `short_text` | YES | `{"value": "..."}` | MAX_FREE_TEXT_CHARS | Non-empty string; floats/integers rejected |
| `long_narrative` | YES | `{"value": "..."}` | MAX_FREE_TEXT_CHARS | Non-empty string |
| `integer` | YES | `{"value": 42}` | — | JSON integer; floats, strings, and booleans explicitly rejected. Python `bool` is an `int` subclass — validation must check `isinstance(val, bool)` and reject before `isinstance(val, int)` accepts. |
| `decimal` | YES | `{"value": "12.3400"}` | — | Decimal string; JSON float rejected |
| `quantity_with_unit` | YES | `{"value": "12.3400", "unit": "mg"}` | — | Decimal string + one unit from `allowed_units`. `allowed_units` is a per-question `JSONField` on `ChecklistQuestion` (field confirmed present in 4D-1 codebase at `models.py`). Frozen by 4D-1 version immutability. Validation uses the pinned question's frozen `allowed_units` list — not a live lookup. Empty unit string rejected; unit not in frozen set rejected. Empty `allowed_units = []` is strictly invalid: no unit is ever accepted; empty list does not mean "any unit allowed" (DR-2-32). |
| `percentage` | YES | `{"value": "12.3400"}` | — | Decimal string; range `0.0000`–`100.0000` inclusive |
| `date` | YES | `{"value": "YYYY-MM-DD"}` | — | ISO 8601 date string only |
| `yes_no` | YES | `{"value": true}` or `{"value": false}` | — | JSON boolean only; strings rejected |
| `yes_no_na` | YES | `{"value": "yes"}` or `{"value": "no"}` or `{"value": "not_applicable"}` | — | Controlled string enum; JSON boolean rejected |
| `single_select` | YES | `{"option": "OPTION_CODE"}` | — | Must be a valid `QuestionOption.code` in the pinned `ChecklistVersion` |
| `multi_select` | YES | `{"options": ["CODE_A", "CODE_B"]}` | MAX_SELECT_OPTIONS items | Sorted ascending; duplicate codes rejected; each code must be a valid `QuestionOption.code` |
| `fda_record_reference` | YES | `{"public_id": "<uuid>", "record_type": "<controlled-type>"}` | — | Source validated against FDA record; `record_type` from closed enum |
| `formulation_component_reference` | YES | `{"public_id": "<uuid>"}` | — | Must belong to the execution's linked `FormulationVersion` |
| `attachment_reference` | YES | `{"document_version_public_id": "<uuid>"}` | — | Must belong to same tenant; DR-2-06 deletion protection applies |
| `calculated_value` | NO | `null` always | — | Value in `CalculationOutcome`; client-supplied `raw_value` rejected with `invalid_raw_value_shape` |
| `calculated_status` | NO | `null` always | — | Status/value in `CalculationOutcome`; client-supplied `raw_value` rejected |
| `reviewer_conclusion` | CONDITIONAL | `{"value": "..."}` | MAX_REVIEWER_CONCLUSION_CHARS (4 000 chars) | Only actor with `PERM_REVIEW_EXECUTION`; only while execution is `submitted_for_review`; dedicated endpoint `POST responses/<uuid>/reviewer-conclusion/`; provenance via `entered_by`/`entered_at`; amendment requires non-empty `correction_reason`; prior and new values retained in `ChecklistResponseHistory` atomically inside the same transaction as the response update (DR-2-27); optimistic lock via `expected_version`; immutable once execution leaves `submitted_for_review`; no automated conclusion. See §6e. |
| `approval_metadata` | NO | `null` in 4D-2 | — | Populated by lifecycle infrastructure; client input prohibited; shape defined in 4D-4 |

**`NOT_APPLICABLE` state (any type):** `raw_value = null`,
`is_not_applicable = True`, `not_applicable_reason` set (structured rule
ID, max `MAX_NOT_APPLICABLE_REASON_CHARS`). `is_not_applicable` is
supported on all 18 types except `calculated_value`, `calculated_status`,
and `approval_metadata`, which always have `raw_value = null` by design
and must not be marked `not_applicable` through the client.

**Unanswered state (eager creation):** `raw_value = null`,
`is_not_applicable = False`, `entered_by = null`. Distinguishable from
`NOT_APPLICABLE` by the `is_not_applicable` flag.

**Size limits — RESOLVED (DR-2-01, DR-2-29):**
- `raw_value`: max `MAX_RAW_VALUE_BYTES = 16_384` bytes (serialized JSON)
- `return_reason`: max `MAX_RETURN_REASON_CHARS = 2_000`
- `reviewer_conclusion_note` on `ChecklistExecution`: max `MAX_REVIEWER_CONCLUSION_CHARS = 4_000`
- `reviewer_conclusion` answer `raw_value.value`: max `MAX_REVIEWER_CONCLUSION_CHARS = 4_000`
  Unicode code points (DR-2-29). Uses the same named constant as the
  `reviewer_conclusion_note` field. Does NOT use `MAX_FREE_TEXT_CHARS`.
  Exceeding this limit returns `reviewer_conclusion_too_long` / 400.
- `short_text`, `long_narrative` `value`: max `MAX_FREE_TEXT_CHARS = 4_000` chars
- `not_applicable_reason`: max `MAX_NOT_APPLICABLE_REASON_CHARS = 200`
- `multi_select` arrays: max `MAX_SELECT_OPTIONS = 64` items

All limits validated at the serializer layer; `error_code = "payload_too_large"`
/ 400 on violation. No silent truncation.

---

## 9. Evidence-reference freezing options

Evidence attachments (`answer_type = attachment_reference` and every
`EVIDENCE_DERIVED` question) reference a `DocumentVersion` by
`public_id` (stored in `raw_value` as
`{"document_version_public_id": "..."}`).

Two freezing options:

**Option A:** reference only — store the UUID. The `DocumentVersion`
row already exists in the `documents` app; `on_delete=PROTECT` (if a
live FK is used) or the documents app's own deletion-protection (if
UUID-referenced) prevents removal. Nothing is copied.

**Option B:** copy-on-freeze — at `approve`, copy the document content
into a separate, execution-scoped storage key. Guarantees true
immutability independent of the `documents` app, but doubles storage
and is architecturally non-trivial.

**RESOLVED (DR-2-06) — Option B (DeletionProtectionRegistry hook):**

Evidence references are stored as `{"document_version_public_id": "<uuid>"}` in
`raw_value`. A live FK in `ChecklistResponse` to `DocumentVersion` would
require a nullable FK on every response row regardless of question type.

Deletion protection: the `documents` app exposes a
`DeletionProtectionRegistry`. `IigChecklistConfig.ready()` registers
a callable that checks whether any `ChecklistResponse` belonging to an
`approved` execution references the given `document_version_public_id`.
If yes, the callable returns `True` (protected) and the `documents` app
raises `DocumentVersionDeleteForbidden` before any DB deletion. The
import direction stays clean: `iig_checklist` registers its hook into
`documents`; `documents` never imports `iig_checklist`.

Tenant ownership check: the `enter_response()` service must verify that
the referenced `document_version_public_id` belongs to a `Document`
owned by the same tenant as the execution before accepting it.

---

## 10. Authorization model

### 10a. New execution-level permissions

Proposed codenames (following `iig_checklist` convention):

| Codename | Suggested role | Purpose |
|---|---|---|
| `iig_checklist.create_execution` | Doer | Create a new execution |
| `iig_checklist.edit_execution` | Doer | Enter / update draft responses |
| `iig_checklist.submit_execution` | Doer | Submit for review |
| `iig_checklist.review_execution` | Reviewer | Review, return |
| `iig_checklist.approve_execution` | VP | Approve, reject |
| `iig_checklist.cancel_execution` | Doer (own) | Cancel a draft |
| `iig_checklist.supersede_execution` | VP | Supersede an approved |
| `iig_checklist.view_execution` | all | View executions |

These are additive to the existing 4D-1 `ROLE_PERMISSIONS`. No
built-in role entry is changed; only new codenames are added. The
`can_mutate_definition_scope()` function is **not** involved — executions
are always tenant-scoped (a tenant runs a checklist against their own
formulation version), never platform-master.

### 10b. Execution-scope isolation

A tenant's executions are never visible to another tenant. The
execution manager follows the same pattern as `ChecklistDefinitionManager`
but simpler: `visible_to(tenant)` filters by `tenant` FK directly,
with no platform-master dual-filter needed.

`ChecklistVersion` used in an execution may be `platform_master` —
that is expected and correct (platform definitions are the authoritative
checklists). The execution's *responses* are tenant-scoped regardless
of the definition's scope.

### 10c. Platform-master mutation does not change

Creating or responding to an execution does not mutate
`ChecklistDefinition`, `ChecklistVersion`, or any of their children. No
new `can_mutate_definition_scope()` check is needed for execution-path
operations. The boundary from 4D-1 is unchanged.

---

## 11. Tenant isolation model

- `ChecklistExecution.tenant` FK: every execution is unambiguously
  owned by exactly one tenant.
- `ChecklistExecution` manager: `visible_to(tenant)` filters by
  `tenant`. No `platform_master` dual-filter.
- `ChecklistResponse`: no direct `tenant` FK. Isolated through its
  `execution` FK — all queries must go through
  `ChecklistExecution.objects.visible_to(tenant)` first.
- `CalculationOutcome`: no `tenant` FK. Isolated through the
  `ChecklistResponse → ChecklistExecution → tenant` chain.
- Generic 404 (never 403) when a tenant attempts to reach another
  tenant's execution — same convention established in 4D-1.
- Cross-tenant execution is not a concept — a formulation version
  and an execution always belong to the same tenant.

---

## 12. Design decisions — all resolved

All nine design questions (7 original + 2 new from design review) are
formally resolved. See `docs/MILESTONE_4D_2_DESIGN_REMEDIATION.md`
for full rationale and corrections.

| # | Question | Decision | DR ref |
|---|---|---|---|
| Q1 | FormulationVersion: live FK vs. UUID | **Live FK with PROTECT** | DR-2-03 |
| Q2 | Execution uniqueness constraint | **One non-terminal per (tenant, version, formulation)** | DR-2-04 |
| Q3 | Completeness gate timing | **Both submit_review AND approve** | DR-2-05 |
| Q4 | Document deletion protection | **DeletionProtectionRegistry hook (Option B)** | DR-2-06 |
| Q5 | reviewer_conclusion_note timing | **Required in approve request body** | DR-2-07 |
| Q6 | Response pre-creation | **Eager, applicability-filtered** | DR-2-08 |
| Q7 | CalculationOutcome in 4D-2 | **Model + DATA_REQUIRED placeholders** | DR-2-09 |
| Q8 | FormulationVersion status requirement | **Must be approved** | DR-2-10 |
| Q9 | Applicability freeze mechanism | **Implicit via 4D-1 immutability** | DR-2-11 |

**No open questions remain. Implementation specification may be finalized
after independent human review.**

---

## 13. Audit model

New event types, extending `IigChecklistEvent` in `iig_checklist/audit.py`:

```
iig_checklist.execution.created
iig_checklist.execution.submitted_for_review
iig_checklist.execution.returned
iig_checklist.execution.approved
iig_checklist.execution.rejected
iig_checklist.execution.cancelled
iig_checklist.execution.superseded
iig_checklist.response.entered
iig_checklist.response.updated
checklist_response.reviewer_conclusion_entered
checklist_response.reviewer_conclusion_updated
```

Payload for lifecycle events: execution `public_id`, actor, before/after
status, `tenant_id`. Never: formulation content, question text, raw
answer values, numeric PKs, storage paths, or proprietary regulatory content.

**response.entered vs response.updated distinction — RESOLVED (DR-2-13):**
- `iig_checklist.response.entered`: emitted when a null/unanswered response
  (`entered_by` was previously null) receives a value for the first time.
- `iig_checklist.response.updated`: emitted when an already-answered response
  (non-null `raw_value` or `is_not_applicable=True` already set) has its
  value changed.

Payload for both response events: `execution_public_id`, `response_public_id`,
`question_public_id`, `data_source_type_snapshot`. Never: `raw_value`,
question text, formulation data, numeric PKs.

No success event is emitted on a denied, illegal-transition, or
validation-failed operation — same rule enforced throughout 4D-1.

---

## 14. API surface options

Proposed endpoints, all under `/api/regx/v1/`:

```
POST   iig-checklists/executions/
GET    iig-checklists/executions/
GET    iig-checklists/executions/<uuid>/
POST   iig-checklists/executions/<uuid>/submit-review/
POST   iig-checklists/executions/<uuid>/approve/
POST   iig-checklists/executions/<uuid>/return/
POST   iig-checklists/executions/<uuid>/reject/
POST   iig-checklists/executions/<uuid>/cancel/
POST   iig-checklists/executions/<uuid>/supersede/

GET    iig-checklists/executions/<uuid>/responses/
POST   iig-checklists/executions/<uuid>/responses/<uuid>/
PATCH  iig-checklists/executions/<uuid>/responses/<uuid>/
POST   iig-checklists/executions/<uuid>/responses/<uuid>/reviewer-conclusion/
```

Conventions inherited from 4D-1:
- UUID-only request/response identifiers — no numeric PKs.
- Generic 404 (never "not found vs. not authorized" distinction to
  a probing client).
- Structured `{"error_code": ..., "detail": ...}` on 400/409.
- `status` never patchable through the generic PATCH endpoint — only
  through dedicated lifecycle-action endpoints.
- Bounded pagination on list endpoints.
- Tenant context required for every endpoint.

Mass-assignment guard: `status`, `approved_by`, `approved_at`,
`submitted_by`, `submitted_at`, and all provenance fields are never
accepted as client-supplied fields in any serializer — only lifecycle
action endpoints may set them, and only through the transition service.

---

## 15. Frontend boundary for 4D-2

4D-2 frontend scope is minimal by design. The question-by-question
response entry UI (the full checklist execution screen) is 4D-3/4D-4
scope because it requires auto-population and calculation display.

4D-2 frontend:
- Execution list: list a tenant's executions with status, version
  reference, formulation version reference, created date.
- Execution create: select an active `ChecklistVersion` and a
  `FormulationVersion`, create an execution. No auto-population in
  4D-2 (blank responses only).
- Execution detail: read-only header — status, version, formulation
  version, provenance fields. Lifecycle action buttons for status-
  appropriate transitions (submit, cancel, supersede). Return-reason
  input when returning.
- No per-question response entry UI in 4D-2 (deferred to 4D-3).

Same frontend conventions as 4D-1: inline styles, `apiRequest` wrapper,
safe 401/403 handling (inline error, no optimistic status change, server
is authoritative).

---

## 16. Migration considerations

- One new migration: `backend/iig_checklist/migrations/0002_execution.py`.
- Three new tables: `iig_checklist_checklistexecution`,
  `iig_checklist_checklistresponse`, `iig_checklist_calculationoutcome`.
- DB constraints: `unique_response_per_question_per_execution`,
  uniqueness constraint on non-terminal executions per version/formulation
  (partial, if Q2 Option B is chosen), expiry/effective date check
  (not applicable to executions).
- No changes to 4D-1 migration `0001_initial.py`.
- Migration drift check (part of Backend CI): `python manage.py
  migrate --check` must pass after adding `0002_execution.py`.

---

## 17. Concurrency risks

**Lock ordering at execution creation — RESOLVED (DR-2-16):**
To prevent deadlocks, `create_execution()` acquires locks in this order:

```
transaction.atomic():
  1. select_for_update() on ChecklistVersion — confirms status == active
  2. select_for_update() on any existing non-terminal execution for this
     (tenant, version, formulation) combination
  3. Create execution + eager responses + DATA_REQUIRED CalculationOutcome rows
```

Taking the `ChecklistVersion` lock first is safe: no other operation
holds an execution lock then a version lock. This ordering avoids the
AB/BA deadlock pattern.

**Concurrent `approve` on the same execution:** two actors attempt
`approve` simultaneously. Mitigation: `select_for_update()` on
`ChecklistExecution` inside `transaction.atomic()` before reading and
writing status — same pattern as 4D-1's `_ChecklistVersionActionViewBase`.

**Concurrent response creation (eager rows):** with eager pre-creation,
all response rows exist before any user can enter a value. "First
answer" is a single-row update, not an insert — no concurrent
create race for the same row. The `unique_response_per_question_per_execution`
constraint remains a backstop for any gap in that reasoning; catch
`IntegrityError` → structured 409.

---

## 18. Security and data-integrity risks

**Unbounded payload fields — RESOLVED (DR-2-01).** All four
previously-unbounded fields now have explicit limits defined in
`execution_constants.py`. Serializer validates before any DB write;
model `clean()` validates as a second layer. `error_code =
"payload_too_large"` on violation. No silent truncation.

**Mass-assignment of status fields.** Mitigated by never including
`status`, `approved_by`, or any provenance field in any serializer's
writable field list.

**Response mutation after approval.** The `ChecklistResponse.clean()`
guard must be called via `full_clean()` at every save path — not left
as an unreachable guard the way `AssessmentSnapshot.clean()` currently
is. This is a required implementation-phase acceptance criterion.

**Cross-tenant execution access.** Mitigated by `visible_to(tenant)`
manager on every queryset, generic 404, and no cross-tenant execution
concept.

**Unsafe `raw_value` JSON.** `raw_value` is stored server-side and
serialized; it is never executed or evaluated. The risk is an
injection attack in a downstream consumer that naively renders the
value (CSV injection, HTML injection). Mitigated by: serializer
validates shape against `answer_type`; export (4D-4) must pass values
through the CSV-safety helper already in `common`.

**`CalculationOutcome` forgery.** A client cannot submit a
`CalculationOutcome` directly — the model exists in 4D-2 and is
populated server-side at execution creation with `status = DATA_REQUIRED`.
4D-3 populates actual values. No client-facing endpoint accepts
`CalculationOutcome` input.

**`CalculationOutcome` cascade and retention — RESOLVED (DR-2-02).**
`CalculationOutcome.response` uses `on_delete=CASCADE` because an
orphaned outcome (from a deleted response) would be meaningless. However,
`ChecklistResponse` has **no delete endpoint** — deletion is impossible
via the API. Once an execution leaves `draft` (after `submit_review`),
service-layer enforcement blocks any response deletion attempt with
`error_code = "response_delete_forbidden"`. Abandoned `draft` executions
may be `cancelled` (lifecycle action); this does not delete any rows.

**`DocumentVersion` reference validation.** If `raw_value` stores a
`document_version_public_id`, the serializer must verify the referenced
`DocumentVersion` belongs to the same tenant before accepting it —
never trust a client-supplied UUID as self-evidently authorized.

---

## 19. Test strategy

Follows the same layered approach as `docs/MILESTONE_4D_1_TEST_STRATEGY.md`.

**Unit / model tests (`test_execution_models.py`):**
- `ChecklistExecution.clean()` immutability guards (post-approved).
- `ChecklistResponse.clean()` immutability once execution is `approved`
  (the `full_clean()` enforcement requirement).
- `CalculationOutcome` field constraints.
- `unique_response_per_question_per_execution` constraint.

**Lifecycle tests (`test_execution_lifecycle.py`):**
- Full 6-action transition table: legal transitions and every illegal
  transition returns the correct structured error with no DB write
  and no audit event.
- Self-approval blocked.
- Terminal states (`rejected`, `cancelled`, `superseded`) cannot
  transition.
- `approve` completeness pre-condition (Q3 resolution).
- Concurrent `approve` test using real threads and `transaction=True`.

**API tests (`test_execution_api.py`):**
- UUID-only responses, generic 404, tenant isolation (Tenant A cannot
  reach Tenant B's execution — 404, not 403).
- Mass-assignment guard (status not patchable via PATCH).
- Lifecycle action endpoints return structured 400 on illegal transition.
- `reviewer_conclusion_note` enforcement at `approve`.

**Response tests (`test_response_api.py`):**
- Response enter/update for each `answer_type` shape.
- `is_not_applicable` accepted; `raw_value` rejected when
  `is_not_applicable = True`.
- `REVIEWER_CONFIRMED` response blocks submit when `confirmed_by` unset.
- Mutation rejected once execution is `approved`.

**Reviewer-conclusion tests (`test_reviewer_conclusion_api.py`):**
- Authorized reviewer enters `reviewer_conclusion` during
  `submitted_for_review` → accepted; `entered_by` and `entered_at`
  populated; `response.version` increments.
- Reviewer cannot enter during `draft` or `returned` → 409
  (`reviewer_conclusion_invalid_state`).
- Actor without `PERM_REVIEW_EXECUTION` cannot enter → 403
  (`reviewer_conclusion_permission_denied`).
- Wrong `answer_type` (non-`reviewer_conclusion`) → 400
  (`reviewer_conclusion_wrong_answer_type`).
- Cross-tenant execution or response → generic 404 (not 403).
- `data_source_type_snapshot` retained on response row after entry.
- Second update without `correction_reason` → 400
  (`reviewer_conclusion_correction_reason_required`).
- Second update with `correction_reason` → accepted; prior value and
  new value retained in `ChecklistResponseHistory` (created inside same
  transaction, after version check); `prior_version` and `new_version`
  accurate; `response.version` increments (DR-2-27, DR-2-30).
- Stale `expected_version` → 409 (`reviewer_conclusion_stale_version`);
  zero `ChecklistResponseHistory` rows created (DR-2-27).
- Raw_value exactly 4 000 chars → accepted; 4 001 chars →
  `reviewer_conclusion_too_long` / 400 (DR-2-29).
- `GET responses/<uuid>/` returns `version` field; initial value 1;
  increments to 2 after first entry (DR-2-28).
- `PATCH responses/<uuid>/` with `{"version": 99}` → structured 400
  (version not writable) (DR-2-28).
- No audit event emitted on failure path.
- `checklist_response.reviewer_conclusion_entered` emitted on first value.
- `checklist_response.reviewer_conclusion_updated` emitted on amendment.
- Conclusion is immutable once execution is `approved` → 409
  (`reviewer_conclusion_immutable`); no history row; no audit event.
- Conclusion is immutable once execution is `superseded` → 409
  (`reviewer_conclusion_immutable`) (DR-2-33).
- Execution `returned`: existing conclusion retained; write attempt →
  `reviewer_conclusion_invalid_state` / 409; value unchanged (DR-2-33).
- Execution resubmitted after return: reviewer may amend with
  `correction_reason`; `ChecklistResponseHistory` row created; prior
  value from before resubmission captured (DR-2-33).
- `ChecklistResponseHistory` instance `.delete()` raises
  `GovernedHistoryMutationForbidden` (DR-2-30).
- `ChecklistResponseHistory.objects.filter(...).delete()` raises
  `GovernedHistoryMutationForbidden` (DR-2-30).
- `ChecklistResponse` with history cannot be deleted (PROTECT raises) (DR-2-30).
- No automated regulatory conclusion is produced.
- Ordinary `PATCH responses/<uuid>/` endpoint with `reviewer_conclusion`
  `raw_value` → 400 (`reviewer_conclusion_wrong_answer_type`).

**Platform authorization tests:** execution endpoints never touch
`can_author_platform_master()` or `can_mutate_definition_scope()` —
executions are always tenant-scoped. A test must pin that
`can_mutate_definition_scope()` is never called in the execution path.

**Docker integration:** extend `.github/workflows/docker-integration.yml`
with an "IIG checklist execution foundation flow" covering: create
execution, enter responses, submit for review, approve, verify
immutability post-approve, verify audit trail.

---

## 20. Exclusions

The following are explicitly out of scope for 4D-2 and must not appear
in any 4D-2 implementation branch:

- `FDA_DERIVED_DEFAULT` auto-population (4D-3).
- `SYSTEM_CALCULATED` computation and recalculation (4D-3).
- Override/deviation workflow (4D-4).
- Reviewer conclusion enforcement is **included in 4D-2 scope** (Q5
  resolved by DR-2-07): `reviewer_conclusion_note` is required in the
  `approve` request body, validated by `ApproveSerializer`, and stored
  atomically with the status transition. Override/deviation workflow and
  final regulatory-conclusion automation remain deferred to 4D-4.
- Controlled JSON/CSV export (4D-4).
- PDF/Word export (explicitly deferred beyond 4D per approved design).
- Real regulatory checklist content.
- Production FDA data ingestion.
- Production client formulation data.
- Automatic safety or regulatory-approval conclusions.
- `templates_registry` CSV-safety helper promotion (4D-4, when exports
  are implemented).
- Any change to 4D-1 models (`ChecklistDefinition`, `ChecklistVersion`,
  `ChecklistSection`, `ChecklistQuestion`, `ApplicabilityRule`).
- Any change to `fda_data`, `formulations`, `iid_assessment`,
  `documents`, `templates_registry`, `identity`, `tenancy`,
  `authorization`, `common`, or `audit` models beyond what is
  strictly necessary for `iig_checklist` to reference them.

---

## 21. Gate status

**Design review: COMPLETE. All findings CLOSED. No Critical or Major findings remain.**

4D-2 is structurally well-contained: three new models in an existing
app, one new migration, one new transition table, a small set of new
API endpoints, a minimal frontend, and a focused test suite.

All nine design questions are formally resolved (§12). Payload limits
are defined. Canonical response shapes are specified. Retention and
deletion semantics are explicit. Lock ordering is specified. FormulationVersion
status requirement is documented. Applicability freeze is confirmed as
implicit.

The implementation specification outline (`MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md`)
may be promoted to a final implementation specification after:
1. A human reviewer with domain authority reviews both this document
   and the spec outline with all DR corrections applied.
2. The final specification is formally approved.
3. A 4D-2 feature branch (`regx/feat/milestone-4d-2-execution-foundation`)
   is created from `regx-main`.

**Ready for independent design review: YES**
**Ready to finalize implementation specification: YES (pending human review)**
**Ready to implement: NO**
