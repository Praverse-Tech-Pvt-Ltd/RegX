# Milestone 7 — Workflow Evidence Discovery

**Discovery only. No code changed.**

Surveyed against `regx-main` `70267448506d30cef30c28b0536f78cc5c1f47bb` — the
Milestone 6 merge commit.

As with Milestone 6, the finding is that the hard parts are already solved. The
document platform already provides immutable versions, a deletion-protection
registry built precisely for this case, and a tenant-scoped reference precedent.
Milestone 7 connects two existing subsystems; it does not build a new one.

---

## 1. Evidence target — `DocumentVersion`, not `Document`

**Decision: `WorkflowEvidence` references `DocumentVersion` by foreign key.**

`DocumentVersion`'s own docstring settles it:

> *"An immutable upload associated with a Document. Once created and processed,
> file metadata is immutable."*

| | `Document` | `DocumentVersion` |
|---|---|---|
| Mutability | `status` flips ACTIVE ⇄ ARCHIVED; gains versions over time | **immutable once processed** |
| Identity of bytes | none — "latest" moves | `sha256_checksum` per row |
| Security state | none | `scan_status`, `processing_status` |
| Suitable as evidence | **no** — meaning changes underneath | **yes** |

Linking a `Document` would mean "whatever this document says today", which is
exactly the mutable-pointer failure §1 of the brief forbids. `DocumentVersion`
carries its own checksum, so a link identifies specific bytes.

This also satisfies §12 by construction rather than by rule: uploading version
N+1 creates a new row and cannot alter the row N link. There is no "move to
latest" to suppress, because nothing points at "latest".

---

## 2. Existing reference precedent — follow its shape, not its gaps

`iig_checklist/response_validation.py::_validate_attachment_reference` already
references a `DocumentVersion` from governed content:

```python
exists = DocumentVersion.objects.filter(
    document__tenant=tenant,
    public_id=value["document_version_public_id"],
).exists()
```

What it establishes: **tenant scoping goes through `document__tenant`**, and the
external identifier is `document_version_public_id`.

What it does **not** do, and Milestone 7 must:

- it does not check `scan_status` — a quarantined version would validate;
- it does not check the actor's *document* permission — only tenant membership;
- it stores the reference as a JSON value, not a relation, so the database
  cannot enforce anything about it.

**Milestone 7 follows the tenant shape and closes both gaps.** §3 of the brief
requires reusing the document platform's real security rules, and a foreign key
lets `PROTECT` and a `UniqueConstraint` do work that a JSON blob cannot.

This is a difference from an existing implementation, so it is stated plainly
rather than silently: the two will not be identical, and the newer one is
stricter.

---

## 3. Security gate — reuse, do not invent

The document platform's own rule, from `documents/views.py`:

```python
if version.scan_status == ScanStatus.QUARANTINED:
    raise PermissionDenied(
        "This version has been quarantined and its content is not accessible."
    )
```

`ScanStatus` is `PENDING · CLEAN · INFECTED · QUARANTINED · SCANNER_UNAVAILABLE ·
SCAN_FAILED` (verified in `documents/models.py`), and `documents/tasks.py` gates
processing on `scan_status != CLEAN`.

**Proposed rule for linking evidence: `scan_status` must be `CLEAN`.**

Stricter than the serve-time check, which only blocks `QUARANTINED`. The
justification: serving a `PENDING` version to the uploader who just posted it is
reasonable, but *citing it as governed evidence* while a scan has not concluded
is not. `INFECTED`, `SCAN_FAILED` and `SCANNER_UNAVAILABLE` are all
non-conclusions and must not become evidence.

**No new security status is invented.** The enum is used as it stands.

---

## 4. Deletion protection — already built, and this is what it is for

`documents/deletion_protection.py` provides `DeletionProtectionRegistry`:
dependent apps register a checker from `AppConfig.ready()`, and the documents app
consults every checker before permitting a `DocumentVersion` delete. Its
docstring states the intent: *"This keeps the dependency direction one-way:
documents never imports iig_checklist or any other dependent app."*

It is enforced at three levels — instance `delete()` on both `Document` and
`DocumentVersion`, and queryset `delete()` via `_ProtectedDocumentVersionQuerySet`
/ `_ProtectedDocumentQuerySet`, which closes the bulk-delete bypass. The registry
**fails closed**: a checker that raises is treated as blocking.

`iig_checklist/apps.py` is the working example, registering
`iig_checklist_response_evidence`.

**Milestone 7 registers `workflow_evidence`.** Combined with FK `PROTECT`, that
gives two independent defences, matching how the repository already treats
governed references.

Note also: **there is no delete endpoint for documents at all.** The API offers
archive and restore only (`DocumentStatus.ACTIVE`/`ARCHIVED`). So evidence
cannot become dangling through ordinary product use; the protection is for
programmatic and administrative paths.

---

## 5. Authorization — two independent checks

**This is the invariant §8 calls critical, and it needs stating precisely.**

Workflow permission and document permission are **separate gates**, and passing
one grants nothing about the other:

- `workflows.view` lets a caller see the workflow and its evidence *list*;
- `documents.view` is what lets a caller resolve a linked version's metadata.

A caller who can view a workflow but lacks `documents.view` must not learn
document detail through the evidence endpoint. Note the role tables make this a
live case rather than a theoretical one: `PLATFORM_SUPPORT` has
`workflows.view` but **no document permissions at all**
(`Role.BuiltIn.PLATFORM_SUPPORT: []  # no document content access`).

So the evidence list must degrade for such a caller — identifiers and link
metadata, without document detail — rather than 403 the whole workflow.

Both permission systems use the same shape (`documents.*` / `workflows.*` dot
codenames, in-code `ROLE_PERMISSIONS`, `has_<domain>_permission` helper), so
calling both is straightforward.

---

## 6. Link history — extend the existing pattern, do not add a third

`WorkflowTransition` (Milestone 6) is the repository's most recent governed
append-only table: model/queryset guards **plus** a PostgreSQL trigger, following
`audit/0001_initial.py`.

**Decision: option B from the brief — preserve history, using the same
mechanism.** An `unlink` sets `unlinked_at`/`unlinked_by` on the row rather than
deleting it, so the historical fact that a version *was* cited survives. A
partial `UniqueConstraint` scoped to active links permits relink-after-unlink
without permitting duplicates.

Deleting the row and relying on `AuditEvent` alone (option A) was considered.
Rejected: audit records the *action*, but the evidence set at a point in time
would then only be reconstructable by replaying events, and a governed evidence
set should be queryable directly.

**No third historical-record mechanism is introduced.** This is the second use
of the Milestone 6 pattern, as that pattern was the second use of the AuditEvent
one.

---

## 7. Workflow state rules

Adopting the brief's default, which matches the engine's existing semantics —
`update_draft` already refuses to edit a non-DRAFT item on the grounds that
content must not change under a reviewer, and evidence is content:

| State | Evidence mutation |
|---|---|
| `DRAFT` | **allowed** |
| `SUBMITTED` | refused |
| `IN_REVIEW` | refused |
| `REJECTED` | refused — `return_to_draft` first, which is already a governed transition |
| `APPROVED` | **immutable** |
| `CANCELLED` | **immutable** |

Reading is always permitted subject to §5.

---

## 8. Audit

`workflow.evidence_linked` and `workflow.evidence_unlinked`, through the existing
`workflows/audit_events.py` emitter, whose payload is an **allow-list** — new
keys must be added to `_ALLOWED_PAYLOAD_KEYS` or they cannot be written at all.

Recorded: `workflow_public_id`, `document_public_id`,
`document_version_public_id`, `evidence_public_id`, `action`.

**Not recorded: the filename.** `original_filename` is user-supplied and can
itself disclose subject matter — a filename is a poor thing to put in an audit
row whose retention differs from the document's. Public IDs resolve to it for
anyone with document permission, which is the correct gate.

Also not recorded: document contents, request bodies, tokens, credentials.

---

## 9. Concurrency

Two callers linking the same version to the same workflow simultaneously must
produce exactly one active link.

A partial `UniqueConstraint` on `(workflow_item, document_version)` where
`unlinked_at IS NULL` makes the database the arbiter. The service wraps the
insert in `transaction.atomic()` with `select_for_update()` on the workflow item
— the same shape as `perform_transition` — and translates `IntegrityError` into
a deterministic conflict response.

---

## 10. Migration classification — stated up front

Per `RELEASE_ROLLBACK_RUNBOOK.md` §4, and deliberately **not** repeating the
Milestone 6 error of calling a `CreateModel` migration Class A when it will hold
governed history:

| Migration | Forward | Rollback |
|---|---|---|
| creates `WorkflowEvidence` | additive, no `RunPython`, no destructive operation | **CLASS C once evidence data exists — DATA RESTORE REQUIRED** |
| immutability trigger | additive: one function, two triggers | **Class A** — reverse drops only what it created |

Reversing the table-creation migration **destroys the governed record of which
document versions were cited as evidence**. Django marking `CreateModel`
reversible describes the schema, not the value of what it holds. The trigger does
not make the rollback safer — a rollback that drops the table takes the trigger
with it.

---

## 11. Non-goals

- **No file duplication.** The document platform remains sole owner of storage,
  checksum, scan status, processing status, versioning and retrieval. Evidence
  stores references and its own metadata.
- **No upload path inside workflows.** Users needing a new document go through
  the Documents module.
- No AI summarisation. No Word integration. No new malware or security status.
- No new immutability mechanism.
- **No production regulatory content**, no Item 1 resolution, no change to the
  0/20 count, no policy decision, no S-1/S-2 closure, no Part 11 or validation
  claim.

---

## Governance

Unchanged and unaffected: governance approvals **0 of 20**, production questions
**0**, Item 1 **PENDING**, production regulatory content **BLOCKED**, the
thirteen owner-policy decisions **PENDING**, S-1 and S-2 **NOT CONFIRMED**.
