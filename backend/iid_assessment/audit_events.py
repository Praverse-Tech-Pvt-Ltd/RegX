"""Audit event type constants and helper for the IID assessment domain."""

from audit.models import AuditEvent


class IidAssessmentEvent:
    MATCH_PREVIEW_GENERATED = "iid_assessment.match_preview.generated"
    RECORD_SELECTED = "iid_assessment.precedent_record.selected"
    UNIT_CONVERSION_PERFORMED = "iid_assessment.unit_conversion.performed"
    UNIT_CONVERSION_BLOCKED = "iid_assessment.unit_conversion.blocked"
    CALCULATION_GENERATED = "iid_assessment.calculation.generated"
    CALCULATION_BLOCKED = "iid_assessment.calculation.blocked"
    SNAPSHOT_CREATED = "iid_assessment.snapshot.created"
    OVERRIDE_APPLIED = "iid_assessment.override.applied"


def emit(
    *,
    event_type: str,
    resource_type: str = "iid_assessment",
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
