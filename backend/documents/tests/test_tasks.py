"""
Celery processing task tests.

Uses CELERY_TASK_ALWAYS_EAGER=True (set in test settings).
"""

import io

import pytest

from documents.models import (
    Document,
    DocumentLocator,
    DocumentType,
    DocumentVersion,
    LocatorType,
    ProcessingStatus,
    ScanStatus,
)
from documents.tasks import process_document_version, scan_document_version


def _make_version(doc, user, sha, storage_key, ext="pdf"):
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
        scan_status=ScanStatus.CLEAN,
    )


@pytest.mark.django_db
class TestScanTask:
    def test_scan_clean_triggers_processing(
        self, settings, tmp_path, tenant_a, user_a, valid_pdf_bytes
    ):
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        import hashlib

        from documents.storage import LocalStorage

        storage = LocalStorage()
        sha = hashlib.sha256(valid_pdf_bytes).hexdigest()
        f = io.BytesIO(valid_pdf_bytes)
        key = storage.store(
            tenant_id=tenant_a.pk,
            file_obj=f,
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="test.pdf",
        )

        doc = Document.objects.create(
            tenant=tenant_a, title="Scan Test", document_type=DocumentType.PDF, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="test.pdf",
            normalized_filename="test.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=len(valid_pdf_bytes),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.PENDING,
        )

        scan_document_version(version.pk, tenant_a.pk)

        version.refresh_from_db()
        assert version.scan_status == ScanStatus.CLEAN
        assert version.processing_status == ProcessingStatus.COMPLETE

    def test_scan_skips_already_clean_idempotent(self, tenant_a, user_a):
        doc = Document.objects.create(
            tenant=tenant_a, title="Idempotent", document_type=DocumentType.PDF, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="f.pdf",
            normalized_filename="f.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="abc" * 20 + "ab",
            storage_key="dummy",
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
            processing_status=ProcessingStatus.COMPLETE,
        )
        # Should not raise; idempotent
        scan_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        assert version.scan_status == ScanStatus.CLEAN


@pytest.mark.django_db
class TestProcessingTask:
    def test_processing_blocked_if_not_clean(self, tenant_a, user_a):
        doc = Document.objects.create(
            tenant=tenant_a, title="Blocked", document_type=DocumentType.PDF, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="f.pdf",
            normalized_filename="f.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="x" * 64,
            storage_key="dummy",
            uploaded_by=user_a,
            scan_status=ScanStatus.PENDING,  # not clean
        )
        # Task should return without processing
        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.PENDING

    def test_unscoped_cross_tenant_task_returns_early(self, tenant_a, tenant_b, user_a, user_b):
        doc = Document.objects.create(
            tenant=tenant_a, title="A Doc", document_type=DocumentType.PDF, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="f.pdf",
            normalized_filename="f.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="y" * 64,
            storage_key="dummy",
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )
        # Pass wrong tenant_id — should not process
        process_document_version(version.pk, tenant_b.pk)
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.PENDING

    def test_pdf_processing_creates_page_locators(
        self, settings, tmp_path, tenant_a, user_a, valid_pdf_bytes
    ):
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        import hashlib

        from documents.storage import LocalStorage

        storage = LocalStorage()
        sha = hashlib.sha256(valid_pdf_bytes).hexdigest()
        key = storage.store(
            tenant_id=tenant_a.pk,
            file_obj=io.BytesIO(valid_pdf_bytes),
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="test.pdf",
        )
        doc = Document.objects.create(
            tenant=tenant_a, title="PDF Proc", document_type=DocumentType.PDF, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="test.pdf",
            normalized_filename="test.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=len(valid_pdf_bytes),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )

        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert DocumentLocator.objects.filter(
            version=version, locator_type=LocatorType.PAGE
        ).exists()

    def test_docx_processing_creates_locators(
        self, settings, tmp_path, tenant_a, user_a, valid_docx_bytes
    ):
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        import hashlib

        from documents.storage import LocalStorage

        storage = LocalStorage()
        sha = hashlib.sha256(valid_docx_bytes).hexdigest()
        key = storage.store(
            tenant_id=tenant_a.pk,
            file_obj=io.BytesIO(valid_docx_bytes),
            expected_sha256=sha,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            original_filename="test.docx",
        )
        doc = Document.objects.create(
            tenant=tenant_a, title="DOCX Proc", document_type=DocumentType.DOCX, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="test.docx",
            normalized_filename="test.docx",
            extension="docx",
            declared_mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=len(valid_docx_bytes),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )

        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.COMPLETE
        locators = DocumentLocator.objects.filter(version=version)
        assert locators.exists()

    def test_xlsx_processing_creates_sheet_locators(
        self, settings, tmp_path, tenant_a, user_a, valid_xlsx_bytes
    ):
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        import hashlib

        from documents.storage import LocalStorage

        storage = LocalStorage()
        sha = hashlib.sha256(valid_xlsx_bytes).hexdigest()
        key = storage.store(
            tenant_id=tenant_a.pk,
            file_obj=io.BytesIO(valid_xlsx_bytes),
            expected_sha256=sha,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename="test.xlsx",
        )
        doc = Document.objects.create(
            tenant=tenant_a, title="XLSX Proc", document_type=DocumentType.XLSX, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="test.xlsx",
            normalized_filename="test.xlsx",
            extension="xlsx",
            declared_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=len(valid_xlsx_bytes),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )

        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert DocumentLocator.objects.filter(
            version=version, locator_type=LocatorType.SHEET
        ).exists()

    def test_pptx_processing_creates_slide_locators(
        self, settings, tmp_path, tenant_a, user_a, valid_pptx_bytes
    ):
        settings.DOCUMENT_STORAGE_BACKEND = "local"
        settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
        settings.CELERY_TASK_ALWAYS_EAGER = True

        import hashlib

        from documents.storage import LocalStorage

        storage = LocalStorage()
        sha = hashlib.sha256(valid_pptx_bytes).hexdigest()
        key = storage.store(
            tenant_id=tenant_a.pk,
            file_obj=io.BytesIO(valid_pptx_bytes),
            expected_sha256=sha,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            original_filename="test.pptx",
        )
        doc = Document.objects.create(
            tenant=tenant_a, title="PPTX Proc", document_type=DocumentType.PPTX, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="test.pptx",
            normalized_filename="test.pptx",
            extension="pptx",
            declared_mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            size_bytes=len(valid_pptx_bytes),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )

        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert DocumentLocator.objects.filter(
            version=version, locator_type=LocatorType.SLIDE
        ).exists()
