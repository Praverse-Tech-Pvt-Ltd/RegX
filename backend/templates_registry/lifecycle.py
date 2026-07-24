"""
Template version lifecycle: transactional state transitions with an
auditable approval trail.

State machine (see TemplateLifecycleStatus):

    draft/imported --submit_for_review--> under_review
    under_review    --return_for_correction--> returned
    under_review    --approve--> approved
    under_review    --reject--> rejected
    returned        --submit_for_review--> under_review
    approved        --activate--> active   (supersedes any prior active version)
    active          --supersede--> superseded
    active/superseded --retire--> retired

Every transition is wrapped in a single DB transaction with
select_for_update() on the sibling version set, so "only one active
version per template" holds even under concurrent requests -- backed
additionally by a DB-level partial unique constraint on the model.

No transition here ever deletes a row. Corrections happen by creating a
new TemplateVersion (see importer.py), never by editing an
approved/active/superseded/retired one.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .audit_events import TemplateEvent, emit
from .models import (
    ApprovalDecision,
    RegulatoryTemplate,
    TemplateApproval,
    TemplateLifecycleStatus,
    TemplateVersion,
)


class InvalidTransition(Exception):
    pass


def _actor_fields(user):
    return {
        "actor_id": getattr(user, "id", None),
        "actor_email": getattr(user, "email", ""),
    }


def submit_for_review(version: TemplateVersion, actor) -> TemplateVersion:
    with transaction.atomic():
        locked = TemplateVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status not in (
            TemplateLifecycleStatus.DRAFT,
            TemplateLifecycleStatus.IMPORTED,
            TemplateLifecycleStatus.RETURNED,
        ):
            raise InvalidTransition(
                f"Cannot submit version in status '{locked.status}' for review."
            )
        locked.status = TemplateLifecycleStatus.UNDER_REVIEW
        locked.save(update_fields=["status", "updated_at"])
        emit(
            event_type=TemplateEvent.VERSION_SUBMITTED_FOR_REVIEW,
            resource_type="template_version",
            resource_id=str(locked.public_id),
            tenant_id=locked.template.tenant_id,
            payload={"template": str(locked.template.public_id)},
            **_actor_fields(actor),
        )
        return locked


def _next_approval_sequence(version: TemplateVersion) -> int:
    last = (
        TemplateApproval.objects.filter(template_version=version)
        .order_by("-approval_sequence")
        .first()
    )
    return (last.approval_sequence + 1) if last else 1


def _record_approval(version, reviewer, decision, comments, role_at_time):
    return TemplateApproval.objects.create(
        template_version=version,
        reviewer=reviewer,
        decision=decision,
        comments=comments,
        approval_sequence=_next_approval_sequence(version),
        role_at_time=role_at_time,
    )


def return_for_correction(
    version: TemplateVersion, reviewer, comments: str, role_at_time: str
) -> TemplateVersion:
    with transaction.atomic():
        locked = TemplateVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status != TemplateLifecycleStatus.UNDER_REVIEW:
            raise InvalidTransition(
                f"Cannot return version in status '{locked.status}' for correction."
            )
        _record_approval(locked, reviewer, ApprovalDecision.RETURNED, comments, role_at_time)
        locked.status = TemplateLifecycleStatus.RETURNED
        locked.save(update_fields=["status", "updated_at"])
        emit(
            event_type=TemplateEvent.VERSION_RETURNED,
            resource_type="template_version",
            resource_id=str(locked.public_id),
            tenant_id=locked.template.tenant_id,
            payload={"comments": comments},
            **_actor_fields(reviewer),
        )
        return locked


def approve(
    version: TemplateVersion, approver, comments: str, role_at_time: str
) -> TemplateVersion:
    """Segregation of duties: the approver must not be the version's creator."""
    with transaction.atomic():
        locked = TemplateVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status != TemplateLifecycleStatus.UNDER_REVIEW:
            raise InvalidTransition(f"Cannot approve version in status '{locked.status}'.")
        if locked.created_by_id is not None and locked.created_by_id == getattr(
            approver, "id", None
        ):
            raise PermissionDenied("A reviewer cannot approve a version they created themselves.")
        _record_approval(locked, approver, ApprovalDecision.APPROVED, comments, role_at_time)
        locked.status = TemplateLifecycleStatus.APPROVED
        locked.approved_by = approver
        locked.approved_at = timezone.now()
        locked.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        emit(
            event_type=TemplateEvent.VERSION_APPROVED,
            resource_type="template_version",
            resource_id=str(locked.public_id),
            tenant_id=locked.template.tenant_id,
            payload={"comments": comments},
            **_actor_fields(approver),
        )
        return locked


