# IID Foundation Test Strategy

Covers `fda_data`, `formulations`, and `iid_assessment` — Milestone
4A-4C's controlled, synthetic-data-only test suite. 154 backend tests
(422 across the full repo), all passing, all against synthetic
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

## Frontend coverage

`frontend/tests/unit/fda-iid.test.tsx` (23 tests) and additions to
`frontend/tests/unit/accessibility.test.tsx` (8 new tests, 18 total)
cover the FDA release inventory/detail, Orange Book search, formulation
reference-selection (including the required confirmation checkbox), and
IID preview screens — provenance labels, no-prefill-from-IID, blocked-
calculation display, multiple-candidate selection, and the absence of any
forbidden safety-claim word. `frontend/e2e/fda-iid.spec.ts` (9 Playwright
tests) covers the same screens end-to-end against deterministic API
mocks. See `FRONTEND_FOUNDATION.md` for what the frontend build covers and
what it explicitly does not (the full 14-screen surface was not built;
see the Milestone 4A-4C final report for the exact accounting).

## What remains explicitly out of scope

- Not every one of the 20 example Playwright scenarios listed in the
  milestone spec has a discrete spec file entry — 9 of the highest-value,
  safety-critical ones do (exact match, multiple candidates, route
  mismatch, exceeds-precedent, no-auto-safety-language, provenance,
  explicit reference confirmation, release registration, Orange Book
  search). The remaining scenarios (dosage-form mismatch, unit mismatch,
  missing-MDE review state, percentage-w/w and daily-exposure calculation
  detail views, dosing-regimen/component entry as standalone E2E flows)
  are covered at the unit/component level instead, not end-to-end.
- Storage-level authorization for raw FDA source files is inherited from
  `documents.storage` and re-verified here only at the API-response-shape
  level (`storage_key` never serialized) — the storage backend's own
  access control is not independently re-tested in this pass.

## Running

```
DJANGO_SETTINGS_MODULE=regx.settings.test DB_HOST=localhost DB_PORT=5434 \
DB_USER=regx_verify_user DB_PASSWORD='VerifyPass_2024!' DB_NAME=regx_verify \
python -m pytest fda_data formulations iid_assessment -q --no-cov
```

Local gates also run clean: `ruff check`, `ruff format --check`,
`lint-imports` (6/6 contracts kept), `manage.py check`,
`makemigrations --check --dry-run`, and the full repo-wide suite
(422 tests, 92.5% coverage).
