# Milestone 4D-2 Implementation Specification
## Checklist Execution, Response, and Immutable Snapshot Foundation

**Status: FINAL — Authorized for implementation.**
**Authorization date:** 2026-07-31
**Authorized by:** Human reviewer (formal approval recorded in PR description)

**Branch:** `regx/design/milestone-4d-2-discovery`
**Base milestone:** Milestone 4D-1 (CLOSED) — SHA `453974a4cd40501479730a524fd1b6671a96d6fc`
**Design inputs:**
- `docs/MILESTONE_4D_2_DISCOVERY.md` — discovery document, all open questions resolved
- `docs/MILESTONE_4D_2_DESIGN_REMEDIATION.md` — DR-2-01 through DR-2-33, all CLOSED
- Fourth independent design review — PASS; R4-M-1 through R4-M-4 closed in this spec

**Implementation branch to open:** `regx/feat/milestone-4d-2-execution-foundation`
(Created from `regx-main` after this spec is approved. **Do not implement on the discovery branch.**)

---

## Part I — Scope and Constraints

### §1 — In scope for 4D-2

- `ChecklistExecution` model, manager, migration.
- `ChecklistResponse` model — eager, applicability-filtered pre-creation at execution creation (DR-2-08).
- `ChecklistResponseHistory` model — append-only governed amendment audit for reviewer-conclusion amendments (DR-2-27, DR-2-30).
- `CalculationOutcome` model — `DATA_REQUIRED` placeholder rows at creation (DR-2-09); no calculation population until 4D-3.
- `execution_constants.py` — payload-limit constants (DR-2-01).
- `DeletionProtectionRegistry` hook in `documents` app, registered in `IigChecklistConfig.ready()` (DR-2-06).
- Execution lifecycle: `execution_transitions.py`, 6 actions, 7 statuses.
- Execution-level permissions: 8 new codenames, `ROLE_PERMISSIONS` extension.
- `GovernedHistoryMutationForbidden` exception and `ChecklistResponseHistoryManager` (R4-M-1).
- Services: `create_execution()`, `transition_execution()`, `enter_response()`, `update_response()`, `enter_reviewer_conclusion()`.
- Views, serializers, URL routing for executions and responses.
- Audit: 11 new `IigChecklistEvent` types.
- Tenant isolation: `ChecklistExecutionManager.visible_to(tenant)`.
- Import-linter: confirm `formulations` does not import `iig_checklist`.
- Minimal frontend: execution list, create, detail, lifecycle actions.
- Docker integration test step: "IIG checklist execution foundation flow."
- Unit, lifecycle, API, response, reviewer-conclusion, history/immutability, and payload-limit tests.
- Migration `0002_execution.py`.
- `create_execution()` validation: all `quantity_with_unit` questions must have non-empty `allowed_units` (R4-M-2).
- Direct tests for `rejected`, `cancelled`, `approved`, and `superseded` terminal states (R4-M-3).
- Direct tests for `prior_is_not_applicable`, `new_is_not_applicable`, `prior_not_applicable_reason`, `new_not_applicable_reason` (R4-M-4).

### §2 — Out of scope for 4D-2

- `FDA_DERIVED_DEFAULT` auto-population (4D-3).
- `SYSTEM_CALCULATED` computation and recalculation (4D-3).
- Override/deviation workflow (4D-4).
- Controlled exports — JSON, CSV, SHA-256 checksum (4D-4).
- Reviewer conclusion enforcement IS included (DR-2-07); override/deviation and regulatory conclusion automation remain deferred.
- Real regulatory checklist content.
- PDF/Word export (deferred beyond 4D).
- Any modification to 4D-1 definition-governance models or migrations.
- Promotion of `_csv_safe_cell()` from `templates_registry` to `common` (deferred to 4D-4).
- Any change to 4D-1 activation gate; `allowed_units` enforcement for new executions is the 4D-2 scope (R4-M-2 closure).

### §3 — Implementation constraints

- No force-push. No squash. No rebase. No merge to `main` without explicit authorization.
- No backend code, frontend code, migrations, CI, or Docker changes on the discovery branch.
- Implementation branch opens after human approval of this spec.
- Every governed row in `iig_checklist` is created through `_create_validated()` (calls `full_clean()` before `save()`). No governed row may be saved without `full_clean()` — the `AssessmentSnapshot` defect (a clean() guard that is never actually called) must not recur.

---

## Part II — Data Model

### §4 — `execution_constants.py`

Location: `backend/iig_checklist/execution_constants.py`

```python
MAX_RAW_VALUE_BYTES          = 16_384   # serialized JSON bytes
MAX_RETURN_REASON_CHARS      = 2_000
MAX_REVIEWER_CONCLUSION_CHARS = 4_000   # applies to both reviewer_conclusion_note
                                        # and reviewer_conclusion answer raw_value.value
MAX_FREE_TEXT_CHARS          = 4_000    # short_text, long_narrative only
MAX_NOT_APPLICABLE_REASON_CHARS = 200
MAX_SELECT_OPTIONS           = 64
```

`MAX_REVIEWER_CONCLUSION_CHARS` is the authoritative limit for both `ChecklistExecution.reviewer_conclusion_note` and the `raw_value.value` string inside a `reviewer_conclusion` answer. It is **not** `MAX_FREE_TEXT_CHARS` (DR-2-29).

### §5 — `ChecklistExecution`

Inherits `PublicIDModel`, `TimeStampedModel`.

**Module:** `backend/iig_checklist/models.py` (alongside 4D-1 models, not a new file).

**Fields (authoritative — no field is client-writable outside its designated service call):**

```
tenant                    FK(tenancy.Tenant, on_delete=PROTECT)
checklist_version         FK(ChecklistVersion, on_delete=PROTECT)
formulation_version       FK(formulations.FormulationVersion, on_delete=PROTECT)  # DR-2-03
status                    CharField(max_length=30, choices=ExecutionStatus, default=ExecutionStatus.DRAFT)
created_by                FK(identity.User, on_delete=PROTECT, related_name="+")
submitted_by              FK(identity.User, SET_NULL, null=True, related_name="+")
submitted_at              DateTimeField(null=True)
reviewed_by               FK(identity.User, SET_NULL, null=True, related_name="+")
returned_by               FK(identity.User, SET_NULL, null=True, related_name="+")
returned_at               DateTimeField(null=True)
return_reason             TextField(blank=True, max_length=2000)           # DR-2-01
approved_by               FK(identity.User, SET_NULL, null=True, related_name="+")
approved_at               DateTimeField(null=True)
rejected_by               FK(identity.User, SET_NULL, null=True, related_name="+")
rejected_at               DateTimeField(null=True)
cancelled_by              FK(identity.User, SET_NULL, null=True, related_name="+")
cancelled_at              DateTimeField(null=True)
superseded_by             FK("self", SET_NULL, null=True, related_name="supersedes")
reviewer_conclusion_note  TextField(blank=True, max_length=4000)           # DR-2-01; set via approve body only
```

**DB constraints:**

```python
class Meta:
    constraints = [
        UniqueConstraint(
            fields=["tenant", "checklist_version", "formulation_version"],
            condition=~Q(status__in=["rejected", "cancelled", "superseded"]),
            name="unique_active_execution_per_version_formulation",
        )
    ]
    indexes = [
        Index(fields=["tenant", "status"]),
        Index(fields=["checklist_version"]),
    ]
```

Partial unique index excludes terminal statuses `rejected`, `cancelled`, `superseded` (DR-2-04). Non-terminal executions — `draft`, `submitted_for_review`, `returned`, `approved` — are all enforced unique per `(tenant, checklist_version, formulation_version)`.

### §6 — `ExecutionStatus` enum

```python
class ExecutionStatus(models.TextChoices):
    DRAFT                 = "draft"
    SUBMITTED_FOR_REVIEW  = "submitted_for_review"
    RETURNED              = "returned"
    APPROVED              = "approved"
    REJECTED              = "rejected"
    CANCELLED             = "cancelled"
    SUPERSEDED            = "superseded"

TERMINAL_EXECUTION_STATUSES = frozenset({
    ExecutionStatus.REJECTED,
    ExecutionStatus.CANCELLED,
    ExecutionStatus.SUPERSEDED,
})
```

### §7 — `ChecklistResponse`

Inherits `PublicIDModel`, `TimeStampedModel`.

```
execution                 FK(ChecklistExecution, on_delete=PROTECT)
question                  FK(ChecklistQuestion, on_delete=PROTECT)
data_source_type_snapshot CharField(max_length=50)  # frozen at creation from question.data_source_classification
raw_value                 JSONField(null=True)       # shape varies by answer_type; max 16 384 bytes serialized
is_not_applicable         BooleanField(default=False)
not_applicable_reason     CharField(null=True, blank=True, max_length=200)  # DR-2-01
entered_by                FK(identity.User, SET_NULL, null=True, related_name="+")
entered_at                DateTimeField(null=True)
confirmed_by              FK(identity.User, SET_NULL, null=True, related_name="+")
confirmed_at              DateTimeField(null=True)
override_reason           TextField(blank=True)
system_derived_value      JSONField(null=True)
version                   PositiveIntegerField(default=1)  # DR-2-23, DR-2-28
```

