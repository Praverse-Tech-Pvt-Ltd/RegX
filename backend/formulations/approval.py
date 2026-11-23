"""Review and approval of a formulation version (Option A, owner decision 2026-11-18;
docs/FORMULATION_APPROVAL_OPTIONS.md).

    draft --submit (Doer / Tenant Admin)--> under_review
    under_review --return with reason (Reviewer / VP)--> draft
    under_review --reject with reason (Reviewer / VP)--> retired
    under_review --approve with note (VP)--> approved
    approved --(a newer version of the same product is approved)--> superseded

Separation of duties, enforced here and not only by role: the user who CREATED
or SUBMITTED a version can never approve it, even when they also hold the VP
role. Every transition is audited (one append-only event each). The database
freezes a version, its components and its dosing regimens once it leaves draft
(migration 0004), so an approved version cannot be changed even outside Python.

Only an approved version can have the IIG checklist run on it
(iig_checklist.services); this module is the only sanctioned way there.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .audit_events import FormulationEvent, emit
from .models import FormulationStatus, FormulationVersion, ProductDevelopmentRecord
from .permissions import (
    PERM_APPROVE,
    PERM_REVIEW,
    PERM_SUBMIT_REVIEW,
    has_formulation_permission,
)


class ApprovalRefused(Exception):
    """A transition refused for a reason the user can act on."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


#: action -> (status it starts from, permission it needs)
ACTIONS = {
    "submit": (FormulationStatus.DRAFT, PERM_SUBMIT_REVIEW),
    "return": (FormulationStatus.UNDER_REVIEW, PERM_REVIEW),
    "reject": (FormulationStatus.UNDER_REVIEW, PERM_REVIEW),
    "approve": (FormulationStatus.UNDER_REVIEW, PERM_APPROVE),
}


def _is_creator_or_submitter(version: FormulationVersion, user) -> bool:
    uid = getattr(user, "id", None)
    return uid is not None and uid in (version.created_by_id, version.submitted_by_id)


def available_actions(version: FormulationVersion, user, tenant) -> list[str]:
    """What this user may do to this version now (for the screen; every
    transition below checks again)."""
    actions = []
    for action, (from_status, perm) in ACTIONS.items():
        if version.status != from_status or not has_formulation_permission(user, tenant, perm):
            continue
        if action == "approve" and _is_creator_or_submitter(version, user):
            continue
        actions.append(action)
    return actions


def _lock(version: FormulationVersion) -> FormulationVersion:
    return FormulationVersion.objects.select_for_update().get(pk=version.pk)


def _require(version, action: str, user, tenant) -> None:
    from_status, perm = ACTIONS[action]
    if not has_formulation_permission(user, tenant, perm):
        raise ApprovalRefused(
            "permission_denied", "You do not have permission to perform this action.", 403
        )
    if version.status != from_status:
        raise ApprovalRefused(
            "illegal_transition",
            f"This version is {version.get_status_display().lower()}; it can be "
            f"{'submitted' if action == 'submit' else action + 'ed'} only when it is "
            f"{from_status.replace('_', ' ')}.",
            409,
        )


def _audit(event_type, version, user, tenant, from_status, **extra):
    emit(
        event_type=event_type,
        resource_type="formulation_version",
        resource_id=str(version.public_id),
        tenant_id=tenant.id,
        actor_id=getattr(user, "id", None),
        actor_email=getattr(user, "email", ""),
        payload={
            "from_status": from_status,
            "to_status": version.status,
            "product_public_id": str(version.product.public_id),
            "version_number": version.version_number,
            **extra,
        },
    )


def completeness_problems(version: FormulationVersion) -> list[str]:
    """Why a draft cannot be submitted yet (empty when it can)."""
    from iid_assessment.amount_limits import recognised_unit

    problems = []
    components = list(version.components.all())
    if not components:
        problems.append("Add at least one component.")
    unknown = [c.ingredient_name for c in components if recognised_unit(c.quantity_unit) is None]
    if unknown:
        problems.append(
            "These components have a unit REGX does not recognise: " + ", ".join(unknown) + "."
        )
    if not version.total_dosage_unit_weight or version.total_dosage_unit_weight <= 0:
        problems.append("Enter the total dosage-unit weight.")
    return problems


