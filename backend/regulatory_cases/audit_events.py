"""Audit for regulatory cases, through the existing AuditEvent system.

No second audit mechanism: this is a thin typed wrapper over `audit.AuditEvent`
exactly as `workflows/audit_events.py` is, with its own allow-list.

**The allow-list is the point.** A case links documents, workflows and
checklists, and their titles and filenames can themselves disclose subject
matter -- what product, what market, what the submission is about. An audit row
has different retention from the resource it describes, so only public IDs and
counts are recorded here. The identifiers resolve to detail for anyone holding
the relevant module permission, which is the correct gate.
"""

from audit.middleware import get_audit_context
from audit.models import AuditEvent


class CaseEvent:
    CREATED = "regulatory_case.created"
    UPDATED = "regulatory_case.updated"
    COMPLETED = "regulatory_case.completed"
    CANCELLED = "regulatory_case.cancelled"

    WORKFLOW_LINKED = "regulatory_case.workflow_linked"
    WORKFLOW_UNLINKED = "regulatory_case.workflow_unlinked"
    DOCUMENT_LINKED = "regulatory_case.document_linked"
    DOCUMENT_UNLINKED = "regulatory_case.document_unlinked"
    CHECKLIST_LINKED = "regulatory_case.checklist_linked"
    CHECKLIST_UNLINKED = "regulatory_case.checklist_unlinked"


#: Anything not named here cannot be written. Deliberately absent: document
#: title, original_filename, sha256, scan status, workflow title, checklist
#: question or response content, and owner email -- every one of which is either
#: user-supplied or discloses the subject of the case.
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "case_public_id",
        "case_number",
        "from_status",
        "to_status",
        "fields_changed",
        "reason_supplied",
        "reason_length",
        "link_public_id",
        "link_kind",
        "target_public_id",
    }
)


def _filtered(payload: dict | None) -> dict:
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
    """Write one immutable audit row for a case action.

    `resource_id` is a public_id, never an internal PK.
    """
    ctx = get_audit_context()
    AuditEvent.objects.create(
        actor_id=actor.pk if actor is not None and actor.is_authenticated else None,
        actor_email=actor.email if actor is not None and actor.is_authenticated else "",
        tenant_id=tenant_id,
        event_type=event_type,
        resource_type="regulatory_case",
        resource_id=str(resource_id),
        payload=_filtered(payload),
        ip_address=ctx.get("ip_address"),
    )
