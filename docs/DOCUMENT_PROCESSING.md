# Document Processing

## Pipeline

Processing runs as two chained Celery tasks after upload:

```
scan_document_version(version_pk, tenant_id)
  ↳ clean → process_document_version(version_pk, tenant_id)
  ↳ infected → QUARANTINED, processing SKIPPED
  ↳ scan_failed → retry up to MAX_SCAN_ATTEMPTS=3
```

## Scan task (`scan_document_version`)

- Fail-closed: scan failures do NOT mark the file clean.
- Retrieves the file from storage, passes it to the configured scanner backend.
- On clean: sets `scan_status=CLEAN`, triggers `process_document_version.delay`.
- On infected: sets `scan_status=QUARANTINED`, `processing_status=SKIPPED`, emits `SCAN_INFECTED` + `QUARANTINED` audit events.
- On scan failure (transient): retries up to 3 times with a 30-second delay.

## Processing task (`process_document_version`)

- Guards: `scan_status` must be `CLEAN` before any processing begins.
- Idempotent: `processing_status=COMPLETE` short-circuits.
- Uses `DocumentProcessingJob` to bound retries to `MAX_PROCESS_ATTEMPTS=3`.
- Extracts locators per format:

| Format | Locator types created |
|---|---|
| PDF | One `PAGE` locator per page with extracted text |
| DOCX | `SECTION` (headings), `PARAGRAPH`, `TABLE` |
| XLSX | One `SHEET` locator per worksheet |
| PPTX | One `SLIDE` locator per slide |

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `DOCUMENT_SCANNER_BACKEND` | `stub` | Scanner backend (`stub` or `clamav`) |
| `DOCUMENT_CLAMAV_HOST` | `127.0.0.1` | ClamAV host |
| `DOCUMENT_CLAMAV_PORT` | `3310` | ClamAV TCP port |
| `CELERY_TASK_ALWAYS_EAGER` | `False` | Set `True` in tests for synchronous execution |
