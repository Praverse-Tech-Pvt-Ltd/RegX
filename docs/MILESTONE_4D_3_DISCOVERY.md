# Milestone 4D-3 Discovery — Draft-Answer Generation, FDA-Derived Population, and Calculation

**Status: DISCOVERY ONLY. No implementation code in this milestone. Not approved for implementation.**

**Branch:** `regx/feat/milestone-4d-3-discovery`
**Base SHA:** `c0adef4448153368c5bb280219c154f60be052f1` (Milestone 4D-2 merge)
**Authoritative inputs:**
- `docs/MILESTONE_4D_DISCOVERY.md` — overarching 4D design (all five open questions resolved)
- `docs/MILESTONE_4D_2_DISCOVERY.md §1` — canonical 4D-3 scope definition
- `docs/MILESTONE_4D_2_IMPLEMENTATION_SPEC.md §2` — 4D-3 items explicitly out of scope for 4D-2
- `docs/IID_CALCULATION_RULES.md` — six calculation formulas, `CalculationResult` dataclass, `CalculationStatus`

This document is the discovery gate for Milestone 4D-3. It determines the
actual approved scope from the repository evidence above, surveys the existing
domain to identify what 4D-3 must build on and what it must not touch, and
records the design questions that require resolution before a 4D-3
implementation specification may be written.

No implementation code is produced here. No migration is created. No existing
runtime behavior is modified. Every decision below is written to be reviewed
and revised before any implementation branch opens.

---

## 1. Confirmed Scope (from repository evidence only)

The canonical scope definition is in `docs/MILESTONE_4D_2_DISCOVERY.md §1`:

> **4D-3 (not started):** Draft-answer generation, automatic `FDA_DERIVED_DEFAULT`
> population, `SYSTEM_CALCULATED` computation, and recalculation.

`docs/MILESTONE_4D_2_IMPLEMENTATION_SPEC.md §2` (Out of scope for 4D-2) confirms:

> - `FDA_DERIVED_DEFAULT` auto-population **(4D-3)**
> - `SYSTEM_CALCULATED` computation and recalculation **(4D-3)**

`docs/MILESTONE_4D_DISCOVERY.md §10` (Automatic draft-answer generation) describes the
approved population pass:

> When a `ChecklistExecution` is created, the system performs one pass:
> - every `FDA_DERIVED_DEFAULT` question is populated from the current governed FDA data;
> - every `SYSTEM_CALCULATED` question whose inputs are already answered is computed;
> - every other question is left blank.

`docs/MILESTONE_4D_DISCOVERY.md §8b` (Recalculation semantics) governs in-draft recalculation:

> While `status = draft`, editing a `USER_REQUIRED`/`EVIDENCE_DERIVED` input answer
> immediately re-triggers recomputation of every `SYSTEM_CALCULATED` question whose
> `calculation_binding` depends on it. The moment `submit_review` succeeds, every
> response is locked.

**4D-2 delivers the lock only** (per `MILESTONE_4D_2_DISCOVERY.md §6d`). 4D-3 delivers
the population.

The confirmed 4D-3 scope is therefore:

1. **`FDA_DERIVED_DEFAULT` population pass** — at execution creation, populate draft
   answers for every applicable question whose `data_source_classification == fda_derived_default`
   by calling existing governed read-side services from `fda_data` and `iid_assessment`.