**DB constraints:**

```python
class Meta:
    constraints = [
        UniqueConstraint(
            fields=["execution", "question"],
            name="unique_response_per_question_per_execution",
        )
    ]
    indexes = [
        Index(fields=["execution"]),
    ]
```

**`clean()` method — must enforce all of the following:**

1. Immutability: if `self.execution.status` is outside `{draft, returned}`, any mutation raises `ValidationError("response_immutable")`.
2. `is_not_applicable = True` implies `raw_value` is null.
3. `not_applicable_reason` is required and non-empty when `is_not_applicable = True`.
4. `override_reason` is non-empty whenever `system_derived_value` is not null.
5. `len(json.dumps(self.raw_value)) <= MAX_RAW_VALUE_BYTES` when `raw_value` is not null (DR-2-01, second-layer enforcement).

`clean()` must be reachable: every `save()` path on a `ChecklistResponse` must call `full_clean()` before `save()` — enforced via `_create_validated()` on initial creation and explicit `full_clean()` calls in every update service. This acceptance criterion is mandatory: the `AssessmentSnapshot` defect (clean() guard that is never actually invoked) must not recur.

No delete endpoint is exposed. Service layer raises `ResponseDeleteForbidden` on any deletion attempt when execution is not `draft` (DR-2-02).

### §8 — `ChecklistResponseHistory`

Inherits `PublicIDModel`, `TimeStampedModel`.

Created by `enter_reviewer_conclusion()` **inside the same transaction, after the version check passes and after the response row is saved** — one row per amendment; never on first entry (DR-2-27, DR-2-30). Rows are governed records and may not be mutated or deleted after creation.

Tenant is derived through `response.execution.tenant`; no direct `tenant` FK.

```
response                        FK(ChecklistResponse, on_delete=PROTECT)
                                # PROTECT: a response with history cannot be deleted (DR-2-30)
prior_raw_value                 JSONField(null=True)
new_raw_value                   JSONField(null=True)
prior_is_not_applicable         BooleanField()           # R4-M-4
new_is_not_applicable           BooleanField()           # R4-M-4
prior_not_applicable_reason     CharField(null=True)     # R4-M-4
new_not_applicable_reason       CharField(null=True)     # R4-M-4
prior_entered_by                FK(identity.User, SET_NULL, null=True, related_name="+")
prior_entered_at                DateTimeField(null=True)
prior_version                   PositiveIntegerField()   # response.version before increment
new_version                     PositiveIntegerField()   # response.version after increment
correction_reason               TextField()              # required; non-empty
amended_by                      FK(identity.User, on_delete=PROTECT, related_name="+")
amended_at                      DateTimeField(auto_now_add=True)
source_classification_snapshot  CharField(max_length=50) # frozen copy of data_source_type_snapshot
```

**Immutability controls (R4-M-1, DR-2-30):**

```python
class GovernedHistoryMutationForbidden(Exception):
    """Raised when any mutation (save, update, delete) is attempted on an
    existing ChecklistResponseHistory row."""


class ChecklistResponseHistoryManager(models.Manager):
    def get_queryset(self):
        return _ImmutableHistoryQuerySet(self.model, using=self._db)


class _ImmutableHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be updated."
        )

    def delete(self):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be deleted."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be bulk-updated."
        )


class ChecklistResponseHistory(PublicIDModel, TimeStampedModel):
    objects = ChecklistResponseHistoryManager()
    ...

    def delete(self, using=None, keep_parents=False):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be deleted."
        )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise GovernedHistoryMutationForbidden(
                "ChecklistResponseHistory rows are append-only; "
                "save() on an existing row is forbidden."
            )
        super().save(*args, **kwargs)
```

Controls summary (R4-M-1 explicit closure):
- **Initial object creation is allowed** — `save()` proceeds when `self.pk is None`.
- **`save()` on an existing row raises `GovernedHistoryMutationForbidden`** — guarded by `self.pk is not None` check.
- **Queryset `.update()` is blocked** — `_ImmutableHistoryQuerySet.update()` raises unconditionally.
- **Queryset `.delete()` is blocked** — `_ImmutableHistoryQuerySet.delete()` raises unconditionally.
- **`bulk_update()` is blocked** — raises `GovernedHistoryMutationForbidden`.
- **Instance `.delete()` is blocked** — `ChecklistResponseHistory.delete()` raises unconditionally.
- **`on_delete=PROTECT` on the `response` FK** — a `ChecklistResponse` with one or more `ChecklistResponseHistory` rows cannot be deleted through any Django path; the DB raises `ProtectedError`.

These controls are registered at app startup in `IigChecklistConfig.ready()` alongside the `DeletionProtectionRegistry` hook.

### §9 — `CalculationOutcome`

Inherits `PublicIDModel`, `TimeStampedModel`.

```
response                              FK(ChecklistResponse, on_delete=CASCADE)
calculation_name                      CharField(max_length=100)  # one of six exact iid_assessment function names
formula_version                       CharField(max_length=50)
status                                CharField(max_length=50, choices=CalculationStatus)
value                                 DecimalField(null=True, max_digits=20, decimal_places=10)
unit                                  CharField(blank=True, max_length=50)
inputs                                JSONField(default=dict)
input_provenance                      JSONField(default=dict)
rounding_rule                         CharField(blank=True, max_length=100)
reason_code                           CharField(blank=True, max_length=100)
generated_at                          DateTimeField(null=True)
source_assessment_snapshot_public_id  UUIDField(null=True)
```

No client-facing write endpoint. 4D-2 creates the model and migration; rows are populated server-side at execution creation with `status = DATA_REQUIRED`. Populated with actual values in 4D-3.

`calculation_name` must be one of the six exact function names from `iid_assessment.calculations`:
`calculate_percentage_w_w`, `calculate_daily_exposure`, `calculate_percentage_of_potency`,
`calculate_difference_from_potency`, `calculate_percentage_of_mde`, `calculate_difference_from_mde`.
Validated at model level via `clean()`.

### §10 — `allowed_units` enforcement at execution creation (R4-M-2)

`create_execution()` validates every applicable `quantity_with_unit` question in the pinned `ChecklistVersion` before writing any rows. If any such question has `allowed_units = []` (empty list), execution creation fails with:

```json
{"error_code": "execution_invalid_quantity_unit_config", "detail": "Question <code> has answer_type quantity_with_unit but allowed_units is empty. Contact the checklist administrator to correct the definition version before creating an execution."}
```

HTTP 400.

**Scope of this enforcement (R4-M-2 closure):**

- This is a `create_execution()` guard only. It does not modify any 4D-1 model or the 4D-1 definition-governance lifecycle.
- The `ChecklistVersion` activation gate (4D-1 scope) is **not** modified in this milestone. Strengthening that gate is a separately deferred improvement.
- Response-level validation also rejects any unit when `allowed_units` is empty — this is enforced in `ChecklistResponseUpdateSerializer` and `enter_response()`, not only at execution creation.
- Empty `allowed_units` does not mean "any unit allowed." It is strictly invalid for a `quantity_with_unit` question.

---

## Part III — Lifecycle

### §11 — `execution_transitions.py`

Location: `backend/iig_checklist/execution_transitions.py`

```python
_EXECUTION_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "submit_review": (frozenset({"draft", "returned"}),          "submitted_for_review"),
    "approve":       (frozenset({"submitted_for_review"}),       "approved"),
    "return":        (frozenset({"submitted_for_review"}),       "returned"),
    "reject":        (frozenset({"draft", "submitted_for_review"}), "rejected"),
    "cancel":        (frozenset({"draft", "returned"}),          "cancelled"),
    "supersede":     (frozenset({"approved"}),                   "superseded"),
}

TERMINAL_EXECUTION_STATUSES = frozenset({"rejected", "cancelled", "superseded"})


class IllegalExecutionTransition(ValueError):
    pass


def validate_execution_transition(current_status: str, action: str) -> str:
    """Returns the resulting status. Raises IllegalExecutionTransition on illegal path."""
    if action not in _EXECUTION_TRANSITIONS:
        raise IllegalExecutionTransition(f"Unknown action: {action!r}")
    legal_from, resulting_status = _EXECUTION_TRANSITIONS[action]
    if current_status not in legal_from:
        raise IllegalExecutionTransition(
            f"Action {action!r} is not legal from status {current_status!r}."
        )
    return resulting_status
```

Structurally identical to `iig_checklist/transitions.py` and `fda_data`'s equivalent. Views call `validate_execution_transition()` before any mutation; illegal transitions return structured 400 with no DB write and no audit event.

### §12 — Pre-conditions (per action)

**`submit_review` (DR-2-05):**

- Every `required=True` question applicable to this execution has a response with `raw_value` not null OR `is_not_applicable=True` with non-empty `not_applicable_reason`.
- Every `REVIEWER_CONFIRMED` question applicable to this execution has `confirmed_by` set.
- Questions with `answer_type == reviewer_conclusion` are **excluded** from this gate — a reviewer conclusion cannot legally exist before `submitted_for_review`.
- Error: `error_code = "incomplete_execution"` / 400.

**`approve` (DR-2-05 redundant safety re-check):**

