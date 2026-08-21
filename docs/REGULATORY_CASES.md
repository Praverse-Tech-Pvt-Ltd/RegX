# Regulatory Cases

**A governed case workspace that composes existing RegX capabilities.**

> **A case status of COMPLETED does NOT mean the agency approved the submission.**
> It records that the tenant stopped working the case. RegX makes no regulatory
> determination, assigns no submission identifier, and this milestone changes
> nothing about that.

> **Not regulatory approval.** No approved production regulatory content, no
> 21 CFR Part 11 compliance, not a validated system, no GxP validation claim.

Implemented against `regx-main` `072b1a125542b29234bd89c8abaad84345f6499b`.

---

## 1. Purpose

A regulatory submission is worked across several RegX modules at once: documents
are uploaded, workflow items route them for review, checklists are executed, and
evidence is cited. Before this milestone there was no object that said *these
things belong to the same submission*.

`RegulatoryCase` is that object. It is a **folder with governance**, not a new
engine.

## 2. Non-goals

Deliberately absent, and none of it is partially built:

- **No AI**, no summarisation, no suggestion.
- **No report generation** of any kind.
- **No production regulatory content.** No CEP, DMF or ANDA rules are encoded;
  `market`, `authority` and `submission_type` are free text the tenant supplies.
- **No second workflow engine.** Approval lives in `workflows.WorkflowItem`.
- **No second evidence table.** Evidence is owned by `workflows.WorkflowEvidence`;
  a case surfaces it *through* its linked workflows.
- **No duplicated document storage.** Not a single byte of file content.

## 3. Model

| Field | Notes |
|---|---|
| `public_id` | UUID. Internal PKs are never exposed. |
| `tenant` | `PROTECT`. A tenant with cases cannot be hard-deleted. |
| `case_number` | **Unique per tenant**, not globally. See §4. |
| `title`, `product_name`, `market`, `submission_type` | Required. |
| `product_code`, `authority`, `target_date`, `description` | Optional. |
| `status` | See §5. |
| `owner` | Optional, must be an active member of the same tenant. |
| `created_by`, `created_at`, `updated_at` | Provenance. |

### 4. Case numbers

`RC-000001`, assigned by the server. **A deliberately internal identifier** — RegX
does not issue agency-meaningful references, and nothing here should be mistaken
for one.

Numbers are **tenant-local**: two tenants may both hold `RC-000001` and they are
different cases. A test asserts exactly that.

Generation is transaction-safe. A dedicated `CaseNumberSequence` row per tenant
is claimed under `select_for_update`, rather than computing `MAX + 1` — which
cannot be made safe without locking every case row in the tenant, or locking the
`Tenant` row and serialising unrelated work.

The `UniqueConstraint` on `(tenant, case_number)` is the real guarantee; the
sequence is the mechanism that avoids ever hitting it. Both are tested: a
barrier-synchronised threaded test proves two concurrent creates take different
numbers, and a separate test proves the database refuses a duplicate even if the
sequence were bypassed.

## 5. Status

| Status | Meaning |
|---|---|
| `OPEN` | Being worked. |
| `ON_HOLD` | Paused. |
| `COMPLETED` | Work stopped. **Not an approval.** |
| `CANCELLED` | Abandoned. |

Deliberately **not** `DRAFT` / `SUBMITTED` / `IN_REVIEW` / `APPROVED` /
`REJECTED` — those belong to the workflow engine and are not repeated here. A
case is operational state; the regulatory decisions happen inside the workflow
items it links.

`COMPLETED` and `CANCELLED` are terminal: editing, linking and unlinking are all
refused with **409**. **Reopening is not offered** — the repository has no reopen
convention for a terminal state, and inventing one would create a governance path
nobody has agreed to.

## 6. Permissions

