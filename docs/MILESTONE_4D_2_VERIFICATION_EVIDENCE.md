# Milestone 4D-2 — Verification Evidence

Branch: `regx/feat/milestone-4d-2-execution-foundation`
Date: 2026-08-03

---

## Remediation summary

### M4D2-B-1: ProductDevelopmentRecord fixture field names

**Root cause.** Six backend test files and the Docker CI workflow created
`ProductDevelopmentRecord` objects using non-existent fields (`name`,
`administration_route`) instead of the model's actual fields
(`proposed_product_name`, `active_ingredient`, `route`).

**Fix.** All six `iig_checklist/tests/test_execution_*.py` and
`test_response*.py` and `test_reviewer_conclusion_api.py` files corrected.
Docker `docker-integration.yml` inline script corrected.

**Commit.** `139999a` — test: correct 4D-2 formulation fixtures

---

### M4D2-F-1: Frontend snake_case/camelCase mismatch

**Root cause.** `apiRequest<T>()` returns Django snake_case JSON verbatim.
UI components expected camelCase (`publicId`, `checklistVersion.versionNumber`).
There was no mapping layer.

**Fix.** Introduced `frontend/src/lib/api/execution-mappers.ts` with
`ChecklistExecutionDTO` / `ChecklistExecution` types and `toChecklistExecution()` /
`toChecklistResponse()` mapper functions. All `iigChecklists.executions.*` API
calls in `api.ts` now pipe through the mapper at a single boundary.

**Unit tests.** 9 new Vitest tests in
`frontend/tests/unit/execution-mappers.test.ts` covering:
- top-level snake_case → camelCase mapping
- nested `checklistVersion` mapping
- nullable timestamp fields
- no residual `_` keys on mapped result
- rejected/cancelled/returned state fields

**Commit.** `51e496a` — fix: align execution frontend API field mapping

---

### M4D2-B-2: Python 3.13 date.fromisoformat() accepts non-calendar formats

**Root cause.** Python 3.13's `date.fromisoformat()` accepts week-date notation
(`2026-W31-1`) and compact notation (`20260803`), which are valid ISO 8601 but
not YYYY-MM-DD calendar dates. The `_validate_date()` function accepted them.

**Fix.** Added `_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")` guard before
calling `date.fromisoformat()` in `backend/iig_checklist/response_validation.py`.

**Commit.** `d929cee` — fix: enforce strict YYYY-MM-DD date format

---

### M4D2-F-2: Playwright route priority (wildcard vs exact)

**Root cause.** In detail page tests, the wildcard route
`exec-e2e-1/**` was registered AFTER the exact GET `exec-e2e-1/`.
Playwright evaluates routes last-registered-first, so the wildcard
intercepted the initial GET before the exact route could handle it,
returning `{}` instead of the execution fixture.

**Fix.** Reordered all detail page route registrations: wildcard first
(lowest priority), exact GET last (highest priority).

**Commit.** `7f017a3` — test: resolve remaining browser-suite Playwright failures

---

### M4D2-F-3: Playwright strict-mode violation on getByText('returned')

**Root cause.** `page.getByText('returned')` uses case-insensitive substring
matching by default. With a `returned` status and rendered `Returned by` /
`Returned at` row headers, three elements matched and Playwright's strict mode
rejected the multi-element locator.

**Fix.** Changed assertion to `page.getByRole('cell', { name: 'returned' })`
which uniquely identifies the status table cell.

**Commit.** `7f017a3` — test: resolve remaining browser-suite Playwright failures

---

## Verification results

### Frontend (Vitest unit tests)

```
Test Files  7 passed (7)
      Tests  131 passed (131)
   Duration  19.17s
```

### Frontend (Playwright e2e)

```
88 passed (12.4s)
```
Includes 15/15 execution-suite tests (`iig-checklist-executions.spec.ts`).

### Backend (pytest)

```
920 passed, 0 failed, 0 error
Coverage: 93.09%
```

### Import-linter

```
7/7 contracts clean
```

### Django system check

```
0 issues
```

### TypeScript

```
0 errors (tsc --noEmit)
```

---

## F6 Remediation summary (2026-08-03)

### F6-F-1: ChecklistResponse.clean() blocked governed reviewer conclusions

**Root cause.** `clean()` raised `response_immutable` for ALL non-`{draft,returned}`
statuses, including `submitted_for_review`. This blocked
`enter_reviewer_conclusion()` from writing RC responses during review.

**Fix.** Exempt `answer_type == reviewer_conclusion` when
`execution.status == submitted_for_review`. All terminal statuses
(`approved`, `rejected`, `cancelled`, `superseded`) and all other answer
types remain unconditionally immutable.

**File.** `backend/iig_checklist/models.py` (`ChecklistResponse.clean()`)

**Commit.** `37d0f78` — fix: permit governed reviewer conclusions during review

---

### F6-F-2: Response-list endpoint returned plain list instead of paginated envelope