- Same completeness check as `submit_review`.
- Additional gate: for every `required=True` question with `answer_type == reviewer_conclusion` applicable to this execution, the response must have a non-null `raw_value` and `is_not_applicable=False`. A missing required reviewer conclusion raises `error_code = "incomplete_execution"` / 400.
- `reviewer_conclusion_note` must be non-empty, provided in the request body (DR-2-07). Error: `error_code = "reviewer_conclusion_required"` / 400.

**`return`:**

- `return_reason` must be non-empty in the request body, max `MAX_RETURN_REASON_CHARS`. Error: `error_code = "missing_return_reason"` / 400.

**`approve` self-approval guard:**

- `execution.submitted_by == request.user` → `error_code = "self_approval_forbidden"` / 403.

**`reject`, `cancel`, `supersede`:** no additional pre-conditions beyond the transition guard and permission check.

---

## Part IV — Permissions

### §13 — New permission codenames

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

### §14 — `ROLE_PERMISSIONS` extension

Additive only — no existing 4D-1 role entry is changed:

| Role | New execution permissions |
|---|---|
| `DOER` | create, edit, submit, cancel, view |
| `REVIEWER` | review, view |
| `VP` | approve, supersede, view |
| `TENANT_ADMIN` | view |
| `PLATFORM_SUPPORT` | (none) |

`can_author_platform_master()` is **not** involved in any execution path. `can_mutate_definition_scope()` is **not** called in any execution path. Executions are always tenant-scoped; using a `platform_master` checklist version does not change the execution's authorization model (see §16.6 — platform authorization pin test).

### §15 — Execution-scope tenant isolation

Every execution view begins with:
```python
execution = get_object_or_404(
    ChecklistExecution.objects.visible_to(tenant),
    public_id=uuid
)
```

`ChecklistExecutionManager.visible_to(tenant)` filters by `tenant` FK directly. No `platform_master` dual-filter — executions are never platform-scoped.

Generic 404 (never 403) when a tenant attempts to reach another tenant's execution. Same convention as 4D-1.

---

## Part V — Services

### §16 — `create_execution(*, tenant, checklist_version_public_id, formulation_version_public_id, actor)`

```
1. Resolve ChecklistVersion from public_id via visible_to(tenant) or platform_master filter.
   Verify status == "active" → else raise ChecklistVersionNotActive /
   error_code = "checklist_version_not_active" / 400.

2. Resolve FormulationVersion by public_id.
   Verify status == "approved" (DR-2-10) → else raise FormulationVersionNotApproved /
   error_code = "formulation_version_not_approved" / 400.
   Verify formulation_version.product_development_record.tenant == tenant (DR-2-03)
   → else raise FormulationVersionTenantMismatch /
   error_code = "formulation_version_tenant_mismatch" / 400.

3. Verify actor has PERM_CREATE_EXECUTION.

4. Validate all applicable quantity_with_unit questions (R4-M-2):
   For each ChecklistQuestion in the active ChecklistVersion where answer_type == quantity_with_unit:
     If allowed_units == [] → raise structured 400 with
     error_code = "execution_invalid_quantity_unit_config" before entering the transaction.

5. Inside transaction.atomic():
   a. select_for_update() on ChecklistVersion (DR-2-16, lock 1).
   b. select_for_update() on any existing non-terminal execution for
      this (tenant, checklist_version, formulation_version) (DR-2-16, lock 2).
      If found → raise ExecutionAlreadyActive / error_code = "execution_already_active" / 409.
   c. _create_validated(ChecklistExecution, status=DRAFT, created_by=actor,
        tenant=tenant, checklist_version=version, formulation_version=fv).
   d. Evaluate applicability rules for each question in the pinned version
      against the formulation_version (DR-2-08).
      For each applicable question:
        _create_validated(ChecklistResponse,
          execution=exec, question=q,
          data_source_type_snapshot=q.data_source_classification,
          raw_value=None, is_not_applicable=False, entered_by=None).
        If q.data_source_classification == DataSourceClassification.SYSTEM_CALCULATED:
          _create_validated(CalculationOutcome,
            response=r, status="DATA_REQUIRED",
            calculation_name=q.calculation_binding_identifier, ...) (DR-2-09).
   e. Catch IntegrityError → structured 409 (uniqueness race backstop).

6. Via transaction.on_commit():
   Emit IigChecklistEvent.EXECUTION_CREATED audit event.

7. Return execution.
```

### §17 — `transition_execution(*, execution, action, actor, **kwargs)`

```
1. validate_execution_transition(execution.status, action) → raises IllegalExecutionTransition
   on illegal path (structured 400, no DB write, no audit event).
2. Verify actor has the action-specific permission (§14).
3. Check action-specific pre-conditions (§12).
4. Inside transaction.atomic() + select_for_update() on execution:
   a. Set new status and provenance fields (actor, timestamp, reason).
   b. execution.full_clean() → execution.save().
5. Via transaction.on_commit():
   Emit lifecycle audit event.
6. Return execution.
```

### §18 — `enter_response(*, execution, question_public_id, actor, raw_value, is_not_applicable, not_applicable_reason)`

**Scope:** applies only to questions whose `answer_type` is **not** `reviewer_conclusion`. Any `reviewer_conclusion` raw_value passed to this service is rejected with `error_code = "reviewer_conclusion_wrong_answer_type"` / 400 before any DB write (DR-2-23).

```
1. Verify execution.status in {draft, returned}.
2. Verify actor has PERM_EDIT_EXECUTION.
3. Resolve ChecklistQuestion by public_id; verify it belongs to the pinned ChecklistVersion.
4. Validate raw_value shape against question.answer_type (all 18 DB values — §24).
   Strict: unknown shapes → structured 400, no partial acceptance.
   Reject reviewer_conclusion raw_value → error_code = "reviewer_conclusion_wrong_answer_type" / 400.
5. If is_not_applicable: verify raw_value is null.
6. Verify not_applicable_reason is non-empty when is_not_applicable is True.
7. Resolve ChecklistResponse for (execution, question) — pre-created at execution creation.
8. response.data_source_type_snapshot = question.data_source_classification (if not already set).
9. Apply raw_value, is_not_applicable, not_applicable_reason, entered_by=actor, entered_at=now.
10. response.full_clean() → response.save().
11. Via transaction.on_commit():
    Emit RESPONSE_ENTERED or RESPONSE_UPDATED audit event.
12. Return response.
```

### §19 — `enter_reviewer_conclusion(*, execution, response_public_id, actor, raw_value, expected_version, correction_reason=None)`

**Transaction ordering rule (DR-2-27):** every regulated write — the `ChecklistResponseHistory` row and the `ChecklistResponse` update — occurs inside a single `transaction.atomic()` block, after the optimistic-version check passes. No history row may be created for a failed or racing update. No audit success event may exist for a failed amendment.

```
Phase A — non-mutating preliminary validation (outside any transaction):

1. Resolve execution via ChecklistExecution.objects.visible_to(tenant) — generic 404 if not
   found or cross-tenant.
2. Verify execution.status == "submitted_for_review"
   → else raise error_code = "reviewer_conclusion_invalid_state" / 409.
3. Verify actor has PERM_REVIEW_EXECUTION
   → else raise error_code = "reviewer_conclusion_permission_denied" / 403.
4. Resolve ChecklistResponse by response_public_id; verify response.execution == execution
   (generic 404 if mismatch or cross-tenant).
5. Verify response.question.answer_type == reviewer_conclusion
   → else error_code = "reviewer_conclusion_wrong_answer_type" / 400.
6. Validate raw_value structure and payload limits:
   - Must be {"value": "..."} with no additional keys.
   - value must be a string (not null, not bool, not int).
   - Trimmed value must not be empty → error_code = "reviewer_conclusion_empty" / 400.
   - len(raw_value["value"]) > MAX_REVIEWER_CONCLUSION_CHARS →
     error_code = "reviewer_conclusion_too_long" / 400 (DR-2-29).
   - len(json.dumps(raw_value)) > MAX_RAW_VALUE_BYTES →
     error_code = "reviewer_conclusion_payload_too_large" / 400.
   - Wrong structure → error_code = "reviewer_conclusion_invalid_payload" / 400.
7. If amendment path (response.raw_value is not None):
   - Verify correction_reason is non-empty
     → else error_code = "reviewer_conclusion_correction_reason_required" / 400.

Phase B — all regulated writes, inside one transaction (DR-2-27):

8. Enter transaction.atomic().
9. select_for_update() on ChecklistExecution (lock order: execution first — DR-2-27).
10. select_for_update() on ChecklistResponse (lock order: response second — DR-2-27).
11. Re-validate after acquiring locks:
    a. Verify execution.status == "submitted_for_review"
       → else rollback: return reviewer_conclusion_invalid_state / 409.
    b. Verify response still belongs to execution (paranoia guard).
    c. Verify response.question.answer_type == reviewer_conclusion.
    d. Verify response.version == expected_version
       → else rollback: return reviewer_conclusion_stale_version / 409.
       No history row created. No audit event emitted.
12. Capture pre-write state for history (in memory — not yet saved):
    is_amendment = (response.raw_value is not None)
    prior_raw_value = response.raw_value
    prior_is_not_applicable = response.is_not_applicable
    prior_not_applicable_reason = response.not_applicable_reason
    prior_entered_by = response.entered_by
    prior_entered_at = response.entered_at
    prior_version = response.version
13. Write response:
    a. response.raw_value = raw_value
    b. response.entered_by = actor
    c. response.entered_at = now (UTC)
    d. response.data_source_type_snapshot = (response.data_source_type_snapshot
       or response.question.data_source_classification)
    e. response.version = prior_version + 1
    f. response.full_clean() → response.save()
14. If is_amendment: create ChecklistResponseHistory inside this same transaction
    (after version check passes, after response.save() at step 13):
      ChecklistResponseHistory(
        response=response,
        prior_raw_value=prior_raw_value,
        new_raw_value=raw_value,
        prior_is_not_applicable=prior_is_not_applicable,       # R4-M-4
        new_is_not_applicable=response.is_not_applicable,      # R4-M-4
        prior_not_applicable_reason=prior_not_applicable_reason, # R4-M-4
        new_not_applicable_reason=response.not_applicable_reason, # R4-M-4
        prior_entered_by=prior_entered_by,
        prior_entered_at=prior_entered_at,
        prior_version=prior_version,
        new_version=response.version,
        correction_reason=correction_reason,
        amended_by=actor,
        source_classification_snapshot=response.data_source_type_snapshot,
      ).save()   # allowed because pk is None — R4-M-1
15. Commit transaction.

Phase C — post-commit:

16. Via transaction.on_commit():
    - is_amendment was False → emit RESPONSE_REVIEWER_CONCLUSION_ENTERED.
    - is_amendment was True  → emit RESPONSE_REVIEWER_CONCLUSION_UPDATED.
    (Only after successful commit — never on any failure path.)
17. Return response.
```

