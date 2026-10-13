# Orange Book Ingestion

## Source

The official FDA Orange Book download is a ZIP containing **`Products.txt`,
`Patent.txt` and `Exclusivity.txt`** — ASCII, **tilde (`~`) delimited**.

> Earlier revisions of this document said *pipe-delimited*. That was wrong.
> Splitting a tilde file on `|` yields a single column per row, which now
> fails column validation rather than importing nonsense.

`Products.txt` columns: `Ingredient`, `DF;Route`, `Trade_Name`, `Applicant`,
`Strength`, `Appl_Type`, `Appl_No`, `Product_No`, `TE_Code`, `Approval_Date`,
`RLD`, `RS`, `Type`.

**Only `Products.txt` is read.** `Patent.txt` and `Exclusivity.txt` ship in the
same archive and are ignored: there is no patent or exclusivity model in this
system, and feeding them to the products adapter produces empty
`OrangeBookProduct` rows that reconciliation then counts as imported.

No commercial or scraped source is accepted. `official_source_reference` is
**supplied by the operator and recorded verbatim** — a file whose columns match
this shape is not thereby proved to have come from FDA, and nothing stamps
"FDA official" on it because the header looked right.

## Supported dataset types

| Dataset type | Importable | Why not |
|---|---|---|
| `orange_book_products` | **yes** | — |
| `fda_iid` | **yes** | — |
| `orange_book_patents` | no | no destination model |
| `orange_book_exclusivity` | no | no destination model |
| `orange_book_discontinued` | no | discontinued flag not carried by the products adapter |
| `fda_substance_identifiers` | no | UNII mappings are created by the proposal workflow, not bulk import |
| `fda_route_terminology` | no | governed vocabulary, not imported source data |
| `fda_dosage_form_terminology` | no | governed vocabulary, not imported source data |

An unsupported type fails with **HTTP 400 before any release is created**. It
previously returned 201 with zero rows imported, which looked like success.
The authoritative list is `fda_data/dispatch.py`; a test asserts every declared
enum member is either importable or has a stated reason.

## IID source contract

Official export: the ZIP FDA publishes (e.g. `iig_july_2026.zip`), or its
`IIR_OCOMM.csv` member. Comma-delimited, CRLF, with this header (verified
against the July 2026 file):
`INGREDIENT_NAME`, `ROUTE`, `DOSAGE_FORM`, `CAS_NUMBER`, `UNII`,
`POTENCY_AMOUNT`, `POTENCY_UNIT`, `MAXIMUM_DAILY_EXPOSURE`,
`MAXIMUM_DAILY_EXPOSURE_UNIT`, plus an optional `RECORD_UPDATED` ("Y" on rows
changed that quarter). The ZIP's `IIR_OCOMM.xls` and `Change_Log_Data` members
are not read.

`INGREDIENT_NAME`, `ROUTE` and `DOSAGE_FORM` must be **present and
non-empty**; a row missing any of them is rejected rather than stored with
blanks. Potency and maximum daily exposure are **not** required: each real row
carries one of them, or neither (potency unit `NA` or `ADJ PH`). Each amount is
stored twice: as the exact text (`potency_amount_raw`, `mde_amount_raw`) and,
when it is a plain decimal, as a number. Anything else is kept as text, left
unparsed and flagged on the row's import result. A UNII of `NA` is a
placeholder, not an identifier, and is never used to match ingredients.

The adapter also accepts the older names (`Inactive Ingredient`,
`Potency Amount`, `Potency Unit`; `Ingredient Name`, `Potency`, `Unit`) for
existing JSON API callers, but an actual file must match what FDA publishes.

**XLSX/XLS is not supported.** `openpyxl` is available, but a cell holding a
formula with no cached result reads as `None`, and the only honest options are
to reject the row or evaluate the formula — and evaluating spreadsheet formulas
from an untrusted file is not something this importer should do. Use the CSV
member; the column contract is identical.

## Importing a file

```bash
python manage.py import_fda_release EOBZIP_2026_01.zip     --dataset-type orange_book_products     --source-reference "FDA Orange Book, downloaded 2026-01-15 from fda.gov"

python manage.py import_fda_release iid.csv     --dataset-type fda_iid     --source-reference "FDA IID export, downloaded 2026-01-15 from fda.gov"
```

`--dataset-type` is mandatory and never sniffed: `Products.txt` and
`Patent.txt` are both tilde-delimited ASCII from the same archive, so guessing
would eventually store patent rows as products. `--dry-run` parses and
validates without writing.

The command **registers** a release. It does not activate one — that still
requires `validate → submit-review → approve → activate`.

### Parser safety

Rejected, not worked around: ZIP members with traversal paths (`..`, absolute),
nested archives, a missing `Products.txt`, two members named `Products.txt`,
uncompressed size over 256 MB, more than 500,000 rows, a row whose field count
differs from the header, and a file that decodes as neither UTF-8 nor Latin-1.
Latin-1 bytes are preserved as characters rather than replaced with U+FFFD,
because a corrupted applicant name in a governed record is worse than a
rejected file.

## Two checksums, two meanings

| Field | Covers |
|---|---|
| `source_checksum_sha256` | the exact bytes supplied — the FDA file/ZIP via the command, or the canonical JSON payload via the API |
| `normalized_payload_sha256` | the canonical rows after parsing, independent of how they arrived |

The first is the identity used for idempotency: the unique constraint is
`(dataset_type, source_checksum_sha256)`, so re-importing the same bytes reuses
the existing release instead of duplicating rows. The second lets two different
source files that normalize identically be recognised as equivalent **without**
losing the distinction between the files themselves.

`source_file_size_bytes` and `parser_identifier` are recorded alongside.
`parser_identifier` is blank for API-registered releases, because no parser ran.

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
