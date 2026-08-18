# Milestone 5A — OQ-8 Resolution

**Status: CLOSED.** The regulatory decision has been made and implemented.
Production regulatory content remains **0/20** — closing OQ-8 approves no
regulatory question and makes no Part 11 claim.

Discovery branch: `regx/discovery/milestone-5a-oq8-resolution`.
Implementation branch: `regx/feat/milestone-5a-oq8-resolution`, cut from
`regx-main` `deb146083730334d7ce281618921384147eecfee`.

---

## 0. REGULATORY DECISION (recorded verbatim in effect)

**An IID/IIG checklist execution is component-scoped.** A single execution is
scoped to exactly **one** formulation component / inactive ingredient, and its
subject component is identified and governed at execution creation. All
execution-level `iid.*` behaviour refers to that same subject component: FDA-derived
values, applicability, `AssessmentSnapshot` provenance, component-specific
calculations, overrides, reviewer conclusions, controlled export and historical
reconstruction.

**The execution-level subject component is authoritative.** A calculation inside
the execution may **not** independently select a different component. Where a
`Q_SUBJECT_COMPONENT` response or calculation input conflicts with the
execution's governed subject, the resolution **fails closed**. There is no
silent switch, no first/last/latest, no inference by name, UNII or database
ordering, and no averaging across components.

**The invariant:**

> **ONE CHECKLIST EXECUTION = ONE FORMULATION VERSION + ONE GOVERNED SUBJECT
> COMPONENT**

A formulation may have several components and therefore several
component-specific executions where required.

**Why whole-formulation aggregation was rejected.** FDA IID evaluation is
fundamentally excipient-specific: the IID is structured around inactive
ingredient + route of administration + dosage form, with potency and maximum
daily exposure carried on the individual excipient record. No approved general
aggregation rule exists, and inventing one would have been engineering asserting
regulatory meaning. §5 Option D is therefore closed, not deferred.

Regulatory basis and decision owner: the regulatory owner, recorded on the task
that authorised this implementation.

---

## 1. Problem statement

OQ-8 as registered in `MILESTONE_5A_DISCOVERY.md` §9.1:

> Which `AssessmentSnapshot` governs execution-level `iid.*` values? A snapshot
> is scoped to one formulation **component**, while applicability and
> FDA-derived defaults are properties of the **execution**.

Tracing the code changes the shape of this question. The registered wording
implies the missing piece is a *choice among components*. It is not — the
approved specification already settles component choice, and settles snapshot
choice too. What is missing is different, and sharper:

> **The approved component-selection mechanism is answer-time and
> per-calculation. Both OQ-8 consumers run at execution-creation time and are
> per-execution. There is no moment at which the approved mechanism can supply
> them an answer, and no approved concept of "the execution's component" for it
> to supply.**

### 1.1 Exact root cause

Three independent facts, each verified in code:

**(a) Component selection is already approved — but it requires a human answer.**

`calculation_registry.py:152` declares the single enabled selector:

```python
{"type": SELECTOR_RESPONSE_REFERENCE, "question_code": Q_SUBJECT_COMPONENT}
```

`ENABLED_SELECTOR_TYPES = {response_reference}`;
`DISABLED_SELECTOR_TYPES = {registry_component_code}` — the non-answer-based
form was contemplated and **deliberately disabled in 4D-3**
(`calculation_registry.py:116-122`). `calculation_inputs.py:610` is explicit
about what that leaves:

> "No ingredient-name match, no UNII fallback, no display-order or primary-key
> inference: the component is whatever the selector response explicitly
> references, or nothing."

So the subject component is whatever a human named in the `Q_SUBJECT_COMPONENT`
response. That is **Option B, already implemented** — for calculations.

**(b) Snapshot selection is also already approved — snapshots are created, never chosen.**

`iid_assessment/services.py:230` `create_assessment_snapshot()`:

> "Every call creates a new row. There is no reuse, no deduplication, no
> `.first()`, no 'latest' lookup and no update path (M4D3-SNO-006/008)."

`calculation_execution.py:365-395` follows that rule: it resolves the subject
component, reads the `FormulationVersion` fresh inside the transaction, resolves
the active release server-side (M4D3-SRC-001/003), injects the governed Part
14.1 worst-case daily units (M4D3-SRC-004), and **mints a new snapshot** whose
`public_id` becomes the outcome's provenance. There is no "which existing
snapshot" question in the approved model, because the approved model never
picks one.

