# Workflow Evidence

**Governed links from workflow items to exact document versions.**

> **Not regulatory approval.** No approved production regulatory content, no
> 21 CFR Part 11 compliance, not a validated system. Linking a document as
> evidence is a record that it was cited — it is not an approval, an attestation
> or an electronic signature.

Implemented against `regx-main` `70267448506d30cef30c28b0536f78cc5c1f47bb`.
Design rationale: [`MILESTONE_7_WORKFLOW_EVIDENCE_DISCOVERY.md`](MILESTONE_7_WORKFLOW_EVIDENCE_DISCOVERY.md).

---

## 1. What it links, and why that matters

`WorkflowEvidence` holds a foreign key to **`DocumentVersion`** — never to
`Document`.

`DocumentVersion` is immutable once processed and carries its own
`sha256_checksum`, so a link identifies **specific bytes**. `Document` is a
mutable container whose "latest" moves as versions are uploaded; linking it
would mean *"whatever this document says today"*, and the meaning of historical
evidence would change under it.

The consequence is structural rather than procedural:

> Link version 3, then upload version 4. The evidence still says version 3,
> because there is no "latest" pointer to follow. There is no *"move to latest"*
> behaviour to suppress — it cannot occur.

Changing which version a workflow cites requires unlinking and linking again,
which is a governed action recorded in audit, and only possible while the item
is in `DRAFT`.

Tested both ways: a newer version with different bytes leaves the existing link
untouched, and a raw SQL attempt to repoint the FK is rejected by the database.

---

## 2. No file duplication

The document platform remains the **sole owner** of storage, checksum, scan
status, processing status, versioning and retrieval.

Evidence stores references and its own metadata: which version, which workflow,
who linked it, when, and an optional label. A test asserts that no
`storage_key`, `sha256_checksum`, `size_bytes`, `content` or `file` field exists
on the model, so duplication cannot creep in later.

**There is no upload path in workflows.** The UI says so and links to the
Documents module.

---

## 3. Two authorization gates

**This is the invariant that most needs stating.** Workflow permission and
document permission are **separate checks, and neither implies the other**.

| Capability | Requires |
|---|---|
| See a workflow's evidence list | `workflows.view` |
| Link or unlink evidence | `workflows.manage_evidence` **and** `documents.view` |
| See document detail on a link | `documents.view` |

A caller with workflow access but no document permission sees **that** evidence
exists — public IDs, label, who linked it and when — and **no document detail**:
no title, no filename, no checksum, no scan status.

This is a live configuration, not a hypothetical. `PLATFORM_SUPPORT` holds
`workflows.view` and its document permission list is literally empty
(`Role.BuiltIn.PLATFORM_SUPPORT: []  # no document content access`). A test
drives exactly that role and asserts the document title never reaches the
response.

Linking is gated twice on purpose: citing a document is an assertion about it,
so the caller must be entitled to the document, not merely to the workflow.

---

## 4. Security gate

A version may be linked only if `scan_status == CLEAN`.

This **reuses `documents.ScanStatus`**; no new security status is invented. It
is deliberately stricter than the document platform's serve-time check, which
blocks only `QUARANTINED`:

| Status | Serve | Link as evidence |
|---|---|---|
| `CLEAN` | allowed | **allowed** |
| `PENDING` | allowed | refused |
| `INFECTED` | allowed¹ | refused |
| `SCAN_FAILED` | allowed¹ | refused |
| `SCANNER_UNAVAILABLE` | allowed¹ | refused |
| `QUARANTINED` | refused | refused |

¹ per the existing view, which only special-cases `QUARANTINED`.

Serving a `PENDING` version to the person who just uploaded it is reasonable.
Citing it as governed evidence while a scan has not concluded is not, and
`INFECTED`, `SCAN_FAILED` and `SCANNER_UNAVAILABLE` are non-conclusions rather
than clearances.

**Fail closed**: anything that is not `CLEAN` is refused.

---

## 5. Tenant isolation

Every query is scoped through `document__tenant` (versions) and `tenant`
(evidence). A version belonging to another tenant cannot be linked.

**Three different failures produce one identical message:**

- no such version;
- a version in another tenant;
- a version that is not security-cleared.

Distinct wording would let a caller probe for documents outside their tenant,
and would disclose the scan state of a document they cannot see. Two tests
assert the indistinguishability directly.

Cross-tenant evidence reads and unlinks return **404**, consistent with the rest
of the repository.

---

## 6. Workflow state rules

| State | Evidence |
|---|---|
| `DRAFT` | **link and unlink allowed** |
| `SUBMITTED` | locked |
| `IN_REVIEW` | locked |
| `REJECTED` | locked — `return_to_draft` first |
| `APPROVED` | **permanent** |
| `CANCELLED` | **permanent** |

Reading is always permitted, subject to §3.

This matches the engine's existing reasoning: `update_draft` already refuses to
edit a non-`DRAFT` item because content must not change under a reviewer.
Evidence is content. `REJECTED` items reopen through the existing
`return_to_draft` transition, which is governed and recorded, rather than
through a private back door here.

Attempting a locked mutation returns **409** with the current state.

---

## 7. History

**Unlinking never deletes a row.** It stamps `unlinked_at` and `unlinked_by`, so
the historical fact that a version was once cited survives.

