"""Audit for external integrations, through the existing AuditEvent system.

A thin typed wrapper with its own allow-list, exactly as every domain app before
it. **The allow-list matters more here than anywhere.** This app handles a
credential and talks to a system nobody in RegX controls, and a remote endpoint's
error body is attacker-influenced text. An audit row is long-lived, widely
readable and rarely re-read carefully -- precisely the wrong place for either.

So: public ids, checksums, enumerated codes, counts and statuses travel. A
secret value, an environment variable's contents, a remote response body, a
remote header, a full URL, a filename and a raw exception string do not. The
connector's *name* does not travel either: it is free text a tenant wrote, and
the connector's public id identifies it without describing it.

Nothing here is a regulatory record of a submission. `external_execution.succeeded`
means an endpoint accepted bytes.
"""

from audit.middleware import get_audit_context
from audit.models import AuditEvent


class IntegrationEvent:
    CONNECTOR_CREATED = "external_connector.created"
    CONNECTOR_UPDATED = "external_connector.updated"
    CONNECTOR_ENABLED = "external_connector.enabled"
    CONNECTOR_DISABLED = "external_connector.disabled"
    CONNECTOR_ARCHIVED = "external_connector.archived"
    CONNECTOR_TESTED = "external_connector.tested"

    EXECUTION_CREATED = "external_execution.created"
    EXECUTION_STARTED = "external_execution.started"
    EXECUTION_SUCCEEDED = "external_execution.succeeded"
    EXECUTION_FAILED = "external_execution.failed"
    EXECUTION_CANCELLED = "external_execution.cancelled"

    OBJECT_LINKED = "external_object.linked"


#: Anything not named here cannot be written. Deliberately absent: connector
#: name and description, credential reference name, base URL, any header, any
#: remote response body or header, any filename, any exception text.
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "connector_public_id",
        "connector_type",
        "execution_public_id",
        "operation",
        "status",
        "resource_type",
        "resource_public_id",
        "snapshot_public_id",
        "manifest_checksum",
        "document_public_id",
        "document_version_public_id",
        "external_object_id",
        "error_code",
        "attempt",
        "attempt_count",
        "configuration_version",
        "bytes_transferred",
        "entry_count",
        "http_status",
        "latency_ms",
        "reachable",
        "authenticated",
        "remote_checksum_verified",
        "correlation_id",
        "test_status",
    }
)

#: Even an allow-listed value is bounded. `external_object_id` is remote input,
#: and a remote system that returns a megabyte of "id" should cost one truncated
#: audit row, not a megabyte of audit storage per attempt.
_MAX_VALUE_LENGTH = 255


def _filtered(payload: dict | None) -> dict:
    if not payload:
        return {}
    cleaned = {}
    for key, value in payload.items():
        if key not in _ALLOWED_PAYLOAD_KEYS:
            continue
        if isinstance(value, str) and len(value) > _MAX_VALUE_LENGTH:
            value = value[:_MAX_VALUE_LENGTH]
        cleaned[key] = value
    return cleaned


def emit(
    *,
    event_type: str,
    resource_id: str = "",
    actor=None,
    tenant_id: int | None = None,
    payload: dict | None = None,
) -> None:
    """Write one immutable audit row. `resource_id` is a public_id, never a PK."""
    ctx = get_audit_context()
    AuditEvent.objects.create(
        actor_id=actor.pk if actor is not None and actor.is_authenticated else None,
        actor_email=actor.email if actor is not None and actor.is_authenticated else "",
        tenant_id=tenant_id,
        event_type=event_type,
        resource_type="external_integration",
        resource_id=str(resource_id),
        payload=_filtered(payload),
        ip_address=ctx.get("ip_address"),
    )
