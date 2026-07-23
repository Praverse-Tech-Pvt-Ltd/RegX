"""Document model tests: versioning, tenant isolation, constraints."""

import pytest
from django.db import IntegrityError

from documents.models import (
    Document,
    DocumentDuplicateLink,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
)


@pytest.mark.django_db
class TestDocumentModel:
    def test_document_creation(self, tenant_a, user_a):
        doc = Document.objects.create(
            tenant=tenant_a,
            title="Test Document",
            document_type=DocumentType.PDF,
            created_by=user_a,
        )
        assert doc.pk is not None
        assert doc.public_id is not None
        assert doc.status == DocumentStatus.ACTIVE
        assert doc.current_version is None

    def test_internal_pk_not_public(self, tenant_a, user_a):
        doc = Document.objects.create(
            tenant=tenant_a,
            title="Doc",
            document_type=DocumentType.PDF,
            created_by=user_a,
        )
        # pk is a BIGINT that must never appear in API responses
        assert isinstance(doc.pk, int)
        # public_id is a UUID
        import uuid

        assert isinstance(doc.public_id, uuid.UUID)


@pytest.mark.django_db
class TestTenantScoping:
    def test_for_tenant_filters_correctly(self, tenant_a, tenant_b, user_a, user_b):
        Document.objects.create(
            tenant=tenant_a, title="A Doc", document_type=DocumentType.PDF, created_by=user_a
        )
        Document.objects.create(
            tenant=tenant_b, title="B Doc", document_type=DocumentType.DOCX, created_by=user_b
        )

        a_docs = Document.objects.for_tenant(tenant_a)
        b_docs = Document.objects.for_tenant(tenant_b)

        assert a_docs.count() == 1
        assert b_docs.count() == 1
        assert a_docs.first().tenant == tenant_a
        assert b_docs.first().tenant == tenant_b

    def test_tenant_a_cannot_see_tenant_b_documents(self, tenant_a, tenant_b, user_a, user_b):
        doc_b = Document.objects.create(
            tenant=tenant_b, title="B Doc", document_type=DocumentType.PDF, created_by=user_b
        )
        a_docs = Document.objects.for_tenant(tenant_a)
        assert not a_docs.filter(pk=doc_b.pk).exists()


@pytest.mark.django_db
class TestVersioningConstraints:
    def _make_version(self, doc, num, user, sha="abc123"):
        return DocumentVersion.objects.create(
            document=doc,
            version_number=num,
            original_filename=f"file_v{num}.pdf",
            normalized_filename=f"file_v{num}.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=1024,
            sha256_checksum=sha + str(num),
            storage_key=f"key/{num}",
            uploaded_by=user,
        )

    def test_version_numbers_are_unique_per_document(self, tenant_a, user_a):
        doc = Document.objects.create(
            tenant=tenant_a, title="Doc", document_type=DocumentType.PDF, created_by=user_a
        )
        self._make_version(doc, 1, user_a)
        with pytest.raises(IntegrityError):
            self._make_version(doc, 1, user_a)

    def test_versions_from_two_documents_can_share_number(self, tenant_a, user_a):
        doc1 = Document.objects.create(
            tenant=tenant_a, title="Doc1", document_type=DocumentType.PDF, created_by=user_a
        )
        doc2 = Document.objects.create(
            tenant=tenant_a, title="Doc2", document_type=DocumentType.PDF, created_by=user_a
        )
        self._make_version(doc1, 1, user_a, sha="aa")
        self._make_version(doc2, 1, user_a, sha="bb")
        assert DocumentVersion.objects.filter(document=doc1, version_number=1).exists()
        assert DocumentVersion.objects.filter(document=doc2, version_number=1).exists()


@pytest.mark.django_db
class TestDuplicateDetection:
    def test_duplicate_link_is_tenant_scoped(self, tenant_a, tenant_b, user_a, user_b):
        doc_a = Document.objects.create(
            tenant=tenant_a, title="A", document_type=DocumentType.PDF, created_by=user_a
        )
        doc_b = Document.objects.create(
            tenant=tenant_b, title="B", document_type=DocumentType.PDF, created_by=user_b
        )
        v_a = DocumentVersion.objects.create(
            document=doc_a,
            version_number=1,
            original_filename="a.pdf",
            normalized_filename="a.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="deadbeef01",
            storage_key="a/1",
            uploaded_by=user_a,
        )
        DocumentVersion.objects.create(
            document=doc_b,
            version_number=1,
            original_filename="b.pdf",
            normalized_filename="b.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=100,
            sha256_checksum="deadbeef02",
            storage_key="b/1",
            uploaded_by=user_b,
        )

        # Duplicate links are scoped to a tenant
        DocumentDuplicateLink.objects.create(
            tenant=tenant_a,
            source_version=v_a,
            matching_version=v_a,
            checksum="deadbeef01",
        )
        assert DocumentDuplicateLink.objects.filter(tenant=tenant_b).count() == 0
        assert DocumentDuplicateLink.objects.filter(tenant=tenant_a).count() == 1
