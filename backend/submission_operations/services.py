"""Read-only aggregation across the governed domains.

**THIS MODULE OWNS NO DATA AND DECIDES NOTHING.**

Every number here is counted from a table another app owns, using that app's own
status fields and that app's own view permission. There is no second source of
truth: no copied readiness, no cached counts, no stored dashboard state. Delete
this app and every fact it reports still exists, unchanged, where it always was.

WHAT "INTERNALLY READY" MEANS
-----------------------------
Exactly: *every active required section of this dossier has Milestone 9
readiness READY*. Nothing more. It is not a claim about a submission, an agency,
a filing or a regulation, and the wording says "internally" everywhere it
appears -- in the API, in the tests and on the screen -- because the shortest
path to a dangerous product is a green badge that reads "ready".

Readiness itself is never recomputed here. M9 derives it, persists it and owns
the formula; this module reads the column. A dashboard that re-derived readiness
from section status would be a second implementation of a governed rule, and the
two would disagree the first time M9 changed.

QUERY STRATEGY
--------------
Aggregate per page, not per row. Every list resolves in a bounded number of
queries: one for the page of parents, then one grouped aggregate per dimension
over exactly that page's ids. Adding rows to a page adds no queries. The
alternative -- annotating four `Count(distinct=True)` across three joins onto one
queryset -- keeps the query count at one and quietly multiplies the row count,
which is worse and much harder to notice.
"""

from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from .attention import REASON_SEVERITY, AttentionReason, sort_key
from .projection import (
    MODULE_CASES,
    MODULE_CHECKLISTS,
    MODULE_DOCUMENTS,
    MODULE_DOSSIERS,
    MODULE_UPGRADES,
    MODULE_WORKFLOWS,
    Visibility,
    visibility_for,
)

#: Operational UX threshold for "due soon", in calendar days.
#:
#: **This is a display window and carries no regulatory meaning.** It is not a
#: submission deadline, a review period, a statutory clock or an agency
#: timeline. It exists so a person scanning the queue sees what is approaching
#: before it is late, and 7 was chosen because it is one working week -- not
#: because any authority says so. Tenants set their own due dates; this only
#: decides when one starts appearing in amber.
DISPLAY_DUE_SOON_DAYS = 7

#: How many candidate rows each attention source contributes before the merge.
#:
#: The queue is a triage list, not an export. Without a cap a tenant with 50,000
#: overdue sections would materialise all of them to show 25, and the honest fix
#: is a bound plus a truthful "there are more" flag rather than silent
#: truncation that reads as "this is everything".
ATTENTION_SCAN_LIMIT = 500

#: The label. Pinned as a constant so the test asserting the wording and the
#: response asserting it are the same string.
SEMANTICS = "internal_operational"

INTERNAL_READINESS_READY = "internally_ready"
INTERNAL_READINESS_PARTIAL = "internally_partially_ready"
INTERNAL_READINESS_NOT_READY = "internally_not_ready"
INTERNAL_READINESS_NO_REQUIRED = "no_required_sections"

#: The complete set, so the filter validator and the frontend cannot drift from
#: the labels the aggregation actually emits.
INTERNAL_READINESS_VALUES = frozenset(
    {
        INTERNAL_READINESS_READY,
        INTERNAL_READINESS_PARTIAL,
        INTERNAL_READINESS_NOT_READY,
        INTERNAL_READINESS_NO_REQUIRED,
    }
)


def _today():
    """The tenant-facing date, from Django's configured timezone.

    `timezone.localdate()` rather than `date.today()`: due dates are stored as
    dates and compared against "today", and taking that from the server's naive
    clock puts the boundary in the wrong place for anyone not sitting in UTC.
    """
    return timezone.localdate()


# ---------------------------------------------------------------------------
# Base querysets -- every one tenant-scoped at the first call, never filtered
# down in Python afterwards.
# ---------------------------------------------------------------------------
def _cases(tenant):
    from regulatory_cases.models import RegulatoryCase

    return RegulatoryCase.objects.filter(tenant=tenant)


def _dossiers(tenant):
    from submission_dossiers.models import SubmissionDossier

    return SubmissionDossier.objects.filter(tenant=tenant)


def _active_sections(tenant):
    """Active sections only.

    `retired_at__isnull=True` is not an optimisation. A retired section is
    withdrawn work, and counting one as outstanding would show a permanent
    overdue item nobody can clear -- M9 retires rather than deletes precisely so
    the history survives, and history is not a to-do list.
    """
    from submission_dossiers.models import DossierSection

    return DossierSection.objects.filter(tenant=tenant, retired_at__isnull=True)


