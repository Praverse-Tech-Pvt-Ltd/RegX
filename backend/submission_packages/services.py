"""Package assembly, review, freeze, clone and export.

**EXACT VERSIONS, ALWAYS.** Nothing in this module reads
`document.current_version`. An entry is created against a `DocumentVersion` the
caller named, and every later read -- manifest, integrity, export -- goes through
`entry.document_version`. That is what makes a frozen package mean something a
year later.

**FROZEN IS INTERNAL.** It means the manifest can no longer change. It is not QA
approval, regulatory approval or agency acceptance, and nothing here decides
whether a package is fit for any external purpose.

STATE MACHINE
-------------
    DRAFT      -> IN_REVIEW, CANCELLED
    IN_REVIEW  -> DRAFT, FROZEN, CANCELLED
    FROZEN     terminal
    CANCELLED  terminal

There is no unfreeze and no reopen. Changing a frozen package means cloning it
into a new DRAFT, which leaves the original exactly as it was -- the only honest
way to keep a record that is also useful.

LOCK ORDER
----------
    1. SubmissionPackage
    2. SubmissionPackageEntry   (by pk, so two transactions agree on an order)
    3. DocumentVersion          (read; the document platform owns its own locks)

The package row is the serialization point: freeze, entry mutation and clone all
take it first, so exactly one freeze can win and no entry can be added into a
package that is mid-freeze.
"""

from django.db import transaction
from django.utils import timezone

from .audit_events import PackageEvent, emit
from .integrity import IntegrityIssue, check_package
from .manifest import MANIFEST_SCHEMA_VERSION, build_manifest, manifest_checksum, total_bytes
from .models import (
    MUTABLE_PACKAGE_STATUSES,
    PackageStatus,
    SubmissionPackage,
    SubmissionPackageEntry,
    SubmissionPackageSnapshot,
)
from .paths import (
    InvalidLogicalPath,
    collision_key,
    normalize_logical_path,
    sanitize_export_filename,
)


class PackageError(Exception):
    """Base for every refusal this module makes."""


class InvalidTarget(PackageError):
    """Absent, cross-tenant or unauthorised -- deliberately indistinguishable."""


class PackageLocked(PackageError):
    """The package is in a state that refuses this operation."""


class PackageIntegrityError(PackageError):
    """Integrity check failed; `issues` carries the enumerated reasons."""

    def __init__(self, message, issues=None):
        self.issues = issues or []
        super().__init__(message)


#: One message for absent, cross-tenant and unauthorised. Distinct messages
#: would let a caller probe for cases, documents and sections outside their
#: tenant -- the Milestone 8 existence-oracle lesson.
INVALID_TARGET_MESSAGE = "That target is not available."


def _assert_tenant(obj, tenant) -> None:
    if obj is None or obj.tenant_id != tenant.pk:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def _resolve_case(case_public_id, tenant):
    from regulatory_cases.models import RegulatoryCase

    return RegulatoryCase.objects.filter(public_id=case_public_id, tenant=tenant).first()


def resolve_document_version(document_version_public_id, tenant):
    """The exact version a caller named, or refuse.

    Requires `scan_status == CLEAN`, matching what `workflows` requires to cite
    a version as governed evidence and deliberately stricter than the document
    platform's serve-time check, which only blocks QUARANTINED. Serving a
    PENDING version to the person who just uploaded it is reasonable; freezing
    it into a permanent manifest is not.

    One message covers "no such version", "another tenant's version" and "not
    cleared", so a caller cannot probe for documents outside their tenant or
    learn the scan state of one they cannot see.
    """
    from documents.models import DocumentVersion, ScanStatus

    version = (
        DocumentVersion.objects.select_related("document")
        .filter(document__tenant=tenant, public_id=document_version_public_id)
        .first()
    )
    if version is None or version.scan_status != ScanStatus.CLEAN:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    return version


def _resolve_section(section_public_id, tenant, package):
    """A dossier section on the SAME case, or refuse.

    Cross-case association is refused rather than tolerated: a package entry
    pointing at a section in a different case is a traceability claim that is
    simply false, and freezing one would make it permanent.
    """
    from submission_dossiers.models import DossierSection

    section = (
        DossierSection.objects.select_related("dossier")
        .filter(public_id=section_public_id, tenant=tenant, retired_at__isnull=True)
        .first()
    )
    if section is None:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    if section.dossier.regulatory_case_id != package.regulatory_case_id:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    return section


def active_entries(package):
    """Active entries with everything the manifest and export need, prefetched.

    `select_related` down to `document_version__document` is what keeps the
    manifest at a constant query count: without it, reading
    `version.document.public_id` per row is a clean N+1 that only shows up on a
    package big enough to matter.
    """
    return (
        SubmissionPackageEntry.objects.filter(package=package, removed_at__isnull=True)
        .select_related(
            "document_version",
            "document_version__document",
            "dossier_section",
            "dossier_section__dossier",
        )
        .order_by("sequence", "id")
    )


