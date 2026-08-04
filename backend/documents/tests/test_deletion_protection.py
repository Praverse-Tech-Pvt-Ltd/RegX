"""Tests for DeletionProtectionRegistry and DocumentVersion.delete() guard."""

import pytest

from documents.deletion_protection import (
    DeletionProtectionRegistry,
    DocumentVersionDeleteForbidden,
)

# ---------------------------------------------------------------------------
# Registry unit tests (no DB required)
# ---------------------------------------------------------------------------


class TestDeletionProtectionRegistry:
    def test_register_and_check_blocking(self):
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("key_a", lambda dv: True)
            blocking = DeletionProtectionRegistry.check(object())
            assert blocking == ["key_a"]

    def test_register_non_blocking(self):
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("key_b", lambda dv: False)
            blocking = DeletionProtectionRegistry.check(object())
            assert blocking == []

    def test_no_checkers_returns_empty(self):
        with DeletionProtectionRegistry._isolated():
            blocking = DeletionProtectionRegistry.check(object())
            assert blocking == []

    def test_idempotent_register(self):
        with DeletionProtectionRegistry._isolated():
            called = []
            DeletionProtectionRegistry.register("key_c", lambda dv: False)
            DeletionProtectionRegistry.register("key_c", lambda dv: called.append(1) or True)
            blocking = DeletionProtectionRegistry.check(object())
            # Second registration replaced the first.
            assert blocking == ["key_c"]
            assert called

    def test_unregister_removes_checker(self):
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("key_d", lambda dv: True)
            DeletionProtectionRegistry.unregister("key_d")
            blocking = DeletionProtectionRegistry.check(object())
            assert blocking == []

    def test_unregister_missing_key_is_noop(self):
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.unregister("nonexistent_key")

    def test_fail_closed_on_checker_exception(self):
        def bad_checker(dv):
            raise RuntimeError("checker exploded")

        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("boom", bad_checker)
            blocking = DeletionProtectionRegistry.check(object())
            assert blocking == ["boom_check_failed"]

    def test_sorted_key_order(self):
        order = []
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("c_checker", lambda dv: order.append("c") or False)
            DeletionProtectionRegistry.register("a_checker", lambda dv: order.append("a") or False)
            DeletionProtectionRegistry.register("b_checker", lambda dv: order.append("b") or False)
            DeletionProtectionRegistry.check(object())
        assert order == ["a", "b", "c"]

    def test_multiple_checkers_all_blocking(self):
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("x1", lambda dv: True)
            DeletionProtectionRegistry.register("x2", lambda dv: True)
            blocking = DeletionProtectionRegistry.check(object())
            assert set(blocking) == {"x1", "x2"}

    def test_isolated_restores_prior_state(self):
        outer_called = []
        DeletionProtectionRegistry.register(
            "_test_outer_key", lambda dv: outer_called.append(1) or False
        )
        try:
            with DeletionProtectionRegistry._isolated():
                # Inside isolation: outer checker is gone.
                assert "_test_outer_key" not in DeletionProtectionRegistry._checkers
                DeletionProtectionRegistry.register("inner", lambda dv: True)
            # Outside isolation: outer checker restored, inner gone.
            assert "_test_outer_key" in DeletionProtectionRegistry._checkers
            assert "inner" not in DeletionProtectionRegistry._checkers
        finally:
            DeletionProtectionRegistry.unregister("_test_outer_key")


# ---------------------------------------------------------------------------
# DocumentVersion.delete() integration
# ---------------------------------------------------------------------------


def _make_document_version(tenant, user):
    from documents.models import Document, DocumentVersion

    doc = Document.objects.create(
        tenant=tenant,
        title="Test Doc",
        document_type="pdf",
        created_by=user,
    )
    return DocumentVersion.objects.create(
        document=doc,
        version_number=1,
        original_filename="test.pdf",
        normalized_filename="test.pdf",
        extension="pdf",
        declared_mime_type="application/pdf",
        size_bytes=1024,
        sha256_checksum="a" * 64,
        storage_key="test/key.pdf",
        uploaded_by=user,
    )