**Invariants enforced by this sequence:**
- A `ChecklistResponseHistory` row never exists for a failed amendment.
- An audit success event never exists for a failed amendment.
- History row and response update succeed or fail atomically.
- No regulated write occurs before the stale-version check at step 11d.
- `response.version` in the history row accurately reflects before/after state.

---

## Part VI — Serializers

### §20 — `ChecklistExecutionSerializer` (read-only)

```
public_id, status, created_at, updated_at,
checklist_version: {public_id, version_number, status},
formulation_version_public_id,
created_by_email, submitted_by_email, submitted_at,
returned_by_email, returned_at, return_reason,
approved_by_email, approved_at,
rejected_by_email, rejected_at,
cancelled_by_email, cancelled_at,
reviewer_conclusion_note
```

Never exposed: tenant_id, internal PKs, storage keys, question text from the pinned version, raw calculation inputs.

### §21 — `ChecklistExecutionCreateSerializer`

Writable fields:
```
checklist_version_public_id: UUIDField (required)
formulation_version_public_id: UUIDField (required)
```

`status`, all provenance fields, and `tenant` are never accepted from client input.

### §22 — `ChecklistResponseSerializer` (read-only, DR-2-28)

```
public_id, question_public_id, data_source_type_snapshot,
raw_value, is_not_applicable, not_applicable_reason,
entered_by_email, entered_at,
confirmed_by_email, confirmed_at,
override_reason, system_derived_value,
version
```

`version` is a read-only positive integer. Initial value is 1. Incremented after each successful write (first entry or amendment). Clients must echo the latest server-provided `version` as `expected_version` when calling the reviewer-conclusion endpoint. `version` is not accepted through any writable serializer — any client-supplied `version` in a non-reviewer-conclusion request body is rejected with a structured 400.

### §23 — `ChecklistResponseUpdateSerializer`

Writable:
```
raw_value: JSONField (nullable)
is_not_applicable: BooleanField
not_applicable_reason: CharField (nullable)
override_reason: TextField (blank)
```

`execution`, `question`, `data_source_type_snapshot`, `confirmed_by`, `confirmed_at`, `system_derived_value`, and `version` are never client-writable.

Mass-assignment guard: any unknown field in the request body returns a structured 400.

**`raw_value` shape validation (DR-2-17) — all 18 `AnswerType` DB values:**

The serializer validates `raw_value` against the canonical shape for the question's `answer_type`. The table of exact DB values is authoritative — see §24.

Validation rules:
- Reject any non-null `raw_value` for `calculated_value`, `calculated_status`, or `approval_metadata`.
- Reject JSON float where decimal string required (`decimal`, `quantity_with_unit`, `percentage`).
- Reject Python `bool` where JSON integer required (`integer`) — `isinstance(val, bool)` checked **before** `isinstance(val, int)` (DR-2-24). `{"value": true}` and `{"value": false}` both return `error_code = "invalid_raw_value_shape"`.
- Reject unit not in `question.allowed_units` for `quantity_with_unit`. Empty `allowed_units = []` means any unit rejected (DR-2-32). Read from resolved question object (frozen by version immutability — not a live DB re-query).
- Reject string `"true"`/`"false"` where JSON boolean required (`yes_no`).
- Reject boolean where controlled string enum required (`yes_no_na`).
- Reject any `yes_no_na` value outside `{"value": "yes"}`, `{"value": "no"}`, `{"value": "not_applicable"}`.
- Reject duplicate option codes in `multi_select`.
- Reject any `reviewer_conclusion` raw_value — use `/reviewer-conclusion/` endpoint → `error_code = "reviewer_conclusion_wrong_answer_type"` / 400 (DR-2-23).

All validation failures return `error_code = "invalid_raw_value_shape"` / 400 before any DB write.

### §24 — Canonical `raw_value` shapes (all 18 `AnswerType` DB values, DR-2-17)

| `answer_type` DB value | Client input | Shape | Limit | Notes |
|---|---|---|---|---|
| `short_text` | YES | `{"value": "..."}` | `MAX_FREE_TEXT_CHARS` | Non-empty string |
| `long_narrative` | YES | `{"value": "..."}` | `MAX_FREE_TEXT_CHARS` | Non-empty string |
| `integer` | YES | `{"value": 42}` | — | JSON integer; float/string/bool rejected; `bool` subclass trap — check `isinstance(val, bool)` before `isinstance(val, int)` |
| `decimal` | YES | `{"value": "12.3400"}` | — | Decimal string; JSON float rejected |
| `quantity_with_unit` | YES | `{"value": "12.3400", "unit": "mg"}` | — | Decimal string + unit from `allowed_units`; empty `allowed_units` → any unit rejected |
| `percentage` | YES | `{"value": "12.3400"}` | — | Decimal string; range `0.0000`–`100.0000` inclusive |
| `date` | YES | `{"value": "YYYY-MM-DD"}` | — | ISO 8601 date string only |
| `yes_no` | YES | `{"value": true}` or `{"value": false}` | — | JSON boolean only; strings rejected |
| `yes_no_na` | YES | `{"value": "yes"}` / `{"value": "no"}` / `{"value": "not_applicable"}` | — | Controlled string enum; boolean rejected |
| `single_select` | YES | `{"option": "OPTION_CODE"}` | — | Valid `QuestionOption.code` in pinned version |
| `multi_select` | YES | `{"options": ["CODE_A", "CODE_B"]}` | `MAX_SELECT_OPTIONS` | Sorted ascending; no duplicates; each code valid |
| `fda_record_reference` | YES | `{"public_id": "<uuid>", "record_type": "<type>"}` | — | `record_type` from closed enum; validated against FDA record |
| `formulation_component_reference` | YES | `{"public_id": "<uuid>"}` | — | Must belong to execution's `FormulationVersion` |
| `attachment_reference` | YES | `{"document_version_public_id": "<uuid>"}` | — | Must belong to same tenant; DR-2-06 deletion protection applies |
| `calculated_value` | NO | `null` always | — | Client `raw_value` rejected |
| `calculated_status` | NO | `null` always | — | Client `raw_value` rejected |
| `reviewer_conclusion` | CONDITIONAL | `{"value": "..."}` | `MAX_REVIEWER_CONCLUSION_CHARS` (4 000) | Dedicated endpoint only; `PERM_REVIEW_EXECUTION`; `submitted_for_review` only; amendment requires `correction_reason` |
| `approval_metadata` | NO | `null` in 4D-2 | — | Client `raw_value` rejected; shape defined in 4D-4 |

**`NOT_APPLICABLE` state (any applicable type):** `raw_value = null`, `is_not_applicable = True`, non-empty `not_applicable_reason`. Supported on all types except `calculated_value`, `calculated_status`, and `approval_metadata`.

### §25 — `ReviewerConclusionSerializer`

Used exclusively by `ChecklistReviewerConclusionView`.

```
raw_value:          JSONField (required)
expected_version:   IntegerField (required)
correction_reason:  CharField(max_length=MAX_REVIEWER_CONCLUSION_CHARS, blank=True)
```

Structural validation:
- `raw_value.value` must be a string; trimmed must not be empty.
- `raw_value.value` max `MAX_REVIEWER_CONCLUSION_CHARS` (4 000) Unicode code points. **Not** `MAX_FREE_TEXT_CHARS` (DR-2-29).
- `json.dumps(raw_value)` max `MAX_RAW_VALUE_BYTES` bytes.
- No additional keys in `raw_value`.
- Unknown fields in request body → structured 400.
- `correction_reason` blank accepted structurally; service enforces non-empty on amendment.

