# Dossier Blueprints

**Reusable, versioned, tenant-controlled dossier outlines.**

> **ACTIVE means available for internal RegX dossier instantiation.** It is not a
> regulatory approval, a QA approval, an agency approval, a submission
> acceptance, or a validated status. There is deliberately **no APPROVED state**.

> **No production regulatory structure ships here.** No CTD modules, no CEP, DMF
> or ANDA structures, no country or agency requirements. `section_code` is free
> text and every test uses generic synthetic codes — A, A.1, B.

> **Not regulatory approval.** No 21 CFR Part 11 compliance claim, no GxP
> validation claim, not a validated system.

Stacked on Milestone 9 (`regx/feat/submission-dossiers`), branched from
`57c0a1544aa295e582375d824c950f3193bcb09c`. **This must not merge before M9.**

---

## 1. Purpose

Milestone 9 lets a user build a dossier outline by hand. This lets a tenant
capture that outline once, version it, and stamp it into as many cases as they
like.

```
DossierBlueprint  "Synthetic outline A"
├── Version 1  ACTIVE      A, A.1, A.2, B, B.1
├── Version 2  DRAFT       (cloned from v1, being edited)
└── Version 3  RETIRED
```

## 2. The core architectural rule

**Blueprints define structure. Dossiers own execution.**

Instantiating a version creates ordinary `submission_dossiers` records —
governed, audited, independent. A dossier **never reads back to its blueprint**.
Publishing version 2 cannot rewrite a dossier built from version 1, and a test
proves it by editing and republishing while asserting the dossier is unchanged.

That is why provenance is a snapshot rather than a live reference, and why the
per-section origin mapping exists for future comparison but is read by nothing
that decides behaviour.

## 3. Non-goals

Deliberately absent, and none of it partially built: eCTD publishing; CEP, DMF or
ANDA rules engines; an agency requirements database; regulatory intelligence;
document generation; AI authoring; a workflow, checklist or evidence engine;
submission validation.

**Template upgrades are also a non-goal.** M10 does not apply version 2 to an
existing dossier, merge blueprint changes, or diff sections into a live dossier.
That is a future milestone, and doing it badly here would undermine the snapshot
guarantee that makes the rest safe.

## 4. Relationship to `templates_registry`

`templates_registry` already provides a controlled-template system: stable
identity across versions, numbered versions with a uniqueness constraint, a
draft/review/approved/active/superseded/retired lifecycle, immutable published
versions, an "only one active version" partial unique index, tenant scoping, a
self-referencing section tree, an importer and an approval trail.

It is **composed with, not reused**, for four reasons:

| | |
|---|---|
| **Semantics** | `TemplateLifecycleStatus` includes `APPROVED`, backed by `TemplateApproval` rows carrying reviewer, decision and role-at-time — the *regulatory content approval* concept tied to the governance gate. A blueprint reaching that state would be indistinguishable in the data model from an approved regulatory template. A dossier outline is a tenant's internal working convenience; calling it approved would assert something nobody decided. |
| **Content model** | `TemplateSection` carries `raw_title`, `normalized_title`, `source_locator` and importer `metadata`, and owns `TemplateItem` questions with a `ResponseType`. It is a questionnaire tree, not a dossier outline. |
| **Deletion governance** | `RegulatoryTemplate.tenant` is `CASCADE` and nullable; `TemplateSection`'s FKs are `CASCADE`. Milestones 8 and 9 established mandatory tenant, `PROTECT` everywhere and retire-never-delete. Hosting blueprints under `CASCADE` would regress guarantees that took three review rounds to establish. |
| **Coupling direction** | Instantiation goes blueprint → `submission_dossiers`. Putting it inside `templates_registry` would make the regulatory content registry depend on the execution layer, which the import-linter contracts deliberately keep isolated. |

**Its patterns are reused verbatim**: `unique(blueprint, version_number)` from
`unique_template_version_number`; the partial unique index on ACTIVE from
`unique_active_version_per_template`; an immutable-status frozenset; and
`select_for_update` over the sibling version set during activation, from
`templates_registry.lifecycle.activate`.

## 5. Models

| Model | Purpose |
|---|---|
| `DossierBlueprint` | Stable identity across versions. Holds no structure. |
| `DossierBlueprintVersion` | One immutable-once-published revision. |
| `DossierBlueprintSection` | One node of a version's outline. Structure only. |
| `BlueprintInstantiation` | The permanent record that one dossier came from one version. |
| `BlueprintSectionOrigin` | Which blueprint section produced which dossier section. |

