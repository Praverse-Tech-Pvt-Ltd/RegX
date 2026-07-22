"""
Storage abstraction for the document platform.

Supported backends:
- LocalStorage  — for development and testing
- Future: S3-compatible backend (stubbed interface defined here)

Design rules:
- Original filename is stored as metadata only; never as the object key.
- Object keys are tenant-prefixed UUID-based paths.
- Checksum verification on store.
- Atomic upload: write to temp name then rename.
- Incomplete-upload cleanup hooks.
- No AWS credentials or bucket names hardcoded.
- Content never stored in the database.
"""

import abc
import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from django.conf import settings


class StorageError(Exception):
    pass


class ChecksumMismatchError(StorageError):
    pass


class StorageBackend(abc.ABC):
    """Abstract interface for document object storage."""

    @abc.abstractmethod
    def store(
        self,
        *,
        tenant_id: int,
        file_obj,
        expected_sha256: str,
        content_type: str,
        original_filename: str,
    ) -> str:
        """Store file_obj and return the storage key.

        Raises ChecksumMismatchError if the stored content does not match
        expected_sha256.
        """

    @abc.abstractmethod
    def retrieve(self, storage_key: str):
        """Return a file-like object for the given storage key."""

    @abc.abstractmethod
    def delete(self, storage_key: str) -> None:
        """Delete the object at storage_key."""

    @abc.abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Return True if the key exists in the store."""

    def presigned_url(self, storage_key: str, expiry_seconds: int = 3600) -> str:
        """Return a presigned URL for the key.

        Not exposed publicly in this milestone. Subclasses implementing
        S3-compatible storage should provide a real implementation.
        """
        raise NotImplementedError("Presigned URLs are not supported by this backend.")


class LocalStorage(StorageBackend):
    """Development and test storage using the local filesystem.

    Object keys: {tenant_id}/{uuid4}{.ext}
    Root: settings.DOCUMENT_LOCAL_STORAGE_ROOT
    """

    def __init__(self):
        self.root = Path(settings.DOCUMENT_LOCAL_STORAGE_ROOT)
        self.root.mkdir(parents=True, exist_ok=True)

    def _key_path(self, storage_key: str) -> Path:
        # Prevent path traversal: ensure key resolves inside root
        resolved = (self.root / storage_key).resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise StorageError("Invalid storage key — path traversal detected.")
        return resolved

    def store(
        self,
        *,
        tenant_id: int,
        file_obj,
        expected_sha256: str,
        content_type: str,
        original_filename: str,
    ) -> str:
        _, ext = os.path.splitext(original_filename)
        ext = ext.lower()
        object_name = f"{uuid.uuid4().hex}{ext}"
        storage_key = f"{tenant_id}/{object_name}"
        dest = self._key_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically via temp file in same directory
        fd, tmp_path = tempfile.mkstemp(dir=dest.parent)
        try:
            hasher = hashlib.sha256()
            file_obj.seek(0)
            with os.fdopen(fd, "wb") as f:
                while True:
                    chunk = file_obj.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)

            actual_sha256 = hasher.hexdigest()
            if actual_sha256 != expected_sha256:
                os.unlink(tmp_path)
                raise ChecksumMismatchError(
                    f"Checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
                )

            shutil.move(tmp_path, dest)
        except Exception:
            # Cleanup incomplete upload
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        return storage_key

    def retrieve(self, storage_key: str):
        path = self._key_path(storage_key)
        if not path.exists():
            raise StorageError(f"Object not found: {storage_key}")
        return open(path, "rb")

    def delete(self, storage_key: str) -> None:
        path = self._key_path(storage_key)
        if path.exists():
            path.unlink()

    def exists(self, storage_key: str) -> bool:
        return self._key_path(storage_key).exists()


class S3CompatibleStorage(StorageBackend):
    """Stub for future S3-compatible object storage.

    Configure with:
    - DOCUMENT_S3_BUCKET
    - DOCUMENT_S3_ENDPOINT_URL (for non-AWS providers)
    - Credentials via IAM role / instance profile (never hardcoded)
    """

    def store(self, *, tenant_id, file_obj, expected_sha256, content_type, original_filename):
        raise NotImplementedError("S3-compatible storage is not yet configured.")

    def retrieve(self, storage_key: str):
        raise NotImplementedError("S3-compatible storage is not yet configured.")

    def delete(self, storage_key: str) -> None:
        raise NotImplementedError("S3-compatible storage is not yet configured.")

    def exists(self, storage_key: str) -> bool:
        raise NotImplementedError("S3-compatible storage is not yet configured.")

    def presigned_url(self, storage_key: str, expiry_seconds: int = 3600) -> str:
        raise NotImplementedError("S3-compatible storage is not yet configured.")


def compute_sha256(file_obj) -> str:
    """Compute SHA-256 of file_obj content. Rewinds before and after."""
    file_obj.seek(0)
    hasher = hashlib.sha256()
    while True:
        chunk = file_obj.read(65536)
        if not chunk:
            break
        hasher.update(chunk)
    file_obj.seek(0)
    return hasher.hexdigest()


def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend instance."""
    backend = getattr(settings, "DOCUMENT_STORAGE_BACKEND", "local")
    if backend == "local":
        return LocalStorage()
    if backend == "s3":
        return S3CompatibleStorage()
    raise StorageError(f"Unknown storage backend: {backend}")
