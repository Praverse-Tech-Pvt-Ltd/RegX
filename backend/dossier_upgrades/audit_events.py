"""Audit for dossier upgrades, through the existing AuditEvent system.

A thin typed wrapper with its own allow-list, exactly as every domain app before
it. **The allow-list is the point**: a section title, a plan note and a blueprint
name are free text describing what a tenant is submitting, and an audit row has
different retention from the plan it describes.
"""

from audit.middleware import get_audit_context
from audit.models import AuditEvent


class UpgradeEvent:
    PLAN_CREATED = "dossier_upgrade.plan_created"
    PLAN_REGENERATED = "dossier_upgrade.plan_regenerated"
    ITEM_ACCEPTED = "dossier_upgrade.item_accepted"
    ITEM_REJECTED = "dossier_upgrade.item_rejected"
    PLAN_MARKED_READY = "dossier_upgrade.plan_marked_ready"
    PLAN_APPLIED = "dossier_upgrade.plan_applied"
    PLAN_CANCELLED = "dossier_upgrade.plan_cancelled"


#: Anything not named here cannot be written. Deliberately absent: section
#: title, description, notes, blueprint name, plan notes, and the VALUES of any
#: changed field. `section_code` is present for the same reason it is in the
#: dossier allow-list -- short organisational metadata a reviewer needs to
#: follow a trail.
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "plan_public_id",
        "item_public_id",
        "dossier_public_id",
        "blueprint_public_id",
        "source_version_public_id",
        "target_version_public_id",
        "application_public_id",
        "source_version_number",
        "target_version_number",
        "section_public_id",
        "section_code",
        "change_type",
        "field_name",
        "from_status",
        "to_status",
        "total_items",
        "actionable_items",
        "conflict_items",
        "accepted_items",
        "rejected_items",
        "blocked_items",
        "sections_added",
        "sections_retired",
        "sections_updated",
        "blocking_reason",
        "fingerprint_matched",
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
        resource_type="dossier_upgrade",
        resource_id=str(resource_id),
        payload=_filtered(payload),
        ip_address=ctx.get("ip_address"),
    )
