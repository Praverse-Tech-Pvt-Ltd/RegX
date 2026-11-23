"""QA-09 (documents): a governed change and its audit record commit together or not at all.

Fault injection: `audit.testing.audit_writes_fail()` makes every audit INSERT fail in
PostgreSQL; each test asserts the change did not persist. On the old code each change
committed before its audit write, so every test here failed.

Covered: upload (documents.ingest), new version upload, archive, restore, and the two
Celery tasks. In the tasks every "save a status, then emit" pair was wrapped the same
way (scan clean / infected / failed; processing started / complete / no-text / failed);
one test per task drives the first pair it reaches, and the wrapping of the others is
identical (see the diff).
"""

from __future__ import annotations

import hashlib
import io

import pytest

from audit.testing import attempt, audit_writes_fail
from documents.models import (
    Document,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
    ProcessingStatus,
    ScanStatus,
)
from documents.tasks import process_document_version, scan_document_version

from .test_api import BASE_URL, _client_for, _pdf_upload, _post_doc

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def client(user_a, tenant_a, admin_membership, local_storage, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False  # the scan is not under test here
    return _client_for(user_a, tenant_a)


def test_upload_rolls_back_without_its_audit(client, valid_pdf_bytes):
    with audit_writes_fail():
        attempt(_post_doc, client, valid_pdf_bytes, "QA-09 upload")
    assert not Document.objects.filter(title="QA-09 upload").exists()
    assert not DocumentVersion.objects.exists()


def test_new_version_rolls_back_without_its_audit(client, valid_pdf_bytes):
    public_id = _post_doc(client, valid_pdf_bytes, "QA-09 versions").json()["public_id"]
    with audit_writes_fail():
        attempt(
            client.post,
            f"{BASE_URL}{public_id}/versions/",
            data={"file": _pdf_upload(valid_pdf_bytes, "v2.pdf")},
            format="multipart",
        )
    assert DocumentVersion.objects.filter(document__public_id=public_id).count() == 1


def test_archive_rolls_back_without_its_audit(client, valid_pdf_bytes):
    public_id = _post_doc(client, valid_pdf_bytes, "QA-09 archive").json()["public_id"]
    with audit_writes_fail():
        attempt(client.post, f"{BASE_URL}{public_id}/archive/")
    assert Document.objects.get(public_id=public_id).status == DocumentStatus.ACTIVE


def test_restore_rolls_back_without_its_audit(client, valid_pdf_bytes):
    public_id = _post_doc(client, valid_pdf_bytes, "QA-09 restore").json()["public_id"]
    assert client.post(f"{BASE_URL}{public_id}/archive/").status_code == 200
    with audit_writes_fail():
        attempt(client.post, f"{BASE_URL}{public_id}/restore/")
    assert Document.objects.get(public_id=public_id).status == DocumentStatus.ARCHIVED


def _stored_version(tenant, user, pdf_bytes, scan_status):
    from documents.storage import get_storage_backend

    sha = hashlib.sha256(pdf_bytes).hexdigest()
    key = get_storage_backend().store(
        tenant_id=tenant.pk,
        file_obj=io.BytesIO(pdf_bytes),
        expected_sha256=sha,
        content_type="application/pdf",
        original_filename="qa09.pdf",
    )
    doc = Document.objects.create(
        tenant=tenant, title="QA-09 task", document_type=DocumentType.PDF, created_by=user
    )
    return DocumentVersion.objects.create(
        document=doc,
        version_number=1,
        original_filename="qa09.pdf",
        normalized_filename="qa09.pdf",
        extension="pdf",
        declared_mime_type="application/pdf",
        size_bytes=len(pdf_bytes),
        sha256_checksum=sha,
        storage_key=key,
        uploaded_by=user,
        scan_status=scan_status,
    )


def test_scan_result_rolls_back_without_its_audit(
    tenant_a, user_a, local_storage, valid_pdf_bytes, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    version = _stored_version(tenant_a, user_a, valid_pdf_bytes, ScanStatus.PENDING)
    with audit_writes_fail():
        attempt(scan_document_version, version.pk, tenant_a.pk)
    version.refresh_from_db()
    assert version.scan_status == ScanStatus.PENDING


def test_processing_status_rolls_back_without_its_audit(
    tenant_a, user_a, local_storage, valid_pdf_bytes
):
    version = _stored_version(tenant_a, user_a, valid_pdf_bytes, ScanStatus.CLEAN)
    before = version.processing_status
    with audit_writes_fail():
        attempt(process_document_version, version.pk, tenant_a.pk)
    version.refresh_from_db()
    assert version.processing_status == before
    assert version.processing_status != ProcessingStatus.PROCESSING
