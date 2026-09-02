"""Audit for submission packages, through the existing AuditEvent system.

A thin typed wrapper with its own allow-list, exactly as every domain app before
it. **The allow-list is the point**: a package name, a document title, an
uploaded filename and a dossier section title are free text describing what a
tenant is preparing to submit, and an audit row has different retention from the
package it describes.

Checksums and public ids travel because they are how a reviewer follows a trail
and they identify without describing. Filenames do not: a filename is content.
"""

from audit.middleware import get_audit_context
from audit.models import AuditEvent


class PackageEvent:
    CREATED = "submission_package.created"
    UPDATED = "submission_package.updated"
    ENTRY_ADDED = "submission_package.entry_added"
    ENTRY_REMOVED = "submission_package.entry_removed"
    ENTRY_REORDERED = "submission_package.entry_reordered"
    SUBMITTED_FOR_REVIEW = "submission_package.submitted_for_review"
    RETURNED_TO_DRAFT = "submission_package.returned_to_draft"
    FROZEN = "submission_package.frozen"
    CANCELLED = "submission_package.cancelled"
    CLONED = "submission_package.cloned"
    EXPORTED = "submission_package.exported"


#: Anything not named here cannot be written. Deliberately absent: package name
#: and description, document title, original filename, export filename, dossier
#: section title and code, and every free-text field on any of them.
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "package_public_id",
        "source_package_public_id",
        "entry_public_id",
        "snapshot_public_id",
        "case_public_id",
        "document_version_public_id",
        "manifest_checksum",
        "entry_count",
        "total_bytes",
        "revision_number",
        "sequence",
        "status",
        "export_format",
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
        resource_type="submission_package",
        resource_id=str(resource_id),
        payload=_filtered(payload),
        ip_address=ctx.get("ip_address"),
    )
