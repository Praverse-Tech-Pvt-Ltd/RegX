"""
Deterministic, Decimal-only unit-conversion service.

No float arithmetic anywhere in this module. No implicit unit guessing --
every conversion either succeeds with an explicit result, or fails closed
with one of the documented reason codes. Mass<->volume conversion requires
an explicitly supplied, approved density; percentage/concentration
conversions require an explicitly supplied basis. Nothing here ever
invents a default.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MASS_UNITS = {
    "microgram": Decimal("0.000001"),
    "milligram": Decimal("0.001"),
    "gram": Decimal("1"),
    "kilogram": Decimal("1000"),
}
# Base mass unit = gram.

VOLUME_UNITS = {
    "microlitre": Decimal("0.000001"),
    "millilitre": Decimal("0.001"),
    "litre": Decimal("1"),
}
# Base volume unit = litre.

COUNT_UNITS = {"tablet", "capsule", "unit", "actuation", "dose"}

DIMENSION_OF_UNIT: dict[str, str] = (
    dict.fromkeys(MASS_UNITS, "mass")
    | dict.fromkeys(VOLUME_UNITS, "volume")
    | dict.fromkeys(COUNT_UNITS, "count")
)


class ConversionReasonCode:
    UNIT_UNKNOWN = "UNIT_UNKNOWN"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    BASIS_REQUIRED = "BASIS_REQUIRED"
    DENSITY_REQUIRED = "DENSITY_REQUIRED"
    CONVERSION_NOT_SUPPORTED = "CONVERSION_NOT_SUPPORTED"
    VALUE_MISSING = "VALUE_MISSING"
    INVALID_VALUE = "INVALID_VALUE"


@dataclass(frozen=True)
class ConversionResult:
    ok: bool
    original_value: Decimal | None
    original_unit: str | None
    converted_value: Decimal | None
    converted_unit: str | None
    reason_code: str | None = None

    @property
    def failed(self) -> bool:
        return not self.ok


def _fail(reason_code: str, original_value=None, original_unit=None) -> ConversionResult:
    return ConversionResult(
        ok=False,
        original_value=original_value,
        original_unit=original_unit,
        converted_value=None,
        converted_unit=None,
        reason_code=reason_code,
    )


def dimension_of(unit: str) -> str | None:
    return DIMENSION_OF_UNIT.get((unit or "").strip().lower())


def convert_mass_or_volume(value, from_unit: str, to_unit: str) -> ConversionResult:
    """Convert within the SAME dimension only (mass<->mass or
    volume<->volume). Fails closed for any cross-dimension request --
    use convert_with_density for mass<->volume."""
    if value is None:
        return _fail(ConversionReasonCode.VALUE_MISSING, None, from_unit)
    try:
        value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return _fail(ConversionReasonCode.INVALID_VALUE, None, from_unit)

    from_unit_key = (from_unit or "").strip().lower()
    to_unit_key = (to_unit or "").strip().lower()
    from_dim = dimension_of(from_unit_key)
    to_dim = dimension_of(to_unit_key)

    if from_dim is None or to_dim is None:
        return _fail(ConversionReasonCode.UNIT_UNKNOWN, value, from_unit)
    if from_dim != to_dim:
        return _fail(ConversionReasonCode.DIMENSION_MISMATCH, value, from_unit)
    if from_dim not in ("mass", "volume"):
        return _fail(ConversionReasonCode.CONVERSION_NOT_SUPPORTED, value, from_unit)

    table = MASS_UNITS if from_dim == "mass" else VOLUME_UNITS
    base_value = value * table[from_unit_key]
    converted = base_value / table[to_unit_key]
    return ConversionResult(
        ok=True,
        original_value=value,
        original_unit=from_unit,
        converted_value=converted,
        converted_unit=to_unit,
    )


def convert_with_density(value, from_unit: str, to_unit: str, density_g_per_ml) -> ConversionResult:
    """Mass<->volume conversion. Requires an explicitly supplied,
    approved density (grams per millilitre) -- never assumed or defaulted."""
    if value is None:
        return _fail(ConversionReasonCode.VALUE_MISSING, None, from_unit)
    from_dim = dimension_of(from_unit)
    to_dim = dimension_of(to_unit)
    if from_dim is None or to_dim is None:
        return _fail(ConversionReasonCode.UNIT_UNKNOWN, None, from_unit)
    if {from_dim, to_dim} != {"mass", "volume"}:
        return _fail(ConversionReasonCode.DIMENSION_MISMATCH, None, from_unit)
    if density_g_per_ml is None:
        return _fail(ConversionReasonCode.DENSITY_REQUIRED, None, from_unit)
    try:
        value = Decimal(str(value))
        density = Decimal(str(density_g_per_ml))
    except (InvalidOperation, TypeError, ValueError):
        return _fail(ConversionReasonCode.INVALID_VALUE, None, from_unit)
    if density <= 0:
        return _fail(ConversionReasonCode.INVALID_VALUE, value, from_unit)

    # Normalize to grams and millilitres first, then apply density.
    grams_per_base = MASS_UNITS
    ml_per_base = {
        "microlitre": Decimal("0.001"),
        "millilitre": Decimal("1"),
        "litre": Decimal("1000"),
    }

    if from_dim == "mass":
        grams = value * grams_per_base[from_unit.strip().lower()]
        ml = grams / density
        converted = ml / ml_per_base[to_unit.strip().lower()]
    else:
        ml = value * ml_per_base[from_unit.strip().lower()]
        grams = ml * density
        converted = grams / grams_per_base[to_unit.strip().lower()]

    return ConversionResult(
        ok=True,
        original_value=value,
        original_unit=from_unit,
        converted_value=converted,
        converted_unit=to_unit,
    )


def calculate_percentage_w_w(
    component_value, component_unit: str, total_value, total_unit: str
) -> ConversionResult:
    """% w/w requires component and total both expressed as compatible
    mass units and an explicit non-zero total -- no basis is assumed."""
    if component_value is None or total_value is None:
        return _fail(ConversionReasonCode.VALUE_MISSING)
    if dimension_of(component_unit) != "mass" or dimension_of(total_unit) != "mass":
        return _fail(ConversionReasonCode.BASIS_REQUIRED, component_value, component_unit)
    converted_total = convert_mass_or_volume(total_value, total_unit, "gram")
    converted_component = convert_mass_or_volume(component_value, component_unit, "gram")
    if converted_total.failed or converted_component.failed:
        return _fail(ConversionReasonCode.CONVERSION_NOT_SUPPORTED, component_value, component_unit)
    if converted_total.converted_value == 0:
        return _fail(ConversionReasonCode.INVALID_VALUE, component_value, component_unit)
    percentage = (converted_component.converted_value / converted_total.converted_value) * Decimal(
        100
    )
    return ConversionResult(
        ok=True,
        original_value=component_value,
        original_unit=component_unit,
        converted_value=percentage,
        converted_unit="percent_w_w",
    )


def convert(value, from_unit: str, to_unit: str, *, density_g_per_ml=None) -> ConversionResult:
    """Top-level entry point: dispatches to the right conversion path.
    Fails closed with UNIT_UNKNOWN for anything not recognized."""
    if from_unit is None or to_unit is None:
        return _fail(ConversionReasonCode.UNIT_UNKNOWN, value, from_unit)
    from_dim = dimension_of(from_unit)
    to_dim = dimension_of(to_unit)
    if from_dim is None or to_dim is None:
        return _fail(ConversionReasonCode.UNIT_UNKNOWN, value, from_unit)
    if from_dim == to_dim:
        if from_dim == "count":
            if from_unit.strip().lower() != to_unit.strip().lower():
                return _fail(ConversionReasonCode.CONVERSION_NOT_SUPPORTED, value, from_unit)
            try:
                value = Decimal(str(value)) if value is not None else None
            except (InvalidOperation, TypeError, ValueError):
                return _fail(ConversionReasonCode.INVALID_VALUE, None, from_unit)
            if value is None:
                return _fail(ConversionReasonCode.VALUE_MISSING, None, from_unit)
            return ConversionResult(True, value, from_unit, value, to_unit)
        return convert_mass_or_volume(value, from_unit, to_unit)
    if {from_dim, to_dim} == {"mass", "volume"}:
        if density_g_per_ml is None:
            return _fail(ConversionReasonCode.DENSITY_REQUIRED, value, from_unit)
        return convert_with_density(value, from_unit, to_unit, density_g_per_ml)
    return _fail(ConversionReasonCode.DIMENSION_MISMATCH, value, from_unit)