**(c) Both OQ-8 consumers run before any answer exists, and cannot mint records.**

| Consumer | Call site | When |
|---|---|---|
| FDA-derived default | `services.py:471` — `_resolve_fda_derived_default(q)` inside the response-creation loop of `create_execution` | Execution creation. The `Q_SUBJECT_COMPONENT` response is being created *in that same loop* with `raw_value=None`. |
| Applicability | `services.py:508` — `evaluate_execution_applicability(...)`, `5A-DEC-004` | Execution creation, same transaction, immediately after the slots exist — all unanswered. |

`evaluate_execution_applicability` is called from exactly one place and never
re-runs. `applicability_runtime.py:200` `derive_applicability_outcome` is
read-only by approved design (M4D3-PST-009):

> "Never recomputed from live data, so a historical execution keeps reporting
> what it was assessed against."

And `build_context` is documented as "in-memory only, assembled once per
governed pass and never persisted" — an applicability pass must not create a
regulated `AssessmentSnapshot` as a side effect, which is precisely what the
approved snapshot rule (b) would require.

**(d) "The execution's component" is not a concept the approved model has.**

M4D3-PRV-009 requires "one component across selector, snapshot and every
component-scoped input" — **within a single calculation**. Nothing constrains
two different component-scoped calculations in the same execution to name the
same component. So even if the ordering problem were solved, "the component of
this execution" would still be undefined: the approved model scopes subject
component to a calculation, not to an execution.

That is the exact root cause. It is a **scope and lifecycle mismatch**, not a
missing preference among components.

---

## 2. Current object model

```
ProductDevelopmentRecord ──1:N── FormulationVersion ──1:N── FormulationComponent
        │ (tenant FK)                     │                          │
        │                                 │ FK (PROTECT)             │ public_id (UUID)
        │                                 │                          │
        │                    ChecklistExecution                      │
        │                    · tenant FK (PROTECT)                   │
        │                    · checklist_version FK (PROTECT)        │
        │                    · formulation_version FK (PROTECT)      │
        │                    · NO component reference  ◄─── the gap  │
        │                                 │                          │
        │                                 │ 1:N                      │
        │                          ChecklistResponse                 │
        │                                 │ 1:N                      │
        │                          CalculationOutcome                │
        │                          · source_assessment_snapshot_public_id (UUID, nullable)
        │                                                            │
        └────────── AssessmentSnapshot (tenant FK) ──────────────────┘
                    · formulation_component_public_id  (UUID value, NOT an FK)
                    · formulation_version_public_id    (UUID value, NOT an FK)
                    · immutable after create (clean() blocks all but
                      reviewer_confirmed_match / reviewer / updated_at)
                    · index (tenant, formulation_component_public_id)
                    · NO uniqueness, NO is_current, NO superseded_by
```

The UUID-valued (non-FK) links on `AssessmentSnapshot` are deliberate — the
model comment says a live FK would let the row's meaning "drift if the
underlying IID/Orange Book row is later superseded". That choice is correct and
is *not* what causes OQ-8, but it does mean the ORM offers no reverse accessor
from a component to its snapshots.

---

## 3. Actual cardinalities

| Relationship | Cardinality | Enforced by |
|---|---|---|
| `ChecklistExecution` → `FormulationVersion` | **N : 1**, non-null | FK, `on_delete=PROTECT` |
| `FormulationVersion` → `FormulationComponent` | **1 : 0..N** | FK `related_name="components"`, CASCADE, `ordering=["display_order"]` |
| `(component, version)` → `AssessmentSnapshot` | **1 : 0..N**, append-only | no constraint; `create_assessment_snapshot` always inserts |
| `ChecklistExecution` → `FormulationComponent` | **none — no field exists** | — |
| `CalculationOutcome` → `AssessmentSnapshot` | **1 : 0..1** | nullable UUID, written per calculation run |

**Can one execution correspond to zero, one, or many components?**

- **Structurally: 0..N.** An execution reaches every component of its
  formulation version and is tied to none of them. Zero is reachable — nothing
  requires a `FormulationVersion` to have components (the only component
  constraint is `quantity_per_dosage_unit > 0`).
- **Per approved mechanism: exactly 1 *per component-scoped calculation*,** named
  by that calculation's `Q_SUBJECT_COMPONENT` response, reconciled by
  M4D3-PRV-009 across that calculation's own selector/snapshot/inputs.
- **Per execution: undefined.** Two component-scoped calculations in one
  execution may legitimately name different components.

