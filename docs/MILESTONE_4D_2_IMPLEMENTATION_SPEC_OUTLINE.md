# Milestone 4D-2 Implementation Specification Outline

**Status: OUTLINE WITH RESOLVED DESIGN. Not authorized for implementation.**
**Prerequisite:** Independent human review and formal approval required before
this outline is promoted to a final implementation specification and an
implementation branch opens.
**Design review:** `docs/MILESTONE_4D_2_DESIGN_REMEDIATION.md` — all findings CLOSED.

**Branch:** `regx/design/milestone-4d-2-discovery`
**Inputs:** `docs/MILESTONE_4D_2_DISCOVERY.md`, `docs/MILESTONE_4D_DISCOVERY.md`,
`docs/MILESTONE_4D_DESIGN_REMEDIATION.md`

This outline follows the same structure as the 4D-1 implementation
specification. Section numbers are stable for cross-referencing in
design-review comments.

---

## Section 1 — Scope

### 1.1 In scope for 4D-2

- `ChecklistExecution` model, manager, and migration.
- `ChecklistResponse` model with applicability-filtered eager pre-creation
  (DR-2-08: one row per applicable question at execution creation).
- `CalculationOutcome` model with `DATA_REQUIRED` placeholder rows at
  creation (DR-2-09); no calculation population until 4D-3.
- `execution_constants.py` — payload limit constants (DR-2-01).
- `DeletionProtectionRegistry` hook in `documents` app + registration in
  `IigChecklistConfig.ready()` (DR-2-06).
- Execution lifecycle: `execution_transitions.py`, 6 actions, 7 statuses.
- Execution-level permissions (8 new codenames), role assignment,
  `ROLE_PERMISSIONS` extension.
- Execution and response services: `create_execution()`,
  `transition_execution()`, `enter_response()`, `update_response()`.
- Execution and response views, serializers, URL routing.
- Audit: 9 new `IigChecklistEvent` types, `emit()` integration.
- Tenant isolation: `ChecklistExecutionManager.visible_to(tenant)`.
- Import-linter: confirm `formulations` does not import `iig_checklist`.
- Minimal frontend: execution list, create, detail, lifecycle actions.
- Docker integration test step: "IIG checklist execution foundation flow."
- Unit, lifecycle, API, response, tenant-isolation, and payload-limit tests.
- Migration `0002_execution.py` with all constraints.

### 1.2 Out of scope for 4D-2

- `FDA_DERIVED_DEFAULT` auto-population (4D-3).
- `SYSTEM_CALCULATED` computation and recalculation (4D-3).
- Override/deviation workflow (4D-4).
- Controlled exports — JSON, CSV, SHA-256 checksum (4D-4).
- Reviewer conclusion enforcement IS included in 4D-2 scope (Q5
  resolved by DR-2-07). Override/deviation workflow and regulatory
  conclusion automation remain deferred to 4D-4.
- Real regulatory checklist content.
- PDF/Word export (deferred beyond 4D per approved design).
- Any modification to 4D-1 definition-governance models or migrations.
- Promotion of `_csv_safe_cell()` from `templates_registry` to `common`
  (deferred to 4D-4 when exports are implemented).

---

## Section 2 — Prerequisites

Before any 4D-2 implementation branch opens:

1. Independent design review of `MILESTONE_4D_2_DISCOVERY.md` with no
   unresolved Critical or Major findings.
2. Formal resolution of all seven open questions (§12 of the discovery
   document) — written decisions attached to the draft PR that opens
   this discovery branch.
3. This outline converted to a final specification by a human reviewer
   with domain authority.

---

## Section 3 — Data model

### 3.1 `ChecklistExecution`

Inherits `PublicIDModel`, `TimeStampedModel`.

Fields (authoritative list — no field is writable by the client
outside its designated service call):

```
tenant                  FK(Tenant, on_delete=PROTECT)
checklist_version       FK(ChecklistVersion, on_delete=PROTECT)
formulation_version     FK(FormulationVersion, on_delete=PROTECT)  # DR-2-03: live FK confirmed
status                  CharField, choices=ExecutionStatus, default=DRAFT
created_by              FK(User, on_delete=PROTECT)
submitted_by            FK(User, SET_NULL, null=True)
submitted_at            DateTimeField(null=True)
reviewed_by             FK(User, SET_NULL, null=True)
returned_by             FK(User, SET_NULL, null=True)
returned_at             DateTimeField(null=True)
return_reason           TextField(blank=True, max_length=2000)      # DR-2-01
approved_by             FK(User, SET_NULL, null=True)
approved_at             DateTimeField(null=True)
rejected_by             FK(User, SET_NULL, null=True)
rejected_at             DateTimeField(null=True)
cancelled_by            FK(User, SET_NULL, null=True)
cancelled_at            DateTimeField(null=True)
superseded_by           FK("self", SET_NULL, null=True)
reviewer_conclusion_note  TextField(blank=True, max_length=4000)   # DR-2-01; set via approve body
```

DB constraints:
- `unique_active_execution_per_version_formulation`: `UniqueConstraint`
  on `(tenant, checklist_version, formulation_version)` with
  `condition=~Q(status__in=["rejected","cancelled","superseded"])` —
  partial unique index on non-terminal rows (DR-2-04).

### 3.2 `ChecklistResponse`

Inherits `PublicIDModel`, `TimeStampedModel`.

```
execution               FK(ChecklistExecution, on_delete=PROTECT)
question                FK(ChecklistQuestion, on_delete=PROTECT)
data_source_type_snapshot  CharField — frozen copy at creation time
                           (implicit freeze: version already immutable, DR-2-11)
raw_value               JSONField(null=True) — shape varies by answer_type
                         max 16384 bytes serialized (DR-2-01)
is_not_applicable       BooleanField(default=False)
not_applicable_reason   CharField(null=True, blank=True, max_length=200)  # DR-2-01
entered_by              FK(User, SET_NULL, null=True)
entered_at              DateTimeField(null=True)
confirmed_by            FK(User, SET_NULL, null=True)
confirmed_at            DateTimeField(null=True)
override_reason         TextField(blank=True)
system_derived_value    JSONField(null=True)
version                 PositiveIntegerField(default=1)  # incremented
                        # on every raw_value write; used for optimistic
                        # locking in enter_reviewer_conclusion() (DR-2-23)
```

DB constraints:
- `unique_response_per_question_per_execution`:
  `UniqueConstraint(fields=["execution", "question"])`.

`clean()` method — enforces:
- Immutability once `execution.status` is outside `{draft, returned}`.
- `is_not_applicable = True` implies `raw_value` is null.
- `not_applicable_reason` is required when `is_not_applicable = True`.
- `override_reason` is non-empty whenever `system_derived_value` is set.
- `len(json.dumps(self.raw_value)) <= MAX_RAW_VALUE_BYTES` when raw_value
  is not null. (DR-2-01 second-layer enforcement.)

`clean()` must be called via `full_clean()` at every save path.
This is a mandatory acceptance criterion: the `AssessmentSnapshot`
defect (clean() unreachable) must not be repeated.

No delete endpoint is exposed. Once an execution leaves `draft`, the
service layer raises `ResponseDeleteForbidden` on any deletion attempt
(DR-2-02).

### 3.3 `CalculationOutcome`

Inherits `PublicIDModel`, `TimeStampedModel`.

```
response                FK(ChecklistResponse, on_delete=CASCADE)
calculation_name        CharField — one of six exact iid_assessment
                        function names; validated at model level
formula_version         CharField
status                  CharField, choices=CalculationStatus (9 values)
value                   DecimalField(null=True, max_digits=20, decimal_places=10)
unit                    CharField(blank=True)
inputs                  JSONField(default=dict)
input_provenance        JSONField(default=dict)
rounding_rule           CharField(blank=True)
reason_code             CharField(blank=True)
generated_at            DateTimeField(null=True)
source_assessment_snapshot_public_id  UUIDField(null=True)
```

No client-facing write endpoint — only server-side services may
create or update `CalculationOutcome` rows. 4D-2 creates the model
and migration; rows are populated by 4D-3.

### 3.4 `ChecklistResponseHistory`