**Root cause.** `ChecklistResponseListView.get()` returned
`Response(serializer.data)` directly, without pagination.

**Fix.** Added `_Pagination` (existing `PageNumberPagination` helper,
`page_size=25`) to `ChecklistResponseListView`. Response is now
`{count, results, next, previous}`.

**File.** `backend/iig_checklist/views.py` (`ChecklistResponseListView`)

**Commit.** `4860d27` — fix: align execution response-list API contract…

---

### F6-F-3: Cross-tenant execution retrieval leaked object existence via 403

**Root cause.** Class-level `permission_classes` on execution views fired
before the view method ran, returning 403 even when the public_id belonged
to a different tenant's execution. The 403 revealed that an object with
that ID existed.

**Fix.** Removed class-level `permission_classes` from all execution views.
Each handler now calls `_get_execution_or_404(public_id, tenant)` first
(uses `visible_to(tenant)` → `DoesNotExist` → 404 for cross-tenant IDs),
then checks permission inline.

**Files.** `backend/iig_checklist/views.py` (all execution detail/action/response views)

**Commit.** `4860d27` — fix: align execution response-list API contract…

---

### F6-T-1: Self-approval test fired PermissionDenied before SelfApprovalForbidden

**Root cause.** `user_a` (doer role) was used as both submitter and
approver-attempt. `doer` lacks `PERM_APPROVE_EXECUTION`, so
`PermissionDenied` fired before the self-approval guard could run.

**Fix.** Use `vp_user` (who holds `PERM_APPROVE_EXECUTION`) as the
submitter; vp_user attempting to approve their own submission triggers
`SelfApprovalForbidden`. Added a companion test confirming a doer gets
`PermissionDenied` with no state change.

**File.** `backend/iig_checklist/tests/test_execution_lifecycle.py`

**Commit.** `c25ce03` — test: correct 4D-2 lifecycle and model fixtures

---

### F6-T-2: Conflicting version_number=1 IntegrityError in model tests

**Root cause.** Two model tests received the `draft_version` fixture, which
creates `ChecklistVersion(version_number=1)`. Both tests also called
`_make_active_checklist_version()` which creates another `version_number=1`
on the same definition, violating the unique constraint.

**Fix.** Removed `draft_version` from both affected test signatures.

**File.** `backend/iig_checklist/tests/test_execution_models.py`

**Commit.** `c25ce03` — test: correct 4D-2 lifecycle and model fixtures

---

### F6-T-3: CalculationOutcome tests omitted required JSONField inputs

**Root cause.** `test_valid_calculation_name_accepted` and
`test_invalid_calculation_name_rejected` passed no `inputs` or
`input_provenance`. Django's `EMPTY_VALUES` treats `{}` (and missing) as
blank, so `full_clean()` raised `ValidationError` on `blank=False` fields.

**Fix.** Both tests now supply `inputs={"placeholder": True}` and
`input_provenance={"placeholder": "pre_calculation"}`.

**File.** `backend/iig_checklist/tests/test_execution_models.py`

**Commit.** `c25ce03` — test: correct 4D-2 lifecycle and model fixtures

---

## Docker smoke flow (2026-08-03)

Script: `backend/iig_checklist/tests/smoke_4d2_execution.py`

Run against a fresh Docker stack:
```
docker compose -p regx-ci up -d
docker exec -i <backend> python manage.py shell \
  < backend/iig_checklist/tests/smoke_4d2_execution.py
```

**Result (all 15 steps pass):**
```
STEP 1 active checklist version + reviewer_conclusion question: OK
STEP 2 approved formulation version: OK
STEP 3 execution created in draft (UUID-only): OK
STEP 4 duplicate active execution rejected with 409: OK
STEP 5 execution submitted for review: OK
STEP 5b response list paginated (count + results): OK
STEP 5c reviewer conclusion first entry: OK
STEP 5d reviewer conclusion amendment + 1 history row: OK
STEP 5e stale version no history created: OK
STEP 6 execution returned with reason: OK
STEP 7 execution approved by VP: OK
STEP 7b terminal (approved) reviewer_conclusion immutable: OK
STEP 7c generic PATCH cannot edit reviewer_conclusion: OK
STEP 8 cross-tenant execution detail returns 404: OK
STEP 8b in-tenant reviewer (no approve perm) gets 403: OK
IIG CHECKLIST EXECUTION 4D-2 SMOKE FLOW v2: ALL STEPS PASS
```

---

## Commit log (F6 remediation)

| SHA | Message |
|-----|---------|
| `37d0f78` | fix: permit governed reviewer conclusions during review |
| `4860d27` | fix: align execution response-list API contract and return generic 404 for cross-tenant executions |
| `c25ce03` | test: correct 4D-2 lifecycle and model fixtures |
| `54d31a6` | test: extend final backend and Docker verification for 4D-2 |
| `<next>` | docs: update 4D-2 final verification evidence |
