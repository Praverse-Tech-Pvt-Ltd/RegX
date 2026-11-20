"""Milestone 4D-3 -- thin adapter over the approved unit-conversion service.

Database-free by construction.  This module adds **no** conversion maths and no
second unit table: it delegates entirely to
``backend/iid_assessment/unit_conversion.py`` and translates that service's
reason codes into the 4D-3 input-failure vocabulary (M4D3-UNC-002/008).

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-UNC-001..011  conversion ownership, canonical units, failure mapping
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from iid_assessment import unit_conversion
from iid_assessment.unit_conversion import ConversionReasonCode

from .calculation_translation import format_decimal_plain

#: M4D3-UNC-002 -- the approved conversion service is the single source of truth.
CONVERSION_RULE_VERSION = "iid_assessment.unit_conversion/1.0"

# M4D3-UNC-008 -- ConversionReasonCode -> 4D-3 input-failure code.
# Every branch is explicit; there is no default-to-success path.
_REASON_TO_FAILURE: MappingProxyType[str, str] = MappingProxyType(
    {
        ConversionReasonCode.UNIT_UNKNOWN: "INPUT_UNIT_UNSUPPORTED",
        ConversionReasonCode.DIMENSION_MISMATCH: "INPUT_UNIT_DIMENSION_MISMATCH",
        ConversionReasonCode.CONVERSION_NOT_SUPPORTED: "INPUT_UNIT_UNSUPPORTED",
        ConversionReasonCode.DENSITY_REQUIRED: "INPUT_DENSITY_REQUIRED",
        ConversionReasonCode.BASIS_REQUIRED: "INPUT_DENSITY_REQUIRED",
        ConversionReasonCode.VALUE_MISSING: "INPUT_UNIT_MISSING",
        ConversionReasonCode.INVALID_VALUE: "INPUT_VALUE_INVALID",
    }
)

#: Returned when the source unit itself is absent (M4D3-UNC-004: never inferred).
FAILURE_UNIT_MISSING = "INPUT_UNIT_MISSING"

#: Fail-closed fallback for an unmapped conversion reason.
FAILURE_UNKNOWN = "UNKNOWN_INTERNAL_FAILURE"


@dataclass(frozen=True, slots=True)
class ConversionOutcome:
    """Result of a governed conversion, with provenance for the outcome record."""

    ok: bool
    value: Decimal | None
    failure_code: str | None
    provenance: MappingProxyType[str, object]


def convert_for_calculation(
    *,
    value: object,
    from_unit: str | None,
    to_unit: str,
    density_g_per_ml: object = None,
) -> ConversionOutcome:
    """Convert ``value`` into ``to_unit`` using the approved service.

    Decimal only -- a float input is rejected outright rather than silently
    coerced (M4D3-UNC-005).  A failure never yields a value, so the caller
    cannot invoke a calculation function afterwards (M4D3-UNC-007).
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        return _failure("INPUT_VALUE_INVALID", value, from_unit, to_unit)
    if value.is_nan() or value.is_infinite():
        return _failure("INPUT_VALUE_INVALID", value, from_unit, to_unit)
    if not from_unit or not str(from_unit).strip():
        # M4D3-UNC-004 -- an absent source unit is missing data, not a mismatch.
        return _failure(FAILURE_UNIT_MISSING, value, from_unit, to_unit)
    if not to_unit or not str(to_unit).strip():
        return _failure(FAILURE_UNIT_MISSING, value, from_unit, to_unit)

    # QA-02: stored spellings ("mg", "g", "µg", "ml") are read through the same
    # alias function as the IID comparison path; an unknown unit passes through
    # unchanged and the service refuses it as before.
    result = unit_conversion.convert(
        value,
        unit_conversion.canonical_unit(from_unit) or from_unit,
        unit_conversion.canonical_unit(to_unit) or to_unit,
        density_g_per_ml=density_g_per_ml,
    )

    if not result.ok:
        failure = _REASON_TO_FAILURE.get(result.reason_code or "", FAILURE_UNKNOWN)
        return _failure(failure, value, from_unit, to_unit, reason=result.reason_code)

    converted = result.converted_value
    factor: str | None = None
    if isinstance(converted, Decimal) and value != 0:
        # Plain notation -- provenance must stay human-readable in a regulated
        # record, so never render the factor as 1E+3.
        factor = format_decimal_plain(converted / value)

    return ConversionOutcome(
        ok=True,
        value=converted,
        failure_code=None,
        provenance=MappingProxyType(
            {
                "original_value": format_decimal_plain(value),
                "original_unit": from_unit,
                "converted_value": format_decimal_plain(converted),
                "converted_unit": result.converted_unit or to_unit,
                "conversion_factor": factor,
                "conversion_rule_version": CONVERSION_RULE_VERSION,
            }
        ),
    )


def _failure(
    failure_code: str,
    value: object,
    from_unit: str | None,
    to_unit: str,
    reason: str | None = None,
) -> ConversionOutcome:
    return ConversionOutcome(
        ok=False,
        value=None,
        failure_code=failure_code,
        provenance=MappingProxyType(
            {
                "original_value": (None if value is None else format_decimal_plain(value)),
                "original_unit": from_unit,
                "converted_value": None,
                "converted_unit": to_unit,
                "conversion_factor": None,
                "conversion_rule_version": CONVERSION_RULE_VERSION,
                "conversion_reason_code": reason,
            }
        ),
    )
