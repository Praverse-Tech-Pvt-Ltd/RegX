# Milestone 5A — OQ-8 Resolution (Discovery)

**Status: BLOCKED ON HUMAN REGULATORY DECISION.** No code changed. Production
regulatory content remains 0/20. Fail-closed behaviour is untouched.

Branch: `regx/discovery/milestone-5a-oq8-resolution`, cut from `regx-main`
`deb146083730334d7ce281618921384147eecfee`.

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

## 8. Preferred resolution (engineering recommendation, conditional)

**Option A**, conditional on the regulatory answer in §9, because it is the only
candidate that is available at creation time, deterministic, well-defined
per-execution, and requires no new regulatory science beyond a scoping
statement. It also composes with everything already approved: calculations keep
their per-calculation `Q_SUBJECT_COMPONENT`, and the snapshot rule
(create-never-select) is reused unchanged.

**If the answer to §9 is "whole formulation" rather than "one component", Option
A is wrong** and the correct resolution is a specified aggregate — which is
Option D and needs its own regulatory specification of the aggregation rule per
`iid.*` field. Engineering should not start that until it is written.

---

## 9. HUMAN REGULATORY DECISION REQUIRED

The smallest question that unblocks this:

> **Is a single IIG checklist execution scoped to exactly one formulation
> component — so that one subject component can be named when the execution is
> created and used for every execution-level `iid.*` value — or is it scoped to
> the whole formulation version, in which case each execution-level `iid.*`
> field needs an approved aggregation rule across components?**

A one-word answer (*component* / *formulation*) selects the resolution path.
If *component*, one follow-up is needed: **may an execution's subject component
differ from a calculation's `Q_SUBJECT_COMPONENT`, and if so which governs the
`iid.*` default?** (Engineering recommendation: allow divergence, record both,
and let the execution-level subject govern execution-level bindings only.)

Owner per the register: Regulatory + Engineering lead.

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

## 17. Status

| | |
|---|---|
| OQ-8 | **BLOCKED ON HUMAN REGULATORY DECISION** (§9) |
| Existing approved specification resolves it | **NO** — it resolves the analogous problem for calculations only |
| Code changed | **NO** |
| Fail-closed behaviour | **PRESERVED** |
| Production regulatory content | **0 / 20** |
| Milestone 5A | **READY FOR REGULATORY AUTHORING / BLOCKED ON HUMAN REGULATORY APPROVAL** — unchanged |
