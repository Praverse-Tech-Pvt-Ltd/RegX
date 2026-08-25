# Submission Dossiers

**An ordered, nested readiness structure inside a regulatory case.**

> **READY means internally ready according to configured RegX section criteria.**
> It does **not** mean regulatory compliance, agency approval, submission
> acceptance, filing acceptance, or validated regulatory status. The UI labels it
> *Internal readiness* for exactly this reason.

> **COMPLETED means internal dossier work stopped.** It is not a submission to an
> authority and not an approval.

> **Not regulatory approval.** No approved production regulatory content, no
> 21 CFR Part 11 compliance, not a validated system, no GxP validation claim.

Implemented against `regx-main` `8c4d19d82191be7baa447bfa9d026f7dcb84f25c`.

---

## 1. Purpose

Milestone 8 gave a case a **folder**. This gives it an **outline**: ordered,
nested sections carrying an owner, a due date, blockers and a derived readiness
state, so a team can see where a submission package actually stands.

## 2. Non-goals

Deliberately absent, and none of it is partially built:

- **No approval engine.** Approval lives in `workflows.WorkflowItem`.
- **No eCTD publishing**, no document generation, no AI authoring.
- **No replacement** for Documents, Workflows, Checklists or WorkflowEvidence.
- **No hard-coded CEP / DMF / ANDA / eCTD ruleset.** `section_code` is free
  text; the engine can *represent* those structures, and encodes none of them.
- **No second evidence table.** Evidence stays owned by `WorkflowEvidence` and
  is surfaced through a section's linked workflows.

## 3. What this app owns

Structure, section metadata, readiness, section relationships and section
activity. Nothing else. Documents stay in `documents`, workflow items in
`workflows`, checklist executions in `iig_checklist`. Not a byte is copied.

## 4. Models

| Model | Purpose |
|---|---|
| `SubmissionDossier` | One submission package inside a case. A case may hold several. |
| `DossierSection` | One node of the outline. Arbitrary nesting via `parent`. |
| `DossierSectionBlocker` | An explicit, structured reason a section is not ready. |
| `DossierSectionDocument` / `Workflow` / `Checklist` | Governed links to work that other apps own. |

### Hierarchy

`templates_registry.TemplateSection` is the existing self-referencing tree in
this repository, and its shape is followed rather than a new one invented.

**One difference matters.** That tree has no cycle or depth guard, because an
importer builds it top-down and cycles cannot arise. These sections are edited
through an API, so every corruption is reachable and each is refused explicitly:

| Attack | Result |
|---|---|
| Self-parent | refused |
| Parent is own descendant (cycle) | refused |
| Parent in another dossier | refused |
| Parent in another tenant | refused |
| Parent is retired | refused |
| Nesting past `MAX_SECTION_DEPTH` (10) | refused, including the depth of a subtree being moved |

The depth ceiling is **operational, not regulatory**: it keeps the ancestor walk
cheap and stops a hostile payload building an arbitrarily deep chain.

`validate_parent` **re-reads the parent from the database** rather than trusting
the object handed in — a caller holding a section fetched before it was retired
would otherwise pass a stale `retired_at = NULL` straight through.

### Section codes

`section_code` is **display metadata only** — `1`, `3.2.S.2.3`, `Response-01`.
**Hierarchy comes from `parent`, never from parsing the string.** No CTD syntax
is enforced or assumed.

**Uniqueness is `(dossier, section_code)`, not `(parent, section_code).**
A submission outline is read and cited as a flat set of codes: "see 3.2.S.2"
means one section in the package, not "whichever 3.2.S.2 sits under this parent".
Parent-local uniqueness would permit two sections printing the same code in one
dossier, which is precisely the ambiguity a code exists to remove.

The constraint is **partial on `retired_at IS NULL`**, so retiring a section
frees its code — otherwise a typo would burn a code permanently.

### Ordering

`sequence`, with `id` as a stable tiebreak so two rows never render in
database-timing order. Sibling uniqueness needs **two** constraints because
PostgreSQL treats NULLs as distinct: one for children, one partial for roots.

Reorder locks the whole sibling group, then renumbers in two phases. The parking
values are a **high offset, not negatives** — `sequence` is a
`PositiveIntegerField` and PostgreSQL rejects a negative outright.

## 5. Statuses

**Section status** — what humans say: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`,
`COMPLETE`, `NOT_APPLICABLE`. There is deliberately **no APPROVED state**.

