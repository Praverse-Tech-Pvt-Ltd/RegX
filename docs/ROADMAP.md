# REGX Roadmap / Handover

Tracks milestone status on the `regx-main` line. This branch is a clean-room implementation and shares no code with the legacy booking demo on `main` — see [LEGACY_BOUNDARY.md](LEGACY_BOUNDARY.md).

## Milestone 6 — Generic Regulatory Workflow Engine

**Status: COMPLETE**
**Merge SHA: `70267448506d30cef30c28b0536f78cc5c1f47bb`** (PR #33)

Turned the `workflows` scaffold — one model, four states, no views, no urls, no
tests, unrouted — into a working engine. A centrally enforced transition table
(`DRAFT → SUBMITTED → IN_REVIEW → APPROVED | REJECTED`, plus `CANCELLED` and
`REJECTED → DRAFT`), a service layer holding a row lock so two conflicting
transitions resolve deterministically, append-only `WorkflowTransition` history
protected by a PostgreSQL trigger, tenant isolation, allow-listed audit and a
generic UI. See [WORKFLOW_ENGINE.md](WORKFLOW_ENGINE.md).

`workflows/0002` is **Class C for rollback** once transition data exists —
reversing it destroys append-only history. `workflows/0003` (the trigger) is
Class A on its own terms and does not make reversing `0002` safe.

## Milestone 15 — Reliability, Performance & Operational Hardening

**Status: IN REVIEW — STACKED ON MILESTONE 14**

Branched from `e7bcc4c599d3b8f42e700a392d1542580802ae80` and **must not merge
before Milestone 14, which must not merge before 13, 12, 11, 10 and 9 in that
order**. GitHub Actions remains blocked at organisation level by a
billing/spending limit; that is an infrastructure condition, not a code
result, and no workflow file was modified to work around it.

Platform hardening, not feature work. No new endpoints, no dossier semantics,
no regulatory content. Every change began with a measurement, and the paths
that measured clean were left alone and recorded as such rather than
"optimised" on suspicion.

Three defects, each found by measuring rather than reading:

The attention queue's scan cap **never reached SQL** — `add()` received an
already-evaluated list, so the database returned every candidate row and Python
built a dict for each one before the cap applied: 1200 dicts to display 500.
The query count was flat at 9 throughout, so a query-count test called the path
healthy at every size. Async work was **dispatched before commit** at three
sites a caller can wrap in a transaction, so a worker could claim a row that
did not exist yet, log "not found", and silently do nothing. And `readiness`
both leaked dependency internals from an `AllowAny` endpoint and **could not
fail**: Django's Redis backend sets no socket timeout, so a Redis that stopped
answering hung the probe instead of returning 503, starving the web process
through its own health checks.

A fourth `on_commit` was added and then **removed**: the write above it is a
bare `save()` outside any transaction, so there was nothing to defer to, and no
measurement justified keeping it.

**No migrations.** Rollback of this milestone is a plain code revert with no
schema or data consequence — the only Class A/B/C question it raises is none.

See [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md),
[LOCK_ORDER.md](LOCK_ORDER.md), [TASK_RELIABILITY.md](TASK_RELIABILITY.md) and
[CAPACITY_AND_LIMITS.md](CAPACITY_AND_LIMITS.md).

**Not claimed:** no caching was added, because every read path here is
authorization-sensitive; no new indexes, because no measured query plan
justified one; no connection pooler; no automatic stale-work recovery, which
would replace an honest unknown with a confident falsehood. `LOCK_ORDER.md`
marks two orderings as verified by code inspection rather than claiming a
deadlock test that was not built. Nothing here is a validated-system, Part 11,
or agency-readiness claim.

## Milestone 14 — Controlled External Integration / Connector Framework

**Status: IN REVIEW — STACKED ON MILESTONE 13**

Branched from `9ebfbbae572332f2de78b7588c2bcaded7b9a0af` and **must not merge
before Milestone 13, which must not merge before 12, 11, 10 and 9 in that
order**. GitHub Actions remains blocked at organisation level by a
billing/spending limit; that is an infrastructure condition, not a code
result, and no workflow file was modified to work around it.

A reusable framework for moving content between RegX and systems nobody in
RegX controls, with two bounded operations on top of it: import a document,
and transfer an exact frozen package. **`GENERIC_HTTPS` only** — SFTP was
scoped and dropped rather than shipped with `AutoAddPolicy`, and vendor names
are absent rather than stubbed.

The security case is the milestone. A connector lets a tenant user cause the
server to make an outbound request, so every destination is resolved and every
answer classified before a socket opens, the checked address is *pinned* for
the connection while TLS still validates the hostname, redirects are refused
outright, and a mixed DNS answer refuses the whole destination rather than
picking the public one. Secrets are stored as the *name* of an environment
variable; the model has no column that could hold a value.

`external_integrations/0001` is **Class C for rollback** once execution history
exists — reversing it destroys the record that content left this deployment.
`0002` (8 functions, 9 triggers) is Class A on its own terms and does not make
reversing `0001` safe. See [EXTERNAL_INTEGRATIONS.md](EXTERNAL_INTEGRATIONS.md).

**Not claimed:** no agency gateway, no submission, no exactly-once delivery
unless the remote endpoint honours the idempotency key it is offered, no proof
a remote system stored anything, and not a validated production interface.

## Milestone 13 — Controlled Submission Package Assembly & Export Manifest

**Status: IN REVIEW — STACKED ON MILESTONE 12**

Branched from `12ea1552e4f88b242c8a6c62b5b76d9f862a7b10` and **must not merge
before Milestone 12, which must not merge before 11, 10 and 9 in that order**.
GitHub Actions is blocked at organisation level by a billing/spending limit;
that is an infrastructure condition, not a code result, and no workflow file was
modified to work around it.

A package answers one question permanently: *which exact bytes were assembled,
and when*. Every entry binds to a `DocumentVersion`, never to a `Document`, so
uploading a new version of a cited document changes nothing about any package
that already cites an earlier one. The guarantee is a foreign key rather than a
rule somebody has to remember — the same pattern `workflows.WorkflowEvidence`
established for citing one exact version, extended to a set of them with a
manifest over the whole.

**FROZEN is an internal RegX state.** It means the manifest can no longer
change. It is not QA approval, regulatory approval, agency acceptance or a claim
that anything is ready to file, and there is deliberately no APPROVED state. A
manifest that could be reopened would not be a manifest, so there is no unfreeze:
changing a frozen package means cloning it into a new draft, which leaves the
original exactly as it was.

Freezing is one transaction that revalidates every cited version — including
whether its file is still in storage — before it computes the canonical manifest,
because after freeze the record is permanent and that is the last moment the
claim can be checked. The manifest is deterministic by construction: sorted keys,
no whitespace, entries ordered by sequence then public id, and **no timestamp
inside the hashed bytes**, so the same composition hashes the same way twice.

Export streams the cited versions into an internal ZIP, hashing each file as it
goes and comparing against the manifest, so an archive whose manifest is a lie
about its own contents fails rather than ships. It is all or nothing: a caller
who cannot retrieve every document is refused the whole archive, because one
silently missing file looks complete to whoever receives it. Logical paths are
tenant-defined and normalised against traversal, Windows device names, Unicode
spelling and case collision. See [SUBMISSION_PACKAGES.md](SUBMISSION_PACKAGES.md).

**No agency format ships.** No eCTD, sequence generation, XML backbone, regional
module, NeeS, ESG or gateway transmission, FDA or EMA validation, completeness
determination, electronic signature, or Part 11 / GxP claim. Synthetic codes
throughout, and the ZIP is an internal container.

`submission_packages/0001` is **Class C for rollback** once any package data
exists: reversing it destroys every frozen manifest and checksum, which is not
derivable from anything else precisely because it does not change when the
documents do. `0002` (seven functions, seven triggers) is Class A on its own
terms and does not make reversing `0001` safe.

## Milestone 12 — Submission Operations & Internal Readiness Dashboard

**Status: IN REVIEW — STACKED ON MILESTONE 11**

Branched from `1cd885a4e44baa1861866ebfc09aa2839c2a0015` and **must not merge
before Milestone 11, which must not merge before Milestone 10, which must not
merge before Milestone 9**. GitHub Actions is blocked at organisation level by a
billing/spending limit; that is an infrastructure condition, not a code result,
and no workflow file was modified to work around it.

Nine milestones of governed domains, and no single place to see the work. This
adds one — and adds nothing else. `submission_operations` is a read model: no
model, no migration, no stored state, no copied readiness, no cached counts.
Every number is counted at request time from the table that owns it, using that
module's own status fields. Delete the app and every fact it reports still
exists where it always was.

**Zero and null are different answers.** `0` means there are none; `null` means
the caller is not entitled to know. A dashboard rendering `0` for a module the
caller cannot see is not being cautious, it is lying — and lying in a way that is
indistinguishable from the truth until the tenant actually has twelve of the
thing. A frozen `Visibility` type makes this structural rather than a convention
somebody has to remember.

**The dashboard permission is a door, not a key.** `submission_operations.view`
grants the right to ask and nothing else; cases, dossiers, documents, workflows,
checklists, blueprints and upgrades each stay behind their own view permission,
checked independently on every request through that module's own helper. A
cross-module dashboard under one permission would be a permission-laundering
machine. A restricted module contributes no count, no row and no note about how
many rows were withheld — a count of what was hidden is itself the disclosure.

Readiness is read from Milestone 9, never recomputed, and every label says
"internally". Retired sections, optional sections and terminal dossiers are all
excluded from outstanding work. The attention queue emits enumerated reason
codes rather than generated prose, ranked blocked → overdue → rejected → due
soon → not started → informational, with a total order so pagination cannot drop
rows. "Due soon" is a seven-day **display** window with no regulatory meaning.

Aggregation is per page, not per row: query counts are flat from 1 to 100 cases
on every surface. Readiness filtering narrows the queryset in SQL **before**
pagination, so `count` describes the filtered set and a match on page four is not
invisible on page one. The activity feed carries what happened to which thing and
when, never who: `Visibility` has no identity gate, so emitting an actor's email
would turn module permission into permission to learn who acted. See
[SUBMISSION_OPERATIONS_DASHBOARD.md](SUBMISSION_OPERATIONS_DASHBOARD.md).

**No regulatory judgement of any kind.** No CTD, eCTD, CEP, DMF, ANDA, USFDA or
EMA structure or rules; no completeness engine; no submission validation; no AI
conclusions. **A green dashboard does not mean a submission is acceptable to
anyone**, and the screen says so in standing copy.

No new table and no migration, so there is nothing here to classify for
rollback — the app adds one permission codename, registered through the existing
`post_migrate` discovery hook.

## Milestone 11 — Blueprint Change Impact & Controlled Dossier Upgrade Planning

**Status: IN REVIEW — STACKED ON MILESTONE 10**

Branched from `a6c3e354ca79dd970db387444191d43d31d5b1ae` and **must not merge
before Milestone 10, which must not merge before Milestone 9**. GitHub Actions
is blocked at organisation level by a billing/spending limit; that is an
infrastructure condition, not a code result, and no workflow file was modified
to work around it.

Milestone 10 made a dossier an independent snapshot, which is right and also
leaves a gap: there was no way to move one onto a newer outline at all. This
closes it — explicitly, reviewably, transactionally. **A blueprint change is
still not a dossier change.** Publishing version 2 changes nothing. An upgrade
happens only when a person generates a plan, reviews it item by item, and
applies it; generating is not applying, accepting is not applying, and READY is
an internal review state with deliberately no APPROVED anywhere in the chain.

`_clone_sections` records no v1→v2 lineage, so matching is derived rather than
stored, and each hop is backed by a constraint: a dossier section reaches its
source through the stored `BlueprintSectionOrigin` row, and the source reaches
the target through `section_code`, which `unique_active_blueprint_section_code`
makes unique per version. Where that chain does not resolve it **refuses to
guess**: a hand-added section is left alone if nothing collides, and reported as
`CONFLICT` for manual review if something does. A changed code is a retirement
plus an addition, not an inferred rename.

Runtime work is protected rather than overwritten. A proposed retirement is
BLOCKED if the dossier section has children, open blockers, resource links or
recorded progress — and those facts are re-checked at apply time, not only at
generation, because runtime changes deliberately do not stale a plan and the
window between review and apply is the dangerous one. A manually set due date is
never overwritten, checked the same way. Plans carry a structural fingerprint and
apply fails closed if the dossier moved underneath them. Every section write
goes through `submission_dossiers.services`, so the Milestone 9 sanctioned
window and its triggers apply unchanged; this module writes no section row
itself.

Provenance is append-only across versions: an upgrade adds a
`DossierUpgradeApplication` and never rewrites the instantiation record that
says how the dossier was originally created. `UpgradeSectionOrigin` exists
because M10's origin INSERT guard correctly refuses a section from a later
version.

Apply re-proves the version and provenance facts under lock rather than trusting
them from generation time, because the structural fingerprint cannot see either:
retiring a blueprint version and advancing the provenance chain both move zero
dossier sections. The target must still be ACTIVE and still belong to this
tenant and blueprint, and the dossier's derived provenance must still be the
plan's source version. `0003` puts a floor under the chain itself — a unique
index that holds under concurrency, plus a trigger that refuses a link starting
nowhere — with each half documented for what it does and does not enforce. This
is the first operation to write across both governed hierarchies, so its lock
order follows the one each already uses internally: dossier, plan, version rows
by version_number, section. See [DOSSIER_UPGRADES.md](DOSSIER_UPGRADES.md).

**No regulatory judgement of any kind.** No CTD, CEP, DMF, ANDA or agency rules;
no regulatory impact assessment; no submission validation. Every test uses
generic synthetic codes. Applying a plan changes only what a person accepted.

`dossier_upgrades/0001` is **Class C for rollback** once any governed upgrade
data exists: reversing it destroys plans, the review decisions recorded on their
items, applied-upgrade history and upgrade section origins — none of it
reconstructible, since a dossier deliberately never reads back to its blueprint.
`0002` (six functions, seven triggers) and `0003` (one unique constraint, one
function, one trigger) are Class A on their own terms and do not make reversing
`0001` safe.

## Milestone 10 — Dossier Blueprint / Template Library

**Status: IN REVIEW — STACKED ON MILESTONE 9**

Branched from `57c0a1544aa295e582375d824c950f3193bcb09c` and **must not merge
before Milestone 9**. GitHub Actions is blocked at organisation level by a
billing/spending limit; that is an infrastructure condition, not a code result,
and no workflow file was modified to work around it.

Milestone 9 lets a user build a dossier outline by hand. This lets a tenant
capture that outline once, version it, and stamp it into as many cases as they
like. **Blueprints define structure; dossiers own execution.** Instantiating a
version produces ordinary governed `submission_dossiers` records that never read
back to the blueprint, so publishing version 2 cannot rewrite a dossier built
from version 1.

`templates_registry` already provides a controlled-template system, and it is
composed with rather than reused. The decisive reason is semantic: its lifecycle
has an APPROVED state backed by a real approval trail tied to the regulatory
content gate, and a tenant's internal dossier outline must not borrow that word.
Its *patterns* are reused verbatim — version-number uniqueness, the partial
unique index on the active version, and the locked sibling set during
activation. See [DOSSIER_BLUEPRINTS.md](DOSSIER_BLUEPRINTS.md) section 4.

A version is DRAFT, ACTIVE or RETIRED, with deliberately no APPROVED. Structure
is editable only while DRAFT and frozen forever afterwards, enforced by
`dossier_blueprints/0002` triggers that read the version's own status — no
sanctioned window is needed here, because unlike a dossier section there is only
one thing a published version may do. Instantiation is gated three times,
independently: blueprint instantiate, dossier create, and case view, with the
target-domain gates checked before the case is resolved so an unauthorised
caller and a missing case are indistinguishable. It is all-or-nothing in one
transaction, and provenance is immutable at the database.

**No production regulatory structure ships.** No CTD modules, no CEP, DMF or
ANDA structures, no country or agency requirements; every test uses generic
synthetic codes. **ACTIVE means available for internal RegX dossier
instantiation** — not a regulatory, QA or agency approval, not a validated
status.

Template upgrades are an explicit non-goal: M10 does not apply a later version
to an existing dossier, merge changes, or diff sections. Milestone 11 adds that
as a separate, explicitly reviewed operation — and does not weaken this
guarantee: publishing a version still changes no dossier by itself.

`dossier_blueprints/0001` is **Class C for rollback** once any governed blueprint
or instantiation data exists: reversing it destroys blueprint identity, version
history and — irreplaceably — the record of which dossier came from which
version, which cannot be reconstructed from a dossier that is deliberately a
snapshot. `0002` (the triggers) is Class A on its own terms and does not make
reversing `0001` safe.

## Milestone 9 — Submission Dossier / Section Readiness Workspace

**Status: IN REVIEW**

Milestone 8 gave a case a folder; this gives it an outline. `SubmissionDossier`
holds an ordered, arbitrarily nested set of `DossierSection`s, each with an
owner, a due date, structured blockers and a **derived** readiness state. It owns
structure only: no documents, no workflow items, no checklist executions, no
second evidence table, and no approval engine.

`readiness` is computed by one authoritative function and is absent from every
write serializer — a caller states `status`, the system states readiness. The
calculation deliberately ignores the caller so two users never see contradictory
states for the same section; the privacy obligation is discharged at the
*explanation* layer, where reasons are coarse enumerated codes that never name a
resource the caller may not see. An empty dossier is `NOT_READY`, not vacuously
`READY`.

Linking requires two independent gates — `submission_dossiers.manage_links` and
the target module's own view permission, resolved through that module's own
helper — with the module gate checked *before* the target is resolved, so
absent / cross-tenant / unauthorized are one indistinguishable outcome. This was
a MAJOR review finding against Milestone 8 and is built in here from the start.
Module counts are `null`, never `0`, for callers who cannot see the module.

Section links are governed at the database level from the first migration:
`submission_dossiers/0002` installs PostgreSQL triggers on all three link tables
because `link.save()` bypasses the manager.

Independent review found two further gaps, both closed in
`submission_dossiers/0003`. Retirement was the intended removal path for a
section but was enforced only in services, and `PROTECT` covered only a section
that already held a governed relationship — a bare section could still be
hard-deleted by ORM or SQL. And blocker history had a CHECK constraint and
nothing else, so a resolved blocker could be reopened, re-resolved, or have its
content and provenance rewritten with no audit row, which matters because
blockers gate readiness directly. Sections now refuse deletion at model,
queryset and database level in every state, and a blocker makes exactly one
transition, OPEN to RESOLVED, and is immutable and undeletable thereafter.

A third pass closed the section UPDATE bypass that closing DELETE had left
behind. `update()`, `bulk_update()` and `save()` had stayed open so reorder and
readiness could work, which also let any ORM caller rewrite tenant, dossier,
parent, readiness or the retirement stamps directly. `submission_dossiers/0004`
replaces that with a **sanctioned window**: the service layer declares which of
four operations is running, in a transaction-scoped PostgreSQL parameter, and the
trigger holds that statement to exactly the columns the operation may touch.
Identity and provenance are frozen under every window and none; a retired section
is frozen entirely; and the database independently re-checks self-parent,
cross-dossier, cross-tenant, retired-parent and cycle. Declaring an operation
grants nothing on its own.

**No CEP, DMF, ANDA or eCTD structure is built in.** `section_code` is display
metadata; hierarchy comes from `parent`, never from parsing the string. See
[SUBMISSION_DOSSIERS.md](SUBMISSION_DOSSIERS.md).

**READY means internally ready against configured RegX criteria. COMPLETED means
internal work stopped. Neither is an agency decision, a filing acceptance, or a
regulatory approval.**

`submission_dossiers/0001` is **Class C for rollback** once any dossier exists:
reversing it destroys the outline, the section hierarchy and ordering, the link
history including retired links, and the whole blocker history with its
resolution provenance. `0002`, `0003` and `0004` (the triggers) are Class A on
their own terms — each drops exactly what it created and touches no row — and
none of them makes reversing `0001` safe. Removing protection is not the same as
making destruction safe.

## Milestone 8 — Regulatory Case / Submission Workspace

**Status: COMPLETE**
**Merge SHA: `8c4d19d82191be7baa447bfa9d026f7dcb84f25c`** (PR #36)

The first object that says *these things belong to the same submission*.
`RegulatoryCase` is a governed folder that composes workflow items, documents and
checklist executions; it owns no regulatory content and duplicates no engine.
Evidence stays owned by `workflows.WorkflowEvidence` and is surfaced through the
case's linked workflows rather than stored again.

Case permission grants nothing about linked resources: a caller sees document,
workflow or checklist detail only where they independently hold that module's own
view permission. See [REGULATORY_CASES.md](REGULATORY_CASES.md).

Case numbers are tenant-local and deliberately internal — RegX assigns no
agency-meaningful reference. **A case status of COMPLETED is not a regulatory
approval.**

`regulatory_cases/0001` is **Class C for rollback** once any case exists:
reversing it destroys the record of what each case cited, and the per-tenant
number sequence.

## Milestone 7 — Workflow Evidence and Document Linking

**Status: IN REVIEW**

Connects workflow items to the existing document platform. Evidence references
an exact `DocumentVersion` — never a `Document` — so uploading a newer version
cannot change what historical evidence means. No file bytes are duplicated: the
document platform stays the sole owner of storage, checksum, scan status and
retrieval. Workflow permission and document permission are enforced as separate
gates. See [WORKFLOW_EVIDENCE.md](WORKFLOW_EVIDENCE.md).

## Milestone 5A — Production Regulatory Checklist Content Readiness

**Status: ENGINEERING PREREQUISITES COMPLETE (5A-P1) — BLOCKED ON REGULATORY APPROVAL**
**Production regulatory checklist content: 0 of 20 approved — gate OPEN.**

### 5A-P1 — Content engine prerequisites: COMPLETE

Discovery found three capability limits that made it unsafe to ask a regulatory
authority to approve content. 5A-P1 closed them, under approved project-owner
decisions `5A-DEC-001` through `5A-DEC-007`:

- **FDA-derived resolvers** now exist as a governed allow-list with source
  provenance, explicit failure statuses and no fabricated defaults;
- **applicability rules are evaluated at runtime**, deterministically and
  fail-closed, with the APP-009 ownership boundary preserved;
- **select options carry approved labels**, so a reviewer never sees a raw code
  and no label is derived in the client;
- **jurisdiction** is structured governed metadata on `ChecklistVersion`, inside
  the checksum-covered export;
- **platform-master ownership** was verified rather than rebuilt — the existing
  controls already enforce `5A-DEC-006`;
- **no per-question export exclusion** was built: `5A-DEC-003` chose full
  governed inclusion for the first production release.

**Engineering prerequisites are not regulatory approvals.** The count stays at
0 of 20 and moves only when a named regulatory authority signs. One new open
question (**OQ-8**, which `AssessmentSnapshot` governs execution-level `iid.*`
values) is deliberately left to the owner; until it is answered, affected rules
evaluate to `review_required` and affected bindings record `source_unavailable`
rather than guessing.

See [MILESTONE_5A_P1_ENGINEERING_EVIDENCE.md](MILESTONE_5A_P1_ENGINEERING_EVIDENCE.md).

5A discovery converted the production-content gate from an unspecific "0/20" into a
controlled approval package a qualified RA/QA authority can review and sign. It
defines the content schema, per-item ownership, evidence requirements,
engine traceability, the approval workflow, sign-off criteria and the engineering
handoff. It contains **no production regulatory content** — no question text, no
template selection, no guidance interpretation, and no approval or signature.

5A is **COMPLETE only when all 20 items are resolved and item 20 carries a valid
formal sign-off** by the identified regulatory authority. Until then it is
BLOCKED ON REGULATORY APPROVAL, and engineering implementation of approved
content does not begin.

Discovery surfaced three capability limits that constrain what can meaningfully
be approved today, each traced to merged code and each raised as an open
question rather than resolved by engineering: applicability rules are validated
and stored but never evaluated at runtime; FDA-derived default bindings are
inert because the resolver layer was deliberately held out of 4D-3 scope; and
there is no per-question export inclusion/exclusion mechanism.

5A is **not** FDA data ingestion, client formulation onboarding, template
migration, production infrastructure, 21 CFR Part 11 validation, or go-live
approval. No Part 11 compliance is claimed, and no Part 11 validated electronic
signature system exists in this repository.

See [MILESTONE_5A_DISCOVERY.md](MILESTONE_5A_DISCOVERY.md),
[MILESTONE_5A_REGULATORY_CONTENT_PACKAGE_TEMPLATE.md](MILESTONE_5A_REGULATORY_CONTENT_PACKAGE_TEMPLATE.md),
and [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md).

---

## Milestone 4A–4C — FDA Data Governance, Formulation Foundation, and IID Assessment

**Milestone 4A–4C technical foundation: COMPLETE**
**Production FDA data ingestion: NOT STARTED**
**Production client formulation use: NOT STARTED**
**Engineering Milestone 4D (regulatory checklist execution): COMPLETE** — 4D-1, 4D-2, 4D-3 and 4D-4 are complete on `regx-main` through PR #18 (merge SHA `6ed2a4efd9aef71d500776750fc73c100de55586`).
**Production regulatory checklist content: 0 of 20 approved — separate human regulatory-authorship gate, still OPEN.**

4D-4 delivered APP-009 applicability ownership (PR #12), controlled exports with canonical checksum and normalized provenance (PR #15), governed overrides/deviations (PR #16), governed `approval_metadata`, tenant-scoped capabilities and override UI (PR #17), and strict reviewer-conclusion concurrency plus the dedicated per-response reviewer-conclusion frontend workflow (PR #18). Override clearing remains APPROVED-DEFERRED; the known `ControlledExportError` mapping issue remains MINOR-DEFERRED. Neither is a Critical/Major blocker to the defined engineering milestone.

See [MILESTONE_4D_CLOSEOUT_STATUS.md](MILESTONE_4D_CLOSEOUT_STATUS.md), [MILESTONE_4D_4_DISCOVERY.md](MILESTONE_4D_4_DISCOVERY.md), [MILESTONE_4D_4_REVIEWER_CONCLUSION_EVIDENCE.md](MILESTONE_4D_4_REVIEWER_CONCLUSION_EVIDENCE.md), and [MILESTONE_4D_4_CONTENT_APPROVAL.md](MILESTONE_4D_4_CONTENT_APPROVAL.md) for the engineering closeout, decision register/evidence, and the still-open production-content gate.

Three apps: `fda_data` (platform-level FDA source-data governance), `formulations` (tenant-scoped product/formulation records), and `iid_assessment` (IID precedent matching, unit conversion, calculation, and decision engine). See [FDA_DATA_GOVERNANCE.md](FDA_DATA_GOVERNANCE.md), [FDA_IID_INGESTION.md](FDA_IID_INGESTION.md), [FDA_TERMINOLOGY_MAPPING.md](FDA_TERMINOLOGY_MAPPING.md), [FORMULATION_DATA_MODEL.md](FORMULATION_DATA_MODEL.md), [IID_MATCHING_ENGINE.md](IID_MATCHING_ENGINE.md), [IID_CALCULATION_RULES.md](IID_CALCULATION_RULES.md), and [IID_DECISION_STATUSES.md](IID_DECISION_STATUSES.md) for architecture.

### Scope delivered

- **FDA source-data governance:** `FDADataSourceRelease` lifecycle (registered → validated → under_review → approved → active → superseded/rejected), segregation of duties (importer cannot approve their own import), no auto-activation.
- **Orange Book support:** product/patent/exclusivity import and search.
- **FDA IID support:** Inactive Ingredient Database import, `IIDIngredient`/`IIDPrecedentRecord` models.
- **Terminology mapping governance:** `RouteMapping`, `DosageFormMapping`, `UnitMapping`, and `SubstanceSynonymMapping` (raw ingredient name → canonical ingredient/UNII/CAS identity) — a single authoritative transition service (`fda_data/mapping_transitions.py`) enforces legal lifecycle transitions across all four types; nothing is ever auto-approved.
- **Production substance-mapping proposal API:** `POST /api/regx/v1/fda-data/mappings/substances/proposals/` — the shipped entry point for creating a `PROPOSED` mapping; no Django shell/ORM dependency remains to start this workflow.
- **Reviewer/approver provenance:** `created_by`/`submitted_by`/`reviewer`/`approved_by`/`rejected_by`/`returned_by` are each recorded distinctly, never overwritten by a later action.
- **Affected-record API and stale-release matching protection:** non-approved mappings scoped to a superseded/unrelated release can no longer block a legitimate fallback match against the active release.
- **Formulation foundation:** `ProductDevelopmentRecord`, `FormulationVersion`, `FormulationComponent`, `DosingRegimen` — tenant-scoped, explicit (never automatic) reference-product selection, Decimal-only quantities.
- **IID matching, unit conversion, and calculation:** deterministic precedent matching, mass/volume/count unit conversion (density-gated), six calculation formulas, and a closed-vocabulary decision engine that structurally forbids constructing a "SAFE"/"FDA APPROVED"/automatic-approval status. `AssessmentSnapshot` freezes a point-in-time result, including which mapping version confirmed identity.

### Record

- **PR:** [#5](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/5)
- **Merge SHA:** `d9d0d13519a154bb2c0558a0aed6bbac313aa587` (two-parent merge commit into `regx-main`, not squashed)
- **Release tag:** [`regx-fda-iid-foundation-v0.4.0`](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/releases/tag/regx-fda-iid-foundation-v0.4.0), on the merge commit
- **Legacy `main`:** unchanged throughout (`8ed8cf4b79262c1f3f261e872dc387783818e9ed`)

### Human review

- **First focused review gate:** identified 1 Critical (mapping lifecycle transitions not validated against current status — e.g. a still-`PROPOSED` mapping could be approved directly) and 1 Major (no shipped API or import path could create a `PROPOSED` `SubstanceSynonymMapping` — only Django shell/ORM insertion could), plus 2 Minor findings (`reviewer` overwritten on every mapping action; a stale non-approved mapping from a superseded release could block a legitimate fallback match). Result: FAIL.
- **Remediation (HR-01–HR-04):** a single authoritative transition table now gates every mapping-action view inside a `select_for_update()` transaction, returning a structured 400 with no mutation and no audit event on an illegal transition; a new production proposal endpoint always creates `PROPOSED` and is gated by a dedicated permission; `rejected_by`/`rejected_at`/`returned_by`/`returned_at` fields were added so each lifecycle action records only its own actor; `_unapproved_state_for()` now scopes blocking mappings to currently-usable releases. See [HUMAN_REVIEW_PR5_REMEDIATION.md](HUMAN_REVIEW_PR5_REMEDIATION.md) for the full traceability table.
- **Second focused review gate:** PASS — all four findings independently confirmed closed by direct code inspection (not by trusting CI or the remediation doc's own claims); no new Critical or Major finding introduced. One non-blocking observation: the frontend still renders approve/reject buttons regardless of current status, relying on the server-side transition table (authoritative) to reject illegal actions with 400.

### CI (post-merge, on `regx-main` at the merge commit)

- [Backend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30242694946) — success (533 passed, 93.29% coverage)
- [Frontend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30242694936) — success (99 unit/accessibility, 63 Playwright)
- [Docker Integration](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30242694991) — success, including the production substance-proposal path, a blocked direct-approval-of-`PROPOSED` check, and the full approved-synonym IID assessment flow

### Test counts

- **Backend:** 533 tests passed (141 in `fda_data`, 21 in `formulations`, 103 in `iid_assessment`), 93.29% coverage (gate 55%). Ruff lint/format clean, import-linter 6/6 contracts kept, OpenAPI generates, AIDatabase guard clean, 483/warning-letter guard clean.
- **Frontend unit/accessibility:** 99 tests (Vitest + React Testing Library + jest-axe).
- **Frontend Playwright:** 63 tests, including the full substance-mapping proposal → submit-review → approve lifecycle.

### Known limitations

1. Only synthetic, non-confidential fixtures are included — no real FDA source file (Orange Book, IID) has been imported.
2. No real client formulation/product data is included; all formulation fixtures are synthetic.
3. Engineering Milestone 4D is complete through PR #18, including APP-009 applicability ownership, controlled exports/provenance, governed overrides, approval metadata, tenant-scoped capabilities, and the per-response reviewer-conclusion workflow. The production regulatory-content gate remains open at 0 of 20 approved items and is tracked separately in [MILESTONE_4D_4_CONTENT_APPROVAL.md](MILESTONE_4D_4_CONTENT_APPROVAL.md). Override clearing is APPROVED-DEFERRED and `ControlledExportError` remains MINOR-DEFERRED; see [MILESTONE_4D_CLOSEOUT_STATUS.md](MILESTONE_4D_CLOSEOUT_STATUS.md).
4. Only one production substance-mapping creation path exists (the manual proposal API); an import-generated candidate path is a natural follow-on, not a blocking gap.
5. No 21 CFR Part 11 compliance is claimed by this milestone.
6. Human regulatory review remains mandatory at every mapping and assessment decision point — an IID precedent match is a comparison reference only, never an automatic safety or regulatory-approval determination.
7. Storage-level authorization for raw FDA source files is inherited from the existing `documents.storage` layer and only re-verified here at the API-response-shape level (carried over from Milestone 2).

---

## Milestone 3 — Regulatory Template Migration and Governance Foundation

**Milestone 3 technical framework: COMPLETE**
**Production regulatory-template migration: NOT STARTED**

Canonical `templates_registry` domain, staged import pipeline, non-destructive
normalization, deterministic duplicate-candidate reconciliation, a full
approval lifecycle (draft → review → approve/reject/return → activate →
supersede/retire), tenant isolation, segregation of duties, JSON/CSV
reconciliation exports, and governance APIs/frontend. This is the migration
and governance **framework** only — no real client regulatory template
content has been imported, reviewed, approved, or activated. See
[TEMPLATE_GOVERNANCE.md](TEMPLATE_GOVERNANCE.md) for architecture and the
other `TEMPLATE_*.md` docs for the import pipeline, normalization, duplicate
reconciliation, approval lifecycle, reconciliation reports, and test
strategy.

### Record

- **PR:** [#3](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/3)
- **Source SHA:** `27d38cb6e6d1c4bb893c943ce036d37b9e91f352`
- **Merge SHA:** `37a58ce9149d47e55823ef15a40f53a19f64f08e` (two-parent merge commit into `regx-main`, not squashed)
- **Release tag:** [`regx-template-governance-v0.3.0`](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/releases/tag/regx-template-governance-v0.3.0), on the merge commit
- **Legacy `main`:** unchanged throughout (`8ed8cf4b79262c1f3f261e872dc387783818e9ed`)

### Human review

- **First review gate:** identified 1 Critical (cross-tenant duplicate-candidate mutation in `MigrationBatchReviewView`) and 1 Major (CSV/formula-injection in reconciliation exports) finding, plus 2 Minor findings (concurrent version-number allocation race, incomplete audit metadata). Result: FAIL.
- **Remediation:** all four findings fixed with 25 new regression tests. Cross-tenant candidate resolution is now scoped through a shared `duplicate_candidates_for_source_package()` helper with atomic all-or-nothing bulk review; CSV exports are neutralized against formula injection at render time (raw DB values untouched); version-number allocation is now lock-serialized with a bounded retry; duplicate-resolution and reconciliation-export audit events now carry full decision detail.
- **Second review gate:** PASS — no Critical or Major findings remained. One non-blocking documentation gap noted (CSV export-safety and `RECONCILIATION_EXPORTED` event not yet documented).
- **Documentation closure:** PASS — `TEMPLATE_RECONCILIATION_REPORT.md` and `TEMPLATE_DUPLICATE_RECONCILIATION.md` updated to close the gap.

### CI (post-merge, on `regx-main` at the merge commit)

- [Backend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30067420018) — success
- [Frontend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30067420025) — success
- [Docker Integration](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/30067420031) — success

### Test counts

- **Backend:** 268 tests passed (99 in `templates_registry`, including tenant-isolation, CSV-security, concurrency, audit, and 10 planted-failure scenarios), 92.01% coverage (gate 55%). Ruff lint/format clean, import-linter 4/4 contracts kept, OpenAPI generates and validates, AIDatabase guard clean, 483/warning-letter guard clean.
- **Frontend unit/accessibility:** 32 tests (Vitest + React Testing Library + jest-axe), including 10 accessibility checks.
- **Frontend Playwright:** 34 tests, including the migration-governance flow suite (template lifecycle actions, migration batch list/detail, reconciliation permission gating, duplicate-candidate resolution).

### Known limitations

1. Only synthetic, non-confidential fixtures are included — no real client regulatory template package has been imported.
2. Source ownership and licensing for any future real client source package remain to be confirmed before import.
3. Production regulatory-approver (VP/Tenant Admin) role assignments for real tenants remain to be defined by the client organization.
4. No checklist-execution engine exists — this milestone is governance/migration only.
5. No IIG calculations exist. `TemplateItem.applicability_rule` is a reserved placeholder field only; no evaluation logic exists.
6. No Orange Book integration exists.
7. No AI summarization or chatbot exists.
8. No Word add-in exists.
9. No 21 CFR Part 11 compliance is claimed by this milestone.
10. Production malware scanning still requires an actual scanner deployment (carried over from Milestone 2 — `StubScanner` marks all files clean; `ClamAVScanner` needs a running clamd service not part of this milestone's compose stack).
11. S3-compatible storage remains an integration point only (carried over from Milestone 2 — `LocalStorage` is what's exercised end-to-end).
12. The Docker Integration CI workflow verifies clean stack startup and migrations; it does not automate a complete real-template-package migration cycle end to end.

---

## Milestone 2 — Secure Document Platform Foundation

**Status: COMPLETE**

Tenant-scoped document upload, malware-scan gating, format-specific processing (PDF/DOCX/XLSX/PPTX), and versioning, with a Next.js frontend on a hardened Django/DRF backend. See [DOCUMENT_PLATFORM.md](DOCUMENT_PLATFORM.md) for architecture.

### Record

- **PR:** [#1](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/1)
- **Source SHA:** `a25dc743f9281025b6cd4928dde2003261475cfb`
- **Merge SHA:** `7a749c852ab0cec42e6eabcaa59932fe0549b668` (two-parent merge commit into `regx-main`, not squashed)
- **Release tag:** [`regx-document-platform-v0.2.0`](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/releases/tag/regx-document-platform-v0.2.0), on the merge commit
- **Legacy `main`:** unchanged throughout (`8ed8cf4b79262c1f3f261e872dc387783818e9ed`)

### CI (post-merge, on `regx-main` at the merge commit)

- [Backend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/29983493597) — success
- [Frontend CI](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/29983493644) — success
- [Docker Integration](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/actions/runs/29983493605) — success

### Test counts

- **Backend:** 169 tests passed, 90.15% coverage (gate 55%). Ruff lint/format clean, import-linter 3/3 contracts kept, AIDatabase guard clean.
- **Frontend unit/accessibility:** 25 tests (Vitest + React Testing Library + jest-axe) — no serious/critical automated a11y violations on `/signin`, `/documents`, `/documents/{id}`.
- **Frontend Playwright:** 24 tests (18 document-flow, 3 sign-in, 2 security/storage, 1 CSP-hydration regression guard).

### Known limitations

1. Production malware scanning requires a real scanner deployment — the shipped `StubScanner` marks all files clean and is explicitly logged as unsafe for production; `ClamAVScanner` exists as the real backend but needs a running clamd service, which is not part of this milestone's compose stack.
2. S3-compatible storage is an abstraction/integration point only — `LocalStorage` is the storage backend actually exercised end-to-end; `S3CompatibleStorage` is scaffolded but not verified against a real S3-compatible endpoint.
3. The Docker Integration CI workflow does not yet automate the complete synthetic PDF upload → scan → processing → locator-creation cycle. That full pipeline was verified manually against the live compose stack during closure, not by a repeatable, automated CI step.
4. Electronic signatures and 21 CFR Part 11 validation are **not implemented**. No claim of Part 11 compliance is made by this milestone.
5. OCR is not implemented.
6. Document comparison and AI summaries are not implemented.

---

## Milestone 1 — REGX Foundation

Branch and tenancy/identity/authorization/audit foundation preceding the document platform. See prior commits on `regx-main` for detail; not re-summarized here.

---

## Next

Milestone 4A–4C and Engineering Milestone 4D are technically complete on `regx-main`. Production FDA data ingestion, production client formulation use, and production regulatory-template migration remain open and require real source/client content plus the corresponding human review and approval processes.

**Milestone 5A is in discovery** and is the defined successor: it makes the production regulatory checklist-content gate signable. It is blocked on human regulatory approval, not on engineering. The next action is a regulatory one — the template-scope decision (register item 1).

Engineering has since continued on tracks that do not touch the regulatory gate:
findings F-1 to F-7 (technical readiness, all merged), Milestone 6 (workflow
engine, merged), Milestone 7 (workflow evidence), Milestone 8 (regulatory case
workspace, merged), Milestone 9 (submission dossier / section readiness),
Milestone 10 (dossier blueprint library, stacked on 9), Milestone 11
(controlled dossier upgrade planning, stacked on 10), Milestone 12 (submission
operations dashboard, stacked on 11) and Milestone 13 (controlled submission
package assembly, stacked on 12). **None of that work
advances the content gate**, which moves only when a named regulatory authority
supplies a real approval. In particular, a blueprint version reading ACTIVE
means only that RegX will let a tenant create dossiers from it, an upgrade plan
reading READY means only that it has been reviewed inside RegX and may be
applied, and a dossier section reading READY is an internal readiness signal. The operations
dashboard reports internal operational status and nothing else, and a package
reading FROZEN means only that its internal manifest can no longer change. None
of these is, or may be presented as, regulatory approval.

Milestones 5B–5D are **not scoped**. 5A deliberately records no detailed requirements for them; each needs its own discovery. Capability areas such as ANDA/DMF scoring, regulatory AI, report generation and Word integration remain unscoped as engineering milestones.