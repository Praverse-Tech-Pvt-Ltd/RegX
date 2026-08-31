"""Internal submission packages: an exact, frozen set of document versions.

**A PACKAGE NEVER FOLLOWS "LATEST".** Every entry binds to a `DocumentVersion`,
never to a `Document`. Uploading a new version of a cited document changes
nothing about any package that already cites an earlier one -- that is the whole
point of the milestone, and it is enforced by the foreign key rather than by a
rule somebody has to remember.

`workflows.WorkflowEvidence` established this pattern for citing one exact
version; a package is the same idea for a set of them.

**FROZEN IS AN INTERNAL REGX STATE.** It means the manifest can no longer
change. It is not QA approval, not regulatory approval, not agency acceptance,
and not a statement that anything is ready to file. There is deliberately no
APPROVED state for it to be confused with.

**No agency format ships.** No eCTD, no sequence generation, no XML backbone, no
regional module, no NeeS, no gateway transmission. A package is a manifest and a
ZIP of files the tenant chose.
"""

from django.db import models
from django.db.models.functions import Coalesce

from common.models import PublicIDModel, TimeStampedModel

from .governance import PackageMutationForbidden

PACKAGE_MUTATION_MESSAGE = (
    "Submission packages are governed; use submission_packages.services rather "
    "than writing rows directly."
)
ENTRY_MUTATION_MESSAGE = (
    "Package entries are governed; use submission_packages.services rather than "
    "writing rows directly."
)
SNAPSHOT_MESSAGE = "A frozen package manifest is permanent and cannot be changed."


class PackageStatus(models.TextChoices):
    """Deliberately NOT an approval flow.

    A package is being assembled, being looked at, settled, or abandoned. The
    regulatory decisions, if any, happen elsewhere and are not repeated here --
    the same reasoning `regulatory_cases.CaseStatus` gives for having no
    APPROVED state.
    """

    DRAFT = "draft", "Draft"
    IN_REVIEW = "in_review", "In review"
    FROZEN = "frozen", "Frozen"
    CANCELLED = "cancelled", "Cancelled"


#: Structural edits are refused in these states. FROZEN is permanent by design:
#: a manifest that can be reopened is not a manifest, it is a draft with a
#: checksum. Changing a frozen package means cloning it into a new DRAFT.
TERMINAL_PACKAGE_STATUSES = frozenset({PackageStatus.FROZEN, PackageStatus.CANCELLED})
MUTABLE_PACKAGE_STATUSES = frozenset({PackageStatus.DRAFT})


class _NoDeleteQuerySet(models.QuerySet):
    """Blocks the bulk paths that skip `Model.delete()`.

    `Model.save()` resolves through `_base_manager` -- a plain `Manager` Django
    auto-creates, not `objects` -- so restricting the public manager can never
    cover a bare `save()`. That is what the `0002` triggers are for. This closes
    the queryset paths a service-layer mistake would otherwise take.
    """

    def delete(self):
        raise PackageMutationForbidden(PACKAGE_MUTATION_MESSAGE)


class PackageManager(models.Manager.from_queryset(_NoDeleteQuerySet)):
    """Read and create. Governed writes go through `governed`."""


class GovernedManager(models.Manager):
    """The service layer's own door, for `update()` the triggers still police."""


class _EntryQuerySet(models.QuerySet):
    def delete(self):
        raise PackageMutationForbidden(ENTRY_MUTATION_MESSAGE)


class EntryManager(models.Manager.from_queryset(_EntryQuerySet)):
    pass


class _HistoryQuerySet(models.QuerySet):
    def delete(self):
        raise PackageMutationForbidden(SNAPSHOT_MESSAGE)

    def update(self, **kwargs):
        raise PackageMutationForbidden(SNAPSHOT_MESSAGE)


class SnapshotManager(models.Manager.from_queryset(_HistoryQuerySet)):
    pass


