# Milestone 4D-2 Implementation Notes

## Scope

Milestone 4D-2 adds the `ChecklistExecution` lifecycle to the existing
IIG checklist definition-governance domain (Milestone 4D-1). The feature
implements seven-status execution lifecycle governance for IIG checklists
against approved formulation versions, with pre-created response slots,
reviewer-conclusion entry with governed amendment history, and deletion
protection for referenced document versions.

## Architecture Decisions

### Dependency Direction
`documents` never imports `iig_checklist`. The `DeletionProtectionRegistry`
in `backend/documents/deletion_protection.py` is a process-wide callable
registry. `iig_checklist` registers its checker from `IigChecklistConfig.ready()`
— keeping the import direction one-way.

### Tenant Guard Ordering
In `create_execution()`, the FormulationVersion tenant guard runs **before**
the status guard. This prevents information leakage (a wrong-tenant actor
must not learn whether a formulation version is approved or not).

### Optimistic Locking on ChecklistResponse.version
`ChecklistResponse.version` starts at 1 and increments on every
reviewer-conclusion write. The `enter_reviewer_conclusion()` service
validates `expected_version == locked_response.version` inside the
transaction. Concurrent submitters receive `ReviewerConclusionStaleVersion`.

### Append-Only History
`ChecklistResponseHistory` rows are immutable after creation. The model's
`save()` raises `GovernedHistoryMutationForbidden` if `pk is not None`.
The custom `_ImmutableHistoryQuerySet` raises on `.update()`, `.delete()`,
and `.bulk_update()`.

### Partial Unique Constraint
`ChecklistExecution` has a partial UniqueConstraint on
`(tenant, checklist_version, formulation_version)` where
`status NOT IN ('rejected', 'cancelled', 'superseded')`. Terminal-status
executions do not block new executions for the same combination.

### raw_value Shape Validation (DR-2-17)
`backend/iig_checklist/response_validation.py` is the single authoritative
module for canonical `raw_value` shape validation across all 18 `AnswerType`
DB values (spec §23/§24). `ChecklistResponseUpdateSerializer.validate()`
calls `validate_raw_value_shape()` with the question, execution, and tenant
in context before any DB write; failures return
`error_code = "invalid_raw_value_shape"` / 400. Notable rules: JSON `bool` is
rejected for `integer` even though `bool` is an `int` subclass in Python
(`isinstance(val, bool)` checked before `isinstance(val, int)`, DR-2-24);
`quantity_with_unit` validates the unit against `question.allowed_units`,
rejecting every unit when the list is empty (DR-2-32); `single_select` and
`multi_select` validate option codes against `question.validation_rule["options"]`
when the checklist author has defined one (this codebase has no dedicated
`QuestionOption` model, so option codes are authored into `validation_rule`);
`fda_record_reference` validates `record_type` against the closed
`FDA_RECORD_TYPES` set in `execution_constants.py` and checks existence
against the corresponding `fda_data` model.

### DocumentVersion Deletion Protection — QuerySet and Cascade Coverage
The original `DocumentVersion.delete()` instance override (`backend/documents/models.py`)
consulted `DeletionProtectionRegistry` but could be bypassed by
`DocumentVersion.objects.filter(...).delete()` (Django's queryset-level bulk
delete never calls the instance method) and by cascading through
`Document.delete()` (`DocumentVersion.document` is `on_delete=CASCADE`).
`backend/documents/managers.py` now defines `_ProtectedDocumentVersionQuerySet`
and `_ProtectedDocumentQuerySet`, both overriding `.delete()` to check every
row (for `Document`, every version of every document in the queryset) against
`DeletionProtectionRegistry` before delegating to `super().delete()`; a single
blocked row fails the whole call, so no partial deletion occurs. `Document.delete()`
gained the same instance-level guard as `DocumentVersion.delete()`. Deleting a
`Tenant` (which cascades to `Document` then to `DocumentVersion`) is out of
scope for this protection — the M4D2-F-3 finding was specifically about
`DocumentVersion` queryset/bulk delete and parent-`Document` cascade, not
higher-level cascade chains.

## Files Changed

| File | Change |
|------|--------|
| `backend/iig_checklist/execution_constants.py` | NEW — payload-limit constants |
| `backend/iig_checklist/enums.py` | Added `ExecutionStatus`, `CalculationStatus`, `TERMINAL_EXECUTION_STATUSES` |
| `backend/iig_checklist/execution_transitions.py` | NEW — transition table + `IllegalExecutionTransition` |
| `backend/iig_checklist/models.py` | Added `ChecklistExecution`, `ChecklistResponse`, `ChecklistResponseHistory`, `CalculationOutcome` |
| `backend/iig_checklist/migrations/0002_execution.py` | Generated migration |
| `backend/iig_checklist/permissions.py` | Added 8 execution permission codenames + DRF permission classes |
| `backend/iig_checklist/services.py` | Added `create_execution`, `transition_execution`, `enter_reviewer_conclusion`, `_check_execution_completeness` |
| `backend/iig_checklist/audit.py` | Added 11 execution audit event types |
| `backend/iig_checklist/apps.py` | Registers deletion-protection checker in `ready()` |
| `backend/iig_checklist/serializers.py` | Added execution + response serializers; `ChecklistResponseUpdateSerializer` now validates raw_value shape via `response_validation.py` |
| `backend/iig_checklist/response_validation.py` | NEW — canonical `raw_value` shape validation for all 18 `AnswerType` values (DR-2-17) |
| `backend/iig_checklist/views.py` | Added 10 execution + response views; action views now use action-specific outer permission classes; `ChecklistResponseUpdateView` passes question/execution/tenant context to the serializer |
| `backend/iig_checklist/urls.py` | Added 12 URL patterns |
| `backend/documents/deletion_protection.py` | NEW — `DeletionProtectionRegistry` |
| `backend/documents/managers.py` | `TenantScopedManager`/`VersionTenantScopedManager` now built on protected querysets that consult the registry on `.delete()` |
| `backend/documents/models.py` | `DocumentVersion.delete()` and `Document.delete()` both consult registry |
| `frontend/src/lib/api.ts` | Added `ChecklistExecution`, `ChecklistResponse` types + API namespace |
| `frontend/src/app/iig-checklists/executions/page.tsx` | NEW — execution list page |
| `frontend/src/app/iig-checklists/executions/new/page.tsx` | NEW — create execution page |
| `frontend/src/app/iig-checklists/executions/[executionPublicId]/page.tsx` | NEW — execution detail page |

## Known Scope Exclusions (deferred to 4D-3)

- Dynamic applicability evaluation (all questions treated as applicable in 4D-2)
- `CalculationOutcome` population (created with `status=data_required` as placeholder)
- PDF/document evidence attachment to responses
