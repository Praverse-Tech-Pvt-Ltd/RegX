# Template Approval Lifecycle

## State machine

```
draft/imported --submit_for_review--> under_review
under_review    --return_for_correction--> returned
under_review    --approve--> approved
under_review    --reject--> rejected
returned        --submit_for_review--> under_review
approved        --activate--> active   (supersedes any prior active version)
active          --supersede--> superseded
active/superseded --retire--> retired
```

All transitions live in `lifecycle.py`, each wrapped in a single
`transaction.atomic()` block with `select_for_update()` on the version (and,
for activation, the template and its sibling active versions). Invalid
transitions raise `InvalidTransition`, surfaced as a `400` through the API.

## Invariants

- **Imported content starts inactive.** `import_eligible_records()` never
  creates or transitions to an `ACTIVE` status — every imported version
  starts `IMPORTED`.
- **Only an approved version may activate.** `lifecycle.activate()` raises
  `InvalidTransition` unless `status == APPROVED`.
- **Only one active version per template.** Enforced twice: `activate()`
  transactionally supersedes any prior active sibling under
  `select_for_update()`, *and* a DB-level partial unique index
  (`unique_active_version_per_template`, `UniqueConstraint` with
  `condition=Q(status=ACTIVE)`) makes a second concurrently-active version
  impossible even if a future code path bypasses the service layer.
- **Approved/active/superseded/retired versions are immutable.**
  `TemplateVersion.clean()` compares against the persisted original and
  raises `ValidationError` if any field other than `status`,
  `superseded_date`, or `updated_at` changed while the original status was
  one of those four. Corrections require a new `TemplateVersion`, never an
  edit.
- **Segregation of duties.** `lifecycle.approve()` raises
  `PermissionDenied` if the approver is the version's own `created_by` —
  a reviewer/doer cannot approve their own submission.
- **Supersession preserves history.** `activate()`'s automatic supersession
  and the explicit `supersede()` action both set `status=SUPERSEDED` and
  `superseded_date`; no row is ever deleted.
- **Retirement doesn't delete history.** `retire()` only changes `status`
  (and clears `template.current_approved_version` if it pointed at the
  retired version); the row and its full approval trail remain queryable.
- **Rejection preserves the trail.** `reject()` records a `TemplateApproval`
  row before transitioning to `REJECTED` — the review history survives.
- **Every decision is audited.** Each transition emits an `AuditEvent` and,
  for review/approve/reject/return, a sequential `TemplateApproval` row
  (`approval_sequence` increments per version).

## Permission → transition mapping

| Transition | Required permission |
|---|---|
| Submit for review | `templates.inventory` |
| Approve / Reject | `templates.approve` |
| Return for correction | `templates.review` |
| Activate | `templates.activate` |
| Supersede | `templates.supersede` |
| Retire | `templates.retire` |

Verified by `templates_registry/tests/test_lifecycle.py` and planted-failure
scenarios #3, #5, and #6 in `test_planted_failures.py`.
