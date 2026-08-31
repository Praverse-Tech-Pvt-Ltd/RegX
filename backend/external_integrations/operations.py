"""The two things a connector can actually do.

Each operation is a named, bounded routine with its own validated payload. There
is no generic "call this URL with this body" operation, because that is not an
integration framework, it is a proxy that authenticated tenant users can point
anywhere.

IMPORT_DOCUMENT
    Fetch bytes from the connector and hand them to `documents.ingest`, which is
    the *same* function the upload endpoint calls. Validation, MIME detection,
    Office and archive inspection, checksum, storage and the malware scan all
    happen because that function does them. There is no connector-shaped way to
    skip any of it: this module does not have the option.

PUSH_FROZEN_PACKAGE
    Ask Milestone 13 to produce the archive for an exact frozen snapshot, then
    stream it. The archive is built by `submission_packages.export`, which
    verifies every file against the frozen manifest; if it refuses, nothing is
    sent. This module never reconstructs a package, never selects "the latest
    revision", and never touches a package that is not FROZEN.

WHAT IS NOT CLAIMED
-------------------
A 2xx means the endpoint accepted the bytes. It does not mean the remote system
stored them, indexed them, or will still have them tomorrow, and none of those
things are recorded as if they were true. Remote checksum comparison happens only
when the endpoint actually returns a checksum; when it does not,
`remote_checksum_verified` is `False` and stays that way.
"""

from __future__ import annotations

import hashlib
import tempfile

from .netpolicy import DestinationRefused, build_url
from .transport import TransportError, TransportErrorCode, perform_request