| Codename | Granted to |
|---|---|
| `regulatory_cases.view` | DOER, REVIEWER, VP, TENANT_ADMIN, PLATFORM_SUPPORT |
| `regulatory_cases.create` | DOER, TENANT_ADMIN |
| `regulatory_cases.edit` | DOER, TENANT_ADMIN |
| `regulatory_cases.manage_links` | DOER, TENANT_ADMIN |
| `regulatory_cases.complete` | REVIEWER, VP, TENANT_ADMIN |
| `regulatory_cases.cancel` | VP, TENANT_ADMIN |

Dot-form codenames with an in-code role map and a fail-closed helper, matching
the six existing domain apps. No new roles are invented.

Status changes are **not** reachable through `PATCH`: they move only through the
dedicated `complete` and `cancel` endpoints, each with its own permission.
Otherwise `edit` would silently grant both. A test asserts a `PATCH` carrying
`status` leaves the case `OPEN`.

## 7. Authorization separation — the invariant that matters most

    CASE VIEW != DOCUMENT VIEW
    CASE VIEW != WORKFLOW VIEW
    CASE VIEW != CHECKLIST VIEW

Holding `regulatory_cases.view` tells you a case links three documents. It tells
you nothing about **what** those documents are.

Detail is added only when the caller **independently** holds that module's own
view permission, resolved through that module's own helper
(`has_document_permission`, `has_workflow_permission`,
`has_iig_checklist_permission`) so the two cannot drift apart. This is the same
principle Milestone 7 applied to evidence, applied three times over.

A caller without the module permission receives:

- the link's `public_id`, `label`, `linked_at` and the linking actor's **name**
- the target's `public_id` — an opaque UUID that discloses nothing on its own,
  and which the UI needs as a stable key
- `restricted: true`

**Never**: document title, filename, checksum, scan status, workflow title,
checklist detail, or any email address.

> **A live configuration, not a hypothetical.** `PLATFORM_SUPPORT` holds
> `regulatory_cases.view` and its document permission list is literally `[]`. A
> test drives that exact role and asserts the document title never reaches the
> response.
>
> **Note the honest limit.** No built-in role currently separates cases from
> *workflows* — `PLATFORM_SUPPORT` holds `workflows.view`, so it legitimately
> sees workflow detail. That is the platform's own configuration, not a leak. The
> gate is still enforced in code, and is tested against the projection directly
> with a caller who genuinely lacks the permission, because a role-based test
> there would prove nothing.

### Linking is gated the same way as reading

**`regulatory_cases.manage_links` alone is not enough to link anything.** The
target module's own view permission is required as well, resolved through that
module's own helper — the same helpers the projection uses, so read and link
cannot drift apart.

This was a finding from independent review of PR #36, and it was a real one.
Without the second gate the endpoint was an **existence oracle**: a caller
holding only `manage_links` could point it at any same-tenant UUID and read the
answer off the result — success meant the object existed, an error meant it did
not, for objects they had no permission to see.

The permission is checked **before** the target is resolved, and raises the same
exception with the same message, so three outcomes are one indistinguishable
result:

| Situation | Result |
|---|---|
| Target exists, caller lacks the module permission | identical |
| Target does not exist | identical |
| Target belongs to another tenant | identical |

A refused link emits **no audit event** — a rejected attempt must leave no trace
suggesting it happened. Tested for each of the three kinds, at the service layer
and at the HTTP boundary, plus mutation-tested: removing the check turns five
tests red.

## 8. Relationships

Three explicit through-models rather than a generic relation: each target needs
its own tenant check, permission gate and deletion protection, and a
`GenericForeignKey` would hide all three behind an untyped column.

| Model | Target | Why that target |
|---|---|---|
| `RegulatoryCaseWorkflow` | `workflows.WorkflowItem` | The unit of review. |
| `RegulatoryCaseDocument` | `documents.Document` | A case tracks *which documents belong to this submission*, and that should follow the document as versions are uploaded. Milestone 7's exact-version pinning answers a different question — *which bytes did this workflow cite* — and is untouched. |
| `RegulatoryCaseChecklist` | `iig_checklist.ChecklistExecution` | The tenant's operational run. A definition is catalogue content shared across cases. |

