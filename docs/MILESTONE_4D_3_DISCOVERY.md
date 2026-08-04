# Milestone 4D-3 Discovery — Draft-Answer Generation, FDA-Derived Population, and Calculation

**Status: DISCOVERY COMPLETE. Open questions resolved. Pending second adversarial review before implementation specification.**

**Branch:** `regx/feat/milestone-4d-3-discovery`
**Base SHA:** `c0adef4448153368c5bb280219c154f60be052f1` (Milestone 4D-2 merge)
**Authoritative inputs:**
- `docs/MILESTONE_4D_DISCOVERY.md` — overarching 4D design (all five open questions resolved)
- `docs/MILESTONE_4D_2_DISCOVERY.md §1` — canonical 4D-3 scope definition
- `docs/MILESTONE_4D_2_IMPLEMENTATION_SPEC.md §2` — 4D-3 items explicitly out of scope for 4D-2
- `docs/IID_CALCULATION_RULES.md` — six calculation formulas, `CalculationResult` dataclass, `CalculationStatus`

**Adversarial review note:** The overarching 4D design document (`MILESTONE_4D_DISCOVERY.md`)
uses `{"all": [...]}` / `{"any": [...]}` composite node examples in some sections. Those
examples do not match the runtime contract. The actual grammar implemented in
`backend/iig_checklist/applicability.py` is authoritative: composite nodes use
`{"operator": "all"|"any", "conditions": [...]}` and leaf nodes use
`{"field": ..., "op": ..., "value": ...}`. Where this document cites the 4D design,
the grammar described here governs over any conflicting example in the 4D design document.

This document is the discovery gate for Milestone 4D-3. It determines the
actual approved scope from the repository evidence above, surveys the existing
domain to identify what 4D-3 must build on and what it must not touch, and
records the design decisions that must be reflected in the 4D-3 implementation
specification.

No implementation code is produced here. No migration is created. No existing
runtime behavior is modified.

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
> `calculation_binding_identifier` entry in the registry depends on it. The moment
> `submit_review` succeeds, every response is locked.

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
   creation with `status = "data_required"` by 4D-2's `create_execution()`).

3. **In-draft recalculation** — when `enter_response()` writes a `USER_REQUIRED` or
   `EVIDENCE_DERIVED` answer on a `draft` execution, cascade-recompute every
   `SYSTEM_CALCULATED` question that depends on the updated answer via the
   `CALCULATION_BINDING_REGISTRY` (resolved from `ChecklistQuestion.calculation_binding_identifier`).

4. **`source_assessment_snapshot_public_id` population** — where a `SYSTEM_CALCULATED`
   question's answer is derived from a live `run_preview()` call, freeze the result as
   an `AssessmentSnapshot` and set `CalculationOutcome.source_assessment_snapshot_public_id`
   to that snapshot's `public_id` (OQ-4 resolved: live-first; see §6).

5. **No new calculation formulas** — all six from `iid_assessment.calculations` are
   reused unmodified. No formula logic is duplicated or replaced.

6. **Frontend: draft population display** — show computed/pre-filled answers to the
   user in the execution detail UI, with provenance labels distinguishing
   `FDA_DERIVED_DEFAULT` values from `USER_REQUIRED` ones.

7. **Status translation layer** — a governed translation from `iid_assessment.calculations.CalculationStatus`
   engine result strings to `iig_checklist.enums.CalculationStatus` stored values,
   required because `CalculationOutcome.status` uses the `iig_checklist` enum (see §4e).

---

## 2. What 4D-3 Explicitly Does NOT Include

These items are confirmed deferred to later milestones by the approved design:

- Override/deviation workflow — **4D-4**
- Controlled JSON/CSV export — **4D-4**
- `reviewer_conclusion_note` / reviewer conclusion routing — **already delivered in 4D-2**
- Per-question `EVIDENCE_DERIVED` attachment-confirmation flow — **4D-4**
- PDF/Word export — explicitly deferred beyond 4D
- Real regulatory checklist content — deferred to a separate regulatory-content gate
- Promotion of `_csv_safe_cell()` to `common` — 4D-4
- Electronic signatures, 21 CFR Part 11 compliance — not in scope for any 4D stage
- Asynchronous calculation execution — the `CalculationStatus.CALCULATING` value is
  reserved for future async work; 4D-3's synchronous population pass never sets it
- New database model or migration for calculation binding — the approved approach uses
  `ChecklistQuestion.calculation_binding_identifier` (an existing `CharField`) as a
  registry key; no new field or migration is introduced (see §4c)
- Arbitrary formula builder — tenant users cannot author executable calculation logic
- Manual override / deviation from calculated values — 4D-4

---

## 3. Current Architecture Relevant to 4D-3

### 3a. Execution and response infrastructure (4D-2, CLOSED)

The following models, services, and infrastructure are in `regx-main` and must not be
modified by 4D-3 beyond the targeted additions described in §4–§7:

