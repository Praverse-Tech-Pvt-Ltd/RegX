# Dossier Upgrades

**Blueprint change impact, and the only sanctioned way to move a dossier forward.**

> **BLUEPRINT CHANGE IS NOT DOSSIER CHANGE.** Publishing a newer blueprint
> version never alters a dossier. An upgrade happens only when a person
> generates a plan, reviews it item by item, and explicitly applies it.

> **READY means the plan has been reviewed inside RegX and may be applied.** It
> is not a regulatory approval, a QA approval, an agency decision or a claim
> about the submission. There is deliberately **no APPROVED state**.

> **No regulatory judgement of any kind.** Nothing here knows what a submission
> requires. It compares two tenant-authored outlines and reports the
> differences. No CTD, CEP, DMF, ANDA, USFDA or EMA structure ships or is
> assumed. No Part 11 claim, no GxP validation claim, no validated-production
> claim.

Stacked on Milestone 10 (`regx/feat/dossier-blueprints`), branched from
`a6c3e354ca79dd970db387444191d43d31d5b1ae`. **Must not merge before M10, which
must not merge before M9.**

---

## 1. Purpose

Milestone 10 made a dossier an independent snapshot, which is exactly right and
also leaves a gap: there was no way to move one onto a newer outline at all.
This adds a controlled path — explicit, reviewable, auditable, transactional,
tenant-scoped, permission-gated and provenance-preserving.

```
Blueprint v1 ACTIVE ──instantiate──► Dossier
Blueprint v2 ACTIVE                  Dossier unchanged   ← M10 guarantee
                                          │
                            generate ─────┤ read-only proposal
                            review   ─────┤ decisions only
                            apply    ─────► only the accepted items
```

## 2. Non-goals

Deliberately absent, none of it partially built: automatic dossier rewrite; a
regulatory completeness engine; eCTD upgrade; CEP/DMF/ANDA rules; AI authoring;
auto-approval; auto-readiness; agency impact assessment; submission validation;
document content migration; workflow or checklist migration.

**Nothing is applied without an explicit user action.** Generate is not apply.
Accept is not apply. Ready is not apply.

## 3. Why matching has to be derived

`dossier_blueprints._clone_sections` copies a version's structure into fresh
rows and records **no pointer back** — it builds a local `mapping` and discards
it. There is no stored v1→v2 lineage, so the comparison derives one. Each hop is
backed by a constraint or a stored row, not a heuristic:

```
dossier section ──[BlueprintSectionOrigin — a stored row]──► source section
source section  ──[section_code, unique per version]───────► target section
```

`unique_active_blueprint_section_code` makes a code identify at most one active
section per version, so the second hop is exact rather than a guess.

### Where it refuses to guess

A dossier section with **no origin row** was added by hand and is not
blueprint-controlled.

| Situation | Outcome |
|---|---|
| Manual section, code matches nothing in the target | **left entirely alone** — no item at all |
| Manual section, code **collides** with a target section | **`CONFLICT`**, blocked, manual review |

The collision is genuinely ambiguous: adding the target section would violate
`unique_active_section_code_per_dossier`, and updating the manual one would
silently adopt work the user owns. Both guesses could be wrong, so it makes
neither.

A section whose **code changed** between versions is reported as a retirement
plus an addition, not a rename — two truthful statements rather than one
inferred one, and the retirement still carries the runtime-work protection.

## 4. Change types

`ADD_SECTION` · `RETIRE_SECTION` · `UPDATE_TITLE` · `UPDATE_DESCRIPTION` ·
`UPDATE_REQUIRED` · `MOVE_SECTION` · `REORDER_SECTION` · `UPDATE_DUE_OFFSET` ·
`NO_CHANGE` · `CONFLICT`

**Structural and default-metadata only.** `status`, `readiness`,
`readiness_reason`, blockers, document/workflow/checklist links, `owner` and
`notes` are never blueprint-controlled and never appear as a change. A blueprint
has no opinion about work in progress.

One item per field, so accepting a title change never silently accepts a
reparent alongside it.

## 5. Runtime work is protected

A blueprint dropping a section is a statement about the template. It is not a
statement that the work someone has done under that section is worthless — and
that distinction is the difference between a useful upgrade and a destructive
one.