def _required_sections(tenant):
    """Active *required* sections in non-terminal dossiers.

    Optional sections are excluded from every completion metric: a tenant marking
    a section not-required has said it does not gate the work, and counting it
    would make their own judgement invisible.
    """
    from submission_dossiers.models import TERMINAL_DOSSIER_STATUSES

    return (
        _active_sections(tenant)
        .filter(
            required=True,
        )
        .exclude(dossier__status__in=TERMINAL_DOSSIER_STATUSES)
    )


def _open_blockers(tenant):
    from submission_dossiers.models import BlockerStatus, DossierSectionBlocker

    return DossierSectionBlocker.objects.filter(
        tenant=tenant,
        status=BlockerStatus.OPEN,
        section__retired_at__isnull=True,
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
def overview(*, user, tenant, visibility: Visibility | None = None) -> dict:
    """Tenant-wide operational summary, gated dimension by dimension.

    A restricted module is `None`, never `0`. See `projection`.
    """
    from submission_dossiers.models import DossierStatus, Readiness, SectionStatus

    vis = visibility or visibility_for(user, tenant)
    today = _today()
    soon = today + timedelta(days=DISPLAY_DUE_SOON_DAYS)

    cases_block = None
    if vis.allows(MODULE_CASES):
        from regulatory_cases.models import CaseStatus

        agg = _cases(tenant).aggregate(
            open=Count("id", filter=Q(status=CaseStatus.OPEN)),
            on_hold=Count("id", filter=Q(status=CaseStatus.ON_HOLD)),
            completed=Count("id", filter=Q(status=CaseStatus.COMPLETED)),
            cancelled=Count("id", filter=Q(status=CaseStatus.CANCELLED)),
        )
        cases_block = {
            "open": agg["open"],
            "on_hold": agg["on_hold"],
            "completed": agg["completed"],
            "cancelled": agg["cancelled"],
        }

    dossiers_block = None
    sections_block = None
    blockers_block = None
    if vis.allows(MODULE_DOSSIERS):
        d = _dossiers(tenant).aggregate(
            open=Count("id", filter=Q(status=DossierStatus.OPEN)),
            on_hold=Count("id", filter=Q(status=DossierStatus.ON_HOLD)),
            completed=Count("id", filter=Q(status=DossierStatus.COMPLETED)),
            cancelled=Count("id", filter=Q(status=DossierStatus.CANCELLED)),
        )
        dossiers_block = {
            "open": d["open"],
            "on_hold": d["on_hold"],
            "completed": d["completed"],
            "cancelled": d["cancelled"],
        }

        s = _required_sections(tenant).aggregate(
            total=Count("id"),
            # Readiness is M9's derived column, read not recomputed.
            complete=Count("id", filter=Q(readiness=Readiness.READY)),
            blocked=Count("id", filter=Q(status=SectionStatus.BLOCKED)),
            overdue=Count(
                "id",
                filter=Q(due_date__lt=today) & ~Q(readiness=Readiness.READY),
            ),
            due_soon=Count(
                "id",
                filter=Q(due_date__gte=today, due_date__lte=soon) & ~Q(readiness=Readiness.READY),
            ),
            not_started=Count("id", filter=Q(status=SectionStatus.NOT_STARTED)),
        )
        sections_block = {
            "required_total": s["total"],
            "required_complete": s["complete"],
            "required_blocked": s["blocked"],
            "required_overdue": s["overdue"],
            "required_due_soon": s["due_soon"],
            "required_not_started": s["not_started"],
        }
        blockers_block = {"open": _open_blockers(tenant).count()}

    workflows_block = None
    if vis.allows(MODULE_WORKFLOWS):
        from workflows.models import WorkflowItem

        now = timezone.now()
        w = WorkflowItem.objects.filter(tenant=tenant).aggregate(
            waiting_review=Count(
                "id",
                filter=Q(state__in=[WorkflowItem.State.SUBMITTED, WorkflowItem.State.IN_REVIEW]),
            ),
            rejected=Count("id", filter=Q(state=WorkflowItem.State.REJECTED)),
            overdue=Count(
                "id",
                filter=Q(due_at__lt=now)
                & ~Q(
                    state__in=[
                        WorkflowItem.State.APPROVED,
                        WorkflowItem.State.REJECTED,
                        WorkflowItem.State.CANCELLED,
                    ]
                ),
            ),
        )
        workflows_block = {
            "waiting_review": w["waiting_review"],
            "rejected": w["rejected"],
            "overdue": w["overdue"],
        }

    documents_block = None
    if vis.allows(MODULE_DOCUMENTS):
        from submission_dossiers.models import DossierSectionDocument

        documents_block = {
            "linked": DossierSectionDocument.objects.filter(
                tenant=tenant, unlinked_at__isnull=True, section__retired_at__isnull=True
            ).count()
        }

    checklists_block = None
    if vis.allows(MODULE_CHECKLISTS):
        from iig_checklist.enums import ExecutionStatus
        from iig_checklist.models import ChecklistExecution

        c = ChecklistExecution.objects.filter(tenant=tenant).aggregate(
            incomplete=Count(
                "id",
                filter=Q(
                    status__in=[
                        ExecutionStatus.DRAFT,
                        ExecutionStatus.SUBMITTED_FOR_REVIEW,
                        ExecutionStatus.RETURNED,
                    ]
                ),
            ),
        )
        checklists_block = {"incomplete": c["incomplete"]}

    upgrades_block = None
    if vis.allows(MODULE_UPGRADES):
        upgrades_block = _upgrade_summary(tenant)

    return {
        "cases": cases_block,
        "dossiers": dossiers_block,
        "sections": sections_block,
        "blockers": blockers_block,
        "workflows": workflows_block,
        "documents": documents_block,
        "checklists": checklists_block,
        "upgrades": upgrades_block,
        "restricted_modules": vis.restricted_modules,
        "due_soon_days": DISPLAY_DUE_SOON_DAYS,
        "generated_at": timezone.now(),
        "semantics": SEMANTICS,
    }


def _upgrade_summary(tenant) -> dict:
    """Open, blocked and stale plan counts in a bounded number of queries.

    Staleness needs a structural fingerprint per dossier, and M11's
    `is_stale()` loads one dossier's sections per call -- correct there, an N+1
    here. So the sections for every dossier with an open plan are fetched once
    and grouped in memory, and M11's `structural_fingerprint` does the hashing.
    The formula is not reimplemented; only the loading is batched.
    """
    from dossier_upgrades.models import DossierUpgradePlan, ItemStatus, PlanStatus

    open_plans = list(
        DossierUpgradePlan.objects.filter(
            tenant=tenant, status__in=[PlanStatus.DRAFT, PlanStatus.READY]
        ).values("id", "dossier_id", "dossier_fingerprint")
    )
    if not open_plans:
        return {"open": 0, "blocked": 0, "stale": 0}

    plan_ids = [p["id"] for p in open_plans]
    blocked_plan_ids = set(
        DossierUpgradePlan.objects.filter(
            id__in=plan_ids, items__status=ItemStatus.BLOCKED
        ).values_list("id", flat=True)
    )

    fingerprints = _fingerprints_for({p["dossier_id"] for p in open_plans}, tenant)
    stale = sum(
        1 for p in open_plans if fingerprints.get(p["dossier_id"]) != p["dossier_fingerprint"]
    )
    return {
        "open": len(open_plans),
        "blocked": len(blocked_plan_ids),
        "stale": stale,
    }


def _fingerprints_for(dossier_ids, tenant) -> dict:
    """One query for every dossier's sections, then M11's hash per dossier."""
    from dossier_upgrades.fingerprint import structural_fingerprint

    if not dossier_ids:
        return {}
    sections = (
        _active_sections(tenant)
        .filter(dossier_id__in=dossier_ids)
        .select_related("parent")
        .order_by("dossier_id", "id")
    )
    grouped: dict = {did: [] for did in dossier_ids}
    for section in sections:
        grouped.setdefault(section.dossier_id, []).append(section)
    return {did: structural_fingerprint(rows) for did, rows in grouped.items()}


# ---------------------------------------------------------------------------
# Internal readiness -- aggregated from M9, never recomputed
# ---------------------------------------------------------------------------
def internal_readiness_label(required_total: int, required_complete: int) -> str:
    """Aggregate M9 readiness into one internal word.

    Deliberately four-valued. A dossier with no required sections is not
    "ready" -- there is nothing to be ready about -- and collapsing that into
    the same green as a finished dossier is the single most misleading thing
    this screen could do.
    """
    if required_total == 0:
        return INTERNAL_READINESS_NO_REQUIRED
    if required_complete >= required_total:
        return INTERNAL_READINESS_READY
    if required_complete > 0:
        return INTERNAL_READINESS_PARTIAL
    return INTERNAL_READINESS_NOT_READY


# ---------------------------------------------------------------------------
# Case rows
# ---------------------------------------------------------------------------
def case_rows(*, tenant, visibility: Visibility, queryset=None) -> list[dict]:
    """Operational summary per case, aggregated over exactly the given page.

    `queryset` is already paginated by the view. Every dimension below is one
    grouped query over that page's ids, so a page of 500 costs the same number
    of queries as a page of 1.
    """
    from submission_dossiers.models import (
        DossierStatus,
        Readiness,
        SectionStatus,
        SubmissionDossier,
    )

    cases = list(queryset) if queryset is not None else list(_cases(tenant))
    if not cases:
        return []
    case_ids = [c.pk for c in cases]
    today = _today()
    soon = today + timedelta(days=DISPLAY_DUE_SOON_DAYS)

    dossier_counts: dict = {}
    section_stats: dict = {}
    blocker_counts: dict = {}
    if visibility.allows(MODULE_DOSSIERS):
        for row in (
            SubmissionDossier.objects.filter(tenant=tenant, regulatory_case_id__in=case_ids)
            .values("regulatory_case_id")
            .annotate(
                total=Count("id"),
                open=Count("id", filter=Q(status=DossierStatus.OPEN)),
            )
        ):
            dossier_counts[row["regulatory_case_id"]] = row

        for row in (
            _required_sections(tenant)
            .filter(dossier__regulatory_case_id__in=case_ids)
            .values("dossier__regulatory_case_id")
            .annotate(
                required_total=Count("id"),
                required_complete=Count("id", filter=Q(readiness=Readiness.READY)),
                blocked=Count("id", filter=Q(status=SectionStatus.BLOCKED)),
                overdue=Count("id", filter=Q(due_date__lt=today) & ~Q(readiness=Readiness.READY)),
                due_soon=Count(
                    "id",
                    filter=Q(due_date__gte=today, due_date__lte=soon)
                    & ~Q(readiness=Readiness.READY),
                ),
            )
        ):
            section_stats[row["dossier__regulatory_case_id"]] = row

        for row in (
            _open_blockers(tenant)
            .filter(section__dossier__regulatory_case_id__in=case_ids)
            .values("section__dossier__regulatory_case_id")
            .annotate(n=Count("id"))
        ):
            blocker_counts[row["section__dossier__regulatory_case_id"]] = row["n"]

    workflow_attention: dict = {}
    if visibility.allows(MODULE_WORKFLOWS):
        workflow_attention = _case_workflow_attention(tenant, case_ids)

    upgrade_attention: dict = {}
    if visibility.allows(MODULE_UPGRADES):
        upgrade_attention = _case_upgrade_attention(tenant, case_ids)

    rows = []
    for case in cases:
        stats = section_stats.get(case.pk, {})
        required_total = stats.get("required_total", 0)
        required_complete = stats.get("required_complete", 0)
        dcounts = dossier_counts.get(case.pk, {})
        rows.append(
            {
                "public_id": case.public_id,
                "case_number": case.case_number,
                "title": case.title,
                "status": case.status,
                "target_date": case.target_date,
                "owner": _user_ref(case.owner) if case.owner_id else None,
                "last_activity_at": case.updated_at,
                "dossiers": visibility.gate(
                    MODULE_DOSSIERS,
                    {"total": dcounts.get("total", 0), "open": dcounts.get("open", 0)},
                ),
                "sections": visibility.gate(
                    MODULE_DOSSIERS,
                    {
                        "required_total": required_total,
                        "required_complete": required_complete,
                        "blocked": stats.get("blocked", 0),
                        "overdue": stats.get("overdue", 0),
                        "due_soon": stats.get("due_soon", 0),
                    },
                ),
                "open_blockers": visibility.gate(MODULE_DOSSIERS, blocker_counts.get(case.pk, 0)),
                "internal_readiness": visibility.gate(
                    MODULE_DOSSIERS,
                    internal_readiness_label(required_total, required_complete),
                ),
                "workflow_attention": visibility.gate(
                    MODULE_WORKFLOWS, workflow_attention.get(case.pk, 0)
                ),
                "upgrade_attention": visibility.gate(
                    MODULE_UPGRADES, upgrade_attention.get(case.pk, 0)
                ),
            }
        )
    return rows


def _case_workflow_attention(tenant, case_ids) -> dict:
    """Rejected or waiting-review workflows linked to each case, in one query."""
    from regulatory_cases.models import RegulatoryCaseWorkflow
    from workflows.models import WorkflowItem

    counts: dict = {}
    for row in (
        RegulatoryCaseWorkflow.objects.filter(
            tenant=tenant,
            case_id__in=case_ids,
            unlinked_at__isnull=True,
            workflow_item__state__in=[
                WorkflowItem.State.REJECTED,
                WorkflowItem.State.SUBMITTED,
                WorkflowItem.State.IN_REVIEW,
            ],
        )
        .values("case_id")
        .annotate(n=Count("id"))
    ):
        counts[row["case_id"]] = row["n"]
    return counts


def _case_upgrade_attention(tenant, case_ids) -> dict:
    """Open plans that are blocked or stale, per case."""
    from dossier_upgrades.models import DossierUpgradePlan, ItemStatus, PlanStatus

    plans = list(
        DossierUpgradePlan.objects.filter(
            tenant=tenant,
            status__in=[PlanStatus.DRAFT, PlanStatus.READY],
            dossier__regulatory_case_id__in=case_ids,
        )
        .annotate(
            has_blocked=Exists(
                DossierUpgradePlan.objects.filter(
                    pk=OuterRef("pk"), items__status=ItemStatus.BLOCKED
                )
            )
        )
        .values(
            "id",
            "dossier_id",
            "dossier_fingerprint",
            "has_blocked",
            "dossier__regulatory_case_id",
        )
    )
    if not plans:
        return {}
    fingerprints = _fingerprints_for({p["dossier_id"] for p in plans}, tenant)
    counts: dict = {}
    for p in plans:
        stale = fingerprints.get(p["dossier_id"]) != p["dossier_fingerprint"]
        if p["has_blocked"] or stale:
            key = p["dossier__regulatory_case_id"]
            counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Dossier rows
# ---------------------------------------------------------------------------
def dossier_rows(*, tenant, visibility: Visibility, queryset=None) -> list[dict]:
    from submission_dossiers.models import Readiness, SectionStatus

    dossiers = list(queryset) if queryset is not None else list(_dossiers(tenant))
    if not dossiers:
        return []
    ids = [d.pk for d in dossiers]
    today = _today()
    soon = today + timedelta(days=DISPLAY_DUE_SOON_DAYS)

    stats: dict = {}
    for row in (
        _active_sections(tenant)
        .filter(dossier_id__in=ids, required=True)
        .values("dossier_id")
        .annotate(
            required_total=Count("id"),
            required_complete=Count("id", filter=Q(readiness=Readiness.READY)),
            blocked=Count("id", filter=Q(status=SectionStatus.BLOCKED)),
            overdue=Count("id", filter=Q(due_date__lt=today) & ~Q(readiness=Readiness.READY)),
            due_soon=Count(
                "id",
                filter=Q(due_date__gte=today, due_date__lte=soon) & ~Q(readiness=Readiness.READY),
            ),
        )
    ):
        stats[row["dossier_id"]] = row

    blockers: dict = {}
    for row in (
        _open_blockers(tenant)
        .filter(section__dossier_id__in=ids)
        .values("section__dossier_id")
        .annotate(n=Count("id"))
    ):
        blockers[row["section__dossier_id"]] = row["n"]

    upgrade_flags: dict = {}
    if visibility.allows(MODULE_UPGRADES):
        upgrade_flags = _dossier_upgrade_flags(tenant, ids)

    rows = []
    for d in dossiers:
        s = stats.get(d.pk, {})
        required_total = s.get("required_total", 0)
        required_complete = s.get("required_complete", 0)
        rows.append(
            {
                "public_id": d.public_id,
                "title": d.title,
                "status": d.status,
                "case_public_id": (
                    d.regulatory_case.public_id if visibility.allows(MODULE_CASES) else None
                ),
                "case_number": (
                    d.regulatory_case.case_number if visibility.allows(MODULE_CASES) else None
                ),
                "internal_readiness": internal_readiness_label(required_total, required_complete),
                "required_total": required_total,
                "required_complete": required_complete,
                "blocked_sections": s.get("blocked", 0),
                "overdue_sections": s.get("overdue", 0),
                "due_soon_sections": s.get("due_soon", 0),
                "open_blockers": blockers.get(d.pk, 0),
                "target_date": d.target_date,
                "owner": _user_ref(d.owner) if d.owner_id else None,
                "last_activity_at": d.updated_at,
                "upgrade": visibility.gate(
                    MODULE_UPGRADES,
                    upgrade_flags.get(d.pk, {"open": 0, "blocked": 0, "stale": 0}),
                ),
            }
        )
    return rows


def _dossier_upgrade_flags(tenant, dossier_ids) -> dict:
    from dossier_upgrades.models import DossierUpgradePlan, ItemStatus, PlanStatus

    plans = list(
        DossierUpgradePlan.objects.filter(
            tenant=tenant,
            status__in=[PlanStatus.DRAFT, PlanStatus.READY],
            dossier_id__in=dossier_ids,
        )
        .annotate(
            has_blocked=Exists(
                DossierUpgradePlan.objects.filter(
                    pk=OuterRef("pk"), items__status=ItemStatus.BLOCKED
                )
            )
        )
        .values("id", "dossier_id", "dossier_fingerprint", "has_blocked")
    )
    if not plans:
        return {}
    fingerprints = _fingerprints_for({p["dossier_id"] for p in plans}, tenant)
    flags: dict = {}
    for p in plans:
        entry = flags.setdefault(p["dossier_id"], {"open": 0, "blocked": 0, "stale": 0})
        entry["open"] += 1
        if p["has_blocked"]:
            entry["blocked"] += 1
        if fingerprints.get(p["dossier_id"]) != p["dossier_fingerprint"]:
            entry["stale"] += 1
    return flags


# ---------------------------------------------------------------------------
# Attention queue
# ---------------------------------------------------------------------------
def attention_rows(*, tenant, visibility: Visibility) -> tuple[list[dict], bool]:
    """Every reason the caller is entitled to see, merged and ranked.

    Returns `(rows, truncated)`. A restricted module contributes nothing at all
    -- not a redacted row, not a "3 hidden" note. A count of withheld rows is
    itself the disclosure this module exists to prevent.
    """
    from submission_dossiers.models import (
        TERMINAL_DOSSIER_STATUSES,
        Readiness,
        SectionStatus,
    )

    rows: list[dict] = []
    truncated = False
    today = _today()
    soon = today + timedelta(days=DISPLAY_DUE_SOON_DAYS)

    def add(source_rows) -> None:
        nonlocal truncated
        materialised = list(source_rows[: ATTENTION_SCAN_LIMIT + 1])
        if len(materialised) > ATTENTION_SCAN_LIMIT:
            truncated = True
            materialised = materialised[:ATTENTION_SCAN_LIMIT]
        rows.extend(materialised)

    if visibility.allows(MODULE_DOSSIERS):
        base = (
            _required_sections(tenant)
            .select_related("dossier", "dossier__regulatory_case", "owner")
            .order_by("due_date", "id")
        )

        blocked = base.filter(status=SectionStatus.BLOCKED)
        add(
            [_section_row(s, AttentionReason.REQUIRED_SECTION_BLOCKED, visibility) for s in blocked]
        )

        overdue = base.filter(due_date__lt=today).exclude(
            Q(readiness=Readiness.READY) | Q(status=SectionStatus.BLOCKED)
        )
        add(
            [_section_row(s, AttentionReason.OVERDUE_REQUIRED_SECTION, visibility) for s in overdue]
        )

        due_soon = base.filter(due_date__gte=today, due_date__lte=soon).exclude(
            Q(readiness=Readiness.READY) | Q(status=SectionStatus.BLOCKED)
        )
        add(
            [
                _section_row(s, AttentionReason.DUE_SOON_REQUIRED_SECTION, visibility)
                for s in due_soon
            ]
        )

        not_started = base.filter(status=SectionStatus.NOT_STARTED, due_date__isnull=True)
        add(
            [
                _section_row(s, AttentionReason.REQUIRED_SECTION_NOT_STARTED, visibility)
                for s in not_started
            ]
        )

        blockered = (
            _open_blockers(tenant)
            .select_related("section__dossier", "section__dossier__regulatory_case")
            .exclude(section__dossier__status__in=TERMINAL_DOSSIER_STATUSES)
            .order_by("-created_at", "-id")
        )
        add([_blocker_row(b, visibility) for b in blockered])

    if visibility.allows(MODULE_WORKFLOWS):
        add(_workflow_rows(tenant, visibility))

    if visibility.allows(MODULE_UPGRADES):
        add(_upgrade_plan_rows(tenant, visibility))

    if visibility.allows(MODULE_CASES):
        from regulatory_cases.models import CaseStatus

        empty_cases = (
            _cases(tenant)
            .filter(status=CaseStatus.OPEN)
            .annotate(n=Count("dossiers"))
            .filter(n=0)
            .order_by("-updated_at", "-id")
        )
        add(
            [
                {
                    "reason_code": AttentionReason.CASE_WITH_NO_DOSSIER,
                    "severity": REASON_SEVERITY[AttentionReason.CASE_WITH_NO_DOSSIER],
                    "resource_type": "regulatory_case",
                    "resource_public_id": c.public_id,
                    "resource_label": c.case_number,
                    "case_public_id": c.public_id,
                    "dossier_public_id": None,
                    "due_date": c.target_date,
                    "operational_state": c.status,
                    "_sort_updated_desc": -c.updated_at.timestamp(),
                }
                for c in empty_cases
            ]
        )

        on_hold = _cases(tenant).filter(status=CaseStatus.ON_HOLD).order_by("-updated_at", "-id")
        add(
            [
                {
                    "reason_code": AttentionReason.DOSSIER_ON_HOLD,
                    "severity": REASON_SEVERITY[AttentionReason.DOSSIER_ON_HOLD],
                    "resource_type": "regulatory_case",
                    "resource_public_id": c.public_id,
                    "resource_label": c.case_number,
                    "case_public_id": c.public_id,
                    "dossier_public_id": None,
                    "due_date": c.target_date,
                    "operational_state": c.status,
                    "_sort_updated_desc": -c.updated_at.timestamp(),
                }
                for c in on_hold
            ]
        )

    rows.sort(key=sort_key)
    return rows, truncated


def _section_row(section, reason, visibility) -> dict:
    return {
        "reason_code": reason,
        "severity": REASON_SEVERITY[reason],
        "resource_type": "dossier_section",
        "resource_public_id": section.public_id,
        "resource_label": section.section_code,
        "case_public_id": (
            section.dossier.regulatory_case.public_id if visibility.allows(MODULE_CASES) else None
        ),
        "dossier_public_id": section.dossier.public_id,
        "due_date": section.due_date,
        "operational_state": section.status,
        "_sort_updated_desc": -section.updated_at.timestamp(),
    }


def _blocker_row(blocker, visibility) -> dict:
    reason = AttentionReason.OPEN_BLOCKER
    return {
        "reason_code": reason,
        "severity": REASON_SEVERITY[reason],
        "resource_type": "dossier_section_blocker",
        "resource_public_id": blocker.public_id,
        # The blocker's own title is tenant-authored free text about a problem;
        # the section code identifies where to look without quoting it.
        "resource_label": blocker.section.section_code,
        "case_public_id": (
            blocker.section.dossier.regulatory_case.public_id
            if visibility.allows(MODULE_CASES)
            else None
        ),
        "dossier_public_id": blocker.section.dossier.public_id,
        "due_date": None,
        "operational_state": blocker.status,
        "_sort_updated_desc": -blocker.updated_at.timestamp(),
    }


def _workflow_rows(tenant, visibility) -> list[dict]:
    from workflows.models import WorkflowItem

    items = WorkflowItem.objects.filter(
        tenant=tenant,
        state__in=[
            WorkflowItem.State.REJECTED,
            WorkflowItem.State.SUBMITTED,
            WorkflowItem.State.IN_REVIEW,
        ],
    ).order_by("-updated_at", "-id")

    rows = []
    for item in items:
        reason = (
            AttentionReason.WORKFLOW_REJECTED
            if item.state == WorkflowItem.State.REJECTED
            else AttentionReason.WORKFLOW_WAITING_REVIEW
        )
        rows.append(
            {
                "reason_code": reason,
                "severity": REASON_SEVERITY[reason],
                "resource_type": "workflow_item",
                "resource_public_id": item.public_id,
                "resource_label": item.title,
                "case_public_id": None,
                "dossier_public_id": None,
                "due_date": item.due_at.date() if item.due_at else None,
                "operational_state": item.state,
                "_sort_updated_desc": -item.updated_at.timestamp(),
            }
        )
    return rows


def _upgrade_plan_rows(tenant, visibility) -> list[dict]:
    from dossier_upgrades.models import DossierUpgradePlan, ItemStatus, PlanStatus

    plans = list(
        DossierUpgradePlan.objects.filter(
            tenant=tenant, status__in=[PlanStatus.DRAFT, PlanStatus.READY]
        )
        .select_related("dossier", "dossier__regulatory_case")
        .annotate(
            has_blocked=Exists(
                DossierUpgradePlan.objects.filter(
                    pk=OuterRef("pk"), items__status=ItemStatus.BLOCKED
                )
            )
        )
        .order_by("-updated_at", "-id")
    )
    if not plans:
        return []
    fingerprints = _fingerprints_for({p.dossier_id for p in plans}, tenant)

    rows = []
    for plan in plans:
        stale = fingerprints.get(plan.dossier_id) != plan.dossier_fingerprint
        if plan.has_blocked:
            reason = AttentionReason.BLOCKED_UPGRADE_PLAN
        elif stale:
            reason = AttentionReason.STALE_UPGRADE_PLAN
        else:
            continue
        rows.append(
            {
                "reason_code": reason,
                "severity": REASON_SEVERITY[reason],
                "resource_type": "dossier_upgrade_plan",
                "resource_public_id": plan.public_id,
                # The dossier's title and identity belong to `submission_dossiers`
                # and are gated on ITS permission, not on the one that surfaced
                # this row. A caller holding `dossier_upgrades.view` without
                # `submission_dossiers.view` would otherwise learn that a dossier
                # exists and what it is called. The row is about the plan, so
                # when the dossier is hidden it says only that.
                "resource_label": (
                    plan.dossier.title if visibility.allows(MODULE_DOSSIERS) else "Upgrade plan"
                ),
                "case_public_id": (
                    plan.dossier.regulatory_case.public_id
                    if visibility.allows(MODULE_CASES)
                    else None
                ),
                "dossier_public_id": (
                    plan.dossier.public_id if visibility.allows(MODULE_DOSSIERS) else None
                ),
                "due_date": None,
                "operational_state": plan.status,
                "_sort_updated_desc": -plan.updated_at.timestamp(),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Owner workload
# ---------------------------------------------------------------------------
def owner_workload(*, tenant, visibility: Visibility) -> list[dict]:
    """Where work sits, by owner. Current tenant members only.

    Owners come from the sections themselves rather than from the tenant's user
    list, so a user with no work never appears -- and a user from another tenant
    cannot, because the sections are tenant-scoped before the grouping.
    """
    from submission_dossiers.models import Readiness, SectionStatus

    if not visibility.allows(MODULE_DOSSIERS):
        return []

    today = _today()
    grouped = (
        _required_sections(tenant)
        .values("owner_id", "owner__public_id", "owner__full_name")
        .annotate(
            required_total=Count("id"),
            outstanding=Count("id", filter=~Q(readiness=Readiness.READY)),
            blocked=Count("id", filter=Q(status=SectionStatus.BLOCKED)),
            overdue=Count("id", filter=Q(due_date__lt=today) & ~Q(readiness=Readiness.READY)),
        )
        .order_by("-outstanding", "owner__full_name", "owner_id")
    )

    rows = []
    for row in grouped:
        rows.append(
            {
                "owner": (
                    {
                        "public_id": row["owner__public_id"],
                        "full_name": row["owner__full_name"],
                    }
                    if row["owner_id"]
                    else None
                ),
                "unassigned": row["owner_id"] is None,
                "required_total": row["required_total"],
                "outstanding": row["outstanding"],
                "blocked": row["blocked"],
                "overdue": row["overdue"],
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Recent activity
# ---------------------------------------------------------------------------
#: Only these event types reach the feed, and only the fields below travel with
#: them. An allow-list rather than a deny-list: a new event type added by
#: another milestone appears here only when someone decides it is safe, instead
#: of appearing automatically and being reviewed never.
ACTIVITY_EVENT_MODULES: dict[str, str] = {
    "regulatory_case.created": MODULE_CASES,
    "regulatory_case.completed": MODULE_CASES,
    "regulatory_case.cancelled": MODULE_CASES,
    "dossier.created": MODULE_DOSSIERS,
    "dossier.section_created": MODULE_DOSSIERS,
    "dossier.section_updated": MODULE_DOSSIERS,
    "dossier.section_retired": MODULE_DOSSIERS,
    "dossier.blocker_created": MODULE_DOSSIERS,
    "dossier.blocker_resolved": MODULE_DOSSIERS,
    "workflow.transitioned": MODULE_WORKFLOWS,
    "workflow.evidence_linked": MODULE_WORKFLOWS,
    "dossier_blueprint.instantiated": MODULE_DOSSIERS,
    "dossier_upgrade.plan_created": MODULE_UPGRADES,
    "dossier_upgrade.plan_applied": MODULE_UPGRADES,
}

#: The only payload keys ever copied out of an AuditEvent, and the module each
#: one belongs to. Titles, notes, descriptions, reasons and blueprint names are
#: absent by construction: this feed says *what kind of thing happened to which
#: identifier*, never what it said.
#:
#: The mapping matters as much as the list. `dossier_public_id` can appear in an
#: upgrade event, and an upgrade permission is not a dossier permission -- so
#: each key is gated on the module that OWNS it rather than the one that emitted
#: the event. `None` means the key travels unconditionally.
ACTIVITY_PAYLOAD_KEYS: dict[str, str | None] = {
    "action": None,
    "dossier_public_id": MODULE_DOSSIERS,
    "case_public_id": MODULE_CASES,
}

ACTIVITY_LIMIT = 50


def recent_activity(*, tenant, visibility: Visibility, limit: int = ACTIVITY_LIMIT) -> list[dict]:
    from audit.models import AuditEvent

    allowed = [
        event for event, module in ACTIVITY_EVENT_MODULES.items() if visibility.allows(module)
    ]
    if not allowed:
        return []

    events = AuditEvent.objects.filter(tenant_id=tenant.pk, event_type__in=allowed).order_by(
        "-created_at", "-id"
    )[:limit]

    return [
        {
            "event_type": e.event_type,
            "resource_type": e.resource_type,
            "resource_public_id": e.resource_id,
            "occurred_at": e.created_at,
            "actor_email": e.actor_email or None,
            "detail": {
                k: v
                for k, v in (e.payload or {}).items()
                if k in ACTIVITY_PAYLOAD_KEYS
                and (
                    ACTIVITY_PAYLOAD_KEYS[k] is None or visibility.allows(ACTIVITY_PAYLOAD_KEYS[k])
                )
            },
        }
        for e in events
    ]


def _user_ref(user) -> dict:
    return {"public_id": str(user.public_id), "full_name": user.full_name}