- `ChecklistExecution` — 7-status lifecycle; `create_execution()` creates response rows
  eagerly with `raw_value = None` and `CalculationOutcome` rows with
  `CalculationOutcome.status = "data_required"` (the stored value of
  `iig_checklist.enums.CalculationStatus.DATA_REQUIRED`) for every `SYSTEM_CALCULATED`
  question. 4D-3 updates these from `"data_required"` to `"complete"` or `"error"`.
- `ChecklistResponse` — per-question answer row; `data_source_type_snapshot` frozen at
  creation; `full_clean()` enforced at every save.
- `CalculationOutcome` — placeholder created in 4D-2 with:
  - `status = "data_required"` (stored string; `iig_checklist.enums.CalculationStatus`)
  - `value = None`
  - `inputs = {}`
  - `input_provenance = {}`
  4D-3 populates these with real translated values. See §4e for the translation spec.
- `enter_response()` — accepts `USER_REQUIRED`/`EVIDENCE_DERIVED` answers; must be
  extended (not replaced) to trigger recalculation after a successful write.
- `ChecklistQuestion.calculation_binding_identifier` — an existing `CharField(max_length=100,
  blank=True)` on each `SYSTEM_CALCULATED` question. Stores a short, governed registry
  key string (e.g. `"percentage_w_w"`) that the population pass resolves against the
  server-side `CALCULATION_BINDING_REGISTRY`. It is **not** a `JSONField` and does **not**
  store a JSON calculation schema. No migration is required. See §4c for the registry
  design.
- `applicability.py` — structured, allow-listed applicability rule validator (4D-1
  delivery). Validates `condition_json` trees using the grammar:
  - Composite: `{"operator": "all"|"any", "conditions": [...]}`
  - Leaf: `{"field": ..., "op": ..., "value": ...}`
  The **runtime evaluator** (evaluating a validated tree against a live context) is not
  yet implemented — 4D-3 implements it. See §5.

### 3b. `iid_assessment` services (read-only, 4D-3 consumers)

All of the following are existing, shipped, unmodified services. 4D-3 calls them;
4D-3 does not alter them.

- `iid_assessment.assess.run_preview(*, formulation_component, active_release)` — runs
  the full matching + calculation pipeline and returns a `PreviewResult`. Used as the
  live-first source for `SYSTEM_CALCULATED` answers (OQ-4 resolved; see §6).
- `iid_assessment.matching.find_iid_candidates(...)` — IID precedent-match lookup.
- `iid_assessment.calculations.*` — six pure functions returning `CalculationResult`
  dataclass instances. 4D-3 passes `CalculationResult` fields through the translation
  layer (§4e) before writing to `CalculationOutcome`. The engine's own `CalculationStatus`
  strings are never stored directly in `CalculationOutcome.status`.
- `iid_assessment.models.AssessmentSnapshot` — immutable per-component snapshot; set as
  `CalculationOutcome.source_assessment_snapshot_public_id` when a live `run_preview()`
  result is frozen.

**Two `CalculationStatus` namespaces — critical distinction:**

| Namespace | Class | Values | Where used |
|---|---|---|---|
| Engine | `iid_assessment.calculations.CalculationStatus` | `"OK"`, `"ROUTE_MISMATCH"`, `"INGREDIENT_UNRESOLVED"`, `"UNIT_MISMATCH"`, `"FDA_VALUE_UNAVAILABLE"`, `"DATA_REQUIRED"`, `"NOT_COMPARABLE"`, `"REGULATORY_REVIEW_REQUIRED"`, etc. | `CalculationResult.status` (in memory only) |
| Model | `iig_checklist.enums.CalculationStatus` | `"data_required"`, `"calculating"`, `"complete"`, `"error"` | `CalculationOutcome.status` (stored in DB, validated by `full_clean()`) |

Engine status strings must never be written directly to `CalculationOutcome.status`.
The translation layer (§4e) is the only path between the two. See §4e for the exhaustive
mapping.

### 3c. `fda_data` services (read-only, 4D-3 consumers)

- `fda_data.substance_matching.resolve_substance_identity(normalized_name)` — resolves a
  substance name to an approved `SubstanceSynonymMapping` or direct `IIDIngredient` match.
  Used for `FDA_DERIVED_DEFAULT` identity questions.
- `IIDPrecedentRecord`, `IIDIngredient`, `OrangeBookProduct` — read-only sources for
  `FDA_DERIVED_DEFAULT` values. 4D-3 must never write to these tables.

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
`condition_json` tree and an execution-context dict, evaluates the tree, and returns the
`ApplicabilityOutcome` configured on the `ApplicabilityRule` row (`APPLICABLE`,
`NOT_APPLICABLE`, or `REVIEW_REQUIRED`). The evaluator does not return a plain boolean;
it returns the configured branch outcome from `ApplicabilityRule.outcome_if_true` or
`ApplicabilityRule.outcome_if_false` based on the evaluated condition. See §5.

---

## 4. Population Pass Design

The approved design specifies one pass at execution creation (§10 of
`MILESTONE_4D_DISCOVERY.md`) that:

1. Calls `FDA_DERIVED_DEFAULT` resolvers for every applicable question of that
   classification.
2. Calls calculation functions for every applicable `SYSTEM_CALCULATED` question whose
   upstream inputs are already present.

