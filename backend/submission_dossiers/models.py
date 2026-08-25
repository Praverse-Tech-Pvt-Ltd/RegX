"""Submission dossiers: an ordered, nested readiness structure inside a case.

**This app owns structure and readiness. It owns no content and no engine.**

A dossier is an outline: sections, their order, who owns them, what is blocking
them, and whether the work behind them is internally ready. The work itself
stays where it already lives -- `documents.Document`, `workflows.WorkflowItem`,
`iig_checklist.ChecklistExecution` -- and evidence stays owned by
`workflows.WorkflowEvidence`. Nothing here copies a byte, re-implements a state
machine, or creates a second evidence table.

**READY means internally ready according to configured RegX section criteria.**
It is not regulatory compliance, agency approval, submission acceptance, filing
acceptance, or validated status. See docs/SUBMISSION_DOSSIERS.md.

On the hierarchy: `templates_registry.TemplateSection` is the existing
self-referencing tree in this repository and its shape is followed here
(`parent`, sequence, code unique within its scope). It is built by an importer
that constructs the tree top-down, so cycles cannot arise there and it has no
guard. These sections are edited through an API, so cycles ARE reachable and
are refused explicitly -- see `services.validate_parent`.
"""

import uuid

from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class DossierMutationForbidden(Exception):
    """Raised when a governed dossier row is mutated outside the service layer."""


#: Operational ceiling, not a regulatory one. Deep enough for any real
#: submission outline (CTD bottoms out around five levels); shallow enough that
#: an ancestor walk stays cheap and a hostile payload cannot build a chain that
#: makes readiness aggregation expensive.
MAX_SECTION_DEPTH = 10


class DossierStatus(models.TextChoices):
    """Operational state of the dossier, deliberately NOT an approval flow.

    COMPLETED means the tenant considers the internal dossier work finished. It
    carries no claim that anything was submitted to or accepted by an authority.
    """

    OPEN = "open", "Open"
    ON_HOLD = "on_hold", "On hold"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


TERMINAL_DOSSIER_STATUSES = frozenset({DossierStatus.COMPLETED, DossierStatus.CANCELLED})


class SectionStatus(models.TextChoices):
    """What the humans say about the section.

    No APPROVED state: approval belongs to the workflow engine. COMPLETE means
    internal work is considered done by the tenant's own process.
    """

    NOT_STARTED = "not_started", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    BLOCKED = "blocked", "Blocked"
    COMPLETE = "complete", "Complete"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class Readiness(models.TextChoices):
    """What the system derives. Never set directly by a user -- see services."""

    NOT_READY = "not_ready", "Not ready"
    PARTIALLY_READY = "partially_ready", "Partially ready"
    READY = "ready", "Ready"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class ReadinessReason(models.TextChoices):
    """Safe, enumerated explanations.

    Codes rather than prose, and deliberately coarse: a reason that named the
    offending workflow or document would leak exactly what the projection layer
    withholds from a caller who lacks that module's permission.
    """

    READY = "ready", "Ready"
    NOT_APPLICABLE = "not_applicable", "Not applicable"
    OPEN_BLOCKER = "open_blocker", "One or more open blockers"
    SECTION_NOT_COMPLETE = "section_not_complete", "Section is not marked complete"
    REQUIRED_CHILD_NOT_READY = "required_child_not_ready", "A required child section is not ready"
    NO_SUPPORTING_WORK = "no_supporting_work", "No supporting work recorded yet"


