"""Regulatory case workspace: a case, and governed links to work that already
exists elsewhere in RegX.

**This app owns no regulatory content and duplicates no engine.** A case is a
folder with governance: it references workflow items, documents and checklist
executions that the workflows, documents and iig_checklist apps continue to own
entirely. Nothing here copies their data, and evidence in particular stays owned
by `workflows.WorkflowEvidence` -- a case surfaces evidence *through* its linked
workflows and never creates a second evidence table.
"""

import uuid

from django.db import models, transaction

from common.models import PublicIDModel, TimeStampedModel


class CaseLinkMutationForbidden(Exception):
    """Raised when a governed case link is mutated outside the service layer."""


class CaseStatus(models.TextChoices):
    """Operational state of the case folder, deliberately NOT an approval flow.

    DRAFT / SUBMITTED / IN_REVIEW / APPROVED / REJECTED belong to
    `workflows.WorkflowItem` and are not repeated here. A case is open, paused,
    finished with, or abandoned; the regulatory decisions happen inside the
    workflow items it links.

    COMPLETED means "we have stopped working this case". It carries no claim
    that any authority approved anything.
    """

    OPEN = "open", "Open"
    ON_HOLD = "on_hold", "On hold"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


#: Structural changes (linking, unlinking, editing) are refused in these states.
#: Reopening is deliberately not offered: the repository has no reopen
#: convention for a terminal state, and inventing one here would create a
#: governance path nobody has agreed to.
TERMINAL_STATUSES = frozenset({CaseStatus.COMPLETED, CaseStatus.CANCELLED})


class CaseNumberSequence(models.Model):
    """Per-tenant counter behind `case_number`.

    A dedicated row rather than `MAX(case_number) + 1`: the max query cannot be
    made safe without locking every case row in the tenant, and locking the
    Tenant row itself would serialise unrelated work. `next_value` is claimed
    under `select_for_update`, so two concurrent creates take different numbers.

    The unique constraint on `(tenant, case_number)` is the real guarantee --
    this is the mechanism that avoids ever hitting it.
    """

    tenant = models.OneToOneField(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="case_number_sequence"
    )
    next_value = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "case number sequence"
        verbose_name_plural = "case number sequences"

    def __str__(self):
        return f"sequence for tenant {self.tenant_id} -> {self.next_value}"

    @classmethod
    def claim(cls, tenant) -> str:
        """Take the next case number for this tenant. Caller must be in an atomic block."""
        row, _ = cls.objects.select_for_update().get_or_create(tenant=tenant)
        value = row.next_value
        row.next_value = value + 1
        row.save(update_fields=["next_value"])
        # Internal identifier only. Deliberately NOT an agency-meaningful
        # reference: RegX does not assign submission numbers.
        return f"RC-{value:06d}"


