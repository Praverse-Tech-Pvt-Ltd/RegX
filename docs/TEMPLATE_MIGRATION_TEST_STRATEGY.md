# Template Migration Test Strategy

## Test layout

| File | Covers |
|---|---|
| `templates_registry/tests/conftest.py` | Tenant/user/role fixtures; synthetic ANDA/DMF-like rows, mojibake/HTML/duplicate/excluded/malformed fixture rows |
| `test_models.py` | Constraints (canonical code uniqueness, one-active-version, section/item/option uniqueness, duplicate-candidate exactly-one-subject) and `TemplateVersion.clean()` immutability |
| `test_lifecycle.py` | Full state-machine walk, segregation of duties, activation supersession, invalid-transition guards, approval sequence numbering |
| `test_permissions.py` | Role → permission matrix for Doer/Reviewer/VP/Tenant Admin/Platform Support, fail-closed behavior |
| `test_importer.py` | Source/record exclusion guards, normalization (mojibake/HTML/numbering/category), duplicate detection, idempotent rerun |
| `test_api.py` | Tenant isolation, permission enforcement (including the reconciliation view/export split), response shape (no numeric IDs, no source paths for non-raw viewers), generic 404 |
| `test_planted_failures.py` | The 10 named scenarios below, each plant → detect → restore/rerun |

Frontend: `frontend/tests/unit/templates-list.test.tsx` (component-level) and
`frontend/e2e/migration-governance.spec.ts` (Playwright, route-mocked)
covering the same governance flows end-to-end in the UI.

## Synthetic fixtures (section 12)

All fixtures in `conftest.py` are synthetic and non-confidential, modeled on
the *structural shape* of legacy tables identified during source inventory,
never real client content:

- `anda_like_rows` / `dmf_like_rows` — valid ANDA-like / DMF-like template rows
- `duplicate_rows` — two rows sharing identical text (legitimate reuse across report types)
- `mojibake_row` — the exact `DO�S` corruption pattern found during inventory
- `html_and_numbering_row` — CKEditor-style HTML with embedded `"1. "` numbering
- a category-typo row (constructed inline in `test_importer.py`)
- `missing_locator_row` — empty module/category/chapter context
- a malformed row (constructed inline, non-adapter-shaped `fields`)
- `excluded_483_row` / `excluded_aidatabase_row` — must be rejected, never imported
- rerun/idempotency is exercised directly against `run_migration_batch()`

## Security/integrity coverage (section 13)

All 20 listed areas are covered across `test_models.py`, `test_lifecycle.py`,
`test_permissions.py`, `test_importer.py`, and `test_api.py`: 483/AIDatabase
rejection, unapproved-cannot-activate, imported-inactive-by-default,
raw-text-immutable, approved-version-immutable, activation-requires-approval,
only-one-active-version, cross-tenant isolation (source/package/duplicate),
no-numeric-IDs, no-source-paths, checksum preservation, rerun idempotency,
partial-failure reconciliation, auditable normalization mapping, unauthorized
reviewer blocked, no-self-approval, and audited activation/supersession/
retirement.

## The 10 planted-failure scenarios (`test_planted_failures.py`)

Each test plants the exact violation, asserts the system's guard detects and
blocks it, and then proves the system still works cleanly afterward (a
legitimate operation succeeds, or a rerun stays stable). No planted violation
is ever committed as working code — every plant lives inside a
`pytest.raises(...)` or an assertion inside the test itself.

1. AIDatabase import — `SourceExcluded` raised, nothing persisted
2. 483 source record accepted — classified `EXCLUDED`, never becomes a `TemplateItem`
3. Imported version auto-activated — `lifecycle.activate()` raises `InvalidTransition` on an unapproved version
4. Raw text overwritten by normalization — `raw_text` unchanged after `normalize_text_field()` and after a rerun
5. Approved version modified — `TemplateVersion.clean()` raises `ValidationError`
6. Second active version created — DB-level `IntegrityError` from the partial unique index
7. Tenant filter removed — demonstrates the unscoped manager would leak, and that `for_tenant_including_platform()` does not
8. Numeric ID exposed — asserted absent from a real API response
9. Source path exposed — asserted absent from a real API response for a non-raw viewer
10. Import rerun creates duplicates — three consecutive reruns produce no new rows

## Bugs found and fixed during this milestone

- **Reconciliation export permission gap**: `MigrationBatchReconciliationCsvView`/
  `JsonView` originally used `CanInventorySources` (held by Doer/Tenant Admin)
  instead of `CanExportReconciliation` (held by VP/Tenant Admin) — a Doer could
  export the reconciliation report while a VP without `templates.inventory`
  could not. Fixed by splitting the JSON view into `CanReview |
  CanExportReconciliation` (viewing, for review purposes) and the CSV view
  into `CanExportReconciliation` only (formal export), and by widening the
  overly-narrow `CanInventorySources` requirement on read-only GET endpoints
  (source package list, migration batch list/detail/results) to
  `CanViewTemplates`, matching the pattern already used for template
  endpoints.
- **Reconciliation report missing `public_id`**: `build_reconciliation_report()`
  hand-built minimal dicts for `normalization_mappings` and
  `duplicate_candidates` that omitted `public_id`, `raw_value`,
  `similarity_evidence`, and other fields the frontend's duplicate-resolution
  flow depends on — meaning duplicate-candidate resolution was silently
  non-functional end-to-end. Fixed by reusing the existing
  `NormalizationMappingSerializer` / `TemplateDuplicateCandidateSerializer`.