So an execution-level `iid.*` binding faces **N components × M snapshots each**,
with no approved relationship narrowing it, and no approved notion that the
execution has a single subject at all.

---

## 4. Current fail-closed behaviour (unchanged, and correct)

| Path | Behaviour | Code |
|---|---|---|
| Applicability rule reading any `iid.*` field | `review_required`, reason `APPLICABILITY_SOURCE_UNRESOLVED` | `applicability_runtime.py:113` — `unresolved = {"iid"}`, always |
| FDA-derived binding (`iid.potency_amount`, `iid.maximum_daily_exposure`, `iid.route`) | `source_unavailable` provenance, **no value written** | `services.py:358` — `resolve(binding, None)` |

Both are visible in the API and in the controlled export. The three registry
entries are explicitly labelled "synthetic infrastructure bindings" that
"assert nothing about which FDA field answers which regulatory question".

This behaviour is preserved by this discovery. Nothing was weakened.

---

## 5. Candidate resolutions

Assessed against regulatory meaning, determinism, reproducibility, tenant
safety, auditability, provenance, stale-data risk, calculation compatibility,
override compatibility, controlled export, historical reconstruction and
migration impact.

### Option A — the execution explicitly binds one subject component

Add a nullable subject-component reference to `ChecklistExecution`, supplied by
the creator at execution creation.

| Criterion | Assessment |
|---|---|
| Regulatory meaning | Requires the authority to affirm that an IIG checklist execution is *about* one component. That is a regulatory scoping statement, not a mechanism. |
| Determinism | **Strong.** Available before any answer; one value for the whole execution. |
| Reproducibility | **Strong.** Frozen on the execution row, covered by export and history. |
| Tenant safety | Validated the same way `_component_in_execution` already does — component must belong to the execution's own formulation version. |
| Provenance | Natural: execution-level provenance gains one UUID. |
| Stale data | None; the component is pinned at creation and the version is PROTECTed. |
| Calculation compatibility | Coexists. Per-calculation `Q_SUBJECT_COMPONENT` remains authoritative for calculations; M4D3-PRV-009 unaffected. Possible divergence between execution subject and a calculation's subject must be defined (recommend: allowed, and both recorded). |
| Override / export / history | Additive; no existing semantics change. |
| Migration | Additive nullable column + index. No backfill: existing executions stay `NULL` and keep failing closed. |

**Blocks on:** one regulatory statement (see §9).

### Option B — the question/binding identifies the component

Extend the existing `component_selector` to applicability rules and
`prefill_source` bindings.

