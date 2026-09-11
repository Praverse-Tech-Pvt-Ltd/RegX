"""P2: audit coverage for document processing failure and scan dispatch.

`document.processing.started` and `document.processing.complete` were both
emitted; the two failure paths were not. A version could end permanently
FAILED with the trail showing only that processing began -- the success path
audited, the failure path silent.

`document.scan.queued` was declared and never emitted either, which left a
version sitting at PENDING indistinguishable from one whose scan task was
never dispatched.

Both event types were already declared. P2 emits them; it does not invent
vocabulary.
"""

import io

import pytest

from documents.models import (
    Document,
    DocumentType,
    DocumentVersion,
    ProcessingStatus,
    ScanStatus,
)
from documents.tasks import _fail_job, process_document_version

pytestmark = pytest.mark.django_db

PROCESSING_FAILED = "document.processing.failed"
SCAN_QUEUED = "document.scan.queued"


def _events(event_type):
    from audit.models import AuditEvent

    return AuditEvent.objects.filter(event_type=event_type)


def _version(tenant, user, **overrides):
    document = Document.objects.create(
        tenant=tenant,
        title="P2 audit subject",
        document_type=DocumentType.PDF,
        created_by=user,
    )
    fields = {
        "document": document,
        "version_number": 1,
        "original_filename": "f.pdf",
        "normalized_filename": "f.pdf",
        "extension": "pdf",
        "declared_mime_type": "application/pdf",
        "size_bytes": 100,
        "sha256_checksum": "x" * 64,
        "storage_key": "dummy",
        "uploaded_by": user,
        "scan_status": ScanStatus.CLEAN,
    }
    fields.update(overrides)
    return DocumentVersion.objects.create(**fields)


class TestProcessingFailureIsAudited:
    def test_permanent_failure_emits_the_event(self, tenant_a, user_a):
        """`_fail_job` is the shared terminal-failure path for every extractor."""
        version = _version(tenant_a, user_a)
        from documents.models import DocumentProcessingJob

        job = DocumentProcessingJob.objects.create(version=version, job_type="extract")

        before = _events(PROCESSING_FAILED).count()
        _fail_job(job, version, "unsupported_format", "boom", retryable=False)

        assert _events(PROCESSING_FAILED).count() == before + 1
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.FAILED

    def test_event_records_tenant_and_target(self, tenant_a, user_a):
        version = _version(tenant_a, user_a)
        from documents.models import DocumentProcessingJob

        job = DocumentProcessingJob.objects.create(version=version, job_type="extract")
        _fail_job(job, version, "parse_error", "detail", retryable=True)

        event = _events(PROCESSING_FAILED).latest("created_at")
        assert event.tenant_id == tenant_a.id
        assert event.resource_id == str(version.public_id)
        assert event.resource_type == "document"

    def test_payload_carries_failure_code_and_retryability(self, tenant_a, user_a):
        version = _version(tenant_a, user_a)
        from documents.models import DocumentProcessingJob

        job = DocumentProcessingJob.objects.create(version=version, job_type="extract")
        _fail_job(job, version, "parse_error", "detail", retryable=True)

        payload = _events(PROCESSING_FAILED).latest("created_at").payload
        assert payload["failure_code"] == "parse_error"
        assert payload["retryable"] is True
        assert "attempt_count" in payload

    def test_payload_never_carries_the_failure_detail(self, tenant_a, user_a):
        """`detail` is str(exc). For a parse failure that can quote bytes of
        the document being processed, which must not enter an append-only
        table. It stays on the row, where it can be deleted."""
        version = _version(tenant_a, user_a)
        from documents.models import DocumentProcessingJob

        job = DocumentProcessingJob.objects.create(version=version, job_type="extract")
        _fail_job(job, version, "parse_error", "BYTES FROM THE DOCUMENT", retryable=False)

        payload = _events(PROCESSING_FAILED).latest("created_at").payload
        assert "failure_detail" not in payload
        assert "BYTES FROM THE DOCUMENT" not in str(payload)
        # ...but it is still recorded where it can be removed later.
        version.refresh_from_db()
        assert version.failure_detail == "BYTES FROM THE DOCUMENT"

    def test_retries_exhausted_path_emits_the_event(self, tenant_a, user_a):
        """The second failure path: attempts exhausted before work begins."""
        version = _version(tenant_a, user_a)
        from documents.models import DocumentProcessingJob

        DocumentProcessingJob.objects.create(
            version=version, job_type="extract", attempt_count=99, max_attempts=3
        )

        before = _events(PROCESSING_FAILED).count()
        process_document_version(version.pk, tenant_a.pk)

        assert _events(PROCESSING_FAILED).count() == before + 1
        payload = _events(PROCESSING_FAILED).latest("created_at").payload
        assert payload["failure_code"] == "max_attempts_exceeded"
        assert payload["retryable"] is False

    def test_a_successful_run_emits_no_failure_event(self, tenant_a, user_a):
        """Guards the semantics: failure events mean failure."""
        version = _version(tenant_a, user_a, scan_status=ScanStatus.PENDING)
        before = _events(PROCESSING_FAILED).count()
        # Not clean, so the task returns before doing any work at all.
        process_document_version(version.pk, tenant_a.pk)
        assert _events(PROCESSING_FAILED).count() == before


