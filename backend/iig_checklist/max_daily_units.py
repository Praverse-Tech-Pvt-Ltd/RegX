"""Milestone 4D-3 Part 14.1 -- the governed maximum-daily-units selector.

The selection algorithm itself now lives in ``common.max_daily_units``. It was
moved there unchanged, and this module re-exports it so the governed identity
that M4D3-MDU-001..024 and the acceptance matrix refer to keeps its name and its
import path.

**Why it moved.** M4D3-MDU-006 forbids accepting a dosing value from a client
request payload, so the persisted snapshot endpoint in ``iid_assessment`` must
derive the value through this selector. The import contract
``iig-checklist-content-is-not-imported-by-governed-domains`` forbids
``iid_assessment`` importing anything from this app, so a selector that only
lives here is unreachable from the endpoint that needs it. The algorithm is pure
-- ``dataclasses``, ``Decimal``, no ORM, no Django -- so ``common`` is where a
shared, domain-free rule belongs, and both callers can now reach exactly one
implementation.

Nothing about the selection changed: not the two governed sources, not the
worst-case reconciliation of M4D3-MDU-010, not the M4D3-MDU-008 tie-break, not
the fail-closed contract of M4D3-MDU-013/014. ``select_maximum_daily_units``
remains the sole scientific selector.

Callers reading rows from the database should use
``formulations.dosing.resolve_governed_maximum_daily_units()``, which collects
both governed sources and calls this selector, rather than assembling candidates
themselves.
"""

from __future__ import annotations

from common.max_daily_units import (
    DETAIL_REQUIRED,
    DETAIL_SOURCE_DISAGREEMENT,
    DETAIL_SOURCE_INVALID,
    RESOLVER_VERSION,
    SOURCE_COMBINED_CONSERVATIVE,
    SOURCE_DOSING_REGIMEN,
    SOURCE_FORMULATION_VERSION,
    DosingRegimenCandidate,
    MaxDailyUnitsSelection,
    select_maximum_daily_units,
)

__all__ = [
    "DETAIL_REQUIRED",
    "DETAIL_SOURCE_DISAGREEMENT",
    "DETAIL_SOURCE_INVALID",
    "RESOLVER_VERSION",
    "SOURCE_COMBINED_CONSERVATIVE",
    "SOURCE_DOSING_REGIMEN",
    "SOURCE_FORMULATION_VERSION",
    "DosingRegimenCandidate",
    "MaxDailyUnitsSelection",
    "select_maximum_daily_units",
]
