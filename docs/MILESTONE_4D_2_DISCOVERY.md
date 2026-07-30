# Milestone 4D-2 Discovery — Checklist Execution, Response and Immutable Snapshot Foundation

**Status: DISCOVERY ONLY. No product code. Not approved for implementation.**

**Branch:** `regx/design/milestone-4d-2-discovery`
**Base SHA:** `453974a4cd40501479730a524fd1b6671a96d6fc` (Milestone 4D-1 merge)

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
via its `public_id` (UUID field, not a live FK, following the
`AssessmentSnapshot` pattern) or a live FK with `on_delete=PROTECT`.
This is the primary **open design question** — see §12.

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
  formulation_version_public_id   UUID (not a live FK — see §12 open Q1)
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

### 6b. `approve` pre-conditions (open)

The approved design states that `approve` requires every `required`
question to have a non-null response or a valid `NOT_APPLICABLE`
resolution, and every `REVIEWER_CONFIRMED` question to have
`confirmed_by` set. Whether completeness is enforced as a pre-condition
to `submit_review` (strict gate), to `approve` only (permissive draft),
or as both (redundant safety net) is an **OPEN QUESTION** — see §12 Q3.

### 6c. Recalculation semantics (approved)

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

**Snapshot option A (UUID-reference pattern):**
`formulation_version_public_id` stored as a UUID field (not a live FK),
following `AssessmentSnapshot`'s own pattern. This means a formulation
version deletion cannot cascade into executions, but the reference
becomes a dangling UUID if the formulation version is deleted. Given
`FormulationVersion` is `on_delete=PROTECT` everywhere a child model
references it, this is a theoretical risk not a practical one.

**Snapshot option B (live FK + PROTECT):**
`formulation_version` as a live `FK(on_delete=PROTECT)`. Deletion
blocked. Simpler to query. Import linter allows `iig_checklist` to
import from `formulations`.

Recommendation: **Option B** (live FK). The `PROTECT` constraint is
consistent with how `ChecklistVersion.definition` is structured, and it
is cleaner than a dangling UUID. The `AssessmentSnapshot` UUID-reference
pattern was chosen to avoid a Django cross-app FK at a time when
`iid_assessment` and `formulations` import boundaries were less settled;
`iig_checklist` → `formulations` is already an approved import-linter
direction.

---

## 8. Response storage options

**`raw_value` as `JSONField`** — typed by `answer_type` but stored as
opaque JSON. The shape varies: `{"value": 500.0}` for `decimal`,
`{"selected": ["option_a"]}` for `multi_select`, `{"document_version_public_id": "..."}` for `attachment_reference`.

Option A: single `raw_value` JSONField with no server-side schema.
Risk: no structural validation at the DB layer; downstream consumers
must handle arbitrary shapes. Mitigated by serializer-level validation
against the question's `answer_type`.

Option B: separate typed columns (`decimal_value`, `text_value`,
`boolean_value`, etc.). Guarantees DB-level type safety, but adds
~10 nullable columns and complicates queries.

Recommendation: **Option A** (single JSONField) with strict
serializer-level validation against `answer_type`. This is the same
approach `CalculationOutcome.inputs` / `input_provenance` already use,
and it is consistent with `ApplicabilityRule.condition_json`. The
open-schema risk is real but bounded: `answer_type` on the question
definition is the schema, and the serializer enforces it at the API
boundary.

The `NOT_APPLICABLE` case does not use `raw_value` at all:
`is_not_applicable = True` and `not_applicable_reason` (a structured
rule identifier, never free text) are the sole storage, leaving
`raw_value` null. This prevents "not applicable" from being represented
as an overloaded blank/null value that could be confused with "not yet
answered."

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

Recommendation: **Option A** with UUID reference in `raw_value` and
documented dependency on the `documents` app's own retention policy.
Per the approved 4D design §15: "an attachment referenced by an
`approved` `ChecklistExecution` is delete-blocked, following the same
'cannot delete something a governed conclusion depends on' pattern
already enforced for approved `SubstanceSynonymMapping` rows." This
means the `documents` app must expose a deletion-protection hook that
`iig_checklist` registers — an open integration point, see §12 Q4.

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

## 12. Open design questions requiring a decision before implementation

The following questions are genuinely unresolved. None is decided
here; each is recorded with competing options and the information
needed to close it. A human decision is required before the
implementation specification can be finalized.

**Q1 — FormulationVersion reference: live FK vs. UUID field?**
Options: live `FK(on_delete=PROTECT)` (simpler, consistent with 4D-1
pattern) or UUID field following `AssessmentSnapshot` (looser coupling).
Recommendation in §7: live FK. Requires confirmation.

**Q2 — Execution uniqueness constraint: how many executions per
(tenant, checklist_version, formulation_version)?**
Option A: unlimited (no constraint). A tenant may run the same
checklist against the same formulation version multiple times, e.g.
to supersede a prior approved execution with an updated one.
Option B: unique non-terminal execution per (tenant, checklist_version,
formulation_version) — only one `draft`/`submitted_for_review`/
`returned` execution at a time; `approved`/`rejected`/`cancelled`/
`superseded` are terminal and exempt. Prevents accidental parallel
drafts but complicates UI if a tenant needs to start a fresh draft
before the prior one reaches a terminal state.
Option C: fully unique — only one execution ever, regardless of
status. Too restrictive; breaks the approved "corrected assessment
always starts a new execution" semantics.
Recommendation: **Option B** — one active (non-terminal) execution
at a time per (tenant, version, formulation_version). Requires a
partial unique constraint. Needs confirmation.

