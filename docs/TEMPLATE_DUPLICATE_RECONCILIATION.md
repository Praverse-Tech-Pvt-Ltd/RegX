# Template Duplicate Reconciliation

## Principle: detection generates candidates, humans resolve them

`find_duplicate_candidates_for_item()` runs deterministic matches only; it
never merges, deletes, or auto-collapses a `TemplateItem`. Every match it
finds becomes a `TemplateDuplicateCandidate` row with `resolution=pending`,
left for a Reviewer to explicitly resolve.

## Deterministic match types

| `DuplicateMatchType` | Basis |
|---|---|
| `canonical_code` | Same `canonical_item_code` within tenant scope |
| `legacy_identifier` | Same `legacy_identifier` |
| `normalized_text` | Same fully-normalized text |
| `exact_raw_checksum` / `exact_normalized_checksum` | Reserved for source-record-level exact matching |
| `fuzzy_similarity` | Reserved for future similarity scoring — review-only, must never auto-collapse |

Detection is idempotent: a rerun uses `get_or_create` keyed on
`(subject, suspected_match, match_type)`, so it never creates duplicate
candidate rows for the same pair.

## Resolution

A candidate's `resolution` moves from `pending` to one of `same` / `distinct`
/ `superseded` / `merge_approved`, set only via the review endpoint
(`POST /migration-batches/{id}/review/`, requires `templates.review`) with
the reviewer and reason recorded. Nothing in the pipeline transitions this
field automatically.

The review endpoint only resolves candidates that belong to the reviewed
batch's source package — a candidate `public_id` from another tenant, or
from a different source package in the same tenant, is not in scope and
returns a generic `404`. A review request is atomic: a single
foreign/invalid entry rejects the whole request before any candidate is
mutated. Each successful resolution emits a `DUPLICATE_CANDIDATE_RESOLVED`
audit event (candidate public ID, previous resolution, new resolution,
reviewer, reason, batch public ID, source-package public ID) inside the
same transaction as the mutation. See
[TEMPLATE_RECONCILIATION_REPORT.md](TEMPLATE_RECONCILIATION_REPORT.md#audit-events)
for the full audit-event definitions.

## Subject constraint

A `TemplateDuplicateCandidate` always identifies exactly one "new" side —
either `subject_source_record` (a not-yet-imported record) or
`subject_template_item` (an already-imported item), never both and never
neither. This is enforced by a DB-level `CheckConstraint`
(`duplicate_candidate_exactly_one_subject`), not just application logic.

## Future parameterized-template pattern (explicitly not implemented)

`TemplateItem.applicability_rule` (JSONField) is a placeholder reserved for a
future pattern where one canonical template definition is shared across
multiple parameter sets (e.g. an IIG-style checklist). No applicability-rule
evaluation logic exists in this milestone — IIG calculation is out of scope.

Verified by `templates_registry/tests/test_models.py::TestDuplicateCandidateExactlyOneSubject`,
`test_importer.py::TestDuplicateDetection`, and planted-failure scenario #10
(rerun does not create duplicates).
