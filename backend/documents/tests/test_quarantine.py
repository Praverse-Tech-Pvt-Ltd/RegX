"""
Malware scanning and quarantine verification tests.

Proves fail-closed design, state transitions, and audit events.
All tests use synthetic scanners and local storage with real file bytes.
"""

import hashlib
import io

import pytest

from documents.models import (
    Document,
    DocumentType,
    DocumentVersion,
    ProcessingStatus,
    ScanStatus,
)
from documents.scanner import ScanOutcome, ScanResult, StubScanner
from documents.tasks import process_document_version, scan_document_version

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(tenant, user, doc_type=DocumentType.PDF):
    return Document.objects.create(
        tenant=tenant, title="Quarantine Test", document_type=doc_type, created_by=user
    )


def _store_bytes(tmp_path, tenant, content, filename):
    """Store bytes in LocalStorage and return (key, sha256)."""
    from documents.storage import LocalStorage

    sha = hashlib.sha256(content).hexdigest()
    storage = LocalStorage()
    key = storage.store(
        tenant_id=tenant.pk,
        file_obj=io.BytesIO(content),
        expected_sha256=sha,
        content_type="application/octet-stream",
        original_filename=filename,
    )
    return key, sha


def _make_version(doc, user, storage_key, sha, ext="pdf", scan_status=ScanStatus.PENDING):
    return DocumentVersion.objects.create(
        document=doc,
        version_number=1,
        original_filename=f"file.{ext}",
        normalized_filename=f"file.{ext}",
        extension=ext,
        declared_mime_type="application/pdf",
        size_bytes=100,
        sha256_checksum=sha,
        storage_key=storage_key,
        uploaded_by=user,
        scan_status=scan_status,
    )


# ---------------------------------------------------------------------------
# Fail-closed scan design
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFailClosedScan:
    def test_unscanned_file_cannot_be_processed(self, tenant_a, user_a, settings, tmp_path):
        """Version with scan_status=PENDING must not be processed."""
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")

        key, sha = _store_bytes(tmp_path, tenant_a, b"dummy content", "file.pdf")
        doc = _make_doc(tenant_a, user_a)
        version = _make_version(doc, user_a, key, sha)
        # scan_status=PENDING (default in _make_version)

        process_document_version(version.pk, tenant_a.pk)

        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.PENDING

    def test_scan_failed_result_does_not_become_clean(
        self, tenant_a, user_a, settings, tmp_path, monkeypatch
    ):
        """SCAN_FAILED scan result must not set scan_status=CLEAN."""
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        key, sha = _store_bytes(tmp_path, tenant_a, b"content", "file.pdf")

        def fail_scan(self, _file_obj):
            return ScanOutcome(result=ScanResult.SCAN_FAILED, threat_name=None, detail="timeout")

        monkeypatch.setattr("documents.scanner.StubScanner.scan", fail_scan)
        monkeypatch.setattr("documents.tasks.get_scanner_backend", lambda: StubScanner())

        doc = _make_doc(tenant_a, user_a)
        version = _make_version(doc, user_a, key, sha)

        # With ALWAYS_EAGER, self.retry() raises Retry/MaxRetriesExceeded after attempts
        try:
            scan_document_version(version.pk, tenant_a.pk)
        except Exception:
            pass

        version.refresh_from_db()
        assert version.scan_status != ScanStatus.CLEAN

    def test_scanner_unavailable_does_not_clean(
        self, tenant_a, user_a, settings, tmp_path, monkeypatch
    ):
        """SCANNER_UNAVAILABLE result must not set scan_status=CLEAN."""
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        key, sha = _store_bytes(tmp_path, tenant_a, b"content", "file.pdf")

        def unavailable_scan(self, _file_obj):
            return ScanOutcome(
                result=ScanResult.SCANNER_UNAVAILABLE, threat_name=None, detail="conn refused"
            )

        monkeypatch.setattr("documents.scanner.StubScanner.scan", unavailable_scan)
        monkeypatch.setattr("documents.tasks.get_scanner_backend", lambda: StubScanner())

        doc = _make_doc(tenant_a, user_a)
        version = _make_version(doc, user_a, key, sha)

        try:
            scan_document_version(version.pk, tenant_a.pk)
        except Exception:
            pass

        version.refresh_from_db()
        assert version.scan_status != ScanStatus.CLEAN