class RegulatoryCase(PublicIDModel, TimeStampedModel):
    """A tenant-scoped regulatory case folder.

    `case_number` is unique per tenant, not globally: two tenants may both hold
    RC-000001 and they are different cases.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        related_name="regulatory_cases",
        db_index=True,
    )

    case_number = models.CharField(max_length=32, db_index=True)
    title = models.CharField(max_length=255)

    product_name = models.CharField(max_length=255)
    product_code = models.CharField(max_length=64, blank=True)
    market = models.CharField(max_length=120)
    authority = models.CharField(max_length=120, blank=True)
    submission_type = models.CharField(max_length=120)

    status = models.CharField(
        max_length=16, choices=CaseStatus.choices, default=CaseStatus.OPEN, db_index=True
    )

    owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_regulatory_cases",
    )
    target_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "case_number"], name="unique_case_number_per_tenant"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.case_number} {self.title}"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Governed link tables
#
# One explicit through-model per target rather than a generic relation: each
# target needs its own tenant check, its own permission gate and its own
# deletion protection, and a GenericForeignKey would hide all three behind an
# untyped column. The three are deliberately near-identical in shape, which is
# what makes the base class below worth having.
# ---------------------------------------------------------------------------
class _LinkQuerySet(models.QuerySet):
    """Blocks bulk paths that would bypass the service layer.

    Same reasoning as `workflows._EvidenceQuerySet`: unlinking records an actor
    and emits audit, and a queryset update or delete would skip both.
    """

    def update(self, **kwargs):
        raise CaseLinkMutationForbidden(
            "Case links are governed; use regulatory_cases.services to unlink."
        )

    def delete(self):
        raise CaseLinkMutationForbidden(
            "Case links are append-only and cannot be deleted; unlink instead."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise CaseLinkMutationForbidden("Case links are governed and cannot be bulk-updated.")


class CaseLinkManager(models.Manager):
    def get_queryset(self):
        return _LinkQuerySet(self.model, using=self._db)


class BaseCaseLink(TimeStampedModel):
    """Shared shape for the three case link tables.

    Abstract, so each link still gets its own table, its own unique constraint
    and its own indexes -- the sharing is of behaviour, not of storage.

    Unlinking stamps rather than deletes, matching `WorkflowEvidence`: the fact
    that a case once cited a workflow, document or checklist is itself part of
    the case history.
    """

    objects = CaseLinkManager()

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    # Denormalised so links stay tenant-filterable without joining through the
    # case on every query, and so a mismatched tenant is visible on the row.
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")

    label = models.CharField(max_length=255, blank=True)

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
        raise CaseLinkMutationForbidden(
            "Case links are append-only and cannot be deleted; unlink instead."
        )


class RegulatoryCaseWorkflow(BaseCaseLink):
    """A case cites a workflow item. The workflows app still owns the item."""

    case = models.ForeignKey(
        RegulatoryCase, on_delete=models.PROTECT, related_name="workflow_links"
    )
    workflow_item = models.ForeignKey(
        "workflows.WorkflowItem", on_delete=models.PROTECT, related_name="case_links"
    )

    class Meta(BaseCaseLink.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["case", "workflow_item"],
                condition=models.Q(unlinked_at__isnull=True),
                name="unique_active_case_workflow",
            ),
        ]
        indexes = [models.Index(fields=["case", "unlinked_at"])]

    def __str__(self):
        return f"case {self.case_id} -> workflow {self.workflow_item_id}"


class RegulatoryCaseDocument(BaseCaseLink):
    """A case cites a document.

    The target is `Document`, not `DocumentVersion`: a case folder tracks *which
    documents belong to this submission*, and that reference should follow the
    document as new versions are uploaded. Milestone 7's exact-version pinning
    exists for a different question -- "which bytes did this workflow cite" --
    and is untouched here.
    """

    case = models.ForeignKey(
        RegulatoryCase, on_delete=models.PROTECT, related_name="document_links"
    )
    document = models.ForeignKey(
        "documents.Document", on_delete=models.PROTECT, related_name="case_links"
    )

    class Meta(BaseCaseLink.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["case", "document"],
                condition=models.Q(unlinked_at__isnull=True),
                name="unique_active_case_document",
            ),
        ]
        indexes = [models.Index(fields=["case", "unlinked_at"])]

    def __str__(self):
        return f"case {self.case_id} -> document {self.document_id}"


class RegulatoryCaseChecklist(BaseCaseLink):
    """A case cites a checklist execution.

    `ChecklistExecution` rather than `ChecklistDefinition` or `ChecklistVersion`:
    the execution is the tenant's operational run, which is what belongs to a
    case. A definition is catalogue content shared across cases.
    """

    case = models.ForeignKey(
        RegulatoryCase, on_delete=models.PROTECT, related_name="checklist_links"
    )
    checklist_execution = models.ForeignKey(
        "iig_checklist.ChecklistExecution", on_delete=models.PROTECT, related_name="case_links"
    )

    class Meta(BaseCaseLink.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["case", "checklist_execution"],
                condition=models.Q(unlinked_at__isnull=True),
                name="unique_active_case_checklist",
            ),
        ]
        indexes = [models.Index(fields=["case", "unlinked_at"])]

    def __str__(self):
        return f"case {self.case_id} -> checklist execution {self.checklist_execution_id}"


#: Used by the services and views so the three link types can be handled
#: uniformly without losing their individual typing.
LINK_MODELS = {
    "workflow": RegulatoryCaseWorkflow,
    "document": RegulatoryCaseDocument,
    "checklist": RegulatoryCaseChecklist,
}


def _unstamped(model) -> models.QuerySet:
    """Active links only. Kept here so every caller filters the same way."""
    return model.objects.filter(unlinked_at__isnull=True)


__all__ = [
    "LINK_MODELS",
    "TERMINAL_STATUSES",
    "CaseLinkMutationForbidden",
    "CaseNumberSequence",
    "CaseStatus",
    "RegulatoryCase",
    "RegulatoryCaseChecklist",
    "RegulatoryCaseDocument",
    "RegulatoryCaseWorkflow",
    "transaction",
]
