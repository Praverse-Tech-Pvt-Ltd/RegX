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
                    "discontinued": bool(row.get("_discontinued", False)),
                },
            }
        )
    return neutral


def fda_iid_adapter(rows: list[dict]) -> list[dict]:
    """Adapts rows shaped like the official FDA IID export:
    {Ingredient Name, Potency, Unit, Route, Dosage Form, CAS Number, UNII,
    Maximum Daily Exposure, MDE Unit}. Some columns are frequently absent
    or blank in real IID releases -- .get() with "" default, never a
    fabricated placeholder."""
    neutral = []
    for i, row in enumerate(rows):
        neutral.append(
            {
                "row_locator": f"row:{row.get('_row_number', i)}",
                "raw_payload": dict(row),
                "fields": {
                    "ingredient_name_raw": row.get("Ingredient Name", ""),
                    "unii": row.get("UNII", ""),
                    "cas_number": row.get("CAS Number", ""),
                    "route_raw": row.get("Route", ""),
                    "dosage_form_raw": row.get("Dosage Form", ""),
                    "potency_raw": row.get("Potency", ""),
                    "potency_unit_raw": row.get("Unit", ""),
                    "mde_raw": row.get("Maximum Daily Exposure", ""),
                    "mde_unit_raw": row.get("MDE Unit", ""),
                },
            }
        )
    return neutral


def row_checksum(fields: dict) -> str:
    return sha256_payload(fields)
