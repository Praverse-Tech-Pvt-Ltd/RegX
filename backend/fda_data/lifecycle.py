"""
FDA data-source release lifecycle: transactional state transitions.

    registered -> staged -> validated -> under_review -> approved -> active
    under_review -> rejected

Activation supersedes (never deletes) any prior active release for the
same dataset_type, transactionally, exactly mirroring
templates_registry.lifecycle.activate(). No transition here is ever
triggered automatically by the import pipeline -- activation is always a
distinct, explicit, permission-gated, audited action.
"""

from __future__ import annotations

from django.db import transaction

from .audit_events import FdaDataEvent, emit
from .models import FDADataSourceRelease, FDAReleaseStatus


class InvalidTransition(Exception):
    pass


def _actor_fields(user):
    return {"actor_id": getattr(user, "id", None), "actor_email": getattr(user, "email", "")}


def submit_for_review(
    release: FDADataSourceRelease, actor, extra_payload: dict | None = None
) -> FDADataSourceRelease:
    with transaction.atomic():
        locked = FDADataSourceRelease.objects.select_for_update().get(pk=release.pk)
        if locked.status not in (
            FDAReleaseStatus.REGISTERED,
            FDAReleaseStatus.STAGED,
            FDAReleaseStatus.VALIDATED,
        ):
            raise InvalidTransition(
                f"Cannot submit release in status '{locked.status}' for review."
            )
        locked.status = FDAReleaseStatus.UNDER_REVIEW
        locked.save(update_fields=["status", "updated_at"])
        emit(
            event_type=FdaDataEvent.RELEASE_SUBMITTED_FOR_REVIEW,
            resource_id=str(locked.public_id),
            payload={"dataset_type": locked.dataset_type, **(extra_payload or {})},
            **_actor_fields(actor),
        )
        return locked


def approve(release: FDADataSourceRelease, approver, notes: str = "") -> FDADataSourceRelease:
    """Segregation of duties: the approver must not be the release's importer."""
    with transaction.atomic():
        locked = FDADataSourceRelease.objects.select_for_update().get(pk=release.pk)
        if locked.status != FDAReleaseStatus.UNDER_REVIEW:
            raise InvalidTransition(f"Cannot approve release in status '{locked.status}'.")
        if locked.imported_by_id is not None and locked.imported_by_id == getattr(
            approver, "id", None
        ):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("An approver cannot approve a release they imported themselves.")
        from django.utils import timezone

        locked.status = FDAReleaseStatus.APPROVED
        locked.approved_by = approver
        locked.approved_at = timezone.now()
        if notes:
            locked.notes = (locked.notes + "\n" if locked.notes else "") + notes
        locked.save(update_fields=["status", "approved_by", "approved_at", "notes", "updated_at"])
        emit(
            event_type=FdaDataEvent.RELEASE_APPROVED,
            resource_id=str(locked.public_id),
            payload={"dataset_type": locked.dataset_type},
            **_actor_fields(approver),
        )
        return locked


def reject(release: FDADataSourceRelease, actor, reason: str = "") -> FDADataSourceRelease:
    with transaction.atomic():
        locked = FDADataSourceRelease.objects.select_for_update().get(pk=release.pk)
        if locked.status != FDAReleaseStatus.UNDER_REVIEW:
            raise InvalidTransition(f"Cannot reject release in status '{locked.status}'.")
        locked.status = FDAReleaseStatus.REJECTED
        if reason:
            locked.notes = (locked.notes + "\n" if locked.notes else "") + reason
        locked.save(update_fields=["status", "notes", "updated_at"])
        emit(
            event_type=FdaDataEvent.RELEASE_REJECTED,
            resource_id=str(locked.public_id),
            payload={"reason": reason},
            **_actor_fields(actor),
        )
        return locked


def activate(release: FDADataSourceRelease, actor) -> FDADataSourceRelease:
    """Approved -> Active. Supersedes any prior active release for the same
    dataset_type inside the same transaction. Never invoked by the import
    pipeline itself."""
    with transaction.atomic():
        locked = FDADataSourceRelease.objects.select_for_update().get(pk=release.pk)
        if locked.status != FDAReleaseStatus.APPROVED:
            raise InvalidTransition(
                f"Cannot activate release in status '{locked.status}'; only an approved "
                "release may be activated."
            )
        siblings = FDADataSourceRelease.objects.select_for_update().filter(
            dataset_type=locked.dataset_type, status=FDAReleaseStatus.ACTIVE
        )
        from django.utils import timezone

        now = timezone.now()
        for prior_active in siblings:
            prior_active.status = FDAReleaseStatus.SUPERSEDED
            prior_active.superseded_by_release = locked
            prior_active.save(update_fields=["status", "superseded_by_release", "updated_at"])
            emit(
                event_type=FdaDataEvent.RELEASE_SUPERSEDED,
                resource_id=str(prior_active.public_id),
                payload={"superseded_by": str(locked.public_id)},
                **_actor_fields(actor),
            )

        locked.status = FDAReleaseStatus.ACTIVE
        locked.activated_by = actor
        locked.activated_at = now
        locked.save(update_fields=["status", "activated_by", "activated_at", "updated_at"])

        # An SPL terminology release changes the controlled vocabulary only
        # here, once approved and activated -- never when it is loaded.
        from .spl_terminology import TERMINOLOGY_DATASET_TYPES, apply_on_activation

        if locked.dataset_type in TERMINOLOGY_DATASET_TYPES:
            apply_on_activation(locked)
        emit(
            event_type=FdaDataEvent.RELEASE_ACTIVATED,
            resource_id=str(locked.public_id),
            payload={"dataset_type": locked.dataset_type},
            **_actor_fields(actor),
        )
        return locked
