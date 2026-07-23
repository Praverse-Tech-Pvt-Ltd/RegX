# Template Import Pipeline

## Staged pipeline

```
1.  register_source_package()   -- checksum + package-level exclusion guard
2.  create_migration_batch()    -- one MigrationBatch per run, correlation_id
3.  extract_records()           -- idempotent: get_or_create per source_record_identifier
4.  (raw text/payload/locator/checksum/encoding preserved verbatim at extraction)
5.  classify_records()          -- per-record exclusion guard (483/AIDatabase/etc.)
6.  (eligible records proceed; excluded records get a MigrationRecordResult
     of EXCLUDED and stop here)
7.  import_eligible_records()   -- per-record normalization + duplicate detection
8.  (duplicate candidates recorded as pending review, never auto-merged)
9.  (import target: TemplateItem under a new DRAFT/IMPORTED TemplateVersion --
     never an existing approved/active version)
10. reconciliation report available (JSON/CSV) any time after step 9
11. regulatory review (MigrationBatchReviewView -- duplicate-candidate resolution)
12. approval (lifecycle.approve, requires templates.approve)
13. controlled activation (lifecycle.activate, requires templates.activate)
```

`run_migration_batch()` is a convenience wrapper running steps 3, 5, and 7 in
sequence for a single API call; steps 11-13 are always separate, explicit,
audited actions.

## Idempotency and safe retry

- `extract_records()` uses `get_or_create` keyed on
  `(source_package, source_record_identifier)` — rerunning with the same
  input list never creates a second `TemplateSourceRecord`.
- `import_eligible_records()` skips any source record that already has a
  `MigrationRecordResult` for this batch, so a retried or re-triggered batch
  never re-imports the same record or creates a duplicate `TemplateItem`.
- `TemplateItem` creation itself is `get_or_create` keyed on
  `(template_section, canonical_item_code)`.
- A mid-batch exception during a single record's import is caught, recorded
  as a `FAILED` `MigrationRecordResult` for that record only, and does not
  abort the rest of the batch (see `import_eligible_records`'s per-record
  `transaction.atomic()` block).
- A batch-level exception (e.g. during extraction) marks the whole batch
  `FAILED` with `error_summary` set, and re-raises.

Verified by `templates_registry/tests/test_importer.py::TestIdempotentRerun`
and the corresponding planted-failure scenario #10 in
`templates_registry/tests/test_planted_failures.py`.

## Transaction boundaries and audit events

- Every stage transitions `MigrationBatch.status` and persists a running
  `counts` dict (extracted/eligible/excluded/imported/requires_review/failed).
- Every meaningful event (package registered, batch started/completed/
  failed, record extracted/excluded, normalization applied, duplicate
  candidate created/resolved, version imported/submitted/approved/rejected/
  activated/superseded/retired) emits an immutable `AuditEvent` via
  `audit_events.emit()`.
- Tenant scope is carried explicitly on `MigrationBatch.tenant` /
  `TemplateSourcePackage.tenant` (nullable for platform-level master content)
  — there is no ambient/implicit tenant context inside the pipeline itself.

## What the pipeline never does

- Never activates imported content automatically (imported/draft versions
  stay inactive until an explicit `lifecycle.approve()` + `lifecycle.activate()`
  walk).
- Never mutates `raw_text`/`raw_payload` on a `TemplateSourceRecord` —
  normalization always produces a *new* value recorded in a
  `NormalizationMapping` row.
- Never silently collapses duplicate candidates — see
  `TEMPLATE_DUPLICATE_RECONCILIATION.md`.
