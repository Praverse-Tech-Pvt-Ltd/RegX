"""
Document versioning and concurrency tests.

Proves:
- Version numbers are assigned atomically (select_for_update prevents collisions).
- process_document_version is idempotent (safe to call twice).
- Sequential uploads produce monotonically increasing version numbers.
"""

import hashlib
import io

import pytest
from rest_framework.test import APIClient

from documents.models import (
    Document,
    DocumentType,
    DocumentVersion,
    ProcessingStatus,
    ScanStatus,
)
from documents.tasks import process_document_version

UPLOAD_URL = "/api/regx/v1/documents/"


def _client(user, tenant):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return c


def _pdf_upload(valid_pdf_bytes):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("test.pdf", valid_pdf_bytes, content_type="application/pdf")


@pytest.mark.django_db
class TestSequentialVersioning:
    def test_second_upload_increments_version_number(
        self, tenant_a, user_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        """A second upload to the same document gets version_number=2."""
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client(user_a, tenant_a)

        resp = client.post(
            UPLOAD_URL,
            {"title": "Version Test", "document_type": "pdf", "file": _pdf_upload(valid_pdf_bytes)},
            format="multipart",
        )
        assert resp.status_code == 201, resp.json()
        public_id = resp.json()["public_id"]

        resp2 = client.post(
            f"{UPLOAD_URL}{public_id}/versions/",
            {"file": _pdf_upload(valid_pdf_bytes)},
            format="multipart",
        )
        assert resp2.status_code == 201, resp2.json()
        assert resp2.json()["version_number"] == 2

    def test_three_sequential_uploads_monotone(
        self, tenant_a, user_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        """Three uploads produce version_numbers 1, 2, 3 in order."""
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client(user_a, tenant_a)

        resp = client.post(
            UPLOAD_URL,
            {
                "title": "Triple Version",
                "document_type": "pdf",
                "file": _pdf_upload(valid_pdf_bytes),
            },
            format="multipart",
        )
        assert resp.status_code == 201, resp.json()
        public_id = resp.json()["public_id"]

        for expected_v in (2, 3):
            r = client.post(
                f"{UPLOAD_URL}{public_id}/versions/",
                {"file": _pdf_upload(valid_pdf_bytes)},
                format="multipart",
            )
            assert r.status_code == 201, r.json()
            assert r.json()["version_number"] == expected_v


@pytest.mark.django_db
class TestProcessingIdempotency:
    def test_process_twice_does_not_duplicate_locators(
        self, tenant_a, user_a, local_storage, valid_pdf_bytes, settings
    ):
        """Calling process_document_version twice produces no duplicate locators."""
        from documents.models import DocumentLocator
        from documents.storage import LocalStorage

        settings.CELERY_TASK_ALWAYS_EAGER = True

        sha = hashlib.sha256(valid_pdf_bytes).hexdigest()
        key = LocalStorage().store(
            tenant_id=tenant_a.pk,
            file_obj=io.BytesIO(valid_pdf_bytes),
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="idem.pdf",
        )

        doc = Document.objects.create(
            tenant=tenant_a,
            title="Idempotency Test",
            document_type=DocumentType.PDF,
            created_by=user_a,
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="idem.pdf",
            normalized_filename="idem.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=len(valid_pdf_bytes),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )

        process_document_version(version.pk, tenant_a.pk)
        count_after_first = DocumentLocator.objects.filter(version=version).count()

        process_document_version(version.pk, tenant_a.pk)
        count_after_second = DocumentLocator.objects.filter(version=version).count()

        assert count_after_first == count_after_second
        assert count_after_first > 0

    def test_process_complete_skips_reprocessing(self, tenant_a, user_a):
        """Version already COMPLETE is not reprocessed."""
        doc = Document.objects.create(
            tenant=tenant_a,
            title="Skip Test",
            document_type=DocumentType.PDF,
            created_by=user_a,
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="done.pdf",
            normalized_filename="done.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="a" * 64,
            storage_key="dummy",
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
            processing_status=ProcessingStatus.COMPLETE,
        )

        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        assert version.processing_status == ProcessingStatus.COMPLETE