# ---------------------------------------------------------------------------
# Package lifecycle
# ---------------------------------------------------------------------------
@transaction.atomic
def create_package(*, case_public_id, tenant, actor, name, description=""):
    """Create a DRAFT package on a case.

    TWO GATES, checked independently: `submission_packages.create` (by the view)
    and `regulatory_cases.view` (here, **before the case is resolved**), so an
    unauthorised caller and a missing case are one indistinguishable outcome.
    """
    from regulatory_cases.permissions import PERM_VIEW as CASE_VIEW
    from regulatory_cases.permissions import has_case_permission

    if not has_case_permission(actor, tenant, CASE_VIEW):
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    case = _resolve_case(case_public_id, tenant)
    if case is None:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)
    if case.is_terminal:
        raise PackageLocked("This case is closed and accepts no new packages.")

    package = SubmissionPackage.objects.create(
        tenant=tenant,
        regulatory_case=case,
        name=name,
        description=description,
        created_by=actor,
    )
    emit(
        event_type=PackageEvent.CREATED,
        resource_id=package.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "created",
            "package_public_id": str(package.public_id),
            "case_public_id": str(case.public_id),
            "revision_number": package.revision_number,
        },
    )
    return package


@transaction.atomic
def update_package(*, package, tenant, actor, **fields):
    """Rename or re-describe a package that is still being assembled.

    Metadata only, and only while DRAFT. A frozen package's name is part of its
    manifest and therefore part of what the checksum covers -- renaming it
    afterwards would make the stored manifest disagree with the row it
    describes.
    """
    _assert_tenant(package, tenant)
    locked = _locked(package, tenant)
    _require_mutable(locked)

    allowed = {k: v for k, v in fields.items() if k in {"name", "description"}}
    if not allowed:
        return locked

    now = timezone.now()
    SubmissionPackage.governed.filter(pk=locked.pk).update(updated_at=now, **allowed)
    locked.refresh_from_db()
    emit(
        event_type=PackageEvent.UPDATED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={"action": "updated", "package_public_id": str(locked.public_id)},
    )
    return locked


def _locked(package, tenant):
    locked = SubmissionPackage.objects.select_for_update().get(pk=package.pk)
    _assert_tenant(locked, tenant)
    return locked


def _require_mutable(package) -> None:
    if package.status not in MUTABLE_PACKAGE_STATUSES:
        raise PackageLocked(
            f"This package is {package.status} and its composition cannot be changed."
        )


@transaction.atomic
def add_entry(
    *,
    package,
    tenant,
    actor,
    document_version_public_id,
    logical_path="",
    display_name="",
    dossier_section_public_id=None,
):
    """Bind one exact document version into a DRAFT package.

    TWO GATES: `submission_packages.manage_entries` (by the view) and
    `documents.view` (here). A package permission has never granted document
    visibility, and adding an entry reads a document version.
    """
    from documents.permissions import PERM_VIEW as DOCUMENTS_VIEW
    from documents.permissions import has_document_permission

    _assert_tenant(package, tenant)
    if not has_document_permission(actor, tenant, DOCUMENTS_VIEW):
        raise InvalidTarget(INVALID_TARGET_MESSAGE)

    locked = _locked(package, tenant)
    _require_mutable(locked)

    version = resolve_document_version(document_version_public_id, tenant)
    section = (
        _resolve_section(dossier_section_public_id, tenant, locked)
        if dossier_section_public_id
        else None
    )

    try:
        path = normalize_logical_path(logical_path)
    except InvalidLogicalPath as exc:
        raise PackageIntegrityError(str(exc), [{"code": exc.code}]) from exc

    filename = sanitize_export_filename(
        version.original_filename, fallback=f"document-{version.public_id}"
    )

    # Collision is checked against the live active set under the package lock,
    # so two concurrent adds cannot both pass. The database's partial unique
    # index on (package, document_version) is the floor beneath this.
    key = collision_key(path, filename)
    for existing in active_entries(locked):
        if collision_key(existing.logical_path, existing.export_filename) == key:
            raise PackageIntegrityError(
                "Another entry already exports to that path.",
                [{"code": IntegrityIssue.DUPLICATE_PATH}],
            )

    next_sequence = (
        active_entries(locked).order_by("-sequence").values_list("sequence", flat=True).first()
    )
    entry = SubmissionPackageEntry.objects.create(
        tenant=tenant,
        package=locked,
        document_version=version,
        dossier_section=section,
        logical_path=path,
        export_filename=filename,
        display_name=display_name or version.original_filename,
        sequence=(next_sequence + 1) if next_sequence is not None else 0,
        added_by=actor,
    )
    emit(
        event_type=PackageEvent.ENTRY_ADDED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "entry_added",
            "package_public_id": str(locked.public_id),
            "entry_public_id": str(entry.public_id),
            "document_version_public_id": str(version.public_id),
        },
    )
    return entry


