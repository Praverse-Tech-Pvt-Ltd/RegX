"""Workflows domain — generic tenant-scoped work item and its append-only
transition history.

This is workflow *infrastructure*. It carries no regulatory content, confers no
approval, and establishes no Part 11 claim — see docs/WORKFLOW_ENGINE.md.

State is never assigned directly. It changes only through
`workflows.services`, which validates against `workflows.transitions` while
holding a row lock.
"""

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
