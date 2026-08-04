"""Milestone 4D-3 -- pure conservative maximum-daily-units selection.

Database-free by construction.  The caller resolves candidates from the ORM
(deferred) and passes immutable values in; this module only selects and explains.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-MDU-001..024  two governed sources, worst-case selection, provenance

Verified schema facts behind this design:
  * ``FormulationVersion.maximum_dosage_units_per_day`` is nullable.
  * ``DosingRegimen.maximum_units_per_day`` is required, ``> 0`` by check
    constraint, one-to-many per version, with **no** lifecycle/status field --
    so no lifecycle filter is invented here (M4D3-MDU-003).
  * ``patient_population`` is free text with no governed selector, so it is
    provenance only and never a filter (M4D3-MDU-009).

Monotonicity rationale (M4D3-MDU-022): daily exposure is
``quantity_per_dosage_unit * maximum_dosage_units_per_day`` and the quantity is
strictly positive by check constraint, so exposure rises with maximum units;
percentage-of-MDE rises with exposure and difference-from-MDE falls (less
headroom).  Selecting the highest candidate is therefore safety-conservative for
every current consumer.  A new consumer requires a fresh monotonicity review
(M4D3-MDU-024).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import TypeGuard

SOURCE_FORMULATION_VERSION = "formulation_version"
SOURCE_DOSING_REGIMEN = "dosing_regimen"
SOURCE_COMBINED_CONSERVATIVE = "combined_conservative"

RESOLVER_VERSION = "1.0"

DETAIL_REQUIRED = "MAX_DAILY_UNITS_REQUIRED"
DETAIL_SOURCE_INVALID = "MAX_DAILY_UNITS_SOURCE_INVALID"
DETAIL_SOURCE_DISAGREEMENT = "MAX_DAILY_UNITS_SOURCE_DISAGREEMENT"


@dataclass(frozen=True, slots=True)
class DosingRegimenCandidate:
    """An immutable, already-resolved ``DosingRegimen`` candidate."""

    public_id: str
    maximum_units_per_day: object
    patient_population: str = ""


@dataclass(frozen=True, slots=True)
class MaxDailyUnitsSelection:
    """Outcome of the conservative resolver."""

    resolved: bool
    value: Decimal | None
    source_type: str | None
    source_disagreement: bool
    detail_code: str | None
    provenance: MappingProxyType[str, object]


def _is_valid_decimal(value: object) -> TypeGuard[Decimal]:
    """Decimal only.  ``bool`` is rejected even though it subclasses ``int``.

    Declared as a ``TypeGuard`` so callers narrow to ``Decimal`` naturally, with
    no need for a type-checker suppression at the assignment sites.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        return False
    if value.is_nan() or value.is_infinite():
        return False
    return value > 0


def select_maximum_daily_units(
    *,
    formulation_version_public_id: str,
    version_scalar: object = None,
    regimen_candidates: tuple[DosingRegimenCandidate, ...] = (),
) -> MaxDailyUnitsSelection:
    """Select the conservative worst-case maximum daily units.

    Returns the selected value plus complete sanitized provenance.  Fails closed
    (``resolved=False``) when no valid candidate exists, so the caller leaves the
    kwarg unresolved and the engine canonicalises to ``DATA_REQUIRED``
    (M4D3-MDU-014).
    """
    invalid: list[str] = []

    # -- Step 1: collect governed candidates (M4D3-MDU-002/005) --------------
    version_candidate: Decimal | None = None
    if version_scalar is not None:
        if _is_valid_decimal(version_scalar):
            version_candidate = version_scalar
        else:
            invalid.append(SOURCE_FORMULATION_VERSION)

    valid_regimens: list[tuple[Decimal, DosingRegimenCandidate]] = []
    for candidate in regimen_candidates:
        units = candidate.maximum_units_per_day
        if _is_valid_decimal(units):
            valid_regimens.append((units, candidate))
        else:
            invalid.append(candidate.public_id)

    considered = tuple(
        {
            "public_id": c.public_id,
            "maximum_units_per_day": str(c.maximum_units_per_day),
            "patient_population": c.patient_population,
            "valid": _is_valid_decimal(c.maximum_units_per_day),
        }
        for c in regimen_candidates
    )

    # -- Step 2: resolve the regimen candidate (M4D3-MDU-007/008) -----------
    regimen_value: Decimal | None = None
    selected_regimen: DosingRegimenCandidate | None = None
    tie_break_applied = False
    if valid_regimens:
        highest = max(value for value, _ in valid_regimens)
        tied = sorted(
            (c for value, c in valid_regimens if value == highest),
            key=lambda c: c.public_id,
        )
        tie_break_applied = len(tied) > 1
        selected_regimen = tied[0]
        regimen_value = highest

    # -- Step 4 (fail closed): nothing usable -------------------------------
    if version_candidate is None and regimen_value is None:
        detail = DETAIL_SOURCE_INVALID if invalid else DETAIL_REQUIRED
        return MaxDailyUnitsSelection(
            resolved=False,
            value=None,
            source_type=None,
            source_disagreement=False,
            detail_code=detail,
            provenance=_provenance(
                formulation_version_public_id=formulation_version_public_id,
                version_scalar=version_scalar,
                considered=considered,
                selected_value=None,
                selected_regimen=None,
                source_type=None,
                disagreement=False,
                tie_break_applied=False,
                invalid=tuple(invalid),
            ),
        )

    # -- Step 3: reconcile the two sources (M4D3-MDU-010/011/012) -----------
    if version_candidate is not None and regimen_value is None:
        selected, source_type, disagreement = (
            version_candidate,
            SOURCE_FORMULATION_VERSION,
            False,
        )
    elif version_candidate is None:
        selected, source_type, disagreement = (
            regimen_value,
            SOURCE_DOSING_REGIMEN,
            False,
        )
    else:
        disagreement = version_candidate != regimen_value
        # Never the lower value, never an average, never creation order.
        selected = max(version_candidate, regimen_value)
        source_type = SOURCE_COMBINED_CONSERVATIVE

    return MaxDailyUnitsSelection(
        resolved=True,
        value=selected,
        source_type=source_type,
        source_disagreement=disagreement,
        detail_code=DETAIL_SOURCE_DISAGREEMENT if disagreement else None,
        provenance=_provenance(
            formulation_version_public_id=formulation_version_public_id,
            version_scalar=version_scalar,
            considered=considered,
            selected_value=selected,
            selected_regimen=selected_regimen,
            source_type=source_type,
            disagreement=disagreement,
            tie_break_applied=tie_break_applied,
            invalid=tuple(invalid),
        ),
    )


def _provenance(
    *,
    formulation_version_public_id: str,
    version_scalar: object,
    considered: tuple[dict[str, object], ...],
    selected_value: Decimal | None,
    selected_regimen: DosingRegimenCandidate | None,
    source_type: str | None,
    disagreement: bool,
    tie_break_applied: bool,
    invalid: tuple[str, ...],
) -> MappingProxyType[str, object]:
    """M4D3-MDU-016/017/018 -- complete provenance, public identifiers only."""
    return MappingProxyType(
        {
            "resolver_version": RESOLVER_VERSION,
            "selected_source_type": source_type,
            "formulation_version_public_id": formulation_version_public_id,
            "version_scalar": None if version_scalar is None else str(version_scalar),
            "considered_regimens": considered,
            "selected_value": None if selected_value is None else str(selected_value),
            "selected_regimen_public_id": (
                None if selected_regimen is None else selected_regimen.public_id
            ),
            "tie_break_applied": tie_break_applied,
            "source_disagreement": disagreement,
            "invalid_candidates": invalid,
        }
    )