class SubmissionPackage(PublicIDModel, TimeStampedModel):
    """One assembly of exact document versions for one regulatory case."""

    objects = PackageManager()
    governed = GovernedManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="submission_packages"
    )
    regulatory_case = models.ForeignKey(
        "regulatory_cases.RegulatoryCase",
        on_delete=models.PROTECT,
        related_name="submission_packages",
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=PackageStatus.choices, default=PackageStatus.DRAFT, db_index=True
    )

    #: Internal revision within a package family. **Not an agency sequence
    #: number.** It counts how many times this tenant has re-cut this package,
    #: nothing more, and no external meaning may be read into it. Unique within
    #: the family, enforced by `unique_revision_per_package_family`.
    revision_number = models.PositiveIntegerField(default=1)

    #: Immediate provenance: the frozen package this one was copied from.
    #:
    #: **This may branch.** Two clones of the same frozen revision are both
    #: legitimate -- someone can cut two alternatives from one baseline -- so
    #: `source_package` forms a tree, not a chain. What is linear is
    #: `revision_number` within the family, which is a different claim and the
    #: only one the schema actually enforces.
    source_package = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="clones"
    )

    #: The package that started this revision family, or NULL when this row *is*
    #: the start of one.
    #:
    #: Family identity is deliberately NOT the package name. A name is display
    #: text a user may edit at any time, and keying revisions on it would mean a
    #: rename silently forked one family into two -- or worse, merged two into
    #: one and collided their revision numbers. `family_root` is set once at
    #: clone time and frozen by the `0002` trigger thereafter.
    #:
    #: NULL rather than self-referential because a row cannot point at its own
    #: primary key before that key exists. The family of any package is
    #: therefore `COALESCE(family_root_id, id)`, which is what the uniqueness
    #: constraint and the clone lock both use.
    family_root = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="family_members"
    )

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    frozen_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    frozen_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    #: Set once, at freeze. Empty until then -- a checksum on an editable
    #: package would describe something that is still moving.
    manifest_checksum = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["regulatory_case", "-created_at"]),
        ]
        constraints = [
            # State and stamps agree, so a row cannot claim to be frozen without
            # saying when. The `0002` trigger enforces the transitions; this
            # enforces the resting state.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=["draft", "in_review"],
                        frozen_at__isnull=True,
                        cancelled_at__isnull=True,
                        manifest_checksum="",
                    )
                    | models.Q(status="frozen", frozen_at__isnull=False, cancelled_at__isnull=True)
                    | models.Q(status="cancelled", cancelled_at__isnull=False)
                ),
                name="package_stamps_are_consistent",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_package=models.F("id")),
                name="package_is_not_its_own_source",
            ),
            models.CheckConstraint(
                condition=~models.Q(family_root=models.F("id")),
                name="package_is_not_its_own_family_root",
            ),
            # THE floor under revision assignment. Locking the family root
            # serializes the ordinary path; this makes a duplicate impossible
            # even for a transaction that never took the lock -- a raw cursor, a
            # migration, or a future code path nobody re-reviewed.
            #
            # Expressed over COALESCE so a family founder (family_root NULL) and
            # its clones resolve to the same key. A plain multi-column unique
            # index cannot do that: NULLs would make every founder distinct from
            # everything, including its own family.
            models.UniqueConstraint(
                Coalesce("family_root", "id"),
                "tenant",
                "revision_number",
                name="unique_revision_per_package_family",
            ),
        ]

    def __str__(self):
        return f"{self.name} r{self.revision_number} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_PACKAGE_STATUSES

    @property
    def is_mutable(self) -> bool:
        return self.status in MUTABLE_PACKAGE_STATUSES

    def delete(self, using=None, keep_parents=False):
        raise PackageMutationForbidden(PACKAGE_MUTATION_MESSAGE)