**Dossier status** — `OPEN`, `ON_HOLD`, `COMPLETED`, `CANCELLED`. Terminal
statuses refuse *all* structural change (sections, links, blockers, reorder,
retire) with **409**. **Reopening is not offered** — the repository has no reopen
convention and inventing one would create a governance path nobody agreed to.

## 6. Readiness — derived, never claimed

A user sets `status`; the **system** decides `readiness`. The serializer has no
`readiness` field at all, and a test asserts a `PATCH` carrying one changes
nothing.

```
NOT_APPLICABLE   if status == NOT_APPLICABLE
NOT_READY        if any open blocker
READY            if status == COMPLETE and every required non-N/A child is READY
PARTIALLY_READY  if status == COMPLETE but a required child is not READY
PARTIALLY_READY  if there is supporting work (a link, or IN_PROGRESS, or children)
NOT_READY        otherwise
```

Optional children never hold a parent back. **N/A children are excluded
entirely** — otherwise ruling a section out would make its parent permanently
unreachable.

### Two decisions worth reviewing

**The calculation ignores the caller.** Readiness is computed from backend data
with no permission filter, because a section's readiness must not change
depending on who is looking — two users would otherwise see contradictory states
for the same section. The privacy obligation is discharged at the **explanation**
layer instead.

**An empty dossier is `NOT_READY`, not vacuously `READY`.** An empty outline is
not a finished one, and `READY` would be the most misleading possible answer.

### Known limitation — a dossier that requires nothing can never be completed

`aggregate()` derives overall readiness from the **required, non-N/A** sections
only. Three shapes therefore have no required sections at all, so they never
reach `READY` and `complete_dossier` refuses them permanently:

1. an empty dossier — intended, and the reason code is truthful;
2. **every section optional, even when every one of them is `READY`**;
3. every section `NOT_APPLICABLE`.

(1) is the designed behaviour. (2) and (3) fall out of the same rule. (2) is a
usability trap rather than a safety property: the reason returned is
`NO_SUPPORTING_WORK`, which is **false** — the work exists and is ready, it
simply is not required.

**This is deliberately not fixed here.** What `READY` should mean for a dossier
that requires nothing is a governance judgement about the meaning of a regulatory
readiness signal, not an implementation detail, so it is raised for the owner
rather than decided in code. The current behaviour is the safe side to be wrong
on — it under-claims readiness rather than over-claiming it — and it is pinned by
`test_a_dossier_with_no_required_sections_never_reaches_ready` so it cannot drift
unnoticed while the decision is open.

### Reason codes

Coarse enumerated codes, never prose: `READY`, `NOT_APPLICABLE`,
`OPEN_BLOCKER`, `SECTION_NOT_COMPLETE`, `REQUIRED_CHILD_NOT_READY`,
`NO_SUPPORTING_WORK`. A reason naming the offending workflow or document would
leak exactly what the projection withholds.

## 7. Blockers

Structured rows, not prose buried in notes — readiness depends on them, and a
blocker recorded in a `notes` field cannot gate a calculation.

A **CheckConstraint** enforces resolution consistency: an open blocker carries
neither `resolved_by` nor `resolved_at`; a resolved one carries both. Without it
the halves could drift and a "resolved" row could exist with no accountability.

Blocker history is never deleted.

## 8. Permissions

| Codename | Granted to |
|---|---|
| `submission_dossiers.view` | DOER, REVIEWER, VP, TENANT_ADMIN, PLATFORM_SUPPORT |
| `.create` / `.edit` / `.manage_sections` / `.manage_links` | DOER, TENANT_ADMIN |
| `.manage_blockers` | DOER, REVIEWER, TENANT_ADMIN |
| `.complete` | REVIEWER, VP, TENANT_ADMIN |
| `.cancel` | VP, TENANT_ADMIN |

