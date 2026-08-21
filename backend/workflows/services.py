"""Authoritative WorkflowItem transition service.

Every state change in this domain goes through `perform_transition`. Nothing
else may write `WorkflowItem.state` -- not views, not serializers, not the
frontend, not a model `save()` override.

The concurrency contract, matching `fda_data/lifecycle.py` and
`templates_registry/lifecycle.py`: re-fetch the row with `select_for_update()`
inside `transaction.atomic()` and validate against **the locked row's** state,
never against a copy read before the lock. That is what makes two conflicting
transitions from one state resolve deterministically instead of last-write-wins
-- see docs/WORKFLOW_ENGINE.md "Concurrency".
"""

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .audit_events import ACTION_EVENTS, WorkflowEvent, emit
from .models import WorkflowEvidence, WorkflowItem, WorkflowTransition
from .permissions import ACTION_PERMISSIONS, has_workflow_permission
from .transitions import (
    REASON_REQUIRED_ACTIONS,
    IllegalWorkflowTransition,
    validate_workflow_transition,
)


class WorkflowPermissionDenied(Exception):
    """Actor lacks the permission required for this action in this tenant."""


class ReasonRequired(Exception):
    """A governed action was attempted without the required non-blank reason."""


class InvalidAssignee(Exception):
    """Proposed assignee is not an active member of this item's tenant."""


class TenantMismatch(Exception):
    """The item does not belong to the tenant the caller is acting in."""


class InvalidEvidenceTarget(Exception):
    """The document version is not linkable: absent, another tenant's, or not
    security-cleared. One message covers all three -- see the service."""


class EvidenceLocked(Exception):
    """The workflow state does not permit changing the evidence set."""


class DuplicateEvidence(Exception):
    """That version is already actively linked to this workflow item."""


def _assert_same_tenant(item: WorkflowItem, tenant) -> None:
    if tenant is None or item.tenant_id != tenant.pk:
        raise TenantMismatch("Workflow item does not belong to the active tenant.")


@transaction.atomic
def perform_transition(
    *,
    item: WorkflowItem,
    action: str,
    actor,
    tenant,
    reason: str = "",
) -> WorkflowItem:
    """Validate, apply and record one state transition.

    Order matters. Tenant scope is checked before anything else, then the row is
    locked, then legality is decided against the locked state, then permission,
    then the reason rule. Validation that could reject must complete before any
    write, so a rejected attempt leaves no trace beyond the failed request.
    """
    _assert_same_tenant(item, tenant)

    locked = WorkflowItem.objects.select_for_update().get(pk=item.pk)

    # Re-assert after locking: the row could in principle have been reparented
    # between the caller's read and the lock.
    _assert_same_tenant(locked, tenant)

    from_state = locked.state

    # Raises IllegalWorkflowTransition if this action is not legal from the
    # state we actually hold the lock on. This is the stale-state rejection:
    # the loser of a race sees the winner's state here, not its own.
    to_state = validate_workflow_transition(from_state, action)

    required = ACTION_PERMISSIONS.get(action)
    if required is None or not has_workflow_permission(actor, tenant, required):
        raise WorkflowPermissionDenied(f"Actor may not {action} in this tenant.")

    reason = (reason or "").strip()
    if action in REASON_REQUIRED_ACTIONS and not reason:
        raise ReasonRequired(f"A reason is required to {action} a workflow item.")

    locked.state = to_state
    locked.save(update_fields=["state", "updated_at"])

    record = WorkflowTransition.objects.create(
        workflow_item=locked,
        tenant=locked.tenant,
        action=action,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        reason=reason,
    )

    emit(
        event_type=ACTION_EVENTS[action],
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=locked.tenant_id,
        payload={
            "action": action,
            "from_state": from_state,
            "to_state": to_state,
            "reason_supplied": bool(reason),
            "reason_length": len(reason),
            "transition_public_id": str(record.public_id),
        },
    )
    return locked