class BlockerSeverity(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class BlockerStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"


# ---------------------------------------------------------------------------
# Dossier
# ---------------------------------------------------------------------------
class SubmissionDossier(PublicIDModel, TimeStampedModel):
    """One structured submission package inside a case.

    A case may hold several -- an initial submission and a later deficiency
    response are different packages of the same case. Nothing constrains what
    they represent: `title` is free text and no submission taxonomy is encoded.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="submission_dossiers"
    )
    regulatory_case = models.ForeignKey(
        "regulatory_cases.RegulatoryCase", on_delete=models.PROTECT, related_name="dossiers"
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=DossierStatus.choices, default=DossierStatus.OPEN, db_index=True
    )

    owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_dossiers",
    )
    target_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["regulatory_case", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.regulatory_case_id})"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_DOSSIER_STATUSES


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------
SECTION_DELETE_MESSAGE = "Dossier sections cannot be deleted; retire the section instead."
BLOCKER_MUTATION_MESSAGE = (
    "Blocker history is governed; use submission_dossiers.services to resolve a blocker."
)
BLOCKER_DELETE_MESSAGE = "Blocker history cannot be deleted."


class _DossierSectionQuerySet(models.QuerySet):
    """Blocks queryset DELETE only.

    `update()` and `bulk_update()` are deliberately left alone: a section is
    legitimately mutable. `services.reorder_section` renumbers a whole sibling
    group with `.update()`, and `services.recalculate_dossier` writes derived
    readiness with `.bulk_update()`. Banning those would break the two
    operations that exist precisely to keep the outline consistent.

    What must never happen is the row disappearing -- a section's creation is
    already governed history, and it can carry link and blocker history that
    would be stranded.
    """

    def delete(self):
        raise DossierMutationForbidden(SECTION_DELETE_MESSAGE)


class DossierSectionManager(models.Manager):
    def get_queryset(self):
        return _DossierSectionQuerySet(self.model, using=self._db)


class _BlockerQuerySet(models.QuerySet):
    """Blockers are append-once history and gate readiness, so all three bulk
    paths are closed. Nothing in the service layer uses any of them: resolution
    goes through a single locked `save()`."""

    def update(self, **kwargs):
        raise DossierMutationForbidden(BLOCKER_MUTATION_MESSAGE)

    def delete(self):
        raise DossierMutationForbidden(BLOCKER_DELETE_MESSAGE)

    def bulk_update(self, objs, fields, batch_size=None):
        raise DossierMutationForbidden(BLOCKER_MUTATION_MESSAGE)


class BlockerManager(models.Manager):
    def get_queryset(self):
        return _BlockerQuerySet(self.model, using=self._db)


class DossierSection(PublicIDModel, TimeStampedModel):
    """One node of the dossier outline.

    `section_code` is display metadata only -- "1", "3.2.S.2.3", "Response-01".
    **Hierarchy comes from `parent`, never from parsing the string.** No CTD
    syntax is enforced and none is assumed; the engine must be able to represent
    those structures without encoding them.

    **Retirement is the only removal path.** See `services.retire_section`, the
    guards below, and the database triggers in `0003`.
    """

    objects = DossierSectionManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_sections"
    )
    dossier = models.ForeignKey(
        SubmissionDossier, on_delete=models.PROTECT, related_name="sections"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )

    section_code = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    sequence = models.PositiveIntegerField(default=0)
    required = models.BooleanField(default=True)

    status = models.CharField(
        max_length=20,
        choices=SectionStatus.choices,
        default=SectionStatus.NOT_STARTED,
        db_index=True,
    )
    #: Derived, never user-supplied. Persisted so list views need not recompute
    #: the whole tree per row; recomputed by `services.recalculate_readiness`
    #: on every change that could affect it.
    readiness = models.CharField(
        max_length=20, choices=Readiness.choices, default=Readiness.NOT_READY, db_index=True
    )
    readiness_reason = models.CharField(
        max_length=32, choices=ReadinessReason.choices, default=ReadinessReason.NO_SUPPORTING_WORK
    )

    owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_dossier_sections",
    )
    due_date = models.DateField(null=True, blank=True)

    #: Governed retirement, never deletion. A section can carry link history and
    #: blocker history, and removing the row would strand both.
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        # Deterministic: sequence first, then id as a stable tiebreak so two
        # rows sharing a sequence never render in database-timing order.
        ordering = ["sequence", "id"]
        constraints = [
            # Dossier-local rather than parent-local. A submission outline is
            # read and cited as a flat set of codes -- "see 3.2.S.2" means one
            # section in the package, not "whichever 3.2.S.2 sits under this
            # parent". Parent-local uniqueness would permit two sections with
            # the same printed code in one dossier, which is exactly the
            # ambiguity a code is supposed to remove.
            models.UniqueConstraint(
                fields=["dossier", "section_code"],
                condition=models.Q(retired_at__isnull=True),
                name="unique_active_section_code_per_dossier",
            ),
            # Sibling ordering, in two parts because PostgreSQL treats NULLs as
            # distinct: a single constraint on (dossier, parent, sequence)
            # would not constrain root sections at all.
            models.UniqueConstraint(
                fields=["dossier", "parent", "sequence"],
                condition=models.Q(retired_at__isnull=True, parent__isnull=False),
                name="unique_child_sequence_per_parent",
            ),
            models.UniqueConstraint(
                fields=["dossier", "sequence"],
                condition=models.Q(retired_at__isnull=True, parent__isnull=True),
                name="unique_root_sequence_per_dossier",
            ),
        ]
        indexes = [
            models.Index(fields=["dossier", "parent", "sequence"]),
            models.Index(fields=["dossier", "retired_at"]),
            models.Index(fields=["tenant"]),
        ]

    def __str__(self):
        return f"{self.section_code} {self.title}"

    @property
    def is_retired(self) -> bool:
        return self.retired_at is not None

    def delete(self, using=None, keep_parents=False):
        raise DossierMutationForbidden(SECTION_DELETE_MESSAGE)


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------
class DossierSectionBlocker(PublicIDModel, TimeStampedModel):
    """An explicit reason a section is not ready.

    Explicit rather than buried in `notes`, because readiness depends on it: a
    blocker recorded in prose cannot gate a calculation. Resolution stamps and
    is auditable; blocker history is never deleted.

    **Lifecycle: OPEN -> RESOLVED, exactly once, then immutable forever.** The
    check constraint below keeps the two resolution halves consistent at any
    instant; it cannot see the previous row, so it permits a resolved blocker
    being rewritten back to open. The `0003` triggers close that.
    """

    objects = BlockerManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_blockers"
    )
    section = models.ForeignKey(DossierSection, on_delete=models.PROTECT, related_name="blockers")

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    severity = models.CharField(
        max_length=10, choices=BlockerSeverity.choices, default=BlockerSeverity.MEDIUM
    )
    status = models.CharField(
        max_length=10, choices=BlockerStatus.choices, default=BlockerStatus.OPEN, db_index=True
    )

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    resolved_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # A resolved blocker must carry who and when; an open one must
            # carry neither. Without this the two halves could drift and a
            # "resolved" row could exist with no accountability on it.
            models.CheckConstraint(
                condition=(
                    models.Q(status="open", resolved_at__isnull=True, resolved_by__isnull=True)
                    | models.Q(
                        status="resolved", resolved_at__isnull=False, resolved_by__isnull=False
                    )
                ),
                name="blocker_resolution_is_consistent",
            ),
        ]
        indexes = [models.Index(fields=["section", "status"])]

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status == BlockerStatus.OPEN

    def delete(self, using=None, keep_parents=False):
        raise DossierMutationForbidden(BLOCKER_DELETE_MESSAGE)


# ---------------------------------------------------------------------------
# Governed section links
#
# Same shape and same reasoning as M8's case links: one explicit through-model
# per target so each keeps its own tenant check, permission gate and deletion
# protection, and a GenericForeignKey cannot hide any of the three behind an
# untyped column.
# ---------------------------------------------------------------------------
class _SectionLinkQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise DossierMutationForbidden(
            "Section links are governed; use submission_dossiers.services to unlink."
        )

    def delete(self):
        raise DossierMutationForbidden(
            "Section links are append-only and cannot be deleted; unlink instead."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise DossierMutationForbidden("Section links are governed and cannot be bulk-updated.")


class SectionLinkManager(models.Manager):
    def get_queryset(self):
        return _SectionLinkQuerySet(self.model, using=self._db)


class BaseSectionLink(TimeStampedModel):
    """Shared behaviour for the three section link tables.

    Abstract, so each still gets its own table, constraint and indexes.
    Unlinking stamps rather than deletes: the fact that a section once cited a
    document, workflow or checklist is part of the section's history.
    """

    objects = SectionLinkManager()

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=255, blank=True)

    linked_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    linked_at = models.DateTimeField(auto_now_add=True)
    unlinked_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["linked_at", "id"]

    @property
    def is_active(self) -> bool:
        return self.unlinked_at is None

    def delete(self, using=None, keep_parents=False):
        raise DossierMutationForbidden(
            "Section links are append-only and cannot be deleted; unlink instead."
        )


class DossierSectionDocument(BaseSectionLink):
    """Structural membership, so it targets `Document` and follows its versions.

    `DocumentVersion` is deliberately NOT the target: exact-version pinning
    answers "which bytes did this workflow cite", which is
    `workflows.WorkflowEvidence`'s job and stays there.
    """

    section = models.ForeignKey(
        DossierSection, on_delete=models.PROTECT, related_name="document_links"
    )
    document = models.ForeignKey(
        "documents.Document", on_delete=models.PROTECT, related_name="dossier_section_links"
    )

    class Meta(BaseSectionLink.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["section", "document"],
                condition=models.Q(unlinked_at__isnull=True),
                name="unique_active_section_document",
            ),
        ]
        indexes = [models.Index(fields=["section", "unlinked_at"])]


class DossierSectionWorkflow(BaseSectionLink):
    section = models.ForeignKey(
        DossierSection, on_delete=models.PROTECT, related_name="workflow_links"
    )
    workflow_item = models.ForeignKey(
        "workflows.WorkflowItem", on_delete=models.PROTECT, related_name="dossier_section_links"
    )

    class Meta(BaseSectionLink.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["section", "workflow_item"],
                condition=models.Q(unlinked_at__isnull=True),
                name="unique_active_section_workflow",
            ),
        ]
        indexes = [models.Index(fields=["section", "unlinked_at"])]


class DossierSectionChecklist(BaseSectionLink):
    section = models.ForeignKey(
        DossierSection, on_delete=models.PROTECT, related_name="checklist_links"
    )
    checklist_execution = models.ForeignKey(
        "iig_checklist.ChecklistExecution",
        on_delete=models.PROTECT,
        related_name="dossier_section_links",
    )

    class Meta(BaseSectionLink.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["section", "checklist_execution"],
                condition=models.Q(unlinked_at__isnull=True),
                name="unique_active_section_checklist",
            ),
        ]
        indexes = [models.Index(fields=["section", "unlinked_at"])]


LINK_MODELS = {
    "document": DossierSectionDocument,
    "workflow": DossierSectionWorkflow,
    "checklist": DossierSectionChecklist,
}

__all__ = [
    "LINK_MODELS",
    "MAX_SECTION_DEPTH",
    "TERMINAL_DOSSIER_STATUSES",
    "BlockerSeverity",
    "BlockerStatus",
    "DossierMutationForbidden",
    "DossierSection",
    "DossierSectionBlocker",
    "DossierSectionChecklist",
    "DossierSectionDocument",
    "DossierSectionWorkflow",
    "DossierStatus",
    "Readiness",
    "ReadinessReason",
    "SectionStatus",
    "SubmissionDossier",
]