# ---------------------------------------------------------------------------
# Quarantine enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestQuarantine:
    def test_infected_file_becomes_quarantined(
        self, tenant_a, user_a, settings, tmp_path, monkeypatch
    ):
        """INFECTED scan result sets scan_status=QUARANTINED and processing=SKIPPED."""
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        content = b"EICAR-LIKE-TEST-CONTENT"
        key, sha = _store_bytes(tmp_path, tenant_a, content, "infected.pdf")

        def infected_scan(self, _file_obj):
            return ScanOutcome(
                result=ScanResult.INFECTED, threat_name="TestVirus.Eicar", detail="infected"
            )

        monkeypatch.setattr("documents.scanner.StubScanner.scan", infected_scan)
        monkeypatch.setattr("documents.tasks.get_scanner_backend", lambda: StubScanner())

        doc = _make_doc(tenant_a, user_a)
        version = _make_version(doc, user_a, key, sha, scan_status=ScanStatus.PENDING)

        scan_document_version(version.pk, tenant_a.pk)

        version.refresh_from_db()
        assert version.scan_status == ScanStatus.QUARANTINED
        assert version.processing_status == ProcessingStatus.SKIPPED

    def test_quarantined_version_blocks_processing(self, tenant_a, user_a):
        """process_document_version must not run on a quarantined version."""
        doc = _make_doc(tenant_a, user_a)
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="q.pdf",
            normalized_filename="q.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="e" * 64,
            storage_key="dummy",
            uploaded_by=user_a,
            scan_status=ScanStatus.QUARANTINED,
            processing_status=ProcessingStatus.SKIPPED,
        )

        process_document_version(version.pk, tenant_a.pk)

        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.SKIPPED

    def test_infected_threat_name_recorded(self, tenant_a, user_a, settings, tmp_path, monkeypatch):
        """Infected file failure_code is set to 'infected'."""
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        key, sha = _store_bytes(tmp_path, tenant_a, b"virus bytes", "virus.pdf")

        monkeypatch.setattr(
            "documents.scanner.StubScanner.scan",
            lambda self, _: ScanOutcome(ScanResult.INFECTED, "Trojan.GenericKD", "infected"),
        )
        monkeypatch.setattr("documents.tasks.get_scanner_backend", lambda: StubScanner())

        doc = _make_doc(tenant_a, user_a)
        version = _make_version(doc, user_a, key, sha)

        scan_document_version(version.pk, tenant_a.pk)

        version.refresh_from_db()
        assert version.failure_code == "infected"


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScanAuditEvents:
    def test_clean_scan_emits_scan_complete_event(self, tenant_a, user_a, settings, tmp_path):
        """Clean scan emits SCAN_COMPLETE audit event."""
        from audit.models import AuditEvent
        from documents.audit_events import DocumentEvent

        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        content = b"%PDF-1.4 clean content"
        key, sha = _store_bytes(tmp_path, tenant_a, content, "clean.pdf")

        doc = _make_doc(tenant_a, user_a)
        version = _make_version(doc, user_a, key, sha)

        before_count = AuditEvent.objects.filter(event_type=DocumentEvent.SCAN_COMPLETE).count()
        scan_document_version(version.pk, tenant_a.pk)

        assert (
            AuditEvent.objects.filter(event_type=DocumentEvent.SCAN_COMPLETE).count() > before_count
        )

    def test_infected_scan_emits_quarantine_event(
        self, tenant_a, user_a, settings, tmp_path, monkeypatch
    ):
        """Infected scan emits QUARANTINED audit event."""
        from audit.models import AuditEvent
        from documents.audit_events import DocumentEvent

        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        key, sha = _store_bytes(tmp_path, tenant_a, b"malware-bytes", "malware.pdf")

        monkeypatch.setattr(
            "documents.scanner.StubScanner.scan",
            lambda self, _: ScanOutcome(ScanResult.INFECTED, "Evil.Malware", "infected"),
        )
        monkeypatch.setattr("documents.tasks.get_scanner_backend", lambda: StubScanner())

        doc = _make_doc(tenant_a, user_a)
        version = _make_version(doc, user_a, key, sha)

        before_q = AuditEvent.objects.filter(event_type=DocumentEvent.QUARANTINED).count()
        scan_document_version(version.pk, tenant_a.pk)
        assert AuditEvent.objects.filter(event_type=DocumentEvent.QUARANTINED).count() > before_q

    def test_storage_error_emits_scan_failed_event(self, tenant_a, user_a, settings, tmp_path):
        """Storage retrieval failure emits SCAN_FAILED audit event (no retry path)."""
        from audit.models import AuditEvent
        from documents.audit_events import DocumentEvent

        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        doc = _make_doc(tenant_a, user_a)
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="missing.pdf",
            normalized_filename="missing.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="f" * 64,
            storage_key="nonexistent/key/that/does/not/exist",
            uploaded_by=user_a,
        )

        before_fail = AuditEvent.objects.filter(event_type=DocumentEvent.SCAN_FAILED).count()
        # Storage retrieve will raise → task emits SCAN_FAILED and returns (no retry)
        scan_document_version(version.pk, tenant_a.pk)
        assert AuditEvent.objects.filter(event_type=DocumentEvent.SCAN_FAILED).count() > before_fail
