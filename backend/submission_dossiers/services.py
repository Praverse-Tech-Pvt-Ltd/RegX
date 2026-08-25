"""Dossier service layer: every governed mutation goes through here."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import readiness as readiness_engine
from .audit_events import DossierEvent, emit
from .governance import (
    OP_RECALCULATE,
    OP_REORDER,
    OP_RETIRE,
    OP_UPDATE,
    section_write,
)
from .models import (
    MAX_SECTION_DEPTH,
    BlockerStatus,
    DossierSection,
    DossierSectionBlocker,
    DossierSectionChecklist,
    DossierSectionDocument,
    DossierSectionWorkflow,
    DossierStatus,
    Readiness,
    SectionStatus,
    SubmissionDossier,
)


class InvalidTarget(Exception):
    """Target absent, cross-tenant, unauthorized or ineligible.

    ONE exception for all four. Separate messages would let a caller probe for
    the existence of a document, workflow or checklist they cannot see -- the
    existence oracle that independent review found in Milestone 8.
    """


class DossierLocked(Exception):
    """The dossier is completed or cancelled and refuses structural change."""


class DuplicateLink(Exception):
    """That target is already actively linked to this section."""


class InvalidHierarchy(Exception):
    """The requested parent would produce an invalid or cyclic tree."""


class NotReady(Exception):
    """Completion refused: required sections are not internally ready."""


INVALID_TARGET_MESSAGE = "That item is not available to link to this section."

#: Parking range for the two-phase sibling renumber in `reorder_section`.
#: Far above any realistic ordering so it cannot collide with a live value.
_SEQUENCE_PARK_OFFSET = 1_000_000


def _require_mutable(dossier: SubmissionDossier) -> None:
    if dossier.is_terminal:
        raise DossierLocked(f"This dossier is {dossier.status} and no longer accepts changes.")


def _assert_tenant(obj, tenant) -> None:
    if obj.tenant_id != tenant.pk:
        raise obj.__class__.DoesNotExist


# ---------------------------------------------------------------------------
# Dossier lifecycle
# ---------------------------------------------------------------------------
@transaction.atomic
def create_dossier(*, case, tenant, actor, **fields) -> SubmissionDossier:
    _assert_tenant(case, tenant)
    dossier = SubmissionDossier.objects.create(
        tenant=tenant, regulatory_case=case, created_by=actor, **fields
    )
    emit(
        event_type=DossierEvent.CREATED,
        resource_id=dossier.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "created",
            "dossier_public_id": str(dossier.public_id),
            "to_status": dossier.status,
        },
    )
    return dossier


@transaction.atomic
def update_dossier(*, dossier, tenant, actor, **fields) -> SubmissionDossier:
    _assert_tenant(dossier, tenant)
    locked = SubmissionDossier.objects.select_for_update().get(pk=dossier.pk)
    _assert_tenant(locked, tenant)
    _require_mutable(locked)

    changed = [n for n, v in fields.items() if getattr(locked, n) != v]
    for name, value in fields.items():
        setattr(locked, name, value)

    if changed:
        locked.save(update_fields=[*changed, "updated_at"])
        emit(
            event_type=DossierEvent.UPDATED,
            resource_id=locked.public_id,
            actor=actor,
            tenant_id=tenant.pk,
            payload={
                "action": "updated",
                "dossier_public_id": str(locked.public_id),
                # Names only: values carry product and submission detail.
                "fields_changed": sorted(changed),
            },
        )
    return locked


def complete_dossier(*, dossier, tenant, actor, reason: str = "") -> SubmissionDossier:
    """Finish a dossier.

    **Gated on readiness, not merely on permission.** Marking a dossier complete
    while required sections are not ready would make the status meaningless.
    The refusal carries safe reason codes only -- never the identity of a
    resource the caller may not be entitled to see.

    Completing a dossier records that internal work stopped. It is NOT an agency
    submission and NOT an approval.
    """
    _assert_tenant(dossier, tenant)
    with transaction.atomic():
        locked = SubmissionDossier.objects.select_for_update().get(pk=dossier.pk)
        _assert_tenant(locked, tenant)
        if locked.is_terminal:
            raise DossierLocked(f"This dossier is already {locked.status}.")

        recalculate_dossier(locked)
        pairs = list(
            DossierSection.objects.filter(dossier=locked, retired_at__isnull=True).values_list(
                "required", "readiness"
            )
        )
        overall, overall_reason = readiness_engine.aggregate(pairs)
        if overall != Readiness.READY:
            raise NotReady(overall_reason)

        return _set_dossier_status(
            locked, tenant, actor, DossierStatus.COMPLETED, DossierEvent.COMPLETED, reason
        )


def cancel_dossier(*, dossier, tenant, actor, reason: str = "") -> SubmissionDossier:
    """Abandon a dossier. Unlike completion this has no readiness gate: work can
    be stopped at any point."""
    _assert_tenant(dossier, tenant)
    with transaction.atomic():
        locked = SubmissionDossier.objects.select_for_update().get(pk=dossier.pk)
        _assert_tenant(locked, tenant)
        if locked.is_terminal:
            raise DossierLocked(f"This dossier is already {locked.status}.")
        return _set_dossier_status(
            locked, tenant, actor, DossierStatus.CANCELLED, DossierEvent.CANCELLED, reason
        )


def _set_dossier_status(locked, tenant, actor, to_status, event, reason):
    from_status = locked.status
    locked.status = to_status
    locked.save(update_fields=["status", "updated_at"])
    emit(
        event_type=event,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": to_status,
            "dossier_public_id": str(locked.public_id),
            "from_status": from_status,
            "to_status": to_status,
            # Text is not recorded: it is free-form and describes the work.
            "reason_supplied": bool(reason),
            "reason_length": len(reason or ""),
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------
def validate_parent(*, dossier, tenant, parent, child=None) -> None:
    """Refuse every way a parent assignment can corrupt the tree.

    `TemplateSection`, the existing tree in this repository, has no equivalent
    guard because an importer builds it top-down and cycles cannot arise. These
    sections are edited through an API, so each of these is reachable.
    """
    if parent is None:
        return

    # Re-read the parent rather than trusting the object handed in. A caller
    # holding a section fetched before it was retired would otherwise pass a
    # stale `retired_at = None` straight through this check -- the validation
    # has to reflect the database, not whatever the caller happens to be
    # holding. Same single message for absent, cross-tenant, cross-dossier and
    # retired, so none of the four can be told apart.
    parent = DossierSection.objects.filter(pk=parent.pk).first()
    if parent is None:
        raise InvalidHierarchy("Parent section is not available.")
    if parent.tenant_id != tenant.pk:
        raise InvalidHierarchy("Parent section is not available.")
    if parent.dossier_id != dossier.pk:
        raise InvalidHierarchy("Parent section is not available.")
    if parent.retired_at is not None:
        raise InvalidHierarchy("Parent section is not available.")

    if child is not None and parent.pk == child.pk:
        raise InvalidHierarchy("A section cannot be its own parent.")

    # Walk to the root. Bounded by MAX_SECTION_DEPTH so a pre-existing cycle
    # (which the guards above should prevent, but which a direct database edit
    # could still create) cannot spin here forever.
    depth = 1
    node = parent
    seen = set()
    while node is not None:
        if node.pk in seen:
            raise InvalidHierarchy("Section hierarchy contains a cycle.")
        seen.add(node.pk)
        if child is not None and node.pk == child.pk:
            # The proposed parent is a descendant of the section being moved.
            raise InvalidHierarchy("A section cannot be moved beneath its own descendant.")
        depth += 1
        if depth > MAX_SECTION_DEPTH:
            raise InvalidHierarchy(f"Section nesting is limited to {MAX_SECTION_DEPTH} levels.")
        node = node.parent

    if child is not None:
        # Moving a subtree also moves its own depth, so the deepest descendant
        # must still fit. Without this a shallow move could push a deep subtree
        # past the ceiling.
        if depth + _subtree_depth(child) - 1 > MAX_SECTION_DEPTH:
            raise InvalidHierarchy(f"Section nesting is limited to {MAX_SECTION_DEPTH} levels.")


def _subtree_depth(section) -> int:
    """Depth of the subtree rooted at `section`, counting itself as 1."""
    children = list(section.children.filter(retired_at__isnull=True))
    if not children:
        return 1
    return 1 + max(_subtree_depth(c) for c in children)


@transaction.atomic
def create_section(*, dossier, tenant, actor, parent=None, **fields) -> DossierSection:
    _assert_tenant(dossier, tenant)
    locked = SubmissionDossier.objects.select_for_update().get(pk=dossier.pk)
    _require_mutable(locked)
    validate_parent(dossier=locked, tenant=tenant, parent=parent)

    if fields.get("sequence") is None:
        fields["sequence"] = _next_sequence(locked, parent)

    try:
        section = DossierSection.objects.create(
            tenant=tenant, dossier=locked, parent=parent, created_by=actor, **fields
        )
    except IntegrityError as exc:
        raise DuplicateLink(
            "A section with that code or sequence already exists in this dossier."
        ) from exc

    recalculate_dossier(locked)
    section.refresh_from_db()

    emit(
        event_type=DossierEvent.SECTION_CREATED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "section_created",
            "dossier_public_id": str(locked.public_id),
            "section_public_id": str(section.public_id),
            "parent_public_id": str(parent.public_id) if parent else "",
            "section_code": section.section_code,
            "to_status": section.status,
        },
    )
    return section


def _next_sequence(dossier, parent) -> int:
    from django.db.models import Max

    existing = DossierSection.objects.filter(
        dossier=dossier, parent=parent, retired_at__isnull=True
    ).aggregate(Max("sequence"))["sequence__max"]
    return 0 if existing is None else existing + 10


@transaction.atomic
def update_section(*, section, tenant, actor, parent=..., **fields) -> DossierSection:
    _assert_tenant(section, tenant)
    dossier = SubmissionDossier.objects.select_for_update().get(pk=section.dossier_id)
    _require_mutable(dossier)

    locked = DossierSection.objects.select_for_update().get(pk=section.pk)
    _assert_tenant(locked, tenant)
    if locked.is_retired:
        raise DossierLocked("This section is retired and no longer accepts changes.")

    changed = []
    if parent is not ...:
        validate_parent(dossier=dossier, tenant=tenant, parent=parent, child=locked)
        if locked.parent_id != (parent.pk if parent else None):
            locked.parent = parent
            changed.append("parent")

    from_status = locked.status
    for name, value in fields.items():
        if getattr(locked, name) != value:
            setattr(locked, name, value)
            changed.append(name)

    if changed:
        try:
            # The window is opened around this one statement, not the whole
            # function: the narrower it is, the less it can be borrowed by
            # anything that runs alongside it.
            with section_write(OP_UPDATE):
                locked.save(update_fields=[*changed, "updated_at"])
        except IntegrityError as exc:
            raise DuplicateLink(
                "A section with that code or sequence already exists in this dossier."
            ) from exc

        recalculate_dossier(dossier)
        locked.refresh_from_db()

        event = DossierEvent.SECTION_UPDATED
        if "status" in changed and locked.status == SectionStatus.COMPLETE:
            event = DossierEvent.SECTION_COMPLETED
        elif "status" in changed and locked.status == SectionStatus.NOT_APPLICABLE:
            event = DossierEvent.SECTION_NOT_APPLICABLE

        emit(
            event_type=event,
            resource_id=dossier.public_id,
            actor=actor,
            tenant_id=tenant.pk,
            payload={
                "action": "section_updated",
                "dossier_public_id": str(dossier.public_id),
                "section_public_id": str(locked.public_id),
                "fields_changed": sorted(changed),
                "from_status": from_status,
                "to_status": locked.status,
                "to_readiness": locked.readiness,
                "readiness_reason": locked.readiness_reason,
            },
        )
    return locked


@transaction.atomic
def reorder_section(*, section, tenant, actor, sequence: int) -> DossierSection:
    """Move a section within its sibling group.

    The whole sibling set is locked, not just the moving row: two concurrent
    reorders that each read-then-write would otherwise interleave and leave two
    siblings sharing a sequence, which the unique constraint would reject at a
    confusing moment or, worse, render in database-timing order.
    """
    _assert_tenant(section, tenant)
    dossier = SubmissionDossier.objects.select_for_update().get(pk=section.dossier_id)
    _require_mutable(dossier)

    siblings = list(
        DossierSection.objects.select_for_update()
        .filter(dossier=dossier, parent_id=section.parent_id, retired_at__isnull=True)
        .order_by("sequence", "id")
    )
    locked = next((s for s in siblings if s.pk == section.pk), None)
    if locked is None:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    from_sequence = locked.sequence
    others = [s for s in siblings if s.pk != locked.pk]
    others.insert(min(max(sequence, 0), len(others)), locked)

    # Rewrite the whole group in one pass. Two-phase to sidestep the unique
    # constraint: a straight renumber can collide with a value still held by a
    # row not yet updated.
    #
    # The parking values are a HIGH offset, not negatives -- `sequence` is a
    # PositiveIntegerField, so PostgreSQL rejects a negative with a check
    # violation. The offset is far above any real ordering, and both phases
    # happen inside the same locked transaction, so it is never observable.
    park = _SEQUENCE_PARK_OFFSET
    with section_write(OP_REORDER):
        for index, sibling in enumerate(others):
            DossierSection.governed.filter(pk=sibling.pk).update(sequence=park + index)
        for index, sibling in enumerate(others):
            DossierSection.governed.filter(pk=sibling.pk).update(sequence=index * 10)

    locked.refresh_from_db()
    emit(
        event_type=DossierEvent.SECTION_REORDERED,
        resource_id=dossier.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "section_reordered",
            "dossier_public_id": str(dossier.public_id),
            "section_public_id": str(locked.public_id),
            "from_sequence": from_sequence,
            "to_sequence": locked.sequence,
        },
    )
    return locked


@transaction.atomic
def retire_section(*, section, tenant, actor) -> DossierSection:
    """Retire rather than delete.

    A section can carry link history and blocker history, and deleting the row
    would strand both. Retirement keeps the record and frees its code and
    sequence for reuse -- the unique constraints are partial on
    `retired_at IS NULL` for exactly that reason.
    """
    _assert_tenant(section, tenant)
    dossier = SubmissionDossier.objects.select_for_update().get(pk=section.dossier_id)
    _require_mutable(dossier)

    locked = DossierSection.objects.select_for_update().get(pk=section.pk)
    if locked.is_retired:
        raise DossierLocked("This section is already retired.")
    if locked.children.filter(retired_at__isnull=True).exists():
        raise InvalidHierarchy("Retire the child sections first.")

    locked.retired_at = timezone.now()
    locked.retired_by = actor
    with section_write(OP_RETIRE):
        locked.save(update_fields=["retired_at", "retired_by", "updated_at"])

    recalculate_dossier(dossier)
    emit(
        event_type=DossierEvent.SECTION_RETIRED,
        resource_id=dossier.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "section_retired",
            "dossier_public_id": str(dossier.public_id),
            "section_public_id": str(locked.public_id),
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------
def recalculate_dossier(dossier) -> None:
    """Recompute readiness for every active section, bottom-up.

    One pass over three aggregate queries, not a query per section: the tree is
    loaded once, children are grouped in memory, and deepest nodes are resolved
    first so a parent always sees final child values.
    """
    from django.db.models import Count

    sections = list(
        DossierSection.objects.filter(dossier=dossier, retired_at__isnull=True).order_by("id")
    )
    if not sections:
        return

    ids = [s.pk for s in sections]
    blockers = dict(
        DossierSectionBlocker.objects.filter(section_id__in=ids, status=BlockerStatus.OPEN)
        .values("section_id")
        .annotate(n=Count("id"))
        .values_list("section_id", "n")
    )
    counts = {s.pk: {} for s in sections}
    for kind, model in (
        ("document", DossierSectionDocument),
        ("workflow", DossierSectionWorkflow),
        ("checklist", DossierSectionChecklist),
    ):
        for sid, n in (
            model.objects.filter(section_id__in=ids, unlinked_at__isnull=True)
            .values("section_id")
            .annotate(n=Count("id"))
            .values_list("section_id", "n")
        ):
            counts[sid][kind] = n

    children_of: dict = {}
    for s in sections:
        children_of.setdefault(s.parent_id, []).append(s)

    # Depth per node, so the deepest are resolved first.
    by_id = {s.pk: s for s in sections}
    depth = {}

    def _depth(node):
        if node.pk in depth:
            return depth[node.pk]
        parent = by_id.get(node.parent_id)
        depth[node.pk] = 1 if parent is None else _depth(parent) + 1
        return depth[node.pk]

    for s in sections:
        _depth(s)

    resolved: dict = {}
    for s in sorted(sections, key=lambda n: -depth[n.pk]):
        child_results = [
            (c.required, resolved[c.pk][0]) for c in children_of.get(s.pk, []) if c.pk in resolved
        ]
        resolved[s.pk] = readiness_engine.calculate(
            s,
            open_blockers=blockers.get(s.pk, 0),
            link_counts=counts.get(s.pk, {}),
            child_results=child_results,
        )

    to_update = []
    for s in sections:
        new_readiness, new_reason = resolved[s.pk]
        if s.readiness != new_readiness or s.readiness_reason != new_reason:
            s.readiness = new_readiness
            s.readiness_reason = new_reason
            to_update.append(s)
    if to_update:
        # The ONLY path that may write readiness. No API, serializer or view
        # reaches this: readiness is derived, and the window plus the `0004`
        # trigger make that true below the serializer layer as well.
        with section_write(OP_RECALCULATE):
            DossierSection.governed.bulk_update(to_update, ["readiness", "readiness_reason"])


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------
@transaction.atomic
def create_blocker(*, section, tenant, actor, **fields) -> DossierSectionBlocker:
    _assert_tenant(section, tenant)
    dossier = SubmissionDossier.objects.select_for_update().get(pk=section.dossier_id)
    _require_mutable(dossier)

    blocker = DossierSectionBlocker.objects.create(
        tenant=tenant, section=section, created_by=actor, **fields
    )
    recalculate_dossier(dossier)
    emit(
        event_type=DossierEvent.BLOCKER_CREATED,
        resource_id=dossier.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "blocker_created",
            "dossier_public_id": str(dossier.public_id),
            "section_public_id": str(section.public_id),
            "blocker_public_id": str(blocker.public_id),
            "severity": blocker.severity,
        },
    )
    return blocker


@transaction.atomic
def resolve_blocker(*, blocker, tenant, actor) -> DossierSectionBlocker:
    _assert_tenant(blocker, tenant)
    locked = DossierSectionBlocker.objects.select_for_update().get(pk=blocker.pk)
    _assert_tenant(locked, tenant)
    if locked.status == BlockerStatus.RESOLVED:
        raise DossierLocked("This blocker is already resolved.")

    dossier = locked.section.dossier
    _require_mutable(dossier)

    locked.status = BlockerStatus.RESOLVED
    locked.resolved_by = actor
    locked.resolved_at = timezone.now()
    locked.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])

    recalculate_dossier(dossier)
    emit(
        event_type=DossierEvent.BLOCKER_RESOLVED,
        resource_id=dossier.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "blocker_resolved",
            "dossier_public_id": str(dossier.public_id),
            "section_public_id": str(locked.section.public_id),
            "blocker_public_id": str(locked.public_id),
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Section links -- two gates, exactly as regulatory_cases does it
# ---------------------------------------------------------------------------
def _resolve_document(public_id, tenant):
    from documents.models import Document

    return Document.objects.filter(public_id=public_id, tenant=tenant).first()


def _resolve_workflow(public_id, tenant):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.filter(public_id=public_id, tenant=tenant).first()


def _resolve_checklist(public_id, tenant):
    from iig_checklist.models import ChecklistExecution

    return ChecklistExecution.objects.filter(public_id=public_id, tenant=tenant).first()


def _may_view(kind):
    def check(user, tenant):
        from .projection import PERMISSION_CHECKS

        return PERMISSION_CHECKS[kind](user, tenant)

    return check


LINK_SPECS = {
    "document": {
        "model": DossierSectionDocument,
        "field": "document",
        "resolve": _resolve_document,
        "may_view": _may_view("document"),
        "linked_event": DossierEvent.DOCUMENT_LINKED,
        "unlinked_event": DossierEvent.DOCUMENT_UNLINKED,
    },
    "workflow": {
        "model": DossierSectionWorkflow,
        "field": "workflow_item",
        "resolve": _resolve_workflow,
        "may_view": _may_view("workflow"),
        "linked_event": DossierEvent.WORKFLOW_LINKED,
        "unlinked_event": DossierEvent.WORKFLOW_UNLINKED,
    },
    "checklist": {
        "model": DossierSectionChecklist,
        "field": "checklist_execution",
        "resolve": _resolve_checklist,
        "may_view": _may_view("checklist"),
        "linked_event": DossierEvent.CHECKLIST_LINKED,
        "unlinked_event": DossierEvent.CHECKLIST_UNLINKED,
    },
}


def link_target(*, kind, section, target_public_id, actor, tenant, purpose=""):
    """Link a document, workflow item or checklist execution to a section.

    TWO gates, both required: `submission_dossiers.manage_links` (by the view)
    AND the target module's own view permission (here). Neither implies the
    other.

    The module permission is checked BEFORE the target is resolved, and every
    failure raises the same exception with the same message, so unauthorized /
    absent / cross-tenant are one indistinguishable outcome. Resolving first
    would let response timing separate "does not exist" from "not yours".
    """
    spec = LINK_SPECS[kind]
    _assert_tenant(section, tenant)

    with transaction.atomic():
        dossier = SubmissionDossier.objects.select_for_update().get(pk=section.dossier_id)
        _require_mutable(dossier)

        locked = DossierSection.objects.select_for_update().get(pk=section.pk)
        _assert_tenant(locked, tenant)
        if locked.is_retired:
            raise DossierLocked("This section is retired and no longer accepts changes.")

        if not spec["may_view"](actor, tenant):
            raise InvalidTarget(INVALID_TARGET_MESSAGE)

        target = spec["resolve"](target_public_id, tenant)
        if target is None:
            raise InvalidTarget(INVALID_TARGET_MESSAGE)

        try:
            with transaction.atomic():
                link = spec["model"].objects.create(
                    section=locked,
                    tenant=tenant,
                    linked_by=actor,
                    purpose=(purpose or "").strip()[:255],
                    **{spec["field"]: target},
                )
        except IntegrityError as exc:
            raise DuplicateLink("That item is already linked to this section.") from exc

        recalculate_dossier(dossier)
        emit(
            event_type=spec["linked_event"],
            resource_id=dossier.public_id,
            actor=actor,
            tenant_id=tenant.pk,
            payload={
                "action": f"{kind}_linked",
                "dossier_public_id": str(dossier.public_id),
                "section_public_id": str(locked.public_id),
                "link_kind": kind,
                "link_public_id": str(link.public_id),
                "target_public_id": str(target.public_id),
            },
        )
    return link


def unlink_target(*, kind, section, link_public_id, actor, tenant):
    """Retire a section link. Stamps, never deletes."""
    spec = LINK_SPECS[kind]
    _assert_tenant(section, tenant)

    with transaction.atomic():
        dossier = SubmissionDossier.objects.select_for_update().get(pk=section.dossier_id)
        _require_mutable(dossier)

        record = (
            spec["model"]
            .objects.select_for_update()
            .filter(
                public_id=link_public_id,
                section=section,
                tenant=tenant,
                unlinked_at__isnull=True,
            )
            .first()
        )
        if record is None:
            raise InvalidTarget(INVALID_TARGET_MESSAGE)

        from django.db import models as _models

        record.unlinked_at = timezone.now()
        record.unlinked_by = actor
        # The manager blocks `update()` deliberately; this is the one sanctioned
        # write, so it goes through the base Model.save.
        _models.Model.save(record, update_fields=["unlinked_at", "unlinked_by", "updated_at"])

        recalculate_dossier(dossier)
        emit(
            event_type=spec["unlinked_event"],
            resource_id=dossier.public_id,
            actor=actor,
            tenant_id=tenant.pk,
            payload={
                "action": f"{kind}_unlinked",
                "dossier_public_id": str(dossier.public_id),
                "section_public_id": str(section.public_id),
                "link_kind": kind,
                "link_public_id": str(record.public_id),
            },
        )
    return record


def active_links(*, kind, section):
    """Active links of one kind with the target pre-joined."""
    spec = LINK_SPECS[kind]
    related = [spec["field"], "linked_by"]
    if kind == "document":
        related.append("document__current_version")
    if kind == "checklist":
        related.append("checklist_execution__checklist_version")
    return (
        spec["model"]
        .objects.filter(section=section, unlinked_at__isnull=True)
        .select_related(*related)
        .order_by("linked_at", "id")
    )
