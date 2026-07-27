"""
Pure, versioned, Decimal-only calculation services.

Every function returns a structured CalculationResult carrying its
formula identifier/version, inputs, provenance, status, and reason code --
never a bare number. A blocked calculation always returns a documented
status, never a silently-omitted value or a zero standing in for "unknown."
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

FORMULA_VERSION = "1.0.0"


class CalculationStatus:
    OK = "OK"
    ROUTE_MISMATCH = "ROUTE_MISMATCH"
    DOSAGE_FORM_MISMATCH = "DOSAGE_FORM_MISMATCH"
    INGREDIENT_UNRESOLVED = "INGREDIENT_UNRESOLVED"
    UNIT_CONVERSION_FAILED = "UNIT_MISMATCH"
    IID_VALUE_MISSING = "FDA_VALUE_UNAVAILABLE"
    IID_VALUE_INVALID = "FDA_VALUE_UNAVAILABLE"
    PROPOSED_VALUE_MISSING = "DATA_REQUIRED"
    MAX_DAILY_UNITS_MISSING = "DATA_REQUIRED"
    BASIS_UNCLEAR = "NOT_COMPARABLE"
    RELEASE_NOT_ACTIVE = "REGULATORY_REVIEW_REQUIRED"
    RECORD_SUPERSEDED = "REGULATORY_REVIEW_REQUIRED"


@dataclass(frozen=True)
class CalculationResult:
    formula_identifier: str
    formula_version: str
    status: str
    value: Decimal | None = None
    unit: str | None = None
    inputs: dict = field(default_factory=dict)
    input_provenance: dict = field(default_factory=dict)
    rounding_rule: str = "none (Decimal, unrounded)"
    reason_code: str | None = None
    generated_at: str = ""

    @property
    def ok(self) -> bool:
        return self.status == CalculationStatus.OK


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _blocked(
    formula_id: str, status: str, inputs: dict, provenance: dict | None = None
) -> CalculationResult:
    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=status,
        inputs=inputs,
        input_provenance=provenance or {},
        reason_code=status,
        generated_at=_now_iso(),
    )


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def calculate_percentage_w_w(
    *, quantity_per_unit_grams, total_dosage_unit_weight_grams
) -> CalculationResult:
    """A: excipient % w/w = quantity_per_unit / total_dosage_unit_weight * 100."""
    formula_id = "percentage_w_w"
    q = _to_decimal(quantity_per_unit_grams)
    t = _to_decimal(total_dosage_unit_weight_grams)
    inputs = {
        "quantity_per_unit_grams": str(quantity_per_unit_grams),
        "total_dosage_unit_weight_grams": str(total_dosage_unit_weight_grams),
    }
    if q is None or t is None:
        return _blocked(formula_id, CalculationStatus.PROPOSED_VALUE_MISSING, inputs)
    if t == 0:
        return _blocked(formula_id, CalculationStatus.BASIS_UNCLEAR, inputs)
    value = (q / t) * Decimal(100)
    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=CalculationStatus.OK,
        value=value,
        unit="percent_w_w",
        inputs=inputs,
        generated_at=_now_iso(),
    )


def calculate_daily_exposure(
    *, quantity_per_dosage_unit, maximum_dosage_units_per_day
) -> CalculationResult:
    """B: proposed maximum daily excipient exposure = quantity_per_unit * max_units_per_day."""
    formula_id = "daily_exposure"
    q = _to_decimal(quantity_per_dosage_unit)
    m = _to_decimal(maximum_dosage_units_per_day)
    inputs = {
        "quantity_per_dosage_unit": str(quantity_per_dosage_unit),
        "maximum_dosage_units_per_day": str(maximum_dosage_units_per_day),
    }
    if q is None:
        return _blocked(formula_id, CalculationStatus.PROPOSED_VALUE_MISSING, inputs)
    if m is None:
        return _blocked(formula_id, CalculationStatus.MAX_DAILY_UNITS_MISSING, inputs)
    value = q * m
    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=CalculationStatus.OK,
        value=value,
        inputs=inputs,
        generated_at=_now_iso(),
    )


def calculate_percentage_of_potency(
    *, converted_proposed_quantity, selected_iid_potency_amount
) -> CalculationResult:
    """C: % of selected IID potency precedent."""
    formula_id = "percentage_of_iid_potency"
    p = _to_decimal(converted_proposed_quantity)
    ref = _to_decimal(selected_iid_potency_amount)
    inputs = {
        "converted_proposed_quantity": str(converted_proposed_quantity),
        "selected_iid_potency_amount": str(selected_iid_potency_amount),
    }
    if p is None:
        return _blocked(formula_id, CalculationStatus.PROPOSED_VALUE_MISSING, inputs)
    if ref is None:
        return _blocked(formula_id, CalculationStatus.IID_VALUE_MISSING, inputs)
    if ref <= 0:
        return _blocked(formula_id, CalculationStatus.IID_VALUE_INVALID, inputs)
    value = (p / ref) * Decimal(100)
    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=CalculationStatus.OK,
        value=value,
        unit="percent_of_potency",
        inputs=inputs,
        generated_at=_now_iso(),
    )


def calculate_difference_from_potency(
    *, selected_iid_potency_amount, converted_proposed_quantity
) -> CalculationResult:
    """D: selected IID potency - converted proposed quantity."""
    formula_id = "difference_from_iid_potency"
    ref = _to_decimal(selected_iid_potency_amount)
    p = _to_decimal(converted_proposed_quantity)
    inputs = {
        "selected_iid_potency_amount": str(selected_iid_potency_amount),
        "converted_proposed_quantity": str(converted_proposed_quantity),
    }
    if ref is None:
        return _blocked(formula_id, CalculationStatus.IID_VALUE_MISSING, inputs)
    if p is None:
        return _blocked(formula_id, CalculationStatus.PROPOSED_VALUE_MISSING, inputs)
    value = ref - p
    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=CalculationStatus.OK,
        value=value,
        inputs=inputs,
        generated_at=_now_iso(),
    )


def calculate_percentage_of_mde(
    *, converted_proposed_daily_exposure, selected_iid_mde
) -> CalculationResult:
    """E: % of selected IID MDE. Blocked (not zero) when MDE is unavailable."""
    formula_id = "percentage_of_iid_mde"
    e = _to_decimal(converted_proposed_daily_exposure)
    ref = _to_decimal(selected_iid_mde)
    inputs = {
        "converted_proposed_daily_exposure": str(converted_proposed_daily_exposure),
        "selected_iid_mde": str(selected_iid_mde),
    }
    if e is None:
        return _blocked(formula_id, CalculationStatus.PROPOSED_VALUE_MISSING, inputs)
    if ref is None:
        return _blocked(formula_id, CalculationStatus.IID_VALUE_MISSING, inputs)
    if ref <= 0:
        return _blocked(formula_id, CalculationStatus.IID_VALUE_INVALID, inputs)
    value = (e / ref) * Decimal(100)
    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=CalculationStatus.OK,
        value=value,
        unit="percent_of_mde",
        inputs=inputs,
        generated_at=_now_iso(),
    )


def calculate_difference_from_mde(
    *, selected_iid_mde, converted_proposed_daily_exposure
) -> CalculationResult:
    """F: selected IID MDE - converted proposed daily exposure."""
    formula_id = "difference_from_iid_mde"
    ref = _to_decimal(selected_iid_mde)
    e = _to_decimal(converted_proposed_daily_exposure)
    inputs = {
        "selected_iid_mde": str(selected_iid_mde),
        "converted_proposed_daily_exposure": str(converted_proposed_daily_exposure),
    }
    if ref is None:
        return _blocked(formula_id, CalculationStatus.IID_VALUE_MISSING, inputs)
    if e is None:
        return _blocked(formula_id, CalculationStatus.PROPOSED_VALUE_MISSING, inputs)
    value = ref - e
    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=CalculationStatus.OK,
        value=value,
        inputs=inputs,
        generated_at=_now_iso(),
    )