Inherits `PublicIDModel`, `TimeStampedModel`.

Created by `enter_reviewer_conclusion()` **inside the same transaction,
after the version check passes and after the response row is saved** — one
row per amendment, never on first entry (DR-2-27, DR-2-30). Rows are
governed records and may not be mutated or deleted after creation.

Tenant is derived through `response.execution.tenant`; no direct `tenant` FK.

```
response                FK(ChecklistResponse, on_delete=PROTECT)
                        — PROTECT: a response with history cannot be deleted;
                          no cascade deletion of governed amendment records
prior_raw_value         JSONField(null=True)   — raw_value before amendment
new_raw_value           JSONField(null=True)   — raw_value written by amendment
prior_is_not_applicable BooleanField           — is_not_applicable before amendment
new_is_not_applicable   BooleanField           — is_not_applicable after amendment
prior_not_applicable_reason CharField(null=True) — not_applicable_reason before
new_not_applicable_reason   CharField(null=True) — not_applicable_reason after
prior_entered_by        FK(User, SET_NULL, null=True)
prior_entered_at        DateTimeField(null=True)
prior_version           PositiveIntegerField   — response.version before increment
new_version             PositiveIntegerField   — response.version after increment
correction_reason       TextField()            — required; non-empty
amended_by              FK(User, on_delete=PROTECT)
amended_at              DateTimeField(auto_now_add=True)
source_classification_snapshot  CharField      — frozen copy of
                        response.data_source_type_snapshot at amendment time,
                        so the history row is self-interpreting without a
                        live question lookup
```

**Retention and immutability (DR-2-30):**
- History rows are append-only; no `update()` or `save()` after initial
  creation.
- `ChecklistResponseHistoryManager` (an `ImmutableManager`-style queryset)
  raises `GovernedHistoryMutationForbidden` on `.update()` or
  `.delete()` at the queryset level.
- `ChecklistResponseHistory.delete()` raises
  `GovernedHistoryMutationForbidden` at the model instance level.
- `ChecklistResponse.on_delete=PROTECT` on the history FK ensures no
  cascade deletion occurs. A `ChecklistResponse` with one or more history
  rows cannot be deleted through any path.
- No `bulk_update` on history rows is permitted.
- No client-facing write or delete endpoint exposes these rows.

Read-only endpoint (optional, 4D-2 scope decision): history rows may be
surfaced via `GET responses/<uuid>/history/` requiring `PERM_VIEW_EXECUTION`,
accessed through tenant-scoped retrieval via the parent execution.

---

## Section 4 — Lifecycle

### 4.1 `execution_transitions.py`

Location: `backend/iig_checklist/execution_transitions.py`.

```python
_EXECUTION_TRANSITIONS = {
    "submit_review": (frozenset({"draft", "returned"}), "submitted_for_review"),
    "approve":       (frozenset({"submitted_for_review"}),  "approved"),
    "return":        (frozenset({"submitted_for_review"}),  "returned"),
    "reject":        (frozenset({"draft", "submitted_for_review"}), "rejected"),
    "cancel":        (frozenset({"draft", "returned"}),     "cancelled"),
    "supersede":     (frozenset({"approved"}),              "superseded"),
}

TERMINAL_EXECUTION_STATUSES = frozenset({"rejected", "cancelled", "superseded"})

class IllegalExecutionTransition(ValueError):
    pass

def validate_execution_transition(current_status: str, action: str) -> str:
    ...
```

### 4.2 `ExecutionStatus` enum

```python
class ExecutionStatus(models.TextChoices):
    DRAFT                 = "draft"
    SUBMITTED_FOR_REVIEW  = "submitted_for_review"
    RETURNED              = "returned"
    APPROVED              = "approved"
    REJECTED              = "rejected"
    CANCELLED             = "cancelled"
    SUPERSEDED            = "superseded"
```

### 4.3 Pre-condition checks (per action)

`submit_review` (DR-2-05):
- Every `required=True` question applicable to this execution has a
  response with `raw_value` not null OR `is_not_applicable=True` with
  `not_applicable_reason` set.
- Every `REVIEWER_CONFIRMED` question applicable to this execution has
  `confirmed_by` set.
- Error: `error_code = "incomplete_execution"` / 400.

`approve` (DR-2-05 — redundant safety re-check):
- Same completeness check as `submit_review`.
- `reviewer_conclusion` completeness (DR-2-23): for every `required=True`
  question with `answer_type == reviewer_conclusion` applicable to this
  execution, the response must have a non-null `raw_value` and
  `is_not_applicable=False`. A missing required reviewer conclusion raises
  `error_code = "incomplete_execution"` / 400. This gate does not apply at
  `submit_review` — a reviewer conclusion cannot legally exist before the
  execution reaches `submitted_for_review`.
- `reviewer_conclusion_note` non-empty, provided in the request body
  (DR-2-07: `ApproveSerializer` accepts this field; service stores it on
  `ChecklistExecution` atomically with the status transition).
- Error for completeness: `error_code = "incomplete_execution"` / 400.
- Error for missing note: `error_code = "reviewer_conclusion_required"` / 400.

`return`:
- `return_reason` must be non-empty, provided in the request body,
  max `MAX_RETURN_REASON_CHARS` (DR-2-01).
- Error: `error_code = "missing_return_reason"` / 400.

`approve` self-approval guard:
- Actor who called `submit_review` (i.e., `execution.submitted_by`)
  cannot be the actor who calls `approve`.
- Error: `error_code = "self_approval_forbidden"` / 403.

---

## Section 5 — Permissions

### 5.1 New permission codenames

Add to `backend/iig_checklist/permissions.py`:

```python
PERM_CREATE_EXECUTION    = "iig_checklist.create_execution"
PERM_EDIT_EXECUTION      = "iig_checklist.edit_execution"
PERM_SUBMIT_EXECUTION    = "iig_checklist.submit_execution"
PERM_REVIEW_EXECUTION    = "iig_checklist.review_execution"
PERM_APPROVE_EXECUTION   = "iig_checklist.approve_execution"
PERM_CANCEL_EXECUTION    = "iig_checklist.cancel_execution"
PERM_SUPERSEDE_EXECUTION = "iig_checklist.supersede_execution"
PERM_VIEW_EXECUTION      = "iig_checklist.view_execution"
```

### 5.2 `ROLE_PERMISSIONS` extension

Additive only — no existing 4D-1 role entry is changed:

| Role | New permissions added |
|---|---|
| Doer | create, edit, submit, cancel, view |
| Reviewer | review, view |
| VP | approve, supersede, view |
| Viewer | view |
| Owner | all execution permissions |

`can_author_platform_master()` is **not** involved in execution
operations. `can_mutate_definition_scope()` is **not** called in the
execution path.

### 5.3 Execution-scope tenant isolation

Every execution view begins with:
```python
execution = get_object_or_404(
    ChecklistExecution.objects.visible_to(tenant),
    public_id=uuid
)
```

Generic 404 — not a `PermissionDenied` — when a tenant attempts
to reach another tenant's execution. Same convention as 4D-1.

---

## Section 6 — Services

### 6.1 `create_execution(tenant, checklist_version_public_id, formulation_version_public_id, actor)`

```
1. Resolve ChecklistVersion from public_id.
   Verify status == "active" → else raise ChecklistVersionNotActive / 400.
2. Resolve FormulationVersion, verify status == "approved" (DR-2-10)
   → else raise FormulationVersionNotApproved / 400.
   Verify formulation_version.product_development_record.tenant == tenant
   → else raise FormulationVersionTenantMismatch / 400.
3. Check actor has PERM_CREATE_EXECUTION.
4. Inside transaction.atomic():
   a. select_for_update() on ChecklistVersion (DR-2-16, lock 1).
   b. select_for_update() on any existing non-terminal execution for
      this (tenant, checklist_version, formulation_version) (DR-2-16,
      lock 2). If found → raise ExecutionAlreadyActive / 409.
   c. Create ChecklistExecution(status=DRAFT, created_by=actor, tenant=tenant,
      checklist_version=version, formulation_version=fv).
   d. Evaluate applicability rules for each question in the pinned version
      against the formulation_version (DR-2-08). For applicable questions:
      - Create ChecklistResponse(execution=exec, question=q,
          data_source_type_snapshot=q.data_source_classification,
          raw_value=null, is_not_applicable=False, entered_by=null).
      - If q.data_source_classification == DataSourceClassification.SYSTEM_CALCULATED: create
        CalculationOutcome(response=r, status="DATA_REQUIRED",
          calculation_name=q.bound_calculation_name, ...) (DR-2-09).
   e. Catch IntegrityError → structured 409 (uniqueness race).
5. Emit iig_checklist.execution.created audit event.
6. Return execution.
```