A blueprint section carries **no runtime state** — no status, readiness,
blockers, links or evidence. Those belong to the instantiated dossier section,
which is the governed execution record. A blueprint that carried runtime state
would drift from the dossiers built out of it the moment either changed.

### Provenance lives in its own models

Rather than adding columns to `submission_dossiers.SubmissionDossier`. Two
reasons: Milestone 9 is still under review and adding fields to its model would
entangle the two, and provenance is genuinely its own record with its own
immutability rules. It also gives the per-section origin mapping somewhere
natural to hang.

Foreign keys answer *which row* and are `PROTECT`ed so it cannot vanish; the
snapshot fields (`version_number`, `blueprint_name`, `section_count`) answer
*what did it say at the time*, which a rename would otherwise destroy.

## 6. Lifecycle

```
DRAFT ──activate──► ACTIVE ──retire──► RETIRED
  │                                        ▲
  └──────────────retire────────────────────┘
```

Three states, and deliberately no APPROVED. **ACTIVE means available for
internal RegX dossier instantiation** and nothing more.

**Only one ACTIVE version per blueprint**, matching the `templates_registry`
convention. Activating v2 retires v1 in the same transaction, so there is never
an instant with two or zero. A partial unique index enforces it beneath the
service, so even a code path that skips the service cannot produce two.

Editing an ACTIVE version to make the next revision is impossible by design.
`create_version` clones structure into a fresh DRAFT; v1 is untouched, and every
dossier built from it stays exactly as it was.

## 7. Immutability

| State | Structure |
|---|---|
| DRAFT | editable |
| ACTIVE | frozen forever |
| RETIRED | frozen forever |

### Why there is no sanctioned window

Milestone 9 needed a transaction-scoped "which operation is running" declaration
because a dossier section is legitimately mutable by four operations with four
different column sets, and the database had no other way to tell a reorder from
a readiness write from an arbitrary rewrite.

**Blueprints do not have that problem.** A version's own `status` is the
discriminator, and the `0002` triggers read it directly. That is strictly better
here: it cannot be forgotten by a caller, it cannot be left open, it needs no
Python cooperation, and it is the same fact a human reviewer reads off the row.
A window would add a mechanism without adding a guarantee, and every mechanism
is another thing to get wrong.

### Three layers

| Path | Guard |
|---|---|
| `objects.update()` / `.bulk_update()` / `.delete()` | the public queryset writes nothing at all |
| `instance.save()` | the `0002` triggers — `Model.save()` resolves through `_base_manager`, a plain `Manager` Django auto-creates rather than `objects`, so a manager restriction **cannot** cover this path |
| raw SQL, psql, a migration | the `0002` triggers, the only layer that holds when Python is not in the path |

### What `0002` enforces

**Versions** — identity and provenance frozen always (`id`, `public_id`,
`tenant_id`, `blueprint_id`, `version_number`, `created_by_id`, `created_at`,
`supersedes_id`). A RETIRED version refuses every UPDATE. An ACTIVE one may only
go to RETIRED, with both stamps together, and its activation stamps are frozen.
A DRAFT may edit notes and transition. DELETE refused.

`version_number` never moves, so the race guard in `create_version` cannot be
undone after the fact.

**Sections** — frozen entirely unless their version is DRAFT: one rule covering
"no edits after activation", "no edits after retirement" and "no inserting into
a published version". Identity frozen always, retirement one-way, DELETE
refused. INSERT re-validates the hierarchy.

**Provenance** — `BlueprintInstantiation` and `BlueprintSectionOrigin` refuse
UPDATE and DELETE outright. There is no legitimate edit: the row records that a
thing happened, and rewriting which version a dossier came from would falsify
the only record of it.

An `information_schema.columns` coverage test asserts every column on both the
version and section tables is classified, so a column added later cannot quietly
become writable.

## 8. Hierarchy

Same integrity rules as Milestone 9, enforced in the service **and** at the
database:

| Attack | Result |
|---|---|
| Self-parent | refused |
| Parent is own descendant (cycle) | refused |
| Parent in another version | refused |
| Parent in another tenant | refused |
| Parent is retired | refused |
| Nesting past `MAX_BLUEPRINT_DEPTH` (10) | refused |

The database cycle check climbs the ancestor chain bounded by
`MAX_BLUEPRINT_DEPTH + 2` hops — a handful of indexed single-row lookups, run
only when `parent_id` actually changes. The bound terminates on a pre-existing
cycle rather than spinning, and enforces depth from below.