**Q3 — Completeness pre-condition: enforced at `submit_review`, at
`approve`, or both?**
The approved design says `approve` requires completeness. Whether
`submit_review` also requires it (strict — prevents trivially
incomplete drafts from entering the review queue) or allows incomplete
submissions (permissive — lets a reviewer see in-progress work before
all required questions are answered, possibly for an early return) is
unresolved. Recommendation: enforce at `submit_review` only (partial
completeness gates review entry); approval adds a second, final check.
Needs confirmation.

**Q4 — Document deletion protection: how does `iig_checklist` prevent
deletion of a `DocumentVersion` referenced by an approved execution?**
Option A: `iig_checklist` registers a pre-delete signal on
`DocumentVersion` and raises `ProtectedError` if any approved
execution references it. This couples `documents` to `iig_checklist`
via Django signals — an inbound dependency direction the import linter
currently forbids.
Option B: `documents` exposes a deletion-protection hook/registry
that `iig_checklist` registers into, keeping the dependency direction
clean (`iig_checklist` → `documents`, not `documents` → `iig_checklist`).
Option C: `DocumentVersion` live FK with `on_delete=PROTECT` on
`ChecklistResponse`. Requires an explicit FK (not UUID in raw_value).
Recommendation: **Option C** if evidence references are stored as a
structured FK field rather than inside `raw_value`; or **Option B**
if `raw_value` UUID approach is kept. This decision is coupled to the
`raw_value` shape decision (§8). Needs confirmation.

**Q5 — `reviewer_conclusion_note` enforcement: at `submit_review` or
at `approve`?**
The approved design (§13) says it is required at `approve`. Whether
the reviewer who calls `approve` supplies it in the same API call
(field on the action request body) or it must already be set on the
execution record before `approve` is callable, determines the API
shape. Recommendation: supplied in the `approve` action request body
(same pattern as `return` requiring `reason` in the request body),
stored on `ChecklistExecution`. Needs confirmation.

**Q6 — `ChecklistResponse` pre-creation: one row per question created
eagerly at execution creation, or created lazily as answers are
entered?**
Option A (eager): at execution creation, a `ChecklistResponse` row
is created for every question in the pinned `ChecklistVersion`, with
`raw_value = null`. Makes "question not yet answered" explicit and
queryable; simplifies completeness checks.
Option B (lazy): rows are created only when an answer is entered.
"Not yet answered" is inferred by absence. Simpler to write, harder
to query for completeness.
This is a 4D-2 structural choice because it affects the migration
and the API shape even before 4D-3's auto-population pass. Recommendation:
**Option A** (eager). Needs confirmation.

**Q7 — `CalculationOutcome` in 4D-2 scope?**
The model must exist for 4D-3 (calculation population) to build on.
If 4D-2 creates `ChecklistResponse` rows eagerly (Q6 Option A), it
must also create `CalculationOutcome` rows for `SYSTEM_CALCULATED`
questions — but with `status = DATA_REQUIRED` (no inputs yet). If
responses are created lazily, `CalculationOutcome` rows are not created
until 4D-3. Recommendation: include `CalculationOutcome` model and
migration in 4D-2 but leave all rows unpopulated until 4D-3.
Needs confirmation.

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
```

Every event payload: execution `public_id`, actor, before/after status
(lifecycle events), `tenant_id`. Never: formulation content, question
text, raw answer values, numeric PKs, storage paths, or proprietary
regulatory content. Consistent with the audit safety bar established
in 4D-1.

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

**Concurrent `approve` on the same execution:** two actors attempt
`approve` simultaneously. Mitigation: `select_for_update()` on
`ChecklistExecution` inside `transaction.atomic()` before reading and
writing status — same pattern as 4D-1's `_ChecklistVersionActionViewBase`.

**Concurrent response creation (eager Q6 Option A):** two actors both
try to create the initial response for the same question.
`unique_response_per_question_per_execution` `UniqueConstraint` is the
backstop; the service must catch `IntegrityError` and return a
structured 409, never a raw DB exception.

**`ChecklistVersion` activation while an execution is being created:**
the execution creation service must hold a `select_for_update()` on
the `ChecklistVersion` row while verifying `status == active` and
creating the execution, or accept a TOCTOU window where the version
is superseded between the check and the FK write. Given version
supersession is a rare, deliberate human action, a TOCTOU window is
acceptable; the `ChecklistVersion.status == active` check is advisory,
not a hard DB constraint on `ChecklistExecution`.

---

## 18. Security and data-integrity risks

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
`CalculationOutcome` directly — the model exists in 4D-2 but is only
populated by the server-side calculation service (4D-3). In 4D-2,
`CalculationOutcome` rows are either absent (lazy Q6 option) or
server-created with `status = DATA_REQUIRED` (eager option). No client-
facing endpoint accepts `CalculationOutcome` input.

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
- Reviewer conclusion required at `approve` — the note field exists in
  4D-2 but the enforcement is 4D-4 scope unless Q5 is resolved as
  4D-2.
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

## 21. Recommendation

4D-2 is structurally well-contained: three new models in an existing
app, one new migration, one new transition table, a small set of new
API endpoints, a minimal frontend, and a focused test suite. The
primary risk is not scope but **design ambiguity in the seven open
questions** — particularly Q2 (uniqueness constraint shape) and Q4
(document deletion protection), which affect the migration schema and
the import boundary respectively. These must be decided before the
implementation specification is finalized.

The implementation specification outline (`MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md`)
should not be treated as authorization for implementation until:
1. All seven open questions in §12 are resolved with explicit decisions.
2. This discovery document passes an independent design review with no
   Critical or Major findings.
3. A focused specification-review pass (equivalent to the one performed
   for 4D-1) confirms the implementation spec is sufficient.
