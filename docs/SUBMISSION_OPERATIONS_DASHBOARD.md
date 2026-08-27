# Submission Operations Dashboard

**One operational view across the governed domains. It owns no data and decides
nothing.**

> **This dashboard reflects internal RegX operational status only.** It is not a
> statement of agency acceptance, regulatory approval, filing completeness or
> submission validity. A green dashboard does not mean a submission is
> acceptable to anyone.

> **No regulatory judgement of any kind.** No CTD, eCTD, CEP, DMF, ANDA, USFDA
> or EMA structure or rules. No completeness engine, no submission validation,
> no AI conclusions. Everything here is deterministic and counted from tables
> another app owns.

Stacked on Milestone 11 (`regx/feat/dossier-upgrades`), branched from
`1cd885a4e44baa1861866ebfc09aa2839c2a0015`. **Must not merge before M11, which
must not merge before M10, which must not merge before M9.**

---

## 1. What it is

A read model. Every number is counted, at request time, from the authoritative
table using that module's own status fields and that module's own view
permission.

```
authoritative domain tables
        ↓
permission-aware query/aggregation service   ← submission_operations
        ↓
dashboard API
        ↓
frontend dashboard
```

There is **no second source of truth**: no copied readiness, no cached counts,
no stored dashboard state, no new model, no migration. Delete this app and every
fact it reports still exists, unchanged, where it always was.

## 2. Non-goals

Deliberately absent: eCTD publishing; CTD/CEP/DMF/ANDA completeness rules;
jurisdiction requirements; regulatory intelligence; AI conclusions; document
authoring; submission validation; electronic signatures; a governance approval
engine; and any new workflow, document, checklist or readiness engine. It
composes the existing domains and duplicates none of them.

## 3. Zero and null are different answers

The single rule the whole product turns on.

| Value | Means |
|---|---|
| `0` | there are none |
| `null` | **you are not entitled to know** |

A dashboard that renders `0` for a module the caller cannot see is not being
cautious, it is lying — and lying in a way indistinguishable from the truth
right up until the tenant actually has twelve of the thing. It also leaks over
time: a caller watching `0` become `12` has learned something about a module
they were never granted.

So an unavailable dimension is `None` through the service layer, `null` on the
wire, and **"Unavailable"** on screen. Never a dash, never a zero, never a
`{restricted: true}` flag sitting beside real numbers — each of those has to be
defended against in the UI too, and one missed branch renders a number.

`Visibility` in [`projection.py`](../backend/submission_operations/projection.py)
makes this structural rather than a convention. The aggregation code cannot
reach a restricted module's numbers without passing a gate that returns `None`.

## 4. The permission is a door, not a key

`submission_operations.view` grants exactly one thing: the right to ask.

It grants **no** visibility into cases, dossiers, documents, workflows,
checklists, blueprints or upgrades. Each stays behind its own module's view
permission, checked independently on every request through that module's own
helper:

| Module | Authoritative gate |
|---|---|
| cases | `regulatory_cases.view` |
| dossiers | `submission_dossiers.view` |
| documents | `documents.view` |
| workflows | `workflows.view` |
| checklists | `iig_checklist.view_execution` |
| blueprints | `dossier_blueprints.view` |
| upgrades | `dossier_upgrades.view` |

A dashboard aggregating across modules under a single permission would be a
permission-laundering machine: read access to seven governed domains granted by
one codename nobody reviewed as such. Holding this and nothing else produces a
page that renders, says "Unavailable" in every panel, and leaks nothing — not
even a count, because a count is an answer.

The gates are imported **by name** rather than looked up from a table of
strings, so deleting or renaming one is an import error here instead of a
silently-`False` lookup that quietly opens a panel nobody re-reviewed.

## 5. Internal readiness

Aggregated from Milestone 9. **Never recomputed.**

M9 derives readiness, persists it and owns the formula; this module reads the
column. A dashboard re-deriving readiness from section status would be a second
implementation of a governed rule, and the two would disagree the first time M9
changed. A test constructs the disagreement deliberately — a section marked
COMPLETE that M9 still calls NOT_READY because it carries an open blocker — and
asserts the dashboard follows M9.

| Label | Meaning |
|---|---|
| `internally_ready` | every active required section has M9 readiness READY |
| `internally_partially_ready` | some do |
| `internally_not_ready` | none do |
| `no_required_sections` | there is nothing to be ready about |

Four-valued deliberately. A dossier with no required sections is **not** ready,
and collapsing that into the same green as finished work is the single most
misleading thing this screen could do.

Every label says "internally". A badge reading plain "Ready" on an operations
screen invites exactly the reading this product must never support.

## 6. What counts as work

