# IID Foundation Test Strategy

Covers `fda_data`, `formulations`, and `iid_assessment` — Milestone
4A-4C's controlled, synthetic-data-only test suite. 171 backend tests
(439 across the full repo), all passing, all against synthetic
FDA-shaped fixtures (never real Orange Book/IID content, never AIDatabase
or 483 content, never legacy IIG answer data).

## What is covered

**`iid_assessment/tests/test_unit_conversion.py`** (21 tests) — mass,
volume, and count conversions; dimension mismatch; missing basis/density;
percentage w/w; unsupported conversion paths; Decimal precision/no-float
behavior.

**`iid_assessment/tests/test_calculations.py`** — all six formulas (A–F),
each formula's blocked-status paths (missing proposed value, missing max
daily units, missing/invalid IID reference value, zero denominator).

**`iid_assessment/tests/test_decisions.py`** — all five
`PrecedentDecisionStatus` values, the structural forbidden-status/
forbidden-word enforcement (`__post_init__` raising `ValueError`), and that
no "safe"/"approved" status can be constructed.

**`iid_assessment/tests/test_matching_and_assess.py`** (12 tests) —
exact match, route/dosage-form/ingredient mismatch, multiple-exact-matches
never auto-resolved, end-to-end `run_preview()` for pass/exceeds/no-match/
review-required/not-comparable, no-prefill-from-IID, API-level preview and
snapshot-immutability, forbidden-word absence in the API response body.

**`fda_data/tests/test_importer_and_lifecycle.py`** (19 tests) — valid
Orange Book import, combined dosage-form/route parsing, non-date approval
text, discontinued reconciliation, duplicate checksum, malformed/schema-drift
rows, IID import (valid/missing/invalid potency, missing MDE, ambiguous
ingredient, unmapped route/dosage form, duplicate record), release
lifecycle (submit → approve → activate, segregation of duties,
single-active-release-per-dataset-type, no-auto-activation, supersession).

**`fda_data/tests/test_api_and_security.py`** (9 tests) — CSV
formula-injection neutralization on export, no source-file-path leakage in
CSV/JSON export, Doer cannot export reconciliation, no numeric ID in the
release list response, raw fields hidden from non-`view_raw` holders,
Doer cannot approve or activate a release.

**`formulations/tests/test_models_and_api.py`** (21 tests) — product-code
uniqueness per tenant (model-level and structured-400-via-API), no-
reference-product-selected-by-default, total weight / component quantity /
dosing-regimen positivity constraints (model-level and structured-400-via-
API), approved-version immutability, Decimal-not-float quantities,
cross-tenant 404 on products and on formulation-version components, no
numeric ID in API responses, explicit (never automatic) reference-product
selection, component and dosing-regimen creation via API.

**`iid_assessment/tests/test_planted_failures.py`** (15 tests) — one
discrete plant/detect/restore/rerun test per scenario from the milestone
spec: auto-activate release, overwrite active release, potency parsed as
zero, fuzzy route match, auto-select-highest-potency, mass→volume without
density, float arithmetic, calculate without max daily units, cross-tenant
formulation lookup, source-path exposure, numeric-ID exposure, SAFE status
construction, Doer approving a release, snapshot mutation after an FDA
refresh, and unneutralized formula-injection export. Each test plants the
violation via the real service/API layer, asserts the system's actual
guard rejects it, and then exercises the legitimate path to confirm a
clean rerun still works.

**`fda_data/tests/test_raw_file_security.py`** (9 tests) — `storage_key`
is absent from every serializer response regardless of role (including
`view_raw` holders), Platform Support has zero `fda_data` access
(view/export/import all rejected), an under-permissioned write attempt
(Reviewer registering a release) is rejected, a nonexistent release
returns a generic 404, and an unauthenticated request is rejected rather
than disclosing existence via 404.

**`iid_assessment/tests/test_decimal_security.py`** (6 tests) — a JSON
float (e.g. `0.1`) submitted to `MatchPreviewRequestSerializer` converts to
an exact `Decimal` with no binary-float tail; non-numeric strings, `nan`,
and `inf`/`-inf` are all rejected as structured validation errors; the
unit-conversion engine fails closed (never raises) on a value that can't
become a `Decimal` at all; calculation output is deterministic across
repeated calls with identical `Decimal` inputs.

**`fda_data/tests/test_mappings_api.py`** (11 tests) — mapping list
filtered by type/status, Doer cannot list or approve/reject a mapping
(VP/Reviewer only), approve/reject persist the reviewer and reason,
approved mappings are immutable at the model layer, nonexistent mapping
and unknown mapping-type both return generic 404, no numeric ID in the
response.

**`fda_data/tests/test_orange_book_api.py`** (6 tests) — RLD /
reference-standard / discontinued / application-type / strength filters
each narrow results correctly; a non-RLD product is never returned when
filtering for RLD, even when it shares an application with an RLD
product.

