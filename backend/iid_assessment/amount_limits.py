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
* A percentage at most 100, whatever its spelling ("%", "% w/w", "%w/v",
  "percent", ...). Above 100 is impossible for w/w and v/v; for w/v it is
  possible in principle, but the highest IID w/v value is 92.
* Maximum dosage units per day greater than zero and at most 1,000. The largest
  realistic regimens are a few dozen units a day (for example enzyme capsules
  with every meal); 1,000 leaves a wide margin and still catches an extra zero
  or two (10,000).

A formulation component's unit must be one REGX can convert or read: a mass
(mg, g, kg, µg), a volume (mL, L) or a percentage. `recognised_unit` says which;
anything else (for example "furlongs" or "tablets") is refused for new
components and flagged on old ones as not comparable.
"""

from __future__ import annotations

from decimal import Decimal

from .comparison import conversion_key
from .unit_conversion import convert_mass_or_volume, dimension_of

MAX_IN_BASE_UNIT = Decimal("1000000")
MAX_PERCENTAGE = Decimal("100")
MAX_DOSAGE_UNITS_PER_DAY = Decimal("1000")
PERCENT_UNIT = "percent"
#: The units a formulation component may use, as offered in the screen.
COMPONENT_UNITS = ("mg", "g", "kg", "µg", "mL", "L", PERCENT_UNIT)
UNIT_CHOICE_TEXT = "mg, g, kg, µg, mL, L or % (percent)"
_BASE = {"mass": ("milligram", "mg"), "volume": ("millilitre", "mL")}


def _shown(value: Decimal) -> str:
    return format(value.normalize(), ",f")


def is_percentage_unit(unit: str | None) -> bool:
    """True for any spelling of a percentage: "%", "% w/w", "%w/v", "percent", "pct"."""
    text = (unit or "").strip().lower().replace(" ", "")
    return text.startswith("%") or text in ("pct", "percentage") or text.startswith("percent")


def recognised_unit(unit: str | None) -> str | None:
    """The unit's family ("mass", "volume" or "percentage"), or None when REGX
    cannot convert or read it."""
    if is_percentage_unit(unit):
        return "percentage"
    key = conversion_key(unit)
    return dimension_of(key) if key else None


def unit_problem(unit: str | None) -> str | None:
    """None for a recognised unit, else a sentence for the user."""
    if recognised_unit(unit) is not None:
        return None
    shown = (unit or "").strip()
    return f"Choose a unit from the list: {UNIT_CHOICE_TEXT}" + (
        f" (got '{shown}')." if shown else "."
    )


def dosage_units_per_day_problem(value: Decimal | None) -> str | None:
    """None when the maximum dosage units per day is acceptable (or not given)."""
    if value is None:
        return None
    if value <= 0:
        return "The maximum number of dosage units per day must be greater than zero."
    if value > MAX_DOSAGE_UNITS_PER_DAY:
        return (
            "The maximum number of dosage units per day cannot be more than 1,000 "
            f"(you entered {_shown(value)}); check for extra zeros."
        )
    return None


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