### 6.2 `transition_execution(execution, action, actor, **kwargs)`

```
1. validate_execution_transition(execution.status, action) — raises
   IllegalExecutionTransition on illegal path.
2. Check actor has the action-specific permission.
3. Check action-specific pre-conditions (§4.3).
4. Inside transaction.atomic() + select_for_update() on execution:
   a. Set new status and provenance fields (actor, timestamp, reason).
   b. execution.full_clean() → execution.save().
5. Emit lifecycle audit event.
6. Return execution.
```

### 6.3 `enter_response(execution, question_public_id, actor, raw_value, is_not_applicable, not_applicable_reason)`

**Scope:** applies only to questions whose `answer_type` is **not**
`reviewer_conclusion`. For `reviewer_conclusion` questions, use
`enter_reviewer_conclusion()` (§6.4). If a `reviewer_conclusion` `raw_value`
is passed to this service, step 4 shape-validation rejects it with
`error_code = "reviewer_conclusion_wrong_answer_type"` / 400 before any
DB write. This prevents the ordinary response path from accidentally
accepting reviewer conclusions or operating during `submitted_for_review`.

```
1. Verify execution.status in {draft, returned}.
2. Verify actor has PERM_EDIT_EXECUTION.
3. Resolve ChecklistQuestion, verify it belongs to the pinned
   ChecklistVersion.
4. Validate raw_value shape against question.answer_type (strict;
   unknown shapes → structured 400, no partial acceptance).
5. If is_not_applicable: verify raw_value is null.
6. Resolve or create ChecklistResponse for (execution, question)
   (depending on Q6 resolution — create if lazy, update if eager).
7. response.data_source_type_snapshot = question.data_source_classification.
8. response.full_clean() → response.save().
9. Emit iig_checklist.response.entered or .updated audit event.
10. Return response.
```

### 6.4 `enter_reviewer_conclusion(*, execution, response_public_id, actor, raw_value, expected_version, correction_reason=None)`

**Transaction ordering rule (DR-2-27):** every regulated write — the
`ChecklistResponseHistory` row and the `ChecklistResponse` update — occurs
inside a single `transaction.atomic()` block, after the optimistic-version
check passes. No history row may be created for a failed or racing update.
No audit success event may exist for a failed amendment.

```
Phase A — non-mutating preliminary validation (outside any transaction):

1. Resolve execution via ChecklistExecution.objects.visible_to(tenant)
   — generic 404 if not found or cross-tenant.
2. Verify execution.status == "submitted_for_review"
   → else raise ReviewerConclusionInvalidState /
     error_code = "reviewer_conclusion_invalid_state" / 409.
3. Verify actor has PERM_REVIEW_EXECUTION
   → else raise ReviewerConclusionPermissionDenied /
     error_code = "reviewer_conclusion_permission_denied" / 403.
4. Resolve ChecklistResponse by response_public_id; verify
   response.execution == execution (generic 404 if mismatch).
5. Verify response.question.answer_type == reviewer_conclusion
   → else error_code = "reviewer_conclusion_wrong_answer_type" / 400.
6. Validate raw_value shape and payload limits:
   {"value": "..."} — value must be a non-empty string after trim;
   max MAX_REVIEWER_CONCLUSION_CHARS (4 000) chars; max MAX_RAW_VALUE_BYTES
   bytes total; no additional keys; no arrays or nested objects.
   Error codes: "reviewer_conclusion_empty" / 400 (empty after trim);
   "reviewer_conclusion_too_long" / 400 (exceeds 4 000 char limit);
   "reviewer_conclusion_payload_too_large" / 400 (exceeds byte limit);
   "reviewer_conclusion_invalid_payload" / 400 (wrong shape).
7. If amendment path (response.raw_value is not null):
   a. Verify correction_reason is non-empty
      → else error_code = "reviewer_conclusion_correction_reason_required" / 400.

Phase B — all regulated writes, inside one transaction (DR-2-27):

8. Enter transaction.atomic().
9. select_for_update() on ChecklistExecution (lock order: execution first).
10. select_for_update() on ChecklistResponse (lock order: response second).
11. Re-validate after acquiring locks:
    a. Verify execution.status == "submitted_for_review"
       → else rollback and return reviewer_conclusion_invalid_state / 409.
    b. Verify response still belongs to execution (paranoia guard).
    c. Verify response.question.answer_type == reviewer_conclusion.
    d. Verify response.version == expected_version
       → else rollback and return reviewer_conclusion_stale_version / 409.
       No history row is created. No audit event is emitted.
12. Capture pre-write state for history (in memory, not yet saved):
    is_amendment = (response.raw_value is not null)
    prior_raw_value = response.raw_value
    prior_is_not_applicable = response.is_not_applicable
    prior_not_applicable_reason = response.not_applicable_reason
    prior_entered_by = response.entered_by
    prior_entered_at = response.entered_at
    prior_version = response.version
13. Write response:
    a. Set response.raw_value = raw_value.
    b. Set response.entered_by = actor.
    c. Set response.entered_at = now (UTC).
    d. Ensure response.data_source_type_snapshot is set
       (= response.question.data_source_classification if null).
    e. response.version = prior_version + 1.
    f. response.full_clean() → response.save().
14. If is_amendment: create ChecklistResponseHistory inside this same
    transaction (after version check, after response save):
      ChecklistResponseHistory(
        response=response,
        prior_raw_value=prior_raw_value,
        new_raw_value=raw_value,
        prior_is_not_applicable=prior_is_not_applicable,
        new_is_not_applicable=response.is_not_applicable,
        prior_not_applicable_reason=prior_not_applicable_reason,
        new_not_applicable_reason=response.not_applicable_reason,
        prior_entered_by=prior_entered_by,
        prior_entered_at=prior_entered_at,
        prior_version=prior_version,
        new_version=response.version,
        correction_reason=correction_reason,
        amended_by=actor,
        source_classification_snapshot=response.data_source_type_snapshot,
      ).save()
15. Commit transaction.

Phase C — post-commit:

16. Via transaction.on_commit():
    Emit audit event (only after successful commit):
    - First entry (is_amendment was False): emit
      checklist_response.reviewer_conclusion_entered.
    - Amendment (is_amendment was True): emit
      checklist_response.reviewer_conclusion_updated.
17. Return response.
```

**Invariants enforced by this sequence:**
- A `ChecklistResponseHistory` row never exists for a failed amendment.
- An audit success event never exists for a failed amendment.
- History row and response update succeed or fail atomically.
- No regulated write occurs before the stale-version check at step 11d.
- `response.version` in the history row (`prior_version`/`new_version`)
  accurately reflects the before/after state of that specific amendment.

No direct status mutation occurs. No automated regulatory conclusion is
generated. No override/deviation metadata in 4D-2.

---

## Section 7 — Views and URL routing

### 7.1 Execution views

| Class | Method | URL | Permission check |
|---|---|---|---|
| `ChecklistExecutionListCreateView` | GET, POST | `/api/regx/v1/iig-checklists/executions/` | list: `view_execution`; create: `create_execution` |
| `ChecklistExecutionDetailView` | GET | `/api/regx/v1/iig-checklists/executions/<uuid>/` | `view_execution` |
| `ChecklistExecutionSubmitView` | POST | `.../executions/<uuid>/submit-review/` | `submit_execution` |
| `ChecklistExecutionApproveView` | POST | `.../executions/<uuid>/approve/` | `approve_execution`; `self_approval_forbidden = True` |
| `ChecklistExecutionReturnView` | POST | `.../executions/<uuid>/return/` | `review_execution` |
| `ChecklistExecutionRejectView` | POST | `.../executions/<uuid>/reject/` | `approve_execution` |
| `ChecklistExecutionCancelView` | POST | `.../executions/<uuid>/cancel/` | `cancel_execution` |
| `ChecklistExecutionSupersedeView` | POST | `.../executions/<uuid>/supersede/` | `supersede_execution` |

