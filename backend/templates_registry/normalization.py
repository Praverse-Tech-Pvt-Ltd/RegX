"""
Non-destructive normalization. Every function here returns a normalized
value derived from a raw value -- the raw value is never mutated or
discarded. Callers are responsible for recording a NormalizationMapping
row per applied rule (see importer.apply_normalization).
"""

import html
import re
import unicodedata

# A conservative, targeted mojibake-repair table. Real ftfy-style universal
# repair is out of scope for this milestone; these are the specific
# corruption patterns observed in the legacy source during inventory (see
# docs/TEMPLATE_SOURCE_INVENTORY.md) plus their common cousins.
_MOJIBAKE_REPLACEMENTS = {
    "�": "'",  # literal U+FFFD replacement character standing in for an apostrophe
    "â€™": "'",  # â€™ -> '
    "â€œ": '"',  # â€œ -> "
    "â€�": '"',  # â€ + replacement -> "
    "Ã©": "é",  # Ã© -> é
    "Ã¨": "è",  # Ã¨ -> è
    "": "-",  # Wingdings-derived private-use bullet glyph -> plain dash
}

_NUMBERING_PREFIX = re.compile(r"^\s*(\d{1,3})[\.\)]\s*")


def strip_html(raw_html: str) -> str:
    """Extract plain text from a small HTML fragment (CKEditor-style
    <p>/<br/>/entity output). Deliberately minimal -- no external HTML
    parser dependency -- sufficient for the flat markup this source
    produces."""
    if not raw_html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"</p>\s*<p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text.strip()


def collapse_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\r\n?", "\n", text or "")).strip()


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def repair_mojibake(text: str) -> str:
    repaired = text or ""
    for bad, good in _MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(bad, good)
    return repaired


def split_embedded_numbering(text: str) -> tuple[str, str | None]:
    """If text starts with an embedded ordinal like "1. " or "2) ", split
    it out. Returns (text_without_prefix, prefix_number_or_None). The raw
    text is untouched by this -- callers store the split result as the
    *normalized* text/metadata, never overwriting raw_text."""
    match = _NUMBERING_PREFIX.match(text or "")
    if not match:
        return text, None
    return text[match.end() :].strip(), match.group(1)


def normalize_text_field(raw_text: str) -> dict:
    """Full non-destructive pipeline for a question/title text field.
    Returns a dict describing each step so the caller can record one
    NormalizationMapping row per rule actually applied (i.e. one whose
    output differs from its input)."""
    steps = []

    step1 = strip_html(raw_text)
    steps.append(("html_to_text", raw_text, step1))

    step2 = repair_mojibake(step1)
    steps.append(("mojibake_repair", step1, step2))

    step3 = normalize_unicode(step2)
    steps.append(("unicode_nfc", step2, step3))

    step4 = collapse_whitespace(step3)
    steps.append(("whitespace_collapse", step3, step4))

    final_text, numbering_prefix = split_embedded_numbering(step4)
    steps.append(("embedded_numbering_split", step4, final_text))

    return {
        "normalized_text": final_text,
        "numbering_prefix": numbering_prefix,
        "steps": [
            {"rule": rule, "raw_value": before, "normalized_value": after}
            for rule, before, after in steps
            if before != after
        ],
    }


def normalize_category_value(
    raw_category: str, mapping_table: dict[str, str] | None = None
) -> dict:
    """Category/label normalization. mapping_table is an explicit,
    reviewed raw->normalized lookup (e.g. {"DO�S": "DO'S"}); values not
    present in the table pass through mojibake-repair + whitespace-collapse
    only, with no silent spelling correction."""
    mapping_table = mapping_table or {}
    if raw_category in mapping_table:
        normalized = mapping_table[raw_category]
        rule = "reviewed_category_mapping"
    else:
        normalized = collapse_whitespace(repair_mojibake(raw_category or ""))
        rule = "mojibake_repair_and_whitespace_collapse"
    return {
        "normalized_value": normalized,
        "rule": rule,
        "changed": normalized != raw_category,
    }