#: A ceiling on an imported document, independent of the connector's response
#: limit. Taken from the document platform's own upload limit rather than
#: chosen here: reading far more than the platform will accept means a
#: hostile endpoint can make the worker do work that is thrown away, and two
#: numbers that are supposed to agree would drift.
def max_import_bytes() -> int:
    from django.conf import settings

    return int(getattr(settings, "DOCUMENT_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))


class OperationError(Exception):
    """An operation failed, with a safe enumerated code."""

    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class OperationErrorCode:
    PAYLOAD_INVALID = "PAYLOAD_INVALID"
    PACKAGE_NOT_FROZEN = "PACKAGE_NOT_FROZEN"
    PACKAGE_INTEGRITY_FAILED = "PACKAGE_INTEGRITY_FAILED"
    PACKAGE_MISSING = "PACKAGE_MISSING"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"


# ---------------------------------------------------------------------------
# IMPORT_DOCUMENT
# ---------------------------------------------------------------------------
def run_import_document(*, execution, connector, config, credential_reference, actor, tenant):
    """Fetch one remote object and turn it into a Document, the normal way."""
    from documents.ingest import ingest_new_document
    from documents.models import DocumentType
    from documents.validators import UploadValidationError

    from .secrets import SecretUnavailable, auth_headers

    payload = execution.request_summary or {}
    relative_path = payload.get("relative_path") or ""
    filename = payload.get("external_object_id") or ""
    title = payload.get("title") or filename or "Imported document"
    # Required and constrained by the payload schema -- and checked again
    # here, for the same reason the configuration is: a stored summary is
    # still a stored value, and this function is reachable from a task, a
    # retry and any future caller that did not go through the serializer.
    #
    # No fallback. A guessed type would be a claim about content this app
    # never inspected, and `objects.create()` would store the guess without
    # complaint because Django does not enforce `choices` there.
    document_type = payload.get("document_type")
    if document_type not in set(DocumentType.values):
        raise OperationError(OperationErrorCode.PAYLOAD_INVALID)

    try:
        url = build_url(
            base_url=config["base_url"],
            allowed_path_prefix=config["allowed_path_prefix"],
            relative_path=relative_path,
        )
    except DestinationRefused as exc:
        raise OperationError(exc.code) from None

    try:
        headers = auth_headers(connector, credential_reference)
    except SecretUnavailable as exc:
        raise OperationError(TransportErrorCode.CREDENTIAL_UNAVAILABLE) from exc

    # Streamed to a temporary file, never held in memory: an imported document
    # can be as large as the document platform allows, and holding one in RAM to
    # serve one execution is how a worker dies.
    handle = tempfile.NamedTemporaryFile(suffix=".bin")
    try:
        response = perform_request(
            connector=connector,
            configuration=config,
            method="GET",
            url=url,
            headers=headers,
            sink=handle,
            max_response_bytes=min(config["max_response_bytes"], max_import_bytes()),
        )
        handle.flush()
        size = handle.tell()
        if size <= 0:
            raise OperationError(OperationErrorCode.EMPTY_RESPONSE)
        handle.seek(0)

        # The temporary file itself goes to `ingest`, not a copy of its
        # contents. Everything downstream -- the validators, the checksum,
        # the storage backend -- reads with `seek`/`read` in chunks, so
        # nothing needs the bytes in memory and nothing gets them there.
        #
        # This previously built a `SimpleUploadedFile` from `handle.read()`,
        # which materialised the whole import in the worker and made the
        # temporary file pointless. Streaming is the reason it exists.
        safe_name = _safe_filename(filename)
        declared_mime = _declared_mime(payload, safe_name)

        try:
            document, version = ingest_new_document(
                tenant=tenant,
                actor=actor,
                file_obj=handle,
                filename=safe_name,
                declared_mime=declared_mime,
                title=title,
                document_type=document_type,
            )
        except UploadValidationError as exc:
            # The document platform refused the content. That is the pipeline
            # working, so the execution fails with a code and no document is
            # created -- and this is not retryable, because the same bytes will
            # be refused the same way.
            raise OperationError(OperationErrorCode.DOCUMENT_REJECTED) from exc

        return {
            "http_status": response.status,
            "bytes_transferred": size,
            "latency_ms": response.latency_ms,
            "external_reference": response.external_reference or filename,
            "document_public_id": str(document.public_id),
            "document_version_public_id": str(version.public_id),
            "external_object_id": filename,
            "remote_checksum_verified": False,
        }
    finally:
        handle.close()


def _declared_mime(payload: dict, filename: str) -> str:
    """The content type to declare for fetched bytes.

    A browser sets this from the file it is uploading, so an import does the
    same from the object's name. `application/octet-stream` is deliberately
    NOT a fallback: the document platform refuses it, and refusing every
    import because the connector could not be bothered to say what it fetched
    would be a worse failure than a wrong guess -- the *detected* type is
    checked against the bytes either way, which is the check that matters.
    """
    import mimetypes

    declared = (payload.get("declared_mime") or "").strip()
    if declared:
        return declared[:128]
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _safe_filename(raw: str) -> str:
    """A remote-supplied name, reduced to something a filename validator can judge.

    Path separators and traversal are stripped here rather than passed on: the
    document platform's `validate_filename` would refuse them, but a refusal at
    that point would be reported as "the remote document was rejected", which is
    a confusing way to say "the remote system tried to name a file `../../etc`".
    """
    import os

    base = os.path.basename((raw or "").replace("\\", "/")).strip()
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*')
    return base[:200] or "imported"


# ---------------------------------------------------------------------------
# PUSH_FROZEN_PACKAGE
# ---------------------------------------------------------------------------
def run_push_frozen_package(*, execution, connector, config, credential_reference, actor, tenant):
    """Transfer the archive for one exact frozen snapshot."""
    from submission_packages import services as package_services
    from submission_packages.export import ExportError, write_package_zip
    from submission_packages.models import PackageStatus, SubmissionPackage

    from .secrets import SecretUnavailable, auth_headers

    package = (
        SubmissionPackage.objects.filter(public_id=execution.resource_public_id, tenant=tenant)
        .select_related("snapshot")
        .first()
    )
    if package is None:
        raise OperationError(OperationErrorCode.PACKAGE_MISSING)
    if package.status != PackageStatus.FROZEN:
        raise OperationError(OperationErrorCode.PACKAGE_NOT_FROZEN)

    snapshot = getattr(package, "snapshot", None)
    if snapshot is None:
        raise OperationError(OperationErrorCode.PACKAGE_MISSING)

    # The execution named a snapshot and a checksum when it was created. If
    # either has moved, this is not the transfer that was authorised, and it is
    # refused rather than performed against whatever is there now.
    if execution.snapshot_public_id and str(snapshot.public_id) != execution.snapshot_public_id:
        raise OperationError(OperationErrorCode.PACKAGE_INTEGRITY_FAILED)
    if execution.manifest_checksum and snapshot.manifest_checksum != execution.manifest_checksum:
        raise OperationError(OperationErrorCode.PACKAGE_INTEGRITY_FAILED)

    entries = list(package_services.active_entries(package))
    handle = tempfile.NamedTemporaryFile(suffix=".zip")
    try:
        try:
            # Milestone 13's exporter, unchanged: every file is streamed and
            # checked against the frozen manifest. A package that cannot produce
            # a valid archive is never sent -- the failure happens here, before
            # any remote call.
            counts = write_package_zip(snapshot=snapshot, entries=entries, destination=handle)
        except ExportError as exc:
            raise OperationError(OperationErrorCode.PACKAGE_INTEGRITY_FAILED) from exc

        handle.flush()
        size = handle.tell()
        handle.seek(0)
        digest = _digest_of(handle)
        handle.seek(0)

        try:
            url = build_url(
                base_url=config["base_url"],
                allowed_path_prefix=config["allowed_path_prefix"],
                relative_path=(execution.request_summary or {}).get("relative_path") or "",
            )
        except DestinationRefused as exc:
            raise OperationError(exc.code) from None

        try:
            headers = auth_headers(connector, credential_reference)
        except SecretUnavailable as exc:
            raise OperationError(TransportErrorCode.CREDENTIAL_UNAVAILABLE) from exc

        headers.update(
            {
                "Content-Type": "application/zip",
                # The remote system's chance to recognise a repeat. Whether it
                # takes it is the remote system's business -- see the module
                # docstring on what is not claimed.
                "X-Idempotency-Key": execution.idempotency_key,
                "X-Manifest-Checksum": snapshot.manifest_checksum,
            }
        )

        response = perform_request(
            connector=connector,
            configuration=config,
            method="PUT",
            url=url,
            headers=headers,
            body_stream=handle,
            body_length=size,
        )

        # Compared only if the endpoint actually returned one. No checksum means
        # not verified, and that is what gets recorded -- not silence that reads
        # like success.
        verified = False
        if response.remote_checksum:
            if response.remote_checksum.lower() != digest:
                raise OperationError(OperationErrorCode.PACKAGE_INTEGRITY_FAILED)
            verified = True

        return {
            "http_status": response.status,
            "bytes_transferred": size,
            "latency_ms": response.latency_ms,
            "external_reference": response.external_reference or snapshot.manifest_checksum,
            "external_object_id": response.external_reference or str(package.public_id),
            "remote_checksum": response.remote_checksum,
            "remote_checksum_verified": verified,
            "attempt": execution.attempt_count,
            "entry_count": counts.get("entry_count"),
        }
    finally:
        handle.close()


def _digest_of(handle) -> str:
    hasher = hashlib.sha256()
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        hasher.update(chunk)
    return hasher.hexdigest()


OPERATIONS = {
    "import_document": run_import_document,
    "push_frozen_package": run_push_frozen_package,
}


def run(operation: str, **kwargs) -> dict:
    handler = OPERATIONS.get(operation)
    if handler is None:
        raise OperationError(OperationErrorCode.PAYLOAD_INVALID)
    try:
        return handler(**kwargs)
    except TransportError as exc:
        raise OperationError(exc.code, retryable=exc.retryable) from None