All lifecycle action views inherit `_ChecklistExecutionActionViewBase`,
mirroring `_ChecklistVersionActionViewBase` from 4D-1. This base class:
- Resolves and verifies tenant.
- Calls `visible_to(tenant)` — generic 404 for cross-tenant access.
- Calls `validate_execution_transition()` — structured 400 on illegal
  transition; no audit event on failure.
- Delegates to `transition_execution()`.
- Emits audit event only on success.

`ChecklistExecutionApproveView.self_approval_forbidden = True` — the
view base class checks `execution.submitted_by == request.user` and
returns a structured 403 with `error_code = "self_approval_forbidden"`.

### 7.2 Response views

| Class | Method | URL | Permission check |
|---|---|---|---|
| `ChecklistResponseListView` | GET | `.../executions/<uuid>/responses/` | `view_execution` |
| `ChecklistResponseUpdateView` | PATCH | `.../executions/<uuid>/responses/<uuid>/` | `edit_execution` |
| `ChecklistReviewerConclusionView` | POST | `.../executions/<uuid>/responses/<uuid>/reviewer-conclusion/` | `review_execution` |

`ChecklistReviewerConclusionView`:
- POST only; resolves execution and response by public UUID via
  tenant-scoped retrieval (generic 404 for cross-tenant).
- Validates request body with `ReviewerConclusionSerializer` (§8.5).
- Invokes `enter_reviewer_conclusion()` (§6.4).
- Server-side `PERM_REVIEW_EXECUTION` check inside the service — not
  solely at the view level.
- Returns the updated `ChecklistResponseSerializer` representation
  (UUID-only; no internal IDs; no storage paths).
- Structured 400/403/409 on all error paths; no raw exception text.

`ChecklistResponseUpdateView` (PATCH) does **not** accept
`reviewer_conclusion` answer types. The serializer (§8.4) rejects any
`reviewer_conclusion` raw_value with
`error_code = "reviewer_conclusion_wrong_answer_type"` / 400.

PATCH only — responses are always created eagerly (pending Q6) or via
a dedicated "enter response" endpoint. `status` is never a writable
field in any response serializer.

### 7.3 URL routing

Add to `backend/iig_checklist/urls.py`:
```python
path("executions/", ChecklistExecutionListCreateView.as_view()),
path("executions/<uuid:public_id>/", ChecklistExecutionDetailView.as_view()),
path("executions/<uuid:public_id>/submit-review/", ChecklistExecutionSubmitView.as_view()),
path("executions/<uuid:public_id>/approve/", ChecklistExecutionApproveView.as_view()),
path("executions/<uuid:public_id>/return/", ChecklistExecutionReturnView.as_view()),
path("executions/<uuid:public_id>/reject/", ChecklistExecutionRejectView.as_view()),
path("executions/<uuid:public_id>/cancel/", ChecklistExecutionCancelView.as_view()),
path("executions/<uuid:public_id>/supersede/", ChecklistExecutionSupersedeView.as_view()),
path("executions/<uuid:public_id>/responses/", ChecklistResponseListView.as_view()),
path("executions/<uuid:public_id>/responses/<uuid:response_public_id>/",
     ChecklistResponseUpdateView.as_view()),
path("executions/<uuid:public_id>/responses/<uuid:response_public_id>/reviewer-conclusion/",
     ChecklistReviewerConclusionView.as_view()),
```

---

## Section 8 — Serializers

### 8.1 `ChecklistExecutionSerializer`

Read-only representation:
```
public_id, status, created_at, updated_at,
checklist_version: {public_id, version_number, status},
formulation_version_public_id (UUID only — from the live FK on the model; Q1 resolved by DR-2-03),
created_by_email, submitted_by_email, submitted_at,
returned_by_email, returned_at, return_reason,
approved_by_email, approved_at,
rejected_by_email, rejected_at,
cancelled_by_email, cancelled_at,
reviewer_conclusion_note
```

Never exposed: tenant_id, internal PKs, storage keys, question text
from the pinned version (fetched separately via the version detail
endpoint), raw calculation inputs.

### 8.2 `ChecklistExecutionCreateSerializer`

Writable fields (client-supplied only):
```
checklist_version_public_id: UUIDField
formulation_version_public_id: UUIDField
```

`status`, all provenance fields, and `tenant` are never accepted from
client input — set only by the service.

### 8.3 `ChecklistResponseSerializer`

Read-only (DR-2-28):
```
public_id, question_public_id, data_source_type_snapshot,
raw_value, is_not_applicable, not_applicable_reason,
entered_by_email, entered_at,
confirmed_by_email, confirmed_at,
override_reason, system_derived_value,
version
```

`version` is a read-only positive integer. Initial value is 1. The server
increments it after each successful write (first entry or amendment). Clients
must echo the latest server-provided `version` value as `expected_version` when
calling the reviewer-conclusion endpoint. `version` cannot be supplied through
`ChecklistResponseUpdateSerializer` or any other writable serializer — any
client-supplied `version` in a non-reviewer-conclusion request body is rejected
with a structured 400. Every successful reviewer-conclusion response body
includes the updated `version`.

### 8.4 `ChecklistResponseUpdateSerializer`

Writable:
```
raw_value: JSONField (nullable)
is_not_applicable: BooleanField
not_applicable_reason: CharField (nullable)
override_reason: TextField (blank)
```

`execution`, `question`, `data_source_type_snapshot`, `confirmed_by`,
`confirmed_at`, `system_derived_value`, and `version` are never
client-writable — all set by the service layer only.

Mass-assignment guard: any unknown field in the request body returns a
structured 400, not silent acceptance.

**`raw_value` shape validation (DR-2-17):** the serializer validates
`raw_value` against the canonical shape for the question's `answer_type`
(all 18 DB values from `enums.py`). Validation rejects:
- a non-null `raw_value` for `calculated_value`, `calculated_status`,
  or `approval_metadata` (client input prohibited);
- a JSON float where a decimal string is required (`decimal`,
  `quantity_with_unit`, `percentage`);
- a Python `bool` value where a JSON integer is required (`integer`) —
  `bool` is an `int` subclass in Python; serializer must check
  `isinstance(val, bool)` and reject **before** `isinstance(val, int)`
  accepts. `{"value": true}` and `{"value": false}` both return
  `error_code = "invalid_raw_value_shape"` (DR-2-24);
- a unit not present in the pinned question's `allowed_units` JSONField
  for `quantity_with_unit` — `allowed_units` is frozen by 4D-1 version
  immutability; validation reads from the resolved question object, not
  a live DB query (DR-2-25); an empty `allowed_units` list is strictly
  invalid — no unit is accepted when the list is empty
  (`invalid_raw_value_shape` / 400); a non-`quantity_with_unit` question
  must have an empty `allowed_units` (DR-2-32);
- a string `"true"`/`"false"` where a JSON boolean is required (`yes_no`);
- a boolean where a controlled string enum is required (`yes_no_na`);
- any `yes_no_na` value outside `{"value": "yes"}`, `{"value": "no"}`,
  `{"value": "not_applicable"}`;
- duplicate option codes in `multi_select`;
- any `reviewer_conclusion` `raw_value` — this answer type must use the
  dedicated `/reviewer-conclusion/` endpoint and `ReviewerConclusionSerializer`
  (§8.5). Return `error_code = "reviewer_conclusion_wrong_answer_type"` / 400
  (DR-2-23).

All validation failures return `error_code = "invalid_raw_value_shape"` /
400 before any DB write.

### 8.5 `ReviewerConclusionSerializer`

Used exclusively by `ChecklistReviewerConclusionView` (§7.2).

Writable fields:
```
raw_value:          JSONField — required; must match reviewer_conclusion
                    canonical shape {"value": "..."}
expected_version:   IntegerField — required; must equal response.version
                    at lock time; stale value → 409
correction_reason:  CharField (optional on first entry; required when
                    response.raw_value is not null)
```

