"""Governed maximum-daily-units resolution from persisted formulation rows.

One helper, used by **every** caller that creates a governed
``AssessmentSnapshot``: the checklist calculation-execution service and the
persisted snapshot API endpoint. Both must reach the same answer, because a
snapshot's frozen ``decision_status`` depends on it, so the collection of the two
governed sources lives here rather than being written twice.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-MDU-001  the two governed sources
  - M4D3-MDU-002/003/005  candidate eligibility
  - M4D3-MDU-006  **no dosing value is ever accepted from a client request**
  - M4D3-MDU-010  worst-case reconciliation -- the higher of the two
  - M4D3-MDU-013/014  fail closed, leaving the kwarg unresolved

This module reads rows and hands plain values to
``common.max_daily_units.select_maximum_daily_units()``. It implements no
comparison, no tie-break and no fallback of its own: every scientific rule stays
in that one pure selector.

It lives in ``formulations`` because that is where the rows live and because both
callers may import it. ``iig_checklist`` may not be imported by ``iid_assessment``
(contract ``iig-checklist-content-is-not-imported-by-governed-domains``), so a
helper in the checklist app could not have served the API path.
"""

from __future__ import annotations

from common.max_daily_units import (
    DosingRegimenCandidate,
    MaxDailyUnitsSelection,
    select_maximum_daily_units,
)


def collect_dosing_regimen_candidates(formulation_version):
    """Every governed ``DosingRegimen`` of this exact formulation version.

    No lifecycle filter is invented: ``DosingRegimen`` has no status field, so
    every related row is a governed candidate (M4D3-MDU-003). Rows are read
    fresh and ordered by ``public_id`` purely so provenance is byte-stable across
    runs -- the selector's own M4D3-MDU-007/008 rules decide which one wins, not
    this ordering. Nothing is dropped: an invalid value is passed through and the
    selector records it as invalid (M4D3-MDU-005).
    """
    return tuple(
        DosingRegimenCandidate(
            public_id=str(regimen.public_id),
            maximum_units_per_day=regimen.maximum_units_per_day,
            patient_population=regimen.patient_population,
        )
        for regimen in formulation_version.dosing_regimens.all().order_by("public_id")
    )


def resolve_governed_maximum_daily_units(
    *, formulation_version
) -> MaxDailyUnitsSelection:
    """The conservative worst-case selection for one formulation version.

    Both governed sources are supplied -- the version scalar and every dosing
    regimen -- and the selector reconciles them, taking the higher
    (M4D3-MDU-010). ``formulation_version`` must be a **current** instance: the
    caller is responsible for reading it inside its transaction rather than
    passing a stale cached relation, because every frozen snapshot value derives
    from it.

    Returns the selector's own ``MaxDailyUnitsSelection``. When it fails closed
    (``resolved=False``) the caller leaves the kwarg unresolved so the engine
    canonicalises to ``DATA_REQUIRED`` (M4D3-MDU-014) -- never substituting zero,
    one source, or an invented default.
    """
    return select_maximum_daily_units(
        formulation_version_public_id=str(formulation_version.public_id),
        version_scalar=formulation_version.maximum_dosage_units_per_day,
        regimen_candidates=collect_dosing_regimen_candidates(formulation_version),
    )


def governed_maximum_daily_units_value(*, formulation_version):
    """The selected ``Decimal``, or ``None`` when the selection failed closed."""
    selection = resolve_governed_maximum_daily_units(
        formulation_version=formulation_version
    )
    return selection.value if selection.resolved else None


def current_formulation_version(formulation_version_id):
    """The current row for this identity -- never a caller's cached relation.

    A ``ChecklistExecution`` holds ``formulation_version`` as a lazily-loaded FK.
    Once that descriptor is populated it keeps whatever the row looked like when
    it was first touched, so resolving governed values from it can silently use
    stale data. Callers that hold only an identity go through here instead.
    """
    from .models import FormulationVersion

    return FormulationVersion.objects.select_related("product").get(
        pk=formulation_version_id
    )


def resolve_current_maximum_daily_units(
    *, formulation_version_id
) -> MaxDailyUnitsSelection:
    """Fresh read plus governed selection, for a caller holding an identity.

    The one entry point for callers that do not already hold a current
    ``FormulationVersion``. It reads the row inside the caller's transaction and
    then applies exactly the same governed selection as every other caller, so a
    stale execution instance cannot make one consumer disagree with another.

    Read-only: no write, no lock, no audit.
    """
    return resolve_governed_maximum_daily_units(
        formulation_version=current_formulation_version(formulation_version_id)
    )


__all__ = [
    "collect_dosing_regimen_candidates",
    "current_formulation_version",
    "governed_maximum_daily_units_value",
    "resolve_current_maximum_daily_units",
    "resolve_governed_maximum_daily_units",
]