**Fails on ordering.** The only enabled selector form is `response_reference`,
and both consumers run before any response is answered. Making it work would
require either re-running applicability after answers (contradicting
M4D3-PST-009's frozen, one-shot outcome) or enabling
`registry_component_code`, which 4D-3 deliberately disabled. Also does not
resolve the per-execution/per-calculation scope mismatch.

### Option C — system selects the governed worst-case component

**Requires regulatory science engineering must not invent.** "Worst case" for
`iid.*` is not defined anywhere approved. Worst by proposed daily exposure? By
exceedance margin against MDE? By criticality of the component's function? Each
is a different regulatory claim. Note the existing worst-case helper
(`governed_maximum_daily_units_value`) is Part 14.1 *dosing regimen* worst case
— an approved rule about **units per day**, not about which component matters
most. Reusing its name for a different decision would be a category error.

### Option D — evaluate all eligible components and aggregate

Same regulatory gap as C, plus new aggregate semantics ("the execution's
`iid.route` when three components have three different routes" has no approved
meaning), plus it would mint N snapshots per applicability pass — regulated
writes from an in-memory, non-transactional evaluation path. Rejected on both
regulatory and engineering grounds.

### Option E — an existing domain relationship already resolves it

**Investigated in full; the answer is no for the OQ-8 consumers, yes for
calculations.** §1.1(a)/(b) documents the approved mechanism that exists
(M4D3-FCR-002..004/012/013, M4D3-SNO-001/006/008, M4D3-SRC-001/003/004). It
cannot be lifted to execution level because of (c) ordering and (d) scope. This
option is closed — but it is why the recommendation below is narrow: most of the
machinery already exists and is approved.

---

## 6. Regulatory implications

The decision determines **which precedent record answers a regulated question**
on an approved checklist. Choosing a component chooses an IID precedent, which
chooses a potency/MDE/route that a reviewer signs against. Engineering can
determine relationships, cardinality, determinism, provenance and transaction
rules. It cannot determine that "the execution is about the highest-exposure
inactive ingredient" — that is a regulatory mapping.

`MILESTONE_5A_APPROVAL_REGISTER.md` already carries this constraint into the
approval workflow (items 11 and 12; the OQ-8 warnings at lines 27, 32, 257, 294).

---

## 7. Engineering implications

- The resolver contract (`resolve(identifier, source)`, pure, no queries) is
  already correct and needs no change: it takes a caller-selected source. Only
  the **caller's selection step** is missing.
- `_resolve_fda_derived_default(question)` currently receives only the question
  — not the execution. Any resolution requires threading execution context into
  it. That is a small, contained signature change.
- Applicability would need the subject available in `build_context(execution)`,
  which already receives the execution — so Option A needs no new plumbing
  there, only a populated field.
- Under Option A, an execution created without a subject component must keep
  failing closed exactly as today. The fail-closed path must remain the default,
  not an error branch.

---

## 8. Chosen resolution — Option A, as decided

**Option A: the execution explicitly binds one subject component.** Selected by
the regulatory decision in §0, and implemented. It is available at creation time,
deterministic, well-defined per execution, and reuses everything already
approved — the snapshot rule (create-never-select), the server-side release
resolution and the Part 14.1 worst-case daily-units helper are all unchanged.

---

## 9. HUMAN REGULATORY DECISION — ANSWERED

The question put to the owner was whether an execution is scoped to one
formulation component or to the whole formulation version.

**Answer: component.** And on the follow-up — whether an execution's subject may
differ from a calculation's `Q_SUBJECT_COMPONENT` — the owner went further than
the engineering recommendation: divergence is **not** permitted. The
execution-level subject is authoritative and a conflict fails closed. That is
implemented as stated; the recommendation to allow divergence was not adopted.

---

## 10-15. Impact if Option A is approved

| Area | Impact |
|---|---|
| **Migration** | One additive nullable UUID column (+ index) on `ChecklistExecution`. No backfill; existing rows stay `NULL` and keep failing closed. Reversible. |
| **Models** | `ChecklistExecution` gains the field and a validation that the component belongs to its own `formulation_version` (mirroring `_component_in_execution`). `AssessmentSnapshot` unchanged. |
| **API** | `POST /executions/` accepts an optional subject-component `public_id`; execution serializers expose it. Omission keeps today's behaviour exactly. |
| **Frontend** | Optional component picker on execution creation, sourced from the formulation version's components. Nothing else changes; no UI redesign. |
| **Provenance** | Execution-level provenance gains the subject component UUID and the created snapshot UUID, using the existing `SUBJECT_COMPONENT_PROVENANCE_KEY` spelling. |
| **Export** | The controlled export gains those UUIDs and must include them in the checksum, exactly as jurisdiction is handled today. |
| **Audit** | `EXECUTION_CREATED` payload gains the subject component UUID. Snapshot creation already emits its own governed event. |

---

## 16. Required tests (if implemented)

Focused, adversarial, and mostly already patterned in the suite:

1. single component named → deterministic resolution, provenance recorded
2. multiple components present, one named → the named one governs, no inference
3. no component named → `review_required` / `source_unavailable` (fail-closed default)
4. component named that belongs to another formulation version → refused
5. **two-tenant adversarial:** component UUID from tenant B on tenant A's execution → refused, identity never echoed
6. component belongs to a *different version* of the same product → refused
7. no active FDA release → `source_unavailable`, never a fabricated value
8. snapshot creation failure inside the transaction → whole execution discarded
9. historical reproducibility: an approved execution keeps reporting its original snapshot after a later release supersedes it
10. applicability outcome frozen after creation (M4D3-PST-009 preserved)
11. controlled export includes the new UUIDs and the checksum changes when they change
12. `expected_version` concurrency unaffected on the touched endpoints
13. divergence case: execution subject ≠ calculation `Q_SUBJECT_COMPONENT` behaves per the §9 follow-up answer

Gates: focused backend tests; full backend suite if backend code changes
materially; frontend typecheck/lint/unit/E2E if the API contract changes.

---

## 17. What was implemented

### Model

`ChecklistExecution.subject_component` — FK to `formulations.FormulationComponent`,
`on_delete=PROTECT`, `null=True`. A live FK rather than a frozen UUID because an
execution is operational state (unlike `AssessmentSnapshot`, which freezes
identity deliberately), and PROTECT is what stops a component being deleted out
from under a governed execution — matching how `formulation_version` is already
held.

`clean()` enforces two invariants at the model layer, so no code path can bypass
them: the component must belong to the execution's own formulation version
(which also closes the cross-tenant case, since a foreign component necessarily
belongs to a foreign version), and once set it is immutable — a correction
requires a new execution.

**Uniqueness had to change.** The old constraint was one active execution per
`(tenant, checklist_version, formulation_version)`, which made per-component
executions impossible. It is now two constraints: one active execution per
`(…, subject_component)` where the subject is set, and — because SQL treats NULLs
as distinct — the original constraint retained for subject-less rows, so the
pre-OQ-8 guarantee is not silently weakened.

Migration `0006_execution_subject_component`: additive nullable column, index,
and the constraint split. Reversible.

### Creation contract — the ordering fix

The subject component is resolved and validated **before** the transaction, so it
is already known when the two consumers run inside it. That is the fix to the root
cause in §1.1(c); nothing is deferred to a later "recompute" pass, and
`M4D3-PST-009`'s frozen applicability outcome is untouched.

Inside the transaction, in order: create the execution → create the governed
component-specific `AssessmentSnapshot` → resolve FDA-derived defaults against it
→ evaluate applicability against it.

Exactly one snapshot is created per creation pass and shared by every `iid.*`
binding in it. This is **not** the forbidden kind of reuse (`M4D3-SNO-006/008`
bans `.first()`, `.latest()`, dedup and reuse of pre-existing rows): the row is
new, made in this transaction, for this execution's one subject component.
Sharing it is what makes the bindings mutually consistent — minting one per
question could straddle a release change and leave a single execution answering
from two different sources.

### FDA-derived resolver

`_resolve_fda_derived_default(question, precedent)` now receives the governed
`IIDPrecedentRecord` reached through the snapshot, instead of `None`. The resolver
contract is unchanged and still pure: it receives an already-selected source and
queries nothing. `None` remains legitimate and still records an explicit
`source_unavailable` with no value — for a legacy execution, a subject component
that matched no precedent, or no active FDA release.

Provenance per resolved binding additionally records
`subject_component_public_id`, `formulation_version_public_id` and
`assessment_snapshot_public_id`; release identity was already covered by
`source_version` (release UUID plus source checksum).

### Applicability

`build_context(execution, iid_snapshot)` resolves `iid.match_status`,
`iid.has_potency` and `iid.has_mde` from the passed snapshot. The snapshot is
passed in rather than looked up: this function is in-memory only and must not
create a regulated record. With no snapshot the `iid` group stays unresolved and a
rule reading it still fails closed to `review_required`.

### Calculation consistency

The execution's subject joins the candidate set in
`calculation_inputs._resolve_subject_component`, reconciled by the same
order-independent machinery as the selector and upstream outcomes
(`M4D3-PRV-009`). Disagreement fails closed through the existing mismatch path —
there is deliberately no branch letting the execution's value silently overwrite
the selector's. A new provenance source, `execution_subject`, records that the
execution asserted the identity.

### `Q_SUBJECT_COMPONENT` — treatment **A** (retained, subordinate)

Retained unchanged as the calculation-level selector, now **subordinate** to the
execution subject: it cannot select a different component because any divergence
fails closed. Not deprecated (B) and not server-derived (C), because both would
mean rewriting response-population semantics for an approved mechanism that
already works — and the invariant already guarantees the consistency the decision
requires. This is the minimum-risk path for the current architecture.

### API and frontend

`POST …/executions/` accepts an optional `subject_component_public_id`; the
service refuses creation without it when the content reads `iid.*`. A well-formed
UUID asserts nothing — eligibility is proven server-side. Two governed errors:
`subject_component_required` and `subject_component_not_eligible`, the latter
deliberately not distinguishing "no such component" from "belongs to another
formulation or tenant".

Execution reads expose `subject_component_public_id` and
`subject_component_ingredient_name`. The executions table shows the governed
excipient beside the formulation version, with an em dash for a legacy execution
that has none. No UI redesign; the existing company/RegX shell is unchanged.

### Controlled export and audit

The export's `execution` block carries `subject_component_public_id` and
`subject_component_ingredient_name` — inside the checksum-covered payload,
omitted rather than nulled for a legacy execution, and mirrored in the CSV
flattening. `EXECUTION_CREATED` audit gains the subject component and snapshot
UUIDs, recording `None` truthfully rather than omitting it. UUIDs only.

## 18. What determines the subject requirement — CORRECTED

**Execution subject requirement is determined solely by the governed
`ChecklistDefinition.execution_scope` classification, and never by question
content.**

An earlier revision of this document triggered the requirement on content that
read `iid.*`. The regulatory owner corrected that: an execution's regulatory
scope must not change merely because a version added, removed or reworded a
question. A component-scoped checklist that currently declares no `iid.*`
binding is still a component-scoped checklist.

| `ChecklistDefinition.execution_scope` | Requirement |
| --- | --- |
| `formulation_component` | **Subject component required**, always — independent of question content |
| `formulation_version` | **Not inherently required.** Supplying one is refused rather than ignored |
| *blank / unclassified* | **Execution creation prohibited** — `execution_scope_unclassified` |

### The classifier

`ChecklistExecutionScope` on **`ChecklistDefinition`**, never on
`ChecklistVersion`: execution scope is an invariant of the checklist, and putting
it on the version is exactly what would let a new content version silently
re-scope it. It sits beside `scope_type`, which is about *ownership*
(`platform_master` / `tenant`) and is a different question entirely.

Named for the scope rather than for the product label, so the engine enforces a
structural invariant instead of having to know what "IID/IIG" means.

**No classifier previously existed.** This was verified before adding one:
neither `ChecklistDefinition`, `ChecklistVersion`, the enums, the templates
registry (`category` is free text with no link to this app), nor any
specification carried a machine-readable checklist type. Nothing is inferred
from title, code, description, question codes, bindings, calculations,
jurisdiction, `regulatory_basis` or template free text — a test asserts that a
definition named "IIG Proportionality Clearance - Tablets and Capsules", with an
IID description and `iid.*` content, is still refused while unclassified.

### Zero eligible components

For a `formulation_component` definition whose formulation version has **no
eligible components**: **execution creation is not permitted — fail closed**,
with `subject_component_unavailable`. No subject-less component-scoped execution
is created, no component is invented, and selection is not deferred.

Kept distinct from `subject_component_required` (the caller named none) and from
`execution_scope_unclassified` (we do not know what the checklist regulates).
Three different faults, three different fixes.

### Governance of the classification

`execution_scope` is governed configuration. `ChecklistDefinitionDetailView`
exposes only `GET` and `DELETE` — there is no `PATCH`/`PUT`, so in practice the
value is set once at creation, and a test pins that. `clean()` additionally
refuses changing an already-governed value: re-classifying would silently alter
what every existing approved version and completed execution of that checklist
was regulating. Blank → value **is** permitted, because existing definitions must
be able to become governed.

Cloning carries the classification forward, otherwise every clone would be born
unclassified and unexecutable. That is not inference: it is propagating an
explicit classification to content that regulates the same thing.

## 19. Historical data

**Existing definitions are NOT auto-classified.** The migration adds the column
and backfills nothing — no title, code or content heuristic runs. Every existing
definition is unclassified until a human governs it, and until then no execution
can be created against it. That is deliberate: a permissive default would have
silently under-governed a component-specific checklist.

No backfill of executions either, and no guessing. Existing executions keep
`subject_component = NULL` and retain pre-OQ-8 behaviour exactly: `iid.*` stays unresolved, no snapshot is
created for them, and a component-scoped calculation continues to be governed by
its own selector. An already-approved execution therefore keeps reproducing what
it was assessed against, which the decision requires.

Classified per the brief: no historical execution falls in class **A**
(unambiguously reconstructable), because nothing persisted on a pre-OQ-8
execution identifies a subject component — `Q_SUBJECT_COMPONENT` responses are
per-calculation and need not agree across an execution. All existing rows are
therefore class **B/C**, and the nullable transitional state is the correct
handling.

## 20. Status

| | |
|---|---|
| OQ-8 | **CLOSED** |
| Regulatory decision | **Component-scoped; execution subject authoritative** (§0) |
| Existing approved specification resolved it | **NO** — the decision was required, then implemented |
| Fail-closed behaviour | **PRESERVED** — every unresolved case remains `review_required` / `source_unavailable` |
| Production regulatory content | **0 / 20** — unchanged; no question authored or approved |
| Part 11 | **No claim** |
| Milestone 5A | **READY FOR REGULATORY CONTENT AUTHORING / APPROVAL** — the last engine ambiguity is closed; approval remains a human act |
