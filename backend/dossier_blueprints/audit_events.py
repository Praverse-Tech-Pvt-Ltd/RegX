"""Audit for dossier blueprints, through the existing AuditEvent system.

No second audit mechanism -- a thin typed wrapper with its own allow-list,
exactly as `submission_dossiers/audit_events.py`.

**The allow-list is the point.** A blueprint name, a section title and a
description are free text that describes what a tenant is submitting and to
whom. An audit row has different retention from the blueprint it describes, so
only identifiers, version numbers, counts, statuses and changed field NAMES are
recorded.
"""

from audit.middleware import get_audit_context
from audit.models import AuditEvent


class BlueprintEvent:
    CREATED = "dossier_blueprint.created"
    UPDATED = "dossier_blueprint.updated"
    ARCHIVED = "dossier_blueprint.archived"

    VERSION_CREATED = "dossier_blueprint_version.created"
    VERSION_ACTIVATED = "dossier_blueprint_version.activated"
    VERSION_RETIRED = "dossier_blueprint_version.retired"

    SECTION_CREATED = "dossier_blueprint_section.created"
    SECTION_UPDATED = "dossier_blueprint_section.updated"
    SECTION_REORDERED = "dossier_blueprint_section.reordered"
    SECTION_RETIRED = "dossier_blueprint_section.retired"

    INSTANTIATED = "dossier_blueprint.instantiated"


#: Anything not named here cannot be written. Deliberately absent: blueprint
#: name, section title, description, notes, and the VALUES of any changed field.
#: `section_code` is present for the same reason it is in the dossier allow-list
#: -- it is short organisational metadata a reviewer needs to follow a trail --
#: and `blueprint_name` is deliberately NOT, because it is free text a tenant
#: may put a product or an authority into.
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "blueprint_public_id",
        "version_public_id",
        "section_public_id",
        "parent_public_id",
        "supersedes_public_id",
        "instantiation_public_id",
        "dossier_public_id",
        "case_public_id",
        "section_code",
        "version_number",
        "from_status",
        "to_status",
        "from_sequence",
        "to_sequence",
        "section_count",
        "retired_version_public_id",
        "fields_changed",
        "required",
        "notes_supplied",
        "notes_length",
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
        resource_type="dossier_blueprint",
        resource_id=str(resource_id),
        payload=_filtered(payload),
        ip_address=ctx.get("ip_address"),
    )
