"""Tests for DeletionProtectionRegistry and DocumentVersion.delete() guard."""

import pytest

from documents.deletion_protection import (
    DocumentVersionDeleteForbidden,
    DeletionProtectionRegistry,
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
    import uuid
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

    def test_import_guard_no_circular_import(self):
        """documents.deletion_protection must not import iig_checklist."""
        import documents.deletion_protection as dp_module
        import sys

        # The module must be importable and iig_checklist must not appear
        # in its direct imports (not in sys.modules at module level).
        source = dp_module.__file__
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "iig_checklist" not in content
