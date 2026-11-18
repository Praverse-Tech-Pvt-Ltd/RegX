"""The limits on an amount a user enters, shared by formulation components and the
IID preview so the two always accept and refuse the same numbers.

* Greater than zero. A zero amount is not an amount of an ingredient; the
  formulation component has always refused it, and the IID preview now agrees.
* At most 1,000,000 in the unit entered. The largest number anywhere in the
  FDA IID July 2026 file is 239,360 (mg, a maximum daily exposure), so the limit
  is over four times anything published. It catches extra-zero typos, which the
  database field (14 digits) let through: 99,999,999,999,999 mg was accepted
  and produced a % w/w of 39,999,999,999,999.6 %.
* A percentage at most 100. Above 100 is impossible for w/w and v/v; for w/v it
  is possible in principle, but the highest IID value is 92, so 100 is a safe
  ceiling and anything above it is far more likely a mistake.
"""

from __future__ import annotations

from decimal import Decimal

MAX_AMOUNT = Decimal("1000000")
MAX_PERCENTAGE = Decimal("100")


def amount_problem(value: Decimal | None, *, is_percentage: bool) -> str | None:
    """None when the amount is acceptable, else a sentence to show the user."""
    if value is None:
        return None
    if value <= 0:
        return "The amount must be greater than zero."
    if is_percentage and value > MAX_PERCENTAGE:
        return "A percentage cannot be more than 100."
    if value > MAX_AMOUNT:
        return (
            "The amount cannot be more than 1,000,000 in the unit entered "
            "(the largest value in the FDA IID is 239,360); check for extra zeros."
        )
    return None