### 4a. Population sequencing

The population pass at execution creation runs in this deterministic order within a
single `transaction.atomic()` block:

1. Create the `ChecklistExecution` and pre-create all applicable `ChecklistResponse`
   and `CalculationOutcome` rows (4D-2 behavior; unchanged).
2. Assemble the applicability context dict from `FormulationVersion` fields (see §5a).
3. For each question in the version (in defined display order):
   - Evaluate the question's `ApplicabilityRule.condition_json`, if any.
   - If the outcome is `NOT_APPLICABLE`: mark `ChecklistResponse.is_not_applicable = True`,
     set `not_applicable_reason` from `ApplicabilityRule.reason_code`, skip further
     population for this question.
   - If the outcome is `REVIEW_REQUIRED`: leave the response in its initial state and mark
     it as requiring governed review before population can proceed (see §5c).
   - If the outcome is `APPLICABLE` (or no rule): continue to step 4.
4. Populate all `FDA_DERIVED_DEFAULT` questions in the version (all sections, all
   applicable questions) using the resolver functions (§4b).
5. Compute all `SYSTEM_CALCULATED` questions whose upstream inputs are now non-null
   (from just-populated FDA-derived values or pre-existing `FormulationVersion` fields)
   using the registry (§4c) and translation layer (§4e). Questions with missing upstream
   inputs remain at `status = "data_required"`.
6. For each `CalculationOutcome` write: translate engine result → model status (§4e),
   call `full_clean()`, then `save()`.
7. After the transaction commits, emit audit events via `transaction.on_commit()`.

Because `FDA_DERIVED_DEFAULT` values never depend on other questions' answers, and
`SYSTEM_CALCULATED` answers depend only on `FDA_DERIVED_DEFAULT`, `USER_REQUIRED`, and
`EVIDENCE_DERIVED` inputs (never on `REVIEWER_CONFIRMED`), this ordering is deterministic
and does not require iterative re-runs.

**Non-overwrite rules:**
- `USER_REQUIRED` response values entered by a user must never be overwritten by the
  population pass.
- `REVIEWER_CONCLUSION` responses must never be touched by the population pass.
- `APPROVAL_METADATA` responses must never be populated by this pass.
- `FDA_DERIVED_DEFAULT` draft values written by the population pass may only be
  replaced according to an explicit governed recalculation rule (not automatic).
- Executions in `submitted_for_review`, `approved`, `rejected`, `cancelled`, or
  `superseded` status must never be recalculated. Only `draft` and `returned` are
  valid recalculable states.
- Terminal executions (`approved`, `rejected`, `cancelled`, `superseded`) must never be
  automatically recalculated when source data changes; a human must explicitly act.

**Idempotency:**
- Re-running the population pass with unchanged inputs (same `FormulationVersion`,
  same FDA source, same `AssessmentSnapshot`) must produce no duplicate history rows.
- Unchanged `CalculationOutcome` values must not increment `ChecklistResponse.version`.
- Unchanged outcomes must not emit misleading update audit events.
- Duplicate `CalculationOutcome` rows are prevented by the existing `UniqueConstraint`
  on `(response,)`.
- Source snapshot and provenance must remain stable for identical inputs.

### 4b. `ChecklistAnswerSource` resolver functions (OQ-1 resolved)

**OQ-1 is resolved: use module-level resolver functions.**

Rationale: functions are sufficient for deterministic source resolution; dependencies
can be passed explicitly; this matches existing service-layer conventions; it avoids
unnecessary state and lifecycle complexity.

The resolver layer lives in a new `iig_checklist/answer_sources.py` module:

```
resolve_fda_derived(question, formulation_version, context) → resolved_value | None
resolve_identity_match(question, formulation_version) → IIDIngredient | None
```

- The mapping from question code to resolver is a small, explicit dispatch dict, not
  dynamic reflection.
- The resolver for identity-match questions calls `resolve_substance_identity()`.
- The resolver for precedent-route/dosage-form questions calls `find_iid_candidates()`.
- The resolver for formulation fields reads directly from `FormulationVersion` /
  `FormulationComponent` model fields.
- No `eval`, no `exec`, no dynamic attribute lookup on untrusted input.

### 4c. `CALCULATION_BINDING_REGISTRY` and `calculation_binding_identifier` (OQ-2 resolved)

**OQ-2 is resolved: use `ChecklistQuestion.calculation_binding_identifier` as a short,
governed registry key. No migration is required.**

`ChecklistQuestion.calculation_binding_identifier` is an existing
`CharField(max_length=100, blank=True)` in `backend/iig_checklist/models.py`. It stores
a short, governed identifier string (e.g. `"percentage_w_w"`) that the population pass
resolves against the server-side `CALCULATION_BINDING_REGISTRY`. It is not a `JSONField`.
It does not store a JSON calculation schema. No new field and no migration are required.

**Registry design (discovery-level; exact Python shape is implementation-spec scope):**

The `CALCULATION_BINDING_REGISTRY` is a Python dict defined in server-side code
(not in the database). Each entry maps a short identifier to a calculation configuration:

```
CALCULATION_BINDING_REGISTRY = {
    "percentage_w_w": {
        "function": calculate_percentage_w_w,         # direct function reference
        "input_resolvers": {                           # keyed by function kwarg name
            "quantity_per_unit_grams": ...,            # resolver: question code or formulation field
            "total_dosage_unit_weight_grams": ...,     # resolver: formulation field
        },
        "dependencies": ["Q_QUANTITY_PER_UNIT"],      # question codes this calc depends on
        "formula_version": "1.0.0",
        "output_unit": "percent_w_w",
    },
    ...
}
```

This is a discovery-level example only. The implementation specification must define
the exact Python shape of the registry.

**Registry design requirements:**

- **Identifier format:** short ASCII slug, lowercase, underscores only, max 100 characters
  (compatible with `CharField(max_length=100)`).
- **Allow-list enforcement:** only identifiers present in `CALCULATION_BINDING_REGISTRY`
  are valid. An unknown identifier must be rejected at `ChecklistVersion` activation time
  with a structured error.
- **Unknown identifier handling:** an unknown identifier encountered at calculation time
  (e.g. registry out of sync with a stored record) must fail closed — it must not silently
  produce a success outcome. It must set `CalculationOutcome.status = "error"` and
  `reason_code = "UNKNOWN_REGISTRY_IDENTIFIER"`.
- **Function mapping:** each registry entry holds a direct Python function reference (one
  of the six approved `iid_assessment.calculations` functions). No `getattr` from
  untrusted input. No dynamic import. No `eval`. No arbitrary expression evaluation.
- **Input resolver mapping:** each registry entry declares how to gather the function's
  keyword arguments — by question code (read from `ChecklistResponse.raw_value`) or from
  a named `FormulationVersion` / `FormulationComponent` field.
- **Dependency declarations:** each registry entry declares which `ChecklistQuestion`
  codes supply its inputs. This is used to build the dependency graph for recalculation
  cascade ordering and for activation-time cycle validation.
- **Formula version:** each registry entry declares the `formula_version` string to store
  in `CalculationOutcome.formula_version` (must match `FORMULA_VERSION` from
  `iid_assessment.calculations`).
- **Deterministic ordering:** the population pass processes `SYSTEM_CALCULATED` questions
  in topological order derived from the dependency graph. Where no dependency exists
  between two questions, alphabetical `code` order is used as a tiebreaker for stability.
- **Activation-time validation:** when a `ChecklistVersion` is activated, the system
  must verify:
  - Every `SYSTEM_CALCULATED` question's `calculation_binding_identifier` resolves to a
    registry entry.
  - Every declared dependency (question code) exists in the same `ChecklistVersion`.
  - No cross-version references.
  - No cycles in the dependency graph (DAG validation; see §14).
- **No tenant-provided executable logic:** tenant users cannot add, modify, or inject
  entries into the registry. Registry entries are defined in server-side version-controlled
  code and deployed as part of the application.

### 4d. Recalculation on `enter_response()` (OQ-3 resolved)

**OQ-3 is resolved: synchronous recalculation in the same database transaction.**

Rationale: the six calculation functions are pure, fast, and Decimal-only (no I/O, no
external calls). Transaction duration is not a concern. Consistency is paramount: a reader
must never see a `ChecklistExecution` where a `USER_REQUIRED` answer has been updated
but the dependent `SYSTEM_CALCULATED` outcomes still reflect prior inputs.

Per the approved §8b rule: while `status = draft`, any `USER_REQUIRED` or
`EVIDENCE_DERIVED` answer update triggers recomputation of every dependent
`SYSTEM_CALCULATED` question. 4D-3 must extend `enter_response()` to:

1. Acquire `select_for_update()` on the `ChecklistExecution` row before reading any
   `ChecklistResponse` values used as calculation inputs. This serializes concurrent
   recalculations on the same execution.
2. Write and validate the triggering `USER_REQUIRED`/`EVIDENCE_DERIVED` response.
3. Using the `CALCULATION_BINDING_REGISTRY`, identify all `SYSTEM_CALCULATED` questions
   in the same execution whose declared dependencies include the just-updated question code.
4. Process affected questions in topological dependency order (stable, matching the
   population-pass order).
5. Re-run the calculation for each affected question using the same resolver functions
   as the population pass.
6. For each result: translate engine status → model status (§4e), call `full_clean()`,
   then update the `CalculationOutcome` row in place.
7. All writes (response + all affected `CalculationOutcome` rows) must be inside a single
   `transaction.atomic()` block. If any step raises an exception, the entire block rolls
   back — no partial calculation results are persisted.
8. After the transaction commits, emit audit events via `transaction.on_commit()`.

**Lock order** (must be respected to prevent deadlocks):
1. `ChecklistExecution` (via `select_for_update()`)
2. Affected `ChecklistResponse` rows (in stable pk order)
3. `CalculationOutcome` rows (in stable pk order)

**Bounded complexity:**
- Maximum number of `SYSTEM_CALCULATED` questions affected by a single recalculation
  cascade must be bounded at activation time via the dependency graph.
