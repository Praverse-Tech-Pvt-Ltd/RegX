"""Upgrade plan generation, review and application.

**Generate is read-only. Accept writes nothing. Only apply writes.**

Every dossier write goes through `submission_dossiers.services`, so the
Milestone 9 sanctioned window and its `0004` triggers still hold. Nothing here
reaches past them.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .audit_events import UpgradeEvent, emit
from .comparison import (
    BLOCK_DUPLICATE_CODE,
    BLOCK_HAS_BLOCKERS,
    BLOCK_HAS_LINKS,
    BLOCK_HAS_PROGRESS,
    BLOCK_PARENT_UNAVAILABLE,
    compare,
)
from .fingerprint import fingerprint_for_dossier
from .models import (
    ACTIONABLE_CHANGE_TYPES,
    ChangeType,
    DossierUpgradeApplication,
    DossierUpgradePlan,
    DossierUpgradePlanItem,
    ItemStatus,
    PlanStatus,
    UpgradeSectionOrigin,
)

#: One message for every way a target can be unavailable, so absent /
#: cross-tenant / unauthorised are one indistinguishable outcome.
INVALID_TARGET_MESSAGE = "That item is not available."


class InvalidTarget(Exception):
    """Absent, in another tenant, or not visible to this caller."""


class UpgradeLocked(Exception):
    """The plan or dossier is in a state that refuses this operation."""


class PlanStale(Exception):
    """The dossier changed after the plan was generated."""


class NothingToApply(Exception):
    """No accepted, actionable item to write."""


def _assert_tenant(obj, tenant) -> None:
    if obj.tenant_id != tenant.pk:
        raise obj.__class__.DoesNotExist


# ---------------------------------------------------------------------------
# Provenance lookup
# ---------------------------------------------------------------------------
def current_version_for(dossier):
    """Which blueprint version this dossier is currently at.

    The latest applied upgrade if there is one, otherwise the version it was
    instantiated from. **Never taken from the caller** -- a client-supplied
    source version is a client-supplied claim about history.
    """
    from dossier_blueprints.models import BlueprintInstantiation

    latest = (
        DossierUpgradeApplication.objects.filter(dossier=dossier)
        .select_related("target_version", "blueprint")
        .order_by("-created_at", "-id")
        .first()
    )
    if latest is not None:
        return latest.blueprint, latest.target_version

    instantiation = (
        BlueprintInstantiation.objects.filter(dossier=dossier)
        .select_related("blueprint_version", "blueprint")
        .first()
    )
    if instantiation is None:
        return None, None
    return instantiation.blueprint, instantiation.blueprint_version


def _origin_map(dossier):
    """dossier section pk -> the blueprint section it currently corresponds to.

    Instantiation origins first, then upgrade origins layered on top, so a
    section added by a later upgrade maps to that upgrade's blueprint section
    rather than to nothing.
    """
    from dossier_blueprints.models import BlueprintSectionOrigin

    mapping = {}
    for row in BlueprintSectionOrigin.objects.filter(instantiation__dossier=dossier).values_list(
        "dossier_section_id", "blueprint_section_id"
    ):
        mapping[row[0]] = row[1]
    for row in UpgradeSectionOrigin.objects.filter(application__dossier=dossier).values_list(
        "dossier_section_id", "blueprint_section_id"
    ):
        mapping[row[0]] = row[1]
    return mapping


def _runtime_facts(sections):
    """Per-section facts that decide whether a retirement is safe.

    Batched into four aggregate queries rather than one per section: a 500
    section dossier would otherwise cost 2000 queries to compare.
    """
    from submission_dossiers.models import (
        DossierSectionBlocker,
        DossierSectionChecklist,
        DossierSectionDocument,
        DossierSectionWorkflow,
        SectionStatus,
    )

    ids = [s.pk for s in sections]
    children = dict(
        type(sections[0])
        .objects.filter(parent_id__in=ids, retired_at__isnull=True)
        .values("parent_id")
        .annotate(n=Count("id"))
        .values_list("parent_id", "n")
        if sections
        else []
    )
    blockers = dict(
        DossierSectionBlocker.objects.filter(section_id__in=ids, status="open")
        .values("section_id")
        .annotate(n=Count("id"))
        .values_list("section_id", "n")
    )
    links: dict = {}
    for model in (DossierSectionDocument, DossierSectionWorkflow, DossierSectionChecklist):
        for sid, n in (
            model.objects.filter(section_id__in=ids, unlinked_at__isnull=True)
            .values("section_id")
            .annotate(n=Count("id"))
            .values_list("section_id", "n")
        ):
            links[sid] = links.get(sid, 0) + n

    # "Recorded progress" means a human has said something about this section:
    # moved it off the default status, taken ownership, written notes, or set a
    # due date by hand. A blueprint has no standing to discard any of that.
    progressed = {
        s.pk: True
        for s in sections
        if s.status != SectionStatus.NOT_STARTED
        or s.owner_id is not None
        or (s.notes or "").strip()
        or s.due_date is not None
    }
    return {
        "children": children,
        "blockers": blockers,
        "links": links,
        "progressed": progressed,
    }


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
@transaction.atomic
def generate_plan(*, dossier, tenant, actor, target_version_public_id, notes=""):
    """Compare the dossier against a target version and persist the proposal.

    **Writes no dossier row.** The only rows created are the plan and its items.

    THREE GATES, checked independently, none implying another:

      1. `dossier_upgrades.generate`     -- checked by the view
      2. `submission_dossiers.view`      -- this reads a dossier's structure
      3. `dossier_blueprints.view`       -- this reads a blueprint version

    Gates 2 and 3 are checked **before the target version is resolved**, and
    every failure raises the same exception with the same message, so absent /
    cross-tenant / unauthorised are one indistinguishable outcome. That is the
    Milestone 8 existence-oracle lesson, applied here too.
    """
    from dossier_blueprints.models import BlueprintVersionStatus, DossierBlueprintVersion
    from dossier_blueprints.permissions import PERM_VIEW as BLUEPRINT_VIEW
    from dossier_blueprints.permissions import has_blueprint_permission
    from submission_dossiers.models import DossierSection
    from submission_dossiers.permissions import PERM_VIEW as DOSSIER_VIEW
    from submission_dossiers.permissions import has_dossier_permission

    _assert_tenant(dossier, tenant)

    if not has_dossier_permission(actor, tenant, DOSSIER_VIEW):
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    if not has_blueprint_permission(actor, tenant, BLUEPRINT_VIEW):
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    blueprint, source_version = current_version_for(dossier)
    if source_version is None:
        raise UpgradeLocked(
            "This dossier was not created from a blueprint, so there is nothing to upgrade."
        )

    target = DossierBlueprintVersion.objects.filter(
        public_id=target_version_public_id, tenant=tenant
    ).first()
    if target is None:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    if target.blueprint_id != blueprint.pk:
        # Cross-blueprint upgrade is meaningless: the two outlines describe
        # different things and no section correspondence exists.
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    if target.pk == source_version.pk:
        raise UpgradeLocked("The dossier is already at that version.")
    if target.status != BlueprintVersionStatus.ACTIVE:
        # Only a published version may seed a plan. A draft is still being
        # edited, and a retired one was withdrawn on purpose.
        raise UpgradeLocked(
            f"Only an active blueprint version can be planned against; that one is {target.status}."
        )

    dossier_sections = list(
        DossierSection.objects.filter(dossier=dossier, retired_at__isnull=True)
        .select_related("parent", "owner")
        .order_by("sequence", "id")
    )
    changes = _compute_changes(dossier, source_version, target, dossier_sections)
    plan = _persist_plan(
        dossier=dossier,
        tenant=tenant,
        actor=actor,
        blueprint=blueprint,
        source_version=source_version,
        target=target,
        changes=changes,
        notes=notes,
    )
    emit(
        event_type=UpgradeEvent.PLAN_CREATED,
        resource_id=plan.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "plan_created",
            "plan_public_id": str(plan.public_id),
            "dossier_public_id": str(dossier.public_id),
            "blueprint_public_id": str(blueprint.public_id),
            "source_version_public_id": str(source_version.public_id),
            "target_version_public_id": str(target.public_id),
            "source_version_number": source_version.version_number,
            "target_version_number": target.version_number,
            "total_items": plan.total_items,
            "actionable_items": plan.actionable_items,
            "conflict_items": plan.conflict_items,
            "notes_supplied": bool(notes),
            "notes_length": len(notes or ""),
        },
    )
    return plan


def _compute_changes(dossier, source_version, target, dossier_sections):
    from dossier_blueprints.models import DossierBlueprintSection

    source_sections = list(
        DossierBlueprintSection.objects.filter(
            blueprint_version=source_version, retired_at__isnull=True
        ).select_related("parent")
    )
    target_sections = list(
        DossierBlueprintSection.objects.filter(
            blueprint_version=target, retired_at__isnull=True
        ).select_related("parent")
    )
    return compare(
        dossier_sections=dossier_sections,
        source_sections=source_sections,
        target_sections=target_sections,
        origins=_origin_map(dossier),
        runtime=_runtime_facts(dossier_sections),
    )


def _persist_plan(*, dossier, tenant, actor, blueprint, source_version, target, changes, notes):
    from django.db import IntegrityError

    try:
        plan = DossierUpgradePlan.objects.create(
            tenant=tenant,
            dossier=dossier,
            blueprint=blueprint,
            source_version=source_version,
            target_version=target,
            created_by=actor,
            notes=notes,
            dossier_fingerprint=fingerprint_for_dossier(dossier),
        )
    except IntegrityError as exc:
        # Narrow on purpose. Catching every IntegrityError and calling it
        # "already exists" would turn any future NOT NULL or FK bug into a
        # confident, wrong answer -- which is exactly what happened while
        # building this, and cost a debugging round.
        if "unique_open_upgrade_plan_per_target" not in str(exc):
            raise
        # Two live proposals for the same move are a review hazard: a reviewer
        # accepting items on one cannot see the other.
        raise UpgradeLocked(
            "An open upgrade plan for that version already exists. Cancel or apply it first."
        ) from exc

    _write_items(plan, tenant, changes)
    _refresh_counts(plan)
    return plan


def _write_items(plan, tenant, changes):
    for index, change in enumerate(changes):
        DossierUpgradePlanItem.objects.create(
            tenant=tenant,
            plan=plan,
            change_type=change.change_type,
            status=change.status,
            dossier_section=change.dossier_section,
            source_section=change.source_section,
            target_section=change.target_section,
            section_code=change.section_code,
            field_name=change.field_name,
            before_value=change.before_value,
            after_value=change.after_value,
            blocking_reason=change.blocking_reason,
            requires_manual_review=change.requires_manual_review,
            sequence=index * 10,
        )


def _refresh_counts(plan):
    items = list(plan.items.all())
    DossierUpgradePlan.governed.filter(pk=plan.pk).update(
        total_items=len(items),
        actionable_items=sum(1 for i in items if i.change_type in ACTIONABLE_CHANGE_TYPES),
        conflict_items=sum(1 for i in items if i.change_type == ChangeType.CONFLICT),
        updated_at=timezone.now(),
    )
    plan.refresh_from_db()


@transaction.atomic
def regenerate_plan(*, plan, tenant, actor):
    """Recompute an open plan against the current dossier.

    Every item is replaced, so review decisions are deliberately **not**
    carried over: an accept was a judgement about a change computed from a
    dossier that has since moved, and silently reapplying it would launder a
    stale decision into a fresh-looking plan.
    """
    _assert_tenant(plan, tenant)
    locked = DossierUpgradePlan.objects.select_for_update().get(pk=plan.pk)
    _assert_tenant(locked, tenant)
    if not locked.is_open:
        raise UpgradeLocked(f"This plan is {locked.status} and cannot be regenerated.")

    from submission_dossiers.models import DossierSection

    dossier_sections = list(
        DossierSection.objects.filter(dossier=locked.dossier, retired_at__isnull=True)
        .select_related("parent", "owner")
        .order_by("sequence", "id")
    )
    changes = _compute_changes(
        locked.dossier, locked.source_version, locked.target_version, dossier_sections
    )

    # A regenerate replaces the proposal, so the old items go and the plan row --
    # with the public_id anything external holds -- survives.
    #
    # This is the ONE place items are deleted, and it goes through the governed
    # manager so the `0002` trigger still decides: item deletion is permitted
    # only while the parent plan is open. Once a plan is applied or cancelled its
    # items are history and the database refuses to remove them.
    DossierUpgradePlanItem.governed.filter(plan=locked).delete()

    _write_items(locked, tenant, changes)
    DossierUpgradePlan.governed.filter(pk=locked.pk).update(
        dossier_fingerprint=fingerprint_for_dossier(locked.dossier),
        status=PlanStatus.DRAFT,
        reviewed_by=None,
        reviewed_at=None,
        updated_at=timezone.now(),
    )
    locked.refresh_from_db()
    _refresh_counts(locked)

    emit(
        event_type=UpgradeEvent.PLAN_REGENERATED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "plan_regenerated",
            "plan_public_id": str(locked.public_id),
            "dossier_public_id": str(locked.dossier.public_id),
            "total_items": locked.total_items,
            "actionable_items": locked.actionable_items,
            "conflict_items": locked.conflict_items,
        },
    )
    return locked


def is_stale(plan) -> bool:
    """Has the dossier moved since the plan was computed?"""
    return fingerprint_for_dossier(plan.dossier) != plan.dossier_fingerprint


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
@transaction.atomic
def set_item_status(*, item, tenant, actor, accept: bool):
    """Accept or reject one proposed change. Writes nothing to the dossier."""
    _assert_tenant(item, tenant)
    plan = DossierUpgradePlan.objects.select_for_update().get(pk=item.plan_id)
    _assert_tenant(plan, tenant)
    if not plan.is_open:
        raise UpgradeLocked(f"This plan is {plan.status} and its items are final.")

    locked = DossierUpgradePlanItem.objects.select_for_update().get(pk=item.pk)
    if locked.status == ItemStatus.BLOCKED:
        raise UpgradeLocked(
            "This item is blocked and cannot be accepted; resolve the underlying work first."
        )
    if locked.change_type not in ACTIONABLE_CHANGE_TYPES:
        raise UpgradeLocked("This item proposes no change.")

    now = timezone.now()
    DossierUpgradePlanItem.governed.filter(pk=locked.pk).update(
        status=ItemStatus.ACCEPTED if accept else ItemStatus.REJECTED,
        reviewed_by=actor,
        reviewed_at=now,
        updated_at=now,
    )
    locked.refresh_from_db()

    emit(
        event_type=UpgradeEvent.ITEM_ACCEPTED if accept else UpgradeEvent.ITEM_REJECTED,
        resource_id=plan.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "item_accepted" if accept else "item_rejected",
            "plan_public_id": str(plan.public_id),
            "item_public_id": str(locked.public_id),
            "change_type": locked.change_type,
            "field_name": locked.field_name,
            "section_code": locked.section_code,
            "to_status": locked.status,
        },
    )
    return locked


@transaction.atomic
def mark_ready(*, plan, tenant, actor):
    """Declare the plan reviewed.

    READY means reviewed internally and applicable. It is **not** a regulatory
    approval, a QA approval or an agency decision, and there is no APPROVED
    state for it to be confused with.
    """
    _assert_tenant(plan, tenant)
    locked = DossierUpgradePlan.objects.select_for_update().get(pk=plan.pk)
    _assert_tenant(locked, tenant)
    if locked.status != PlanStatus.DRAFT:
        raise UpgradeLocked(f"This plan is {locked.status}.")
    if locked.items.filter(
        status=ItemStatus.PROPOSED, change_type__in=ACTIONABLE_CHANGE_TYPES
    ).exists():
        raise UpgradeLocked("Every actionable item must be accepted or rejected first.")

    now = timezone.now()
    DossierUpgradePlan.governed.filter(pk=locked.pk).update(
        status=PlanStatus.READY, reviewed_by=actor, reviewed_at=now, updated_at=now
    )
    locked.refresh_from_db()
    emit(
        event_type=UpgradeEvent.PLAN_MARKED_READY,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "plan_marked_ready",
            "plan_public_id": str(locked.public_id),
            "from_status": PlanStatus.DRAFT,
            "to_status": PlanStatus.READY,
        },
    )
    return locked


@transaction.atomic
def cancel_plan(*, plan, tenant, actor):
    _assert_tenant(plan, tenant)
    locked = DossierUpgradePlan.objects.select_for_update().get(pk=plan.pk)
    _assert_tenant(locked, tenant)
    if locked.is_terminal:
        raise UpgradeLocked(f"This plan is already {locked.status}.")

    now = timezone.now()
    from_status = locked.status
    DossierUpgradePlan.governed.filter(pk=locked.pk).update(
        status=PlanStatus.CANCELLED, cancelled_by=actor, cancelled_at=now, updated_at=now
    )
    locked.refresh_from_db()
    emit(
        event_type=UpgradeEvent.PLAN_CANCELLED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "plan_cancelled",
            "plan_public_id": str(locked.public_id),
            "from_status": from_status,
            "to_status": PlanStatus.CANCELLED,
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
@transaction.atomic
def apply_plan(*, plan, tenant, actor):
    """Write the accepted items, all or nothing.

    FOUR GATES, checked independently:

      1. `dossier_upgrades.apply`                  -- checked by the view
      2. `submission_dossiers.manage_sections`     -- this writes sections
      3. the dossier must not be terminal
      4. the plan must not be stale

    Gate 2 is checked before anything is resolved, with the same
    indistinguishable message as every other target failure.

    Every dossier write goes through `submission_dossiers.services`, so the M9
    sanctioned window and the `0004` triggers apply exactly as they do to a
    hand-edited dossier. Nothing here writes a section row directly.
    """
    from submission_dossiers import services as dossier_services
    from submission_dossiers.permissions import PERM_MANAGE_SECTIONS, has_dossier_permission

    _assert_tenant(plan, tenant)

    if not has_dossier_permission(actor, tenant, PERM_MANAGE_SECTIONS):
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    locked = DossierUpgradePlan.objects.select_for_update().get(pk=plan.pk)
    _assert_tenant(locked, tenant)
    if locked.status != PlanStatus.READY:
        raise UpgradeLocked(
            f"Only a plan marked ready can be applied; this one is {locked.status}."
        )

    dossier = locked.dossier
    if dossier.is_terminal:
        # A completed or cancelled dossier refuses structural change. M9 would
        # refuse each write anyway; refusing here gives a clean answer instead
        # of a half-attempted transaction.
        raise UpgradeLocked(f"This dossier is {dossier.status} and no longer accepts changes.")

    if locked.items.filter(status=ItemStatus.BLOCKED).exists():
        raise UpgradeLocked("This plan has blocked items. Resolve or regenerate before applying.")

    # Staleness, checked against the live dossier. Fails closed: a plan that
    # cannot prove the dossier is unchanged is not applied.
    if is_stale(locked):
        raise PlanStale("The dossier changed after this plan was generated. Regenerate the plan.")

    accepted = [
        item
        for item in locked.items.select_related(
            "dossier_section", "target_section", "source_section"
        ).order_by("sequence", "id")
        if item.status == ItemStatus.ACCEPTED and item.change_type in ACTIONABLE_CHANGE_TYPES
    ]
    if not accepted:
        raise NothingToApply("No accepted changes to apply.")

    counts = _execute(accepted=accepted, dossier=dossier, tenant=tenant, actor=actor, plan=locked)

    now = timezone.now()
    DossierUpgradePlanItem.governed.filter(pk__in=[i.pk for i in accepted]).update(
        status=ItemStatus.APPLIED, updated_at=now
    )
    DossierUpgradePlan.governed.filter(pk=locked.pk).update(
        status=PlanStatus.APPLIED, applied_by=actor, applied_at=now, updated_at=now
    )
    locked.refresh_from_db()

    application = DossierUpgradeApplication.objects.create(
        tenant=tenant,
        dossier=dossier,
        plan=locked,
        blueprint=locked.blueprint,
        source_version=locked.source_version,
        target_version=locked.target_version,
        source_version_number=locked.source_version.version_number,
        target_version_number=locked.target_version.version_number,
        sections_added=counts["added"],
        sections_retired=counts["retired"],
        sections_updated=counts["updated"],
        applied_by=actor,
    )
    for section, blueprint_section in counts["origins"]:
        UpgradeSectionOrigin.objects.create(
            tenant=tenant,
            application=application,
            dossier_section=section,
            blueprint_section=blueprint_section,
        )

    # Readiness is derived, never set: the M9 engine recomputes the whole tree.
    dossier_services.recalculate_dossier(dossier)

    emit(
        event_type=UpgradeEvent.PLAN_APPLIED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "plan_applied",
            "plan_public_id": str(locked.public_id),
            "application_public_id": str(application.public_id),
            "dossier_public_id": str(dossier.public_id),
            "source_version_public_id": str(locked.source_version.public_id),
            "target_version_public_id": str(locked.target_version.public_id),
            "source_version_number": application.source_version_number,
            "target_version_number": application.target_version_number,
            "sections_added": counts["added"],
            "sections_retired": counts["retired"],
            "sections_updated": counts["updated"],
            "fingerprint_matched": True,
        },
    )
    return application


def _execute(*, accepted, dossier, tenant, actor, plan):
    """Write the accepted items in a safe order.

    Additions before updates so a move has somewhere to land; retirements last
    and deepest-first, because M9 refuses to retire a section with active
    children. Ordering is not cosmetic -- each of these would fail outright in
    the wrong sequence.
    """
    from submission_dossiers import services as dossier_services
    from submission_dossiers.models import DossierSection

    counts = {"added": 0, "retired": 0, "updated": 0, "origins": []}
    by_code = {
        s.section_code: s
        for s in DossierSection.objects.filter(dossier=dossier, retired_at__isnull=True)
    }

    additions = [i for i in accepted if i.change_type == ChangeType.ADD_SECTION]
    updates = [
        i
        for i in accepted
        if i.change_type
        in (
            ChangeType.UPDATE_TITLE,
            ChangeType.UPDATE_DESCRIPTION,
            ChangeType.UPDATE_REQUIRED,
            ChangeType.UPDATE_DUE_OFFSET,
            ChangeType.MOVE_SECTION,
        )
    ]
    reorders = [i for i in accepted if i.change_type == ChangeType.REORDER_SECTION]
    retirements = [i for i in accepted if i.change_type == ChangeType.RETIRE_SECTION]

    # A precondition, checked before anything is written. Runtime facts are
    # re-checked rather than trusted from generation time: a retirement is only
    # ever proposed for a section carrying no work, but runtime changes
    # deliberately do not stale a plan (see is_stale), so a blocker opened or a
    # document linked between the review and the apply would otherwise ride
    # straight through. M9's retire_section refuses active children and nothing
    # else -- right for a human acting deliberately with the section in front of
    # them, wrong for a decision made against facts that have since moved.
    #
    # Refuse the whole apply rather than skip the item: the reviewer approved a
    # plan, not a subset of one. Children are left to M9's floor, because
    # checking them here would misread a parent whose only child this same
    # apply retires.
    _assert_retirements_are_still_safe(retirements)

    # 1. Additions, shallowest first -- `sequence` was set by the comparison in
    #    depth order, so a parent is always created before its children.
    for item in sorted(additions, key=lambda i: i.sequence):
        target = item.target_section
        parent_code = target.parent.section_code if target.parent_id else None
        parent = by_code.get(parent_code) if parent_code else None
        if parent_code and parent is None:
            raise UpgradeLocked(
                f"Cannot add {target.section_code}: its parent is not in this dossier."
            )
        if target.section_code in by_code:
            raise UpgradeLocked(
                f"Cannot add {target.section_code}: that code already exists in this dossier."
            )

        created = dossier_services.create_section(
            dossier=dossier,
            tenant=tenant,
            actor=actor,
            parent=parent,
            section_code=target.section_code,
            title=target.title,
            description=target.description,
            sequence=_safe_sequence(dossier, parent, target.sequence),
            required=target.required,
            due_date=_derived_due_date(dossier, target),
        )
        by_code[created.section_code] = created
        counts["added"] += 1
        counts["origins"].append((created, target))

    # 2. Metadata and moves.
    for item in updates:
        section = item.dossier_section
        if section is None:
            continue
        section.refresh_from_db()
        fields = {}
        kwargs = {}
        target = item.target_section

        if item.change_type == ChangeType.UPDATE_TITLE:
            fields["title"] = target.title
        elif item.change_type == ChangeType.UPDATE_DESCRIPTION:
            fields["description"] = target.description
        elif item.change_type == ChangeType.UPDATE_REQUIRED:
            fields["required"] = target.required
        elif item.change_type == ChangeType.UPDATE_DUE_OFFSET:
            # Re-checked here rather than trusted from generation time: a due
            # date set by hand between generate and apply must survive.
            if section.due_date is not None:
                continue
            derived = _derived_due_date(dossier, target)
            if derived is None:
                continue
            fields["due_date"] = derived
        elif item.change_type == ChangeType.MOVE_SECTION:
            parent_code = target.parent.section_code if target.parent_id else None
            new_parent = by_code.get(parent_code) if parent_code else None
            if parent_code and new_parent is None:
                raise UpgradeLocked(
                    f"Cannot move {target.section_code}: {BLOCK_PARENT_UNAVAILABLE}."
                )
            kwargs["parent"] = new_parent

        if fields or kwargs:
            dossier_services.update_section(
                section=section, tenant=tenant, actor=actor, **kwargs, **fields
            )
            counts["updated"] += 1

    # 3. Reorders, through the M9 reorder service -- `update_section` may not
    #    move `sequence` at all, by the 0004 window's design.
    for item in reorders:
        section = item.dossier_section
        if section is None:
            continue
        section.refresh_from_db()
        siblings = list(
            DossierSection.objects.filter(
                dossier=dossier, parent_id=section.parent_id, retired_at__isnull=True
            ).order_by("sequence", "id")
        )
        desired = min(max(int(item.after_value or 0) // 10, 0), max(len(siblings) - 1, 0))
        dossier_services.reorder_section(
            section=section, tenant=tenant, actor=actor, sequence=desired
        )
        counts["updated"] += 1

    # 4. Retirements, deepest first: M9 refuses a section with active children.
    for item in sorted(retirements, key=lambda i: -_depth_of(i.dossier_section)):
        section = item.dossier_section
        if section is None:
            continue
        section.refresh_from_db()
        if section.retired_at is not None:
            continue
        dossier_services.retire_section(section=section, tenant=tenant, actor=actor)
        counts["retired"] += 1

    return counts


def _assert_retirements_are_still_safe(retirements):
    """Refuse if work appeared on a section after its retirement was accepted.

    One batched pass over the live rows, so the cost does not grow with the
    number of retirements in the plan.
    """
    from submission_dossiers.models import DossierSection

    ids = [i.dossier_section_id for i in retirements if i.dossier_section_id]
    if not ids:
        return
    live = list(DossierSection.objects.filter(pk__in=ids, retired_at__isnull=True))
    if not live:
        return

    facts = _runtime_facts(live)
    for section in live:
        if facts["blockers"].get(section.pk):
            reason = BLOCK_HAS_BLOCKERS
        elif facts["links"].get(section.pk):
            reason = BLOCK_HAS_LINKS
        elif facts["progressed"].get(section.pk):
            reason = BLOCK_HAS_PROGRESS
        else:
            continue
        raise UpgradeLocked(
            f"Cannot retire {section.section_code}: {reason}. Work was recorded "
            "on it after this plan was reviewed; regenerate the plan."
        )


def _safe_sequence(dossier, parent, preferred):
    """The blueprint's sequence where it is free, otherwise the next free slot.

    Copying the blueprint's sequence verbatim collides whenever the dossier
    still holds a section there -- which is the normal case, because the section
    the blueprint dropped to free that slot may not be retired in this dossier
    at all: the reviewer may have rejected that item, or it may be blocked by
    live work.

    A collision would raise `unique_root_sequence_per_dossier` and abort the
    whole upgrade, so ordering degrades to "appended" rather than the upgrade
    failing. Preserving the blueprint's exact ordering matters less than not
    destroying a dossier over it, and a REORDER item can still move the section
    afterwards if the ordering is what the reviewer cares about.
    """
    from submission_dossiers.models import DossierSection

    taken = set(
        DossierSection.objects.filter(
            dossier=dossier, parent=parent, retired_at__isnull=True
        ).values_list("sequence", flat=True)
    )
    if preferred not in taken:
        return preferred
    return (max(taken) + 10) if taken else 0


def _depth_of(section, limit=32) -> int:
    depth, walker, guard = 0, section, 0
    while walker is not None and walker.parent_id and guard < limit:
        walker = walker.parent
        depth += 1
        guard += 1
    return depth


def _derived_due_date(dossier, target_section):
    """Tenant configuration, not a regulatory timeline -- the same rule M10 uses
    at instantiation: the section is due `offset` days before the target date."""
    if dossier.target_date is None or target_section.default_due_offset_days is None:
        return None
    return dossier.target_date - timedelta(days=target_section.default_due_offset_days)


def available_targets(*, dossier, tenant):
    """Active versions of the dossier's own blueprint that it is not already at."""
    from dossier_blueprints.models import BlueprintVersionStatus, DossierBlueprintVersion

    blueprint, current = current_version_for(dossier)
    if blueprint is None:
        return DossierBlueprintVersion.objects.none()
    return DossierBlueprintVersion.objects.filter(
        blueprint=blueprint, tenant=tenant, status=BlueprintVersionStatus.ACTIVE
    ).exclude(pk=current.pk if current else None)


__all__ = [
    "BLOCK_DUPLICATE_CODE",
    "INVALID_TARGET_MESSAGE",
    "InvalidTarget",
    "NothingToApply",
    "PlanStale",
    "UpgradeLocked",
    "apply_plan",
    "available_targets",
    "cancel_plan",
    "current_version_for",
    "generate_plan",
    "is_stale",
    "mark_ready",
    "regenerate_plan",
    "set_item_status",
]