def reject(version: TemplateVersion, approver, comments: str, role_at_time: str) -> TemplateVersion:
    with transaction.atomic():
        locked = TemplateVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status != TemplateLifecycleStatus.UNDER_REVIEW:
            raise InvalidTransition(f"Cannot reject version in status '{locked.status}'.")
        _record_approval(locked, approver, ApprovalDecision.REJECTED, comments, role_at_time)
        locked.status = TemplateLifecycleStatus.REJECTED
        locked.save(update_fields=["status", "updated_at"])
        emit(
            event_type=TemplateEvent.VERSION_REJECTED,
            resource_type="template_version",
            resource_id=str(locked.public_id),
            tenant_id=locked.template.tenant_id,
            payload={"comments": comments},
            **_actor_fields(approver),
        )
        return locked


def activate(version: TemplateVersion, actor) -> TemplateVersion:
    """Approved -> Active. Transactionally supersedes any prior active
    version of the same template. Never auto-invoked by the import
    pipeline -- activation is always a distinct, explicit, audited action."""
    with transaction.atomic():
        locked = TemplateVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status != TemplateLifecycleStatus.APPROVED:
            raise InvalidTransition(
                f"Cannot activate version in status '{locked.status}'; only an approved "
                "version may be activated."
            )

        template = RegulatoryTemplate.objects.select_for_update().get(pk=locked.template_id)

        # Lock and supersede the sibling set to guarantee "only one active
        # version" even under concurrent activate() calls.
        siblings = TemplateVersion.objects.select_for_update().filter(
            template=template, status=TemplateLifecycleStatus.ACTIVE
        )
        today = date.today()
        for prior_active in siblings:
            prior_active.status = TemplateLifecycleStatus.SUPERSEDED
            prior_active.superseded_date = today
            prior_active.save(update_fields=["status", "superseded_date", "updated_at"])
            emit(
                event_type=TemplateEvent.VERSION_SUPERSEDED,
                resource_type="template_version",
                resource_id=str(prior_active.public_id),
                tenant_id=template.tenant_id,
                payload={"superseded_by": str(locked.public_id)},
                **_actor_fields(actor),
            )

        locked.status = TemplateLifecycleStatus.ACTIVE
        locked.effective_date = today
        locked.save(update_fields=["status", "effective_date", "updated_at"])

        template.current_approved_version = locked
        template.lifecycle_status = TemplateLifecycleStatus.ACTIVE
        template.save(update_fields=["current_approved_version", "lifecycle_status", "updated_at"])

        emit(
            event_type=TemplateEvent.VERSION_ACTIVATED,
            resource_type="template_version",
            resource_id=str(locked.public_id),
            tenant_id=template.tenant_id,
            payload={"template": str(template.public_id)},
            **_actor_fields(actor),
        )
        return locked


def supersede(version: TemplateVersion, actor, reason: str = "") -> TemplateVersion:
    """Explicit manual supersession of an active version without an
    immediate replacement (as opposed to the automatic supersession that
    happens inside activate())."""
    with transaction.atomic():
        locked = TemplateVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status != TemplateLifecycleStatus.ACTIVE:
            raise InvalidTransition(f"Cannot supersede version in status '{locked.status}'.")
        locked.status = TemplateLifecycleStatus.SUPERSEDED
        locked.superseded_date = date.today()
        locked.save(update_fields=["status", "superseded_date", "updated_at"])

        template = RegulatoryTemplate.objects.select_for_update().get(pk=locked.template_id)
        if template.current_approved_version_id == locked.pk:
            template.current_approved_version = None
            template.save(update_fields=["current_approved_version", "updated_at"])

        emit(
            event_type=TemplateEvent.VERSION_SUPERSEDED,
            resource_type="template_version",
            resource_id=str(locked.public_id),
            tenant_id=locked.template.tenant_id,
            payload={"reason": reason},
            **_actor_fields(actor),
        )
        return locked


def retire(version: TemplateVersion, actor, reason: str = "") -> TemplateVersion:
    with transaction.atomic():
        locked = TemplateVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status not in (
            TemplateLifecycleStatus.ACTIVE,
            TemplateLifecycleStatus.SUPERSEDED,
        ):
            raise InvalidTransition(f"Cannot retire version in status '{locked.status}'.")
        locked.status = TemplateLifecycleStatus.RETIRED
        locked.save(update_fields=["status", "updated_at"])

        template = RegulatoryTemplate.objects.select_for_update().get(pk=locked.template_id)
        if template.current_approved_version_id == locked.pk:
            template.current_approved_version = None
            template.save(update_fields=["current_approved_version", "updated_at"])

        emit(
            event_type=TemplateEvent.VERSION_RETIRED,
            resource_type="template_version",
            resource_id=str(locked.public_id),
            tenant_id=locked.template.tenant_id,
            payload={"reason": reason},
            **_actor_fields(actor),
        )
        return locked