Object-level permission and lifecycle checks are enforced in the service (§19), not the serializer.

### §26 — Lifecycle action serializers

- `ReturnSerializer`: `{return_reason: str}` — required, non-empty, max `MAX_RETURN_REASON_CHARS`.
- `ApproveSerializer`: `{reviewer_conclusion_note: str}` — required, non-empty, max `MAX_REVIEWER_CONCLUSION_CHARS` (DR-2-07, DR-2-01). Stored atomically with status transition.
- All other actions: empty body accepted; extra fields rejected with 400.

All serializers validate payload limits against constants in `execution_constants.py` before calling the service. `error_code = "payload_too_large"` / 400 on violation. No silent truncation at any layer (DR-2-01).

---

## Part VII — Views and URLs

### §27 — Execution views

| Class | Method | URL | Permission |
|---|---|---|---|
| `ChecklistExecutionListCreateView` | GET, POST | `/api/regx/v1/iig-checklists/executions/` | list: `view_execution`; create: `create_execution` |
| `ChecklistExecutionDetailView` | GET | `/api/regx/v1/iig-checklists/executions/<uuid>/` | `view_execution` |
| `ChecklistExecutionSubmitView` | POST | `.../executions/<uuid>/submit-review/` | `submit_execution` |
| `ChecklistExecutionApproveView` | POST | `.../executions/<uuid>/approve/` | `approve_execution`; self-approval guard |
| `ChecklistExecutionReturnView` | POST | `.../executions/<uuid>/return/` | `review_execution` |
| `ChecklistExecutionRejectView` | POST | `.../executions/<uuid>/reject/` | `approve_execution` |
| `ChecklistExecutionCancelView` | POST | `.../executions/<uuid>/cancel/` | `cancel_execution` |
| `ChecklistExecutionSupersedeView` | POST | `.../executions/<uuid>/supersede/` | `supersede_execution` |

All lifecycle action views inherit `_ChecklistExecutionActionViewBase`, mirroring `_ChecklistVersionActionViewBase` from 4D-1. Base class:
- Resolves and verifies tenant context.
- Calls `visible_to(tenant)` — generic 404 for cross-tenant access.
- Calls `validate_execution_transition()` — structured 400 on illegal transition; no audit event on failure.
- Delegates to `transition_execution()`.
- Emits audit event only on success (via `transaction.on_commit()`).

`ChecklistExecutionApproveView`: checks `execution.submitted_by == request.user` before calling the service — structured 403 with `error_code = "self_approval_forbidden"`.

### §28 — Response views

| Class | Method | URL | Permission |
|---|---|---|---|
| `ChecklistResponseListView` | GET | `.../executions/<uuid>/responses/` | `view_execution` |
| `ChecklistResponseUpdateView` | PATCH | `.../executions/<uuid>/responses/<uuid>/` | `edit_execution` |
| `ChecklistReviewerConclusionView` | POST | `.../executions/<uuid>/responses/<uuid>/reviewer-conclusion/` | `review_execution` |

`ChecklistReviewerConclusionView`:
- POST only; resolves execution and response by public UUID via tenant-scoped retrieval.
- Validates with `ReviewerConclusionSerializer` (§25).
- Invokes `enter_reviewer_conclusion()` (§19).
- Server-side `PERM_REVIEW_EXECUTION` check enforced inside the service — not solely at the view level.
- Returns updated `ChecklistResponseSerializer` representation including `version`.
- Structured 400/403/409 on all error paths; no raw exception text.

`ChecklistResponseUpdateView` (PATCH) does **not** accept `reviewer_conclusion` answer types. The serializer rejects with `error_code = "reviewer_conclusion_wrong_answer_type"` / 400 (DR-2-23).

### §29 — URL routing

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

## Part VIII — Audit

### §30 — New event types

Add to `IigChecklistEvent` in `backend/iig_checklist/audit.py`:

```python
EXECUTION_CREATED                    = "iig_checklist.execution.created"
EXECUTION_SUBMITTED                  = "iig_checklist.execution.submitted_for_review"
EXECUTION_RETURNED                   = "iig_checklist.execution.returned"
EXECUTION_APPROVED                   = "iig_checklist.execution.approved"
EXECUTION_REJECTED                   = "iig_checklist.execution.rejected"
EXECUTION_CANCELLED                  = "iig_checklist.execution.cancelled"
EXECUTION_SUPERSEDED                 = "iig_checklist.execution.superseded"
RESPONSE_ENTERED                     = "iig_checklist.response.entered"
RESPONSE_UPDATED                     = "iig_checklist.response.updated"
RESPONSE_REVIEWER_CONCLUSION_ENTERED = "checklist_response.reviewer_conclusion_entered"
RESPONSE_REVIEWER_CONCLUSION_UPDATED = "checklist_response.reviewer_conclusion_updated"
```

### §31 — Audit payload conventions

**Lifecycle events:** execution `public_id`, actor email, tenant_id, before/after status.

**Response events (`entered`, `updated`):** execution `public_id`, response `public_id`, `question_public_id`, `data_source_type_snapshot`. Never: `raw_value`, question text, numeric PKs.

**Reviewer-conclusion events:** execution `public_id`, response `public_id`, question `public_id`, actor email, `prior_response_version`, `new_response_version`, `execution_status`, boolean `correction_reason_present`. Never: conclusion text, `raw_value`, `prior_raw_value`, or any regulated conclusion content.

Emit only on success. No audit event on validation failure, illegal transition, authorization denial, or stale-version conflict. All events emitted via `transaction.on_commit()` — never before the transaction commits.

**`response.entered` vs `response.updated` distinction (DR-2-13):**
- `entered`: response `entered_by` was previously null; first value recorded.
- `updated`: `entered_by` was previously non-null; value changed.

---

## Part IX — Error Taxonomy

### §32 — Structured error codes

All errors follow the format (identical to 4D-1):
```json
{"error_code": "<code>", "detail": "<human-readable message>"}
```

| `error_code` | HTTP | Trigger |
|---|---|---|
| `illegal_execution_transition` | 400 | `validate_execution_transition()` raises |
| `execution_already_active` | 409 | Uniqueness violation on non-terminal executions (DR-2-04) |
| `checklist_version_not_active` | 400 | `create_execution()` — version not `active` |
| `formulation_version_not_approved` | 400 | `create_execution()` — FV not `approved` (DR-2-10) |
| `formulation_version_tenant_mismatch` | 400 | FV belongs to different tenant (DR-2-03) |
| `execution_invalid_quantity_unit_config` | 400 | `quantity_with_unit` question has empty `allowed_units` at execution creation (R4-M-2) |
| `incomplete_execution` | 400 | `submit_review` or `approve` completeness gate (DR-2-05) |
| `missing_return_reason` | 400 | `return` action with empty `return_reason` |
| `reviewer_conclusion_required` | 400 | `approve` body missing `reviewer_conclusion_note` (DR-2-07) |
| `self_approval_forbidden` | 403 | `approve` actor is same as `submitted_by` |
| `response_immutable` | 400 | `enter_response` on approved execution |
| `response_delete_forbidden` | 400 | Deletion attempt on non-draft execution response (DR-2-02) |
| `invalid_raw_value_shape` | 400 | `raw_value` does not match `answer_type` canonical shape (DR-2-17) |
| `payload_too_large` | 400 | Any field exceeds limit constant (DR-2-01) |
| `not_applicable_requires_reason` | 400 | `is_not_applicable=True` without reason |
| `document_version_not_found` | 400 | `document_version_public_id` not in tenant (DR-2-06) |
| `reviewer_conclusion_wrong_answer_type` | 400 | `enter_response()` or PATCH receives `reviewer_conclusion` raw value (DR-2-23) |
| `reviewer_conclusion_invalid_state` | 409 | `enter_reviewer_conclusion()` when execution not `submitted_for_review` (DR-2-23) |
| `reviewer_conclusion_permission_denied` | 403 | Actor lacks `PERM_REVIEW_EXECUTION` (DR-2-23) |
| `reviewer_conclusion_invalid_payload` | 400 | `ReviewerConclusionSerializer` validation failure (DR-2-23) |
| `reviewer_conclusion_empty` | 400 | `raw_value` blank after trim (DR-2-23) |
| `reviewer_conclusion_too_long` | 400 | `raw_value` exceeds `MAX_REVIEWER_CONCLUSION_CHARS` (4 000) chars (DR-2-29) |
| `reviewer_conclusion_payload_too_large` | 400 | Outer payload exceeds byte limit (DR-2-23) |
| `reviewer_conclusion_stale_version` | 409 | `expected_version` mismatch (DR-2-23) |
| `reviewer_conclusion_correction_reason_required` | 400 | Amendment with no `correction_reason` (DR-2-23) |
| `reviewer_conclusion_immutable` | 409 | `enter_reviewer_conclusion()` on `approved` or `superseded` execution (DR-2-23) |

---

## Part X — Migration

### §33 — `0002_execution.py`

**This is a documentation-only plan; no migration file is created on the discovery branch. The migration is created on the implementation branch.**