## Frontend coverage

`frontend/tests/unit/fda-iid.test.tsx` (40 tests) and
`frontend/tests/unit/accessibility.test.tsx` (24 tests) cover all 13
routes in `FRONTEND_FOUNDATION.md`'s route matrix — provenance labels,
no-prefill-from-IID, no-auto-mapping-approval, no-auto-reference-selection,
blocked-calculation display, multiple-candidate selection, structured
form-validation errors, and the absence of any forbidden safety-claim
word. `frontend/e2e/fda-iid.spec.ts` (22 Playwright tests, 78 across the
full frontend suite) covers the same screens end-to-end against
deterministic API mocks.

### 20/20 required E2E scenario matrix (`frontend/e2e/fda-iid.spec.ts`)

| # | Scenario | Test name |
|---|---|---|
| 1 | FDA release inventory loads | `FDA release inventory > loads and lists a registered release` |
| 2 | New release registration | `FDA release inventory > new release registration navigates to detail and does not auto-activate` |
| 3 | Release reconciliation screen | `FDA release reconciliation screen > shows counts and per-row reconciliation results` |
| 4 | Terminology mapping review | `Terminology mapping review > lists a proposed mapping and requires explicit confirmation to approve, never auto-approved` |
| 5 | Orange Book search | `Orange Book search > searches and shows FDA-sourced results` |
| 6 | Orange Book filters | `Orange Book filters and product detail > RLD filter narrows results to only RLD-flagged products` |
| 7 | Orange Book product detail | `Orange Book filters and product detail > product detail shows FDA-sourced provenance and never implies auto-selection` |
| 8 | Explicit reference selection | `Formulation record and explicit reference selection > creating a product record and selecting a reference product requires explicit confirmation` |
| 9 | Product record creation | `Formulation version creation, component entry, and dosing regimen > creates a product record via the standalone new-product route` |
| 10 | Formulation version creation | `Formulation version creation, component entry, and dosing regimen > creates a formulation version, then adds an inactive component and a dosing regimen` |
| 11 | Inactive component entry | (same test as #10 — component entry step) |
| 12 | Dosing regimen entry | (same test as #10 — dosing-regimen step) |
| 13 | Exact IID match preview | `IID assessment preview > exact match within precedent shows the required disclaimer and no automatic safety language` |
| 14 | Multiple-match review state | `IID assessment preview > multiple exact matches require explicit reviewer selection, never auto-picked` |
| 15 | Missing-MDE review state | `IID assessment preview > missing-MDE shows review-required, never a fabricated MDE value` |
| 16 | Route mismatch | `IID assessment preview > route mismatch is shown distinctly and never treated as comparable` |
| 17 | Dosage-form mismatch | `IID assessment preview > dosage-form mismatch is shown distinctly and never treated as comparable` |
| 18 | Unit mismatch | `IID assessment preview > unit mismatch is shown when the proposed unit cannot be reconciled with the precedent` |
| 19 | Percentage w/w and daily-exposure calculation | `IID assessment preview > percentage w/w and daily-exposure calculations are displayed with calculated provenance` |
| 20 | Exceeds-IID-precedent warning and required disclaimer | `IID assessment preview > exceeding the IID precedent shows an escalation warning, never a pass` |

Also covered as distinct tests: no automatic quantity defaulting
(`no automatic quantity defaulting -- proposed field never pre-fills
from a precedent`), an API error state (`an API error surfaces distinctly,
not as a fabricated result`), and a reconciliation permission-error state
(`a permission-denied reconciliation request shows a distinct error, not
a blank page`). Loading/empty states, raw-path absence, and numeric-ID
absence are covered at the unit-test level in `fda-iid.test.tsx` and
`accessibility.test.tsx` rather than duplicated in Playwright.

## What remains explicitly out of scope

- No dedicated UI or tests for substance/UNII synonym mappings — no
  backend model exists for this mapping type.
- No "view affected records" drill-down from a mapping row (the count is
  shown; the underlying record list is not).
- Storage-level authorization for raw FDA source files is inherited from
  `documents.storage` and re-verified here only at the API-response-shape
  level (`storage_key` never serialized) — the storage backend's own
  access control is not independently re-tested in this pass.
- Milestone 4D (final checklist execution and approval workflow) is not
  implemented and remains fully out of scope.

## Running

```
DJANGO_SETTINGS_MODULE=regx.settings.test DB_HOST=localhost DB_PORT=5434 \
DB_USER=regx_verify_user DB_PASSWORD='VerifyPass_2024!' DB_NAME=regx_verify \
python -m pytest fda_data formulations iid_assessment -q --no-cov
```

Local gates also run clean: `ruff check`, `ruff format --check`,
`lint-imports` (6/6 contracts kept), `manage.py check`,
`makemigrations --check --dry-run`, and the full repo-wide suite
(439 tests, 92.4% coverage).