`MAX_BLUEPRINT_DEPTH` equals `submission_dossiers.MAX_SECTION_DEPTH`, asserted by
a test: a blueprint deeper than a dossier may hold would be unusable.

**Hierarchy comes from `parent`, never from parsing `section_code`.** A test
creates `A.1` with no parent and asserts it stays a root.

## 9. Activation validation

`validate_structure` refuses activation of a version that is not internally
coherent: at least one active section, unique codes, every parent present and in
this version, no cycles, depth within the ceiling, and no two siblings sharing a
sequence.

**It is a structural check and nothing more.** RegX has no idea what a given
submission requires, and a blueprint that passes here is merely coherent — never
regulatorily complete.

## 10. Concurrency

| Race | Guard |
|---|---|
| Two version creations | blueprint row `select_for_update`, plus `unique(blueprint, version_number)` beneath it. Four concurrent threads produce 1, 2, 3, 4. |
| Two activations | the whole sibling version set is locked, plus the partial unique index. Three concurrent activations leave exactly one ACTIVE. |
| Section write during activation | both take the version lock, so a write either lands before the publish or meets a frozen version — and the INSERT trigger refuses it either way. |

All three are tested with real threads against PostgreSQL, not simulated.

## 11. Instantiation

```
POST /dossier-blueprint-versions/{id}/instantiate/
{ "regulatory_case_public_id": "…", "title": "…",
  "owner_public_id": null, "target_date": null }
```

The version comes from the URL. **The tenant is never accepted from the client.**

### Three gates, none implying another

1. `dossier_blueprints.instantiate` — checked by the view
2. `submission_dossiers.create` — this creates a dossier
3. `regulatory_cases.view` — this reads a case

Gates 2 and 3 are checked **before the case is resolved**, and every failure
raises the same exception with the same message, so "case does not exist",
"case belongs to another tenant" and "you may not see cases" are one
indistinguishable outcome. Milestone 8 shipped an endpoint that leaked exactly
this difference; a test asserts the two messages are byte-identical.

A refused instantiation emits **no audit event**.

### All-or-nothing

One transaction. A test injects a controlled failure at the third section and
asserts zero dossiers, zero sections, zero provenance rows and zero audit events
survive; a second test injects it at the provenance step, which is the dangerous
one because the dossier already exists by then.

### What is copied, and what is not

Copied: `section_code`, `title`, `description`, `sequence`, `required`, and the
parent hierarchy remapped onto the new rows.

**Not copied**: identifiers, timestamps, the creator, and every runtime field. A
generated section starts at the Milestone 9 defaults — `NOT_STARTED`, readiness
derived, no blockers, no links — because it is a fresh execution record, not a
copy of one. `created_by` is whoever instantiated, not whoever authored the
blueprint.

Readiness is **derived**, not defaulted: one recalculation for the whole tree
after the rows exist. A test asserts a leaf comes out `NOT_READY` while its
parent comes out `PARTIALLY_READY` — two different answers from one call is what
proves a derivation ran rather than a column default surviving.

`submission_dossiers.services.create_section` is deliberately not used: it
recalculates readiness on every call, which would be quadratic. The validation is
not lost — the structure was validated at activation, and the
`submission_dossiers/0004` INSERT trigger re-checks parent tenant, dossier and
cycles on every row regardless of who inserts it.

### Due dates

If a section has `default_due_offset_days` and the dossier has a `target_date`:

```
section due date = dossier target date − offset days
```

**Tenant configuration, not a regulatory timeline.** No offset is invented: with
no target date, or no configured offset, the section simply has no due date.

### Owner defaults

**A blueprint stores no user reference at all** — a test asserts the section
model has no owner column. Nothing picks an owner at instantiation. Choosing
among several users holding a role would be magic ownership selection, so the
owner is left null.

### Duplicate instantiation

**Allowed, deliberately.** Two dossiers from one blueprint on one case is a real
workflow — a resubmission, a parallel track. Guessing duplicate intent from
case + blueprint + date would be inventing product policy. No idempotency key is
required in M10; if one is wanted later it should be explicit.

## 12. Permissions

| Codename | Granted to |
|---|---|
| `.view` | DOER, REVIEWER, VP, TENANT_ADMIN, PLATFORM_SUPPORT |
| `.create` / `.edit` / `.manage_sections` / `.create_version` | DOER, TENANT_ADMIN |
| `.activate` / `.retire` | REVIEWER, VP, TENANT_ADMIN |
| `.instantiate` | DOER, REVIEWER, TENANT_ADMIN |
| `.archive` | VP, TENANT_ADMIN |