- A single `enter_response()` call may not trigger unbounded recalculation. The maximum
  depth and maximum node count of the dependency graph must be specified in the
  implementation specification.

### 4e. `CalculationStatus` Translation Layer (new requirement)

There are two distinct `CalculationStatus` namespaces that must never be conflated:

**Engine namespace** (`iid_assessment.calculations.CalculationStatus`) — returned in
`CalculationResult.status`. These are the raw engine result strings. They are in-memory
values only and must never be stored directly in `CalculationOutcome.status`.

**Model namespace** (`iig_checklist.enums.CalculationStatus`) — the `choices` for
`CalculationOutcome.status`. Django's `full_clean()` enforces that only these four
stored values are valid: `"data_required"`, `"calculating"`, `"complete"`, `"error"`.

The translation layer maps engine results to model values. The mapping is exhaustive
and fails closed: an unknown engine status must never map to `"complete"`.

**Canonical translation table:**

| Engine result (`CalculationResult.status`) | Stored `CalculationOutcome.status` | Stored `CalculationOutcome.reason_code` | Notes |
|---|---|---|---|
| `"OK"` | `"complete"` | `""` (blank) | Success path |
| `"DATA_REQUIRED"` | `"data_required"` | `"DATA_REQUIRED"` | Upstream input missing |
| `"INGREDIENT_UNRESOLVED"` | `"error"` | `"INGREDIENT_UNRESOLVED"` | No approved substance mapping |
| `"ROUTE_MISMATCH"` | `"error"` | `"ROUTE_MISMATCH"` | Route does not match IID precedent |
| `"DOSAGE_FORM_MISMATCH"` | `"error"` | `"DOSAGE_FORM_MISMATCH"` | Dosage form does not match |
| `"UNIT_MISMATCH"` | `"error"` | `"UNIT_MISMATCH"` | Unit conversion failed |
| `"FDA_VALUE_UNAVAILABLE"` | `"error"` | `"FDA_VALUE_UNAVAILABLE"` | IID value null/invalid |
| `"NOT_COMPARABLE"` | `"error"` | `"NOT_COMPARABLE"` | Inputs outside comparison range |
| `"REGULATORY_REVIEW_REQUIRED"` | `"error"` | `"REGULATORY_REVIEW_REQUIRED"` | Release superseded/inactive |
| unknown string | `"error"` | `"UNKNOWN_ENGINE_STATUS"` | Fail-closed; never maps to complete |

**Alias resolution:** the engine defines several aliases that map to a single canonical
string. The canonical string (not the Python alias name) is what appears in
`CalculationResult.status` and what the translation table above operates on:

| Python alias | Canonical string stored in `reason_code` |
|---|---|
| `CalculationStatus.UNIT_CONVERSION_FAILED` | `"UNIT_MISMATCH"` |
| `CalculationStatus.IID_VALUE_MISSING` | `"FDA_VALUE_UNAVAILABLE"` |
| `CalculationStatus.IID_VALUE_INVALID` | `"FDA_VALUE_UNAVAILABLE"` |
| `CalculationStatus.PROPOSED_VALUE_MISSING` | `"DATA_REQUIRED"` |
| `CalculationStatus.MAX_DAILY_UNITS_MISSING` | `"DATA_REQUIRED"` |
| `CalculationStatus.BASIS_UNCLEAR` | `"NOT_COMPARABLE"` |
| `CalculationStatus.RELEASE_NOT_ACTIVE` | `"REGULATORY_REVIEW_REQUIRED"` |
| `CalculationStatus.RECORD_SUPERSEDED` | `"REGULATORY_REVIEW_REQUIRED"` |

**Translation requirements:**
- Engine status must never be copied directly into `CalculationOutcome.status`.
- Every translated model value must pass `full_clean()` without raising `ValidationError`.
- Unknown engine status fails closed — maps to `"error"`, never to `"complete"`.
- The `"calculating"` stored value is reserved for future asynchronous execution. The
  synchronous 4D-3 population pass must never set `CalculationOutcome.status = "calculating"`.
- When `status = "error"`, `value` must be `None` (no partial value stored).
- When `status = "data_required"`, `value` must be `None`.
- When `status = "complete"`, `value` and `unit` may be set.
- The translation function must be exhaustive and unit-tested for every engine status
  string including all aliases.

### 4f. `generated_at` type handling

`CalculationResult.generated_at` (returned by all six calculation functions) is a `str`
in ISO 8601 format (produced by `datetime.now(tz=UTC).isoformat()`).

`CalculationOutcome.generated_at` is a Django `DateTimeField(null=True, blank=True)`.

The implementation must:

- Parse the ISO 8601 string into a timezone-aware `datetime` object before assigning
  to `CalculationOutcome.generated_at`.
- Reject naive (tz-unaware) timestamps — the calculation functions always produce UTC,
  so any naive timestamp indicates a code defect.
- Reject malformed or empty strings — fall back to `None` with an appropriate logged
  warning (not an exception that aborts the population pass for a timestamp-only failure).
- Never store an arbitrary client-supplied timestamp; only server-generated values from
  the calculation functions are accepted.