Deleting the row and relying on `AuditEvent` alone was considered and rejected:
audit records the *action*, but a governed evidence set should be directly
queryable, not reconstructable only by replaying events.

A partial `UniqueConstraint` on `(workflow_item, document_version)` where
`unlinked_at IS NULL` permits relinking after an unlink while forbidding
duplicates.

### Database-level protection

Migration `0005` installs a PostgreSQL guard, following `audit/0001_initial.py`
and `workflows/0003` — the same plpgsql shape, no new mechanism.

It is **deliberately not identical** to those two. They forbid every `UPDATE`;
evidence must permit exactly one — the unlink stamp. So the trigger:

- forbids `DELETE` outright;
- forbids any `UPDATE` to an already-unlinked row;
- forbids changing any column other than the two unlink stamps;
- forbids clearing the stamps back to `NULL`.

The effect is append-only with one permitted transition: a row moves
active → unlinked once, and nothing else ever changes. ORM-level guards on the
manager remain as defence in depth.

---

## 8. Deletion protection

`WorkflowEvidence.document_version` is `on_delete=PROTECT`, **and** the app
registers a checker with the existing `DeletionProtectionRegistry` from
`AppConfig.ready()` — the same mechanism `iig_checklist` uses, which keeps the
dependency one-way so `documents` never imports `workflows`.

Two independent defences, matching how the repository already guards governed
references.

The checker deliberately counts **unlinked rows too**: the historical record
that a version was cited is itself governed, and deleting the version would
strand it.

Note also that the document API offers **archive and restore, not delete**, so
evidence cannot become dangling through ordinary product use. The protection
covers programmatic and administrative paths.

---

## 9. Concurrency

Two callers linking the same version to the same item simultaneously produce
**exactly one** active link. The partial unique constraint makes the database
the arbiter; the loser receives a deterministic `DuplicateEvidence` → **409**.

Proven with a barrier-synchronised threaded test, `transaction=True` so real
constraints apply.

---

## 10. Audit

`workflow.evidence_linked` and `workflow.evidence_unlinked`, through the
existing allow-list emitter — new keys must be added to
`_ALLOWED_PAYLOAD_KEYS` or they cannot be written at all.

Recorded: `workflow_public_id`, `document_public_id`,
`document_version_public_id`, `evidence_public_id`, `action`.

**The filename is never recorded.** `original_filename` is user-supplied and can
itself disclose subject matter — a poor thing to place in an audit row whose
retention differs from the document's. Public IDs resolve to it for anyone
holding `documents.view`, which is the correct gate. A test links a document
titled `SECRET_PROJECT_CODENAME` and asserts it never appears in the payload.

Also never recorded: document contents, request bodies, tokens, credentials.

---

## 11. API

| Method | Path | Purpose |
|---|---|---|
| GET | `workflows/{id}/evidence/` | list active links |
| POST | `workflows/{id}/evidence/` | link a version |
| DELETE | `workflows/{id}/evidence/{evidence_id}/` | unlink |

`public_id` only; no internal PK is exposed, and the FK id is never serialised.

**409** for a locked state or a duplicate, **403** for a permission failure,
**400** for an unavailable version, **404** for anything outside the tenant.

---

## 12. Migrations and rollback classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4. Forward
risk and rollback risk are different questions.

| Migration | Forward | Rollback |
|---|---|---|
| `0004` — create `WorkflowEvidence` | additive, no `RunPython`, no destructive operation | **CLASS C once evidence data exists** |
| `0005` — immutability guard | additive: two functions, two triggers | **Class A** |

> ### `workflows/0004` is CLASS C — DATA RESTORE REQUIRED
>
> Once any evidence row exists, reversing `0004` **drops the table and destroys
> the governed record of which document versions were cited**, including the
> history of links since retired.
>
> **Do not backward-migrate `0004` merely because Django marks `CreateModel`
> reversible.** Django is describing the schema, not the value of what it holds.
>
> Use **Level 3 data restore**, not a backward migration.

`0005` is Class A on its own terms: its `reverse_sql` drops only the two
functions and two triggers it created, touching no row. **It does not make
reversing `0004` safe** — a rollback that drops the table takes the guard with
it.

Same distinction the runbook draws for `iig_checklist/0006` and
`workflows/0002`: structurally reversible, not data-safe to reverse.

---

## 13. Known limitations

- **No upload from workflows**, by design — §2.
- **No comments thread.** Evidence carries a short label, not discussion.
- **Version changes are manual**: unlink and relink, only in `DRAFT`. There is
  no "update to latest version" action, deliberately.
- **`canManage` in the UI is advisory.** It decides whether a control renders;
  the API re-checks both gates on every call.
- **The link form takes a version UUID.** There is no document picker yet, so in
  practice a user copies the id from the Documents module.
- **No evidence-history view.** Unlinked rows are retained and auditable but are
  not surfaced in the UI; the list shows active links only.
- **`scan_status` is evaluated at link time.** A version that is `CLEAN` when
  linked and later re-classified stays linked; nothing re-validates existing
  evidence.

---

## 14. Non-goals

No AI summarisation. No Word integration. No new malware or security status. No
new immutability mechanism. No duplication of document storage.

**No production regulatory content**, no Item 1 resolution, no change to the
0/20 governance count, no policy decision, no S-1/S-2 closure, no Part 11 or
validated-process claim.
