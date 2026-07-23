# Document API

Base path: `/api/regx/v1/documents/`

All requests require authentication (session cookie) and `X-Tenant-Slug` header.

## Endpoints

### List documents
`GET /api/regx/v1/documents/`

Query parameters: `status` (active|archived), `document_type` (pdf|docx|xlsx|pptx), `page`.

Permission: `document:view`

### Create document
`POST /api/regx/v1/documents/`

Multipart form: `title` (string), `document_type` (pdf|docx|xlsx|pptx), `file` (file).

Returns: Document object with `public_id`. No `storage_key` or internal `id` in response.

On validation failure: HTTP 422 with `code` and `detail` fields.

Permission: `document:create`

### Get document
`GET /api/regx/v1/documents/<public_id>/`

Permission: `document:view`

### Archive document
`POST /api/regx/v1/documents/<public_id>/archive/`

Permission: `document:archive`

### Restore document
`POST /api/regx/v1/documents/<public_id>/restore/`

Permission: `document:archive`

### List versions
`GET /api/regx/v1/documents/<public_id>/versions/`

Permission: `document:view`

### Upload new version
`POST /api/regx/v1/documents/<public_id>/versions/`

Multipart form: `file` (file). Cannot upload to an archived document (409).

Permission: `document:upload_version`

### Get version detail
`GET /api/regx/v1/documents/<public_id>/versions/<version_public_id>/`

Permission: `document:view_previous_versions`

### Get version status
`GET /api/regx/v1/documents/<public_id>/versions/<version_public_id>/status/`

Returns `scan_status` and `processing_status` for polling.

Permission: `document:view_processing_status`

### List locators
`GET /api/regx/v1/documents/<public_id>/versions/<version_public_id>/locators/`

Returns paginated `DocumentLocator` objects. Returns 403 if the version is quarantined.

Query parameter: `locator_type` to filter by type.

Permission: `document:view`

## Security notes

- Internal BIGINT PKs are never returned.
- `storage_key` is excluded from all serializers.
- Cross-tenant access returns 404, not 403 (no existence disclosure).
- Quarantined version locators return 403.
