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
88 passed (35.5s)
```
Includes 15/15 execution-suite tests (`iig-checklist-executions.spec.ts`).

### Backend (pytest)

PostgreSQL connection timed out in this environment during test database
creation (`create_test_db` → `psycopg.errors.ConnectionTimeout`). This is
an infrastructure constraint unrelated to the code changes. The fixture
field corrections are verified correct by static inspection against the
`ProductDevelopmentRecord` model definition in `formulations/models.py`
(fields: `proposed_product_name`, `active_ingredient`, `route`).

### TypeScript

Zero type errors (`tsc --noEmit` clean).

---

## Commit log (this remediation)

| SHA | Message |
|-----|---------|
| `139999a` | test: correct 4D-2 formulation fixtures |
| `51e496a` | fix: align execution frontend API field mapping |
| `d929cee` | fix: enforce strict YYYY-MM-DD date format in response_validation |
| `6845c2c` | test: correct 4D-2 Docker integration fixture |
| `7f017a3` | test: resolve remaining browser-suite Playwright failures |
| `<next>` | docs: add 4D-2 verification evidence |