- Unit-test timezone-aware parsing and malformed-value behavior explicitly.

---

## 5. Applicability Runtime Evaluator Design

### 5a. Context object

The runtime evaluator needs a context dict keyed by the field registry's names
(`FIELD_REGISTRY_VERSION = 1`):

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

This context is assembled once per population pass from the `FormulationVersion` fields
and the `FDA_DERIVED_DEFAULT` resolution results. It is an in-memory dict, never stored
in the database. A missing field in the context is treated as absent (`None` for existence
checks; absent for comparison checks).

### 5b. Evaluator function and grammar

The evaluator is a pure function added to `backend/iig_checklist/applicability.py`:

```python
def evaluate_applicability(rule: ApplicabilityRule, context: dict) -> str:
    """Evaluates rule.condition_json against context and returns the configured
    branch outcome string (one of ApplicabilityOutcome values).
    condition_json must have already been validated by validate_condition_json().
    No eval, no exec, no dynamic attribute access. Pure function; no side effects."""
```

The function:
1. Evaluates `rule.condition_json` against `context` using the operator dispatch table
   (same operators as the validator: `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists`,
   `gt`, `gte`, `lt`, `lte`; composed via `all` AND `any`).
2. If the condition evaluates to `True`, returns `rule.outcome_if_true`.
3. If the condition evaluates to `False`, returns `rule.outcome_if_false`.

The return value is one of the `ApplicabilityOutcome` choices:
- `"applicable"` — question is applicable; population continues normally.
- `"not_applicable"` — question is not applicable; `ChecklistResponse.is_not_applicable`
  is set to `True`.
- `"review_required"` — question requires governed review before population proceeds;
  neither applicable nor not-applicable is set automatically.

**Grammar — authoritative node shapes (from `applicability.py`):**

The grammar implemented in `backend/iig_checklist/applicability.py` is the authoritative
contract. The older `{"all": [...]}` / `{"any": [...]}` composite examples that appear
in some sections of the overarching 4D design document are not the runtime contract.

- **Composite node:** `{"operator": "all"|"any", "conditions": [<node>, ...]}`
- **Leaf node:** `{"field": "<field_name>", "op": "<operator>", "value": <value>}`
  (no `"value"` key for `exists` / `not_exists` operators)

No other shapes are valid. The evaluator must mirror this grammar exactly.

### 5c. Branch outcome consumption

**`APPLICABLE`** (`outcome == "applicable"`):
- `ChecklistResponse.is_not_applicable` remains `False`.
- No `not_applicable_reason` is stored.
- Population proceeds normally for this question.

**`NOT_APPLICABLE`** (`outcome == "not_applicable"`):
- `ChecklistResponse.is_not_applicable = True`.
- `ChecklistResponse.not_applicable_reason` is set to `ApplicabilityRule.reason_code`
  (the structured, governed reason stored on the rule row — not `condition_checksum`,
  which does not exist as a field, and not free text).
- If the response already has a user-entered `raw_value`, the implementation must not
  silently destroy it. Any transition affecting stored regulated data must create a
  governed history row (consistent with the existing `ChecklistResponseHistory` pattern).
- Population of this question's `raw_value` is skipped; it remains `None`.

**`REVIEW_REQUIRED`** (`outcome == "review_required"`):
- The response must not be silently marked applicable or not-applicable.
- Automatic population or calculation for this response must not proceed.
- The execution remains editable but the response must be visibly flagged as requiring
  regulated review before submission.
- The exact persisted representation of `REVIEW_REQUIRED` state (which existing
  `ChecklistResponse` fields carry this signal, and whether any new field or model is
  needed) must be resolved in the final implementation specification. No new model or
  migration may be introduced without explicit authorization. The implementation spec must
  use existing fields where possible.

### 5d. `NOT_APPLICABLE` vs. `DATA_REQUIRED` distinction

These are two distinct `ChecklistResponse` states and must never be conflated:

- **`NOT_APPLICABLE`:** `is_not_applicable = True`, `not_applicable_reason` set to the
  governed rule `reason_code`. The question is inapplicable for this product/route.
- **`DATA_REQUIRED`:** `is_not_applicable = False`, `raw_value = None`,
  `CalculationOutcome.status = "data_required"`. The question is applicable, but
  upstream inputs are not yet present. The user must enter them.

A `SYSTEM_CALCULATED` question whose applicability rule evaluates to `APPLICABLE` but
whose upstream inputs are still unresolved remains in `DATA_REQUIRED` state, not
`NOT_APPLICABLE` state.

---

## 6. `source_assessment_snapshot_public_id` Population (OQ-4 resolved)

**OQ-4 is resolved: live-first source resolution.**

At population time, the system always calls `run_preview()` against the currently active
FDA release. The result is frozen as an `AssessmentSnapshot` for this
`(FormulationComponent, active_release)` tuple (reusing an existing exact match if one
exists; creating a new one otherwise). `CalculationOutcome.source_assessment_snapshot_public_id`
is set to the resulting snapshot's `public_id` — unconditionally.

