"""
Non-destructive parsing and controlled-vocabulary lookup helpers.

Nothing here guesses. A value that can't be parsed or mapped safely is
left null with an explicit REVIEW_REQUIRED-class status -- never coerced
to a default, never silently dropped.
"""

import re
from decimal import Decimal, InvalidOperation

from .models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    DosageFormMapping,
    RouteMapping,
)

# Orange Book's DF;Route field packs dosage form and route together,
# semicolon-separated (e.g. "TABLET;ORAL"). Some rows use other
# separators observed in practice; this list is intentionally small and
# explicit rather than a permissive catch-all.
_DF_ROUTE_SEPARATORS = (";", " - ")

_STRENGTH_NUMBER_UNIT = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/%]+)\s*$")


def split_dosage_form_route(raw: str) -> tuple[str, str]:
    """Split an Orange Book "DF;Route" field into (dosage_form, route),
    both still raw/unnormalized. Returns ("", "") if no separator is
    found -- never guesses which half is which."""
    raw = (raw or "").strip()
    for sep in _DF_ROUTE_SEPARATORS:
        if sep in raw:
            df, _, route = raw.partition(sep)
            return df.strip(), route.strip()
    return "", ""


def parse_strength(raw: str) -> dict:
    """Attempt to parse a single-value strength string like "500 MG" into
    (amount, unit). Only accepts the single-number-single-unit shape;
    anything else (ratios, multi-ingredient combinations, ranges) is left
    unparsed with status REVIEW_REQUIRED and the raw string preserved."""
    raw = (raw or "").strip()
    match = _STRENGTH_NUMBER_UNIT.match(raw)
    if not match:
        return {"amount": None, "unit_raw": "", "status": "review_required"}
    amount_str, unit_raw = match.groups()
    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        return {"amount": None, "unit_raw": unit_raw, "status": "review_required"}
    return {"amount": amount, "unit_raw": unit_raw, "status": "parsed"}


def lookup_route_mapping(source_dataset: str, raw_value: str) -> ControlledRoute | None:
    """Only an APPROVED, currently-active mapping resolves a raw value to
    a ControlledRoute. A proposed/reviewed-but-not-approved mapping never
    resolves anything."""
    mapping = RouteMapping.objects.filter(
        source_dataset=source_dataset,
        source_raw_value=raw_value,
        is_current=True,
        status="approved",
    ).first()
    return mapping.controlled_route if mapping else None


def lookup_dosage_form_mapping(source_dataset: str, raw_value: str) -> ControlledDosageForm | None:
    mapping = DosageFormMapping.objects.filter(
        source_dataset=source_dataset,
        source_raw_value=raw_value,
        is_current=True,
        status="approved",
    ).first()
    return mapping.controlled_dosage_form if mapping else None


def lookup_unit(unit_raw: str) -> ControlledUnit | None:
    """Exact code/symbol/alias match only -- no fuzzy matching."""
    unit_raw = (unit_raw or "").strip()
    if not unit_raw:
        return None
    from django.db.models import Q

    exact = ControlledUnit.objects.filter(
        Q(code__iexact=unit_raw) | Q(symbol__iexact=unit_raw), active=True
    ).first()
    return exact or _lookup_unit_alias(unit_raw)


def _lookup_unit_alias(unit_raw: str) -> ControlledUnit | None:
    for unit in ControlledUnit.objects.filter(active=True):
        aliases = unit.aliases or []
        if any(str(a).lower() == unit_raw.lower() for a in aliases):
            return unit
    return None
