# Milestone 4D-2 Design Remediation

**Status: DESIGN REVIEW COMPLETE. Not implementation authorization.**

**Branch:** `regx/design/milestone-4d-2-discovery`
**Review target:** `docs/MILESTONE_4D_2_DISCOVERY.md` + `docs/MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md`
**Review against:** `docs/MILESTONE_4D_DISCOVERY.md`, `docs/MILESTONE_4D_DESIGN_REMEDIATION.md`,
`docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md`, `docs/MILESTONE_4D_1_SPEC_REMEDIATION.md`,
`docs/MILESTONE_4D_1_IMPLEMENTATION.md`, `docs/MILESTONE_4D_1_TEST_STRATEGY.md`

This document records every finding from the independent design review,
the approved resolution for each, exact corrections applied to the
discovery and specification-outline documents, and the final gate
status. Format follows `docs/MILESTONE_4D_DESIGN_REMEDIATION.md`
exactly.

---

## Pre-review verification

- Branch: `regx/design/milestone-4d-2-discovery` ✓
- Local and remote HEAD: `e5683d6` ✓
- Base: `regx-main` at `453974a4cd40501479730a524fd1b6671a96d6fc` ✓
- Files differing from `regx-main`: exactly two documentation files ✓
- Working tree: clean ✓
- Legacy `main`: unchanged ✓
- PR: open, draft ✓

---

## Findings register

### DR-2-01 — MAJOR — Unbounded payload fields

**Status: CLOSED**

**Finding:** Four fields in the proposed model design have no explicit
maximum size, byte limit, or character limit:
- `ChecklistResponse.raw_value` (JSONField)
- `ChecklistExecution.return_reason` (TextField)
- `ChecklistExecution.reviewer_conclusion_note` (TextField)
- `ChecklistResponse.not_applicable_reason` (CharField)

Without explicit limits, oversized payloads can be accepted silently,
cause unexpected DB truncation (PostgreSQL TEXT is unbounded but
application expectations may not be), produce OOM in JSON
deserialization, or bypass response-size SLOs.

The approved 4D-1 codebase sets precedent:
`applicability.py` defines `MAX_PAYLOAD_BYTES = 8192`,
`MAX_CONDITION_COUNT = 50`, `MAX_RECURSION_DEPTH = 5`.

**Resolution (APPROVED):**