@transaction.atomic
def assign(*, item: WorkflowItem, assignee, actor, tenant) -> WorkflowItem:
    """Assign or unassign an item. `assignee=None` clears the assignment.

    A cross-tenant assignee is rejected here rather than at the serializer, so
    the rule holds for every caller of the service, not just the HTTP one.
    """
    _assert_same_tenant(item, tenant)
    locked = WorkflowItem.objects.select_for_update().get(pk=item.pk)
    _assert_same_tenant(locked, tenant)

    if locked.is_terminal:
        raise IllegalWorkflowTransition(
            f"Cannot reassign a workflow item in terminal state {locked.state!r}.",
            locked.state,
        )

    if assignee is not None:
        from tenancy.models import TenantMembership

        is_member = TenantMembership.objects.filter(
            tenant=locked.tenant, user=assignee, is_active=True
        ).exists()
        if not is_member:
            raise InvalidAssignee("Assignee is not an active member of this tenant.")

    previous = locked.assigned_to
    locked.assigned_to = assignee
    locked.assigned_at = timezone.now() if assignee is not None else None
    locked.save(update_fields=["assigned_to", "assigned_at", "updated_at"])

    emit(
        event_type=WorkflowEvent.ASSIGNED if assignee else WorkflowEvent.UNASSIGNED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=locked.tenant_id,
        payload={
            "assigned_to_public_id": str(assignee.public_id) if assignee else None,
            "previous_assignee_public_id": str(previous.public_id) if previous else None,
        },
    )
    return locked


@transaction.atomic
def create_item(*, tenant, actor, title: str, description: str = "", due_at=None):
    """Create a DRAFT item. Creation is not a transition and writes no history:
    there is no from_state to record."""
    item = WorkflowItem.objects.create(
        tenant=tenant,
        created_by=actor,
        title=title,
        description=description,
        due_at=due_at,
        state=WorkflowItem.State.DRAFT,
    )
    emit(
        event_type=WorkflowEvent.CREATED,
        resource_id=item.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={"title_length": len(title), "due_at_set": due_at is not None},
    )
    return item


@transaction.atomic
def update_draft(*, item: WorkflowItem, actor, tenant, **fields) -> WorkflowItem:
    """Edit an item that is still in DRAFT. Editing a non-draft item is refused
    -- content must not change under a reviewer."""
    _assert_same_tenant(item, tenant)
    locked = WorkflowItem.objects.select_for_update().get(pk=item.pk)
    _assert_same_tenant(locked, tenant)

    if locked.state != WorkflowItem.State.DRAFT:
        raise IllegalWorkflowTransition(
            f"Only a DRAFT workflow item may be edited; this one is {locked.state!r}.",
            locked.state,
        )

    editable = {"title", "description", "due_at"}
    changed = []
    for name, value in fields.items():
        if name in editable and getattr(locked, name) != value:
            setattr(locked, name, value)
            changed.append(name)

    if changed:
        locked.save(update_fields=[*changed, "updated_at"])
        emit(
            event_type=WorkflowEvent.UPDATED,
            resource_id=locked.public_id,
            actor=actor,
            tenant_id=locked.tenant_id,
            payload={"fields_changed": sorted(changed)},
        )
    return locked


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------
# Only a DRAFT item's evidence may change. `update_draft` already refuses to
# edit a non-DRAFT item on the grounds that content must not change under a
# reviewer -- evidence is content, so it follows the same rule. REJECTED items
# go through the existing `return_to_draft` transition first, which is governed
# and recorded, rather than getting a private back door here.
EVIDENCE_MUTABLE_STATES = frozenset({WorkflowItem.State.DRAFT})


def _require_linkable_version(*, document_version_public_id, tenant):
    """Resolve a version this tenant may cite as evidence, or refuse.

    Requires scan_status == CLEAN. Deliberately stricter than the document
    platform's serve-time check, which only blocks QUARANTINED: serving a
    PENDING version to the person who just uploaded it is reasonable, citing it
    as governed evidence is not. INFECTED, SCAN_FAILED and SCANNER_UNAVAILABLE
    are non-conclusions, not clearances. No new security status is invented --
    this uses documents.ScanStatus as it stands.

    One message covers "no such version", "another tenant's version" and "not
    cleared". Distinct messages would let a caller probe for documents outside
    their tenant, and would disclose the scan state of one they cannot see.
    """
    from documents.models import DocumentVersion, ScanStatus

    version = (
        DocumentVersion.objects.select_related("document")
        .filter(document__tenant=tenant, public_id=document_version_public_id)
        .first()
    )
    if version is None or version.scan_status != ScanStatus.CLEAN:
        raise InvalidEvidenceTarget("Document version is not available to link as evidence.")
    return version


