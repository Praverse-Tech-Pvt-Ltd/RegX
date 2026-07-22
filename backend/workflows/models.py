"""Workflows domain — scaffold only for foundation milestone."""

from django.db import models
from common.models import PublicIDModel, TimeStampedModel


class WorkflowItem(PublicIDModel, TimeStampedModel):
    """Placeholder workflow item. Full domain implementation in subsequent milestone."""

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="workflow_items"
    )
    created_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="workflow_items"
    )
    title = models.CharField(max_length=255)
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} [{self.state}]"