Validation (structural only — object-level permission and lifecycle
checks are enforced in the service, §6.4):
- `raw_value.value` must be a string.
- Trimmed `raw_value.value` must not be empty.
- `raw_value.value` max `MAX_REVIEWER_CONCLUSION_CHARS` (4 000) Unicode
  code points (DR-2-29). Not `MAX_FREE_TEXT_CHARS`.
- `json.dumps(raw_value)` max `MAX_RAW_VALUE_BYTES` bytes.
- No additional keys in `raw_value`.
- Unknown fields in request body → structured 400.
- `correction_reason` is `CharField(max_length=MAX_REVIEWER_CONCLUSION_CHARS,
  blank=True)` — blank is accepted structurally; the service enforces
  non-empty when amendment is detected.

### 8.6 Lifecycle action serializers

Each action has a minimal request-body serializer:

- `ReturnSerializer`: `{return_reason: str}` — required, non-empty,
  max `MAX_RETURN_REASON_CHARS` (DR-2-01).
- `ApproveSerializer`: `{reviewer_conclusion_note: str}` — required,
  non-empty, max `MAX_REVIEWER_CONCLUSION_CHARS` (DR-2-07, DR-2-01).
  Field stored on `ChecklistExecution` atomically with status transition.
- All other actions: empty body accepted; extra fields rejected with 400.

Payload limit serializer validation (DR-2-01): any serializer that
accepts free-text or JSON fields must validate against the constants
in `execution_constants.py` before calling the service layer.
`error_code = "payload_too_large"` / 400 on violation. No silent
truncation at any layer.

---

## Section 9 — Audit

### 9.1 New event types

Add to `IigChecklistEvent` in `backend/iig_checklist/audit.py`:

```python
EXECUTION_CREATED             = "iig_checklist.execution.created"
EXECUTION_SUBMITTED           = "iig_checklist.execution.submitted_for_review"
EXECUTION_RETURNED            = "iig_checklist.execution.returned"
EXECUTION_APPROVED            = "iig_checklist.execution.approved"
EXECUTION_REJECTED            = "iig_checklist.execution.rejected"
EXECUTION_CANCELLED           = "iig_checklist.execution.cancelled"
EXECUTION_SUPERSEDED          = "iig_checklist.execution.superseded"
RESPONSE_ENTERED              = "iig_checklist.response.entered"
RESPONSE_UPDATED              = "iig_checklist.response.updated"
RESPONSE_REVIEWER_CONCLUSION_ENTERED = "checklist_response.reviewer_conclusion_entered"
RESPONSE_REVIEWER_CONCLUSION_UPDATED = "checklist_response.reviewer_conclusion_updated"
```

### 9.2 Payload conventions

All payloads: execution `public_id`, actor email, tenant_id, before/after
status (lifecycle events).

Response events: execution `public_id`, response `public_id`,
`question_public_id`, `data_source_type_snapshot`. Never: `raw_value`
(may contain proprietary formulation data), question text, numeric PKs,
storage paths.

Reviewer-conclusion events (`reviewer_conclusion_entered` /
`reviewer_conclusion_updated`): execution `public_id`, response
`public_id`, question `public_id`, actor email, `prior_response_version`,
`new_response_version`, `execution_status`, and a boolean
`correction_reason_present` (true/false — presence indicator only).
Never: the conclusion text itself, full `raw_value`, prior `raw_value`,
or any regulated conclusion content. Full amendment history lives in
`ChecklistResponseHistory` rows, not reconstructed from audit events.

Emit only on success. No audit event on validation failure, illegal
transition, or authorization denial.

---

## Section 10 — Migration

**Proposed migration plan (DR-2-31). This is a documentation-only outline;
no migration file is created during this design task.**

`backend/iig_checklist/migrations/0002_execution.py`:

```
1. CreateModel ChecklistExecution — all fields from §3.1, including:
   - all provenance FK fields (SET_NULL on User)
   - reviewer_conclusion_note TextField(blank=True, max_length=4000)
   - UniqueConstraint(
       fields=["tenant", "checklist_version", "formulation_version"],
       condition=~Q(status__in=["rejected","cancelled","superseded"]),
       name="unique_active_execution_per_version_formulation"
     )

2. CreateModel ChecklistResponse — all fields from §3.2, including:
   - version = PositiveIntegerField(default=1)       ← DR-2-23/DR-2-28
   - all provenance FK fields (SET_NULL on User)
   - override_reason TextField(blank=True)
   - system_derived_value JSONField(null=True)
   - UniqueConstraint(
       fields=["execution", "question"],
       name="unique_response_per_question_per_execution"
     )

3. CreateModel ChecklistResponseHistory — all fields from §3.4, including:
   ← DR-2-30/DR-2-31
   - response FK(ChecklistResponse, on_delete=PROTECT)
   - prior_raw_value JSONField(null=True)
   - new_raw_value JSONField(null=True)
   - prior_is_not_applicable BooleanField
   - new_is_not_applicable BooleanField
   - prior_not_applicable_reason CharField(null=True)
   - new_not_applicable_reason CharField(null=True)
   - prior_entered_by FK(User, SET_NULL, null=True)
   - prior_entered_at DateTimeField(null=True)
   - prior_version PositiveIntegerField
   - new_version PositiveIntegerField
   - correction_reason TextField()
   - amended_by FK(User, on_delete=PROTECT)
   - amended_at DateTimeField(auto_now_add=True)
   - source_classification_snapshot CharField

4. CreateModel CalculationOutcome — all fields from §3.3.

5. AddIndex(ChecklistExecution, fields=["tenant", "status"])
6. AddIndex(ChecklistExecution, fields=["checklist_version"])
7. AddIndex(ChecklistResponse, fields=["execution"])
8. AddIndex(ChecklistResponseHistory, fields=["response"])
```

**Code-level retention controls (not database constraints — must be
implemented in Python):**
- `ChecklistResponseHistoryManager` overrides `.update()` and `.delete()`
  to raise `GovernedHistoryMutationForbidden`.
- `ChecklistResponseHistory.delete()` (model instance) raises
  `GovernedHistoryMutationForbidden`.
- These controls are registered in `IigChecklistConfig.ready()` alongside
  the `DeletionProtectionRegistry` hook.

Migration safety:
- All `CreateModel` operations on new tables — no `ALTER TABLE` on
  existing 4D-1 tables.
- No data migration.
- `migrate --check` must pass; `squashmigrations` must not be run
  on 4D-2 migrations until after 4D-3 is shipped and all rollback
  scenarios are confirmed.

---

## Section 11 — Import linter

Add `iig_checklist` → `formulations` to the allowed-imports contract
in `backend/pyproject.toml` (Q1 resolved to live FK by DR-2-03):

```toml
[[tool.importlinter.contracts]]
name = "iig-checklist-formulation-read-only"
type = "forbidden"
source_modules = ["formulations"]
forbidden_modules = ["iig_checklist"]
```

This forbids `formulations` → `iig_checklist` (the reverse direction),
leaving the `iig_checklist` → `formulations` direction permitted. The
existing contract already covers this direction; verify the linter
passes after the new FK is added.

---

## Section 12 — Frontend

### 12.1 Execution list page

`frontend/src/app/iig-checklists/executions/page.tsx`

- Fetch `GET /api/regx/v1/iig-checklists/executions/?tenant=<slug>`.
- Display: status badge, `ChecklistVersion` version number, formulation
  version reference, created date.
- "New execution" button → execution create page.
- 401 → `/signin`. 403 → inline error (never `/signin`). Same
  convention as 4D-1.

### 12.2 Execution create page

`frontend/src/app/iig-checklists/executions/new/page.tsx`

- Two selects: active `ChecklistVersion` (filtered to `status == active`),
  `FormulationVersion` (for tenant).
