"""Audit event type constants and helper for the template registry domain."""

from audit.models import AuditEvent


class TemplateEvent:
    SOURCE_PACKAGE_REGISTERED = "template.source_package.registered"
    MIGRATION_BATCH_STARTED = "template.migration_batch.started"
    MIGRATION_BATCH_COMPLETED = "template.migration_batch.completed"
    MIGRATION_BATCH_FAILED = "template.migration_batch.failed"
    SOURCE_RECORD_EXTRACTED = "template.source_record.extracted"
    SOURCE_RECORD_EXCLUDED = "template.source_record.excluded"
    NORMALIZATION_APPLIED = "template.normalization.applied"
    DUPLICATE_CANDIDATE_CREATED = "template.duplicate_candidate.created"
    DUPLICATE_CANDIDATE_RESOLVED = "template.duplicate_candidate.resolved"
    VERSION_IMPORTED = "template.version.imported"
    VERSION_SUBMITTED_FOR_REVIEW = "template.version.submitted_for_review"
    VERSION_RETURNED = "template.version.returned"
    VERSION_APPROVED = "template.version.approved"
    VERSION_REJECTED = "template.version.rejected"
    VERSION_ACTIVATED = "template.version.activated"
    VERSION_SUPERSEDED = "template.version.superseded"
    VERSION_RETIRED = "template.version.retired"


def emit(
    *,
    event_type: str,
    resource_type: str = "template",
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