Rationale: reproducibility must be unconditional. Staleness-avoidance code (checking
whether an existing snapshot references the current active release) is a maintenance
liability and the source of the T-04 / T-08 risks. Using live-first eliminates the
staleness question for new executions and sets `source_assessment_snapshot_public_id`
unconditionally.

**Snapshot lookup must filter by tenant** (addresses adversarial review T-08): any
`AssessmentSnapshot` lookup must include `tenant = execution.tenant` as a filter
condition. A snapshot from another tenant must never be used as the source for a
calculation.

**Historical executions:** once an execution has been submitted, approved, or otherwise
moved to a terminal or locked status, the `CalculationOutcome.source_assessment_snapshot_public_id`
must not be updated even if the underlying FDA release changes. The snapshot reference
at lock time is the authoritative provenance record.

---

## 7. No New Models or Migrations

4D-3 does not introduce new database models or migrations. All required columns exist in
4D-2 and are consumed as follows:

- `CalculationOutcome` — all fields present; `value`, `inputs`, `input_provenance`,
  `source_assessment_snapshot_public_id`, `formula_version`, `status`, `reason_code`,
  `generated_at` are all already defined. 4D-3 populates them with real translated values.
- `ChecklistResponse.raw_value`, `entered_by`, `entered_at` — already defined;
  4D-3 writes non-null values for `FDA_DERIVED_DEFAULT` questions.
- `ChecklistResponse.system_derived_value` — already defined; used in 4D-4 for
  override tracking, not yet populated in 4D-3.
- `ChecklistQuestion.calculation_binding_identifier` — already a `CharField(max_length=100)`;
  the registry-key approach (§4c) requires no change to this field and no migration.

The applicability runtime evaluator requires no configuration or cache table — it is a
pure function operating on an in-memory context dict and the already-stored `condition_json`.

The `CALCULATION_BINDING_REGISTRY` is server-side Python code, not a database table.

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
- **`SYSTEM_CALCULATED` answers:** display `CalculationOutcome.value` when
  `CalculationOutcome.status = "complete"`. When `status = "data_required"` or
  `status = "error"`, display the `reason_code` string (not a fabricated numeric value,
  not zero, not blank). The frontend must use the model status values (`"complete"`,
  `"data_required"`, `"error"`) from the API response — it must not interpret or
  re-map the raw engine `reason_code` string.
- **`USER_REQUIRED` answers with `prefill_source`:** show the pre-filled value as
  editable; display a "Pre-filled from formulation" hint rather than a provenance label.
- **Recalculation feedback:** when a user edits a `USER_REQUIRED` field whose change
  triggers recalculation, the affected `SYSTEM_CALCULATED` fields update after the
  PATCH completes (reload from server, no client-side formula re-evaluation).
- **No formula logic in the frontend** — the frontend is a display layer only; all
  calculation logic lives in the backend. No frontend code may implement any of the six
  calculation formulas.
- **Calculation outcome display** — the frontend consumes the read-only `CalculationOutcome`
  serialized representation described in §15. It must never issue a PATCH or PUT to
  `CalculationOutcome` rows directly.

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

**No fabricated values.** A blocked calculation (`CalculationOutcome.status = "error"` or
`"data_required"`) is written with `value = None` and a non-empty `reason_code`. The
system never stores `0` or an empty string as a stand-in for "unknown." The
`reason_code` field carries the exact engine status string for auditability.

**Status translation is the controlled bridge.** Engine status strings from
`iid_assessment.calculations.CalculationStatus` must never bypass the translation layer
described in §4e and be written directly to `CalculationOutcome.status`. The translation
function is the single point of truth for this mapping.

**Provenance labeling.** `FDA_DERIVED_DEFAULT` answers written by the population pass
must set `entered_by = None` and emit a distinct audit event
(`iig_checklist.response.fda_populated`) rather than the ordinary `response.entered`
event, so the audit trail distinguishes system-generated draft values from user-entered
ones.

**`full_clean()` enforcement.** Every `CalculationOutcome` update in 4D-3 goes through
`full_clean()` before `save()`. The `AssessmentSnapshot.clean()` defect (a guard that
is never invoked because `full_clean()` was not called) must not recur.

**No user-input trust in calculation inputs.** The population pass reads from governed
FDA data and frozen formulation-version fields only. No client-supplied value is used as
a calculation input during the automatic population pass.

**Registry integrity.** The `CALCULATION_BINDING_REGISTRY` is defined in server-side
version-controlled code. Tenant users cannot add, modify, or inject registry entries.
Runtime registry lookups use a static dict — no `getattr` from untrusted input, no
`eval`, no dynamic import.

**Audit events after commit only.** All `iig_checklist` audit events emitted by the
population or recalculation path must be dispatched via `transaction.on_commit()` to
prevent partially-committed audit state.

---

## 11. Open Questions Register — All Resolved

All four open questions have been resolved as part of the adversarial review remediation.
No open questions remain before the implementation specification may be written.

