"""
Source-record classification: the fail-closed gate that decides whether a
record may proceed toward import, or must be excluded before any content
is written into a TemplateItem.

This is a content-boundary guard, independent of (and in addition to) the
AIDatabase import guard enforced at the Python-import level by
common/tests/test_guards.py. That guard proves REGX code never imports the
AIDatabase package; this module proves REGX never imports AIDatabase-*sourced
data* either, even if it arrives via an otherwise-valid neutral JSON package.
"""

import re

# Matches identifiers/table names/source-type strings that indicate 483,
# warning-letter, inspection-analytics, or AIDatabase-originated content.
_EXCLUDED_IDENTIFIER_PATTERNS = [
    re.compile(r"\bform\s*483\b", re.IGNORECASE),
    re.compile(r"\b483\s*observation", re.IGNORECASE),
    re.compile(r"\bwarning\s*letter\b", re.IGNORECASE),
    re.compile(r"\baidatabase\b", re.IGNORECASE),
    re.compile(r"^aid[-_]", re.IGNORECASE),
    re.compile(r"\bpaca\b", re.IGNORECASE),
    re.compile(r"\broot[-_ ]cause\s*inspection", re.IGNORECASE),
    re.compile(r"\binvestigator\s*intelligence\b", re.IGNORECASE),
    re.compile(r"\binspection\s*analytics\b", re.IGNORECASE),
]

_EXCLUDED_SOURCE_TYPE_VALUES = {
    "form483",
    "483",
    "warning_letter",
    "warningletter",
    "aidatabase",
    "inspection_analytics",
    "paca",
}


class ExclusionReason:
    FORM_483_OR_WARNING_LETTER = "excluded_483_or_warning_letter"
    AIDATABASE_SOURCED = "excluded_aidatabase_sourced"
    INSPECTION_ANALYTICS = "excluded_inspection_analytics"


def _matches_excluded_pattern(*values: str) -> str | None:
    for value in values:
        if not value:
            continue
        for pattern in _EXCLUDED_IDENTIFIER_PATTERNS:
            if pattern.search(value):
                if "aidatabase" in value.lower() or re.match(r"^aid[-_]", value, re.IGNORECASE):
                    return ExclusionReason.AIDATABASE_SOURCED
                if re.search(
                    r"paca|root[-_ ]cause|investigator\s*intelligence|analytics",
                    value,
                    re.IGNORECASE,
                ):
                    return ExclusionReason.INSPECTION_ANALYTICS
                return ExclusionReason.FORM_483_OR_WARNING_LETTER
    return None


def classify_source_package(source_type: str, source_name: str) -> str | None:
    """Return an exclusion reason code if this package's declared type/name
    matches disallowed content, else None (eligible to proceed)."""
    if (source_type or "").strip().lower() in _EXCLUDED_SOURCE_TYPE_VALUES:
        return (
            ExclusionReason.FORM_483_OR_WARNING_LETTER
            if "483" in (source_type or "").lower() or "warning" in (source_type or "").lower()
            else ExclusionReason.AIDATABASE_SOURCED
        )
    return _matches_excluded_pattern(source_type, source_name)


def classify_source_record(
    identifier: str, raw_text: str, raw_payload: dict, source_locator: str = ""
) -> str | None:
    """Return an exclusion reason code if this individual record's
    identifier, text, payload, or locator matches disallowed content, else
    None (eligible to proceed to normalization)."""
    payload_str = ""
    try:
        payload_str = " ".join(str(v) for v in raw_payload.values()) if raw_payload else ""
    except Exception:
        payload_str = str(raw_payload)

    return _matches_excluded_pattern(identifier, raw_text, payload_str, source_locator)