- POST on submit → redirect to execution detail on 201.
- 403 → inline error distinguishing insufficient permission from
  uniqueness conflict (409 → "An active execution already exists for
  this combination").
- No optimistic updates.

### 12.3 Execution detail page

`frontend/src/app/iig-checklists/executions/[executionPublicId]/page.tsx`

- Read-only header: status, version reference, formulation version,
  provenance fields.
- Lifecycle action buttons rendered per status (same pattern as
  `versions/[versionPublicId]/page.tsx`):
  - `draft`/`returned`: Submit for review, Cancel.
  - `submitted_for_review`: Approve, Reject, Return (with reason input).
  - `approved`: Supersede.
  - Terminal statuses: no action buttons.
- Mutation 403 → inline `actionError` (never redirect to `/signin`).
- No optimistic status change — `load()` called after successful action.
- No per-question response entry UI in 4D-2.

### 12.4 API client additions

`frontend/src/lib/api.ts` extensions:

```typescript
export interface ChecklistExecution { ... }
export interface ChecklistResponse { ... }
export const iigChecklists = {
  ...existing,
  executions: {
    list(tenantSlug: string): Promise<ChecklistExecution[]>,
    create(tenantSlug: string, body: {...}): Promise<ChecklistExecution>,
    get(tenantSlug: string, publicId: string): Promise<ChecklistExecution>,
    submitReview(tenantSlug: string, publicId: string): Promise<ChecklistExecution>,
    approve(tenantSlug: string, publicId: string, note: string): Promise<ChecklistExecution>,
    return(tenantSlug: string, publicId: string, reason: string): Promise<ChecklistExecution>,
    reject(tenantSlug: string, publicId: string): Promise<ChecklistExecution>,
    cancel(tenantSlug: string, publicId: string): Promise<ChecklistExecution>,
    supersede(tenantSlug: string, publicId: string): Promise<ChecklistExecution>,
  },
  responses: {
    list(tenantSlug: string, executionPublicId: string): Promise<ChecklistResponse[]>,
    update(tenantSlug: string, executionPublicId: string, responsePublicId: string, body: {...}): Promise<ChecklistResponse>,
  }
}
```

---

## Section 13 — Test strategy

### 13.1 Unit / model tests

`backend/iig_checklist/tests/test_execution_models.py`:

- `ChecklistExecution.clean()`: status field is not directly editable
  outside service (verified by attempting direct attribute set).
- `ChecklistResponse.clean()`: immutability once execution is `approved`;
  `full_clean()` actually invoked (direct `save()` without `full_clean()`
  must fail the test, proving the defect cannot recur).
- `CalculationOutcome`: field constraints, `calculation_name` validation.
- `unique_response_per_question_per_execution`: `IntegrityError` on
  duplicate `(execution, question)`.
- `unique_active_execution_per_version_formulation`: `IntegrityError`
  when two non-terminal executions share `(tenant, version, formulation)`.
- Payload limits (DR-2-01): one test per limit verifying exactly-at-limit
  accepted and exactly-over-limit rejected with `payload_too_large` (not
  a raw Django ValidationError). Test targets: `raw_value`, `return_reason`,
  `reviewer_conclusion_note`, `not_applicable_reason`.
- `raw_value` shapes (DR-2-17): one test per `answer_type` (all 18
  DB values from `enums.py`) verifying: canonical shape accepted;
  at least one malformed shape rejected with `invalid_raw_value_shape`;
  `calculated_value` and `calculated_status` reject any client-supplied
  `raw_value`; `approval_metadata` rejects client input; `decimal` and
  `percentage` reject JSON floats; `yes_no` rejects strings; `yes_no_na`
  rejects booleans and any string outside the three controlled values;
  `multi_select` rejects duplicate option codes.
- Integer boolean rejection (DR-2-24): `{"value": 1}` accepted;
  `{"value": 0}` accepted; `{"value": true}` rejected with
  `invalid_raw_value_shape`; `{"value": false}` rejected; `{"value": 1.0}`
  rejected; `{"value": "1"}` rejected.
- `quantity_with_unit` allowed-units validation (DR-2-25, DR-2-32): a unit
  present in `question.allowed_units` accepted; a unit absent from
  `question.allowed_units` rejected with `invalid_raw_value_shape`; an
  empty unit string rejected; `question.allowed_units = []` → any unit
  rejected (empty list is strictly invalid, not permissive); duplicate
  unit codes in `allowed_units` rejected; a non-`quantity_with_unit`
  question with non-empty `allowed_units` rejected at the governance gate;
  `question.allowed_units` read from the resolved question object at the
  time of validation, not re-queried from a live (possibly mutated) source.
- `ChecklistResponse.version` (DR-2-23): default is 1; increments to 2
  after `enter_reviewer_conclusion()` first entry; increments to 3 after
  amendment.
- `ChecklistResponseHistory` (DR-2-23, DR-2-30): created on amendment;
  `prior_raw_value` equals pre-amendment value; `new_raw_value` equals
  the value written; `prior_version` and `new_version` accurately reflect
  before/after state; `correction_reason` non-empty; `amended_by` is the
  acting user; not created on first entry.
- History immutability (DR-2-30): calling `.delete()` on a
  `ChecklistResponseHistory` instance raises `GovernedHistoryMutationForbidden`;
  `ChecklistResponseHistory.objects.filter(...).delete()` raises
  `GovernedHistoryMutationForbidden`; `ChecklistResponseHistory.objects.update(...)`
  raises `GovernedHistoryMutationForbidden`.
- Response PROTECT guard (DR-2-30): attempting to delete a
  `ChecklistResponse` that has one or more `ChecklistResponseHistory` rows
  raises a Django `ProtectedError` (via `on_delete=PROTECT` on the FK).
- `ChecklistResponseSerializer` version exposure (DR-2-28): a `GET` on a
  response returns `version`; initial value is 1; after first
  `enter_reviewer_conclusion()` it is 2; after amendment it is 3; the
  `version` field is absent from `ChecklistResponseUpdateSerializer` writable
  fields; a `PATCH` with `{"version": 99}` is rejected with structured 400.
- FormulationVersion status gate (DR-2-10): `create_execution()` rejects
  `draft` and `under_review` formulation versions with
  `formulation_version_not_approved`.
- Cross-tenant formulation version gate (DR-2-03): `create_execution()`
  rejects a formulation version belonging to a different tenant with
  `formulation_version_tenant_mismatch`.
- CalculationOutcome DATA_REQUIRED placeholders (DR-2-09, DR-2-18):
  execution creation for a version with questions whose
  `data_source_classification == SYSTEM_CALCULATED` creates
  `CalculationOutcome` rows with `status=DATA_REQUIRED`. Covers both
  `calculated_value` and `calculated_status` answer types. Questions
  with `USER_REQUIRED`, `REVIEWER_CONFIRMED`, `FDA_DERIVED_DEFAULT`, or
  `EVIDENCE_DERIVED` classification do NOT receive placeholders. No
  calculation evaluation occurs in 4D-2; no other `CalculationOutcome`
  creation path exists in this milestone.

### 13.2 Lifecycle tests

`backend/iig_checklist/tests/test_execution_lifecycle.py`:

- Complete legal transition table: all 6 actions × all legal source
  statuses (6 passing paths).
- Complete illegal transition coverage: every action attempted from
  every disallowed status — structured `IllegalExecutionTransition`
  raised, no DB write, no audit event.
- `reject` from `draft` succeeds for an authorized actor (DR-2-19).
- `reject` from `submitted_for_review` succeeds.
- `reject` from `returned`, `approved`, `cancelled`, `rejected`,
  `superseded` is blocked.
- Terminal states cannot transition (3 tests: `rejected`, `cancelled`,
  `superseded`).
- Self-approval guard: `submitted_by == actor` on `approve` → structured
  403, no transition.
- `submit_review` completeness pre-condition: incomplete execution
  rejected with structured 400 (pending Q3).
- `approve` completeness check.
- `return` requires `return_reason` in request body.
- Concurrent `approve`: two threads call `approve` simultaneously;
  exactly one succeeds, one receives a structured error; no double
  approval. Test uses `transaction=True` and real threads.

### 13.3 API tests

`backend/iig_checklist/tests/test_execution_api.py`:

- UUID-only responses on all endpoints (no numeric PKs).
- Generic 404 (not 403) when Tenant A's actor requests Tenant B's
  execution.
- `status` not patchable via PATCH on any endpoint.
- Illegal transition via lifecycle action endpoint returns structured 400.
- `reviewer_conclusion_note` required at `approve` (DR-2-07); missing
  note returns `reviewer_conclusion_required` / 400.
- Bounded pagination on list endpoint.
- 401/403 handling consistent with 4D-1 conventions.

### 13.4 Response tests

`backend/iig_checklist/tests/test_response_api.py`:

- `raw_value` accepted for each of the 18 `answer_type` shapes (all
  DB values from `enums.py`); malformed shape rejected with structured
  400 (`invalid_raw_value_shape`).
- `is_not_applicable = True` + `raw_value = null` accepted.
- `is_not_applicable = True` + non-null `raw_value` rejected.
- `not_applicable_reason` required when `is_not_applicable = True`.
- `REVIEWER_CONFIRMED` response: `confirmed_by` required before
  `submit_review`.
- Mutation after `approved` → 400 (immutability enforced via
  `full_clean()`).
- `document_version_public_id` in `raw_value` validated for tenant
  ownership.

### 13.5 Reviewer-conclusion tests (DR-2-23, DR-2-26, DR-2-27, DR-2-28, DR-2-29, DR-2-33)

**Service — first entry:**

- `enter_reviewer_conclusion()` with `execution.status=submitted_for_review`
  and actor holding `PERM_REVIEW_EXECUTION` succeeds; `response.raw_value`
  updated; `response.version` incremented from 1 to 2; no
  `ChecklistResponseHistory` row created.
- Actor lacking `PERM_REVIEW_EXECUTION` → `reviewer_conclusion_permission_denied`
  / 403; no history row; no audit event.
- `execution.status=draft` → `reviewer_conclusion_invalid_state` / 409.
- `execution.status=returned` → `reviewer_conclusion_invalid_state` / 409;
  existing conclusion value is retained unmodified on the response.
- `execution.status=approved` → `reviewer_conclusion_immutable` / 409.
- `execution.status=superseded` → `reviewer_conclusion_immutable` / 409.
- `raw_value` empty string → `reviewer_conclusion_empty` / 400.
- `raw_value` exactly 4 000 chars → accepted (DR-2-29).
- `raw_value` 4 001 chars → `reviewer_conclusion_too_long` / 400 (DR-2-29).
- `expected_version` mismatch (stale) → `reviewer_conclusion_stale_version`
  / 409; DB not written; no history row created (DR-2-27).
- `expected_version` mismatch (concurrent write simulation via two threads) →
  exactly one succeeds, one receives 409; only one history row exists
  after both attempts (DR-2-27).
- `question.answer_type ≠ reviewer_conclusion` passed to
  `enter_reviewer_conclusion()` → raises (programmer error guard).

**Service — amendment:**

- Amendment with `correction_reason` provided: `response.version`
  increments; one `ChecklistResponseHistory` row created inside the same
  transaction with correct `prior_raw_value`, `new_raw_value`,
  `prior_version`, `new_version`, `prior_entered_by`, `amended_by`,
  `amended_at`, and `correction_reason` (DR-2-27, DR-2-30).
- Stale `expected_version` on amendment attempt: 409 returned; zero
  `ChecklistResponseHistory` rows created for that attempt (DR-2-27).
- Amendment without `correction_reason` →
  `reviewer_conclusion_correction_reason_required` / 400; no DB write;
  no history row.
- Multiple amendments produce multiple `ChecklistResponseHistory` rows in
  insertion order; `prior_version`/`new_version` chain is contiguous.

**Returned / resubmitted / superseded lifecycle (DR-2-33):**

- Execution is `returned` after a reviewer_conclusion exists: conclusion
  value is retained on the `ChecklistResponse` row; no history row created
  on return transition.
- While execution is `returned`: `enter_reviewer_conclusion()` →
  `reviewer_conclusion_invalid_state` / 409; conclusion value unchanged.
- Execution is resubmitted (→ `submitted_for_review`): reviewer may amend
  the conclusion; amendment requires non-empty `correction_reason`; one
  `ChecklistResponseHistory` row is created with `prior_raw_value` =
  value from before resubmission; no audit or history created on the
  resubmission transition itself.
- Execution is `superseded`: `enter_reviewer_conclusion()` →
  `reviewer_conclusion_immutable` / 409; no history row; no audit event.

**Endpoint — `POST .../responses/<uuid>/reviewer-conclusion/`:**

- Happy-path 200: correct actor, valid payload, correct state; response
  body includes updated `version`.
- Non-reviewer actor → 403.
- Wrong execution state → 409 with structured error.
- Missing `raw_value` → 400.
- Missing `expected_version` → 400.
- Stale `expected_version` → 409 with `reviewer_conclusion_stale_version`.
- Response UUID belongs to different execution → 404.
- Cross-tenant response UUID → 404.
- `enter_response()` rejects `reviewer_conclusion` payload →
  `reviewer_conclusion_wrong_answer_type` / 400.
- `ChecklistResponseUpdateView` rejects `reviewer_conclusion` payload →
  `reviewer_conclusion_wrong_answer_type` / 400.
- `GET responses/<uuid>/` exposes `version`; initial value is 1; after
  first entry it is 2; `PATCH` with `{"version": 99}` is rejected with
  structured 400 (DR-2-28).

**Audit:**

- `checklist_response.reviewer_conclusion_entered` event emitted on
  first entry; payload contains execution `public_id`, response
  `public_id`, question `public_id`, actor email, `prior_response_version`,
  `new_response_version`, `execution_status`; does NOT contain conclusion
  text.
- `checklist_response.reviewer_conclusion_updated` event emitted on
  amendment; payload contains `correction_reason_present=True`; does NOT
  contain conclusion text or `prior_raw_value`.
- No success audit event on any failure path (stale version, wrong
  permission, wrong state, wrong answer_type).

### 13.6 Platform-authorization pin test

A dedicated test confirms that `can_mutate_definition_scope()` and
`can_author_platform_master()` are never called during any execution
path. This is a regression guard for the 4D-1 authorization boundary.

### 13.7 Docker integration test

Add to `.github/workflows/docker-integration.yml`:

```
- name: IIG checklist execution foundation flow
  run: |
    # Create execution against active ChecklistVersion
    # Enter required responses (one per answer type)
    # Submit for review
    # Return with reason
    # Re-enter responses
    # Submit for review again
    # Approve as VP (different user from submitter)
    # Verify immutability (attempt response update → 400)
    # Verify audit trail (execution.created, submitted×2, returned,
    #   approved, response.entered, response.updated events present)
    # Verify cross-tenant 404 (Tenant B cannot see Tenant A's execution)
    # Attempt cancel on approved → verify 400 (illegal transition)
```

---

## Section 14 — Error taxonomy

Structured errors returned by 4D-2 endpoints:

| `error_code` | HTTP | Trigger |
|---|---|---|
| `illegal_execution_transition` | 400 | `validate_execution_transition()` raises |
| `execution_already_active` | 409 | Uniqueness violation on non-terminal executions (DR-2-04) |
| `checklist_version_not_active` | 400 | `create_execution()` — version not `active` |
| `formulation_version_not_approved` | 400 | `create_execution()` — FV not `approved` (DR-2-10) |
| `formulation_version_tenant_mismatch` | 400 | FV belongs to different tenant (DR-2-03) |
| `incomplete_execution` | 400 | `submit_review` or `approve` completeness check (DR-2-05) |
| `missing_return_reason` | 400 | `return` action with empty `return_reason` |
| `reviewer_conclusion_required` | 400 | `approve` body missing `reviewer_conclusion_note` (DR-2-07) |
| `self_approval_forbidden` | 403 | `approve` actor is same as `submitted_by` |
| `response_immutable` | 400 | `enter_response` on approved execution |
| `response_delete_forbidden` | 400 | Deletion attempt on non-draft execution response (DR-2-02) |
| `invalid_raw_value_shape` | 400 | `raw_value` does not match `answer_type` canonical shape (DR-2-12) |
| `payload_too_large` | 400 | Any field exceeds its limit constant (DR-2-01) |
| `not_applicable_requires_reason` | 400 | `is_not_applicable=True` without reason |
| `document_version_not_found` | 400 | `raw_value.document_version_public_id` not in tenant (DR-2-06) |
| `reviewer_conclusion_wrong_answer_type` | 400 | `enter_response()` or `ChecklistResponseUpdateView` receives `reviewer_conclusion` raw value (DR-2-23) |
| `reviewer_conclusion_invalid_state` | 409 | `enter_reviewer_conclusion()` called when execution not in `submitted_for_review` (DR-2-23) |
| `reviewer_conclusion_permission_denied` | 403 | Actor lacks `PERM_REVIEW_EXECUTION` for `enter_reviewer_conclusion()` (DR-2-23) |
| `reviewer_conclusion_invalid_payload` | 400 | `ReviewerConclusionSerializer` validation failure (DR-2-23) |
| `reviewer_conclusion_empty` | 400 | `raw_value` is blank or empty string (DR-2-23) |
| `reviewer_conclusion_too_long` | 400 | `raw_value` exceeds `MAX_REVIEWER_CONCLUSION_CHARS` (4 000) Unicode code points (DR-2-23, DR-2-29) |
| `reviewer_conclusion_payload_too_large` | 400 | Outer payload exceeds limit constant (DR-2-23) |
| `reviewer_conclusion_stale_version` | 409 | `expected_version` does not match `response.version` (DR-2-23) |
| `reviewer_conclusion_correction_reason_required` | 400 | Amendment attempt with no `correction_reason` (DR-2-23) |
| `reviewer_conclusion_immutable` | 409 | `enter_reviewer_conclusion()` on approved execution (DR-2-23) |

Format (identical to 4D-1):
```json
{"error_code": "<code>", "detail": "<human-readable message>"}
```

---

## Section 15 — Rollback strategy

4D-2 adds new tables only. Rollback is `python manage.py migrate
iig_checklist 0001` — drops the four new tables (`ChecklistExecution`,
`ChecklistResponse`, `ChecklistResponseHistory`, `CalculationOutcome`)
with no effect on 4D-1 data. The frontend pages are new routes; removing
them does not affect 4D-1 pages. No 4D-1 migration or model is modified.

---

## Section 16 — Acceptance criteria

4D-2 is considered complete when:

1. All unit, lifecycle, API, response, and payload-limit tests pass.
2. Docker integration test "IIG checklist execution foundation flow"
   passes.
3. `migrate --check` passes with `0002_execution.py` applied.
4. Import-linter contracts all pass (`formulations` does not import
   `iig_checklist`; `iig_checklist` → `formulations` permitted).
5. Frontend execution list, create, and detail pages render without
   console errors; lifecycle actions update status correctly; mutation
   403 shows inline error.
6. `ChecklistResponse.clean()` is provably called on every `save()` path
   (a test that calls `save()` directly without `full_clean()` on an
   approved execution must fail — pins acceptance criterion against the
   `AssessmentSnapshot` defect pattern).
7. Payload-limit tests pass: at-limit accepted, over-limit returns
   `payload_too_large` / 400 with no DB write for all four bounded fields
   (DR-2-01).
8. `create_execution()` rejects non-approved `FormulationVersion` with
   `formulation_version_not_approved` (DR-2-10).
9. Cross-tenant formulation version reference rejected with
   `formulation_version_tenant_mismatch` (DR-2-03).
10. `DeletionProtectionRegistry` hook registered in `IigChecklistConfig.ready()`;
    test verifies that attempting to delete a `DocumentVersion` referenced by an
    approved execution raises `DocumentVersionDeleteForbidden` (DR-2-06).
11. No Critical or Major findings in the independent implementation review
    (equivalent standard to the 4D-1 post-implementation review).
12. All nine design decisions from `MILESTONE_4D_2_DESIGN_REMEDIATION.md`
    are referenced in the implementation PR description.
13. `enter_reviewer_conclusion()` can only be called when
    `execution.status=submitted_for_review`; all other states return the
    appropriate structured error (DR-2-23).
14. `enter_response()` and `ChecklistResponseUpdateView` reject
    `reviewer_conclusion` raw values with
    `reviewer_conclusion_wrong_answer_type` / 400 (DR-2-23).
15. Integer `raw_value` of `true` or `false` is rejected with
    `invalid_raw_value_shape`; integers 0 and 1 are accepted (DR-2-24).
16. `quantity_with_unit` validation uses `question.allowed_units` from the
    pinned question at time of response entry; a unit not in
    `allowed_units` is rejected (DR-2-25).
17. All reviewer-conclusion provenance tests in §13.5 pass, including
    optimistic-locking stale-version tests, `ChecklistResponseHistory`
    row creation on amendment with correct `prior_version`/`new_version`,
    and returned/resubmitted/superseded lifecycle cases (DR-2-26, DR-2-33).
18. `ChecklistResponseHistory` is append-only: instance `.delete()` and
    queryset `.delete()`/`.update()` raise `GovernedHistoryMutationForbidden`;
    a `ChecklistResponse` with history cannot be deleted (DR-2-30).
19. `ChecklistResponseSerializer` exposes `version` (read-only); initial
    value is 1; successful reviewer-conclusion write returns new version;
    `version` is not writable through `ChecklistResponseUpdateSerializer`
    (DR-2-28).
20. reviewer_conclusion `raw_value` of exactly 4 000 chars is accepted;
    4 001 chars returns `reviewer_conclusion_too_long` / 400 (DR-2-29).
21. `quantity_with_unit` question with `allowed_units = []` is rejected at
    the approval/activation governance gate; response validation with an
    empty frozen list returns `invalid_raw_value_shape` / 400 (DR-2-32).
22. Failed stale-version amendment creates zero `ChecklistResponseHistory`
    rows and emits zero audit success events (DR-2-27).

---

## Section 17 — Design decisions — all resolved

All nine design questions (7 original + 2 from design review) are
formally resolved. See `docs/MILESTONE_4D_2_DESIGN_REMEDIATION.md`.

| Question | Resolution | DR ref | Impact sections |
|---|---|---|---|
| Q1 — live FK vs. UUID | Live FK with PROTECT | DR-2-03 | §3.1, §6.1, §11 |
| Q2 — uniqueness constraint | One non-terminal per combination | DR-2-04 | §3.1, §10 |
| Q3 — completeness gate | Both submit_review AND approve | DR-2-05 | §4.3, §6.2, §13.2 |
| Q4 — document deletion | DeletionProtectionRegistry hook | DR-2-06 | §1.1, §3.2, §6.3 |
| Q5 — reviewer_conclusion_note | Required in approve request body | DR-2-07 | §4.3, §8.5 |
| Q6 — eager vs. lazy | Eager, applicability-filtered | DR-2-08 | §3.2, §6.1 |
| Q7 — CalculationOutcome scope | Model + DATA_REQUIRED placeholders | DR-2-09 | §3.3, §6.1 |
| Q8 — FV status requirement | Must be approved | DR-2-10 | §6.1, §14 |
| Q9 — applicability freeze | Implicit via 4D-1 immutability | DR-2-11 | §3.2 |

**No open questions remain.**

---

## Section 18 — Relationship to future milestones

| Milestone | What it builds on from 4D-2 |
|---|---|
| 4D-3 | `ChecklistResponse` eager rows populated with `FDA_DERIVED_DEFAULT`; `CalculationOutcome` rows computed from 4D-2's `CalculationOutcome` model using `iid_assessment.calculations` services; recalculation on `USER_REQUIRED` change; `REVIEWER_CONFIRMED` auto-populated where confidence is high |
| 4D-4 | Override/deviation workflow on `ChecklistResponse`; controlled JSON/CSV export with SHA-256 checksum; `_csv_safe_cell()` promotion from `templates_registry` to `common`; real regulatory checklist content loading |

4D-2 must not pre-implement any 4D-3 or 4D-4 feature, even partially.
Partial implementations that "just need to be wired up" in a later
milestone consistently introduce untested, unreviewed behavior into the
codebase. If a 4D-3 or 4D-4 feature is tempting to add in 4D-2,
document it as an exclusion here and add it as an open question for
the relevant milestone's discovery document instead.
