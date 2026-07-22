"""Storage abstraction tests."""

import hashlib
import io

import pytest

from documents.storage import ChecksumMismatchError, LocalStorage, StorageError, compute_sha256


@pytest.fixture
def storage(tmp_path, settings):
    settings.DOCUMENT_STORAGE_BACKEND = "local"
    settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
    return LocalStorage()


class TestLocalStorage:
    def test_store_and_retrieve(self, storage):
        content = b"Hello, REGX document platform!"
        sha = hashlib.sha256(content).hexdigest()
        f = io.BytesIO(content)

        key = storage.store(
            tenant_id=1,
            file_obj=f,
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="test.pdf",
        )
        assert key.startswith("1/")
        assert storage.exists(key)

        retrieved = storage.retrieve(key)
        assert retrieved.read() == content
        retrieved.close()

    def test_checksum_mismatch_raises(self, storage):
        content = b"Some content"
        wrong_sha = "0" * 64
        f = io.BytesIO(content)

        with pytest.raises(ChecksumMismatchError):
            storage.store(
                tenant_id=1,
                file_obj=f,
                expected_sha256=wrong_sha,
                content_type="application/pdf",
                original_filename="test.pdf",
            )

    def test_incomplete_upload_cleaned_up_on_checksum_fail(self, storage, tmp_path):
        content = b"Content"
        wrong_sha = "0" * 64
        f = io.BytesIO(content)
        store_root = tmp_path / "store"

        with pytest.raises(ChecksumMismatchError):
            storage.store(
                tenant_id=99,
                file_obj=f,
                expected_sha256=wrong_sha,
                content_type="application/pdf",
                original_filename="test.pdf",
            )
        # No temp files left
        import glob

        leftover = glob.glob(str(store_root / "**" / "tmp*"), recursive=True)
        assert len(leftover) == 0

    def test_path_traversal_rejected(self, storage):
        with pytest.raises(StorageError):
            storage.retrieve("../../etc/passwd")

    def test_delete(self, storage):
        content = b"To be deleted"
        sha = hashlib.sha256(content).hexdigest()
        f = io.BytesIO(content)
        key = storage.store(
            tenant_id=1,
            file_obj=f,
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="del.pdf",
        )
        assert storage.exists(key)
        storage.delete(key)
        assert not storage.exists(key)

    def test_tenant_prefixed_key(self, storage):
        content = b"tenant prefix test"
        sha = hashlib.sha256(content).hexdigest()
        key = storage.store(
            tenant_id=42,
            file_obj=io.BytesIO(content),
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="file.pdf",
        )
        assert key.startswith("42/")

    def test_original_filename_not_in_key(self, storage):
        content = b"private content"
        sha = hashlib.sha256(content).hexdigest()
        key = storage.store(
            tenant_id=1,
            file_obj=io.BytesIO(content),
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="confidential_report_2024.pdf",
        )
        assert "confidential_report_2024" not in key


class TestComputeSha256:
    def test_correct_sha256(self):
        content = b"hello world"
        expected = hashlib.sha256(content).hexdigest()
        assert compute_sha256(io.BytesIO(content)) == expected

    def test_rewinds_after(self):
        f = io.BytesIO(b"data")
        compute_sha256(f)
        assert f.tell() == 0
