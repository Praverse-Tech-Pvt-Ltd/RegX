# Document Versioning

## Model

Each `Document` has a `current_version` pointer (nullable OneToOne to `DocumentVersion`). All historical versions are accessible via `doc.versions.all()`.

`DocumentVersion.version_number` is a positive integer assigned atomically using `SELECT FOR UPDATE` on the parent document row. Version numbers are sequential and unique per document.

## Upload flow

1. POST `/api/regx/v1/documents/` — creates `Document` + `DocumentVersion` with `version_number=1`.
2. POST `/api/regx/v1/documents/<id>/versions/` — adds a new `DocumentVersion` to an existing `Document`. The document's `current_version` is updated atomically.

## Constraints

- Cannot upload a new version to an archived document (409 Conflict).
- Version numbers are immutable once assigned.
- `DocumentVersion` records are append-only; existing versions cannot be modified.

## Duplicate detection

On each upload the SHA-256 checksum is compared against all existing versions in the same tenant. If a match is found, a `DocumentDuplicateLink` is created. Cross-tenant checksums are never compared or disclosed.

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/regx/v1/documents/<id>/versions/` | List all versions (newest first) |
| POST | `/api/regx/v1/documents/<id>/versions/` | Upload new version |
| GET | `/api/regx/v1/documents/<id>/versions/<vid>/` | Version detail |
| GET | `/api/regx/v1/documents/<id>/versions/<vid>/status/` | Scan + processing status |
| GET | `/api/regx/v1/documents/<id>/versions/<vid>/locators/` | Extracted locators |