def _require_evidence_mutable(item: WorkflowItem) -> None:
    if item.state not in EVIDENCE_MUTABLE_STATES:
        raise EvidenceLocked(
            f"Evidence cannot be changed while the workflow item is {item.state!r}."
        )


@transaction.atomic
def link_evidence(
    *, item: WorkflowItem, document_version_public_id, actor, tenant, label: str = ""
) -> WorkflowEvidence:
    """Link one exact DocumentVersion to a DRAFT workflow item.

    Two authorization gates, both required and checked separately: the caller's
    workflow permission (by the view) and the tenant scope of the version
    (here). Neither implies the other.
    """
    _assert_same_tenant(item, tenant)
    locked = WorkflowItem.objects.select_for_update().get(pk=item.pk)
    _assert_same_tenant(locked, tenant)
    _require_evidence_mutable(locked)

    version = _require_linkable_version(
        document_version_public_id=document_version_public_id, tenant=tenant
    )

    try:
        with transaction.atomic():
            record = WorkflowEvidence.objects.create(
                workflow_item=locked,
                document_version=version,
                tenant=locked.tenant,
                label=(label or "").strip()[:255],
                linked_by=actor,
            )
    except IntegrityError as exc:
        # The partial unique constraint fired: another caller won the race, or
        # the version is already linked. Either way exactly one active link
        # exists, which is the property that matters.
        raise DuplicateEvidence(
            "That document version is already linked to this workflow item."
        ) from exc

    emit(
        event_type=WorkflowEvent.EVIDENCE_LINKED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=locked.tenant_id,
        payload={
            "action": "evidence_linked",
            "workflow_public_id": str(locked.public_id),
            "document_public_id": str(version.document.public_id),
            "document_version_public_id": str(version.public_id),
            "evidence_public_id": str(record.public_id),
        },
    )
    return record


@transaction.atomic
def unlink_evidence(*, item: WorkflowItem, evidence_public_id, actor, tenant) -> WorkflowEvidence:
    """Unlink evidence from a DRAFT workflow item.

    The row is stamped, never deleted: the historical fact that a version was
    cited survives, and the partial unique constraint then permits relinking.
    """
    _assert_same_tenant(item, tenant)
    locked = WorkflowItem.objects.select_for_update().get(pk=item.pk)
    _assert_same_tenant(locked, tenant)
    _require_evidence_mutable(locked)

    record = (
        WorkflowEvidence.objects.select_for_update()
        .filter(
            workflow_item=locked,
            tenant=tenant,
            public_id=evidence_public_id,
            unlinked_at__isnull=True,
        )
        .select_related("document_version__document")
        .first()
    )
    if record is None:
        raise InvalidEvidenceTarget("Evidence link not found for this workflow item.")

    record.unlinked_by = actor
    record.unlinked_at = timezone.now()
    # models.Model.save bypasses the manager's blocked queryset update()
    # deliberately: this IS the governed path, and the only one permitted to
    # stamp these two fields.
    models.Model.save(record, update_fields=["unlinked_by", "unlinked_at"])

    version = record.document_version
    emit(
        event_type=WorkflowEvent.EVIDENCE_UNLINKED,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=locked.tenant_id,
        payload={
            "action": "evidence_unlinked",
            "workflow_public_id": str(locked.public_id),
            "document_public_id": str(version.document.public_id),
            "document_version_public_id": str(version.public_id),
            "evidence_public_id": str(record.public_id),
        },
    )
    return record


def active_evidence_for(item: WorkflowItem, tenant):
    """Active links only, tenant-scoped. Read path -- no state restriction."""
    return (
        WorkflowEvidence.objects.filter(workflow_item=item, tenant=tenant, unlinked_at__isnull=True)
        .select_related("document_version__document", "linked_by")
        .order_by("linked_at", "id")
    )