@transaction.atomic
def remove_entry(*, entry, tenant, actor):
    """Retire an entry. Never delete.

    An entry that was once in a package is part of how the package came to look
    the way it does, and a DRAFT is still governed history.
    """
    _assert_tenant(entry, tenant)
    locked_package = _locked(entry.package, tenant)
    _require_mutable(locked_package)

    locked = SubmissionPackageEntry.objects.select_for_update().get(pk=entry.pk)
    if locked.removed_at is not None:
        raise PackageLocked("This entry has already been removed.")

    now = timezone.now()
    SubmissionPackageEntry.governed.filter(pk=locked.pk).update(
        removed_at=now, removed_by=actor, updated_at=now
    )
    emit(
        event_type=PackageEvent.ENTRY_REMOVED,
        resource_id=locked_package.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "entry_removed",
            "package_public_id": str(locked_package.public_id),
            "entry_public_id": str(locked.public_id),
        },
    )
    locked.refresh_from_db()
    return locked


@transaction.atomic
def reorder_entry(*, entry, tenant, actor, sequence):
    _assert_tenant(entry, tenant)
    locked_package = _locked(entry.package, tenant)
    _require_mutable(locked_package)

    locked = SubmissionPackageEntry.objects.select_for_update().get(pk=entry.pk)
    if locked.removed_at is not None:
        raise PackageLocked("A removed entry cannot be reordered.")

    now = timezone.now()
    SubmissionPackageEntry.governed.filter(pk=locked.pk).update(
        sequence=int(sequence), updated_at=now
    )
    emit(
        event_type=PackageEvent.ENTRY_REORDERED,
        resource_id=locked_package.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "entry_reordered",
            "package_public_id": str(locked_package.public_id),
            "entry_public_id": str(locked.public_id),
            "sequence": int(sequence),
        },
    )
    locked.refresh_from_db()
    return locked


def _transition(*, package, tenant, actor, to_status, allowed_from, event, stamps=None):
    locked = _locked(package, tenant)
    if locked.status not in allowed_from:
        raise PackageLocked(f"A package that is {locked.status} cannot move to {to_status}.")

    now = timezone.now()
    fields = {"status": to_status, "updated_at": now, **(stamps(actor, now) if stamps else {})}
    SubmissionPackage.governed.filter(pk=locked.pk).update(**fields)
    locked.refresh_from_db()
    emit(
        event_type=event,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": event.split(".", 1)[1],
            "package_public_id": str(locked.public_id),
            "status": to_status,
        },
    )
    return locked


@transaction.atomic
def submit_for_review(*, package, tenant, actor):
    _assert_tenant(package, tenant)
    return _transition(
        package=package,
        tenant=tenant,
        actor=actor,
        to_status=PackageStatus.IN_REVIEW,
        allowed_from={PackageStatus.DRAFT},
        event=PackageEvent.SUBMITTED_FOR_REVIEW,
        stamps=lambda actor, now: {"reviewed_by": None, "reviewed_at": None},
    )


@transaction.atomic
def return_to_draft(*, package, tenant, actor):
    _assert_tenant(package, tenant)
    return _transition(
        package=package,
        tenant=tenant,
        actor=actor,
        to_status=PackageStatus.DRAFT,
        allowed_from={PackageStatus.IN_REVIEW},
        event=PackageEvent.RETURNED_TO_DRAFT,
    )


@transaction.atomic
def cancel_package(*, package, tenant, actor):
    _assert_tenant(package, tenant)
    return _transition(
        package=package,
        tenant=tenant,
        actor=actor,
        to_status=PackageStatus.CANCELLED,
        allowed_from={PackageStatus.DRAFT, PackageStatus.IN_REVIEW},
        event=PackageEvent.CANCELLED,
        stamps=lambda actor, now: {"cancelled_by": actor, "cancelled_at": now},
    )


# ---------------------------------------------------------------------------
# Integrity and freeze
# ---------------------------------------------------------------------------
def validate_package(*, package, tenant, verify_storage: bool = False) -> dict:
    """Internal package integrity only. No regulatory conclusion of any kind."""
    _assert_tenant(package, tenant)
    issues = check_package(
        package=package, entries=active_entries(package), verify_storage=verify_storage
    )
    return {
        "valid": not issues,
        "issues": issues,
        "semantics": "internal_package_integrity",
    }


