"""The one authoritative readiness calculation.

Readiness is **derived, never claimed**. A user sets `status`; the system
decides `readiness` from that status, the section's open blockers, its supporting
links and its required children. Nothing in the frontend recomputes it.

**What READY means, exactly:** internally ready according to the configured RegX
section criteria below. It is not regulatory compliance, agency approval,
submission acceptance, filing acceptance, or validated status, and the UI labels
it "Internal readiness" for that reason.

**Why the calculation ignores the caller.** Readiness is computed from backend
data with no permission filter, because a section's readiness must not change
depending on who is looking -- two users would otherwise see contradictory
states for the same section. The privacy obligation is discharged at the
*explanation* layer instead: reasons are coarse enumerated codes that name no
workflow, document or checklist, so a caller who cannot see a linked workflow
still cannot learn anything about it from the reason.
"""

from .models import Readiness, ReadinessReason, SectionStatus


def _has_supporting_work(section, link_counts: dict) -> bool:
    """Any recorded work at all: a link of any kind, or a human saying so."""
    return (
        link_counts.get("document", 0) > 0
        or link_counts.get("workflow", 0) > 0
        or link_counts.get("checklist", 0) > 0
        or section.status == SectionStatus.IN_PROGRESS
    )


def calculate(section, *, open_blockers: int, link_counts: dict, child_results: list) -> tuple:
    """Return `(readiness, reason)` for one section.

    `child_results` is a list of `(required, readiness)` for the section's
    ACTIVE children, already computed -- the caller walks the tree bottom-up so
    this never recurses and never queries.
    """
    # 1. Not applicable short-circuits everything. A section the tenant has
    #    ruled out cannot block its parent and is not "not ready".
    if section.status == SectionStatus.NOT_APPLICABLE:
        return Readiness.NOT_APPLICABLE, ReadinessReason.NOT_APPLICABLE

    # 2. An open blocker is disqualifying regardless of anything else. This is
    #    the whole reason blockers are structured rows rather than prose.
    if open_blockers > 0:
        return Readiness.NOT_READY, ReadinessReason.OPEN_BLOCKER

    # 3. A required child that is not ready holds the parent back. Optional
    #    children never do, and NOT_APPLICABLE children are excluded entirely --
    #    otherwise ruling a section out would make its parent permanently
    #    unreachable.
    required_children_blocking = [
        readiness
        for required, readiness in child_results
        if required and readiness not in (Readiness.READY, Readiness.NOT_APPLICABLE)
    ]

    if section.status == SectionStatus.COMPLETE:
        if required_children_blocking:
            return Readiness.PARTIALLY_READY, ReadinessReason.REQUIRED_CHILD_NOT_READY
        return Readiness.READY, ReadinessReason.READY

    # 4. Not complete. Distinguish "something is happening" from "nothing yet",
    #    because a dossier full of NOT_READY tells a user nothing about where
    #    the work actually stands.
    if _has_supporting_work(section, link_counts) or child_results:
        return Readiness.PARTIALLY_READY, ReadinessReason.SECTION_NOT_COMPLETE

    return Readiness.NOT_READY, ReadinessReason.NO_SUPPORTING_WORK


def aggregate(section_readiness: list) -> tuple:
    """Overall internal readiness for a dossier.

    `section_readiness` is `(required, readiness)` for every ACTIVE section.

    READY only when every required, non-N/A section is READY. A dossier with no
    required sections at all is NOT_READY rather than vacuously READY --
    an empty outline is not a finished one, and reporting READY for it would be
    the most misleading possible answer.
    """
    required = [r for req, r in section_readiness if req and r != Readiness.NOT_APPLICABLE]

    if not required:
        return Readiness.NOT_READY, ReadinessReason.NO_SUPPORTING_WORK

    if all(r == Readiness.READY for r in required):
        return Readiness.READY, ReadinessReason.READY

    if any(r in (Readiness.READY, Readiness.PARTIALLY_READY) for r in required):
        return Readiness.PARTIALLY_READY, ReadinessReason.SECTION_NOT_COMPLETE

    return Readiness.NOT_READY, ReadinessReason.NO_SUPPORTING_WORK


def summarise(section_readiness: list, open_blockers: int) -> dict:
    """Counts for the dossier header.

    Every number here is derived from section state the caller can already see
    one row per. Nothing module-specific is counted -- workflow states, evidence
    counts and document scan states are gated elsewhere and are deliberately not
    aggregated into this.
    """
    readiness_values = [r for _, r in section_readiness]
    overall, reason = aggregate(section_readiness)
    return {
        "total_sections": len(section_readiness),
        "required_sections": sum(1 for req, _ in section_readiness if req),
        "ready": readiness_values.count(Readiness.READY),
        "partially_ready": readiness_values.count(Readiness.PARTIALLY_READY),
        "not_ready": readiness_values.count(Readiness.NOT_READY),
        "not_applicable": readiness_values.count(Readiness.NOT_APPLICABLE),
        "open_blockers": open_blockers,
        "overall_readiness": overall,
        "overall_reason": reason,
    }
