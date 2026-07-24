"""Audit event type constants and helper for the FDA data-governance domain."""

from audit.models import AuditEvent


class FdaDataEvent:
    RELEASE_REGISTERED = "fda_data.release.registered"
    FILE_STORED = "fda_data.release.file_stored"
    IMPORT_STARTED = "fda_data.release.import_started"
    SCHEMA_VALIDATED = "fda_data.release.schema_validated"
    ROW_IMPORT_FAILED = "fda_data.row.import_failed"
    MAPPING_PROPOSED = "fda_data.mapping.proposed"
    MAPPING_APPROVED = "fda_data.mapping.approved"
    MAPPING_REJECTED = "fda_data.mapping.rejected"
    RELEASE_SUBMITTED_FOR_REVIEW = "fda_data.release.submitted_for_review"
    RELEASE_APPROVED = "fda_data.release.approved"
    RELEASE_ACTIVATED = "fda_data.release.activated"
    RELEASE_SUPERSEDED = "fda_data.release.superseded"
    RELEASE_REJECTED = "fda_data.release.rejected"
    RECONCILIATION_EXPORTED = "fda_data.reconciliation.exported"


def emit(
    *,
    event_type: str,
    resource_type: str = "fda_data_release",
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