Each stores `case`, target, `tenant`, `label`, `linked_by`, `linked_at`,
`unlinked_by`, `unlinked_at`.

**Unlinking stamps, never deletes.** The fact that a case once cited a workflow,
document or checklist is part of the case history. `delete()` always raises, and
the manager blocks `update()`, `delete()` and `bulk_update()` so nothing bypasses
the service layer.

A partial `UniqueConstraint` on `(case, target) WHERE unlinked_at IS NULL`
permits relinking after an unlink while forbidding duplicates — and makes the
database the arbiter of concurrent links. A threaded test proves two simultaneous
links produce exactly one winner.

### Database-level immutability

The manager blocking `update()`, `delete()` and `bulk_update()` is **not
sufficient**, and independent review of PR #36 was right to say so. None of it
stops the obvious path:

```python
link = RegulatoryCaseDocument.objects.get(...)
link.document = some_other_document
link.save()
```

`save()` issues a plain `UPDATE` that never passes through the manager, so a
governed link could be repointed at another document, moved to a different case
or tenant, or have its provenance rewritten — outside the service layer and with
no audit row. Only the database can refuse that.

`0002` installs a PostgreSQL guard on **all three** link tables, following
`workflows/0005`. Deliberately not a blanket `UPDATE` ban: a link must make
exactly one transition, active → unlinked, once. So the trigger:

- forbids `DELETE` outright, **including after an unlink**;
- forbids any `UPDATE` to an already-unlinked row;
- freezes `id`, `public_id`, `case_id`, `tenant_id`, the target FK,
  `linked_by_id`, `linked_at`, `label` and `created_at`;
- requires both unlink stamps to move together;
- permits `updated_at` to change **only inside that sanctioned transition**, so
  it cannot become a backdoor for an otherwise-frozen row.

A completeness test reads `information_schema.columns` for each of the three
tables and asserts every column is either frozen, an unlink stamp, the target, or
`updated_at` — so a future column cannot silently escape the guard.

Mutation-tested: removing the frozen-column comparison turns six tests red, and
the migration was restored byte-identical afterwards.

## 9. Tenant isolation

Every case and every link carries `tenant`. Cross-tenant linking **fails closed**,
and absent, cross-tenant and ineligible targets produce **one identical message** —
otherwise a caller could probe another tenant for the existence of a workflow or
document by comparing responses. Tests assert the indistinguishability directly.

Cross-tenant case access returns **404**, not 403: a 403 would confirm the case
exists. The owner lookup uses the same single message for the same reason.

## 10. Audit

`regulatory_case.created`, `.updated`, `.completed`, `.cancelled`, and
`.{workflow,document,checklist}_{linked,unlinked}` — through the existing
`AuditEvent` system, with a strict allow-list.

Recorded: case public_id, case number, status transition, link kind, link and
target public_ids, changed **field names**, and whether a reason was supplied.

**Never recorded**: document title, filename, checksum, scan status, workflow
title, checklist content, owner email, changed field **values**, or reason text.
A document title can itself disclose the subject of a submission, and an audit row
has different retention from the resource it describes. Four tests assert these
absences with deliberately distinctive synthetic values.

## 11. Deletion protection

Every governed reference is `PROTECT`, and there is no `CASCADE` on any link.

| Deleting | Result |
|---|---|
| A linked `Document` | `ProtectedError` |
| A linked `WorkflowItem` | `ProtectedError` |
| A linked `ChecklistExecution` | `ProtectedError` |
| A `RegulatoryCase` with links | `ProtectedError` |
| A `Tenant` with cases | `ProtectedError` |

**Protection survives unlink**: the historical record that a case cited a
document is itself governed, so deleting the document would strand it. Tested.

`documents.DeletionProtectionRegistry` is not used here — it guards
`DocumentVersion`, and case links target `Document`. The FK is the right
mechanism at this level.