A proposed retirement is emitted **`BLOCKED`** when the dossier section has:

| Reason code | Meaning |
|---|---|
| `has_active_children` | still has child sections |
| `has_open_blockers` | an open blocker |
| `has_resource_links` | linked documents, workflows or checklists |
| `has_recorded_progress` | status moved off the default, an owner, notes, or a due date |

A blocked item cannot be accepted, and a plan holding one cannot be applied.

**These facts are re-checked at apply time, not merely at generation.** The
window between review and apply is the dangerous one: runtime changes
deliberately do not stale a plan (§6), so a blocker opened or a document linked
after the reviewer accepted would otherwise ride straight through — M9's
`retire_section` refuses active children and nothing else, which is right for a
human acting deliberately with the section in front of them and wrong for a
decision made against facts that have since moved. The whole apply is refused
rather than the item skipped: the reviewer approved a plan, not a subset of one.

A **manually set due date is never overwritten** — re-checked the same way, so a
date set between generate and apply survives.

## 6. Staleness

A plan describes a dossier as it stood when the plan was generated. If the
dossier moves afterwards, the plan is describing something that no longer
exists: *"add a child under section B"* is a different act if B has since been
retired.

Each plan stores a canonical SHA-256 over the dossier's active structure —
`public_id`, parent, `section_code`, `title`, `description`, `required`,
`sequence` — order-independent, retired rows excluded. `apply` recomputes it and
**fails closed**: a plan that cannot prove the dossier is unchanged is not
applied.

**Runtime changes deliberately do not make a plan stale.** If ticking a status
or taking ownership invalidated every open plan, users would learn to regenerate
reflexively and stop reading the guard at all. That exemption is safe only
because apply re-checks the runtime facts a retirement actually depends on
(§5) — the two decisions are load-bearing together, not separately.

Regenerating replaces every item and resets review decisions — an accept was a
judgement about a dossier that has since moved, and silently reapplying it would
launder a stale decision into a fresh-looking plan. The plan's `public_id`
survives.

## 7. Apply

### Everything is re-proved under lock

Generation checked the target and the provenance. Neither stays true on its
own, and **the fingerprint cannot stand in for either**: it hashes the dossier's
section tree, and both of these move without touching a single section.

| Re-proved at apply | Why generation is not enough |
|---|---|
| target is still ACTIVE | a version can be retired between review and apply. Honouring the plan anyway would let a withdrawn version keep changing dossiers after its owner pulled it. |
| target still belongs to this tenant and this blueprint | the plan's columns are frozen by `0002`, so a divergence means the rows they point at moved |
| target is not the source | the plan's own check constraint says so; re-proved because it is cheap and the alternative is a self-referential upgrade |
| the dossier's derived provenance is still the plan's source | another plan may have advanced the chain. See §13. |

Provenance is **derived from governed history under the dossier lock** — latest
`DossierUpgradeApplication`, else the `BlueprintInstantiation` — never from a
cached relation and never from the caller. It fails closed: a dossier whose
provenance is missing or inconsistent is not upgraded.

Both refusals name what moved and what to do, and nothing else. No `public_id`,
no version number, no blueprint name: a caller who lost a race learns that they
lost it, not the shape of what won.

**Nothing is written before all of it passes** — no section, no item status, no
plan status, no history row, no origin, no success audit.

### Lock order

`apply_plan` is the first operation in the codebase to write across both
governed hierarchies, so it takes the order each already uses internally rather
than inventing a third:

```
1. SubmissionDossier         M9's root. M9 services re-take it as a no-op,
                             so nothing here ever upgrades a lock.
2. DossierUpgradePlan
3. DossierBlueprintVersion   source and target, by version_number -- the order
                             activate_version uses on a sibling set.
4. DossierSection            taken by M9 services, under 1.
```

The dossier row is the serialization point for the provenance chain. Every
`DossierUpgradeApplication` is inserted while it is held, so a transaction
holding it reads a settled chain rather than one another transaction is midway
through extending — and two applies on one dossier serialize even when they are
different plans holding different plan rows.

`DossierBlueprint` is deliberately **not** locked. `retire_version` takes
blueprint-then-version, so taking it after step 3 would invert that order; and
it buys nothing, because `retire_version` must take the version row step 3
already holds.

