# Document Test Strategy

## Test categories

| Category | File | Count |
|---|---|---|
| Upload validation | `documents/tests/test_validators.py` | ~30 |
| Storage | `documents/tests/test_storage.py` | ~10 |
| Scanner | `documents/tests/test_scanner.py` | ~8 |
| Models | `documents/tests/test_models.py` | ~8 |
| Permissions | `documents/tests/test_permissions.py` | ~10 |
| Celery tasks | `documents/tests/test_tasks.py` | ~10 |
| API / tenant isolation | `documents/tests/test_api.py` | ~20 |

## Planted violations

Security tests follow a planted-violation pattern: the test comment `# PLANTED:` marks the deliberately bad input that must be rejected, and a `# RESTORE:` marks the equivalent valid input that must pass. This ensures guards are tested against realistic adversarial inputs, not just error-path coverage.

Examples:
- Path traversal: `../../etc/passwd.pdf` rejected with `path_traversal` code
- MIME mismatch: JPEG bytes declared as `application/pdf`
- Cross-tenant access: user A requesting tenant B's document expects 404
- Quarantine access: locators endpoint on quarantined version expects 403

## Fixtures

Synthetic files only — no real client documents:

| File | Purpose |
|---|---|
| `valid.pdf` | Minimal valid PDF for happy-path tests |
| `valid.docx` | Minimal valid DOCX |
| `valid.xlsx` | Minimal valid XLSX |
| `valid.pptx` | Minimal valid PPTX |
| `mime_mismatch.pdf` | JPEG bytes named `.pdf` |
| `corrupt_office.docx` | Corrupt ZIP / bad Office container |
| `macro_document.docm` | Macro-enabled Office file (rejected) |
| `duplicate.pdf` | Used for duplicate detection tests |

## Configuration in tests

- `CELERY_TASK_ALWAYS_EAGER=True` — tasks run synchronously in tests
- `DOCUMENT_STORAGE_BACKEND=local` with `tmp_path` — no S3 required
- `DOCUMENT_SCANNER_BACKEND=stub` (default) — no clamd required
- `X-Tenant-Slug` header set via `client.credentials(HTTP_X_TENANT_SLUG=...)`
- `SimpleUploadedFile` used for all file uploads (not raw `io.BytesIO`) to supply `.name` attribute

## Running document tests

```bash
cd backend
pytest documents/ -v
```