@pytest.mark.django_db
class TestDocumentVersionDelete:
    def test_delete_allowed_when_no_checkers(self, tenant_a, user_a):
        with DeletionProtectionRegistry._isolated():
            dv = _make_document_version(tenant_a, user_a)
            dv.delete()  # must not raise

    def test_delete_blocked_when_checker_returns_true(self, tenant_a, user_a):
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("block_all", lambda dv: True)
            dv = _make_document_version(tenant_a, user_a)
            with pytest.raises(DocumentVersionDeleteForbidden):
                dv.delete()

    def test_delete_allowed_when_checker_returns_false(self, tenant_a, user_a):
        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("allow_all", lambda dv: False)
            dv = _make_document_version(tenant_a, user_a)
            dv.delete()  # must not raise

    def test_delete_fail_closed_on_checker_exception(self, tenant_a, user_a):
        def exploding_checker(dv):
            raise RuntimeError("unexpected error")

        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("exploding", exploding_checker)
            dv = _make_document_version(tenant_a, user_a)
            with pytest.raises(DocumentVersionDeleteForbidden):
                dv.delete()


# ---------------------------------------------------------------------------
# QuerySet-level and bulk deletion (M4D2-F-3): DocumentVersion.delete() is an
# instance-level override. Any of these paths must be equally protected:
#   - DocumentVersion.objects.filter(...).delete()
#   - Document.delete() / Document.objects.filter(...).delete() cascading to
#     versions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDocumentVersionQuerySetDelete:
    def test_queryset_delete_blocked_when_checker_returns_true(self, tenant_a, user_a):
        from documents.models import DocumentVersion

        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("block_all", lambda dv: True)
            dv = _make_document_version(tenant_a, user_a)
            with pytest.raises(DocumentVersionDeleteForbidden):
                DocumentVersion.objects.filter(pk=dv.pk).delete()
            assert DocumentVersion.objects.filter(pk=dv.pk).exists()

    def test_queryset_delete_allowed_when_no_checkers(self, tenant_a, user_a):
        from documents.models import DocumentVersion

        with DeletionProtectionRegistry._isolated():
            dv = _make_document_version(tenant_a, user_a)
            DocumentVersion.objects.filter(pk=dv.pk).delete()
            assert not DocumentVersion.objects.filter(pk=dv.pk).exists()

    def test_queryset_delete_blocked_if_any_row_in_bulk_is_blocked(self, tenant_a, user_a):
        from documents.models import DocumentVersion

        with DeletionProtectionRegistry._isolated():
            blocked_dv = _make_document_version(tenant_a, user_a)
            allowed_dv = _make_document_version(tenant_a, user_a)
            DeletionProtectionRegistry.register("block_one", lambda dv: dv.pk == blocked_dv.pk)
            with pytest.raises(DocumentVersionDeleteForbidden):
                DocumentVersion.objects.filter(pk__in=[blocked_dv.pk, allowed_dv.pk]).delete()
            # Fails closed: neither row is removed when any row is blocked.
            assert DocumentVersion.objects.filter(pk=blocked_dv.pk).exists()
            assert DocumentVersion.objects.filter(pk=allowed_dv.pk).exists()


@pytest.mark.django_db
class TestDocumentDeleteCascade:
    def test_document_instance_delete_blocked_when_version_referenced(self, tenant_a, user_a):
        from documents.models import DocumentVersion

        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("block_all", lambda dv: True)
            dv = _make_document_version(tenant_a, user_a)
            doc = dv.document
            with pytest.raises(DocumentVersionDeleteForbidden):
                doc.delete()
            assert DocumentVersion.objects.filter(pk=dv.pk).exists()

    def test_document_instance_delete_allowed_when_no_checkers(self, tenant_a, user_a):
        from documents.models import Document

        with DeletionProtectionRegistry._isolated():
            dv = _make_document_version(tenant_a, user_a)
            doc_pk = dv.document_id
            dv.document.delete()
            assert not Document.objects.filter(pk=doc_pk).exists()

    def test_document_queryset_delete_blocked_when_version_referenced(self, tenant_a, user_a):
        from documents.models import Document, DocumentVersion

        with DeletionProtectionRegistry._isolated():
            DeletionProtectionRegistry.register("block_all", lambda dv: True)
            dv = _make_document_version(tenant_a, user_a)
            doc_pk = dv.document_id
            with pytest.raises(DocumentVersionDeleteForbidden):
                Document.objects.filter(pk=doc_pk).delete()
            assert Document.objects.filter(pk=doc_pk).exists()
            assert DocumentVersion.objects.filter(pk=dv.pk).exists()


# ---------------------------------------------------------------------------
# Import-direction guard (no DB required)
# ---------------------------------------------------------------------------


def test_import_guard_no_circular_import():
    """documents.deletion_protection must not import iig_checklist.

    Parses the module's AST rather than substring-matching the source --
    the module's own docstring names iig_checklist in prose, which a naive
    substring check would misreport as an import.
    """
    import ast

    import documents.deletion_protection as dp_module

    with open(dp_module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read(), dp_module.__file__)

    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any(m == "iig_checklist" or m.startswith("iig_checklist.") for m in imported_modules)
