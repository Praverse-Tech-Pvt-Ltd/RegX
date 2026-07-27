"""
Thin wrapper around documents.storage for platform-level FDA source files.

FDA data releases are not tenant-owned, but documents.storage.store()
requires a tenant_id to compute its object key. PLATFORM_STORAGE_TENANT_ID
is a reserved pseudo-tenant-id namespace (not a real Tenant row) used only
to keep FDA source files in their own storage-key prefix, separate from any
real tenant's documents. This module never modifies documents/storage.py.
"""

from documents.storage import compute_sha256, get_storage_backend

PLATFORM_STORAGE_TENANT_ID = 0


def store_fda_source_file(
    *, file_obj, expected_sha256: str, content_type: str, original_filename: str
) -> str:
    backend = get_storage_backend()
    return backend.store(
        tenant_id=PLATFORM_STORAGE_TENANT_ID,
        file_obj=file_obj,
        expected_sha256=expected_sha256,
        content_type=content_type,
        original_filename=original_filename,
    )


def retrieve_fda_source_file(storage_key: str):
    backend = get_storage_backend()
    return backend.retrieve(storage_key)


__all__ = [
    "PLATFORM_STORAGE_TENANT_ID",
    "compute_sha256",
    "retrieve_fda_source_file",
    "store_fda_source_file",
]
