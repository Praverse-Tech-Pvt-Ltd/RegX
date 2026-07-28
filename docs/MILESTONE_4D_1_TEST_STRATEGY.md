# Milestone 4D-1: Test Strategy

## Backend — `backend/iig_checklist/tests/` (209 tests)

| File | Covers |
|---|---|
| `test_models.py` | Scope/tenant constraint, normalized-code uniqueness, version-number/active-version uniqueness, section/question code/order uniqueness, immutability once not-editable |
| `test_codes.py` | `normalize_code()` grammar, blank/too-long/invalid-character rejection, collision-after-normalization |
| `test_compatibility.py` | Exhaustive 18×5 answer-type × data-source-classification matrix, plus floor assertions and an exhaustiveness check |
| `test_applicability.py` | All 10 deterministic error codes, canonical serialization order-independence, a planted "no eval" test asserting Python-syntax-as-string never executes |
| `test_lifecycle.py` | The full 7-action/8-status transition table (parametrized legal + illegal cases), the full API walk (submit→approve→activate), self-approval blocked, Doer-cannot-approve, illegal-transition-emits-no-audit, return/resubmit provenance preservation, rejected-is-terminal, and a real `threading`-based concurrent-activation test proving only one version ends up `active` |
| `test_services.py` | Concurrent version-number allocation (real threads, distinct sequential numbers), version-number never client-supplied, clone eligibility/duplicate-code/atomicity/provenance-not-copied |
| `test_api.py` | UUID-only responses, generic 404, tenant isolation, platform-master visibility, mass-assignment guard (status not patchable), PATCH blocked once under review, section deletion blocked once locked, the narrow empty-draft deletion exception (and its audit event) |
| `test_clone_api.py` | Clone via the real endpoint, cross-tenant clone blocked, draft-source clone rejected |

Concurrency tests use `@pytest.mark.django_db(transaction=True)` with real
`threading.Thread`s and separate DB connections — a plain
`@pytest.mark.django_db` wraps the test in an uncommitted transaction that
other threads' connections cannot see, which would make the test
vacuously pass (or 404) instead of actually racing.

## Frontend

- **Unit** (`frontend/tests/unit/iig-checklists.test.tsx`, 14 tests):
  definition list/loading/empty/redirect-on-403, create-definition
  success/error, definition-detail versions rendering and
  create-version-button visibility, version-detail lifecycle-action
  visibility per status, return-reason-required validation, read-only
  section/question rendering.
- **Accessibility** (3 tests appended to `accessibility.test.tsx`):
  axe-core scans of the definition list, definition detail, and version
  detail (with lifecycle buttons rendered) screens.
- **Playwright** (`frontend/e2e/iig-checklists.spec.ts`, 8 scenarios):
  list, create→navigate, create-version, submit→return→resubmit,
  approve→activate→second-activate-conflict-surfaced,
  approved/active-never-shows-execution-UI, clone→fresh-draft-v1,
  empty-draft-delete. Every backend response is a deterministic
  `page.route` mock — server-side correctness is the backend suite's job;
  this suite proves the frontend renders and reacts to the documented API
  contract correctly.

### A known gap, disclosed rather than hidden

This milestone's frontend does not include section/question/
applicability-rule authoring forms (only read-only display) — the
specification's UI requirements for those are met by the backend API only
in this pass. Playwright scenarios for "add section," "add question," and
"validate applicability rule" are consequently not present, since there
is no UI to drive them against. This is a scope reduction from the
25-section prompt's frontend list, not a defect; the corresponding
backend endpoints and their test coverage exist in full
(`test_api.py::TestSectionQuestionApi`, `test_applicability.py`).

## Docker integration (`docker-integration.yml`)

A 19-step production-API flow, added alongside the existing
FDA/formulation/IID and template-migration flows. Unlike the frontend's
mocked tests, this step drives the real `iig_checklist` views through
`django.test.Client` inside `manage.py shell` against the live Docker
Postgres/Redis stack — it is what actually caught the clone
response-shape mismatch described in
`docs/MILESTONE_4D_1_IMPLEMENTATION.md`. Steps: create definition →
create version → illegal direct-approve blocked → set effective_date
while draft → submit → Doer-cannot-approve → return → resubmit → approve
→ activate → re-activation-of-active-blocked → UUID-only version list →
clone → active definition still readable → non-empty-draft deletion
blocked → empty draft created → empty draft deleted → audit events
present for both delete and activate → no execution-domain fields appear
anywhere in the flow's responses.

## What this milestone deliberately does not test

Nothing related to ChecklistExecution, ChecklistResponse,
CalculationOutcome, draft-answer generation, overrides/deviations, or
execution exports exists to test — those are out of scope for 4D-1 by
the approved specification.
