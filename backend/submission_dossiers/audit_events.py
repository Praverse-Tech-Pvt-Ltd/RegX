"""Audit for submission dossiers, through the existing AuditEvent system.

No second audit mechanism -- a thin typed wrapper with its own allow-list,
exactly as `regulatory_cases/audit_events.py` and `workflows/audit_events.py`.

**The allow-list is the point.** Section titles, descriptions, notes and blocker
text are free-form and describe the submission: what product, what deficiency,
what the authority asked. An audit row has different retention from the section
it describes, so only identifiers, statuses and changed field NAMES are recorded.
"""

from audit.middleware import get_audit_context
from audit.models import AuditEvent


class DossierEvent:
    CREATED = "submission_dossier.created"
    UPDATED = "submission_dossier.updated"
    COMPLETED = "submission_dossier.completed"
    CANCELLED = "submission_dossier.cancelled"

    SECTION_CREATED = "dossier_section.created"
    SECTION_UPDATED = "dossier_section.updated"
    SECTION_REORDERED = "dossier_section.reordered"
    SECTION_COMPLETED = "dossier_section.completed"
    SECTION_NOT_APPLICABLE = "dossier_section.not_applicable"
    SECTION_RETIRED = "dossier_section.retired"

    BLOCKER_CREATED = "dossier_section.blocker_created"
    BLOCKER_RESOLVED = "dossier_section.blocker_resolved"

    DOCUMENT_LINKED = "dossier_section.document_linked"
    DOCUMENT_UNLINKED = "dossier_section.document_unlinked"
    WORKFLOW_LINKED = "dossier_section.workflow_linked"
    WORKFLOW_UNLINKED = "dossier_section.workflow_unlinked"
    CHECKLIST_LINKED = "dossier_section.checklist_linked"
    CHECKLIST_UNLINKED = "dossier_section.checklist_unlinked"


#: Anything not named here cannot be written. Deliberately absent: section
#: title, description, notes, blocker title and description, document title,
#: filename, workflow title, checklist detail, owner email, and the VALUES of
#: any changed field.
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "dossier_public_id",
        "section_public_id",
        "parent_public_id",
        "blocker_public_id",
        "link_public_id",
        "link_kind",
        "target_public_id",
        "section_code",
        "from_status",
        "to_status",
        "from_readiness",
        "to_readiness",
        "readiness_reason",
        "from_sequence",
        "to_sequence",
        "severity",
        "fields_changed",
        "reason_supplied",
        "reason_length",
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
    """Write one immutable audit row. `resource_id` is a public_id, never a PK."""
    ctx = get_audit_context()
    AuditEvent.objects.create(
        actor_id=actor.pk if actor is not None and actor.is_authenticated else None,
        actor_email=actor.email if actor is not None and actor.is_authenticated else "",
        tenant_id=tenant_id,
        event_type=event_type,
        resource_type="submission_dossier",
        resource_id=str(resource_id),
        payload=_filtered(payload),
        ip_address=ctx.get("ip_address"),
    )