## 12. Migration classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4. Forward risk
and rollback risk are different questions.

| Migration | Forward | Rollback |
|---|---|---|
| `0001_initial` | **Class A** — additive, four `CreateModel`s, zero `RunPython`, zero `RunSQL`, zero destructive operations | **CLASS C — DATA RESTORE REQUIRED once any case exists** |
| `0002_case_link_db_immutability` | **Class A** — additive: two functions, six triggers. No table altered, no row touched | **Class A on its own terms** — `reverse_sql` drops exactly what it created |

> `0002` does **not** make reversing `0001` safe. A rollback that drops the link
> tables takes the guard down with them, which is the opposite of protection.

> Reversing `0001` drops the case table and all three link tables. That destroys
> the record of which workflows, documents and checklists a case cited, including
> links already retired, **and the per-tenant number sequence** — so a later
> re-create would reissue numbers that previously meant something else.
>
> **Do not backward-migrate merely because Django marks `CreateModel`
> reversible.** Django is describing the schema, not the value of what it holds.
> Use a Level 3 data restore.

The classification is repeated as a docstring **inside the migration file**, so an
operator running `migrate regulatory_cases zero` sees it where they act.

## 13. API

| Method | Path |
|---|---|
| GET / POST | `/regulatory-cases/` |
| GET / PATCH | `/regulatory-cases/{public_id}/` |
| POST | `/regulatory-cases/{public_id}/complete/` |
| POST | `/regulatory-cases/{public_id}/cancel/` |
| GET / POST | `/regulatory-cases/{public_id}/{workflows,documents,checklists}/` |
| DELETE | `/regulatory-cases/{public_id}/{kind}/{link_public_id}/` |

**The link kind is part of the path, never the body**, so a caller cannot aim a
document permission at a workflow by changing a field. An unknown kind is a 404
from the URL resolver before any view runs.

`400` unavailable target · `403` permission · `404` outside the tenant ·
`409` terminal case or duplicate link. Public IDs only.

The detail response carries a `permissions` block so the UI can render honestly
instead of inferring capability from a role name.

## 14. Query cost

The detail endpoint fetches each link kind with its target pre-joined via
`select_related`, and resolves each module permission **once per request** rather
than per row.

A test measures query count at 1 link and at 10 and asserts they are **equal**.
It deliberately does not assert an absolute number: that would encode today's
fixed overhead and break on unrelated changes. What must never change is the
shape.

## 15. Frontend

`/regulatory-cases` and `/regulatory-cases/[publicId]`, in the company design
system established by PR #35.

The workspace has five tabs — Overview, Documents, Workflow, Checklists,
Evidence / Activity. Evidence is **presented as belonging to workflow items**,
with a count and a pointer to the workflow, never as case-owned data.

Controls are **advisory only** and driven by the API's `permissions` block: Edit,
link, unlink, Complete and Cancel are hidden when withheld or when the case is
terminal. The backend re-checks every call.

Empty, loading, restricted, 403, 404 and 409 states are all implemented.

## 16. Testing

**Backend (112 tests)**: creation, number uniqueness, number concurrency,
tenant-local numbering, list/detail/update, tenant isolation, cross-tenant
probing indistinguishability, permissions per role, complete, cancel, terminal
mutation refusal, link/unlink/duplicate/relink for each kind, ORM bypass refusal,
concurrent linking, safe projection both ways, audit content and absences,
deletion protection including after unlink, and query-count invariance.

**Frontend**: 17 unit tests and 13 Playwright specs covering list, create,
detail, restricted projection, permission-driven controls, terminal behaviour,
409 handling, not-found and the evidence framing.

## 17. Regulatory boundaries

No production regulatory content. No Item 1 resolution. No change to the 0/20
governance count. No policy decision. No S-1/S-2 closure. No Part 11,
validated-process, GxP or regulatory-approval claim.

**Completing a case is not an approval, and the UI says so on the case itself.**
