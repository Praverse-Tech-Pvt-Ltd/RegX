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

## CSV export

The CSV export is a minimal, per-record table
(`source_record_identifier, target_public_identifier, result, reason_code`)
for reviewers who want a flat spreadsheet view. It is a strict subset of the
JSON report's `records` array, not a separate data source.

### CSV export safety (spreadsheet formula-injection neutralization)

Reconciliation CSV files are generated with Python's standard
`csv.writer`, which handles quoting and escaping of commas, quotes, and
embedded newlines through normal CSV quoting. On top of that, every
untrusted cell value is passed through a neutralization step **at export
render time** before it is written:

- A value is neutralized when its *effective first character* — the first
  character after any plain leading spaces are skipped — is one of:
  `=`, `+`, `-`, `@`, tab, carriage return, or line feed (where
  applicable). These are the characters a spreadsheet application may
  interpret as the start of a formula or dynamic-data expression.
- Neutralization prefixes the value with a single apostrophe (`'`), the
  standard spreadsheet "force text" marker. The original characters are
  preserved after the apostrophe.
- **Leading spaces do not bypass the control** — they are skipped before
  the first-character check, so a value such as `"   =cmd..."` is still
  neutralized.
- The neutralization is applied to every user-influenceable column, not
  only the field a value was first observed in.

This is applied only to the rendered CSV output. **The database-stored raw
values are never modified** — for example, a source record whose
identifier is literally `=1+1` keeps that exact value in the database; only
its rendered CSV cell is prefixed. The behavior is verified by
`templates_registry/tests/test_review_remediation.py`
(`TestCsvFormulaInjectionNeutralization`).

The **JSON** reconciliation output does **not** apply CSV-specific
neutralization: JSON is consumed as structured data, not opened directly in
a spreadsheet, so the apostrophe-prefix marker would be inappropriate
there. Its values are the unmodified stored values.

This control is a defense-in-depth measure designed to reduce the risk of
spreadsheet formula/DDE injection (CWE-1236). It is **not** a guarantee
that every spreadsheet application, version, or import configuration will
render every value inertly. Exported reconciliation data must still be
treated as untrusted content and handled through the organization's
controlled data-handling practices.

## Audit events

### `RECONCILIATION_EXPORTED`

Emitted once per **successful** reconciliation export, for both the CSV and
JSON endpoints, through the standard append-only audit framework
(`audit_events.emit()` → `AuditEvent`). Recorded metadata:

- actor (the authenticated user performing the export);
- tenant;
- migration-batch public ID (the audit record's `resource_id`);
- source-package public ID;
- export format (`"csv"` or `"json"`);
- the report's safe result counts (imported / excluded / duplicate /
  failed / requires-review / unmatched, etc.);
- correlation information through the standard audit framework (the batch
  public ID correlates every event for a batch; a batch also carries its
  own `correlation_id`);
- timestamp (recorded automatically by the audit framework).

Behavioral guarantees:

- The **exported payload itself is not stored** in the audit metadata —
  only the safe counts and identifiers above are recorded, never the
  reconciliation rows or any raw source content.
- An **unauthorized export** (a caller lacking
  `templates.export_reconciliation`, e.g. a Doer against the CSV endpoint)
  is rejected before any export event is written — no successful export
  event is created.
- A **cross-tenant export attempt** resolves to a generic `404` (the batch
  is not visible in the caller's tenant) before any export event is
  written — no successful export event is created.
- Audit records remain subject to the existing append-only audit controls
  (`AuditEvent` rows cannot be updated or deleted).

### `DUPLICATE_CANDIDATE_RESOLVED`

Emitted once per duplicate candidate successfully resolved through the
migration-batch review endpoint, inside the same database transaction as
the mutation it describes (so a rejected/atomic review request rolls back
its audit events along with its would-be mutations — no misleading success
event survives a rejected request). Recorded metadata:

- candidate public ID (the audit record's `resource_id`);
- previous resolution (the value before this decision);
- new resolution (`same` / `distinct` / `superseded` / `merge_approved`);
- reviewer (the authenticated actor);
- reason (the reviewer-supplied justification, if any);
- migration-batch public ID;
- source-package public ID.

As with export events, the audit payload records the decision and the
identifiers only — never the candidate's raw source content.

## What this report does not do

- No branded PDF/Word generation.
- No AI-generated summary text.
- No automatic sign-off — the `approvals` array reflects decisions already
  made through the lifecycle endpoints, it doesn't grant any itself.
