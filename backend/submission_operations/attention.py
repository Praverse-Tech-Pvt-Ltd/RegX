"""Why an item is shown, and in what order. Enumerated, deterministic, internal.

REASON CODES, NOT PROSE
-----------------------
Every row carries a `reason_code` from the enum below and no generated text. A
sentence assembled from the underlying rows would carry exactly the detail the
projection layer withholds -- "workflow WF-14 was rejected" tells a caller
without workflow permission that WF-14 exists -- and it would need re-auditing
every time the wording changed. The frontend maps codes to copy; the backend
never writes a sentence about a resource.

THIS IS OPERATIONAL, NOT REGULATORY
-----------------------------------
`critical` here means "a person should look at this today", not "a deficiency".
None of these codes is a regulatory classification, none maps to an agency
finding, and nothing in this module decides whether a submission is acceptable
to anyone. The severity words are deliberately plain -- `blocked`, `overdue`,
`attention` -- rather than borrowing `Major` or `Critical deficiency`, which
already mean something specific to the people who will read this screen.
"""

from django.db import models


class AttentionReason(models.TextChoices):
    """Only reasons that can be derived truthfully from authoritative state.

    Each one is a fact some other module already owns. Nothing here infers,
    scores or predicts.
    """

    OPEN_BLOCKER = "open_blocker", "Section has an open blocker"
    REQUIRED_SECTION_BLOCKED = "required_section_blocked", "Required section is blocked"
    OVERDUE_REQUIRED_SECTION = "overdue_required_section", "Required section is overdue"
    WORKFLOW_REJECTED = "workflow_rejected", "Linked workflow was rejected"
    DUE_SOON_REQUIRED_SECTION = "due_soon_required_section", "Required section is due soon"
    WORKFLOW_WAITING_REVIEW = "workflow_waiting_review", "Linked workflow is waiting for review"
    REQUIRED_SECTION_NOT_STARTED = "required_section_not_started", "Required section not started"
    BLOCKED_UPGRADE_PLAN = "blocked_upgrade_plan", "Upgrade plan has blocked items"
    STALE_UPGRADE_PLAN = "stale_upgrade_plan", "Upgrade plan is stale"
    DOSSIER_ON_HOLD = "dossier_on_hold", "Case is on hold with open work"
    CASE_WITH_NO_DOSSIER = "case_with_no_dossier", "Open case has no dossier"


class AttentionSeverity(models.TextChoices):
    """Operational urgency. Not a regulatory severity, and not `BlockerSeverity`
    -- that field is tenant-authored data about one blocker, this is a display
    ordering across many kinds of thing."""

    BLOCKED = "blocked", "Blocked"
    OVERDUE = "overdue", "Overdue"
    ATTENTION = "attention", "Needs attention"
    INFORMATIONAL = "informational", "Informational"


#: THE RANKING. Lower sorts first. Documented here as the single source, so the
#: ordering test and the docs read the same numbers rather than two copies that
#: drift.
#:
#:   1  blocked            work cannot proceed at all
#:   2  overdue            a date the tenant themselves set has passed
#:   3  rejected workflow  a decision came back negative and needs a response
#:   4  due soon           a date is approaching
#:   5  not started        required work nobody has picked up
#:   6  informational      true, worth knowing, not urgent
#:
#: Blocked outranks overdue because an overdue item someone can still work on is
#: a worse thing to bury than a blocked one nobody can. Rejected outranks due
#: soon because a rejection is already a fact while a due date is a forecast.
REASON_RANK: dict[str, int] = {
    AttentionReason.REQUIRED_SECTION_BLOCKED: 1,
    AttentionReason.OPEN_BLOCKER: 1,
    AttentionReason.BLOCKED_UPGRADE_PLAN: 1,
    AttentionReason.OVERDUE_REQUIRED_SECTION: 2,
    AttentionReason.WORKFLOW_REJECTED: 3,
    AttentionReason.DUE_SOON_REQUIRED_SECTION: 4,
    AttentionReason.WORKFLOW_WAITING_REVIEW: 4,
    AttentionReason.REQUIRED_SECTION_NOT_STARTED: 5,
    AttentionReason.STALE_UPGRADE_PLAN: 6,
    AttentionReason.DOSSIER_ON_HOLD: 6,
    AttentionReason.CASE_WITH_NO_DOSSIER: 6,
}

REASON_SEVERITY: dict[str, str] = {
    AttentionReason.REQUIRED_SECTION_BLOCKED: AttentionSeverity.BLOCKED,
    AttentionReason.OPEN_BLOCKER: AttentionSeverity.BLOCKED,
    AttentionReason.BLOCKED_UPGRADE_PLAN: AttentionSeverity.BLOCKED,
    AttentionReason.OVERDUE_REQUIRED_SECTION: AttentionSeverity.OVERDUE,
    AttentionReason.WORKFLOW_REJECTED: AttentionSeverity.ATTENTION,
    AttentionReason.DUE_SOON_REQUIRED_SECTION: AttentionSeverity.ATTENTION,
    AttentionReason.WORKFLOW_WAITING_REVIEW: AttentionSeverity.ATTENTION,
    AttentionReason.REQUIRED_SECTION_NOT_STARTED: AttentionSeverity.ATTENTION,
    AttentionReason.STALE_UPGRADE_PLAN: AttentionSeverity.INFORMATIONAL,
    AttentionReason.DOSSIER_ON_HOLD: AttentionSeverity.INFORMATIONAL,
    AttentionReason.CASE_WITH_NO_DOSSIER: AttentionSeverity.INFORMATIONAL,
}

#: Which module a reason is derived from. A caller who cannot see that module
#: never receives the row -- not a redacted version of it, not a count of how
#: many were withheld. "3 rows hidden" is itself the leak.
REASON_MODULE: dict[str, str] = {
    AttentionReason.REQUIRED_SECTION_BLOCKED: "dossiers",
    AttentionReason.OPEN_BLOCKER: "dossiers",
    AttentionReason.OVERDUE_REQUIRED_SECTION: "dossiers",
    AttentionReason.DUE_SOON_REQUIRED_SECTION: "dossiers",
    AttentionReason.REQUIRED_SECTION_NOT_STARTED: "dossiers",
    AttentionReason.WORKFLOW_REJECTED: "workflows",
    AttentionReason.WORKFLOW_WAITING_REVIEW: "workflows",
    AttentionReason.BLOCKED_UPGRADE_PLAN: "upgrades",
    AttentionReason.STALE_UPGRADE_PLAN: "upgrades",
    AttentionReason.DOSSIER_ON_HOLD: "cases",
    AttentionReason.CASE_WITH_NO_DOSSIER: "cases",
}


def sort_key(row: dict):
    """Deterministic to the last field.

    rank, then oldest-relevant-date first, then most-recently-touched, then
    `public_id`. The final tie-break is not decoration: two rows with identical
    rank and timestamps must still come back in the same order on every request,
    or pagination silently drops and repeats rows between pages.
    """
    due = row.get("due_date")
    return (
        REASON_RANK[row["reason_code"]],
        (0, due) if due is not None else (1, None),
        row["_sort_updated_desc"],
        str(row["resource_public_id"]),
    )
