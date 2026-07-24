# Template Source Packages

## Purpose

A `TemplateSourcePackage` is a registered, checksummed batch of controlled
source material staged for import. Registration alone imports nothing —
it only records provenance and runs the content-exclusion guard.

## Registration flow

```
legacy source (SQLite table, spreadsheet, etc.)
  → controlled export (JSON/CSV/DB extract) -- performed outside REGX
  → checksum the export payload (sha256)
  → POST /api/regx/v1/template-sources/
      { source_name, source_type, source_path_or_reference,
        source_version?, source_date?, licensing_ownership_status?,
        payload }
  → classify_source_package(source_type, source_name)
      -- rejects 483/warning-letter/AIDatabase/inspection-analytics
         declared types or names before anything is persisted
  → TemplateSourcePackage row created (get_or_create keyed on
    tenant + source_checksum -- re-registering the same export is a no-op)
```

REGX never queries a live legacy database. The only inputs accepted are
already-exported, static payloads.

## Fields

| Field | Notes |
|---|---|
| `source_name` / `source_type` | Free text + the classification key checked against the exclusion guard |
| `source_path_or_reference` | Where the export came from — visible only to holders of `templates.view_raw` |
| `source_checksum` | sha256 of the checksum payload; unique per tenant |
| `approval_state` | pending / approved / rejected — tracks whether the *source itself* (as opposed to individual template content) has been cleared for use |
| `imported_by` / `imported_at` | Provenance |

## Exclusion guard

`classify_source_package()` rejects a package before it is ever persisted if
its declared `source_type` or `source_name` matches:

- `form483` / `483` / any "483 observation" pattern
- `warning_letter` / "warning letter"
- `aidatabase` / any name containing "AIDatabase"
- `inspection_analytics` / `paca` / "root cause inspection" / "investigator
  intelligence"

A rejected registration raises `SourceExcluded` and the API returns `400` —
nothing is written to the database. This is a package-level guard; individual
records within an otherwise-eligible package are separately classified during
the import pipeline (see `TEMPLATE_IMPORT_PIPELINE.md`).

## Visibility

The default (non-raw) serializer for a source package excludes
`source_path_or_reference`, `file_metadata`, and `licensing_ownership_status`.
Only requesters holding `templates.view_raw` (Reviewer, VP, Tenant Admin) see
the raw variant.