| Rule | Why |
|---|---|
| retired sections excluded | M9 retires rather than deletes so history survives. History is not a to-do list, and a retired overdue section nobody can clear would sit in the queue forever. |
| optional sections excluded from completion metrics | a tenant marking a section not-required has said it does not gate the work |
| sections in terminal dossiers excluded | a completed or cancelled dossier is history |
| a READY section is never overdue | an overdue badge on finished work is noise that trains people to ignore the badge |

## 7. Attention queue

Enumerated reason codes, never generated prose. A sentence assembled from the
underlying rows would carry exactly the detail the projection withholds —
"workflow WF-14 was rejected" tells a caller without workflow permission that
WF-14 exists — and would need re-auditing every time the wording changed. The
frontend maps codes to copy; the backend never writes a sentence about a
resource.

### Ranking

Lower sorts first. Defined once in
[`attention.py`](../backend/submission_operations/attention.py) so the ordering
test and this table read the same numbers.

| Rank | Reasons | Severity |
|---|---|---|
| 1 | `required_section_blocked`, `open_blocker`, `blocked_upgrade_plan` | `blocked` |
| 2 | `overdue_required_section` | `overdue` |
| 3 | `workflow_rejected` | `attention` |
| 4 | `due_soon_required_section`, `workflow_waiting_review` | `attention` |
| 5 | `required_section_not_started` | `attention` |
| 6 | `stale_upgrade_plan`, `dossier_on_hold`, `case_with_no_dossier` | `informational` |

Blocked outranks overdue because an overdue item someone can still work on is a
worse thing to bury than a blocked one nobody can. Rejected outranks due-soon
because a rejection is already a fact while a due date is a forecast.

Full sort key: **rank → earliest due date → most recently updated →
`public_id`**. The final tie-break is not decoration: without a total order,
pagination silently drops and repeats rows between pages.

### Severity vocabulary

`blocked` · `overdue` · `attention` · `informational`

Deliberately plain rather than borrowing `Major` or `Critical deficiency`, which
already mean something specific to the people who will read this screen.
`critical` here would mean "someone should look today", not "a deficiency" — so
the word is not used at all.

### A restricted module contributes nothing

Not a redacted row. Not a "3 hidden" note. **A count of what was withheld is
itself the disclosure this module exists to prevent.**

## 8. Due dates

```
DISPLAY_DUE_SOON_DAYS = 7
```

**A display window with no regulatory meaning.** Not a submission deadline, a
review period, a statutory clock or an agency timeline. Seven was chosen because
it is one working week. Tenants set their own due dates; this only decides when
one starts appearing in amber. A test asserts the disclaimer sits beside the
constant, so an edit that changes the number and drops the note turns red.

Boundaries, all inclusive-of-today-as-due-soon:

| Due date | Overdue | Due soon |
|---|---|---|
| yesterday | ✅ | — |
| today | — | ✅ |
| +1 … +7 | — | ✅ |
| +8 | — | — |

`timezone.localdate()`, not `date.today()`: taking "today" from the server's
naive clock puts the boundary in the wrong place for anyone not in UTC.

## 9. Tenant isolation

Every aggregate is tenant-scoped in its first query. Nothing is fetched broadly
and filtered in Python. Two-tenant tests cover the overview, attention queue,
case table, dossier table, owner workload and activity feed — and they run
against a *loud* other tenant (12 blockers, 6 cases) so a leak would be obvious
rather than invisible.

Owner workload groups owners off the sections themselves rather than the
tenant's user list, so a user from another tenant cannot appear — user existence
is itself disclosure.

## 10. Recent activity

Reads the existing `AuditEvent`. No new audit log, and **viewing the dashboard
writes nothing** — the repository does not audit reads, and inventing that for
one screen would both break the convention and bury the write trail under
dashboard noise.

Two allow-lists, not deny-lists:

- **Event types** — a new event type from a later milestone appears here when
  someone decides it is safe, not automatically.
- **Payload keys** — only `action`, `dossier_public_id`, `case_public_id`.
  Titles, notes, descriptions, reasons and blueprint names are absent by
  construction. The feed says *what kind of thing happened to which
  identifier*, never what it said.

Each event type is gated by the module it belongs to.

## 11. Query strategy

Aggregate per page, not per row.

Each list resolves in a **bounded** number of queries: one for the page of
parents, then one grouped aggregate per dimension over exactly that page's ids.
Adding rows to a page adds no queries.

The alternative — annotating four `Count(distinct=True)` across three joins onto
one queryset — keeps the query count at one and quietly multiplies the row
count, which is worse and much harder to notice.

**The known N+1 trap:** M11's `is_stale()` loads one dossier's sections per
call. Calling it per plan would be one extra query per plan — exactly the bug
M11's own review caught in its plan list. The dashboard loads the sections for
every relevant dossier in one query and reuses M11's `structural_fingerprint`.
The formula is not reimplemented; only the loading is batched.

### Measured budget

Flat from 1 to 100 cases, in every surface:

| Surface | 1 case | 100 cases |
|---|---|---|
| overview | 25 | 25 |
| case list | 24 | 24 |
| dossier list | 22 | 22 |
| attention queue | 26 | 26 |
| owner workload | 18 | 18 |
| recent activity | 18 | 18 |

Absolute counts include auth, session and tenant middleware. The requirement is
that they stay bounded, not that they are small — so every test compares counts
across fixture sizes rather than pinning a number that breaks on every harmless
refactor and still would not catch the thing that matters.

**No cache.** Correctness and permission isolation first: a stale
cross-permission dashboard cache is worse than a slower query.

The attention queue takes at most `ATTENTION_SCAN_LIMIT = 500` rows per source
and reports `truncated: true` when it hits the cap. It is a triage list, not an
export, and a bound plus a truthful flag beats silent truncation that reads as
"this is everything".

## 12. API

| Endpoint | Returns |
|---|---|
| `GET /submission-operations/overview/` | tenant-wide counts, each module gated |
| `GET /submission-operations/attention/` | ranked queue, paginated |
| `GET /submission-operations/cases/` | case rows, paginated, filterable |
| `GET /submission-operations/dossiers/` | dossier rows, paginated, filterable |
| `GET /submission-operations/owners/` | owner workload |
| `GET /submission-operations/recent-activity/` | allow-listed audit feed |

Public IDs only; no internal PK appears anywhere, including the tenant's. Filter
and sort values are validated against enums — an unvalidated filter reaching the
ORM lets a caller probe fields the API never meant to expose. `page_size` is
capped, or a bounded-query dashboard becomes a full-table materialisation.

A caller who may open the dashboard but not see cases gets
`{"results": null, "count": null, "restricted": true}` — not a 403, because they
were entitled to ask.

## 13. Frontend

Route `/submission-operations`. Desktop-first, because it is a dense operations
screen — but every wide table scrolls inside its own labelled region, so the
page body never scrolls sideways at tablet width.

- **Summary cards** — restricted dimensions read "Unavailable" with an
  explanation, never `0`.
- **Attention queue** — severity badges carry a word, never colour alone. Every
  colour pairing is asserted at ≥ 4.5:1 by a **computed** contrast test, because
  axe cannot resolve an inline background against a parent's ground; M9 shipped
  two real AA failures behind exactly that silence.
- **Links only where the caller can follow them.** Rendering a link into a
  hidden module would both break and disclose that the target exists.
- **Empty ≠ restricted.** "No cases yet" and "You do not have permission to view
  cases" are different states, and a screen rendering them identically teaches
  users the wrong thing about their own data.
- Table scroll regions are named `"<X> table"` so they do not collide with the
  enclosing `<section>`, which is itself a region — two nested regions sharing a
  name announce identically and tell a screen-reader user nothing.

## 14. Testing

**Backend (75)**: overview across empty/populated tenants; internal readiness
including the deliberate M9-disagreement case; due-date boundaries at
−1/0/+1/+6/+7/+8; retired and terminal exclusions; attention ranking, stability
and filtering; two-tenant isolation on every surface; permission projection for
every module; the null-vs-zero rule end to end over HTTP; recent-activity
allow-listing; and query-cost invariance.

**Frontend**: 26 unit, 12 new accessibility checks (77 → 89), 16 Playwright.

### Mutation testing

Every guard turned tests red; all files restored md5-identical.

| Mutation | Red |
|---|---|
| Module permission gate always open | 9 |
| Retired-section exclusion removed | 4 |
| Authoritative readiness → status inference (4 call sites) | 4 |
| Overdue boundary off by one (5 call sites) | 4 |
| Null replaced by zero | 3 |
| Attention ranking flattened | 2 |
| Tenant filter removed | 2 |

The tenant-filter mutation turns exactly 2 red, and that is complete rather than
thin: the overview aggregate and owner workload are the only two places where
that filter is the sole tenant guard. Everywhere else the query is already
narrowed by a tenant-scoped case or dossier join, so the filter is defence in
depth and removing it changes nothing observable.

Three mutations initially turned only **one** test red — all of them in the
overview — which was a test-coverage finding rather than a passing guard: the
same expressions are evaluated again per-case, per-dossier and per-owner, and a
guard proven in one place and merely repeated in three is three places nobody is
checking. Those surfaces now have their own tests.

## 15. Regulatory boundaries

No production regulatory structure. No CTD, eCTD, CEP, DMF, ANDA, USFDA or EMA
content or rules. No regulatory impact assessment, submission validation,
readiness claim or agency claim. No Part 11, GxP, validated-process or
agency-approval claim. Synthetic codes throughout. No change to the 20
governance decisions, the 0/20 approval state, Item 1, the 13 owner-policy
decisions, S1 or S2.

**Everything on this screen is internal RegX operational status.**
