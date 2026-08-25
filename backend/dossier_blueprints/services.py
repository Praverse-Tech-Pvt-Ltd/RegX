"""Blueprint lifecycle, structure editing and instantiation.

Every write goes through here. The `0002` triggers are the floor beneath it, and
neither is a substitute for the other: the service produces clean 4xx answers and
audit rows, the database refuses the writes that never reached the service.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from .audit_events import BlueprintEvent, emit
from .models import (
    MAX_BLUEPRINT_DEPTH,
    BlueprintInstantiation,
    BlueprintSectionOrigin,
    BlueprintVersionStatus,
    DossierBlueprint,
    DossierBlueprintSection,
    DossierBlueprintVersion,
)

#: One message for every way a target can be unavailable. See `_resolve_case`.
INVALID_TARGET_MESSAGE = "That item is not available."


class InvalidTarget(Exception):
    """Absent, in another tenant, or not visible to this caller.

    Deliberately one exception with one message for all three: a distinct
    "not found" would turn the endpoint into an existence oracle.
    """


class BlueprintLocked(Exception):
    """The blueprint, version or section is in a state that refuses this change."""


class InvalidHierarchy(Exception):
    """The requested parent would corrupt the section tree."""


class DuplicateValue(Exception):
    """A uniqueness constraint refused the write."""


class NotActivatable(Exception):
    """The version does not yet satisfy the structural rules for activation."""


#: Reorder parks rows at a high offset before renumbering, because `sequence` is
#: a PositiveIntegerField and PostgreSQL rejects a negative outright. Same
#: reasoning and same value as the dossier section reorder.
_SEQUENCE_PARK_OFFSET = 1_000_000


def _assert_tenant(obj, tenant) -> None:
    if obj.tenant_id != tenant.pk:
        raise obj.__class__.DoesNotExist


def _require_draft(version) -> None:
    if version.status != BlueprintVersionStatus.DRAFT:
        raise BlueprintLocked(
            f"Version {version.version_number} is {version.status} and its structure is frozen. "
            f"Create a new version to make changes."
        )


# ---------------------------------------------------------------------------
# Blueprint identity
# ---------------------------------------------------------------------------
@transaction.atomic
def create_blueprint(*, tenant, actor, name, description="", owner=None) -> DossierBlueprint:
    try:
        blueprint = DossierBlueprint.objects.create(
            tenant=tenant,
            created_by=actor,
            name=name.strip(),
            description=description,
            owner=owner,
        )
    except IntegrityError as exc:
        raise DuplicateValue("A blueprint with that name already exists.") from exc

    emit(
        event_type=BlueprintEvent.CREATED,
        resource_id=blueprint.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={"action": "created", "blueprint_public_id": str(blueprint.public_id)},
    )
    return blueprint


@transaction.atomic
def update_blueprint(*, blueprint, tenant, actor, **fields) -> DossierBlueprint:
    _assert_tenant(blueprint, tenant)
    locked = DossierBlueprint.objects.select_for_update().get(pk=blueprint.pk)
    _assert_tenant(locked, tenant)
    if locked.is_archived:
        raise BlueprintLocked("This blueprint is archived.")

    changed = [name for name, value in fields.items() if getattr(locked, name) != value]
    if not changed:
        return locked
    for name, value in fields.items():
        setattr(locked, name, value)

    try:
        locked.save(update_fields=[*changed, "updated_at"])
    except IntegrityError as exc:
        raise DuplicateValue("A blueprint with that name already exists.") from exc

    emit(
        event_type=BlueprintEvent.UPDATED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "updated",
            "blueprint_public_id": str(locked.public_id),
            "fields_changed": sorted(changed),
        },
    )
    return locked


@transaction.atomic
def archive_blueprint(*, blueprint, tenant, actor) -> DossierBlueprint:
    """Archive the identity, never delete it.

    Archiving hides the blueprint from the library and frees its name. It does
    NOT touch its versions: an ACTIVE version stays instantiable, because
    dossiers already built from it and work already in flight should not be
    disrupted by a librarian tidying up. Retire the versions first if that is
    what is meant.
    """
    _assert_tenant(blueprint, tenant)
    locked = DossierBlueprint.objects.select_for_update().get(pk=blueprint.pk)
    _assert_tenant(locked, tenant)
    if locked.is_archived:
        raise BlueprintLocked("This blueprint is already archived.")

    locked.archived_at = timezone.now()
    locked.archived_by = actor
    locked.save(update_fields=["archived_at", "archived_by", "updated_at"])

    emit(
        event_type=BlueprintEvent.ARCHIVED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={"action": "archived", "blueprint_public_id": str(locked.public_id)},
    )
    return locked


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
@transaction.atomic
def create_version(
    *, blueprint, tenant, actor, source_version=None, notes=""
) -> DossierBlueprintVersion:
    """Allocate the next version, optionally cloning a source version's structure.

    **The blueprint row is locked first.** Version numbers are blueprint-local
    and allocated as `max + 1`, so two concurrent callers reading the same max
    would collide. The lock serialises them; the
    `unique_blueprint_version_number` constraint is the floor underneath, so even
    a future code path that skips this function cannot produce a duplicate.
    """
    _assert_tenant(blueprint, tenant)
    locked_blueprint = DossierBlueprint.objects.select_for_update().get(pk=blueprint.pk)
    _assert_tenant(locked_blueprint, tenant)
    if locked_blueprint.is_archived:
        raise BlueprintLocked("This blueprint is archived and accepts no new versions.")

    if source_version is not None:
        _assert_tenant(source_version, tenant)
        if source_version.blueprint_id != locked_blueprint.pk:
            raise InvalidTarget(INVALID_TARGET_MESSAGE)

    highest = DossierBlueprintVersion.objects.filter(blueprint=locked_blueprint).aggregate(
        Max("version_number")
    )["version_number__max"]
    next_number = 1 if highest is None else highest + 1

    try:
        version = DossierBlueprintVersion.objects.create(
            tenant=tenant,
            blueprint=locked_blueprint,
            version_number=next_number,
            status=BlueprintVersionStatus.DRAFT,
            notes=notes,
            supersedes=source_version,
            created_by=actor,
        )
    except IntegrityError as exc:
        raise DuplicateValue("That version number is already taken.") from exc

    if source_version is not None:
        _clone_sections(source_version, version, tenant)

    emit(
        event_type=BlueprintEvent.VERSION_CREATED,
        resource_id=version.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "version_created",
            "blueprint_public_id": str(locked_blueprint.public_id),
            "version_public_id": str(version.public_id),
            "version_number": version.version_number,
            "supersedes_public_id": str(source_version.public_id) if source_version else "",
            "section_count": version.sections.count(),
        },
    )
    return version


def _clone_sections(source, target, tenant) -> None:
    """Copy a version's active structure into a fresh DRAFT version.

    Parents are remapped by walking the source depth-first, so a child is always
    created after its parent and can point at the new row rather than the old
    one. Retired source sections are skipped: they are history on the source
    version, not structure to carry forward.
    """
    sources = list(
        DossierBlueprintSection.objects.filter(
            blueprint_version=source, retired_at__isnull=True
        ).order_by("id")
    )
    children_of: dict = {}
    for s in sources:
        children_of.setdefault(s.parent_id, []).append(s)
    for bucket in children_of.values():
        bucket.sort(key=lambda s: (s.sequence, s.id))

    mapping: dict = {}

    def _copy(parent_source_id, new_parent):
        for s in children_of.get(parent_source_id, []):
            created = DossierBlueprintSection.objects.create(
                tenant=tenant,
                blueprint_version=target,
                parent=new_parent,
                section_code=s.section_code,
                title=s.title,
                description=s.description,
                sequence=s.sequence,
                required=s.required,
                default_due_offset_days=s.default_due_offset_days,
            )
            mapping[s.pk] = created
            _copy(s.pk, created)

    _copy(None, None)


@transaction.atomic
def activate_version(*, version, tenant, actor) -> DossierBlueprintVersion:
    """Publish a DRAFT version, retiring the blueprint's previous ACTIVE one.

    **Only one ACTIVE version per blueprint**, matching the convention
    `templates_registry` already established with
    `unique_active_version_per_template`. Activating v2 retires v1 in the same
    transaction, so there is never an instant with two or zero.

    ACTIVE means *available for internal RegX dossier instantiation*. It is not a
    regulatory approval, a QA approval, an agency approval or a validated status,
    and nothing here should be read as claiming otherwise.
    """
    _assert_tenant(version, tenant)
    blueprint = DossierBlueprint.objects.select_for_update().get(pk=version.blueprint_id)

    # Lock the whole sibling version set, not just this row: two concurrent
    # activations on the same blueprint would otherwise both pass their checks
    # before either wrote.
    siblings = list(
        DossierBlueprintVersion.objects.select_for_update()
        .filter(blueprint=blueprint)
        .order_by("version_number")
    )
    locked = next((v for v in siblings if v.pk == version.pk), None)
    if locked is None:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    if locked.status != BlueprintVersionStatus.DRAFT:
        raise BlueprintLocked(f"Version {locked.version_number} is already {locked.status}.")

    # Structure is validated against the LOCKED state, and section writes take
    # the version lock too, so nothing can be added between check and publish.
    validate_structure(locked)

    now = timezone.now()
    previous = next(
        (v for v in siblings if v.status == BlueprintVersionStatus.ACTIVE and v.pk != locked.pk),
        None,
    )
    if previous is not None:
        previous.status = BlueprintVersionStatus.RETIRED
        previous.retired_at = now
        previous.retired_by = actor
        DossierBlueprintVersion.governed.filter(pk=previous.pk).update(
            status=BlueprintVersionStatus.RETIRED,
            retired_at=now,
            retired_by=actor,
            updated_at=now,
        )

    DossierBlueprintVersion.governed.filter(pk=locked.pk).update(
        status=BlueprintVersionStatus.ACTIVE,
        activated_at=now,
        activated_by=actor,
        updated_at=now,
    )
    locked.refresh_from_db()

    emit(
        event_type=BlueprintEvent.VERSION_ACTIVATED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "version_activated",
            "blueprint_public_id": str(blueprint.public_id),
            "version_public_id": str(locked.public_id),
            "version_number": locked.version_number,
            "from_status": BlueprintVersionStatus.DRAFT,
            "to_status": BlueprintVersionStatus.ACTIVE,
            "section_count": locked.sections.filter(retired_at__isnull=True).count(),
            "retired_version_public_id": str(previous.public_id) if previous else "",
        },
    )
    return locked


def validate_structure(version) -> None:
    """Refuse activation of a version whose structure is not internally sound.

    This is a *structural* check and nothing more. It does not and cannot say
    anything about regulatory completeness: RegX has no idea what a given
    submission requires, and a blueprint that passes here is merely coherent.
    """
    sections = list(
        DossierBlueprintSection.objects.filter(
            blueprint_version=version, retired_at__isnull=True
        ).order_by("id")
    )
    if not sections:
        raise NotActivatable("A version must have at least one section before it is activated.")

    by_id = {s.pk: s for s in sections}
    active_ids = set(by_id)

    codes: dict = {}
    for s in sections:
        if s.section_code in codes:
            raise NotActivatable(f"Section code {s.section_code!r} appears more than once.")
        codes[s.section_code] = s

        if s.parent_id is not None:
            if s.parent_id not in active_ids:
                # A retired or foreign parent. Both mean the tree does not close.
                raise NotActivatable(
                    f"Section {s.section_code!r} has a parent that is retired or "
                    f"outside this version."
                )
            if by_id[s.parent_id].blueprint_version_id != version.pk:
                raise NotActivatable(
                    f"Section {s.section_code!r} has a parent in a different version."
                )

    # Cycles and depth, in one walk per node with a shared memo.
    depth: dict = {}

    def _depth(node):
        if node.pk in depth:
            return depth[node.pk]
        seen = set()
        chain = []
        current = node
        while current is not None:
            if current.pk in seen:
                raise NotActivatable("The section tree contains a cycle.")
            seen.add(current.pk)
            chain.append(current)
            if current.pk in depth:
                break
            current = by_id.get(current.parent_id) if current.parent_id else None

        base = depth.get(chain[-1].pk, 0) if chain[-1].pk in depth else 0
        for offset, item in enumerate(reversed(chain)):
            if item.pk not in depth:
                depth[item.pk] = base + offset + (0 if base else 1)
        return depth[node.pk]

    for s in sections:
        if _depth(s) > MAX_BLUEPRINT_DEPTH:
            raise NotActivatable(
                f"Section {s.section_code!r} nests deeper than {MAX_BLUEPRINT_DEPTH} levels."
            )

    # Sibling ordering must be unambiguous, or two sections render in
    # database-timing order.
    seen_sequences: dict = {}
    for s in sections:
        key = (s.parent_id, s.sequence)
        if key in seen_sequences:
            raise NotActivatable(
                f"Sections {seen_sequences[key]!r} and {s.section_code!r} share a sequence."
            )
        seen_sequences[key] = s.section_code


@transaction.atomic
def retire_version(*, version, tenant, actor) -> DossierBlueprintVersion:
    """Withdraw a version from instantiation. Its structure stays readable forever.

    A DRAFT may be retired (abandoned), and so may an ACTIVE one. Dossiers
    already built from it are untouched -- that is the whole point of a snapshot.
    """
    _assert_tenant(version, tenant)
    DossierBlueprint.objects.select_for_update().get(pk=version.blueprint_id)
    locked = DossierBlueprintVersion.objects.select_for_update().get(pk=version.pk)
    _assert_tenant(locked, tenant)
    if locked.status == BlueprintVersionStatus.RETIRED:
        raise BlueprintLocked("This version is already retired.")

    now = timezone.now()
    from_status = locked.status
    DossierBlueprintVersion.governed.filter(pk=locked.pk).update(
        status=BlueprintVersionStatus.RETIRED,
        retired_at=now,
        retired_by=actor,
        updated_at=now,
    )
    locked.refresh_from_db()

    emit(
        event_type=BlueprintEvent.VERSION_RETIRED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "version_retired",
            "blueprint_public_id": str(locked.blueprint.public_id),
            "version_public_id": str(locked.public_id),
            "version_number": locked.version_number,
            "from_status": from_status,
            "to_status": BlueprintVersionStatus.RETIRED,
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Sections (DRAFT versions only)
# ---------------------------------------------------------------------------
def validate_parent(*, version, tenant, parent, child=None) -> None:
    """Refuse every way a parent assignment can corrupt the tree.

    Re-reads the parent from the database rather than trusting the object handed
    in: a caller holding a section fetched before it was retired would otherwise
    pass a stale `retired_at = NULL` straight through. Same defect, same fix as
    the dossier section version of this function.
    """
    if parent is None:
        return

    parent = DossierBlueprintSection.objects.filter(pk=parent.pk).first()
    if parent is None:
        raise InvalidHierarchy("That parent section is not available.")
    if parent.tenant_id != tenant.pk:
        raise InvalidHierarchy("That parent section is not available.")
    if parent.blueprint_version_id != version.pk:
        raise InvalidHierarchy("A section's parent must be in the same blueprint version.")
    if parent.is_retired:
        raise InvalidHierarchy("That parent section is retired.")

    if child is not None:
        if parent.pk == child.pk:
            raise InvalidHierarchy("A section cannot be its own parent.")
        walker = parent
        hops = 0
        while walker is not None:
            if walker.pk == child.pk:
                raise InvalidHierarchy("That parent would create a cycle.")
            hops += 1
            if hops > MAX_BLUEPRINT_DEPTH + 2:
                raise InvalidHierarchy("Section nesting is too deep.")
            walker = (
                DossierBlueprintSection.objects.filter(pk=walker.parent_id).first()
                if walker.parent_id
                else None
            )

    if _depth_of(parent) + 1 + (_subtree_depth(child) if child else 0) > MAX_BLUEPRINT_DEPTH:
        raise InvalidHierarchy(f"Sections cannot nest deeper than {MAX_BLUEPRINT_DEPTH} levels.")


def _depth_of(section) -> int:
    depth = 1
    walker = section
    while walker is not None and walker.parent_id:
        depth += 1
        if depth > MAX_BLUEPRINT_DEPTH + 2:
            break
        walker = DossierBlueprintSection.objects.filter(pk=walker.parent_id).first()
    return depth


def _subtree_depth(section) -> int:
    """How deep the subtree under `section` runs, so moving it cannot smuggle
    the tree past the ceiling."""
    children = list(DossierBlueprintSection.objects.filter(parent=section, retired_at__isnull=True))
    if not children:
        return 0
    return 1 + max(_subtree_depth(c) for c in children)


def _next_sequence(version, parent) -> int:
    existing = DossierBlueprintSection.objects.filter(
        blueprint_version=version, parent=parent, retired_at__isnull=True
    ).aggregate(Max("sequence"))["sequence__max"]
    return 0 if existing is None else existing + 10


@transaction.atomic
def create_section(*, version, tenant, actor, parent=None, **fields) -> DossierBlueprintSection:
    _assert_tenant(version, tenant)
    # Lock the version, so an activation running concurrently cannot publish a
    # structure this insert is about to change.
    locked_version = DossierBlueprintVersion.objects.select_for_update().get(pk=version.pk)
    _assert_tenant(locked_version, tenant)
    _require_draft(locked_version)
    validate_parent(version=locked_version, tenant=tenant, parent=parent)

    if fields.get("sequence") is None:
        fields["sequence"] = _next_sequence(locked_version, parent)

    try:
        section = DossierBlueprintSection.objects.create(
            tenant=tenant, blueprint_version=locked_version, parent=parent, **fields
        )
    except IntegrityError as exc:
        raise DuplicateValue(
            "A section with that code or sequence already exists in this version."
        ) from exc

    emit(
        event_type=BlueprintEvent.SECTION_CREATED,
        resource_id=locked_version.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "section_created",
            "blueprint_public_id": str(locked_version.blueprint.public_id),
            "version_public_id": str(locked_version.public_id),
            "section_public_id": str(section.public_id),
            "parent_public_id": str(parent.public_id) if parent else "",
            "section_code": section.section_code,
            "required": section.required,
        },
    )
    return section


@transaction.atomic
def update_section(*, section, tenant, actor, parent=..., **fields) -> DossierBlueprintSection:
    _assert_tenant(section, tenant)
    locked_version = DossierBlueprintVersion.objects.select_for_update().get(
        pk=section.blueprint_version_id
    )
    _require_draft(locked_version)

    locked = DossierBlueprintSection.objects.select_for_update().get(pk=section.pk)
    _assert_tenant(locked, tenant)
    if locked.is_retired:
        raise BlueprintLocked("This section is retired and no longer accepts changes.")

    changed = []
    if parent is not ...:
        validate_parent(version=locked_version, tenant=tenant, parent=parent, child=locked)
        if locked.parent_id != (parent.pk if parent else None):
            locked.parent = parent
            changed.append("parent")

    for name, value in fields.items():
        if getattr(locked, name) != value:
            setattr(locked, name, value)
            changed.append(name)

    if not changed:
        return locked

    try:
        locked.save(update_fields=[*changed, "updated_at"])
    except IntegrityError as exc:
        raise DuplicateValue(
            "A section with that code or sequence already exists in this version."
        ) from exc

    emit(
        event_type=BlueprintEvent.SECTION_UPDATED,
        resource_id=locked_version.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "section_updated",
            "version_public_id": str(locked_version.public_id),
            "section_public_id": str(locked.public_id),
            "fields_changed": sorted(changed),
        },
    )
    return locked


@transaction.atomic
def reorder_section(*, section, tenant, actor, sequence: int) -> DossierBlueprintSection:
    """Move a section within its sibling group, renumbering the whole group."""
    _assert_tenant(section, tenant)
    locked_version = DossierBlueprintVersion.objects.select_for_update().get(
        pk=section.blueprint_version_id
    )
    _require_draft(locked_version)

    siblings = list(
        DossierBlueprintSection.objects.select_for_update()
        .filter(
            blueprint_version=locked_version,
            parent_id=section.parent_id,
            retired_at__isnull=True,
        )
        .order_by("sequence", "id")
    )
    locked = next((s for s in siblings if s.pk == section.pk), None)
    if locked is None:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    from_sequence = locked.sequence
    others = [s for s in siblings if s.pk != locked.pk]
    others.insert(min(max(sequence, 0), len(others)), locked)

    # Two phases, parked at a high offset: a straight renumber collides with a
    # value still held by a row not yet updated, and a negative park would fail
    # the PositiveIntegerField check.
    park = _SEQUENCE_PARK_OFFSET
    for index, sibling in enumerate(others):
        DossierBlueprintSection.governed.filter(pk=sibling.pk).update(sequence=park + index)
    for index, sibling in enumerate(others):
        DossierBlueprintSection.governed.filter(pk=sibling.pk).update(sequence=index * 10)

    locked.refresh_from_db()
    emit(
        event_type=BlueprintEvent.SECTION_REORDERED,
        resource_id=locked_version.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "section_reordered",
            "version_public_id": str(locked_version.public_id),
            "section_public_id": str(locked.public_id),
            "from_sequence": from_sequence,
            "to_sequence": locked.sequence,
        },
    )
    return locked


@transaction.atomic
def retire_section(*, section, tenant, actor) -> DossierBlueprintSection:
    """Retire rather than delete, even in a DRAFT version.

    The project already treats creation as audit history everywhere else -- a
    dossier section, a case link, a blocker -- and a draft blueprint section is
    no different: its creation was audited, and a row that vanishes leaves that
    event pointing at nothing. Retirement frees the code and the sequence for
    reuse, which is what a user actually wants when they remove a draft row.
    """
    _assert_tenant(section, tenant)
    locked_version = DossierBlueprintVersion.objects.select_for_update().get(
        pk=section.blueprint_version_id
    )
    _require_draft(locked_version)

    locked = DossierBlueprintSection.objects.select_for_update().get(pk=section.pk)
    _assert_tenant(locked, tenant)
    if locked.is_retired:
        raise BlueprintLocked("This section is already retired.")
    if locked.children.filter(retired_at__isnull=True).exists():
        raise InvalidHierarchy("Retire the child sections first.")

    locked.retired_at = timezone.now()
    locked.retired_by = actor
    locked.save(update_fields=["retired_at", "retired_by", "updated_at"])

    emit(
        event_type=BlueprintEvent.SECTION_RETIRED,
        resource_id=locked_version.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "section_retired",
            "version_public_id": str(locked_version.public_id),
            "section_public_id": str(locked.public_id),
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Instantiation -- the core Milestone 10 operation
# ---------------------------------------------------------------------------
def _resolve_case(case_public_id, tenant):
    from regulatory_cases.models import RegulatoryCase

    return RegulatoryCase.objects.filter(public_id=case_public_id, tenant=tenant).first()


@transaction.atomic
def instantiate_version(
    *,
    version,
    tenant,
    actor,
    case_public_id,
    title,
    owner=None,
    target_date=None,
):
    """Stamp an ACTIVE blueprint version into a new dossier on a case.

    THREE GATES, checked independently, none implying another:

      1. `dossier_blueprints.instantiate`  -- checked by the view
      2. `submission_dossiers.create`      -- this creates a dossier
      3. `regulatory_cases.view`           -- this reads a case

    Gates 2 and 3 are checked **before the case is resolved**, and every failure
    raises the same exception with the same message, so "case does not exist",
    "case belongs to another tenant" and "you may not see cases" are one
    indistinguishable outcome. Milestone 8 shipped an endpoint that leaked
    exactly this difference; it is not repeated.

    All-or-nothing: the whole function is one transaction, so a failure anywhere
    leaves no dossier, no sections, no provenance and no audit row.
    """
    from regulatory_cases.permissions import PERM_VIEW as CASE_PERM_VIEW
    from regulatory_cases.permissions import has_case_permission
    from submission_dossiers.permissions import PERM_CREATE as DOSSIER_PERM_CREATE
    from submission_dossiers.permissions import has_dossier_permission

    _assert_tenant(version, tenant)
    locked_version = DossierBlueprintVersion.objects.select_for_update().get(pk=version.pk)
    _assert_tenant(locked_version, tenant)
    if locked_version.status != BlueprintVersionStatus.ACTIVE:
        raise BlueprintLocked(
            f"Only an active version can be instantiated; this one is {locked_version.status}."
        )

    # Target-domain gates BEFORE resolution, so timing cannot separate the cases.
    if not has_dossier_permission(actor, tenant, DOSSIER_PERM_CREATE):
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    if not has_case_permission(actor, tenant, CASE_PERM_VIEW):
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    case = _resolve_case(case_public_id, tenant)
    if case is None:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    if case.is_terminal:
        raise BlueprintLocked("This case is closed and accepts no new dossiers.")

    blueprint_sections = list(
        DossierBlueprintSection.objects.filter(
            blueprint_version=locked_version, retired_at__isnull=True
        ).order_by("id")
    )
    if not blueprint_sections:
        raise BlueprintLocked("This version has no sections to instantiate.")

    dossier = _create_dossier_shell(
        case=case, tenant=tenant, actor=actor, title=title, owner=owner, target_date=target_date
    )
    created = _materialise_sections(
        blueprint_sections=blueprint_sections,
        dossier=dossier,
        tenant=tenant,
        actor=actor,
        target_date=target_date,
    )

    instantiation = BlueprintInstantiation.objects.create(
        tenant=tenant,
        dossier=dossier,
        blueprint=locked_version.blueprint,
        blueprint_version=locked_version,
        version_number=locked_version.version_number,
        blueprint_name=locked_version.blueprint.name,
        section_count=len(created),
        instantiated_by=actor,
    )
    for blueprint_section, dossier_section in created:
        BlueprintSectionOrigin.objects.create(
            tenant=tenant,
            instantiation=instantiation,
            dossier_section=dossier_section,
            blueprint_section=blueprint_section,
        )

    # One recalculation for the whole tree rather than one per section: the
    # dossier service recomputes every row from three aggregates, so calling it
    # per section would be quadratic on a large blueprint.
    from submission_dossiers.services import recalculate_dossier

    recalculate_dossier(dossier)

    emit(
        event_type=BlueprintEvent.INSTANTIATED,
        resource_id=instantiation.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "instantiated",
            "instantiation_public_id": str(instantiation.public_id),
            "blueprint_public_id": str(locked_version.blueprint.public_id),
            "version_public_id": str(locked_version.public_id),
            "version_number": locked_version.version_number,
            "dossier_public_id": str(dossier.public_id),
            "case_public_id": str(case.public_id),
            "section_count": len(created),
        },
    )
    return instantiation


def _create_dossier_shell(*, case, tenant, actor, title, owner, target_date):
    from submission_dossiers.models import SubmissionDossier

    return SubmissionDossier.objects.create(
        tenant=tenant,
        regulatory_case=case,
        created_by=actor,
        title=title,
        owner=owner,
        target_date=target_date,
    )


def _materialise_sections(*, blueprint_sections, dossier, tenant, actor, target_date):
    """Copy structure into governed dossier sections, parents first.

    Only structural fields are copied. Identifiers, timestamps, the creator and
    every runtime field are deliberately not: a generated section starts at the
    Milestone 9 defaults -- NOT_STARTED, readiness derived, no blockers, no links
    -- because it is a fresh execution record, not a copy of one.

    `submission_dossiers.services.create_section` is deliberately not used: it
    recalculates readiness on every call, which would be quadratic here. The
    validation it performs is not lost -- the blueprint's structure was validated
    at activation, and the `submission_dossiers/0004` INSERT trigger re-checks
    parent tenant, dossier and cycles on every row regardless of who inserts it.
    """
    from submission_dossiers.models import DossierSection

    children_of: dict = {}
    for s in blueprint_sections:
        children_of.setdefault(s.parent_id, []).append(s)
    for bucket in children_of.values():
        bucket.sort(key=lambda s: (s.sequence, s.id))

    created: list = []

    def _emit_level(parent_source_id, new_parent):
        for source in children_of.get(parent_source_id, []):
            due_date = None
            if target_date is not None and source.default_due_offset_days is not None:
                # Tenant configuration, not a regulatory timeline: the section is
                # due `offset` days before the dossier's target date.
                due_date = target_date - timedelta(days=source.default_due_offset_days)

            section = DossierSection.objects.create(
                tenant=tenant,
                dossier=dossier,
                parent=new_parent,
                created_by=actor,
                section_code=source.section_code,
                title=source.title,
                description=source.description,
                sequence=source.sequence,
                required=source.required,
                due_date=due_date,
            )
            created.append((source, section))
            _emit_level(source.pk, section)

    _emit_level(None, None)
    return created


def active_version_for(blueprint):
    return blueprint.versions.filter(status=BlueprintVersionStatus.ACTIVE).first()