| # | Question | Resolution | Section |
|---|---|---|---|
| OQ-1 | `ChecklistAnswerSource` as functions vs. class | **RESOLVED: module-level functions** | §4b |
| OQ-2 | Normative JSON schema for `calculation_binding` | **RESOLVED: `calculation_binding_identifier` is a registry key; no JSON schema; no migration** | §4c |
| OQ-3 | Cascade recalculation in-transaction vs. post-commit | **RESOLVED: synchronous, same-transaction, with `select_for_update()` on execution** | §4d |
| OQ-4 | Snapshot-first vs. live-first for `AssessmentSnapshot` | **RESOLVED: live-first; snapshot always created at population time** | §6 |

---

## 12. What this Discovery Document Explicitly Does Not Do

- Implement any population pass, calculation service call, registry, or applicability evaluator.
- Create migrations, new models, or new Django apps.
- Modify `iid_assessment`, `fda_data`, `formulations`, or `documents` in any way.
- Define the exact Python shape of `CALCULATION_BINDING_REGISTRY` (that is implementation-spec
  scope; the design requirements are defined in §4c).
- Provide a worked example end-to-end (that belongs in the implementation spec's test
  strategy, using synthetic data only).
- Make any claim about which real IIG checklist templates will be shipped (deferred to
  the 4D regulatory-content gate).
- Produce a final implementation specification. This is a **discovery gate only**.
- Resolve the exact persisted representation of `REVIEW_REQUIRED` state (deferred to
  the implementation specification, which must use existing fields where possible and
  must not introduce a new model without authorization).

---

## 13. Gate Status

**Discovery: COMPLETE. All open questions resolved. Pending second adversarial review.**

**Ready for second adversarial review: YES**
**Ready to finalize implementation specification: NO — requires the second adversarial review to pass**
**Ready to implement: NO**

---

## 14. Dependency Graph and Cycle Validation

Acyclicity in the `SYSTEM_CALCULATED` dependency graph is not assumed — it is enforced
by explicit validation at `ChecklistVersion` activation time.

**What is validated at activation:**
1. Every `SYSTEM_CALCULATED` question's `calculation_binding_identifier` resolves to a
   known registry entry.
2. Every registry entry's declared `dependencies` (question codes) exist within the
   same `ChecklistVersion`.
3. No cross-version references exist in any dependency declaration.
4. The dependency graph of all `SYSTEM_CALCULATED` questions forms a directed acyclic
   graph (DAG). A cycle (e.g. question A depends on B, B depends on A) is a configuration
   error that must be rejected at activation with a structured error code.

**Stable topological ordering:** the population pass and recalculation cascade both
process questions in a stable topological order derived from the DAG. Where no
dependency relation exists between two questions, alphabetical `code` order is the
tiebreaker.

**Bounding requirements:**
- Maximum dependency graph depth and maximum affected-node count per single
  `enter_response()` call must be defined in the implementation specification.
- These bounds prevent a single response update from triggering unbounded cascade work.
- Exceeding the bounds at activation must be treated as a configuration error.

**Defensive check at runtime:** even after activation-time validation, the recalculation
loop must include a defensive cycle-detection check (e.g. a visited set) to guard against
registry/activation-check bugs. The maximum number of recalculation iterations per
`enter_response()` call is bounded by the activation-time declared node count.

**If the approved registry disallows `SYSTEM_CALCULATED`-to-`SYSTEM_CALCULATED`
dependencies** (i.e. all `SYSTEM_CALCULATED` questions may only depend on
`FDA_DERIVED_DEFAULT`, `USER_REQUIRED`, or `EVIDENCE_DERIVED` inputs): this constraint
must be enforced explicitly by the activation-time registry validation — not assumed to
be true by the runtime. The defensive cycle check must still be present.

---

## 15. `CalculationOutcome` Serialization Requirements

`CalculationOutcome` rows are surfaced through the existing response-list and response-detail
API as a read-only nested representation. No generic `PATCH`/`PUT` endpoint for
`CalculationOutcome` rows is permitted.

**Required read-only fields in the serialized representation:**

- `public_id` — UUID identifying this `CalculationOutcome` row
- `calculation_name` — the function identifier (from `CalculationOutcome.calculation_name`)
- `formula_version` — e.g. `"1.0.0"` (from `CalculationOutcome.formula_version`)
- `status` — one of `"data_required"`, `"complete"`, `"error"` (never `"calculating"` in 4D-3)
- `value` — `null` when blocked; Decimal string when `status = "complete"`
- `unit` — unit string (may be blank)
- `reason_code` — blank when `status = "complete"`; engine status string when `status = "error"` or `"data_required"`
- `rounding_rule` — from `CalculationOutcome.rounding_rule`
- `generated_at` — ISO 8601 datetime string (null if not yet computed)
- `source_assessment_snapshot_public_id` — UUID or `null`

**Must NOT be exposed:**
- Raw database primary keys
- Internal storage paths
- Registry configuration details (function names, input resolver dicts)
- Cross-tenant metadata
- Arbitrary engine-internal payloads not approved for client consumption

**Frontend requirement:** the frontend must consume this representation through the
centralized DTO mapper. No calculation value may be locally recomputed or overridden
on the client side. No generic calculation `PATCH` endpoint is permitted.
