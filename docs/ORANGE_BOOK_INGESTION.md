# Orange Book Ingestion

## Source

Rows are adapted from the official FDA Orange Book products export shape
(pipe-delimited text file, already parsed into row dicts before reaching
`fda_data`): `Ingredient`, `DF;Route`, `Trade_Name`, `Applicant`, `Strength`,
`Appl_Type`, `Appl_No`, `Product_No`, `TE_Code`, `Approval_Date`, `RLD`,
`RS`. No commercial or scraped source is accepted; `official_source_reference`
on `FDADataSourceRelease` records where the file actually came from.

## Pipeline

1. **Register** (`importer.register_release`) — compute SHA-256 of the raw
   file, store it via `fda_data/storage.py`, create an `FDADataSourceRelease`
   in `registered` status. Re-registering the identical bytes for the same
   `dataset_type` returns the existing release rather than duplicating it.
2. **Adapt** (`adapters.orange_book_products_adapter`) — split the combined
   `DF;Route` field (e.g. `"TABLET;ORAL"`) into `dosage_form_raw`/`route_raw`
   via `terminology.split_dosage_form_route`, and map every other column
   into the neutral row schema. The full original row is preserved verbatim
   as `raw_payload`.
3. **Import** (`importer.import_orange_book_rows`) — for each row:
   - `OrangeBookApplication` is `get_or_create`'d on
     `(release, application_type, application_number)`.
   - `strength_raw` is parsed via `terminology.parse_strength`; a value that
     doesn't parse cleanly gets `strength_parse_status=REVIEW_REQUIRED`, not
     a guessed number.
   - `dosage_form_raw`/`route_raw` are resolved to `ControlledDosageForm`/
     `ControlledRoute` only through an approved `DosageFormMapping`/
     `RouteMapping` row (`terminology.lookup_dosage_form_mapping`/
     `lookup_route_mapping`) — an unmapped raw value normalizes to `None`,
     never a guess.
   - `OrangeBookProduct` is `get_or_create`'d on
     `(release, application, product_number)`; a second row hitting the same
     key produces `FdaImportRowResultType.DUPLICATE`, not a second product.
   - Every row gets exactly one `FdaImportRowResult` (`imported`,
     `duplicate`, or `failed` with `reason_code="import_exception"` and a
     truncated, non-sensitive `safe_detail`).
4. **Reconciliation** — `record_count_expected/extracted/imported/failed`
   are recomputed from the persisted `FdaImportRowResult` rows, never
   estimated.

## Handled edge cases (see `fda_data/tests/test_importer_and_lifecycle.py`)

- Combined dosage-form/route strings split correctly (`"TABLET;ORAL"` →
  dosage form `TABLET`, route `ORAL`).
- Non-date approval text (e.g. `"Approved Prior to Jan 1, 1982"`) is stored
  verbatim in `approval_date_text`, never coerced into a fabricated date.
- A discontinued product reconciles distinctly from an active one
  (`discontinued` flag from the source, not inferred).
- Duplicate checksum / re-registration is idempotent — no duplicate release
  or product rows.
- Schema drift (missing/renamed columns) surfaces as `strength_parse_status
  = REVIEW_REQUIRED` / unmapped route-dosage-form, not a silent skip or a
  crash.
- Malformed rows and rows with formula-like cell content (`=`, `+`, `-`,
  `@`-leading strings) are stored as-is in `raw_row_payload` for audit, but
  never rendered unescaped — see the CSV export neutralization in
  `TEMPLATE_RECONCILIATION_REPORT.md`-equivalent behavior at
  `fda_data/views.py::_csv_safe_cell`.
- Superseding an active release is a distinct lifecycle action
  (`lifecycle.py`) — import never auto-activates or auto-supersedes.

## Out of scope here

Patents/exclusivity/discontinued-list reconciliation beyond the `discontinued`
flag already carried on the products file, and any interpretation of RLD/RS/
TE-code beyond storing them verbatim, are left to the consuming domain
(`formulations`) at reference-product-selection time — see
`FORMULATION_DATA_MODEL.md`.
