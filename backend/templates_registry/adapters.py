"""
Legacy source adapters.

These convert an already-exported, controlled data structure (a Python
list of dicts, as loaded from a JSON or CSV export -- never a live
database connection) into the neutral source-record schema the import
pipeline consumes. Adapters are isolated from runtime product domains:
they do not import AIDatabase, they do not require legacy SQLite at
runtime, and they never query a live legacy database.

Neutral record schema (one dict per source row):
    {
        "identifier": str,        # stable within the source package
        "raw_text": str,          # the question/title text, as-is
        "raw_payload": dict,      # the full original row, preserved verbatim
        "locator": str,           # "<legacy_table>:<legacy_pk>" or similar
        "extraction_method": str,
        "encoding": str,
        "fields": {
            "template_canonical_code": str,
            "template_title": str,
            "template_category": str,
            "section_code": str,
            "section_title": str,
            "item_code": str,
            "response_type": str,   # optional, defaults to "narrative"
            "required": bool,       # optional, defaults to False
        },
    }

legacy source -> controlled export -> checksum -> neutral import package
-> REGX staging -> review -> approval -> activation. This module is the
"controlled export -> neutral import package" step only.
"""


def anda_like_adapter(rows: list[dict], source_name: str) -> list[dict]:
    """Adapts rows shaped like RATools.ANDAReportQuestions:
    {report_name, module_name, chapter_name, category_name, question}."""
    records = []
    for i, row in enumerate(rows):
        report_name = row.get("report_name", "")
        module_name = row.get("module_name", "")
        chapter_name = row.get("chapter_name", "")
        legacy_pk = row.get("id", i)
        records.append(
            {
                "identifier": f"anda-{legacy_pk}",
                "raw_text": row.get("question", ""),
                "raw_payload": dict(row),
                "locator": f"RATools_andareportquestions:{legacy_pk}",
                "extraction_method": "controlled_export_json",
                "encoding": row.get("_encoding", "utf-8"),
                "fields": {
                    "template_canonical_code": f"ANDA-{_slug(report_name)}",
                    "template_title": f"ANDA — {report_name}".strip(" —"),
                    "template_category": row.get("category_name", ""),
                    "section_code": _slug(module_name or "general"),
                    "section_title": module_name or chapter_name or "General",
                    "item_code": f"item-{legacy_pk}",
                    "response_type": "narrative",
                    "required": False,
                },
            }
        )
    return records


def dmf_like_adapter(rows: list[dict], source_name: str, table_hint: str) -> list[dict]:
    """Adapts rows shaped like RATools.DMFReviewTableQuestion or
    DMFCATableQuestion: {module, category, [sub_category], question}."""
    records = []
    for i, row in enumerate(rows):
        module = row.get("module", "")
        legacy_pk = row.get("id", i)
        records.append(
            {
                "identifier": f"dmf-{table_hint}-{legacy_pk}",
                "raw_text": row.get("question", ""),
                "raw_payload": dict(row),
                "locator": f"RATools_{table_hint}:{legacy_pk}",
                "extraction_method": "controlled_export_json",
                "encoding": row.get("_encoding", "utf-8"),
                "fields": {
                    "template_canonical_code": f"DMF-{table_hint.upper()}",
                    "template_title": f"DMF {table_hint.replace('_', ' ').title()}",
                    "template_category": row.get("category", ""),
                    "section_code": _slug(module or "general"),
                    "section_title": module or "General",
                    "item_code": f"item-{legacy_pk}",
                    "response_type": "yes_no_na",
                    "required": False,
                },
            }
        )
    return records


def _slug(value: str) -> str:
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip()).strip("-").lower()
    return cleaned or "general"
