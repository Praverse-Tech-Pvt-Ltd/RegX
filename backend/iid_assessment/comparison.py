"""Like-for-like IID comparison (controlled units, increment 3).

THE ONLY PATH that decides whether an IID potency limit can be compared, and how.
Design: docs/CONTROLLED_UNITS_DESIGN.md sections 3-4 and 8. The old unit link
(`IIDPrecedentRecord.potency_unit_normalized`, `fda_data.terminology.lookup_unit`)
is kept for history only and is read nowhere here.

A proposed amount and an IID record are compared only when both state a
`QuantityExpression` meaning with the SAME family and the SAME basis:

- per dose unit: mass with mass (mg per dose unit), volume with volume;
- per volume: mass per stated volume with mass per stated volume, volume per
  volume with volume per volume. The two stated volumes may differ: the proposed
  amount is restated per the IID record's stated volume by exact rational
  arithmetic (a per b mL -> a x d / b per d mL), never by assuming anything;
- percentage: w/w with w/w, w/v with w/v, v/v with v/v.

Within a family the numerator units convert by an exact power-of-ten factor
(`unit_conversion.convert_mass_or_volume`). Nothing ever converts between
families or bases (no density, no total unit weight, no per-day rule). Anything
else is "cannot compare" with one reason code.

The result is computed, never stored as a decision. It carries the IID record,
its source row and release, the controlled-units release in force, and the label
below. It states only "at or below" or "above" the IID value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction

from . import unit_conversion

LABEL = "technically comparable (not regulatorily approved)"


class CannotCompare:
    """Reason codes, one per refusal. Order of checks is fixed (see compare())."""

    ROUTE_OR_FORM_UNMAPPED = "ROUTE_OR_FORM_UNMAPPED"
    NO_NUMERIC_LIMIT = "NO_NUMERIC_LIMIT"
    DAILY_EXPOSURE_ONLY_NEEDS_Q8 = "DAILY_EXPOSURE_ONLY_NEEDS_Q8"
    IID_UNIT_MISSING = "IID_UNIT_MISSING"
    PROPOSED_VALUE_MISSING = "PROPOSED_VALUE_MISSING"
    PROPOSED_UNIT_MISSING = "PROPOSED_UNIT_MISSING"
    DIFFERENT_FAMILY = "DIFFERENT_FAMILY"
    DIFFERENT_BASIS = "DIFFERENT_BASIS"


_P = "cannot compare: "
REASON_TEXT = {
    CannotCompare.ROUTE_OR_FORM_UNMAPPED: _P
    + "the IID record's route or dosage form is not mapped",
    CannotCompare.NO_NUMERIC_LIMIT: _P + "the IID record has no numeric limit",
    CannotCompare.DAILY_EXPOSURE_ONLY_NEEDS_Q8: (
        _P + "the IID record states only a maximum daily exposure; comparing per day is not "
        "supported yet"
    ),
    CannotCompare.IID_UNIT_MISSING: _P + "the IID record's unit has no established meaning",
    CannotCompare.PROPOSED_VALUE_MISSING: _P + "the proposed amount is missing",
    CannotCompare.PROPOSED_UNIT_MISSING: _P + "the proposed unit has no established meaning",
    CannotCompare.DIFFERENT_FAMILY: (
        _P + "different unit family (e.g. mass vs volume vs percentage)"
    ),
    CannotCompare.DIFFERENT_BASIS: (
        _P + "different basis (e.g. per dose unit vs per volume, w/w vs w/v)"
    ),
}

AT_OR_BELOW, ABOVE = "at_or_below", "above"

#: ControlledUnit code -> the exact-factor key used by unit_conversion. A code
#: that already is such a key maps to itself.
_CONVERSION_KEY = {
    "mg": "milligram",
    "mcg": "microgram",
    "ug": "microgram",
    "µg": "microgram",  # micro sign
    "μg": "microgram",  # Greek small letter mu
    "g": "gram",
    "kg": "kilogram",
    "ml": "millilitre",
    "l": "litre",
}


def conversion_key(unit_code: str | None) -> str | None:
    code = (unit_code or "").strip().lower()
    if not code:
        return None
    key = _CONVERSION_KEY.get(code, code)
    return key if unit_conversion.dimension_of(key) in ("mass", "volume") else None


@dataclass(frozen=True)
class Quantity:
    """An amount with an exact meaning: family + basis (+ units, + stated volume)."""

    amount: Decimal | None
    family: str
    basis: str
    unit: str | None = None  # unit_conversion key, e.g. "milligram"; None for percentages
    denominator_amount: Decimal | None = None
    denominator_unit: str | None = None  # unit_conversion key, per-volume only

    @classmethod
    def from_expression(cls, amount, expression) -> Quantity:
        return cls(
            amount=amount,
            family=expression.family,
            basis=expression.basis,
            unit=conversion_key(expression.numerator_unit.code)
            if expression.numerator_unit_id
            else None,
            denominator_amount=expression.denominator_amount,
            denominator_unit=(
                conversion_key(expression.denominator_unit.code)
                if expression.denominator_unit_id
                else None
            ),
        )

    def display_unit(self) -> str:
        symbols = {
            "milligram": "mg",
            "microgram": "mcg",
            "gram": "g",
            "kilogram": "kg",
            "millilitre": "mL",
            "litre": "L",
        }
        if self.family == "percentage":
            return "%" + self.basis.replace("_", "/")
        unit = symbols.get(self.unit or "", self.unit or "?")
        if self.basis == "per_volume":
            den = symbols.get(self.denominator_unit or "", "?")
            return f"{unit}/{self.denominator_amount.normalize():f}{den}"
        if self.basis == "per_dose_unit":
            return f"{unit} per dose unit"
        return f"{unit} per day"


@dataclass(frozen=True)
class ComparisonResult:
    comparable: bool
    reason_code: str | None
    reason: str
    result: str | None  # AT_OR_BELOW / ABOVE when comparable
    proposed_value: str | None  # in `unit`, exact unless rounded_for_display
    iid_value: str | None
    unit: str | None
    rounded_for_display: bool
    conversion: str
    label: str | None
    iid_record_public_id: str
    iid_release_public_id: str
    iid_source_row: dict
    unit_list_release_public_id: str | None
    #: The meaning the proposed amount was read with (increment 4), e.g.
    #: "mg per dose unit", "mg/5mL", "%w/w". None when it has none.
    proposed_meaning: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _source_row(record) -> dict:
    return {
        "source_row_locator": record.source_row_locator,
        "ingredient_name": record.ingredient_name_raw,
        "route": record.route_raw,
        "dosage_form": record.dosage_form_raw,
        "potency_amount": record.potency_amount_raw,
        "potency_unit": record.potency_unit_raw,
        "maximum_daily_exposure": record.mde_amount_raw,
        "maximum_daily_exposure_unit": record.mde_unit_raw,
    }


def _exact_decimal(value: Fraction) -> tuple[Decimal, bool]:
    """The Fraction as a Decimal, exact when it terminates; else rounded to 6
    places for DISPLAY only (the comparison itself always uses the Fraction)."""
    den = value.denominator
    for p in (2, 5):
        while den % p == 0:
            den //= p
    if den == 1:
        return (Decimal(value.numerator) / Decimal(value.denominator)).normalize(), False
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        Decimal("0.000001")
    ), True


def compare(
    proposed: Quantity, record, *, unit_list_release_public_id: str | None = None
) -> ComparisonResult:
    """Compare a proposed amount with one IID record's potency limit."""
    base = {
        "proposed_meaning": (
            proposed.display_unit()
            if proposed.family in ("mass", "volume", "percentage")
            and (proposed.family == "percentage" or proposed.unit)
            else None
        ),
        "iid_record_public_id": str(record.public_id),
        "iid_release_public_id": str(record.release.public_id),
        "iid_source_row": _source_row(record),
        "unit_list_release_public_id": unit_list_release_public_id,
    }

    def refuse(code: str) -> ComparisonResult:
        return ComparisonResult(
            comparable=False,
            reason_code=code,
            reason=REASON_TEXT[code],
            result=None,
            proposed_value=None,
            iid_value=None,
            unit=None,
            rounded_for_display=False,
            conversion="",
            label=None,
            **base,
        )

    if record.route_normalized_id is None or record.dosage_form_normalized_id is None:
        return refuse(CannotCompare.ROUTE_OR_FORM_UNMAPPED)
    if record.potency_amount is None:
        if record.maximum_daily_exposure is not None:
            return refuse(CannotCompare.DAILY_EXPOSURE_ONLY_NEEDS_Q8)
        return refuse(CannotCompare.NO_NUMERIC_LIMIT)
    if record.potency_expression_id is None:
        return refuse(CannotCompare.IID_UNIT_MISSING)
    if proposed.amount is None:
        return refuse(CannotCompare.PROPOSED_VALUE_MISSING)
    iid = Quantity.from_expression(record.potency_amount, record.potency_expression)
    if proposed.family not in ("mass", "volume", "percentage") or (
        proposed.family != "percentage" and proposed.unit is None
    ):
        return refuse(CannotCompare.PROPOSED_UNIT_MISSING)
    if proposed.family != iid.family:
        return refuse(CannotCompare.DIFFERENT_FAMILY)
    if proposed.basis != iid.basis:
        return refuse(CannotCompare.DIFFERENT_BASIS)

    value = Fraction(Decimal(str(proposed.amount)))
    steps = []
    if iid.family != "percentage":
        if proposed.unit != iid.unit:  # same dimension by family; exact power-of-ten factor
            conv = unit_conversion.convert_mass_or_volume(Decimal(1), proposed.unit, iid.unit)
            if not conv.ok:
                return refuse(CannotCompare.PROPOSED_UNIT_MISSING)
            value *= Fraction(conv.converted_value)
            steps.append(
                f"{proposed.unit} -> {iid.unit} (exact factor {conv.converted_value.normalize():f})"
            )
        if iid.basis == "per_volume":
            if proposed.denominator_amount is None or proposed.denominator_unit is None:
                return refuse(CannotCompare.PROPOSED_UNIT_MISSING)
            den_conv = unit_conversion.convert_mass_or_volume(
                proposed.denominator_amount, proposed.denominator_unit, iid.denominator_unit
            )
            if not den_conv.ok:
                return refuse(CannotCompare.PROPOSED_UNIT_MISSING)
            proposed_den = Fraction(den_conv.converted_value)
            iid_den = Fraction(Decimal(str(iid.denominator_amount)))
            if proposed_den != iid_den:
                value = value * iid_den / proposed_den
                steps.append(
                    f"restated per {iid.denominator_amount.normalize():f} "
                    f"{iid.denominator_unit} "
                    f"(x {iid_den} / {proposed_den}, exact rational arithmetic)"
                )
    iid_value = Fraction(Decimal(str(record.potency_amount)))
    shown, rounded = _exact_decimal(value)
    return ComparisonResult(
        comparable=True,
        reason_code=None,
        reason="compared like for like (same family and basis)",
        result=AT_OR_BELOW if value <= iid_value else ABOVE,
        proposed_value=f"{shown:f}",
        iid_value=f"{Decimal(str(record.potency_amount)).normalize():f}",
        unit=iid.display_unit(),
        rounded_for_display=rounded,
        conversion="; ".join(steps) or "none needed",
        label=LABEL,
        **base,
    )


def stated_quantity(amount, expression) -> Quantity:
    """A formulation amount with the meaning it states (increment 4).

    Only a meaning in force (listed by the active controlled-units release) is
    used. Anything else yields a quantity with no family, which `compare()`
    refuses with PROPOSED_UNIT_MISSING: a meaning the reviewed list does not
    carry is never compared.
    """
    from fda_data.controlled_units import in_force_expressions

    if expression is None or expression.pk not in in_force_expressions():
        return Quantity(amount=amount, family="", basis="")
    return Quantity.from_expression(amount, expression)


def per_dose_unit_quantity(amount, unit: str | None) -> Quantity:
    """A formulation component's quantity: an amount per dosage unit by definition.
    `unit` is a unit_conversion key or a ControlledUnit code (mg, g, mcg, ml)."""
    key = conversion_key(unit)
    family = unit_conversion.dimension_of(key) if key else None
    return Quantity(amount=amount, family=family or "", basis="per_dose_unit", unit=key)


def active_unit_list_release_public_id() -> str | None:
    from fda_data.controlled_units import active_release

    release = active_release()
    return str(release.public_id) if release else None
