# Workflow Engine

**Generic workflow infrastructure.** A tenant-scoped work item moves through a
review lifecycle under a centrally enforced transition table, with append-only
history and immutable audit.

> **This is not regulatory approval.** It contains no approved production
> regulatory content, establishes no 21 CFR Part 11 compliance, and is not a
> validated system. A required reason is a required reason — it is **not** an
> electronic signature.

Implemented against `regx-main` `eaef74f0014248228a62b5bd39979f13abd34a42`.
Design rationale and the survey of what already existed:
[`MILESTONE_6_WORKFLOW_ENGINE_DISCOVERY.md`](MILESTONE_6_WORKFLOW_ENGINE_DISCOVERY.md).

---

## 1. State graph

```
          ┌──────────────── return_to_draft ────────────────┐
          ▼                                                 │
      ┌───────┐  submit   ┌───────────┐ begin_review ┌───────────┐  approve  ┌──────────┐
      │ DRAFT │──────────▶│ SUBMITTED │─────────────▶│ IN_REVIEW │──────────▶│ APPROVED │
      └───┬───┘           └─────┬─────┘              └─────┬─────┘           └──────────┘
          │                     │                          │  reject          (terminal)
          │                     │                          ▼
          │                     │                    ┌──────────┐
          │                     │                    │ REJECTED │
          │                     │                    └────┬─────┘
          │      cancel         │        cancel           │ cancel
          └─────────────────────┴──────────┬──────────────┘
                                           ▼
                                     ┌───────────┐
                                     │ CANCELLED │  (terminal)
                                     └───────────┘
```

| Action | Legal from | Result |
|---|---|---|
| `submit` | DRAFT | SUBMITTED |
| `begin_review` | SUBMITTED | IN_REVIEW |
| `approve` | IN_REVIEW | APPROVED |
| `reject` | IN_REVIEW | REJECTED |
| `return_to_draft` | REJECTED | DRAFT |
| `cancel` | DRAFT, SUBMITTED, IN_REVIEW, REJECTED | CANCELLED |

**`APPROVED` and `CANCELLED` are terminal.** No action is legal from either, and
a terminal item cannot be reassigned.

### Why APPROVED is terminal here

A supersede/reopen pattern does exist in this repository —
`ChecklistVersionStatus.SUPERSEDED`, `TemplateVersion` supersede — but both are
bound to *versioned governed content*. Importing that path would give a generic
work item versioning semantics it does not have. If a reopen path is wanted
later it should be designed with that versioning question answered, not
inherited by accident.

---

## 2. Transition permissions

Codenames follow the domain-app convention (`workflows.*`), enforced through
`ROLE_PERMISSIONS` in `workflows/permissions.py`.

| Action | Permission | doer | reviewer | vp | tenant_admin | platform_support |
|---|---|:-:|:-:|:-:|:-:|:-:|
| view | `workflows.view` | ✅ | ✅ | ✅ | ✅ | ✅ |
| create | `workflows.create` | ✅ | | | ✅ | |
| edit draft / return to draft | `workflows.edit_draft` | ✅ | | | ✅ | |
| submit | `workflows.submit` | ✅ | | | ✅ | |
| begin review | `workflows.review` | | ✅ | ✅ | | |
| approve | `workflows.approve` | | ✅ | ✅ | | |
| reject | `workflows.reject` | | ✅ | ✅ | | |
| cancel | `workflows.cancel` | ✅ | ✅ | ✅ | ✅ | |
| assign | `workflows.assign` | | ✅ | ✅ | ✅ | |

**Fail closed.** No user, no tenant, or no active membership means no
permission. `is_staff` and `is_superuser` are never consulted.

> Three legacy colon-form codenames (`workflow:submit`, `workflow:approve`,
> `workflow:reject`) were seeded before this milestone. They are **left in
> place** — deleting seeded permissions could strip grants from existing role
> assignments — but nothing enforces against them. See the discovery §C.

---

## 3. Reason requirements

| Action | Reason |
|---|---|
| `reject` | **required**, non-blank after trimming |
| `cancel` | **required**, non-blank after trimming |
| everything else | optional |

The reason is stored on the `WorkflowTransition` row. **It is not an electronic
signature** and carries no such meaning.

