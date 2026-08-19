"""Workflow audit event types and emitter.

Same shape as `documents/audit_events.py`. Writes to the immutable
`audit.AuditEvent` table.

Audit events and operational logs are separate systems: AuditEvent is the
regulated record, structured logs are diagnostics. Nothing here writes to a
logger, and `docs/OPERATIONAL_LOGGING.md` explains why the two must not merge.
"""

from audit.middleware import get_audit_context
from audit.models import AuditEvent


class WorkflowEvent:
    CREATED = "workflow.created"
    UPDATED = "workflow.updated"
    SUBMITTED = "workflow.submitted"
    REVIEW_STARTED = "workflow.review_started"
    APPROVED = "workflow.approved"
    REJECTED = "workflow.rejected"
    CANCELLED = "workflow.cancelled"
    RETURNED_TO_DRAFT = "workflow.returned_to_draft"
    ASSIGNED = "workflow.assigned"
    UNASSIGNED = "workflow.unassigned"


#: Action -> event type, for transitions driven through the service layer.
ACTION_EVENTS = {
    "submit": WorkflowEvent.SUBMITTED,
    "begin_review": WorkflowEvent.REVIEW_STARTED,
    "approve": WorkflowEvent.APPROVED,
    "reject": WorkflowEvent.REJECTED,
    "cancel": WorkflowEvent.CANCELLED,
    "return_to_draft": WorkflowEvent.RETURNED_TO_DRAFT,
}

#: Payload keys this domain is permitted to record. An allow-list, not a filter:
#: anything not named here never reaches the audit row. Governed content,
#: credentials, tokens and request bodies are structurally excluded because no
#: caller can add a key.
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "from_state",
        "to_state",
        "reason_supplied",
        "reason_length",
        "assigned_to_public_id",
        "previous_assignee_public_id",
        "transition_public_id",
        "fields_changed",
        "title_length",
        "due_at_set",
    }
)


def _allowed(payload: dict | None) -> dict:
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in _ALLOWED_PAYLOAD_KEYS}


def emit(
    *,
    event_type: str,
    resource_id: str = "",
    actor=None,
    tenant_id: int | None = None,
    payload: dict | None = None,
) -> None:
    """Write one immutable audit row for a workflow action.

    `resource_id` is a public_id, never an internal PK. The reason *text* is
    never recorded here -- only whether one was supplied and how long it was.
    The text itself lives on the WorkflowTransition row, which is the
    append-only record for it.
    """
    ctx = get_audit_context()
    AuditEvent.objects.create(
        actor_id=actor.pk if actor is not None and actor.is_authenticated else None,
        actor_email=actor.email if actor is not None and actor.is_authenticated else "",
        tenant_id=tenant_id,
        event_type=event_type,
        resource_type="workflow_item",
        resource_id=str(resource_id),
        payload=_allowed(payload),
        ip_address=ctx.get("ip_address"),
    )
