# IID Foundation Test Strategy

Covers `fda_data`, `formulations`, and `iid_assessment` — Milestone
4A-4C's controlled, synthetic-data-only test suite. 121 tests, all passing,
all against synthetic FDA-shaped fixtures (never real Orange Book/IID
content, never AIDatabase or 483 content, never legacy IIG answer data).

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

**`formulations/tests/test_models_and_api.py`** (18 tests) — product-code
uniqueness per tenant, no-reference-product-selected-by-default, total
weight / component quantity / dosing-regimen positivity constraints,
approved-version immutability, Decimal-not-float quantities, cross-tenant
404 on products and on formulation-version components, no numeric ID in API
responses, explicit (never automatic) reference-product selection, component
and dosing-regimen creation via API, negative-quantity and zero-max-units
rejection.

## Explicitly not covered in this pass

Being direct about what was deferred rather than silently thin:

- Not all 15 originally-scoped planted-failure scenarios exist as discrete,
  separately-labeled plant/detect/restore/rerun tests. Most are covered
  inline (marked `# PLANTED VIOLATION (detected)` at the point they are
  exercised) rather than as a standalone before/after harness.
- No dedicated test for float-arithmetic injection (verified by code
  inspection — every numeric path in `unit_conversion.py`/`calculations.py`
  goes through `Decimal(str(...))` — rather than a runtime assertion that
  float input is rejected).
- No dedicated test for raw FDA source file access bypassing the API layer
  (storage-level authorization is inherited from `documents.storage`, not
  re-verified here).
- No frontend tests for this milestone — the 14-screen frontend itself was
  not built in this pass (see the Milestone 4A-4C final report for the
  full accounting of what shipped vs. was deferred).

## Running

```
DJANGO_SETTINGS_MODULE=regx.settings.test DB_HOST=localhost DB_PORT=5434 \
DB_USER=regx_verify_user DB_PASSWORD='VerifyPass_2024!' DB_NAME=regx_verify \
python -m pytest fda_data formulations iid_assessment -q --no-cov
```

Local gates also run clean: `ruff check`, `ruff format --check`,
`lint-imports` (6/6 contracts kept), `manage.py check`, and
`makemigrations --check --dry-run`.