def submit(version: FormulationVersion, user, tenant) -> FormulationVersion:
    with transaction.atomic():
        version = _lock(version)
        _require(version, "submit", user, tenant)
        problems = completeness_problems(version)
        if problems:
            raise ApprovalRefused("incomplete_version", " ".join(problems))
        version.status = FormulationStatus.UNDER_REVIEW
        version.submitted_by = user
        version.submitted_at = timezone.now()
        version.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
        _audit(FormulationEvent.VERSION_SUBMITTED_FOR_REVIEW, version, user, tenant, "draft")
    return version


def return_to_draft(version: FormulationVersion, user, tenant, reason: str) -> FormulationVersion:
    reason = (reason or "").strip()
    with transaction.atomic():
        version = _lock(version)
        _require(version, "return", user, tenant)
        if not reason:
            raise ApprovalRefused("reason_required", "Give a reason for returning the version.")
        version.status = FormulationStatus.DRAFT
        version.returned_by = user
        version.returned_at = timezone.now()
        version.return_reason = reason
        version.save(
            update_fields=["status", "returned_by", "returned_at", "return_reason", "updated_at"]
        )
        _audit(
            FormulationEvent.VERSION_RETURNED, version, user, tenant, "under_review", reason=reason
        )
    return version


def reject(version: FormulationVersion, user, tenant, reason: str) -> FormulationVersion:
    reason = (reason or "").strip()
    with transaction.atomic():
        version = _lock(version)
        _require(version, "reject", user, tenant)
        if not reason:
            raise ApprovalRefused("reason_required", "Give a reason for rejecting the version.")
        version.status = FormulationStatus.RETIRED
        version.rejected_by = user
        version.rejected_at = timezone.now()
        version.reject_reason = reason
        version.save(
            update_fields=["status", "rejected_by", "rejected_at", "reject_reason", "updated_at"]
        )
        _audit(
            FormulationEvent.VERSION_REJECTED, version, user, tenant, "under_review", reason=reason
        )
    return version


def approve(version: FormulationVersion, user, tenant, note: str) -> FormulationVersion:
    note = (note or "").strip()
    with transaction.atomic():
        # QA-08: lock the PRODUCT first, so approvals of versions of one product run one
        # at a time. Locking only the version and the currently approved siblings let two
        # transactions both see "none approved" and both approve. Always product, then
        # version: one lock order, no deadlock between approvals.
        ProductDevelopmentRecord.objects.select_for_update().get(pk=version.product_id)
        version = _lock(version)
        _require(version, "approve", user, tenant)
        if _is_creator_or_submitter(version, user):
            raise ApprovalRefused(
                "self_approval_forbidden",
                "You created or submitted this version, so you cannot approve it; another VP must.",
                403,
            )
        if not note:
            raise ApprovalRefused("note_required", "Write a short approval note.")
        now = timezone.now()
        previous = list(
            FormulationVersion.objects.select_for_update()
            .filter(product=version.product, status=FormulationStatus.APPROVED)
            .exclude(pk=version.pk)
        )
        for old in previous:
            old.status = FormulationStatus.SUPERSEDED
            old.superseded_at = now
            old.save(update_fields=["status", "superseded_at", "updated_at"])
            _audit(
                FormulationEvent.VERSION_SUPERSEDED,
                old,
                user,
                tenant,
                "approved",
                superseded_by=str(version.public_id),
            )
        version.status = FormulationStatus.APPROVED
        version.approved_by = user
        version.approved_at = now
        version.approval_note = note
        version.save(
            update_fields=["status", "approved_by", "approved_at", "approval_note", "updated_at"]
        )
        _audit(FormulationEvent.VERSION_APPROVED, version, user, tenant, "under_review", note=note)
    return version


def history(version: FormulationVersion) -> list[dict]:
    """The version's audit trail, oldest first, for the screen."""
    from audit.models import AuditEvent

    events = AuditEvent.objects.filter(resource_id=str(version.public_id)).order_by("created_at")
    labels = {
        FormulationEvent.FORMULATION_VERSION_CREATED: "created",
        FormulationEvent.VERSION_SUBMITTED_FOR_REVIEW: "submitted for review",
        FormulationEvent.VERSION_RETURNED: "returned to draft",
        FormulationEvent.VERSION_REJECTED: "rejected",
        FormulationEvent.VERSION_APPROVED: "approved (internal)",
        FormulationEvent.VERSION_SUPERSEDED: "superseded",
    }
    return [
        {
            "event": labels[e.event_type],
            "at": e.created_at.isoformat(),
            "by": e.actor_email,
            "reason": (e.payload or {}).get("reason") or (e.payload or {}).get("note") or "",
        }
        for e in events
        if e.event_type in labels
    ]
