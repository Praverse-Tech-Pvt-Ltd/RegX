"""Shared CSV formula-injection neutralisation.

Promoted from ``templates_registry.reconciliation._csv_safe_cell`` per
``MILESTONE_4D_DISCOVERY.md`` §17, which resolved this as former Open Question 3:

    ``templates_registry.reconciliation``'s private ``_csv_safe_cell()`` helper
    is promoted to ``common`` now, not duplicated. […] a single shared
    implementation does meaningfully reduce the risk of one consumer's copy
    silently drifting out of sync with a future CSV-injection-safety fix.
    Promotion requires making the function public (dropping the leading
    underscore) and updating ``templates_registry``'s own import to point at the
    promoted ``common`` version, so there is exactly one implementation
    platform-wide, not two that happen to agree today.

The behaviour is carried over unchanged. This module is deliberately
dependency-free — no Django, no models — so it stays importable from any app and
cannot violate the ``common``-has-no-domain-imports contract.
"""

from __future__ import annotations

__all__ = ["CSV_FORMULA_TRIGGER_CHARS", "csv_safe_cell"]

# Any string whose effective first character (after skipping plain leading
# spaces) is one of these is a formula/DDE trigger in Excel, Google Sheets,
# and LibreOffice (CWE-1236). A leading apostrophe is the standard,
# universally-supported "force text" escape: it makes the affected cell
# display its original value verbatim while never being evaluated.
CSV_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_safe_cell(value) -> str:
    """Neutralize a single CSV cell value against spreadsheet formula
    injection. This only affects the rendered export -- it never touches
    the underlying database value (callers pass in already-fetched strings;
    nothing here performs a .save())."""
    text = "" if value is None else str(value)
    effective_first_char = text.lstrip(" ")[:1]
    if effective_first_char in CSV_FORMULA_TRIGGER_CHARS:
        return "'" + text
    return text