The audit event records only *that* a reason was supplied and its length —
never the text. The text belongs on the append-only history row, which is the
record for it; duplicating it into audit would create a second copy of the same
statement in a place with different retention.

---

## 4. Assignment

`assigned_to` is nullable; assigning `null` clears it. Rules:

- the assignee must be an **active member of the item's own tenant**;
- a terminal item cannot be reassigned;
- assignment is audited, recording only public IDs;
- enforcement lives in the **service**, not the serializer, so it holds for
  every caller rather than only the HTTP one.

A cross-tenant user and a user that does not exist produce the **same** error
message. Different wording would let a caller probe for the existence of users
outside their tenant — a test asserts the two are indistinguishable.

---

## 5. Tenant isolation

Every queryset filters on the active tenant from `tenancy.context`. Every lookup
is `(public_id, tenant)`, so a valid UUID from another tenant returns **404, not
403** — a 403 would confirm the item exists somewhere.

Covered by release-blocking regression tests across two tenants: cross-tenant
read, cross-tenant mutation, list leakage, cross-tenant assignment, history
leakage, and transition public IDs used cross-tenant.

---

## 6. History

`WorkflowTransition` — `public_id`, `workflow_item`, `tenant`, `action`,
`from_state`, `to_state`, `actor`, `reason`, `created_at`.

**Append-only.** `save()` on an existing row, `delete()`, queryset `update()`,
`delete()` and `bulk_update()` all raise `WorkflowHistoryMutationForbidden`.
There is no update or delete endpoint, and the read endpoint returns 405 for
every write method.

Protection is at **two layers**, and both are load-bearing:

| Layer | Mechanism | Stops |
|---|---|---|
| ORM | `_ImmutableTransitionQuerySet` + model `save()`/`delete()` guards, matching `iig_checklist.ChecklistResponseHistory` | application code, with a clear domain exception |
| **Database** | PostgreSQL trigger from `workflows/0003`, following `audit/0001_initial.py` | **everything**, including raw SQL and a `psql` session |

The database rejects `UPDATE` and `DELETE` on `workflows_workflowtransition`
outright:

```
ERROR: workflow_transition rows are immutable: UPDATE and DELETE are forbidden.
```

`INSERT` remains permitted — the triggers are `BEFORE UPDATE` and
`BEFORE DELETE` only, so appending still works. Tests prove raw UPDATE, raw
DELETE, unqualified `UPDATE`/`DELETE` across the whole table, and both ORM paths
are all refused, while insertion and normal transitions still succeed.

Model guards are kept as defence in depth rather than replaced: they fire first
and give application code a domain exception instead of a database error.

A failed transition writes **no** history row — validation completes before any
write.

---

## 7. Audit

Every material action emits an immutable `audit.AuditEvent`:

`workflow.created` · `workflow.updated` · `workflow.submitted` ·
`workflow.review_started` · `workflow.approved` · `workflow.rejected` ·
`workflow.cancelled` · `workflow.returned_to_draft` · `workflow.assigned` ·
`workflow.unassigned`

The payload is an **allow-list**, not a filter: only named keys can ever be
written, so governed content, credentials, tokens and request bodies are
structurally excluded rather than stripped. `resource_id` is a `public_id`.

Audit events and operational logs remain separate systems — see
[`OPERATIONAL_LOGGING.md`](OPERATIONAL_LOGGING.md).

---

## 8. Concurrency

Two reviewers acting on one `IN_REVIEW` item — one approving, one rejecting —
must not both succeed.

`perform_transition` re-fetches the row with `select_for_update()` inside
`transaction.atomic()` and validates against **the locked row's** state. The
loser sees the winner's state, fails `validate_workflow_transition`, and gets
**409 Conflict** with the current state. Its transition is never applied and
writes no history.

Proven by a threaded test with a barrier, marked `transaction=True` so real
locks apply. It runs on PostgreSQL; SQLite could not express it, which is one
reason the project prohibits SQLite.

---

## 9. API

Base `/api/regx/v1/`. **`public_id` only — internal PKs are never exposed.**