```
backend/iig_checklist/migrations/0002_execution.py

1. CreateModel ChecklistExecution — all fields from §5, including:
   - reviewer_conclusion_note TextField(blank=True, max_length=4000)
   - UniqueConstraint(
       fields=["tenant", "checklist_version", "formulation_version"],
       condition=~Q(status__in=["rejected","cancelled","superseded"]),
       name="unique_active_execution_per_version_formulation",
     )

2. CreateModel ChecklistResponse — all fields from §7, including:
   - version = PositiveIntegerField(default=1)
   - UniqueConstraint(
       fields=["execution", "question"],
       name="unique_response_per_question_per_execution",
     )

3. CreateModel ChecklistResponseHistory — all fields from §8, including:
   - response FK(ChecklistResponse, on_delete=PROTECT)
   - prior_is_not_applicable BooleanField()
   - new_is_not_applicable BooleanField()
   - prior_not_applicable_reason CharField(null=True)
   - new_not_applicable_reason CharField(null=True)
   - correction_reason TextField()
   - amended_by FK(User, on_delete=PROTECT)
   - amended_at DateTimeField(auto_now_add=True)

4. CreateModel CalculationOutcome — all fields from §9.

5. AddIndex(ChecklistExecution, fields=["tenant", "status"])
6. AddIndex(ChecklistExecution, fields=["checklist_version"])
7. AddIndex(ChecklistResponse, fields=["execution"])
8. AddIndex(ChecklistResponseHistory, fields=["response"])
```

**Migration safety:**
- All `CreateModel` operations on new tables. No `ALTER TABLE` on existing 4D-1 tables.
- No data migration.
- `migrate --check` must pass.
- `squashmigrations` must not be run on 4D-2 migrations until after 4D-3 ships.

**Code-level retention controls** (Python, not DB constraints — registered in `IigChecklistConfig.ready()`):
- `ChecklistResponseHistoryManager` — see §8.
- `DeletionProtectionRegistry` hook for `DocumentVersion` referenced by approved executions — see DR-2-06.

---

## Part XI — Import Linter

### §34 — Import linter contract

The `iig_checklist → formulations` direction is permitted (existing contract). The reverse is forbidden. Verify the linter passes after the new FK is added in 4D-2.

```toml
# In backend/pyproject.toml — verify this entry exists:
[[tool.importlinter.contracts]]
name = "iig-checklist-formulation-read-only"
type = "forbidden"
source_modules = ["formulations"]
forbidden_modules = ["iig_checklist"]
```

---

## Part XII — Frontend

### §35 — Execution list page

`frontend/src/app/iig-checklists/executions/page.tsx`

- Fetch `GET /api/regx/v1/iig-checklists/executions/?tenant=<slug>`.
- Display: status badge, checklist version number, formulation version reference, created date.
- "New execution" button → execution create page.
- 401 → `/signin`. 403 → inline error (never `/signin`).

### §36 — Execution create page

`frontend/src/app/iig-checklists/executions/new/page.tsx`

- Two selects: active `ChecklistVersion` (status == active), `FormulationVersion` (tenant-scoped).
- POST on submit → redirect to execution detail on 201.
- 403 → inline error. 409 → "An active execution already exists for this combination."
- No optimistic updates.

### §37 — Execution detail page

`frontend/src/app/iig-checklists/executions/[executionPublicId]/page.tsx`

- Read-only header: status, version reference, formulation version, provenance fields.
- Lifecycle action buttons per status:
  - `draft`/`returned`: Submit for review, Cancel.
  - `submitted_for_review`: Approve (with reviewer_conclusion_note input), Reject, Return (with reason input).
  - `approved`: Supersede.
  - Terminal: no action buttons.
- Mutation 403 → inline `actionError` (never redirect to `/signin`).
- No optimistic status change — `load()` called after successful action.
- No per-question response entry UI in 4D-2.

### §38 — API client additions

`frontend/src/lib/api.ts` — extend `iigChecklists` object:

```typescript
export interface ChecklistExecution {
  publicId: string;
  status: string;
  checklistVersion: { publicId: string; versionNumber: number; status: string };
  formulationVersionPublicId: string;
  createdByEmail: string | null;
  submittedByEmail: string | null;
  submittedAt: string | null;
  returnedByEmail: string | null;
  returnedAt: string | null;
  returnReason: string;
  approvedByEmail: string | null;
  approvedAt: string | null;
  rejectedByEmail: string | null;
  rejectedAt: string | null;
  cancelledByEmail: string | null;
  cancelledAt: string | null;
  reviewerConclusionNote: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChecklistResponse {
  publicId: string;
  questionPublicId: string;
  dataSourceTypeSnapshot: string;
  rawValue: unknown | null;
  isNotApplicable: boolean;
  notApplicableReason: string | null;
  enteredByEmail: string | null;
  enteredAt: string | null;
  confirmedByEmail: string | null;
  confirmedAt: string | null;
  overrideReason: string;
  systemDerivedValue: unknown | null;
  version: number;
}
```

Execution action methods (all return `Promise<ChecklistExecution>`):
`list`, `create`, `get`, `submitReview`, `approve`, `return`, `reject`, `cancel`, `supersede`.

Response methods:
`responses.list`, `responses.update`.

---

## Part XIII — Test Strategy

### §39 — Unit / model tests

`backend/iig_checklist/tests/test_execution_models.py`

**ChecklistExecution:**
- `status` not directly settable outside service.

**ChecklistResponse:**
- `clean()` raises on mutation when `execution.status == "approved"`.
- `full_clean()` provably called: direct `save()` without `full_clean()` on approved execution must fail, proving the defect cannot recur.
- `unique_response_per_question_per_execution`: `IntegrityError` on duplicate `(execution, question)`.
- `unique_active_execution_per_version_formulation`: `IntegrityError` when two non-terminal executions share `(tenant, version, formulation)`.

**Payload limits (DR-2-01):** one test per limit — exactly-at-limit accepted; exactly-over-limit returns `payload_too_large` (not a raw `ValidationError`). Targets: `raw_value`, `return_reason`, `reviewer_conclusion_note`, `not_applicable_reason`.

**`raw_value` shapes (DR-2-17):** one test per `answer_type` (all 18 DB values) — canonical shape accepted; at least one malformed shape rejected with `invalid_raw_value_shape`; `calculated_value`/`calculated_status`/`approval_metadata` reject any client `raw_value`; `decimal`/`percentage` reject JSON float; `yes_no` rejects strings; `yes_no_na` rejects booleans and out-of-set strings; `multi_select` rejects duplicates.

**Integer boolean rejection (DR-2-24):** `{"value": 1}` accepted; `{"value": 0}` accepted; `{"value": true}` rejected; `{"value": false}` rejected; `{"value": 1.0}` rejected; `{"value": "1"}` rejected.

**`quantity_with_unit` allowed-units (DR-2-25, DR-2-32):** unit in `allowed_units` → accepted; unit absent → rejected; empty string → rejected; `allowed_units = []` → any unit rejected; duplicate codes in `allowed_units` rejected; non-`quantity_with_unit` question with non-empty `allowed_units` rejected at governance gate; validation reads from resolved question at validation time.

**`ChecklistResponse.version` (DR-2-23):** default is 1; increments to 2 after first `enter_reviewer_conclusion()`; increments to 3 after amendment.

**`ChecklistResponseHistory` (DR-2-23, DR-2-30, R4-M-4):** created on amendment; `prior_raw_value` equals pre-amendment value; `new_raw_value` equals value written; `prior_is_not_applicable` and `new_is_not_applicable` accurate; `prior_not_applicable_reason` and `new_not_applicable_reason` accurate (R4-M-4); `prior_version`/`new_version` accurate; `correction_reason` non-empty; `amended_by` correct; NOT created on first entry.

**History immutability (DR-2-30, R4-M-1):**
- Instance `.delete()` raises `GovernedHistoryMutationForbidden`.
- Queryset `.filter(...).delete()` raises `GovernedHistoryMutationForbidden`.
- Queryset `.filter(...).update(...)` raises `GovernedHistoryMutationForbidden`.
- `.save()` on existing instance (pk not None) raises `GovernedHistoryMutationForbidden`.
- `.save()` on new instance (pk is None) succeeds.
- `ChecklistResponse` with history: `.delete()` raises `ProtectedError`.

**`ChecklistResponseSerializer` version (DR-2-28):** `GET` returns `version`; initial 1; after first conclusion entry is 2; `PATCH` with `{"version": 99}` rejected with structured 400.

**FormulationVersion status gate (DR-2-10):** `create_execution()` rejects `draft`/`under_review`/`superseded`/`retired` FV with `formulation_version_not_approved`.

**Cross-tenant FV gate (DR-2-03):** `create_execution()` rejects FV from different tenant.

**CalculationOutcome placeholders (DR-2-09):** `SYSTEM_CALCULATED` questions get `status=DATA_REQUIRED` rows; `USER_REQUIRED`/`REVIEWER_CONFIRMED`/`FDA_DERIVED_DEFAULT`/`EVIDENCE_DERIVED` do not.

**`allowed_units` at execution creation (R4-M-2):** `create_execution()` with a `quantity_with_unit` question having `allowed_units = []` → `execution_invalid_quantity_unit_config` / 400; no execution row written; no response rows written.

### §40 — Lifecycle tests

