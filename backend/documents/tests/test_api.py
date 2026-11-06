"""
Document API tests: tenant isolation, permission enforcement, response shape.

Every test that plants a violation is noted.
Uses X-Tenant-Slug header to activate tenant context via TenantMiddleware.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

BASE_URL = "/api/regx/v1/documents/"

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _client_for(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
    return client


def _pdf_upload(pdf_bytes, filename="test_document.pdf"):
    return SimpleUploadedFile(filename, pdf_bytes, content_type=PDF_MIME)


def _docx_upload(docx_bytes, filename="test_document.docx"):
    return SimpleUploadedFile(filename, docx_bytes, content_type=DOCX_MIME)


def _post_doc(
    client, pdf_bytes, title="Test Document", doc_type="pdf", filename="test_document.pdf"
):
    return client.post(
        BASE_URL,
        data={
            "title": title,
            "document_type": doc_type,
            "file": _pdf_upload(pdf_bytes, filename),
        },
        format="multipart",
    )


@pytest.mark.django_db
class TestUnauthenticatedAccess:
    def test_unauthenticated_list_rejected(self):
        # PLANTED: no credentials
        client = APIClient()
        resp = client.get(BASE_URL)
        assert resp.status_code in (401, 403)

    def test_unauthenticated_upload_rejected(self, valid_pdf_bytes, tenant_a):
        # PLANTED: no credentials on upload
        client = APIClient()
        client.credentials(**{"HTTP_X_TENANT_SLUG": tenant_a.slug})
        resp = client.post(
            BASE_URL,
            data={"title": "X", "document_type": "pdf", "file": _pdf_upload(valid_pdf_bytes)},
            format="multipart",
        )
        assert resp.status_code in (401, 403)


@pytest.mark.django_db
class TestDocumentUploadAPI:
    def test_doer_can_upload_pdf(
        self, user_a, tenant_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes, "My PDF")
        assert resp.status_code == 201
        data = resp.json()
        assert "public_id" in data
        assert "id" not in data  # no internal ID
        assert "storage_key" not in str(data)  # no storage key leaked
        assert data["title"] == "My PDF"

    def test_reviewer_cannot_upload(
        self, user_b, tenant_a, reviewer_membership, local_storage, valid_pdf_bytes, settings
    ):
        # PLANTED: reviewer role cannot upload
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_b, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes, "Viewer Upload Attempt")
        assert resp.status_code == 403

    def test_invalid_extension_returns_422(
        self, user_a, tenant_a, doer_membership, local_storage, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        f = SimpleUploadedFile("file.csv", b"csv,data,here", content_type="text/csv")
        resp = client.post(
            BASE_URL,
            data={"title": "CSV", "document_type": "pdf", "file": f},
            format="multipart",
        )
        assert resp.status_code in (422, 400)

    def test_upload_response_has_no_storage_key(
        self, user_a, tenant_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes)
        assert resp.status_code == 201
        assert "storage_key" not in resp.json()

    def test_upload_response_has_no_internal_id(
        self, user_a, tenant_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes)
        assert resp.status_code == 201
        data = resp.json()
        assert "id" not in data
        assert "pk" not in data

    def test_no_tenant_header_returns_error(
        self, user_a, doer_membership, valid_pdf_bytes, local_storage
    ):
        # PLANTED: request without tenant context
        client = APIClient()
        client.force_authenticate(user=user_a)
        resp = _post_doc(client, valid_pdf_bytes)
        assert resp.status_code in (403, 404, 401)


@pytest.mark.django_db
class TestDocumentListAPI:
    def test_doer_can_list_documents(
        self, user_a, tenant_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        _post_doc(client, valid_pdf_bytes, "Doc 1")
        resp = client.get(BASE_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert data["count"] >= 1

    def test_document_detail_accessible(
        self, user_a, tenant_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes, "Detail Test")
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        resp2 = client.get(f"{BASE_URL}{public_id}/")
        assert resp2.status_code == 200
        assert resp2.json()["public_id"] == public_id


@pytest.mark.django_db
class TestVersionAPI:
    def test_version_list_accessible_by_reviewer(
        self,
        user_a,
        user_b,
        tenant_a,
        doer_membership,
        reviewer_membership,
        local_storage,
        valid_pdf_bytes,
        settings,
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        # Doer uploads
        client_a = _client_for(user_a, tenant_a)
        resp = _post_doc(client_a, valid_pdf_bytes, "Versioned Doc")
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        # Reviewer lists versions
        client_b = _client_for(user_b, tenant_a)
        resp2 = client_b.get(f"{BASE_URL}{public_id}/versions/")
        assert resp2.status_code == 200
        assert resp2.json()["count"] >= 1

    def test_doer_can_upload_new_version(
        self,
        user_a,
        tenant_a,
        doer_membership,
        local_storage,
        valid_pdf_bytes,
        valid_docx_bytes,
        settings,
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes, "Multi-version Doc")
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        resp2 = client.post(
            f"{BASE_URL}{public_id}/versions/",
            data={"file": _docx_upload(valid_docx_bytes)},
            format="multipart",
        )
        assert resp2.status_code == 201
        assert resp2.json()["version_number"] == 2


@pytest.mark.django_db
class TestCrossTenantIsolation:
    def test_tenant_a_cannot_read_tenant_b_document(
        self,
        user_a,
        user_b,
        tenant_a,
        tenant_b,
        doer_membership,
        local_storage,
        valid_pdf_bytes,
        settings,
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        mem_b, _ = TenantMembership.objects.get_or_create(tenant=tenant_b, user=user_b)
        role_b, _ = Role.objects.get_or_create(
            name="doer", tenant=None, defaults={"is_system": True}
        )
        MembershipRole.objects.get_or_create(membership=mem_b, role=role_b)

        client_b = _client_for(user_b, tenant_b)
        resp = _post_doc(client_b, valid_pdf_bytes, "Tenant B Doc")
        assert resp.status_code == 201
        doc_b_public_id = resp.json()["public_id"]

        # User A tries to access tenant B doc via tenant A context
        client_a = _client_for(user_a, tenant_a)
        resp = client_a.get(f"{BASE_URL}{doc_b_public_id}/")
        # Must be 404, not 403 — do not leak existence
        assert resp.status_code == 404

    def test_cross_tenant_duplicate_not_disclosed(
        self,
        user_a,
        user_b,
        tenant_a,
        tenant_b,
        doer_membership,
        local_storage,
        valid_pdf_bytes,
        settings,
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        from authorization.models import MembershipRole, Role
        from documents.models import DocumentDuplicateLink
        from tenancy.models import TenantMembership

        mem_b, _ = TenantMembership.objects.get_or_create(tenant=tenant_b, user=user_b)
        role_b, _ = Role.objects.get_or_create(
            name="doer", tenant=None, defaults={"is_system": True}
        )
        MembershipRole.objects.get_or_create(membership=mem_b, role=role_b)

        client_a = _client_for(user_a, tenant_a)
        _post_doc(client_a, valid_pdf_bytes, "Tenant A Copy")

        client_b = _client_for(user_b, tenant_b)
        _post_doc(client_b, valid_pdf_bytes, "Tenant B Copy")

        from documents.models import DocumentVersion

        v_a = DocumentVersion.objects.filter(document__tenant=tenant_a).first()
        v_b = DocumentVersion.objects.filter(document__tenant=tenant_b).first()
        if v_a and v_b:
            assert not DocumentDuplicateLink.objects.filter(
                tenant=tenant_a, matching_version=v_b
            ).exists()
            assert not DocumentDuplicateLink.objects.filter(
                tenant=tenant_b, matching_version=v_a
            ).exists()


@pytest.mark.django_db
class TestArchiveRestore:
    def test_admin_can_archive_and_restore(
        self, user_a, tenant_a, admin_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes, "Archive Me")
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        resp2 = client.post(f"{BASE_URL}{public_id}/archive/")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "archived"

        resp3 = client.post(f"{BASE_URL}{public_id}/restore/")
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "active"

    def test_doer_cannot_archive(
        self, user_a, tenant_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes, "Try Archive")
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        # PLANTED: doer cannot archive
        resp2 = client.post(f"{BASE_URL}{public_id}/archive/")
        assert resp2.status_code == 403


@pytest.mark.django_db
class TestQuarantineAccess:
    def test_quarantined_version_locators_inaccessible(
        self, user_a, tenant_a, doer_membership, local_storage, valid_pdf_bytes, settings
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client = _client_for(user_a, tenant_a)
        resp = _post_doc(client, valid_pdf_bytes, "Q Doc")
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        vlist = client.get(f"{BASE_URL}{public_id}/versions/")
        version_public_id = vlist.json()["results"][0]["public_id"]

        # Manually quarantine the version
        from documents.models import DocumentVersion, ScanStatus

        DocumentVersion.objects.filter(public_id=version_public_id).update(
            scan_status=ScanStatus.QUARANTINED
        )

        # PLANTED: attempt to access locators of quarantined version
        resp = client.get(f"{BASE_URL}{public_id}/versions/{version_public_id}/locators/")
        assert resp.status_code == 403