### Order of writes

All-or-nothing, in one transaction, in a safe order:

1. **Additions**, shallowest first — the comparison orders them by depth, so a
   parent is always created before its children.
2. **Metadata and moves.**
3. **Reorders**, through `reorder_section` — `update_section` may not move
   `sequence` at all, by the M9 `0004` window's design.
4. **Retirements**, deepest first — M9 refuses to retire a section with active
   children. Their runtime safety is re-checked as a precondition before step 1,
   so a plan whose facts have moved is refused before anything is written rather
   than rolled back after.
5. **Readiness recalculation**, through the M9 engine. Readiness is derived,
   never set.
6. **Provenance**, then audit.

Ordering is not cosmetic: each of these fails outright in the wrong sequence.

**Every dossier write goes through `submission_dossiers.services`**, so the M9
sanctioned window and its triggers apply exactly as they do to a hand-edited
dossier. Nothing here writes a section row directly.

### Sequence allocation

An added section takes the blueprint's `sequence` where that slot is free, and
the next free slot where it is not. A collision is the normal case — the section
the blueprint dropped to free that slot may not be retired in *this* dossier at
all, because the reviewer rejected that item or it was blocked by live work.
Failing the whole upgrade over an ordering collision would be the wrong trade.

## 8. Provenance

M10's `BlueprintInstantiation` records how the dossier was **created** and is
never rewritten. An upgrade is a later, additional event, so it gets its own
record. Rewriting the instantiation to say the dossier "came from v2" would
erase the fact that it was built from v1 and then moved — and M10's triggers
refuse it anyway, correctly.

| Model | Records |
|---|---|
| `DossierUpgradeApplication` | one applied plan: dossier, plan, source/target versions, snapshot version numbers, counts, who and when |
| `UpgradeSectionOrigin` | which target-version blueprint section produced each section an upgrade added |

A dossier accumulates history: v1 instantiated, v2 applied, v3 applied. Ordered
and append-only.

`UpgradeSectionOrigin` exists because M10's `BlueprintSectionOrigin` **cannot**
carry this: its INSERT guard requires the blueprint section to belong to the
instantiation's version, and an upgrade-added section comes from a later one.
That refusal is correct.

The next comparison layers upgrade origins over instantiation origins, so a
section added by an upgrade stays blueprint-tracked rather than looking
manually-added.

## 9. Authorization

| Codename | Granted to |
|---|---|
| `.view` | DOER, REVIEWER, VP, TENANT_ADMIN, PLATFORM_SUPPORT |
| `.generate` | DOER, TENANT_ADMIN |
| `.review` | DOER, REVIEWER, TENANT_ADMIN |
| `.apply` | DOER, TENANT_ADMIN |
| `.cancel` | REVIEWER, VP, TENANT_ADMIN |

**Multi-gate, checked independently:**

| Operation | Gates |
|---|---|
| generate | `dossier_upgrades.generate` + `submission_dossiers.view` + `dossier_blueprints.view` |
| apply | `dossier_upgrades.apply` + `submission_dossiers.manage_sections` + non-terminal dossier + target still ACTIVE + provenance unmoved + not stale |

Target-domain gates are checked **before the target is resolved**, and every
failure raises the same message, so absent / cross-tenant / unauthorised are one
indistinguishable outcome — the M8 existence-oracle lesson. A test asserts the
two messages are byte-identical.

PLATFORM_SUPPORT holds `.view` and no `submission_dossiers.manage_sections`, so
it can read a plan and cannot apply one.

## 10. Tenant isolation

Every object is tenant-scoped and fails closed. Cross-tenant plan, item, dossier,
apply and history are all **404, never 403**. Both the view layer
(`filter(tenant=...)`) and the service layer (`_assert_tenant`) enforce it, and
tests call the service directly with a foreign object so the service gate is not
merely riding on the view's filter.

## 11. Safe projection

A blueprint version's number and status are facts about the dossier's own
history and are always shown. The blueprint **name** is tenant-authored free
text, added only for a caller who independently holds `dossier_blueprints.view`;
everyone else gets `restricted: true`. An upgrade permission is not a key to the
blueprint library.

## 12. Database governance

