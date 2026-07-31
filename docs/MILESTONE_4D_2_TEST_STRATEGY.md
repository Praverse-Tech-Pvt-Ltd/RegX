# Milestone 4D-2 Test Strategy

## Overview

Tests are organized across four layers matching the existing project conventions.

## Layer 1: Model / Constraint Tests

**File:** `backend/iig_checklist/tests/test_execution_models.py`

Coverage:
- `ChecklistExecution` partial unique constraint: active executions blocked,
  terminal-status executions unlock the constraint (rejected, cancelled, superseded)
- `ChecklistExecution.visible_to(tenant)` filters by tenant FK
- `ChecklistResponse.clean()`: `is_not_applicable` requires reason; N/A with
  `raw_value` rejected; payload byte-limit enforced; immutability when execution
  is not in `draft` or `returned`
- `ChecklistResponseHistory` immutability: `save()` on existing row, `delete()`
  on row, queryset `.update()`, queryset `.delete()` — all raise
  `GovernedHistoryMutationForbidden`
- `CalculationOutcome.clean()`: invalid `calculation_name` rejected; valid name
  accepted

## Layer 2: Lifecycle / Service Tests

**Files:**
- `backend/iig_checklist/tests/test_execution_lifecycle.py`
- `backend/iig_checklist/tests/test_reviewer_conclusion_api.py`

Coverage:
- Pure transition table: all 7 legal transitions produce correct resulting status
- Unknown action raises `IllegalExecutionTransition`
- Illegal from-state raises `IllegalExecutionTransition`
- Terminal statuses cannot be transitioned out of
- Self-approval guard: `submitted_by == actor` raises `SelfApprovalForbidden`
- Different-user approval succeeds
- Double-approval raises `IllegalExecutionTransition` (not a silent noop)
- Reviewer-conclusion first entry, amendment with history row, amendment without
  `correction_reason` rejected, stale `expected_version` rejected, wrong execution
  state rejected

## Layer 3: API Tests

**Files:**
- `backend/iig_checklist/tests/test_execution_api.py`
- `backend/iig_checklist/tests/test_response_api.py`

Coverage:
- UUID-only external identifiers (`public_id` present, `id`/`pk` absent)
- Cross-tenant access returns generic 404
- `status` field is not patchable via the detail endpoint
- Permission segregation: reviewer cannot create; doer cannot approve
- Action endpoints: submit/cancel/approve (with and without conclusion note)/
  return (with and without reason)/reject — status codes and resulting status
- Response PATCH: `raw_value` accepted, `version` read-only, `reviewer_conclusion`
  answer type rejected on normal response PATCH endpoint, N/A + reason accepted
- Response immutability when execution is not mutable

## Layer 0: Response Shape Validation

**File:** `backend/iig_checklist/tests/test_response_validation.py`

Unit tests (no DB, except the reference-type existence checks) for
`response_validation.validate_raw_value_shape()` covering all 18 `AnswerType`
DB values (DR-2-17, §23/§24): canonical shape accepted, malformed shape
rejected with `InvalidRawValueShape`; `integer` bool/int subclass trap
(DR-2-24); `quantity_with_unit` allowed-units enforcement including empty
`allowed_units` (DR-2-25, DR-2-32); `decimal`/`percentage` reject JSON float;
`percentage` range bounds; `yes_no` rejects strings; `yes_no_na` rejects
booleans and out-of-set strings; `single_select`/`multi_select` option-code
validation when `question.validation_rule["options"]` is defined;
`multi_select` duplicate/sort/empty-list rejection; `calculated_value`/
`calculated_status`/`approval_metadata` reject any client `raw_value`;
`reviewer_conclusion` rejected via this path (dedicated endpoint only);
`fda_record_reference`/`formulation_component_reference`/`attachment_reference`
existence and shape checks.

## Layer 4: Deletion Protection

**File:** `backend/documents/tests/test_deletion_protection.py`

Coverage:
- Registry unit tests: blocking, non-blocking, idempotent register, unregister,
  fail-closed on checker exception, sorted iteration order, multiple blocking
  checkers, `_isolated()` state restoration
- `DocumentVersion.delete()` blocked when checker returns `True`
- `DocumentVersion.delete()` allowed when no checkers or checker returns `False`
- `DocumentVersion.delete()` blocked when checker raises (fail-closed)
- `DocumentVersion.objects.filter(...).delete()` (queryset/bulk delete)
  blocked when any row in the queryset is blocked, even if other rows in the
  same queryset are not; no partial deletion
- `Document.delete()` blocked when any of its versions is referenced by
  governed content (cascade protection)
- `Document.objects.filter(...).delete()` blocked under the same condition
- Import guard: `documents.deletion_protection` does not import `iig_checklist`,
  verified via AST import-node inspection (not substring search, which
  false-positives on the module's own docstring)

## Layer 5: Frontend / Playwright

**File:** `frontend/e2e/iig-checklist-executions.spec.ts`

All tests use deterministic `page.route` mocks — no live backend required.

Coverage:
- Execution list: empty state, multi-row render, 401 redirects to `/signin`,
  403 shown inline (never redirected)
- New execution: form renders, 201 redirects to detail, 409 conflict inline,
  403 inline
- Execution detail: draft renders submit/cancel buttons; `submitted_for_review`
  renders approve/return/reject; approve disabled until conclusion note filled;
  `approved` renders only supersede; terminal statuses render no action buttons;
  `returned` shows return reason and resubmit; 403 action error inline (never
  redirects to `/signin`)

## Layer 6: Docker Integration

**File:** `.github/workflows/docker-integration.yml`

Added three steps:
1. Execution frontend routes return HTTP 200 (list, new)
2. Execution API routes wired (401/403, not 404) for list and create
3. 8-step smoke flow: create execution, duplicate rejected (409), submit-review,
   return, resubmit, approve with conclusion note, cross-tenant isolation (404)

## What Is Not Covered Here

- Dynamic applicability evaluation (deferred to 4D-3)
- `CalculationOutcome` population (placeholder; 4D-3)
- Concurrent-lock timing tests (covered by advisory note in spec; race is
  prevented by `select_for_update()` inside `transaction.atomic()`)