2. **`SYSTEM_CALCULATED` computation pass** — at execution creation (and on every
   `USER_REQUIRED`/`EVIDENCE_DERIVED` response update in `draft` state), compute every
   applicable `SYSTEM_CALCULATED` question whose upstream inputs are satisfied, by calling
   the six existing calculation functions from `iid_assessment.calculations` verbatim.
   Update the corresponding `CalculationOutcome` rows (currently created at execution
   creation with `status = DATA_REQUIRED` by 4D-2's `create_execution()`).

3. **In-draft recalculation** — when `enter_response()` writes a `USER_REQUIRED` or
   `EVIDENCE_DERIVED` answer on a `draft` execution, cascade-recompute every
   `SYSTEM_CALCULATED` question that depends on the updated answer via
   `ChecklistQuestion.calculation_binding`.

4. **`source_assessment_snapshot_public_id` population** — where a `SYSTEM_CALCULATED`
   question's answer is taken directly from a frozen `AssessmentSnapshot`, set this UUID
   on the `CalculationOutcome` row (currently always null in 4D-2).

5. **No new calculation formulas** — all six from `iid_assessment.calculations` are
   reused unmodified. No formula logic is duplicated or replaced.

6. **Frontend: draft population display** — show computed/pre-filled answers to the
   user in the execution detail UI, with provenance labels distinguishing
   `FDA_DERIVED_DEFAULT` values from `USER_REQUIRED` ones.

---

## 2. What 4D-3 Explicitly Does NOT Include

These items are confirmed deferred to later milestones by the approved design:

- Override/deviation workflow — **4D-4**
- Controlled JSON/CSV export — **4D-4**
- `reviewer_conclusion_note` / reviewer conclusion routing — **already delivered in 4D-2**
- Per-question `EVIDENCE_DERIVED` attachment-confirmation flow — **4D-4** (the
  attachment-reference answer type exists in 4D-2; the evidence-confirmation enforcement
  at submission is part of 4D-4's override/deviation layer)
- PDF/Word export — explicitly deferred beyond 4D
- Real regulatory checklist content — deferred to a separate regulatory-content gate
- Promotion of `_csv_safe_cell()` to `common` — 4D-4
- Electronic signatures, 21 CFR Part 11 compliance — not in scope for any 4D stage

---

## 3. Current Architecture Relevant to 4D-3

### 3a. Execution and response infrastructure (4D-2, CLOSED)

The following models, services, and infrastructure are in `regx-main` and must not be
modified by 4D-3 beyond the targeted additions described in §4–§6:

- `ChecklistExecution` — 7-status lifecycle; `create_execution()` creates response rows
  eagerly with `raw_value = None` and `CalculationOutcome` rows with
  `status = DATA_REQUIRED` for every `SYSTEM_CALCULATED` question.
- `ChecklistResponse` — per-question answer row; `data_source_type_snapshot` frozen at
  creation; `full_clean()` enforced at every save.
- `CalculationOutcome` — placeholder created in 4D-2 with `status = DATA_REQUIRED`,
  `value = None`, `inputs = {}`, `input_provenance = {}`. 4D-3 populates these.
- `enter_response()` — accepts `USER_REQUIRED`/`EVIDENCE_DERIVED` answers; must be
  extended (not replaced) to trigger recalculation after a successful write.
- `ChecklistQuestion.calculation_binding` — JSON field on each `SYSTEM_CALCULATED`
  question that declares which calculation function and which upstream question codes
  supply its inputs. 4D-3 consumes this; it does not redefine it.
- `applicability.py` — structured, allow-listed applicability rule validator (4D-1
  delivery); evaluates `condition_json` against a fixed field registry. The **runtime
  evaluator** (evaluating a rule against a live formulation-version context) is not yet
  implemented — 4D-2 deferred it (the applicability freeze is implicit via version
  immutability; see `MILESTONE_4D_2_DISCOVERY.md §7`). 4D-3 needs the runtime
  evaluator for the population pass.

### 3b. `iid_assessment` services (read-only, 4D-3 consumers)

All of the following are existing, shipped, unmodified services. 4D-3 calls them;
4D-3 does not alter them.

- `iid_assessment.assess.run_preview(*, formulation_component, active_release)` — runs
  the full matching + calculation pipeline and returns a `PreviewResult` (not a stored
  snapshot). Used as the input source for `SYSTEM_CALCULATED` answers that mirror an IID
  assessment result.
- `iid_assessment.matching.find_iid_candidates(...)` — IID precedent-match lookup.
- `iid_assessment.calculations.*` — six pure functions:
  `calculate_percentage_w_w`, `calculate_daily_exposure`, `calculate_percentage_of_potency`,
  `calculate_difference_from_potency`, `calculate_percentage_of_mde`,
  `calculate_difference_from_mde`. Each returns a `CalculationResult` dataclass; 4D-3
  maps `CalculationResult` fields onto `CalculationOutcome` fields verbatim (as specified
  in `docs/MILESTONE_4D_DISCOVERY.md §9`).
- `iid_assessment.models.AssessmentSnapshot` — immutable per-component snapshot; when a
  `SYSTEM_CALCULATED` answer comes directly from a frozen snapshot,
  `CalculationOutcome.source_assessment_snapshot_public_id` is set to that snapshot's
  `public_id`.

### 3c. `fda_data` services (read-only, 4D-3 consumers)

- `fda_data.substance_matching.resolve_substance_identity(normalized_name)` — resolves a
  substance name to an approved `SubstanceSynonymMapping` or direct `IIDIngredient`
  match. Used for `FDA_DERIVED_DEFAULT` identity questions.
- Approved `IIDPrecedentRecord`, `IIDIngredient`, `OrangeBookProduct` — read-only
  sources for `FDA_DERIVED_DEFAULT` values. 4D-3 must never write to these tables.

### 3d. `formulations` data (read-only, 4D-3 consumers)

- `FormulationComponent.quantity_per_dosage_unit`, `quantity_unit`,
  `resolved_ingredient_public_id` — prefill source for `USER_REQUIRED` questions with
  `prefill_source = "formulation_component"`. These values flow into the `USER_REQUIRED`
  question's draft answer as a UI convenience only; the question retains
  `data_source_type_snapshot = "user_required"` and is never labeled FDA-sourced.
- `FormulationVersion.total_dosage_unit_weight`, `maximum_dosage_units_per_day` —
  inputs to calculation formulas A and B.

### 3e. Applicability rule runtime evaluator (new in 4D-3)

`backend/iig_checklist/applicability.py` currently provides a **validator** (structural
validation of a `condition_json` tree at definition-authoring time) but not a **runtime
evaluator** (evaluating a stored, validated tree against a live execution context).
`field_registry.py` declares the allowed field set (`product.route`,
`product.dosage_form`, `product.release_type`, `iid.match_status`, `iid.has_mde`,
`iid.has_potency` — version 1) but provides no binding of these field names to actual
Python values.

4D-3 must implement the runtime evaluator — a pure function that takes a
`condition_json` tree and an execution-context dict (keyed by the same field names in
`FIELD_REGISTRY_VERSION = 1`) and returns `True` (applicable) or `False`
(not applicable). This is a new function in `applicability.py` (not a new file) — small,
no `eval`/`exec`, a fixed dispatch table keyed by `op`, exactly mirroring the
validator's own operator vocabulary.

---

## 4. Population Pass Design (Proposed)

The approved design specifies one pass at execution creation (§10 of
`MILESTONE_4D_DISCOVERY.md`) that:

1. Calls `FDA_DERIVED_DEFAULT` resolvers for every applicable question of that
   classification.
2. Calls calculation functions for every applicable `SYSTEM_CALCULATED` question whose
   upstream inputs are already present (from the FDA-derived answers just populated, or
   from the `FormulationVersion` fields).

### 4a. Population sequencing

Because `SYSTEM_CALCULATED` answers depend on `FDA_DERIVED_DEFAULT` (and
`USER_REQUIRED`) inputs, the population pass must order work:

1. Resolve `FDA_DERIVED_DEFAULT` answers first — all sections, all questions.
2. Compute `SYSTEM_CALCULATED` answers whose all upstream question codes now have
   non-null `raw_value` or `is_not_applicable = True`.
3. Leave as `DATA_REQUIRED` any `SYSTEM_CALCULATED` question that still has unresolved
   upstream inputs (e.g. a `USER_REQUIRED` question the user has not yet answered).

This ordering is deterministic and does not require iterative re-runs — `FDA_DERIVED_DEFAULT`
values never depend on other questions' answers; `SYSTEM_CALCULATED` answers can only
depend on `FDA_DERIVED_DEFAULT`, `USER_REQUIRED`, `EVIDENCE_DERIVED`, or other
`SYSTEM_CALCULATED` questions (never on `REVIEWER_CONFIRMED`).

### 4b. `ChecklistAnswerSource` abstraction

`docs/MILESTONE_4D_DISCOVERY.md §4` proposes a `ChecklistAnswerSource` resolver layer
that calls existing unmodified services. This is the correct boundary:

- `ChecklistAnswerSource.fda_derived(question, formulation_version)` — returns the
  governed FDA value for a given question based on `question.data_source_type` and
  `question.code`, without the population pass needing direct knowledge of which service
  to call per question type. The mapping from question code to resolver is a small,
  explicit dispatch dict, not dynamic reflection.
- The resolver for identity-match questions calls `resolve_substance_identity()`.
- The resolver for precedent-route/dosage-form questions calls `find_iid_candidates()`.
- The resolver for formulation fields reads directly from `FormulationVersion` /
  `FormulationComponent` model fields.

**OPEN QUESTION 1 (requires resolution before implementation):** Should
`ChecklistAnswerSource` be a module-level set of functions or a class? A module-level
function set is simpler and avoids an unnecessary object; a class enables test injection
and mocking. This document recommends functions, but a design reviewer may prefer the
class shape for the same testability reason `iid_assessment.assess` uses a function
boundary.

### 4c. `CalculationBinding` consumption

`ChecklistQuestion.calculation_binding` is a `JSONField` that declares
`{"function": "calculate_percentage_w_w", "inputs": {"quantity_per_unit_grams": "Q4",
"total_dosage_unit_weight_grams": "formulation.total_dosage_unit_weight"}}` or similar.
4D-3 must define the exact structure of this JSON so that the population pass can:

- Identify which `iid_assessment.calculations` function to call.
- Gather input values from upstream question `raw_value` responses or from
  `FormulationVersion` fields.
- Call the function, capture the `CalculationResult`, and write all its fields into the
  `CalculationOutcome` row.

**OPEN QUESTION 2 (requires resolution before implementation):** The exact JSON
schema for `ChecklistQuestion.calculation_binding` is not yet specified in any approved
document. The 4D discovery doc describes the concept (`§9`) but does not supply a
normative schema. This must be defined and reviewed before any implementation. See
`docs/MILESTONE_4D_3_SCOPE_REGISTER.md` for the open-question register.

### 4d. Recalculation on `enter_response()`

Per the approved §8b rule: while `status = draft`, any `USER_REQUIRED` or
`EVIDENCE_DERIVED` answer update triggers recomputation of every dependent
`SYSTEM_CALCULATED` question. 4D-3 must extend `enter_response()` to:

1. After writing and committing the response, collect every `SYSTEM_CALCULATED` question
   in the same execution whose `calculation_binding` declares a dependency on the just-
   updated question's code.
2. Re-run the calculation for each such question (same `ChecklistAnswerSource` path as
   the population pass).
3. Update the `CalculationOutcome` row in place (in-draft mutation is correct and
   expected; §8b explicitly allows in-place mutation in `draft` state).

The dependency graph is acyclic by construction (no `SYSTEM_CALCULATED` question may
depend on another `SYSTEM_CALCULATED` question as a named input — they may only depend
on `FDA_DERIVED_DEFAULT`, `USER_REQUIRED`, or `EVIDENCE_DERIVED` inputs, per the
approved data-source classification rules). This means a single-pass cascade is always
sufficient; no cycle detection is needed.

**OPEN QUESTION 3 (requires resolution before implementation):** Whether the cascade
recalculation runs in the same database transaction as `enter_response()` (guaranteeing
atomicity at the cost of longer transactions) or via `transaction.on_commit()` (
decoupled, shorter transactions, but a window where calculated answers lag). This
document recommends in-transaction (same `transaction.atomic()`) for correctness, since
a partially-updated calculation state in a committed draft execution would be confusing
to a concurrent reader. A reviewer may prefer a different approach.

---

## 5. Applicability Runtime Evaluator Design

### 5a. Context object

The runtime evaluator needs a context dict keyed by the field registry's names:

```python
{
    "product.route": "oral",
    "product.dosage_form": "tablet",
    "product.release_type": "immediate",
    "iid.match_status": "EXACT_MATCH",   # or None if no match
    "iid.has_mde": True,                 # bool: matched IID record has a non-null MDE
    "iid.has_potency": False,
}
```

This context is assembled once per population pass from the `FormulationVersion` and
the `FDA_DERIVED_DEFAULT` resolution results. It is an in-memory dict, never stored in
the database.

### 5b. Evaluator function

```python
def evaluate_condition(condition_json: dict, context: dict) -> bool:
    """Returns True (applicable) or False (not applicable). Pure function; no side effects.
    condition_json must have already been validated by validate_condition_json()."""
```

Operator dispatch mirrors the validator's vocabulary exactly:
`eq`, `neq`, `in`, `not_in`, `exists`, `not_exists`, `gt`, `gte`, `lt`, `lte`; composed
via `all` (AND) / `any` (OR). A field not present in `context` is treated as `None` for
existence checks and as absent for comparison checks (returns `not_exists` = True,
`exists` = False). No `eval`, no `exec`, no dynamic attribute access.

### 5c. `NOT_APPLICABLE` vs. `DATA_REQUIRED`

A question whose `condition_json` evaluates to `False` must be marked
`is_not_applicable = True` with `not_applicable_reason` set to the structured rule
identifier (from `ApplicabilityRule.condition_checksum` or the `ApplicabilityRule`
public ID) — never free text. This matches the §3a requirement: "a question resolved
`NOT_APPLICABLE` does not block `submit_review`/`approve`."

A `SYSTEM_CALCULATED` question whose applicability rule evaluates `True` but whose
upstream inputs are still unresolved remains `raw_value = None`, `is_not_applicable =
False`, `CalculationOutcome.status = DATA_REQUIRED` — these are distinct states.

---

## 6. `source_assessment_snapshot_public_id` Population

When a `SYSTEM_CALCULATED` question's answer is derived from an existing
`AssessmentSnapshot` (because the formulation component already has a frozen IID
assessment preview), `CalculationOutcome.source_assessment_snapshot_public_id` is set
to that snapshot's `public_id`. This implements the reproducibility guarantee from
§9 of the 4D discovery document: "when a checklist question's answer is exactly 'what
did the IID assessment preview say,' it points at the frozen snapshot."

**OPEN QUESTION 4 (requires resolution before implementation):** Under what conditions
does the population pass prefer a frozen `AssessmentSnapshot` over calling `run_preview()`
live? Two options:
- **Option A (snapshot-first):** If a non-stale `AssessmentSnapshot` exists for the
  given `FormulationComponent` and the active FDA release, use it; only call
  `run_preview()` if none exists.
- **Option B (live-first):** Always call `run_preview()` at population time; create a
  new `AssessmentSnapshot` to freeze the result; set `source_assessment_snapshot_public_id`
  to the newly created snapshot.

Option B guarantees that the checklist's calculation provenance always has a frozen
snapshot, making reproducibility unconditional. Option A avoids redundant computation but
introduces a question about which existing snapshots are "fresh enough." This document
recommends Option B for simplicity and unconditional reproducibility, but both options
are valid engineering choices that a reviewer should confirm before implementation.

---

## 7. No New Models or Migrations

4D-3 does not introduce new database models or migrations. All required columns exist in
4D-2:

- `CalculationOutcome` — all fields present; `value`, `inputs`, `input_provenance`,
  `source_assessment_snapshot_public_id`, `formula_version`, `status`, etc. are all
  already defined and nullable. 4D-3 populates them with real values.
- `ChecklistResponse.raw_value`, `entered_by`, `entered_at` — already defined;
  4D-3 writes non-null values for `FDA_DERIVED_DEFAULT` questions.
- `ChecklistResponse.system_derived_value` — already defined; used in 4D-4 for
  override tracking, not yet populated in 4D-3.

If the applicability runtime evaluator requires any configuration or cache table, that
would be a new model — but this document concludes no such table is needed for the
evaluator (pure function + in-memory context dict).

---

## 8. Frontend Scope for 4D-3

The approved design defers the full question-by-question response entry UI to 4D-3/4D-4
(`MILESTONE_4D_2_DISCOVERY.md §15`):

> 4D-2 frontend scope is minimal by design. The question-by-question response entry UI
> (the full checklist execution screen) is 4D-3/4D-4 scope because it requires
> auto-population and calculation display.

4D-3 frontend scope:

- **Execution detail — response section:** display each question's answer with its
  `data_source_type_snapshot` provenance label (`FDA-derived`, `User entry`, `Calculated`,
  `Reviewer confirmed`).
- **Auto-populated answers:** display `FDA_DERIVED_DEFAULT` values as read-only with
  a `ProvenanceLabel(kind="FDA_SOURCE")` badge (matching existing convention).
- **`SYSTEM_CALCULATED` answers:** display the `CalculationOutcome.value` and
  `status` (with status-code display for `DATA_REQUIRED` / `FDA_VALUE_UNAVAILABLE` /
  etc. — never a fabricated value).
- **`USER_REQUIRED` answers with `prefill_source`:** show the pre-filled value as
  editable; display a "Pre-filled from formulation" hint rather than a provenance label.
- **Recalculation feedback:** when a user edits a `USER_REQUIRED` field whose change
  triggers recalculation, the affected `SYSTEM_CALCULATED` fields update after the
  PATCH completes (reload from server, no client-side formula re-evaluation).
- **No formula logic in the frontend** — the frontend is a display layer only; all
  calculation logic lives in the backend.

---

## 9. Import Linter Contract (no change)

4D-3 introduces no new cross-domain import directions. The existing contracts remain
unchanged:

- `iig_checklist` may import from `fda_data`, `formulations`, `iid_assessment`, `documents`
  (read-only services only).
- None of those four may import back into `iig_checklist`.
- `formulations` must not import `iig_checklist` (verified by the existing
  `iig-checklist-formulation-read-only` contract).

The population pass calls `fda_data` and `iid_assessment` read-only services — no
new FK relationships to those apps, no new migration dependencies.

---

## 10. Security and Data-Integrity Considerations

**No auto-approval.** The population pass writes draft answers only. It never advances
`ChecklistExecution.status` beyond `draft`. A populated execution is still a `draft`
that requires explicit `submit_review` and then `approve` by a different actor.

**No fabricated values.** A blocked calculation (`status != OK`) is written with
`value = None` and the correct `reason_code`. The system never stores `0` or an empty
string as a stand-in for "unknown." This matches the existing `CalculationStatus` rule
already enforced in `iid_assessment`.

**Provenance labeling.** `FDA_DERIVED_DEFAULT` answers written by the population pass
must set `entered_by = None` and emit a distinct audit event
(`iig_checklist.response.fda_populated`) rather than the ordinary `response.entered`
event, so the audit trail distinguishes system-generated draft values from user-entered
ones. This is a 4D-3 addition to the audit vocabulary.

**`full_clean()` enforcement.** Every `CalculationOutcome` update in 4D-3 goes through
`full_clean()` before `save()`. The `AssessmentSnapshot.clean()` defect (a guard that
is never invoked) must not recur.

**No user-input trust.** The population pass reads from governed FDA data and frozen
formulation-version fields only. No client-supplied value is used as a calculation input
during the automatic population pass.

---

## 11. Open Questions Register (summary)

See `docs/MILESTONE_4D_3_SCOPE_REGISTER.md` for the full register with decision
options.

| # | Question | Where it matters |
|---|---|---|
| OQ-1 | `ChecklistAnswerSource` as functions vs. class | §4b; testability |
| OQ-2 | Normative JSON schema for `calculation_binding` | §4c; implementation prerequisite |
| OQ-3 | Cascade recalculation in-transaction vs. post-commit | §4d; correctness vs. performance |
| OQ-4 | Snapshot-first vs. live-first for `AssessmentSnapshot` population | §6; reproducibility guarantee |

All four must be resolved and documented before a 4D-3 implementation specification
is written. None may be silently resolved by the implementation branch.

---

## 12. What this Discovery Document Explicitly Does Not Do

- Implement any population pass, calculation service call, or applicability evaluator.
- Create migrations, new models, or new Django apps.
- Modify `iid_assessment`, `fda_data`, `formulations`, or `documents` in any way.
- Specify the exact `calculation_binding` JSON schema (deferred to the implementation
  spec after OQ-2 is resolved).
- Provide a worked example end-to-end (that belongs in the implementation spec's test
  strategy, using synthetic data only).
- Make any claim about which real IIG checklist templates will be shipped (deferred to
  the 4D regulatory-content gate, per the approved design).
- Produce a final implementation specification. This is a **discovery gate only**.

---

## 13. Gate Status

**Discovery: IN PROGRESS. Open questions identified. Not yet ready for implementation specification.**

All four open questions (§11) must be resolved before a 4D-3 implementation spec may
be written. Resolution requires a human reviewer with domain authority to decide between
the options documented in this discovery and in `docs/MILESTONE_4D_3_SCOPE_REGISTER.md`.

**Ready for design review: YES (this document)**
**Ready to finalize implementation specification: NO (OQ-1 through OQ-4 unresolved)**
**Ready to implement: NO**