Dot-form codenames, in-code role map, fail-closed helper. No new roles invented.

## 9. Two-gate linking — both read and write

    SECTION VIEW != DOCUMENT VIEW != WORKFLOW VIEW != CHECKLIST VIEW

Linking requires `manage_links` **and** the target module's own view permission,
resolved through that module's own helper so read and link cannot drift apart.

**This was a MAJOR finding against Milestone 8 and is built in here from the
start.** Without the second gate the endpoint is an *existence oracle*: point it
at any same-tenant UUID and read the answer off the result.

The module permission is checked **before** the target is resolved, and every
failure raises the same exception with the same message, so these are one
indistinguishable outcome:

- target does not exist
- target belongs to another tenant
- target exists but the caller lacks the module permission

A refused link emits **no audit event**.

## 10. Safe projection

A caller without the module permission gets the link's `public_id`, `purpose`,
`linked_at`, the linking actor's **name** (never email), the target's opaque
`public_id`, and `restricted: true`. Never a title, filename, checksum, scan
status, workflow state, or checklist detail.

**Module counts are `null`, never `0`.** Milestone 8 originally reported a real
state breakdown to callers who could not see a single workflow. Reporting zero
would be worse than reporting nothing: it asserts something false. The UI renders
`null` as an em dash.

## 11. Governed link immutability

The manager blocks `update()`, `delete()` and `bulk_update()`, and
`Model.delete()` raises. **That is not sufficient** — `link.save()` issues a
plain `UPDATE` that never passes through the manager.

`0002` installs PostgreSQL triggers on all three link tables from the start,
freezing `id`, `public_id`, `section_id`, `tenant_id`, the target FK,
`linked_by_id`, `linked_at`, `purpose` and `created_at`; permitting only
active → unlinked with **both stamps together**; rejecting `DELETE` before and
after unlink; and allowing `updated_at` to move **only inside** that transition
so it is not a backdoor.

A completeness test reads `information_schema.columns` for each table so a future
column cannot silently escape the guard.

## 12. Section deletion

Sections are **retired, never deleted** — a section can carry link history and
blocker history, and removing the row would strand both. Retirement stamps
`retired_at` / `retired_by`, refuses while active children exist, and frees the
section's code and sequence for reuse.

### The gap independent review found

Retirement was enforced in the service layer, and `on_delete=PROTECT` covered a
section that already held a governed relationship. **Those are not the same
guarantee.** A section with no children, no blockers and no links had nothing
protecting it, so all three of these removed the row outright:

```python
section.delete()
DossierSection.objects.filter(...).delete()
```
```sql
DELETE FROM submission_dossiers_dossiersection WHERE id = ...;
```

A section's creation is already auditable history. The row must not simply
disappear, whether or not anything happens to point at it yet.

Closed at three layers, because each sees something the others cannot:

| Path | Guard |
|---|---|
| `section.delete()` | `DossierSection.delete()` raises `DossierMutationForbidden` |
| `.filter(...).delete()`, `section.children.all().delete()` | `_DossierSectionQuerySet.delete()` raises |
| raw SQL, psql, a cascade, a migration in a hurry | `0003` trigger `no_delete_dossier_section` |

`update()` and `bulk_update()` are **deliberately left open** on the section
queryset. `reorder_section` renumbers a sibling group with `.update()` and
`recalculate_dossier` writes derived readiness with `.bulk_update()`; a blanket
queryset ban would have broken the two operations that exist to keep the outline
consistent. Only DELETE is closed, because only the row disappearing is the
problem.

### Foreign-key protection, unchanged

Every governed FK is `PROTECT` with no `CASCADE`. Deleting a linked document,
workflow item, checklist execution, a dossier with sections, a case with
dossiers, or a tenant with dossiers all raise `ProtectedError`. **Protection
survives unlink.**

## 12b. Blocker history governance

Blockers gate readiness directly, so a rewritable blocker is a rewritable
readiness signal.

The `CheckConstraint` keeps the two resolution halves consistent — open carries
neither stamp, resolved carries both. **A CHECK constraint evaluates one row at
one instant and cannot see that row's previous version**, so on its own it
permitted a resolved blocker being written back to open:

