"""Audit event type constants and helper for the formulations domain."""

from audit.models import AuditEvent


class FormulationEvent:
    REFERENCE_PRODUCT_SELECTED = "formulations.product.reference_selected"
    PRODUCT_CREATED = "formulations.product.created"
    FORMULATION_VERSION_CREATED = "formulations.version.created"
    COMPONENT_ADDED = "formulations.component.added"
    COMPONENT_CHANGED = "formulations.component.changed"
    DOSING_REGIMEN_CHANGED = "formulations.dosing_regimen.changed"
    VERSION_SUBMITTED_FOR_REVIEW = "formulations.version.submitted_for_review"
    VERSION_RETURNED = "formulations.version.returned"
    VERSION_REJECTED = "formulations.version.rejected"
    VERSION_APPROVED = "formulations.version.approved"
    VERSION_SUPERSEDED = "formulations.version.superseded"


def emit(
    *,
    event_type: str,
    resource_type: str = "formulation",
    resource_id: str = "",
    actor_id: int | None = None,
    actor_email: str = "",
    tenant_id: int | None = None,
    payload: dict | None = None,
) -> None:
    AuditEvent.objects.create(
        actor_id=actor_id,
        actor_email=actor_email,
        tenant_id=tenant_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {},
    )
