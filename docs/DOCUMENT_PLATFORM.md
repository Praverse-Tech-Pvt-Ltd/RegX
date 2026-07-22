# Document Platform

## Overview

The document platform provides tenant-scoped secure storage, versioning, and processing for PDF, DOCX, XLSX, and PPTX files.

## Architecture

```
Upload request
  → TenantMiddleware (resolves X-Tenant-Slug)
  → DRF view (validates permissions)
  → UploadValidator (security checks)
  → LocalStorage / S3CompatibleStorage (persists file)
  → DocumentVersion (record created)
  → scan_document_version (Celery task)
      → malware scan
      → process_document_version (Celery task)
          → format-specific extractor
          → DocumentLocator records
```

## Models

| Model | Purpose |
|---|---|
| `Document` | Logical document with a title, type, and current version pointer |
| `DocumentVersion` | Immutable upload record (filename, checksum, scan/processing status) |
| `DocumentLocator` | Extracted structure unit (page, section, paragraph, sheet, slide) |
| `DocumentProcessingJob` | Processing task record with retry tracking |
| `DocumentDuplicateLink` | Same-tenant checksum duplicate links |

## Key invariants

- Public IDs (UUID) are the only identifiers exposed in API responses. Internal BIGINT PKs are never serialized.
- `storage_key` is never exposed in any API response.
- Cross-tenant document access returns 404, not 403, to avoid existence disclosure.
- Quarantined versions block locator access (403).
- Processing begins only after a clean scan result.
- Duplicate detection is scoped to the same tenant; cross-tenant matches are not disclosed.