`backend/iig_checklist/tests/test_execution_lifecycle.py`

- Complete legal transition table: all 6 actions × legal source statuses (6 passing paths).
- Complete illegal transitions: every action from every disallowed status → structured error, no DB write, no audit event.
- **`reject` from `draft` succeeds** (R4-M-3).
- **`reject` from `submitted_for_review` succeeds** (R4-M-3).
- **`reject` from `returned`, `approved`, `cancelled`, `rejected`, `superseded` is blocked** (R4-M-3).
- **`cancel` from `draft` succeeds** — direct test (R4-M-3).
- **`cancel` from `returned` succeeds** — direct test (R4-M-3).
- **`cancel` from `approved`, `submitted_for_review`, `cancelled`, `rejected`, `superseded` is blocked** (R4-M-3).
- **`supersede` from `approved` succeeds** — direct test (R4-M-3).
- **`supersede` from any non-`approved` status is blocked** (R4-M-3).
- Terminal states (`rejected`, `cancelled`, `superseded`) cannot transition — 3 direct tests (R4-M-3).
- Self-approval guard: `submitted_by == actor` on `approve` → 403, no transition.
- `submit_review` completeness pre-condition: incomplete execution → structured 400.
- `approve` completeness and reviewer-conclusion gate.
- `return` requires `return_reason` in body.
- Concurrent `approve`: two threads simultaneously; exactly one succeeds; no double approval. Test uses `transaction=True` and real threads.

### §41 — API tests

`backend/iig_checklist/tests/test_execution_api.py`

- UUID-only responses on all endpoints (no numeric PKs).
- Generic 404 (not 403) when Tenant A requests Tenant B's execution.
- `status` not patchable via any PATCH endpoint.
- Illegal transition via lifecycle endpoint → structured 400.
- `reviewer_conclusion_note` required at `approve` → `reviewer_conclusion_required` / 400 when missing.
- Bounded pagination on list endpoint.
- 401/403 handling consistent with 4D-1 conventions.

### §42 — Response tests

`backend/iig_checklist/tests/test_response_api.py`

- `raw_value` accepted for each of the 18 `answer_type` shapes; malformed → structured 400.
- `is_not_applicable = True` + `raw_value = null` → accepted.
- `is_not_applicable = True` + non-null `raw_value` → rejected.
- `not_applicable_reason` required when `is_not_applicable = True`.
- `REVIEWER_CONFIRMED` response blocks `submit_review` when `confirmed_by` unset.
- Mutation after `approved` → 400.
- `document_version_public_id` validated for tenant ownership.

### §43 — Reviewer-conclusion tests

`backend/iig_checklist/tests/test_reviewer_conclusion_api.py`

**First entry:**
- `submitted_for_review` + `PERM_REVIEW_EXECUTION` + valid payload → accepted; `response.version` = 2; no history row.
- Actor lacking `PERM_REVIEW_EXECUTION` → 403; no history; no audit.
- `draft` → `reviewer_conclusion_invalid_state` / 409.
- `returned` → `reviewer_conclusion_invalid_state` / 409; existing value retained.
- `approved` → `reviewer_conclusion_immutable` / 409.
- `superseded` → `reviewer_conclusion_immutable` / 409.
- Empty string → `reviewer_conclusion_empty` / 400.
- Exactly 4 000 chars → accepted.
- 4 001 chars → `reviewer_conclusion_too_long` / 400 (DR-2-29).
- Stale `expected_version` → `reviewer_conclusion_stale_version` / 409; no history row; no audit.
- Concurrent stale write simulation (two threads) → exactly one succeeds; one 409; one history row total.
- Wrong `answer_type` (non-`reviewer_conclusion`) → raises immediately.

**Amendment:**
- With `correction_reason`: `response.version` increments; one history row inside same transaction; `prior_raw_value`, `new_raw_value`, `prior_version`, `new_version`, `prior_entered_by`, `amended_by`, `amended_at`, `correction_reason` correct.
- `prior_is_not_applicable`, `new_is_not_applicable`, `prior_not_applicable_reason`, `new_not_applicable_reason` accurately captured in history row (R4-M-4).
- Stale `expected_version` on amendment → 409; zero history rows for that attempt.
- Without `correction_reason` → `reviewer_conclusion_correction_reason_required` / 400; no DB write.
- Multiple amendments → multiple history rows; `prior_version`/`new_version` chain is contiguous.

**Returned / resubmitted / superseded lifecycle (DR-2-33):**
- Execution `returned` after conclusion exists: value retained; no history on return transition.
- While `returned`: `enter_reviewer_conclusion()` → `reviewer_conclusion_invalid_state` / 409; unchanged.
- Execution resubmitted (→ `submitted_for_review`): reviewer may amend; requires `correction_reason`; history row created with `prior_raw_value` from before resubmission.
- Execution `superseded`: `enter_reviewer_conclusion()` → `reviewer_conclusion_immutable` / 409; no history; no audit.

**Endpoint tests:**
- Happy-path 200: response body includes updated `version`.
- Non-reviewer → 403. Wrong state → 409. Missing `raw_value` → 400. Missing `expected_version` → 400.
- Response UUID in different execution → 404. Cross-tenant response → 404.
- `enter_response()` rejects `reviewer_conclusion` payload → `reviewer_conclusion_wrong_answer_type` / 400.
- `ChecklistResponseUpdateView` PATCH rejects `reviewer_conclusion` payload → 400.
- `GET responses/<uuid>/` exposes `version`; initial 1; after first entry 2.
- `PATCH` with `{"version": 99}` → structured 400.

**Audit tests:**
- `checklist_response.reviewer_conclusion_entered` emitted on first entry; payload contains execution `public_id`, response `public_id`, question `public_id`, actor email, `prior_response_version`, `new_response_version`, `execution_status`; does NOT contain conclusion text.
- `checklist_response.reviewer_conclusion_updated` emitted on amendment; `correction_reason_present=True`; does NOT contain text or `prior_raw_value`.
- No audit event on any failure path.

### §44 — Platform-authorization pin test

A dedicated test confirms that `can_mutate_definition_scope()` and `can_author_platform_master()` are never called during any execution or response path. Regression guard for the 4D-1 authorization boundary.

### §45 — Docker integration test

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
    # Verify audit trail (execution.created, submitted×2, returned, approved,
    #   response.entered, response.updated events present)
    # Verify cross-tenant 404 (Tenant B cannot see Tenant A's execution)
    # Attempt cancel on approved → verify 400 (illegal transition)