Authoring a blueprint is ordinary build work. Publishing one is not: an ACTIVE
version is what every future dossier in the tenant gets stamped from, so
activation sits where "this is finished" already sits for dossiers and cases.

PLATFORM_SUPPORT holds `.view` and no `submission_dossiers.create`, so it can
read a blueprint and cannot instantiate one — the two-gate rule doing its job,
and the test that proves it.

## 13. Tenant isolation

Every object is tenant-scoped and fails closed. Cross-tenant blueprint, version
and section lookups are **404, never 403** — a 403 would confirm the row exists.
Cross-tenant activation, cloning and instantiation are all refused.

Both the view layer (`filter(tenant=...)`) and the service layer
(`_assert_tenant`) enforce it. Mutation-testing the service gate initially turned
only one test red, because the rest were passing on the view's filter alone;
three tests now call services directly with a foreign object so only the service
gate can refuse.

## 14. Safe projection

Blueprint visibility does not grant visibility into instantiated dossiers, and
dossier visibility does not grant access to blueprint management.

`GET /submission-dossiers/{id}/blueprint-provenance/` requires
`submission_dossiers.view` — it is a fact about the dossier. The blueprint's
**name** is added only for a caller who also holds `dossier_blueprints.view`,
because a name is tenant-authored free text. Everyone else gets the provenance
with `restricted: true`, and the UI renders *"Created from a controlled
blueprint, version N"* — the fact retained, the label withheld.

No user email is ever projected; `full_name` only.

## 15. Audit

`dossier_blueprint.{created,updated,archived}`,
`dossier_blueprint_version.{created,activated,retired}`,
`dossier_blueprint_section.{created,updated,reordered,retired}` and
`dossier_blueprint.instantiated` — through the existing `AuditEvent` with a
strict allow-list.

**Never recorded**: blueprint name, section title, description, notes, and the
values of any changed field. `section_code` is present for the same reason it is
in the dossier allow-list — short organisational metadata a reviewer needs to
follow a trail — and `blueprint_name` deliberately is not, because it is free
text a tenant may put a product or an authority into.

## 16. Deletion

Nothing is hard-deleted. Blueprints are **archived**, versions and sections are
**retired**, provenance is permanent.

**Even a never-activated draft section is retired rather than deleted.** The
project already treats creation as audit history everywhere else — a dossier
section, a case link, a blocker — and a row that vanishes leaves its creation
event pointing at nothing. Retirement frees the code and the sequence for reuse,
which is what a user actually wants when they remove a draft row.

Archiving a blueprint frees its name and does **not** touch its versions: an
ACTIVE version stays instantiable, because work already in flight should not be
disrupted by a librarian tidying up.

## 17. API

| Method | Path |
|---|---|
| GET / POST | `/dossier-blueprints/` |
| GET / PATCH | `/dossier-blueprints/{id}/` |
| POST | `/dossier-blueprints/{id}/archive/` |
| GET / POST | `/dossier-blueprints/{id}/versions/` |
| GET | `/dossier-blueprint-versions/{id}/` |
| POST | `/dossier-blueprint-versions/{id}/{activate,retire}/` |
| GET / POST | `/dossier-blueprint-versions/{id}/sections/` |
| POST | `/dossier-blueprint-versions/{id}/instantiate/` |
| PATCH | `/dossier-blueprint-sections/{id}/` |
| POST | `/dossier-blueprint-sections/{id}/{reorder,retire}/` |
| GET | `/submission-dossiers/{id}/blueprint-provenance/` |

Public IDs only; internal PKs are never exposed, and a test asserts the version
detail body contains no `id` key.

Version detail returns a **flat** section array with `parent_public_id`; the
client assembles the tree. `400` for a bad target or corrupt hierarchy; `409` for
a state conflict — a frozen version, a duplicate, a version not yet activatable.

Serializer component names are prefixed `Blueprint*`. Milestone 9 shipped a
`LinkRequestSerializer` whose generated OpenAPI component collided with the
Milestone 8 one, and drf-spectacular collapsed two different request bodies into
a single component. Distinct names here are not cosmetic.

## 18. Frontend

`/dossier-blueprints`, `/dossier-blueprints/[publicId]`, and
`/dossier-blueprints/[publicId]/versions/[versionPublicId]`.

