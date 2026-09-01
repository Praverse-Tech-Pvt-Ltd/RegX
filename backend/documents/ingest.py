"""The one way bytes become a Document in RegX.

Extracted from `DocumentListCreateView.post`, which was the only implementation
of the upload pipeline and therefore the only place it was correct. Milestone 14
adds a second way for bytes to arrive -- fetched from an external connector --
and two implementations of "validate, hash, store, version, scan" would drift.
The one that drifted would be the one nobody was looking at.

So there is one function, and the connector calls it. There is no "trusted
source" parameter and no way to skip a step: a caller supplies a file object and
gets back a `DocumentVersion` that has been through validation, checksumming and
storage, with a scan queued. A caller that wants less than that does not have an
option.

WHAT THE CALLER CANNOT SKIP
---------------------------
Filename and size rules, declared-vs-detected MIME agreement, Office container
and macro inspection, archive checks, SHA-256 over the real bytes, storage that
verifies that checksum, and the malware scan. The scan is queued here, in the
same transaction's wake, and a version starts life `PENDING` -- the document
platform's own rules then decide what may be done with a version that has not
been cleared. Nothing about arriving through a connector changes any of it.
"""

from __future__ import annotations

import os
import re

from django.db import transaction

from .audit_events import DocumentEvent, emit
from .models import Document, DocumentDuplicateLink, DocumentVersion
from .storage import compute_sha256, get_storage_backend
from .tasks import scan_document_version
from .validators import validate_upload


def normalize_filename(filename: str) -> str:
    """The stored, normalised form of an uploaded name."""
    base = os.path.basename(filename)
    safe = re.sub(r"[^\w.\-]", "_", base)
    return safe[:255]


@transaction.atomic
def _persist(
    *,
    tenant,
    title,
    document_type,
    filename,
    declared_mime,
    validation_meta,
    file_obj,
    sha256,
    actor,
):
    storage = get_storage_backend()

    document = Document.objects.create(
        tenant=tenant, title=title, document_type=document_type, created_by=actor
    )

    # Duplicate detection stays inside the tenant. A checksum match across
    # tenants would tell one tenant something about another's content.
    existing_duplicate = (
        DocumentVersion.objects.for_tenant(tenant).filter(sha256_checksum=sha256).first()
    )

    storage_key = storage.store(
        tenant_id=tenant.pk,
        file_obj=file_obj,
        expected_sha256=sha256,
        content_type=validation_meta.get("detected_mime_type", declared_mime),
        original_filename=filename,
    )

    version = DocumentVersion.objects.create(
        document=document,
        version_number=1,
        original_filename=filename,
        normalized_filename=normalize_filename(filename),
        extension=validation_meta["extension"],
        declared_mime_type=declared_mime,
        detected_mime_type=validation_meta.get("detected_mime_type", ""),
        size_bytes=validation_meta["size_bytes"],
        sha256_checksum=sha256,
        storage_key=storage_key,
        uploaded_by=actor,
    )

    document.current_version = version
    document.save(update_fields=["current_version"])

    if existing_duplicate:
        DocumentDuplicateLink.objects.get_or_create(
            tenant=tenant,
            source_version=version,
            matching_version=existing_duplicate,
            defaults={"checksum": sha256, "relationship_type": "exact"},
        )
        emit(
            event_type=DocumentEvent.DUPLICATE_DETECTED,
            resource_id=str(version.public_id),
            tenant_id=tenant.pk,
            payload={"matching_version": str(existing_duplicate.public_id)},
        )

    return document, version


def ingest_new_document(
    *,
    tenant,
    actor,
    file_obj,
    filename: str,
    declared_mime: str,
    title: str,
    document_type: str,
    ip_address: str | None = None,
):
    """Validate, store, version and queue a scan. Returns `(document, version)`.

    Raises `validators.UploadValidationError` when the content is refused; the
    caller decides how to report that, and both callers emit
    `document.upload.rejected` before doing so.
    """
    validation_meta = validate_upload(
        file_obj=file_obj, filename=filename, declared_mime=declared_mime
    )
    sha256 = compute_sha256(file_obj)

    document, version = _persist(
        tenant=tenant,
        title=title,
        document_type=document_type,
        filename=filename,
        declared_mime=declared_mime,
        validation_meta=validation_meta,
        file_obj=file_obj,
        sha256=sha256,
        actor=actor,
    )

    emit(
        event_type=DocumentEvent.DOCUMENT_CREATED,
        resource_id=str(document.public_id),
        actor_id=actor.pk,
        actor_email=actor.email,
        tenant_id=tenant.pk,
        ip_address=ip_address,
    )
    emit(
        event_type=DocumentEvent.VERSION_CREATED,
        resource_id=str(version.public_id),
        actor_id=actor.pk,
        actor_email=actor.email,
        tenant_id=tenant.pk,
        payload={"version_number": 1, "document_public_id": str(document.public_id)},
        ip_address=ip_address,
    )

    # Queued ON COMMIT, so the worker cannot look up a row that is not there.
    #
    # `_persist` closes its own transaction, so in the ordinary call this is
    # equivalent to dispatching inline -- `on_commit` outside a transaction
    # runs immediately. It matters when a *caller* holds a transaction, which
    # is an ordinary thing to do and which this function, being a shared entry
    # point, cannot see. Measured before this change: dispatch happened once
    # before commit and zero times after.
    #
    # The scan itself is not optional and not conditional on where the bytes
    # came from: a connector is a source of untrusted content exactly as a
    # browser is.
    transaction.on_commit(lambda: scan_document_version.delay(version.pk, tenant.pk))

    return document, version