```

---

## Part XIV — API Response Contracts

### §46 — Response shapes

**`POST /executions/` (201):** `ChecklistExecutionSerializer` representation.
**`GET /executions/<uuid>/` (200):** `ChecklistExecutionSerializer` representation.
**`POST /executions/<uuid>/approve/` (200):** updated `ChecklistExecutionSerializer`.
**`POST /executions/<uuid>/responses/<uuid>/reviewer-conclusion/` (200):** `ChecklistResponseSerializer` including updated `version`.

**All 400/403/409 responses:**
```json
{"error_code": "<code>", "detail": "<human-readable message>"}
```

No raw exception text. No Python tracebacks. No internal IDs. No storage keys.

---

## Part XV — Rollback

### §47 — Rollback strategy

4D-2 adds new tables only. Rollback: `python manage.py migrate iig_checklist 0001` — drops `ChecklistExecution`, `ChecklistResponse`, `ChecklistResponseHistory`, `CalculationOutcome` with no effect on 4D-1 data. Frontend pages are new routes; removing them does not affect 4D-1 pages. No 4D-1 migration or model is modified.

---

## Part XVI — Acceptance Criteria

### §48 — Acceptance criteria

4D-2 is complete when all of the following pass:

1. All unit, lifecycle, API, response, and payload-limit tests pass.
2. Docker integration test "IIG checklist execution foundation flow" passes.
3. `migrate --check` passes with `0002_execution.py` applied.
4. Import-linter contracts all pass (`formulations` does not import `iig_checklist`).
5. Frontend execution list, create, and detail pages render without console errors; lifecycle actions update status correctly; mutation 403 shows inline error.
6. `ChecklistResponse.clean()` is provably called on every `save()` path — a test that calls `save()` directly without `full_clean()` on an approved execution must fail. Pins acceptance criterion against the `AssessmentSnapshot` defect pattern.
7. Payload-limit tests pass: at-limit accepted, over-limit returns `payload_too_large` / 400 with no DB write (DR-2-01).
8. `create_execution()` rejects non-approved `FormulationVersion` with `formulation_version_not_approved` (DR-2-10).
9. Cross-tenant formulation version reference rejected with `formulation_version_tenant_mismatch` (DR-2-03).
10. `DeletionProtectionRegistry` hook registered; test verifies that attempting to delete a `DocumentVersion` referenced by an approved execution raises `DocumentVersionDeleteForbidden` (DR-2-06).
11. No Critical or Major findings in the independent implementation review.
12. All 33 design decisions from `docs/MILESTONE_4D_2_DESIGN_REMEDIATION.md` referenced in the implementation PR description.
13. `enter_reviewer_conclusion()` callable only when `execution.status=submitted_for_review`; all other states return appropriate structured error (DR-2-23).
14. `enter_response()` and `ChecklistResponseUpdateView` reject `reviewer_conclusion` raw values with `reviewer_conclusion_wrong_answer_type` / 400 (DR-2-23).
15. Integer `true`/`false` is rejected with `invalid_raw_value_shape`; integers 0 and 1 are accepted (DR-2-24).
16. `quantity_with_unit` validation uses `question.allowed_units` from pinned question; absent unit rejected (DR-2-25).
17. All reviewer-conclusion tests in §43 pass — optimistic-locking stale-version, `ChecklistResponseHistory` creation on amendment with correct version chain, returned/resubmitted/superseded lifecycle (DR-2-26, DR-2-33).
18. `ChecklistResponseHistory` is append-only: instance `.delete()`, queryset `.delete()`/`.update()`/`.bulk_update()`, and `.save()` on existing instance raise `GovernedHistoryMutationForbidden`; `ChecklistResponse` with history cannot be deleted (R4-M-1, DR-2-30).
19. `ChecklistResponseSerializer` exposes `version` (read-only); initial value 1; successful reviewer-conclusion write returns new version; `version` not writable through `ChecklistResponseUpdateSerializer` (DR-2-28).
20. `reviewer_conclusion` raw_value of exactly 4 000 chars accepted; 4 001 chars returns `reviewer_conclusion_too_long` / 400 (DR-2-29).
21. `quantity_with_unit` question with `allowed_units = []` causes `create_execution()` to fail with `execution_invalid_quantity_unit_config` / 400; response validation rejects any unit when frozen list is empty (R4-M-2, DR-2-32).
22. Failed stale-version amendment creates zero `ChecklistResponseHistory` rows and emits zero audit success events (DR-2-27).
23. Direct tests confirm: `reject` from `draft` succeeds; `cancel` from `draft` succeeds; `supersede` from `approved` succeeds; terminal states (`rejected`, `cancelled`, `superseded`) cannot transition (R4-M-3).
24. `ChecklistResponseHistory` rows accurately capture `prior_is_not_applicable`, `new_is_not_applicable`, `prior_not_applicable_reason`, `new_not_applicable_reason` in amendment tests (R4-M-4).

---

## Part XVII — Implementation Sequence

### §49 — Recommended implementation order

1. `execution_constants.py` — constants only; no model dependencies.
2. `ExecutionStatus` enum, `execution_transitions.py`, `IllegalExecutionTransition`.
3. `GovernedHistoryMutationForbidden`, `ChecklistResponseHistoryManager`.
4. Models: `ChecklistExecution`, `ChecklistResponse`, `ChecklistResponseHistory`, `CalculationOutcome`.
5. `ChecklistExecutionManager.visible_to(tenant)`.
6. Migration `0002_execution.py`.
7. `DeletionProtectionRegistry` hook registration in `IigChecklistConfig.ready()`.
8. Permissions — 8 new codenames, `ROLE_PERMISSIONS` extension.
9. Exception classes: `ChecklistVersionNotActive`, `FormulationVersionNotApproved`, `FormulationVersionTenantMismatch`, `ExecutionAlreadyActive`, `ResponseDeleteForbidden`, `ExecutionAlreadyActive`.
10. Service: `create_execution()` (with R4-M-2 validation).
11. Service: `transition_execution()` with all pre-condition checks.
12. Service: `enter_response()`.
13. Service: `enter_reviewer_conclusion()` (two-phase, DR-2-27).
14. Serializers (all from §20–§26).
15. Views (all from §27–§28).
16. URL routing (§29).
17. New `IigChecklistEvent` types in `audit.py`.
18. Tests (§39–§44 order; lifecycle first, then API, then reviewer-conclusion).
19. Docker integration step (§45).
20. Frontend pages (§35–§38).
21. Import-linter verification.
22. Migration safety check (`migrate --check`).

---

## Part XVIII — Traceability Matrix

### §50 — Design remediation traceability (DR-2-01 through DR-2-33)

| DR ref | Finding | Spec sections | Status |
|---|---|---|---|
| DR-2-01 | Unbounded payload fields | §4, §26, §32, §48 AC7 | CLOSED |
| DR-2-02 | CalculationOutcome cascade and response deletion | §7, §9, §32 | CLOSED |
| DR-2-03 | Live FK to FormulationVersion with PROTECT | §5, §16, §32, §34 | CLOSED |
| DR-2-04 | Non-terminal uniqueness constraint | §5, §33 | CLOSED |
| DR-2-05 | Completeness gate at both submit_review and approve | §12, §40 | CLOSED |
| DR-2-06 | DeletionProtectionRegistry hook | §1, §7, §32, §45, §48 AC10 | CLOSED |
| DR-2-07 | reviewer_conclusion_note required at approve | §12, §26, §40, §41, §48 AC13 | CLOSED |
| DR-2-08 | Eager, applicability-filtered response creation | §1, §16 | CLOSED |
| DR-2-09 | CalculationOutcome DATA_REQUIRED placeholders | §9, §16, §39 | CLOSED |
| DR-2-10 | FormulationVersion must be approved | §16, §32, §39, §48 AC8 | CLOSED |
| DR-2-11 | Applicability freeze via 4D-1 immutability | §7 | CLOSED |
| DR-2-12 | raw_value JSONField with strict validation | §7, §23, §24 | CLOSED |
| DR-2-13 | response.entered vs response.updated distinction | §31, §43 | CLOSED |
| DR-2-14 | (N/A — renumbered) | — | CLOSED |
| DR-2-15 | (N/A — renumbered) | — | CLOSED |
| DR-2-16 | Lock ordering at execution creation | §16 | CLOSED |
| DR-2-17 | Canonical raw_value shapes for all 18 AnswerType values | §23, §24 | CLOSED |
| DR-2-18 | SYSTEM_CALCULATED classification drives CalculationOutcome | §9, §16 | CLOSED |
| DR-2-19 | reject from draft is legal | §11, §40, §48 AC23 | CLOSED |
| DR-2-20 | (N/A) | — | CLOSED |
| DR-2-21 | (N/A) | — | CLOSED |
| DR-2-22 | (N/A) | — | CLOSED |
| DR-2-23 | Reviewer-conclusion dedicated path, optimistic locking | §8, §18, §19, §22, §25, §28, §32, §43, §48 | CLOSED |
| DR-2-24 | Python bool/int subclass trap | §23, §39, §48 AC15 | CLOSED |
| DR-2-25 | allowed_units frozen at validation time | §23, §24, §39, §48 AC16 | CLOSED |
| DR-2-26 | enter_reviewer_conclusion lifecycle tests | §43 | CLOSED |
| DR-2-27 | Transaction ordering: execution lock, response lock, history inside same transaction | §8, §19, §43, §48 AC22 | CLOSED |
| DR-2-28 | version exposed in ChecklistResponseSerializer, not writable in update serializer | §22, §23, §39, §43, §48 AC19 | CLOSED |
| DR-2-29 | reviewer_conclusion char limit = MAX_REVIEWER_CONCLUSION_CHARS (4 000) | §4, §25, §43, §48 AC20 | CLOSED |
| DR-2-30 | ChecklistResponseHistory append-only, on_delete=PROTECT | §8, §33, §39, §43, §48 AC18 | CLOSED |
| DR-2-31 | Migration plan for four models | §33 | CLOSED |
| DR-2-32 | Empty allowed_units strictly invalid for quantity_with_unit | §10, §23, §24, §48 AC21 | CLOSED |
| DR-2-33 | Reviewer-conclusion lifecycle: returned/resubmitted/superseded | §43, §48 AC17 | CLOSED |

### §51 — Fourth-review minor findings traceability (R4-M-1 through R4-M-4)

| Review finding | Description | Spec sections | Status |
|---|---|---|---|
| R4-M-1 | `ChecklistResponseHistory` instance save protection not specified | §8 (full immutability controls block), §48 AC18 | CLOSED |
| R4-M-2 | `allowed_units` enforcement scope for `create_execution()` not specified | §10, §16 step 4, §39, §48 AC21 | CLOSED |
| R4-M-3 | No direct tests for `rejected`, `cancelled`, `approved`, `superseded` states | §40, §48 AC23 | CLOSED |
| R4-M-4 | No direct tests for `prior_is_not_applicable`, `new_is_not_applicable`, `prior_not_applicable_reason`, `new_not_applicable_reason` | §8 (field list), §19 step 14, §43, §48 AC24 | CLOSED |

---

## Appendix — Relationships to Future Milestones

| Milestone | What it builds on from 4D-2 |
|---|---|
| 4D-3 | `ChecklistResponse` eager rows populated with `FDA_DERIVED_DEFAULT`; `CalculationOutcome` rows computed using `iid_assessment.calculations`; recalculation on `USER_REQUIRED` change; `REVIEWER_CONFIRMED` auto-populated where confidence is high |
| 4D-4 | Override/deviation workflow on `ChecklistResponse`; controlled JSON/CSV export with SHA-256; `_csv_safe_cell()` promotion; `approval_metadata` shape defined; real regulatory checklist content |

4D-2 must not pre-implement any 4D-3 or 4D-4 feature, even partially.

---

*End of Milestone 4D-2 Implementation Specification.*
*All findings closed. All open questions resolved. Ready for implementation branch.*
