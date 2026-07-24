# FDA IID Ingestion

## Source

Rows are adapted from the official FDA Inactive Ingredient Database (IID)
export shape: `Ingredient Name`, `UNII`, `CAS Number`, `Route`,
`Dosage Form`, `Potency`, `Unit`, `Maximum Daily Exposure`, `MDE Unit`.
Columns are frequently blank in real IID releases; the adapter reads them
with `.get(..., "")`, never a fabricated placeholder.

## Pipeline

1. **Register** — identical to Orange Book (`importer.register_release`),
   `dataset_type="fda_iid"`.
2. **Adapt** (`adapters.fda_iid_adapter`) — maps each column into the
   neutral row schema; `raw_payload` preserves the original row.
3. **Import** (`importer.import_iid_rows`), per row:
   - **Duplicate detection** is by `(release, raw_row_checksum)` — an exact
     re-occurrence of the same row within a release is recorded as
     `FdaImportRowResultType.DUPLICATE` and skipped, never re-imported as a
     second precedent record.
   - **Ingredient resolution** (`_resolve_iid_ingredient`) — matches an
     existing `IIDIngredient` by UNII first, then by uppercased canonical
     name; creates one only if neither matches. A row with no name at all
     resolves to `None` (ingredient unresolved), never an empty-string
     placeholder record.
   - **Route/dosage-form** resolve only through an approved `RouteMapping`/
     `DosageFormMapping`, same as Orange Book.
   - **Potency** is parsed via `terminology.parse_strength` from
     `"{Potency} {Unit}"`; a blank or unparseable potency stays `None` —
     it is never coerced to `0`.
   - **MDE** is only parsed if `mde_raw` is non-empty; a record with no MDE
     is still `CALCULABLE` for potency-only comparisons — MDE-specific
     comparisons independently return `MDE_UNAVAILABLE` at calculation time
     (`iid_assessment`), rather than blocking the whole record here.
   - **Calculability status** (`_determine_calculability`) is assigned in
     strict precedence: `INGREDIENT_AMBIGUOUS` → `ROUTE_UNMAPPED` →
     `DOSAGE_FORM_UNMAPPED` → `POTENCY_MISSING` → `POTENCY_UNIT_MISSING` →
     `CALCULABLE`. Every `IIDPrecedentRecord` carries this status, and the
     `FdaImportRowResult` for a non-`CALCULABLE` row is
     `REVIEW_REQUIRED` with `reason_code` set to that status, not silently
     `IMPORTED`.

## Handled edge cases (see `fda_data/tests/test_importer_and_lifecycle.py`)

- Valid potency + unit → `CALCULABLE`.
- Missing potency → `POTENCY_MISSING`, not `0`.
- Invalid/unparseable potency text → `POTENCY_MISSING` (fails closed, no
  guessed number).
- Missing MDE → record stays `CALCULABLE` (potency-only); MDE comparison
  later returns `MDE_UNAVAILABLE` rather than blocking.
- Ambiguous ingredient (no name, or a name matching no UNII/normalized-name
  key) → `INGREDIENT_AMBIGUOUS`, ingredient FK stays `None`.
- Unmapped route or dosage form → `ROUTE_UNMAPPED` / `DOSAGE_FORM_UNMAPPED`.
- Duplicate row (identical checksum within the same release) → recorded as
  `DUPLICATE`, no second `IIDPrecedentRecord`.
- Multiple distinct `CALCULABLE` records that share ingredient/route/
  dosage-form (e.g. two potency tiers) are both imported as separate
  precedent records — resolving which one applies to a given assessment is
  the matching engine's job (`IID_MATCHING_ENGINE.md`), never the importer's.

## Never done here

The importer never activates a release, never picks a "best" precedent
record, and never converts units — those are the `lifecycle`,
`iid_assessment.matching`, and `iid_assessment.unit_conversion` modules'
exclusive responsibilities respectively.