| Method | Path | Purpose |
|---|---|---|
| GET | `workflows/` | list (filters: `state`, `assigned_to`) |
| POST | `workflows/` | create (DRAFT) |
| GET | `workflows/{public_id}/` | retrieve |
| PATCH | `workflows/{public_id}/` | edit DRAFT only |
| GET | `workflows/{public_id}/history/` | transition history |
| POST | `workflows/{public_id}/submit/` | |
| POST | `workflows/{public_id}/begin-review/` | |
| POST | `workflows/{public_id}/approve/` | |
| POST | `workflows/{public_id}/reject/` | reason required |
| POST | `workflows/{public_id}/cancel/` | reason required |
| POST | `workflows/{public_id}/return-to-draft/` | |
| POST | `workflows/{public_id}/assign/` | `assigned_to` public_id or null |

**`state` is read-only.** A PATCH carrying `state` is refused with 400 and an
explanation — refused explicitly rather than silently ignored, so a caller
relying on it learns why. The whole request is rejected, not partly applied.

Status codes: **409** for an illegal transition (including a lost race), **403**
for a permission failure, **400** for a missing reason or invalid assignee,
**404** for anything outside the tenant.

Each response carries `available_actions` — structurally legal **and** permitted
for this caller.

---

## 10. Frontend

`/workflows` list, `/workflows/new`, `/workflows/{publicId}` detail with state
badge, assignment, transition controls, a reason form for governed actions, and
a history table.

Controls are rendered from the backend's `available_actions`. **Hiding a button
is presentation, not security** — every endpoint re-checks server-side, and the
UI cannot grant an action by rendering it.

On a 409 the detail page reloads rather than guessing, so a user who lost a race
sees the real current state.

---

## 11. Migrations and rollback classification

Classified per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.
**Forward risk and rollback risk are different questions**, and Django's notion
of "reversible" answers only the first.

| Migration | Forward | Rollback class |
|---|---|---|
| `0002` — states, nullable fields, `WorkflowTransition` table | additive, no `RunPython`, no destructive operation | **C once transition data exists** |
| `0003` — immutability trigger | additive; creates one function and two triggers | **A** — `reverse_sql` drops only what it created, touching no row |

> ### `workflows/0002` is CLASS C — DATA RESTORE REQUIRED
>
> Once any `WorkflowTransition` row exists, reversing `0002` **drops the table
> and destroys append-only workflow history**.
>
> **Do not backward-migrate `0002` merely because Django marks `CreateModel` as
> reversible.** Django is describing the schema, not the value of the history it
> holds. That history is a governed append-only record, protected at the
> database level precisely so it cannot be removed casually.
>
> Use **Level 3 data restore**, not a backward migration.

This is the same distinction the runbook draws for `iig_checklist/0006`:
structurally reversible, not data-safe to reverse.

The `0003` trigger does not change the classification of `0002`. It makes
casual deletion harder; it does not make the rollback safer, because a rollback
that drops the table takes the trigger with it.

**Forward application is low risk** in both migrations: additive throughout,
no `RunPython`, no data migration, no destructive forward operation.

---

## 12. Known limitations

- **`APPROVED` is terminal.** No supersede or reopen path — §1.
- **No notifications.** No framework exists and none was invented.
- **No SLA or escalation.** `is_overdue` is derived from `due_at` and
  terminality, and nothing acts on it.
- **No bulk operations.** One item per request.
- **No workflow *types*.** Every item shares one state graph; there is no
  per-type customisation, no dynamic transitions and no conditional routing.
- **Attachments: delivered in Milestone 7** — workflow items link governed
  document versions as evidence, see [WORKFLOW_EVIDENCE.md](WORKFLOW_EVIDENCE.md).
- **No comments thread.** A reason per transition and an optional evidence
  label, nothing more.
- **`available_actions` is advisory.** It reflects permissions at read time; a
  role change between read and action is resolved server-side, by refusal.
- **Reason text is unbounded** (`TextField`). No size limit is imposed.

---

## 13. Non-goals

This milestone deliberately does **not**:

- author production regulatory questions or select dosage forms;
- resolve Milestone 5A Item 1, or change the governance count from **0/20**;
- change the production-question count from **0**;
- activate production regulatory content, which remains **BLOCKED**;
- decide any of the 13 owner-policy items, which remain **PENDING**;
- close S-1 or S-2, which remain **NOT CONFIRMED**;
- claim 21 CFR Part 11 compliance or validated production operation;
- introduce a generic state-machine framework abstracting the three transition
  tables that already exist.
