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


#: Payload keys permitted for the event types corrected in P2.
#:
#: Per event type, not domain-wide. A domain-wide allow-list would silently
#: drop keys the twelve existing document events already record, changing the
#: historical shape of the trail without review. These two start constrained;
#: the rest keep what they were written with.
#:
#: `failure_detail` is deliberately absent. It carries str(exc), which for a
#: parse failure can quote bytes of the document being processed -- exactly the
#: content the audit table must not absorb, since it cannot be redacted later.
_PAYLOAD_ALLOW_LISTS: dict[str, frozenset[str]] = {
    DocumentEvent.PROCESSING_FAILED: frozenset({"failure_code", "retryable", "attempt_count"}),
    DocumentEvent.SCAN_QUEUED: frozenset({"source"}),
}


def _restrict(event_type: str, payload: dict | None) -> dict:
    """Drop anything the event type is not permitted to record.

    Event types with no entry pass through untouched, so this narrows only
    what P2 adds.
    """
    allowed = _PAYLOAD_ALLOW_LISTS.get(event_type)
    if allowed is None:
        return payload or {}
    return {k: v for k, v in (payload or {}).items() if k in allowed}


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
        payload=_restrict(event_type, payload),
        ip_address=ip_address,
    )