class SubmissionPackageEntry(PublicIDModel, TimeStampedModel):
    """One exact document version, at one place in the package.

    The FK is to `DocumentVersion` and `on_delete=PROTECT`, with a
    `DeletionProtectionRegistry` checker registered from `apps.py` as a second
    defence -- the same two-layer guard `workflows.WorkflowEvidence` uses.
    """

    objects = EntryManager()
    governed = GovernedManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="submission_package_entries"
    )
    package = models.ForeignKey(SubmissionPackage, on_delete=models.PROTECT, related_name="entries")

    #: **Exact bytes.** Never `Document`, never `document.current_version`.
    document_version = models.ForeignKey(
        "documents.DocumentVersion", on_delete=models.PROTECT, related_name="package_entries"
    )

    #: Optional organisational traceability only. It records where in the
    #: dossier this file belongs; it infers nothing about regulatory structure,
    #: and `section_code` is never read as a standard.
    dossier_section = models.ForeignKey(
        "submission_dossiers.DossierSection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="package_entries",
    )

    #: Normalised by `paths.normalize_logical_path` before it is stored. Empty
    #: means the package root.
    logical_path = models.CharField(max_length=400, blank=True)
    #: Derived from the version's filename by `paths.sanitize_export_filename`.
    #: The uploaded name is never used as a path component directly.
    export_filename = models.CharField(max_length=200)
    display_name = models.CharField(max_length=255, blank=True)

    sequence = models.PositiveIntegerField(default=0)

    added_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    #: Retirement, not deletion. An entry that was once in a package is part of
    #: how the package came to look the way it does, and a DRAFT is still
    #: governed history.
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["sequence", "id"]
        indexes = [
            models.Index(fields=["package", "sequence"]),
            models.Index(fields=["tenant"]),
            models.Index(fields=["document_version"]),
        ]
        constraints = [
            # The same exact version twice in one package is almost always a
            # mistake, and a manifest with two identical rows is ambiguous about
            # what was intended. Partial on active rows so a removed entry does
            # not block re-adding the same version later.
            models.UniqueConstraint(
                fields=["package", "document_version"],
                condition=models.Q(removed_at__isnull=True),
                name="unique_active_version_per_package",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(removed_at__isnull=True, removed_by__isnull=True)
                    | models.Q(removed_at__isnull=False, removed_by__isnull=False)
                ),
                name="entry_removal_stamps_are_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.logical_path}/{self.export_filename}".lstrip("/")

    @property
    def is_active(self) -> bool:
        return self.removed_at is None

    def delete(self, using=None, keep_parents=False):
        raise PackageMutationForbidden(ENTRY_MUTATION_MESSAGE)


class SubmissionPackageSnapshot(PublicIDModel, TimeStampedModel):
    """The canonical manifest, as it stood at the instant of freeze.

    Append-only and never rewritten. The manifest is the package's account of
    itself; a record that can be edited afterwards is not a record.

    The JSON is stored rather than recomputed on read. Recomputing would make
    the manifest a function of today's database, so a later schema change or a
    retired dossier section would silently alter what a frozen package claims to
    have been -- and the stored checksum would then disagree with it.
    """

    objects = SnapshotManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="submission_package_snapshots"
    )
    package = models.OneToOneField(
        SubmissionPackage, on_delete=models.PROTECT, related_name="snapshot"
    )

    #: Bumped if the canonical field set ever changes, so an old checksum
    #: compares unequal rather than colliding with a differently-computed value.
    manifest_schema_version = models.PositiveIntegerField(default=1)
    manifest = models.JSONField()
    manifest_checksum = models.CharField(max_length=64, db_index=True)
    entry_count = models.PositiveIntegerField()
    total_bytes = models.BigIntegerField(default=0)

    frozen_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    frozen_at = models.DateTimeField()

    class Meta:
        ordering = ["-frozen_at", "-id"]
        indexes = [models.Index(fields=["tenant"])]

    def __str__(self):
        return f"manifest {self.manifest_checksum[:12]} ({self.entry_count} entries)"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PackageMutationForbidden(SNAPSHOT_MESSAGE)
        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise PackageMutationForbidden(SNAPSHOT_MESSAGE)