The section tree **reuses** `buildTreeRows`, extracted from the Milestone 9
dossier tree into `@/lib/tree` rather than copied. What is shared is the
flattening; the presentation is separate, because a dossier row shows readiness
and blockers while a blueprint row shows required/optional and draft controls.

Flat DOM with `paddingLeft` for depth, never nested containers. Collapsing
filters the visible list rather than unmounting a subtree.

An ACTIVE or RETIRED version renders **clearly read-only**: every editing control
is absent, and a note explains that changes need a new version and that existing
dossiers are unaffected. Status is never communicated by colour alone — every
badge has a text label and a distinct glyph, nothing is green, and every
foreground/background pair is verified ≥ 4.5:1 by a computed contrast test.

The case picker in the instantiate dialog reuses the existing permission-scoped
case list. **No global case enumeration endpoint was added**: a blueprint
permission must not become a way to enumerate cases.

The case workspace gains *"Create from blueprint"* alongside manual creation.
**Manual creation is not removed** — blueprints are a convenience and a control,
never a requirement.

## 19. Migration classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.

| Migration | Forward | Rollback |
|---|---|---|
| `0001_initial` | **Class A** — five `CreateModel`s, zero `RunPython`/`RunSQL`, no existing table altered | **CLASS C — DATA RESTORE REQUIRED once any governed blueprint or instantiation data exists** |
| `0002_blueprint_db_governance` | **Class A** — seven functions, seven triggers; no table altered, no row read or written | **Class A on its own terms** |

> Reversing `0001` destroys blueprint identity, the entire version history and
> its lifecycle stamps, every version's structural hierarchy and ordering, and —
> worst — **instantiation provenance**, the permanent record of which dossier was
> built from which version. That cannot be reconstructed from the dossier,
> because a dossier is deliberately a snapshot that never reads back.
>
> **Removing protection does not make reversing `0001` safe.** `0002` reverses on
> its own terms and drops only the guards; the relationship is one-way.

Both classifications are repeated **inside the migration files**, where an
operator running `migrate dossier_blueprints zero` will actually see them.

## 20. Testing

**Backend (142)**: blueprint identity, archive and name reuse; permissions per
role; tenant isolation at both the view and service layers; versioning,
cloning and clone integrity; the full section hierarchy including self-parent,
cycle, cross-version, cross-tenant, retired parent and depth; ordering and
reorder; activation validation; instantiation with hierarchy, sequence and
`required` preserved and runtime state reset; three-gate authorization with
indistinguishability and no-audit-on-refusal; all-or-nothing transactionality
with injected failures; provenance and its immutability through ORM and raw SQL;
DB governance across versions, sections and provenance; `information_schema`
column coverage; real-thread concurrency; and query-cost invariance.

**Frontend**: 26 unit, 13 new accessibility checks, 19 Playwright.

### Query cost

Measured, not assumed. Invariance, not an absolute — an absolute encodes today's
fixed overhead and breaks on unrelated changes.

| Endpoint | Sizes | Result |
|---|---|---|
| Blueprint list | 1 / 20 / 100 | flat |
| Version detail | 1 / 20 / 100 / 500 sections | flat |
| Instantiation | 10 → 20 sections | sub-linear ratio, not quadratic |

### Mutation testing

Every guard is mutation-tested, because a test that passes without the guard
proves nothing:

| Mutation | Tests turned red |
|---|---|
| Active/retired section freeze removed (`0002`) | 3 |
| Service tenant gate neutered | 4 |
| Two-gate instantiation authorization removed | 3 |
| `@transaction.atomic` removed from instantiation | 2 |
| Version-number race guard (`select_for_update`) removed | 1 |
| Provenance freeze trigger removed | 4 |

Every mutated file was restored and verified byte-identical afterwards, md5
compared against a pre-mutation capture.

The tenant-gate mutation is worth noting: it first turned only **one** test red,
because the rest were passing on the view's tenant filter rather than the service
gate. Three targeted tests were added before re-running.

## 21. Regulatory boundaries

No production regulatory content. No CTD, CEP, DMF or ANDA structure built in.
No country or agency requirements. No Item 1 resolution. No change to the 0/20
governance count. No policy decision. No S-1/S-2 closure. No Part 11, GxP,
validated-process or regulatory-approval claim.

**ACTIVE is internal availability. Nothing here is an agency decision**, and the
UI says so on the library page, the blueprint page and every version page.
