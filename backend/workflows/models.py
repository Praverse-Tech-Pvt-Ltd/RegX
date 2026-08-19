"""Workflows domain — generic tenant-scoped work item and its append-only
transition history.

This is workflow *infrastructure*. It carries no regulatory content, confers no
approval, and establishes no Part 11 claim — see docs/WORKFLOW_ENGINE.md.

State is never assigned directly. It changes only through
`workflows.services`, which validates against `workflows.transitions` while
holding a row lock.
"""

import uuid

from django.db import models
from django.utils import timezone

from common.models import PublicIDModel, TimeStampedModel


class WorkflowItem(PublicIDModel, TimeStampedModel):
    """A generic unit of tenant-scoped work moving through a review lifecycle."""

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        IN_REVIEW = "in_review", "In Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="workflow_items"
    )
    created_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="workflow_items"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    state = models.CharField(
        max_length=20, choices=State.choices, default=State.DRAFT, db_index=True
    )

    # Assignment. Nullable so an item can exist unassigned; the service layer is
    # what enforces that an assignee is an active member of the *same* tenant.
    assigned_to = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_workflow_items",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)

    # Operational metadata only. No SLA, no escalation, no notification --
    # see docs/WORKFLOW_ENGINE.md "Non-goals".
    due_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "state"]),
            models.Index(fields=["tenant", "assigned_to"]),
        ]

    def __str__(self):
        return f"{self.title} [{self.state}]"

    @property
    def is_terminal(self) -> bool:
        from .transitions import TERMINAL_STATES

        return self.state in TERMINAL_STATES

    @property
    def is_overdue(self) -> bool:
        """Purely derived: a due date in the past on a non-terminal item.

        Deliberately not a stored field and deliberately not a policy. Nothing
        acts on this value; it exists so a list view can mark a row.
        """
        if self.due_at is None or self.is_terminal:
            return False
        return self.due_at < timezone.now()


class WorkflowHistoryMutationForbidden(Exception):
    """Raised when any mutation is attempted on an existing WorkflowTransition."""


class _ImmutableTransitionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise WorkflowHistoryMutationForbidden(
            "WorkflowTransition rows are append-only and cannot be updated."
        )

    def delete(self):
        raise WorkflowHistoryMutationForbidden(
            "WorkflowTransition rows are append-only and cannot be deleted."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise WorkflowHistoryMutationForbidden(
            "WorkflowTransition rows are append-only and cannot be bulk-updated."
        )


class WorkflowTransitionManager(models.Manager):
    def get_queryset(self):
        return _ImmutableTransitionQuerySet(self.model, using=self._db)


class WorkflowTransition(PublicIDModel, TimeStampedModel):
    """Append-only record of one state change.

    Written inside the same transaction as the state change, one row per
    transition. Rows may never be mutated or deleted.

    The guard is model-level, matching `iig_checklist.ChecklistResponseHistory`
    rather than the database trigger used for `audit.AuditEvent`. Two history
    tables sharing one mechanism is the point; a third mechanism would not be.
    """

    objects = WorkflowTransitionManager()

    workflow_item = models.ForeignKey(
        WorkflowItem, on_delete=models.PROTECT, related_name="transitions"
    )
    # Denormalised deliberately: history must remain tenant-filterable without
    # joining a row that PROTECT should already prevent from disappearing.
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="workflow_transitions"
    )
    action = models.CharField(max_length=32)
    from_state = models.CharField(max_length=20)
    to_state = models.CharField(max_length=20)
    actor = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["workflow_item", "created_at"]),
            models.Index(fields=["tenant"]),
        ]

    def __str__(self):
        return f"{self.from_state} -> {self.to_state} ({self.action})"

    def delete(self, using=None, keep_parents=False):
        raise WorkflowHistoryMutationForbidden(
            "WorkflowTransition rows are append-only and cannot be deleted."
        )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise WorkflowHistoryMutationForbidden(
                "WorkflowTransition rows are append-only; save() on an existing row is forbidden."
            )
        super().save(*args, **kwargs)


class WorkflowEvidenceMutationForbidden(Exception):
    """Raised when a WorkflowEvidence row is mutated outside the service layer."""


class _EvidenceQuerySet(models.QuerySet):
    """Blocks bulk paths that would bypass the service layer's rules.

    `update()` is refused outright: unlinking goes through
    `workflows.services.unlink_evidence`, which checks workflow state, records
    the actor and emits audit. A queryset update would skip all three.
    """

    def update(self, **kwargs):
        raise WorkflowEvidenceMutationForbidden(
            "WorkflowEvidence rows are governed; use workflows.services to unlink."
        )

    def delete(self):
        raise WorkflowEvidenceMutationForbidden(
            "WorkflowEvidence rows are append-only and cannot be deleted; unlink instead."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise WorkflowEvidenceMutationForbidden(
            "WorkflowEvidence rows are governed and cannot be bulk-updated."
        )


class WorkflowEvidenceManager(models.Manager):
    def get_queryset(self):
        return _EvidenceQuerySet(self.model, using=self._db)


class WorkflowEvidence(models.Model):
    """A governed link from a workflow item to one exact DocumentVersion.

    **References a version, never a document.** `DocumentVersion` is immutable
    once processed and carries its own `sha256_checksum`, so a link identifies
    specific bytes. Linking a `Document` would mean "whatever this says today",
    and uploading version N+1 would silently change what the evidence asserts.
    Because the FK is to the version row, that cannot happen -- there is no
    "latest" pointer to follow.

    **No file bytes are stored here.** The document platform remains sole owner
    of storage, checksum, scan status, processing status and retrieval.

    Rows are never deleted. Unlinking stamps `unlinked_at`/`unlinked_by`, so the
    historical fact that a version was once cited survives -- the same reasoning
    behind `WorkflowTransition`. Database-level immutability is applied by
    migration `0005`.
    """

    objects = WorkflowEvidenceManager()

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    workflow_item = models.ForeignKey(
        WorkflowItem, on_delete=models.PROTECT, related_name="evidence"
    )
    # PROTECT, plus a DeletionProtectionRegistry checker registered from
    # AppConfig.ready(). Two independent defences, matching how the repository
    # already guards governed references to a version.
    document_version = models.ForeignKey(
        "documents.DocumentVersion", on_delete=models.PROTECT, related_name="workflow_evidence"
    )
    # Denormalised so evidence stays tenant-filterable without joining through
    # workflow_item -> tenant on every query.
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="workflow_evidence"
    )

    label = models.CharField(max_length=255, blank=True)

    linked_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    linked_at = models.DateTimeField(auto_now_add=True)
    unlinked_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["linked_at", "id"]
        constraints = [
            # Partial: one ACTIVE link per (item, version). Relinking after an
            # unlink stays possible, duplicates do not. The database is the
            # arbiter, so two concurrent link attempts cannot both win.
            models.UniqueConstraint(
                fields=["workflow_item", "document_version"],
                condition=models.Q(unlinked_at__isnull=True),
                name="unique_active_workflow_evidence",
            ),
        ]
        indexes = [
            models.Index(fields=["workflow_item", "unlinked_at"]),
            models.Index(fields=["tenant"]),
            models.Index(fields=["document_version"]),
        ]

    def __str__(self):
        state = "active" if self.is_active else "unlinked"
        return f"evidence {self.public_id} ({state})"

    @property
    def is_active(self) -> bool:
        return self.unlinked_at is None

    def delete(self, using=None, keep_parents=False):
        raise WorkflowEvidenceMutationForbidden(
            "WorkflowEvidence rows are append-only and cannot be deleted; unlink instead."
        )
