"""Audit event type constants and helpers for the document domain."""

from audit.models import AuditEvent


class DocumentEvent:
    UPLOAD_STARTED = "document.upload.started"
    UPLOAD_VALIDATED = "document.upload.validated"
    UPLOAD_REJECTED = "document.upload.rejected"
    SCAN_QUEUED = "document.scan.queued"
    SCAN_COMPLETE = "document.scan.complete"
    SCAN_INFECTED = "document.scan.infected"
    SCAN_FAILED = "document.scan.failed"
    QUARANTINED = "document.quarantined"
    PROCESSING_STARTED = "document.processing.started"
    PROCESSING_COMPLETE = "document.processing.complete"
    PROCESSING_FAILED = "document.processing.failed"
    VERSION_CREATED = "document.version.created"
    DOCUMENT_CREATED = "document.created"
    DOCUMENT_ARCHIVED = "document.archived"
    DOCUMENT_RESTORED = "document.restored"
    DUPLICATE_DETECTED = "document.duplicate.detected"


def emit(
    *,
    event_type: str,
    resource_type: str = "document",
    resource_id: str = "",
    actor_id: int | None = None,
    actor_email: str = "",
    tenant_id: int | None = None,
    payload: dict | None = None,
    ip_address: str | None = None,
) -> None:
    AuditEvent.objects.create(
        actor_id=actor_id,
        actor_email=actor_email,
        tenant_id=tenant_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {},
        ip_address=ip_address,
    )