There is deliberately **no sanctioned window** here. M9 needed one because a
`DossierSection` is mutable by four operations with four column sets. A plan's
own `status` is the discriminator instead — DRAFT/READY editable, APPLIED and
CANCELLED frozen — and the triggers read it directly. It cannot be forgotten,
cannot be left open, and needs no Python cooperation.

| Rows | Enforced by `0002` |
|---|---|
| Plans | identity and provenance frozen always; a terminal plan refuses every UPDATE; only DRAFT→READY→APPLIED or open→CANCELLED, stamps together; DELETE refused |
| Items | content frozen — including `change_type`, values and section references; only the review status may move; frozen once the plan is terminal; DELETE permitted **only while the plan is open**, for regenerate |
| History | `DossierUpgradeApplication` and `UpgradeSectionOrigin` refuse UPDATE and DELETE outright; **INSERT is validated** so a fabricated record cannot be frozen into place |

That last line is the M10 review lesson applied up front: freezing a row that
was never checked on the way in does not protect the truth, it preserves
whatever was written.

`0003` adds the part `0002` cannot see. `0002` proves each history row is
internally coherent — its tenant, dossier and versions match the plan it names —
and says nothing about how that row relates to the ones already there.

| Guard | What it holds, and what it does not |
|---|---|
| `UNIQUE (dossier, source_version)` | **Holds under concurrency.** A unique index is not snapshot-dependent, so two simultaneous inserts claiming the same source cannot both succeed whatever the isolation level or lock order. Safe because a source version can never repeat: `activate_version` refuses anything but a DRAFT, so a RETIRED version never becomes ACTIVE again. |
| chain trigger | **Holds against a sequential forged insert** — one that invents a starting point or grafts onto a chain ending elsewhere. It reads committed rows, so two concurrent inserts can both observe the same prior state and both pass; that gap is what the index above closes. |

Neither is sufficient alone and neither is claimed to be. A test drives two
concurrent forged inserts and asserts the failure comes from the index — the one
case the trigger provably cannot catch.

Together: a dossier's history is a single chain, each link starts where the
previous ended, and the first starts at the version it was instantiated from.

`Model.save()` resolves through `_base_manager` — a plain `Manager` Django
auto-creates, not `objects` — so restricting the public manager cannot cover it,
and a raw cursor never runs a line of Python. The triggers are the floor.

## 13. Concurrency

| Race | Guard |
|---|---|
| Two simultaneous applies | dossier row `select_for_update` + the DRAFT→READY→APPLIED trigger. Exactly one wins. |
| Two simultaneous generations | `unique_open_upgrade_plan_per_target` partial index. Exactly one open plan. |
| Edit between ready and apply | the fingerprint check. Refuses rather than writing against moved facts. |
| Target retired during apply | both transactions take the version row `FOR UPDATE`, so one waits for the other. Either order is valid; applying a RETIRED target is not. |
| The chain forking | `UNIQUE (dossier, source_version)`. §12. |

Tested with real threads against PostgreSQL, including the apply-versus-retire
race, whose outcome is genuinely undetermined — the test asserts the safety
property rather than a timing.

### Why two READY plans cannot both reach the chain

Worth stating plainly, because it decides how much the provenance gate is
actually carrying:

- only one version per blueprint is ACTIVE — `activate_version` retires the
  previous one in the same transaction;
- at most one **open** plan per (dossier, target).

So two open plans must have different targets, and at most one of those targets
can be ACTIVE. Every reachable sequential attempt to apply a second plan is
therefore met by the target-ACTIVE gate first.

That makes the service-level provenance gate **defence in depth**, and it earns
its place on the case those two constraints do not cover: a history row that
arrived without passing the service at all. A test constructs exactly that — the
chain advanced by a raw insert, leaving a plan whose target is still perfectly
ACTIVE — and its counterpart at the database is `0003`.

## 14. Audit

`dossier_upgrade.{plan_created,plan_regenerated,item_accepted,item_rejected,plan_marked_ready,plan_applied,plan_cancelled}`
through the existing `AuditEvent` with a strict allow-list.

**Never recorded**: section titles, descriptions, notes, blueprint names, plan
notes, or the values of any changed field. `section_code` and `field_name` are
present because a reviewer needs them to follow a trail; the values are not.