class TestScanQueuedIsAudited:
    def test_upload_emits_scan_queued(self, tenant_a, user_a, valid_pdf_bytes):
        from documents.ingest import ingest_new_document

        before = _events(SCAN_QUEUED).count()
        ingest_new_document(
            tenant=tenant_a,
            actor=user_a,
            file_obj=io.BytesIO(valid_pdf_bytes),
            filename="a.pdf",
            declared_mime="application/pdf",
            title="Queued subject",
            document_type=DocumentType.PDF,
        )
        assert _events(SCAN_QUEUED).count() == before + 1

    def test_event_records_tenant_and_target(self, tenant_a, user_a, valid_pdf_bytes):
        from documents.ingest import ingest_new_document

        _, version = ingest_new_document(
            tenant=tenant_a,
            actor=user_a,
            file_obj=io.BytesIO(valid_pdf_bytes),
            filename="a.pdf",
            declared_mime="application/pdf",
            title="Queued subject",
            document_type=DocumentType.PDF,
        )
        event = _events(SCAN_QUEUED).latest("created_at")
        assert event.tenant_id == tenant_a.id
        assert event.resource_id == str(version.public_id)

    def test_payload_is_only_the_source(self, tenant_a, user_a, valid_pdf_bytes):
        from documents.ingest import ingest_new_document

        ingest_new_document(
            tenant=tenant_a,
            actor=user_a,
            file_obj=io.BytesIO(valid_pdf_bytes),
            filename="a.pdf",
            declared_mime="application/pdf",
            title="Queued subject",
            document_type=DocumentType.PDF,
        )
        payload = _events(SCAN_QUEUED).latest("created_at").payload
        assert payload == {"source": "ingest"}

    def test_payload_never_carries_the_filename_or_bytes(self, tenant_a, user_a, valid_pdf_bytes):
        """The filename is user-supplied and can itself disclose subject
        matter; the bytes are the governed content."""
        from documents.ingest import ingest_new_document

        ingest_new_document(
            tenant=tenant_a,
            actor=user_a,
            file_obj=io.BytesIO(valid_pdf_bytes),
            filename="PATIENT-LIST-CONFIDENTIAL.pdf",
            declared_mime="application/pdf",
            title="Queued subject",
            document_type=DocumentType.PDF,
        )
        serialised = str(_events(SCAN_QUEUED).latest("created_at").payload)
        assert "PATIENT-LIST-CONFIDENTIAL" not in serialised
        assert "%PDF" not in serialised

    def test_a_rejected_upload_queues_nothing(self, tenant_a, user_a, mime_mismatch_bytes):
        """A refused upload never reaches the scanner, so it must not record a
        scan as queued. `document.upload.rejected` covers that case."""
        from documents.ingest import ingest_new_document
        from documents.validators import UploadValidationError

        before = _events(SCAN_QUEUED).count()
        with pytest.raises(UploadValidationError):
            ingest_new_document(
                tenant=tenant_a,
                actor=user_a,
                file_obj=io.BytesIO(mime_mismatch_bytes),
                filename="a.pdf",
                declared_mime="application/pdf",
                title="Rejected",
                document_type=DocumentType.PDF,
            )
        assert _events(SCAN_QUEUED).count() == before


class TestPayloadAllowList:
    def test_unlisted_keys_are_dropped(self):
        from documents.audit_events import DocumentEvent, _restrict

        cleaned = _restrict(
            DocumentEvent.PROCESSING_FAILED,
            {"failure_code": "x", "failure_detail": "LEAK", "retryable": False},
        )
        assert cleaned == {"failure_code": "x", "retryable": False}

    def test_events_without_an_allow_list_are_untouched(self):
        """P2 narrows only the two events it corrects; the other twelve keep
        the payloads they were written with."""
        from documents.audit_events import DocumentEvent, _restrict

        payload = {"anything": "preserved"}
        assert _restrict(DocumentEvent.DOCUMENT_CREATED, payload) == payload


class TestAuditRowsRemainImmutable:
    def test_a_processing_failure_event_cannot_be_changed(self, tenant_a, user_a):
        version = _version(tenant_a, user_a)
        from documents.models import DocumentProcessingJob

        job = DocumentProcessingJob.objects.create(version=version, job_type="extract")
        _fail_job(job, version, "parse_error", "detail", retryable=False)
        event = _events(PROCESSING_FAILED).latest("created_at")

        with pytest.raises(PermissionError):
            event.payload = {"failure_code": "rewritten"}
            event.save()

        with pytest.raises(PermissionError):
            event.delete()
