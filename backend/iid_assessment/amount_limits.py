"""The limits on an amount a user enters, shared by formulation components and the
IID preview so the two always accept and refuse the same amounts.

* Greater than zero. A zero amount is not an amount of an ingredient; the
  formulation component has always refused it, and the IID preview agrees.
* At most 1,000,000 in the family's base unit: **mg** for a mass, **mL** for a
  volume. The amount is converted first (exact powers of ten), so 2,000,000 µg
  (2,000 mg) is fine and 1,000 kg (1,000,000,000 mg) is not. The largest number
  anywhere in the FDA IID July 2026 file is 239,360 mg (a maximum daily
  exposure), so the limit is over four times anything published and catches
  wrong units and extra zeros. A unit that cannot be converted is held to
  1,000,000 as typed (the comparison then refuses the unit anyway).
* A percentage at most 100. Above 100 is impossible for w/w and v/v; for w/v it
  is possible in principle, but the highest IID w/v value is 92.
"""

from __future__ import annotations

from decimal import Decimal

from .comparison import conversion_key
from .unit_conversion import convert_mass_or_volume, dimension_of

MAX_IN_BASE_UNIT = Decimal("1000000")
MAX_PERCENTAGE = Decimal("100")
_BASE = {"mass": ("milligram", "mg"), "volume": ("millilitre", "mL")}


def _shown(value: Decimal) -> str:
    return format(value.normalize(), ",f")


def amount_problem(value: Decimal | None, unit: str, *, is_percentage: bool) -> str | None:
    """None when the amount is acceptable, else a sentence to show the user."""
    if value is None:
        return None
    if value <= 0:
        return "The amount must be greater than zero."
    if is_percentage:
        return "A percentage cannot be more than 100." if value > MAX_PERCENTAGE else None
    key = conversion_key(unit)
    family = dimension_of(key) if key else None
    if family in _BASE:
        base_key, symbol = _BASE[family]
        in_base = convert_mass_or_volume(value, key, base_key).converted_value
        if in_base > MAX_IN_BASE_UNIT:
            entered = f"{_shown(value)} {unit.strip()}"
            converted = "" if key == base_key else f" = {_shown(in_base)} {symbol}"
            return (
                f"The amount cannot be more than 1,000,000 {symbol} "
                f"(you entered {entered}{converted}). The largest value in the FDA IID is "
                "239,360 mg; check the unit and for extra zeros."
            )
        return None
    if value > MAX_IN_BASE_UNIT:
        return (
            "The amount cannot be more than 1,000,000 in the unit entered "
            "(the largest value in the FDA IID is 239,360 mg); check for extra zeros."
        )
    return None