```python
blocker.status = "open"
blocker.resolved_at = None
blocker.resolved_by = None
blocker.save()          # internally consistent, and therefore accepted
```

and it permitted rewriting `title`, `description`, `severity`, `section_id`,
`tenant_id`, `created_by_id`, `public_id` or `created_at` at any time, with no
audit row.

### The lifecycle, enforced

```
OPEN ──► RESOLVED ──► immutable forever
```

`0003` installs `guard_update_section_blocker` and `no_delete_section_blocker`:

| Column | Rule |
|---|---|
| `id`, `public_id`, `tenant_id`, `section_id` | frozen |
| `title`, `description`, `severity` | frozen |
| `created_by_id`, `created_at` | frozen |
| `status`, `resolved_by_id`, `resolved_at`, `updated_at` | may move, **only in the resolution** |

- Any `UPDATE` at all is refused once `OLD.status = 'resolved'` — one rule that
  covers reopening, re-resolving and any later content rewrite.
- The `UPDATE` must **be** the resolution: `status` must become `resolved` and
  both stamps must be non-null together. A partial stamp is refused.
- That same rule is what stops a bare `updated_at` touch on an open row from
  becoming a backdoor.
- `DELETE` is refused in **both** states — resolution is not a route to erasure.
- A legal transition carrying an illegal edit alongside it is rejected whole.

The queryset blocks `update()`, `delete()` and `bulk_update()`; `Model.delete()`
raises. None of that sees `blocker.save()`, which issues a plain `UPDATE` — which
is exactly why the trigger exists.

An `information_schema.columns` coverage test asserts that every column on the
table is classified as frozen or transition-only, so a column added later cannot
quietly become rewritable.

**The service layer still answers first.** Resolving an already-resolved blocker
returns a clean `409`, not a database error; the trigger is the floor, not the
user-facing behaviour.

## 13. Audit

`submission_dossier.{created,updated,completed,cancelled}`,
`dossier_section.{created,updated,reordered,completed,not_applicable,retired}`,
`dossier_section.{blocker_created,blocker_resolved}` and
`dossier_section.{document,workflow,checklist}_{linked,unlinked}` — through the
existing `AuditEvent` with a strict allow-list.

**Never recorded**: section title, description, notes, blocker title or
description, document title, filename, workflow title, checklist detail, owner
email, or the **values** of changed fields. Free text describes the submission,
and an audit row has different retention from the section it describes.

## 14. Migration classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.

| Migration | Forward | Rollback |
|---|---|---|
| `0001_initial` | **Class A** — six `CreateModel`s, zero `RunPython`/`RunSQL`, zero destructive ops | **CLASS C — DATA RESTORE REQUIRED once any dossier exists** |
| `0002_section_link_db_immutability` | **Class A** — two functions, six triggers | **Class A on its own terms** |
| `0003_section_and_blocker_db_governance` | **Class A** — three functions, three triggers; no table altered, no row read or written | **Class A on its own terms** |

> Reversing `0001` destroys the outline itself, the section hierarchy and
> ordering, the link history including retired links, and the entire blocker
> history with its resolution provenance. **Do not backward-migrate merely
> because Django marks `CreateModel` reversible.**
>
> Neither `0002` nor `0003` makes reversing `0001` safe. Both reverse cleanly on
> their own terms — each drops exactly the triggers and functions it created and
> touches no row — but **removing protection is not the same as making
> destruction safe**. A rollback that drops the tables takes the guards down with
> them, which is the opposite of protection. The relationship is one-way: `0003`
> can be reversed on its own, and `0001` cannot be reversed safely whether or not
> `0002` and `0003` are still applied.

Both classifications are repeated **inside the migration files**, where an
operator running `migrate submission_dossiers zero` will actually see them.

## 15. API

Dossiers are created and listed under their case; addressed directly once they
have an id, since a dossier `public_id` locates one on its own.

