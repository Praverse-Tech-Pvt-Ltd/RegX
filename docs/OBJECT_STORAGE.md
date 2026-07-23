# Object Storage

## Abstraction

The storage layer is accessed via `documents.storage.get_storage_backend()`, which returns either `LocalStorage` or `S3CompatibleStorage` based on the `DOCUMENT_STORAGE_BACKEND` setting.

## LocalStorage

- Files stored under `DOCUMENT_LOCAL_STORAGE_ROOT/<tenant_id>/<uuid>.<ext>`.
- Atomic write: file is written to a temp file then moved with `shutil.move`.
- Checksum verification: SHA-256 is computed after write and compared to `expected_sha256`. Mismatch raises `ChecksumMismatchError` and the file is deleted.
- Path traversal prevention: resolved path is checked to be within the storage root via `Path.resolve()`.

## S3CompatibleStorage

A stub that raises `NotImplementedError` on all operations. Replace with a boto3/S3-compatible implementation before enabling in production.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `DOCUMENT_STORAGE_BACKEND` | `local` | `local` or `s3` |
| `DOCUMENT_LOCAL_STORAGE_ROOT` | `<BASE_DIR>/document_storage` | Root for local file storage |
| `DOCUMENT_MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Max upload size in bytes |

## Storage key format

`<tenant_id>/<uuid4>.<extension>` — opaque to callers; only the storage backend resolves this to a file path or S3 key.