@transaction.atomic
def freeze_package(*, package, tenant, actor):
    """Settle the manifest, permanently.

    Order matters and every step is inside one transaction, so a failure
    anywhere leaves no frozen status, no snapshot, no checksum and no success
    audit:

      1. lock the package
      2. prove the package is IN_REVIEW
      3. lock the active entries, by pk
      4. **revalidate every document version**, with storage checked
      5. build the canonical manifest and its checksum
      6. write the immutable snapshot
      7. set FROZEN and record the checksum
      8. emit the success event

    Step 4 is not a repeat of the validate endpoint being polite. A version can
    be quarantined, or a file can vanish, between review and freeze -- and after
    freeze the manifest is permanent, so this is the last moment the claim can
    be checked at all.
    """
    _assert_tenant(package, tenant)
    locked = _locked(package, tenant)

    # IN_REVIEW only, matching the state machine in the module docstring and the
    # `0002` trigger. Freezing is permanent, so it is always a second deliberate
    # act rather than something that can happen straight out of assembly -- and
    # having the service accept DRAFT while the database refused it would mean
    # two different state machines, one of which was wrong.
    if locked.status != PackageStatus.IN_REVIEW:
        raise PackageLocked(
            f"A package that is {locked.status} cannot be frozen; submit it for review first."
        )

    # Lock the entries in pk order so two transactions agree on an order and
    # cannot deadlock against each other.
    entry_ids = list(
        SubmissionPackageEntry.objects.filter(package=locked, removed_at__isnull=True)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if entry_ids:
        list(
            SubmissionPackageEntry.objects.select_for_update()
            .filter(pk__in=entry_ids)
            .order_by("pk")
        )

    entries = list(active_entries(locked))
    issues = check_package(package=locked, entries=entries, verify_storage=True)
    if issues:
        raise PackageIntegrityError(
            "This package cannot be frozen while it has integrity issues.", issues
        )

    manifest = build_manifest(package=locked, entries=entries)
    checksum = manifest_checksum(manifest)
    now = timezone.now()

    SubmissionPackageSnapshot.objects.create(
        tenant=tenant,
        package=locked,
        manifest_schema_version=MANIFEST_SCHEMA_VERSION,
        manifest=manifest,
        manifest_checksum=checksum,
        entry_count=len(entries),
        total_bytes=total_bytes(manifest),
        frozen_by=actor,
        frozen_at=now,
    )
    SubmissionPackage.governed.filter(pk=locked.pk).update(
        status=PackageStatus.FROZEN,
        frozen_by=actor,
        frozen_at=now,
        manifest_checksum=checksum,
        updated_at=now,
    )
    locked.refresh_from_db()

    emit(
        event_type=PackageEvent.FROZEN,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "frozen",
            "package_public_id": str(locked.public_id),
            "manifest_checksum": checksum,
            "entry_count": len(entries),
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------
@transaction.atomic
def clone_package(*, package, tenant, actor, name=None):
    """Copy a frozen package into a new DRAFT.

    The only way to change a frozen package, and it does not change it: the
    original keeps its status, its entries, its snapshot and its checksum.

    Entry references are copied **exactly**, including versions that would no
    longer be eligible today. That is deliberate -- the clone starts as a
    faithful picture of what was frozen, so the user can see what has to be
    replaced. Freeze will refuse until they do, which is the right place for the
    refusal: at the moment something permanent is being written, not at the
    moment someone asked to look.
    """
    _assert_tenant(package, tenant)
    source = _locked(package, tenant)
    if source.status != PackageStatus.FROZEN:
        raise PackageLocked("Only a frozen package can be cloned.")

    # Revision numbering is per family, claimed under the source package's lock
    # so two concurrent clones cannot take the same number.
    family_root = source
    while family_root.source_package_id is not None:
        family_root = family_root.source_package
    highest = (
        SubmissionPackage.objects.filter(
            tenant=tenant, regulatory_case=source.regulatory_case, name=source.name
        )
        .order_by("-revision_number")
        .values_list("revision_number", flat=True)
        .first()
    ) or source.revision_number

    clone = SubmissionPackage.objects.create(
        tenant=tenant,
        regulatory_case=source.regulatory_case,
        name=name or source.name,
        description=source.description,
        revision_number=highest + 1,
        source_package=source,
        created_by=actor,
    )
    for entry in active_entries(source):
        SubmissionPackageEntry.objects.create(
            tenant=tenant,
            package=clone,
            document_version=entry.document_version,
            dossier_section=entry.dossier_section,
            logical_path=entry.logical_path,
            export_filename=entry.export_filename,
            display_name=entry.display_name,
            sequence=entry.sequence,
            added_by=actor,
        )

    emit(
        event_type=PackageEvent.CLONED,
        resource_id=clone.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "cloned",
            "package_public_id": str(clone.public_id),
            "source_package_public_id": str(source.public_id),
            "revision_number": clone.revision_number,
        },
    )
    return clone
