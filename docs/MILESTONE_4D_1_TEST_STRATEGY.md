# Milestone 4D-1: Test Strategy

## Backend — `backend/iig_checklist/tests/` (259 tests)

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
| `test_platform_authorization.py` (15 tests) | The post-review remediation for the confirmed Major platform-master **creation** finding: `can_author_platform_master()`/`can_create_definition_for_scope()` unit-level truth table; ordinary Doer blocked from direct-create and from clone into `platform_master` (403, no row created, no success audit event); an `is_superuser` actor succeeds on both paths; Tenant Admin and Platform Support also blocked; a source-inspection test pinning that both `ChecklistDefinitionListCreateView.post` and `ChecklistDefinitionCloneView.post` call the one centralized function |
| `test_platform_mutation_authorization.py` (35 tests) | The remediation for the second, related finding (platform-master content-**mutation** authorization, caught by an independent adversarial re-review before merge): `can_mutate_definition_scope()` unit-level truth table (tenant object + own-tenant actor, tenant object + other-tenant actor, platform object + ordinary Doer, platform object + platform actor missing the operation permission); the full endpoint matrix — version create, version PATCH, every one of the 7 lifecycle actions, section create/update/delete, question create/update/delete, applicability-rule create, empty-draft-definition delete — each denied (403, no row created/changed/deleted, no success audit event) for an ordinary Doer against platform-master content and allowed for the authorized platform actor; a no-success-audit-on-denial check; a check that tenant-scoped mutations and tenant isolation (Tenant A cannot reach Tenant B's tenant-scoped content — generic 404, not 403) are unaffected |

Concurrency tests use `@pytest.mark.django_db(transaction=True)` with real
`threading.Thread`s and separate DB connections — a plain
`@pytest.mark.django_db` wraps the test in an uncommitted transaction that
other threads' connections cannot see, which would make the test
vacuously pass (or 404) instead of actually racing.

## Frontend

- **Unit** (`frontend/tests/unit/iig-checklists.test.tsx`, 20 tests):
  definition list/loading/empty/redirect-on-403, create-definition
  success/error, definition-detail versions rendering and
  create-version-button visibility, version-detail lifecycle-action
  visibility per status, return-reason-required validation, read-only
  section/question rendering, the platform-master scope warning text on
  the create form, a 403-on-platform-master-create denial rendering
  inline (not a signin redirect), 401 still correctly redirecting to
  signin, and (mutation-authorization remediation) the version-detail
  page's platform-master notice appearing only for `scope_type ===
  "platform_master"`, and a denied lifecycle action rendering inline
  without a signin redirect.
- **Accessibility** (3 tests appended to `accessibility.test.tsx`):
  axe-core scans of the definition list, definition detail, and version
  detail (with lifecycle buttons rendered) screens.
- **Playwright** (`frontend/e2e/iig-checklists.spec.ts`, 10 scenarios):
  list, create→navigate, create-version, submit→return→resubmit,
  approve→activate→second-activate-conflict-surfaced,
  approved/active-never-shows-execution-UI, clone→fresh-draft-v1,
  empty-draft-delete, an ordinary Doer's platform-master creation
  attempt being denied with a clear inline message rather than a signin
  redirect, and platform-master content showing the authorization
  notice plus a safely-handled denied lifecycle action. Every backend
  response is a deterministic `page.route` mock — server-side
  correctness is the backend suite's job; this suite proves the
  frontend renders and reacts to the documented API contract correctly.

### Frontend platform-master handling (post-review remediation)

While implementing the platform-master fix, the create-definition form was
found to redirect *any* 403 to `/signin`, indistinguishable from a real
401 (unauthenticated). That would have hidden a legitimate platform-
authorization denial behind a confusing "please sign in" redirect. The fix
separates 401 (→ signin) from 403 (→ inline, specific message), and shows
a warning as soon as "Platform master" is selected, before submission.
Determining the actor's actual platform grant client-side (to hide/disable
the option entirely) would require exposing `is_superuser` on the shared
`identity` app's user-profile endpoint — judged out of scope for this
narrowly-scoped remediation, so the option remains selectable and the
server remains the sole authority; the user simply now gets a clear,
correct answer instead of a misleading one.

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

A 27-step production-API flow, added alongside the existing
FDA/formulation/IID and template-migration flows. Unlike the frontend's
mocked tests, this step drives the real `iig_checklist` views through
`django.test.Client` inside `manage.py shell` against the live Docker
Postgres/Redis stack — it is what actually caught the clone
response-shape mismatch described in
`docs/MILESTONE_4D_1_IMPLEMENTATION.md`. Steps 1-19: create definition →
create version → illegal direct-approve blocked → set effective_date
while draft → submit → Doer-cannot-approve → return → resubmit → approve
→ activate → re-activation-of-active-blocked → UUID-only version list →
clone → active definition still readable → non-empty-draft deletion
blocked → empty draft created → empty draft deleted → audit events
present for both delete and activate → no execution-domain fields appear
anywhere in the flow's responses. Steps 20-22 (platform-master
**creation** remediation): an ordinary Doer's direct `platform_master`
create is rejected with 403 and creates no row; an `is_superuser` actor's
direct `platform_master` create succeeds with `tenant_public_id` null;
the same ordinary Doer's attempt to clone into `platform_master` scope is
rejected with 403 and creates no partial clone. Steps 23-27 (platform-
master content-**mutation** remediation, representative production-API
coverage — the full endpoint matrix belongs in
`test_platform_mutation_authorization.py`, not here, per the instruction
not to make the Docker smoke brittle): the authorized platform actor
creates a version on their platform-master definition; an ordinary Doer's
attempt to PATCH that version's metadata is rejected with 403; the same
Doer's attempt to create a section on it is rejected with 403 and creates
no row; the same Doer's attempt to submit it for review is rejected with
403; the authorized platform actor then successfully creates a section
on it. All steps go through the real production API
(`doer_client`/`platform_client.post`), never an ORM shortcut, so a
regression in `can_create_definition_for_scope()` or
`can_mutate_definition_scope()` would be caught here even in the
hypothetical case it somehow passed pytest.

## What this milestone deliberately does not test

Nothing related to ChecklistExecution, ChecklistResponse,
CalculationOutcome, draft-answer generation, overrides/deviations, or
execution exports exists to test — those are out of scope for 4D-1 by
the approved specification.