| Method | Path |
|---|---|
| GET / POST | `/regulatory-cases/{case_id}/dossiers/` |
| GET / PATCH | `/submission-dossiers/{id}/` |
| POST | `/submission-dossiers/{id}/{complete,cancel}/` |
| GET / POST | `/submission-dossiers/{id}/sections/` |
| GET / PATCH | `/dossier-sections/{id}/` |
| POST | `/dossier-sections/{id}/{reorder,retire}/` |
| GET / POST | `/dossier-sections/{id}/blockers/` |
| POST | `/section-blockers/{id}/resolve/` |
| GET / POST | `/dossier-sections/{id}/{documents,workflows,checklists}/` |
| DELETE | `/dossier-sections/{id}/{kind}/{link_id}/` |

**The link kind is in the path, never the body**, so a document permission cannot
be aimed at a workflow. Public IDs only.

`400` unavailable target · `403` permission · `404` outside the tenant ·
`409` terminal dossier, duplicate, or completion refused while not ready.

### Serialisation

Dossier detail returns a **flat** section array with `parent_public_id`; the
client assembles the tree. Section detail returns **direct children only**.
Recursive serialisation of an unbounded tree per request is the N+1 shape this
avoids.

## 16. Query cost

Measured, not assumed:

| Endpoint | 1 | 10 | 100 |
|---|---|---|---|
| Dossier detail (by sections) | 23 | 23 | 23 |
| Section detail (by links, 1/5/20) | 32 | 32 | 32 |
| Readiness recalculation (5 / 50 sections) | 5 | — | 5 |

Tests assert **invariance**, not an absolute: an absolute encodes today's fixed
overhead and breaks on unrelated changes. What must never change is the shape.

## 17. Frontend

`/submission-dossiers/[publicId]`, plus a **Dossiers tab** on the Milestone 8
case detail — a dossier only exists inside a case, and a separate top-level entry
would let a user reach one without its case context.

**The outline renders as a flat list with indentation, not nested DOM.** A
dossier can hold 500 sections; nesting produces 500-deep containers that are slow
to lay out and impossible to virtualise later. Collapsing filters the visible
list rather than unmounting a subtree.

Readiness is **never communicated by colour alone** — every badge carries a text
label and a distinct glyph. Nothing is green: an approval-coloured badge would
imply an agency decision the platform never makes.

Controls are advisory and driven by the API's `permissions` block; the backend
re-checks every call. Restricted resources render *"Linked resource — access
restricted"*, never a fake zero state.

### Known follow-up UX debt

Linking takes a **UUID pasted by hand**. A governed picker needs a safe,
permission-scoped search endpoint, and building an unscoped resource-enumeration
endpoint purely for convenience would undo the projection work. Deliberately
deferred rather than done unsafely.

## 18. Testing

**Backend (160)**: dossier lifecycle and isolation; hierarchy including
self-parent, cycle, cross-dossier, cross-tenant, retired parent and depth;
ordering and reorder; readiness across every branch including child aggregation;
blockers with database-enforced consistency; two-gate auth per kind with
indistinguishability and no-audit-on-refusal; safe projection; DB immutability
across all three link tables; section deletion refused through model, queryset
and raw SQL in both active and retired states; blocker content, provenance and
lifecycle immutability; `information_schema` column coverage; audit content and
absences; and query-cost invariance.

**Frontend**: 23 unit, 7 new accessibility checks, 16 Playwright.

**Every guard is mutation-tested**, because a test that passes without the guard
proves nothing:

| Mutation | Tests turned red |
|---|---|
| Link frozen-column comparison removed (`0002`) | 6 |
| Two-gate permission check removed | 5 |
| Section DELETE trigger removed (`0003`) | 5 + 1 error |
| Blocker `already resolved` finality rule removed (`0003`) | 3 |
| Blocker frozen-column comparison removed (`0003`) | 7 |
| ORM-level section and blocker `delete()` guards removed | 11 |

Every mutated file was restored and verified byte-identical afterwards.

## 19. Regulatory boundaries

No production regulatory content. No CEP, DMF, eCTD or ANDA structure built in.
No Item 1 resolution. No change to the 0/20 governance count. No policy decision.
No S-1/S-2 closure. No Part 11, GxP, validated-process or regulatory-approval
claim.

**READY is internal readiness. COMPLETED is internal completion. Neither is an
agency decision, and the UI says so on the dossier itself.**