A refused apply emits no success event, and a rolled-back apply leaves no audit
row at all.

## 15. Terminal states

A COMPLETED or CANCELLED dossier refuses application. Comparison and viewing
remain allowed, because a closed dossier's history is still worth reading and a
plan is only a document. M9 would refuse each write anyway; refusing early gives
a clean answer instead of a half-attempted transaction.

## 16. Migration classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.

| Migration | Forward | Rollback |
|---|---|---|
| `0001_initial` | **Class A** — four `CreateModel`s, no `RunPython`/`RunSQL`, no existing table altered | **CLASS C — DATA RESTORE REQUIRED once any governed upgrade data exists** |
| `0002_upgrade_db_governance` | **Class A** — exactly 6 functions and 7 triggers; no table altered, no row read or written | **Class A on its own terms** |
| `0003_upgrade_provenance_chain` | **Class A** — one unique constraint plus exactly 1 function and 1 trigger. The constraint is validated on apply, so a database already holding a forked chain fails loudly rather than losing a row — correct, because a fork is an integrity incident, not something a migration should paper over. | **Class A on its own terms** |

> Reversing `0001` destroys every plan and the review decisions on its items,
> the applied-upgrade history, and the upgrade section origins. None of it is
> reconstructible: a dossier is deliberately a snapshot that never reads back to
> its blueprint, so once this history is gone the dossier cannot say how it came
> to look the way it does.
>
> **Removing `0002`'s protection does not make reversing `0001` safe.** The
> relationship is one-way.

Both migrations' counts are asserted against the generated SQL by a symmetry
test — M10 shipped a docstring claiming five functions and eight triggers where
the SQL had seven of each, so these numbers are checked by the build rather than
by proofreading. (`0002` claimed such a test already covered it; the test lived
in `dossier_blueprints` and did not, which the review pass caught.)

## 17. Testing

**Backend (129)**: comparison across every change type; ambiguity and conflict;
retirement safety for each runtime signal; generation rules including
cross-blueprint, draft and retired targets; review; staleness including the
deliberate runtime exemption; selective apply; transactional rollback with
injected failures at two different points; runtime-work preservation both
across an upgrade and against work recorded after review; provenance
including sequential upgrades; tenant isolation at both layers; multi-gate
authorization with indistinguishability; DB governance; real-thread concurrency;
and query-cost invariance; and apply-time revalidation — a target retired after
review, a chain advanced by an insert that never passed the service, a
non-instantiated dossier, a cross-blueprint plan, sequential v1→v2→v3, and the
database chain guards against a fork, a link that starts nowhere and a link
grafted past the end.

**Frontend**: 25 unit, 19 new accessibility checks (58 → 77), 15 Playwright.

### Query cost

| Surface | Sizes | Result |
|---|---|---|
| Plan list | 1 / 20 / 100 plans | flat |
| Plan detail | 10 / 100 / 500 items | flat |
| Generation | 20 → 40 sections | sub-linear |

The plan list originally grew one query per plan, because `is_stale()`
recomputed the dossier fingerprint per row though every plan in the list shares
one dossier. The query-cost test caught it at 100 plans.

### Mutation testing

| Mutation | Tests turned red |
|---|---|
| Service tenant gate neutered | 2 |
| Staleness check removed | 2 |
| `@transaction.atomic` removed from apply | 2 |
| Runtime-work retirement blocker neutered (generation) | 7 |
| Apply-time retirement re-check removed | 2 |
| Apply-time current-provenance guard removed | 3 |
| Apply-time target-ACTIVE guard removed | 3 |
| Provenance/history freeze trigger removed | 2 |
| Multi-gate apply authorization removed | 2 |

All three mutated files restored and md5-verified byte-identical.

## 18. Regulatory boundaries

No production regulatory structure. No CTD, CEP, DMF, ANDA, USFDA or EMA content
or rules. No automatic regulatory impact claim. No Item 1 resolution. No change
to the 0/20 governance count. No S-1/S-2 closure. No Part 11, GxP,
validated-process or agency-approval claim.

**READY is internal review. Applying changes only what a person accepted.**
Neither is an agency decision, and the UI says so on the panel itself.
