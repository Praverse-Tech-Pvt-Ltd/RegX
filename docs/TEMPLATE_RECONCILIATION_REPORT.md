# Template Reconciliation Report

## Purpose

A per-migration-batch report proving what happened to every source record:
what was expected, what was extracted, what imported cleanly, what was
excluded and why, what needs human review, and what the current approval
state is. This is a governance artifact, not a final branded deliverable —
PDF/Word report generation is explicitly out of scope this milestone.

## Endpoints

| Endpoint | Format | Permission |
|---|---|---|
| `GET /migration-batches/{id}/reconciliation.json` | JSON | `templates.review` OR `templates.export_reconciliation` |
| `GET /migration-batches/{id}/reconciliation.csv` | CSV (records only) | `templates.export_reconciliation` |

Viewing the JSON report (needed to make review decisions) and formally
exporting/downloading a file are treated as distinct actions: a Reviewer can
view the report to do their job, but only VP/Tenant Admin — the roles
holding `templates.export_reconciliation` — can download it as a file.

## Report shape (JSON)

```json
{
  "batch": {"correlation_id", "public_id", "status", "started_at", "completed_at"},
  "source_package": {"public_id", "source_name", "source_checksum"},
  "counts": {
    "expected_records", "extracted_records", "imported", "excluded",
    "duplicate", "failed", "requires_review", "unmatched"
  },
  "records": [{"source_record_identifier", "target_public_identifier", "result", "reason_code", "safe_detail"}],
  "unmatched_records": [{"source_record_identifier", "migration_disposition"}],
  "normalization_mappings": [/* NormalizationMappingSerializer shape */],
  "duplicate_candidates": [/* TemplateDuplicateCandidateSerializer shape */],
  "approvals": [{"template_version", "reviewer", "decision", "approval_sequence", "role_at_time"}]
}
```

`normalization_mappings` and `duplicate_candidates` are serialized through
the same `NormalizationMappingSerializer` / `TemplateDuplicateCandidateSerializer`
used elsewhere in the API, so every entry carries a `public_id` — required
for the frontend's duplicate-resolution flow (see
`TEMPLATE_DUPLICATE_RECONCILIATION.md`) to reference and resolve individual
candidates.

## CSV

The CSV export is a minimal, per-record table
(`source_record_identifier, target_public_identifier, result, reason_code`)
for reviewers who want a flat spreadsheet view. It is a strict subset of the
JSON report's `records` array, not a separate data source.

## What this report does not do

- No branded PDF/Word generation.
- No AI-generated summary text.
- No automatic sign-off — the `approvals` array reflects decisions already
  made through the lifecycle endpoints, it doesn't grant any itself.
