"""
Adapters converting already-exported, controlled FDA row data (a Python
list of dicts, as loaded from the official Orange Book pipe-delimited text
file or the official FDA IID spreadsheet -- never a live scrape) into the
neutral row schema the import pipeline consumes. These adapters never
fetch anything themselves; parsing the raw file bytes into row dicts is a
separate, thin format-reading step performed before an adapter runs.

Neutral row schema:
    {
        "row_locator": str,      # e.g. "row:42" or a source line number
        "raw_payload": dict,     # the full original row, preserved verbatim
        "fields": {...},         # adapter-specific structured fields
    }
"""

from .checksums import sha256_payload
from .terminology import split_dosage_form_route


def orange_book_products_adapter(rows: list[dict]) -> list[dict]:
    """Adapts rows shaped like the official Orange Book products file:
    {Ingredient, DF;Route, Trade_Name, Applicant, Strength, Appl_Type,
    Appl_No, Product_No, TE_Code, Approval_Date, RLD, RS, Type}."""
    neutral = []
    for i, row in enumerate(rows):
        df_route = row.get("DF;Route", "") or row.get("DF_Route", "")
        dosage_form_raw, route_raw = split_dosage_form_route(df_route)
        neutral.append(
            {
                "row_locator": f"row:{row.get('_row_number', i)}",
                "raw_payload": dict(row),
                "fields": {
                    "application_type": row.get("Appl_Type", ""),
                    "application_number": row.get("Appl_No", ""),
                    "product_number": row.get("Product_No", ""),
                    "applicant_short_name": row.get("Applicant", ""),
                    "applicant_full_name": row.get("Applicant_Full_Name", row.get("Applicant", "")),
                    "trade_name": row.get("Trade_Name", ""),
                    "active_ingredient_raw": row.get("Ingredient", ""),
                    "dosage_form_raw": dosage_form_raw,
                    "route_raw": route_raw,
                    "strength_raw": row.get("Strength", ""),
                    "rld_flag": str(row.get("RLD", "")).strip().upper() == "YES",
                    "reference_standard_flag": str(row.get("RS", "")).strip().upper() == "YES",
                    "te_code": row.get("TE_Code", ""),
                    "approval_date_text": row.get("Approval_Date", ""),
                    # The FDA file says RX, OTC or DISCN in `Type`; DISCN is the
                    # only thing that marks a product discontinued. `_discontinued`
                    # is kept for existing JSON API callers that set it directly.
                    "marketing_category": str(row.get("Type", "")).strip().upper(),
                    "discontinued": str(row.get("Type", "")).strip().upper() == "DISCN"
                    or bool(row.get("_discontinued", False)),
                },
            }
        )
    return neutral


#: Official IID column name -> older names this adapter also accepts.
#:
#: The official export publishes `Inactive Ingredient`, `Potency Amount` and
#: `Potency Unit`. This adapter was written against `Ingredient Name`,
#: `Potency` and `Unit`, and because every lookup uses `.get(col, "")`, a real
#: IID file produced rows with an empty ingredient name, potency and unit --
#: silently, because a missing column and an empty cell are indistinguishable
#: to `.get`.
#:
#: The official name is tried first. The older spellings stay accepted so
#: existing JSON API callers and fixtures keep working; `parsers.parse_iid`
#: enforces the official contract for actual files, where a renamed column is
#: a fault rather than a dialect.
_IID_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "ingredient_name_raw": ("Inactive Ingredient", "Ingredient Name"),
    "unii": ("UNII",),
    "cas_number": ("CAS Number",),
    "route_raw": ("Route",),
    "dosage_form_raw": ("Dosage Form",),
    "potency_raw": ("Potency Amount", "Potency"),
    "potency_unit_raw": ("Potency Unit", "Unit"),
    # Not part of the official seven-column contract. Present in some
    # exports; absent is normal, so these stay optional.
    "mde_raw": ("Maximum Daily Exposure",),
    "mde_unit_raw": ("MDE Unit",),
}


def _first_present(row: dict, names: tuple[str, ...]) -> str:
    for name in names:
        if name in row:
            return row.get(name) or ""
    return ""


def fda_iid_adapter(rows: list[dict]) -> list[dict]:
    """Adapts rows from the official FDA IID export.

    Official columns: Inactive Ingredient, Route, Dosage Form, CAS Number,
    UNII, Potency Amount, Potency Unit. Older column spellings are accepted
    as aliases -- see `_IID_COLUMN_ALIASES` for why. Absent optional columns
    yield "", never a fabricated placeholder.
    """
    neutral = []
    for i, row in enumerate(rows):
        neutral.append(
            {
                "row_locator": f"row:{row.get('_row_number', i)}",
                "raw_payload": dict(row),
                "fields": {
                    key: _first_present(row, names) for key, names in _IID_COLUMN_ALIASES.items()
                },
            }
        )
    return neutral


def row_checksum(fields: dict) -> str:
    return sha256_payload(fields)