Define the following constants in
`backend/iig_checklist/execution_constants.py` (new file, analogous
to `applicability.py`'s module-level constants):

```python
# raw_value field limits
MAX_RAW_VALUE_BYTES    = 16_384   # 16 KB; covers multi-select arrays and text fields
MAX_SELECT_OPTIONS     = 64       # maximum items in any multi_select answer
MAX_FREE_TEXT_CHARS    = 4_000    # free-text answer_type (matches textarea UX cap)

# Execution metadata limits
MAX_RETURN_REASON_CHARS        = 2_000
MAX_REVIEWER_CONCLUSION_CHARS  = 4_000

# Not-applicable reason is a structured rule ID — keep it short
MAX_NOT_APPLICABLE_REASON_CHARS = 200
```

Enforcement:
1. **Serializer layer** — validate before any DB write; return
   `error_code = "payload_too_large"` / HTTP 400. No silent truncation.
2. **Model layer** — `max_length=` on `CharField` fields;
   `ChecklistResponse.clean()` checks `len(json.dumps(self.raw_value))`
   against `MAX_RAW_VALUE_BYTES` and raises `ValidationError` with
   `error_code = "raw_value_too_large"`.
3. **Tests** — one dedicated test per limit verifying that exactly-at-
   limit is accepted and exactly-over-limit is rejected with the
   structured error (not a raw Django validation error).

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §18` — added payload-limit section.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §3` — added
  `max_length` annotations to `return_reason` and
  `reviewer_conclusion_note`; `§8.4` — added payload-limit serializer
  validation spec; `§13.1` — added payload-limit unit tests.

---

### DR-2-02 — MINOR — `CalculationOutcome` cascade and retention semantics

**Status: CLOSED**

**Finding:** The original discovery proposed `on_delete=CASCADE` on
`CalculationOutcome.response`. No response-delete endpoint was defined,
making this theoretical. However, the specification was silent on:
(a) whether a `ChecklistResponse` can ever be hard-deleted in any
lifecycle state; (b) whether `CalculationOutcome` rows are retained
after submission; (c) when deletion becomes permanently prohibited.

**Resolution (APPROVED):**

1. `ChecklistResponse` has **no hard-delete endpoint** in 4D-2 or any
   later milestone. Responses are retained for the life of the execution.
2. `CalculationOutcome.response` remains `on_delete=CASCADE` because
   if a `ChecklistResponse` were ever removed (only possible by direct
   DB intervention, not via the API), the orphaned outcome would be
   meaningless. The cascade is documented explicitly in the spec outline.
3. Once an execution leaves `draft` (i.e., after `submit_review`
   succeeds), all `ChecklistResponse` and `CalculationOutcome` rows
   associated with it are **protected from deletion** by service-layer
   enforcement: any attempt to delete a response belonging to a
   non-draft execution raises `ResponseDeleteForbidden` (structured
   400). No delete endpoint is created in 4D-2 — this rule is
   preemptive documentation for future milestones.
4. Abandoned empty `draft` executions (all responses null, never
   submitted) **may** be cancelled by the creating actor via the
   `cancel` lifecycle action. The `cancel` action sets status to
   `cancelled` (terminal); it does not delete any rows. Physical
   deletion of cancelled executions is not supported.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §12` — Q7 resolution updated; §13 added
  retention rule.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §3.2` — added
  explicit cascade note; `§15` — added retention rollback safety entry.

---

### DR-2-03 — MAJOR — Q1: FormulationVersion linkage — RESOLVED

**Status: CLOSED**

**Finding:** Q1 was marked "Recommendation: live FK. Requires confirmation."
This must be formally resolved before an implementation branch opens.

**Resolution (APPROVED — live FK with PROTECT):**

`ChecklistExecution.formulation_version` is a live Django FK to
`formulations.FormulationVersion` with `on_delete=PROTECT`.

Rationale:
- `PROTECT` is consistent with every other governed FK in this
  codebase (`ChecklistVersion.definition`, `ChecklistExecution.tenant`,
  etc.). The UUID-reference pattern (`AssessmentSnapshot`) was a
  deliberate choice made when `iid_assessment → formulations` was a
  forbidden import direction; `iig_checklist → formulations` is already
  permitted by the import-linter contract.
- Live FK enables Django ORM joins and the `select_related()` pattern
  used by every DRF serializer in the repo.
- `FormulationVersion` is immutable once `approved` — the exact rows
  that get linked to an execution are guaranteed never to change their
  content after linkage.
- Cross-tenant protection: `ChecklistExecution.tenant ==
  formulation_version.product_development_record.tenant` must be
  verified in `create_execution()` before the FK is set (not a DB
  constraint — a service-layer guard returning structured 400 with
  `error_code = "formulation_version_tenant_mismatch"` if violated).

Import-linter: add entry to `backend/pyproject.toml` `[forbidden]`
contract confirming `formulations` may NOT import from `iig_checklist`.
The reverse direction (`iig_checklist → formulations`) is already
allowed; no new contract entry is needed for that.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §5` — model field updated to live FK;
  `§7` — snapshot option resolved to Option B; `§12 Q1` — marked CLOSED.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §3.1` — live FK
  confirmed; `§11` — import-linter entry confirmed; `§6.1` — tenant
  ownership check added to service spec.

---

### DR-2-04 — MAJOR — Q2: Execution uniqueness — RESOLVED

**Status: CLOSED**

**Finding:** Q2 was marked "Recommendation: Option B. Needs confirmation."

**Resolution (APPROVED — one non-terminal execution per combination):**

Option B: one non-terminal execution per `(tenant, checklist_version,
formulation_version)` at any time.

Implementation:
```python
UniqueConstraint(
    fields=["tenant", "checklist_version", "formulation_version"],
    condition=~Q(status__in=["rejected", "cancelled", "superseded"]),
    name="unique_active_execution_per_version_formulation",
)
```

`rejected`, `cancelled`, and `superseded` are the terminal statuses;
`draft`, `submitted_for_review`, `returned`, and `approved` are all
non-terminal (an `approved` execution is still "live" — it has not been
superseded yet).

Service behavior on conflict: `create_execution()` must hold
`select_for_update()` on the existing non-terminal execution row (if
any), catch `IntegrityError`, and return
`error_code = "execution_already_active"` / HTTP 409.

Historical retention: terminal executions are retained indefinitely.
A tenant may examine all past executions (including rejected/cancelled)
for a given checklist version + formulation version pair via the list
endpoint with status-filter query parameters.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §5 Constraints`; `§12 Q2` — marked CLOSED.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §3.1` — constraint
  confirmed; `§6.1` — IntegrityError handling; `§14 error taxonomy`.

---

### DR-2-05 — MAJOR — Q3: Completeness pre-condition gate — RESOLVED

**Status: CLOSED**

**Finding:** Q3 was "Recommendation: enforce at `submit_review` only.
Needs confirmation."

**Resolution (APPROVED — enforced at BOTH `submit_review` and `approve`):**

`submit_review` pre-condition (mandatory, structured 400):
- Every `required=True` question has a response with `raw_value` not
  null OR `is_not_applicable=True` with `not_applicable_reason` set.
- Every `REVIEWER_CONFIRMED` question has `confirmed_by` set.

`approve` pre-condition (final safety re-check, structured 400):
- Same completeness check as `submit_review`. This is a redundant
  safety net: if responses were modified between `return` and the
  second `submit_review`, the re-check catches any gap that might
  have been introduced.

Rationale: the approved 4D design (§8c) explicitly states that
`approve` requires completeness AND that `submit_review` should
prevent empty-execution entries into the review queue. Both gates
have distinct purposes — one is a UX protection (no reviewer sees a
blank execution), the other is a regulatory integrity check (no
approved execution has a missing required answer).

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §6b` — resolved; `§12 Q3` — marked CLOSED.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §4.3` — both
  pre-conditions documented; `§6.2` — both enforced in
  `transition_execution()`.

---

### DR-2-06 — MAJOR — Q4: Document deletion protection — RESOLVED

**Status: CLOSED**

**Finding:** Q4 offered three options; Option C (live FK with PROTECT)
was recommended if evidence references are not stored in `raw_value`.
This decision is coupled to the response-storage shape.

**Resolution (APPROVED — UUID reference in `raw_value` + Option B
registry hook):**

Evidence references are stored as `{"document_version_public_id": "<uuid>"}`
inside `raw_value`. A live FK in `ChecklistResponse` to
`DocumentVersion` would require every response row to carry a nullable
FK even when the question is not an attachment type — wasteful and
semantically wrong.

Deletion protection via Option B: the `documents` app exposes a
`DeletionProtectionRegistry` (a simple module-level set of callables).
`iig_checklist.apps.IigChecklistConfig.ready()` registers a callable
that checks whether any `ChecklistResponse` with
`execution__status="approved"` contains the given
`document_version_public_id` in its `raw_value`. If yes, the callable
returns `True` (protected) and the `documents` app's delete service
raises `DocumentVersionDeleteForbidden` before any DB deletion.

This keeps the import direction clean: `documents` holds the registry
and calls registered hooks; `iig_checklist` registers its hook into
`documents` in `AppConfig.ready()` — but `documents` never imports
`iig_checklist`. The hook is a callable the `documents` app calls via
its abstract interface.

Implementation note: the `DeletionProtectionRegistry` and the abstract
hook interface are **4D-2 scope** (the registry must exist for the
hook registration to work). The actual document-delete service in
`documents` that invokes the registry is **existing infrastructure
that must be verified to invoke the registry** — if it does not exist,
adding it is 4D-2 scope too.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §9` — Option B confirmed; `§12 Q4` —
  marked CLOSED.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §1.1` — registry hook
  added to in-scope items; `§3.2` — raw_value shape for evidence
  confirmed; `§6.3` — tenant ownership check for document_version_public_id.

---

### DR-2-07 — MAJOR — Q5: `reviewer_conclusion_note` timing — RESOLVED

**Status: CLOSED**

**Finding:** Q5 was "Recommendation: supplied in `approve` request body.
Needs confirmation."

**Resolution (APPROVED — supplied in `approve` request body):**

`reviewer_conclusion_note` is a required field in the `ApproveSerializer`
(the request body accepted by the `approve` lifecycle action endpoint).
The service stores it on `ChecklistExecution` at the same time the
status transitions to `approved`. It is not a separately settable
field on the execution via PATCH.

This matches the `return` action pattern (return reason required in
the `return` request body), which the 4D-1 reviewer already validated
as the correct UX for lifecycle-action-bound metadata.

`reviewer_conclusion_note` must be non-empty (stripped). An empty
string returns `error_code = "reviewer_conclusion_required"` / 400
before any DB write.

`reviewer_conclusion_note` is subject to `MAX_REVIEWER_CONCLUSION_CHARS`
(DR-2-01 limit).

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §12 Q5` — marked CLOSED.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §4.3`, `§8.5` —
  `ApproveSerializer` confirmed; `§14` — `reviewer_conclusion_required`
  error code added.

---

### DR-2-08 — MAJOR — Q6: Eager vs. lazy response creation — RESOLVED

**Status: CLOSED**

**Finding:** Q6 was "Recommendation: Option A (eager). Needs confirmation."

**Resolution (APPROVED — eager, with applicability filtering):**

At execution creation, a `ChecklistResponse` row is created for every
question in the pinned `ChecklistVersion` **whose applicability rules
evaluate to true against the linked `FormulationVersion`**. Questions
whose applicability rules evaluate to false are not pre-created —
they are ineligible for this execution.

Applicability evaluation at creation time uses the same evaluation
engine as `applicability.py` but against the formulation version's
component attributes rather than a live ingredient lookup (since the
formulation version is already immutable at the time of execution
creation when it is `approved`). If the formulation version is
`draft` or `under_review`, the applicability evaluation still runs
but may be less complete — this is acceptable since executions can
only be created against `approved` formulation versions (see DR-2-09).

`raw_value = null`, `is_not_applicable = False`, `entered_by = null`,
`entered_at = null` for all eagerly created rows. The "not yet
answered" state is the explicit representation of a null `raw_value`
row, not the absence of a row.

Completeness checks query `ChecklistResponse.objects.filter(
execution=execution, raw_value__isnull=True, is_not_applicable=False
)` to find unanswered required questions.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §6b`, `§12 Q6` — resolved; applicability
  evaluation at creation added.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §3.2` — clarified
  eager pre-creation; `§6.1` — applicability-filtered creation.

---

### DR-2-09 — MAJOR — Q7: `CalculationOutcome` model in 4D-2 — RESOLVED

**Status: CLOSED**

**Finding:** Q7 was "Recommendation: include model and migration, rows
unpopulated until 4D-3. Needs confirmation."

**Resolution (APPROVED — model and DATA_REQUIRED placeholders in 4D-2):**

The `CalculationOutcome` model and its migration are included in 4D-2.
At execution creation, for every `SYSTEM_CALCULATED` question whose
applicability rules evaluate to true (same set as DR-2-08), a
`CalculationOutcome` row is created with:
- `status = DATA_REQUIRED` (one of the nine `CalculationStatus` values)
- `value = null`, `inputs = {}`, `input_provenance = {}`
- `generated_at = null`
- `source_assessment_snapshot_public_id = null`

This means 4D-3 can locate all pending calculations by querying
`CalculationOutcome.objects.filter(status="DATA_REQUIRED")` without
needing to re-inspect the question definitions. It also ensures the
`CalculationOutcome` row exists before 4D-3 tries to update it,
avoiding a create-or-update race condition.

No calculation evaluation occurs in 4D-2. `CalculationOutcome` rows
with `status=DATA_REQUIRED` are not displayed as values to the user
— the frontend treats `DATA_REQUIRED` as "pending calculation" and
renders a placeholder indicator.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §12 Q7` — marked CLOSED.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §3.3`, `§6.1` —
  DATA_REQUIRED placeholder creation confirmed.

---

### DR-2-10 — NEW MAJOR — FormulationVersion status requirement for execution creation

**Status: CLOSED**

**Finding (new, not in original discovery):** The discovery document
specified that the `ChecklistVersion` must be `active` at execution
creation but was silent on the required status of `FormulationVersion`.
If a tenant creates an execution against a `draft` formulation version,
the formulation components may be incomplete, making applicability
evaluation unreliable and response provenance meaningless.

**Resolution (APPROVED):**

`create_execution()` requires:
- `ChecklistVersion.status == "active"`
- `FormulationVersion.status == "approved"` (must be immutable;
  `IMMUTABLE_FORMULATION_STATUSES` from `formulations.models`)

If either condition is not met, the service raises:
- `ChecklistVersionNotActive` → `error_code = "checklist_version_not_active"` / 400
- `FormulationVersionNotApproved` → `error_code = "formulation_version_not_approved"` / 400

Rationale: a `draft` or `under_review` formulation version can change
its components between execution creation and execution submission,
invalidating any applicability-evaluated response set. An `approved`
formulation version is immutable by `IMMUTABLE_FORMULATION_STATUSES`
enforcement — its components are stable for the execution lifetime.
`superseded` and `retired` versions are also immutable but represent
outdated formulations — a new execution against a superseded version
should be blocked with a specific error to prompt the user to use the
current approved version.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §6` — added formulation version status
  requirement; `§18` — added formulation-status mismatch as a
  security/integrity risk.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §6.1` — added
  `FormulationVersion.status == approved` check; `§14` — added
  `formulation_version_not_approved` error code.

---

### DR-2-11 — NEW MAJOR — Snapshot: applicability rules must be frozen at creation

**Status: CLOSED**

**Finding (new):** The discovery document described `ChecklistVersion`
as the frozen anchor and noted that responses are pre-created using
applicability evaluation. It did not specify whether the applicability
evaluation result itself is stored — i.e., whether a later change to
an `ApplicabilityRule` (which cannot happen once a version is `active`,
per 4D-1 immutability enforcement) could affect which questions appear
in an existing execution.

**Resolution (APPROVED — implicit freeze by 4D-1 immutability):**

This is already correct by construction. 4D-1 enforces that
`ApplicabilityRule` rows are immutable once the `ChecklistVersion`
leaves `draft`/`returned`. Since an execution can only be created
against an `active` ChecklistVersion, all applicability rules for
that version are already immutable when the execution is created.
The "applicability evaluation at creation" in DR-2-08 therefore uses
stable data — no explicit snapshot of applicability rules is needed.

The `ChecklistResponse` rows created at execution creation implicitly
capture the applicability result (a question has a response row ↔
it was applicable at creation time; no row ↔ not applicable). This
is the correct representation — no additional snapshot field is
required.

This finding clarifies a potential ambiguity in the discovery document;
the underlying design is sound.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §7` — added paragraph confirming
  implicit applicability freeze via 4D-1 immutability.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §3.2` — added comment
  confirming implicit freeze.

---

### DR-2-12 — NEW MINOR — Response schema: `raw_value` shapes not fully specified

**Status: CLOSED**

**Finding (new):** The discovery document mentioned that `raw_value`
varies by `answer_type` and gave three examples but did not specify
the canonical shape for all 11 answer types. The spec outline listed
this as a serializer responsibility without providing the shapes.

**Resolution (APPROVED — canonical shapes defined here):**

Canonical `raw_value` JSON shapes by `answer_type`:

| answer_type | canonical `raw_value` shape | notes |
|---|---|---|
| `boolean` | `{"value": true}` or `{"value": false}` | no null |
| `decimal` | `{"value": "123.456", "unit": "mg/day"}` | string for exact precision; unit may be blank |
| `integer` | `{"value": 42}` | integer only, no float |
| `text` | `{"value": "..."}` | max `MAX_FREE_TEXT_CHARS` chars |
| `date` | `{"value": "YYYY-MM-DD"}` | ISO 8601 date string |
| `single_select` | `{"selected": "option_code"}` | must be a valid `QuestionOption.code` |
| `multi_select` | `{"selected": ["code_a", "code_b"]}` | max `MAX_SELECT_OPTIONS` items |
| `attachment_reference` | `{"document_version_public_id": "<uuid>"}` | tenant ownership validated |
| `fda_record_reference` | `{"fda_record_public_id": "<uuid>", "fda_record_type": "substance"}` | read-only reference |
| `formulation_component_reference` | `{"formulation_component_public_id": "<uuid>"}` | tenant ownership validated |
| `system_calculated` | `null` (always null in `raw_value`; value lives in `CalculationOutcome`) | never set by client |

For `NOT_APPLICABLE` responses of any type: `raw_value = null`,
`is_not_applicable = True`, `not_applicable_reason` set.

For "not yet answered" (eager creation): `raw_value = null`,
`is_not_applicable = False`, `entered_by = null`.

These shapes are the sole canonical reference for serializer
validation. Any `raw_value` not matching the schema for its
question's `answer_type` is rejected with
`error_code = "invalid_raw_value_shape"` / 400.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §8` — canonical shapes table added.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §8` — serializer
  section expanded with shapes reference.

---

### DR-2-13 — NEW MINOR — Audit: response-entered vs response-updated distinction

**Status: CLOSED**

**Finding (new):** The discovery proposed two separate event types
(`response.entered`, `response.updated`) but did not define the
semantic difference. With eager row creation, the "first time a value
is set" on a pre-created null row could be treated as either "entered"
or "updated" depending on implementation.

**Resolution (APPROVED):**

- `iig_checklist.response.entered`: emitted when a null `raw_value`
  (unanswered state) is given a value for the first time (i.e.,
  `entered_by` was previously null). This includes the first
  `is_not_applicable=True` transition from the unanswered state.
- `iig_checklist.response.updated`: emitted when an already-answered
  response (non-null `raw_value` or `is_not_applicable=True` already
  set) has its value changed.

Payload for both: `execution_public_id`, `response_public_id`,
`question_public_id`, `data_source_type_snapshot`. Never: the
actual `raw_value`, question text, formulation data, numeric PKs.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §13` — definitions added.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §9.2` — definitions added.

---

### DR-2-14 — NEW OBSERVATION — `reject` transition source states ambiguity

**Status: CLOSED (no change required)**

**Finding (observation):** The approved 4D design transition table
includes `reject` from `{draft, submitted_for_review}`. The discovery
document reproduced this correctly. The `reject` action applied to a
`draft` execution was queried — this is unusual because a reviewer
would not normally see a draft. However, it is correct: a VP may
reject a draft execution as part of a record-clearing workflow (e.g.,
an erroneous execution started against the wrong formulation version
that was never submitted). This is consistent with the approved design
and requires no change.

**Corrections applied:** none.

---

### DR-2-15 — NEW OBSERVATION — Frontend: response entry UI correctly deferred

**Status: CLOSED (confirmed correct)**

**Finding (observation):** The discovery correctly defers per-question
response entry UI to 4D-3 on the grounds that auto-population and
calculation display must co-exist. The execution detail page in 4D-2
is read-only below the header. This is the correct design: a 4D-2
detail page showing only blank responses with no entry capability is
operationally useless — it must wait for 4D-3's population pass to
be meaningful.

**Corrections applied:** none. Added confirmation to §15 of the
discovery document and the frontend boundary section of the spec outline.

---

### DR-2-16 — NEW MINOR — Concurrency: `select_for_update()` scope at execution creation

**Status: CLOSED**

**Finding (new):** DR-2-04 mandated `select_for_update()` on the
existing non-terminal execution row to handle the uniqueness check.
The discovery document proposed `select_for_update()` on the
`ChecklistVersion` row for the `status == active` check. These are
two separate lock targets; the discovery was unclear about the order
and whether both are needed simultaneously.

**Resolution (APPROVED):**

`create_execution()` lock order (deadlock-safe, largest-scope lock
taken first):

```python
with transaction.atomic():
    # 1. Lock the ChecklistVersion row (advisory: confirms still active)
    version = ChecklistVersion.objects.select_for_update().get(
        public_id=checklist_version_public_id
    )
    if version.status != "active":
        raise ChecklistVersionNotActive(...)

    # 2. Lock any existing non-terminal execution for this combination
    #    (prevents parallel create racing past the uniqueness check)
    existing = ChecklistExecution.objects.select_for_update().filter(
        tenant=tenant,
        checklist_version=version,
        formulation_version=formulation_version,
    ).exclude(status__in=TERMINAL_EXECUTION_STATUSES).first()
    if existing:
        raise ExecutionAlreadyActive(...)

    # 3. Create execution + eager responses + CalculationOutcome placeholders
    ...
```

Taking the `ChecklistVersion` lock first is safe because no other
operation holds the execution lock first then the version lock
(lifecycle transition operations lock the execution only). This
ordering avoids the AB/BA deadlock pattern.

**Corrections applied:**
- `MILESTONE_4D_2_DISCOVERY.md §17` — updated concurrency section
  with lock ordering.
- `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md §6.1` — lock
  ordering confirmed.

---

## Decision register

| # | Question | Decision | Status |
|---|---|---|---|
| Q1 | FormulationVersion: live FK vs. UUID | **Live FK with PROTECT** | CLOSED (DR-2-03) |
| Q2 | Execution uniqueness constraint | **One non-terminal per (tenant, version, formulation)** | CLOSED (DR-2-04) |
| Q3 | Completeness gate timing | **Both submit_review AND approve** | CLOSED (DR-2-05) |
| Q4 | Document deletion protection | **Option B — DeletionProtectionRegistry hook** | CLOSED (DR-2-06) |
| Q5 | reviewer_conclusion_note timing | **Required in approve request body** | CLOSED (DR-2-07) |
| Q6 | Response pre-creation | **Eager with applicability filtering** | CLOSED (DR-2-08) |
| Q7 | CalculationOutcome in 4D-2 | **Model + DATA_REQUIRED placeholders** | CLOSED (DR-2-09) |
| Q8 (new) | FormulationVersion status at execution creation | **Must be approved** | CLOSED (DR-2-10) |
| Q9 (new) | Applicability rules freeze mechanism | **Implicit via 4D-1 immutability** | CLOSED (DR-2-11) |

---

## Findings summary

| ID | Severity | Title | Status |
|---|---|---|---|
| DR-2-01 | Major | Unbounded payload fields | CLOSED |
| DR-2-02 | Minor | CalculationOutcome cascade and retention | CLOSED |
| DR-2-03 | Major | Q1 — FormulationVersion linkage | CLOSED |
| DR-2-04 | Major | Q2 — Execution uniqueness | CLOSED |
| DR-2-05 | Major | Q3 — Completeness gate timing | CLOSED |
| DR-2-06 | Major | Q4 — Document deletion protection | CLOSED |
| DR-2-07 | Major | Q5 — reviewer_conclusion_note timing | CLOSED |
| DR-2-08 | Major | Q6 — Eager vs. lazy responses | CLOSED |
| DR-2-09 | Major | Q7 — CalculationOutcome in scope | CLOSED |
| DR-2-10 | Major | FormulationVersion status requirement | CLOSED |
| DR-2-11 | Major | Applicability freeze mechanism | CLOSED |
| DR-2-12 | Minor | raw_value shapes not fully specified | CLOSED |
| DR-2-13 | Minor | response.entered vs .updated distinction | CLOSED |
| DR-2-14 | Observation | reject from draft semantics | CLOSED |
| DR-2-15 | Observation | Frontend response UI deferral | CLOSED |
| DR-2-16 | Minor | select_for_update() scope at creation | CLOSED |

**Critical remaining: 0**
**Major remaining: 0**
**Minor remaining: 0**
**Observations remaining: 0**

---

## Gate status

| Condition | Status |
|---|---|
| All seven original open questions resolved | YES |
| All new design questions resolved | YES |
| No Critical findings remaining | YES |
| No Major findings remaining | YES |
| payload limits defined | YES |
| Canonical response shapes defined | YES |
| Retention semantics explicit | YES |
| Lock ordering specified | YES |
| FormulationVersion status requirement added | YES |
| Applicability freeze clarified | YES |
| Product code changed | NO |
| Migrations added | NO |
| Backend code changed | NO |
| Frontend code changed | NO |
| Docker / CI changed | NO |

**Ready for independent design review:** YES

**Ready to finalize 4D-2 implementation specification:** YES — pending
one final human review of `MILESTONE_4D_2_IMPLEMENTATION_SPEC_OUTLINE.md`
with all DR corrections applied.

**Ready to implement 4D-2:** NO — implementation specification must be
formally approved by a human reviewer with domain authority before a
feature branch opens.

---

## Dependencies on later milestones

| Item | Milestone |
|---|---|
| `FDA_DERIVED_DEFAULT` auto-population | 4D-3 |
| `SYSTEM_CALCULATED` computation (populating DATA_REQUIRED placeholders) | 4D-3 |
| Applicability re-evaluation after formulation component changes | 4D-3 |
| Override/deviation workflow | 4D-4 |
| `reviewer_conclusion_note` enforcement hardening | 4D-4 (if not already enforced in 4D-2) |
| Controlled JSON/CSV export + `_csv_safe_cell()` promotion | 4D-4 |
| Response entry UI (per-question screen) | 4D-3 |
| REVIEWER_CONFIRMED auto-population | 4D-3 |
| Final regulatory checklist content | 4D-4+ |
| Production FDA data ingestion | beyond 4D |
| PDF/Word export | beyond 4D per approved design |
