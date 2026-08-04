# Milestone 4D-3 Test Strategy

**Status: SPECIFICATION REVISED after failed adversarial review. Test gates in §9 (second review) and §10 (third review: C-1, C-2, M-A … M-E). Matrix reconciliation in §11. Pending second adversarial specification review before implementation.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Scope register:** `docs/MILESTONE_4D_3_SCOPE_REGISTER.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`

This document defines the test strategy for Milestone 4D-3. It follows the same layered
approach established in `docs/MILESTONE_4D_1_TEST_STRATEGY.md` and described in
`docs/MILESTONE_4D_2_DISCOVERY.md §19`. All fixtures are synthetic; no real FDA data,
no real client formulation data, and no real regulatory checklist content is used at any
point in this test suite.

**Important:** `CalculationOutcome.status` uses `iig_checklist.enums.CalculationStatus`
(stored values: `"data_required"`, `"calculating"`, `"complete"`, `"error"`). It does
not store engine-level `iid_assessment.calculations.CalculationStatus` strings such as
`"OK"`, `"INGREDIENT_UNRESOLVED"`, etc. Those engine strings appear only in
`CalculationOutcome.reason_code`. All test assertions on `CalculationOutcome.status`
must use the model-layer stored values (lowercase). See §5 for the full mapping.

Test file names and locations are proposed here. Final locations are subject to revision
in the implementation specification.

---

## 1. Guiding Principles

These are inherited from the 4D-1 and 4D-2 test strategies and apply equally to 4D-3:

1. **No automatic safety or regulatory-approval conclusion.** No test may assert that a
   populated or computed answer constitutes an automatic determination of safety, FDA
   approval, or excipient acceptability. The closest any test may assert is a specific
   `CalculationOutcome.status` stored value (`"complete"`, `"error"`, `"data_required"`)
   and a specific `reason_code` string.

2. **No fabricated pass values.** A blocked calculation (`CalculationOutcome.status = "error"`
   or `"data_required"`) must produce `value = None` and a non-empty `reason_code`. No
   test may accept `0`, an empty string, or `"complete"` as a valid representation of a
   blocked calculation.

3. **`full_clean()` must be invoked.** Every `CalculationOutcome.save()` in the
   population and recalculation paths must call `full_clean()` before `save()`. At least
   one test must prove that a direct `save()` without `full_clean()` on an invalid
   `CalculationOutcome` is caught — i.e., that the guard is actually reachable.

4. **Synthetic fixtures only.** No real `IIDIngredient`, `IIDPrecedentRecord`, or
   `SubstanceSynonymMapping` data is committed to the test database. All test cases use
   synthetic names modeled on the paracetamol/acetaminophen worked example from
   `docs/MILESTONE_4D_DISCOVERY.md §19`.

5. **No formula logic in tests.** Tests do not reimplement any of the six calculation
   formulas. They assert the `CalculationOutcome.value` and stored `status` returned by
   the production code, not a client-computed expected result.

6. **Planted failures required.** Every blocked-calculation engine status must have at
   least one test that verifies the correct stored `(status, reason_code)` pair is produced
   and that it is not silently converted to a `"complete"` outcome.

7. **Translation layer coverage.** Every engine status string (including all aliases)
   must have a dedicated unit test verifying the translation mapping. Unknown engine
   status strings must be shown to fail closed to `"error"`.

8. **Status assertions use stored model values.** All test assertions use the lowercase
   stored values from `iig_checklist.enums.CalculationStatus` — never the uppercase
   engine strings. Assertions on `reason_code` use the canonical engine status strings
   that appear after alias resolution (see §5).

---

## 2. Unit / Service Tests

### 2a. `CalculationStatus` translation layer (`test_status_translation.py`)

Location: `backend/iig_checklist/tests/test_status_translation.py`

This is a new test file covering the translation function (S-17) that maps engine result
strings to model stored values. Every engine status string must be covered.

- Engine `"OK"` → stored `status = "complete"`, `reason_code = ""` (blank).
- Engine `"DATA_REQUIRED"` → stored `status = "data_required"`, `reason_code = "DATA_REQUIRED"`.
- Engine `"INGREDIENT_UNRESOLVED"` → stored `status = "error"`, `reason_code = "INGREDIENT_UNRESOLVED"`.
- Engine `"ROUTE_MISMATCH"` → stored `status = "error"`, `reason_code = "ROUTE_MISMATCH"`.
- Engine `"DOSAGE_FORM_MISMATCH"` → stored `status = "error"`, `reason_code = "DOSAGE_FORM_MISMATCH"`.
- Engine `"UNIT_MISMATCH"` → stored `status = "error"`, `reason_code = "UNIT_MISMATCH"`.
- Engine `"FDA_VALUE_UNAVAILABLE"` → stored `status = "error"`, `reason_code = "FDA_VALUE_UNAVAILABLE"`.
- Engine `"NOT_COMPARABLE"` → stored `status = "error"`, `reason_code = "NOT_COMPARABLE"`.
- Engine `"REGULATORY_REVIEW_REQUIRED"` → stored `status = "error"`, `reason_code = "REGULATORY_REVIEW_REQUIRED"`.
- Unknown engine string `"SOME_FUTURE_STATUS"` → stored `status = "error"`, `reason_code = "UNKNOWN_ENGINE_STATUS"`.
  **Unknown status must never produce `status = "complete"`.**
- Alias `CalculationStatus.UNIT_CONVERSION_FAILED` (canonical: `"UNIT_MISMATCH"`) → stored `status = "error"`, `reason_code = "UNIT_MISMATCH"`.
- Alias `CalculationStatus.IID_VALUE_MISSING` (canonical: `"FDA_VALUE_UNAVAILABLE"`) → stored `status = "error"`, `reason_code = "FDA_VALUE_UNAVAILABLE"`.
- Alias `CalculationStatus.IID_VALUE_INVALID` (canonical: `"FDA_VALUE_UNAVAILABLE"`) → stored `status = "error"`, `reason_code = "FDA_VALUE_UNAVAILABLE"`.
- Alias `CalculationStatus.PROPOSED_VALUE_MISSING` (canonical: `"DATA_REQUIRED"`) → stored `status = "data_required"`, `reason_code = "DATA_REQUIRED"`.
- Alias `CalculationStatus.MAX_DAILY_UNITS_MISSING` (canonical: `"DATA_REQUIRED"`) → stored `status = "data_required"`, `reason_code = "DATA_REQUIRED"`.
- Alias `CalculationStatus.BASIS_UNCLEAR` (canonical: `"NOT_COMPARABLE"`) → stored `status = "error"`, `reason_code = "NOT_COMPARABLE"`.
- Alias `CalculationStatus.RELEASE_NOT_ACTIVE` (canonical: `"REGULATORY_REVIEW_REQUIRED"`) → stored `status = "error"`, `reason_code = "REGULATORY_REVIEW_REQUIRED"`.
- Alias `CalculationStatus.RECORD_SUPERSEDED` (canonical: `"REGULATORY_REVIEW_REQUIRED"`) → stored `status = "error"`, `reason_code = "REGULATORY_REVIEW_REQUIRED"`.
- `"calculating"` is never produced by the translation function (reserved for async; not used in 4D-3's synchronous path).
- For all `"error"` and `"data_required"` outcomes: `value` field in the translated result is `None`.
- `full_clean()` on a `CalculationOutcome` with translated `status = "error"` does not raise `ValidationError`.
- `full_clean()` on a `CalculationOutcome` with translated `status = "complete"` does not raise `ValidationError`.
- Direct assignment of an engine string (`"OK"`, `"ROUTE_MISMATCH"`, etc.) to
  `CalculationOutcome.status` followed by `full_clean()` raises `ValidationError` — confirms
  that engine strings cannot bypass the translation layer.

### 2b. Applicability runtime evaluator (`test_applicability_evaluator.py`)

Location: `backend/iig_checklist/tests/test_applicability_evaluator.py`

New tests for the `evaluate_applicability(rule, context)` function (S-06, §5 of discovery
document). The function returns an `ApplicabilityOutcome` value, not a bool.

**Grammar (composite node shape in `applicability.py`):**
- Composite: `{"operator": "all"|"any", "conditions": [...]}`
- Leaf: `{"field": ..., "op": ..., "value": ...}`

- `all`-composite (`{"operator": "all", "conditions": [...]}`) with all conditions true
  and `outcome_if_true = "applicable"` → returns `"applicable"`.
- `all`-composite with one condition false and `outcome_if_false = "not_applicable"` →
  returns `"not_applicable"`.
- `any`-composite with one condition true and `outcome_if_true = "applicable"` →
  returns `"applicable"`.
- `any`-composite with all conditions false and `outcome_if_false = "not_applicable"` →
  returns `"not_applicable"`.
- Rule with `outcome_if_true = "review_required"`: condition true → returns `"review_required"`.
- Rule with `outcome_if_false = "review_required"`: condition false → returns `"review_required"`.
- `eq` on `product.route` matching context value and `outcome_if_true = "applicable"` → `"applicable"`.
- `eq` on `product.route` not matching and `outcome_if_false = "not_applicable"` → `"not_applicable"`.
- `exists` on `iid.match_status` when context value is not `None` → `outcome_if_true`.
- `exists` on `iid.match_status` when context value is `None` → `outcome_if_false`.
- `not_exists` on `iid.has_mde` when context value is `None` → `outcome_if_true`.
- `gt` / `gte` / `lt` / `lte` on a numeric context field — boundary values return correct outcome.
- Field not present in context: treated as absent (None for existence checks).
- Nested composite (depth > 1): `all` containing an `any` → correct evaluation.
- Maximum-depth tree (depth = 5) evaluates correctly.
- Depth-6 tree was already blocked at validation time; evaluator is never called on it.
- `NOT_APPLICABLE` outcome: population pass sets `is_not_applicable = True` and
  `not_applicable_reason = ApplicabilityRule.reason_code` (not `condition_checksum`,
  which does not exist).
- `APPLICABLE` outcome: `is_not_applicable` remains `False`; `not_applicable_reason` not set.
- `REVIEW_REQUIRED` outcome: response is neither marked applicable nor not-applicable;
  population does not proceed for this question; execution remains editable.

### 2c. Population pass — unit tests (`test_population_service.py`)

Location: `backend/iig_checklist/tests/test_population_service.py`

Tests for the `populate_draft_answers()` service (or equivalent; OQ-1 resolved as
module-level functions in `answer_sources.py`):

**FDA_DERIVED_DEFAULT population:**

- A `FDA_DERIVED_DEFAULT` question whose `resolve_substance_identity()` returns an exact
  match: `raw_value` is set to the resolved `IIDIngredient.public_id`; `entered_by` is
  `None` (system-generated); audit event `iig_checklist.response.fda_populated` is
  emitted on commit.
- A `FDA_DERIVED_DEFAULT` question where the substance name has no approved mapping:
  `raw_value = None` (left blank); no `is_not_applicable` set; no fabricated value;
  dependent `SYSTEM_CALCULATED` questions have `CalculationOutcome.status = "data_required"`.
- A `FDA_DERIVED_DEFAULT` question where applicability rule returns `"not_applicable"`:
  `is_not_applicable = True`, `not_applicable_reason = ApplicabilityRule.reason_code`,
  `raw_value = None`.

**SYSTEM_CALCULATED computation:**

- A `SYSTEM_CALCULATED` question with `calculation_binding_identifier = "percentage_w_w"`
  (resolved from registry): when the upstream `USER_REQUIRED` quantity is 500 mg and
  `FormulationVersion.total_dosage_unit_weight` is 650 mg:
  - `CalculationOutcome.status = "complete"` (stored value, not `"OK"`).
  - `CalculationOutcome.reason_code = ""` (blank).
  - `CalculationOutcome.value` equals the actual `Decimal` output of the production
    function (test must use the production function's return value as the expected; no
    hand-computed assertion).
- A `SYSTEM_CALCULATED` question where an upstream `FDA_DERIVED_DEFAULT` input resolved
  to `None` (no match):
  - `CalculationOutcome.status = "data_required"`.
  - `CalculationOutcome.reason_code = "DATA_REQUIRED"`.
  - `CalculationOutcome.value = None`.
- A `SYSTEM_CALCULATED` question where `total_dosage_unit_weight = 0` (denominator zero):
  - `CalculationOutcome.status = "error"`.
  - `CalculationOutcome.reason_code = "NOT_COMPARABLE"` (canonical for `BASIS_UNCLEAR`).
  - `CalculationOutcome.value = None`.
- A `SYSTEM_CALCULATED` question where `max_daily_units` is `None`:
  - `CalculationOutcome.status = "data_required"`.
  - `CalculationOutcome.reason_code = "DATA_REQUIRED"` (canonical for `MAX_DAILY_UNITS_MISSING`).
  - `CalculationOutcome.value = None`.
- `CalculationOutcome.formula_version` is set (not blank) after a successful computation.
- `CalculationOutcome.inputs` and `input_provenance` are non-empty dicts after a
  successful computation.
- `CalculationOutcome.generated_at` is set (not null) after a successful computation;
  value is a timezone-aware `datetime`.
- `CalculationOutcome.source_assessment_snapshot_public_id` is set when the computation
  is derived from an `AssessmentSnapshot` (OQ-4 resolved: live-first).

**Generated_at parsing:**

- `CalculationResult.generated_at` ISO string is correctly parsed to a timezone-aware
  `datetime` in `CalculationOutcome.generated_at` — not stored as a string.
- A malformed `generated_at` string from a calculation result falls back to `None` in
  `CalculationOutcome.generated_at`; does not raise an exception that aborts the pass.
- A naive datetime string (no timezone) is rejected and falls back to `None`.

**Registry validation:**

- A `SYSTEM_CALCULATED` question with an unknown `calculation_binding_identifier` at
  runtime (registry out of sync): `CalculationOutcome.status = "error"`,
  `reason_code = "UNKNOWN_REGISTRY_IDENTIFIER"`.

**NOT_APPLICABLE propagation:**

- A `SYSTEM_CALCULATED` question whose applicability rule returns `"not_applicable"`:
  `is_not_applicable = True`, `CalculationOutcome.status` unchanged (stays `"data_required"`),
  `not_applicable_reason` is `ApplicabilityRule.reason_code`.
- A `SYSTEM_CALCULATED` question that is inapplicable vs. one that has missing upstream
  data: these must produce distinguishable `ChecklistResponse` states:
  `is_not_applicable = True` vs. `is_not_applicable = False, CalculationOutcome.status = "data_required"`.

**REVIEW_REQUIRED handling:**

- A question whose applicability rule returns `"review_required"`: population does not
  set `raw_value`, does not set `is_not_applicable`; execution remains editable; the
  response is flagged for governed review.

**Non-overwrite rules:**

- A `USER_REQUIRED` response with an existing `raw_value` is not overwritten by the
  population pass.
- A `REVIEWER_CONCLUSION` response is not touched by the population pass.
- An execution in `submitted_for_review` status rejects any population-pass call.

**Sequencing:**

- `FDA_DERIVED_DEFAULT` answers are populated before `SYSTEM_CALCULATED` answers in the
  same pass: a `SYSTEM_CALCULATED` question that depends on a `FDA_DERIVED_DEFAULT` answer
  has a non-null `CalculationOutcome.value` (or a correct blocked status) after a single
  population pass.
- No partial population: if the population pass raises mid-execution, no partial state
  is committed (all writes are inside a single `transaction.atomic()`).

**Idempotency:**

- Re-running the population pass with identical inputs produces no duplicate
  `ChecklistResponseHistory` rows and does not increment `ChecklistResponse.version`.

**`full_clean()` enforcement:**

- Direct call to `CalculationOutcome.save()` without `full_clean()` on an instance with
  an invalid `calculation_name` raises `ValidationError` — proves the guard in
  `CalculationOutcome.clean()` is reachable. The `AssessmentSnapshot` defect must not recur.
- Direct assignment of an engine-level status string (e.g. `"OK"`, `"ROUTE_MISMATCH"`)
  to `CalculationOutcome.status` followed by `full_clean()` raises `ValidationError` —
  confirms engine strings cannot be stored directly in the model.

**Snapshot tenant isolation:**

- An `AssessmentSnapshot` belonging to another tenant is not reused; a new snapshot is
  created for the current execution's tenant.

### 2d. Cyclic binding detection (`test_execution_lifecycle.py`, new cases)

- A `ChecklistVersion` with a dependency cycle (A depends on B, B depends on A) is
  blocked at activation with a structured error.
- A valid `ChecklistVersion` with no cycle activates normally.
- A `ChecklistVersion` where a `SYSTEM_CALCULATED` question's `calculation_binding_identifier`
  references an unknown registry key is blocked at activation.
- A `ChecklistVersion` where a declared dependency references a non-existent question
  code is blocked at activation.

---

## 3. Recalculation Tests (`test_update_checklist_response.py`)

Location: `backend/iig_checklist/tests/test_update_checklist_response.py`

Tests for the cascade recalculation path triggered by the governed service
`update_checklist_response()` on `draft` executions (S-03, S-04, OQ-3 resolved).

**Terminology.** Two distinct sets govern these tests and must not be conflated:

- **`recalculation_triggers`** — governed responses whose change starts a recalculation.
  Includes Form A `question_response` inputs and component-selector responses. These are
  **external trigger nodes**, not graph nodes.
- **`calculation_dependencies`** — Form E `calculation_outcome` edges between
  `SYSTEM_CALCULATED` responses. These form the directed graph used for ordering, depth,
  cascade-node limits and cycle detection.

No test shall assert or imply that only Form E question codes are recalculation triggers.

Required cases:

| Case | Scenario | Expected |
|---|---|---|
| A | Form A user-response change | The direct calculation consuming it recalculates, even though no graph edge exists from the user input |
| B | Form A user-response change with a downstream Form E dependant | Both the direct and the downstream calculated outcomes recalculate |
| C | Component-reference selector change | Component rebinding runs and every affected calculation recalculates (§10.19) |
| D | Form E upstream calculated outcome changes | Downstream calculated outcomes recalculate in topological order |
| E | An unrelated response listed in no `recalculation_triggers` set changes | No recalculation, no version change on any calculated response, no audit |
| F | Registry `recalculation_triggers` does not match the entry's Form A and selector declarations | Activation rejected, `REGISTRY_VALIDATION_FAILED` |
| G | Registry `calculation_dependencies` does not match the entry's Form E declarations | Activation rejected, `REGISTRY_VALIDATION_FAILED` |

The governed service is the only runtime owner of `transaction.atomic()`, the execution
lock, the response lock, `expected_version` validation, response validation,
applicability re-evaluation, dependent recalculation, history creation, the response
version increment and `transaction.on_commit()` audit dispatch.
`ChecklistResponseUpdateView.patch()` is a thin adapter and is exercised only through the
API tests in §4.

- `update_checklist_response()` with a `USER_REQUIRED` answer that feeds into one
  `SYSTEM_CALCULATED` question: after the call, `CalculationOutcome.status = "complete"`
  and `value` is non-null (assuming valid inputs).
- `update_checklist_response()` with a `USER_REQUIRED` answer that feeds into two
  `SYSTEM_CALCULATED` questions: both `CalculationOutcome` rows are updated.
- `update_checklist_response()` when the new value produces a blocked calculation (e.g.
  user sets quantity to `None`): `CalculationOutcome.status = "data_required"` (not
  `"error"` — the blocking condition is missing input, which translates to
  `"data_required"`); `reason_code = "DATA_REQUIRED"`; `value = None`.
- `update_checklist_response()` producing a mismatch result:
  `CalculationOutcome.status = "error"`; `reason_code` = canonical engine status string;
  `value = None`.
- No recalculation triggered when execution is `submitted_for_review` (responses are
  locked): `update_checklist_response()` on a `submitted_for_review` execution returns
  `response_immutable` / 400.
- Recalculation on a `returned` execution (valid recalculable state):
  `update_checklist_response()` succeeds and recalculation runs.
- Concurrent `update_checklist_response()` calls on the same execution: only one proceeds
  at a time (serialized by `select_for_update()` on the execution — T-06 mitigation).
  Test using `transaction=True`.
- Lock order respected: execution locked before response rows, response rows before
  `CalculationOutcome` rows; no deadlock.
- Atomic rollback: if the calculation step raises an exception after the `USER_REQUIRED`
  write, neither the response update nor the `CalculationOutcome` update is committed
  (full `transaction.atomic()` rollback).
- Defensive cycle check in recalculation loop: planted cycle at runtime (registry bug
  scenario) is caught before iteration limit is reached; `CalculationOutcome.status = "error"`.

---

## 4. API Tests

### 4a. Execution creation with population (`test_execution_api.py`, extended)

These are extensions to the existing `test_execution_api.py` (4D-2):

- `POST /executions/`: response body shows `CalculationOutcome` nested or retrievable;
  responses that were `DATA_REQUIRED` pre-population now show a translated stored status
  (`"complete"` or `"error"`) after the population pass runs at creation.
- `GET /executions/<uuid>/responses/`: each response shows `raw_value` for
  `FDA_DERIVED_DEFAULT` questions (non-null after successful population).
- `GET /executions/<uuid>/responses/` for a `SYSTEM_CALCULATED` question: response
  includes `CalculationOutcome` sub-representation with `value`, `status` (stored value:
  `"complete"` or `"error"` or `"data_required"`), `reason_code`, `formula_version`,
  `calculation_name`.
- `FDA_DERIVED_DEFAULT` response `entered_by` is `null` in the serialized output
  (system-generated, not a user).
- `USER_REQUIRED` question with `prefill_source = "formulation_component"`: response
  `raw_value` is `null` (the prefill is a UI hint, not a server-side pre-fill by the
  population pass; this test guards that the frontend, not the backend, pre-fills these).
- No `CalculationOutcome` PATCH or PUT endpoint exists; assert 404/405 on attempted
  direct write to a `CalculationOutcome` resource.

### 4b. Recalculation visible through API (`test_response_api.py`, extended)

- `PATCH /executions/<uuid>/responses/<uuid>/` with a `USER_REQUIRED` value: subsequent
  `GET /executions/<uuid>/responses/` shows `CalculationOutcome.status = "complete"` and
  updated `value` for the dependent `SYSTEM_CALCULATED` question.
- `PATCH` with a value that produces a blocked result: `CalculationOutcome.status = "error"`,
  `reason_code` = canonical engine status string, `value = null` — in the subsequent GET.
- `PATCH` with a value that restores a previously-blocked calculation to passing:
  `CalculationOutcome.status` transitions from `"error"` to `"complete"`.

### 4c. Audit event verification

- After a population pass, `AuditEvent` of type `iig_checklist.response.fda_populated`
  exists for each `FDA_DERIVED_DEFAULT` question that received a non-null value.
- No `iig_checklist.response.entered` event is emitted for system-populated answers.
- After a recalculation-triggering `PATCH`, audit event `iig_checklist.response.updated`
  exists for the triggering `USER_REQUIRED` response; no separate event is emitted for
  the system-updated `SYSTEM_CALCULATED` outcomes.
- Audit events are emitted after transaction commit (not within the transaction).

---

## 5. Planted Failure Tests (`test_planted_failures_4d3.py`)

Location: `backend/iig_checklist/tests/test_planted_failures_4d3.py`

Every `iid_assessment.calculations.CalculationStatus` engine result must have at least
one test that verifies the correct stored `(CalculationOutcome.status, reason_code)` pair
is produced and surfaced in the API. No blocked status may be silently converted to a
pass. `value` must be `None` for all non-OK outcomes.

**Canonical translation — expected stored values:**

| Engine result | Trigger condition | Stored `CalculationOutcome.status` | Stored `reason_code` | `value` |
|---|---|---|---|---|
| `"OK"` | All inputs valid and matched | `"complete"` | `""` (blank) | non-null Decimal |
| `"DATA_REQUIRED"` | Upstream question not yet answered | `"data_required"` | `"DATA_REQUIRED"` | `null` |
| `"INGREDIENT_UNRESOLVED"` | Substance name has no approved mapping | `"error"` | `"INGREDIENT_UNRESOLVED"` | `null` |
| `"ROUTE_MISMATCH"` | Proposed route does not match IID precedent | `"error"` | `"ROUTE_MISMATCH"` | `null` |
| `"DOSAGE_FORM_MISMATCH"` | Proposed dosage form does not match IID precedent | `"error"` | `"DOSAGE_FORM_MISMATCH"` | `null` |
| `"UNIT_MISMATCH"` | Unit conversion fails (engine alias: `UNIT_CONVERSION_FAILED`) | `"error"` | `"UNIT_MISMATCH"` | `null` |
| `"FDA_VALUE_UNAVAILABLE"` | IID precedent has null MDE/potency (engine aliases: `IID_VALUE_MISSING`, `IID_VALUE_INVALID`) | `"error"` | `"FDA_VALUE_UNAVAILABLE"` | `null` |
| `"NOT_COMPARABLE"` | Inputs outside comparison range (engine aliases: `BASIS_UNCLEAR`) | `"error"` | `"NOT_COMPARABLE"` | `null` |
| `"REGULATORY_REVIEW_REQUIRED"` | FDA release superseded/inactive after snapshot taken (engine aliases: `RELEASE_NOT_ACTIVE`, `RECORD_SUPERSEDED`) | `"error"` | `"REGULATORY_REVIEW_REQUIRED"` | `null` |
| unknown string | Registry/engine produces unrecognized status | `"error"` | `"UNKNOWN_ENGINE_STATUS"` | `null` |

**For each row, the test must verify:**
1. The population or recalculation service produces the stated stored `status` value (NOT the engine string).
2. `reason_code` contains the stated value (NOT blank for any non-OK outcome).
3. `value` is `None` for all non-`"complete"` rows.
4. `full_clean()` does not raise `ValidationError` for the stored `(status, reason_code)` pair.
5. The API response serialization returns the stored `status` value and `reason_code` in the
   `CalculationOutcome` nested representation.
6. No success audit event is emitted for a non-OK outcome.

**Additional planted-failure cases:**

- Direct assignment of any engine string (`"OK"`, `"ROUTE_MISMATCH"`, etc.) to
  `CalculationOutcome.status` followed by `full_clean()` raises `ValidationError` —
  confirms the model enforces the `iig_checklist.enums.CalculationStatus` choices.
- `CalculationOutcome.status = "calculating"` cannot be produced by any 4D-3 code path
  (reserved for async; synchronous path must never set it).

---

## 6. Frontend Tests

### 6a. Unit/accessibility (Vitest + React Testing Library + jest-axe)

- Execution detail page with a populated `FDA_DERIVED_DEFAULT` answer: renders provenance
  label "FDA-derived"; answer value displayed as read-only.
- Execution detail page with a `SYSTEM_CALCULATED` answer `CalculationOutcome.status = "complete"`:
  renders `CalculationOutcome.value` formatted appropriately; no status code shown.
- Execution detail page with `CalculationOutcome.status = "data_required"`: renders the
  `reason_code` string; never renders `0`, `""`, or the word `"complete"`.
- Execution detail page with `CalculationOutcome.status = "error"` and
  `reason_code = "FDA_VALUE_UNAVAILABLE"`: renders the `reason_code` with a user-legible
  label; no numeric value displayed.
- `USER_REQUIRED` question with `prefill_source = "formulation_component"`: renders a
  "Pre-filled from formulation" hint; the input is editable; the provenance label is
  NOT "FDA-derived."
- No formula computation in any frontend component: a code-level test (or linting rule)
  that verifies none of the six calculation function names appear in any frontend source
  file. This assertion runs in CI.
- `REVIEW_REQUIRED` applicability outcome: the affected response is rendered as requiring
  governed review; it is not marked as applicable or not-applicable.

### 6b. Playwright E2E

- Create execution → population pass runs → checklist detail shows populated answers.
- Edit a `USER_REQUIRED` field → page reloads → dependent `SYSTEM_CALCULATED` field
  shows updated `value` and `status = "complete"` from server (not a locally computed
  value).
- Blocked calculation scenario: enter a quantity that produces `"FDA_VALUE_UNAVAILABLE"` →
  `SYSTEM_CALCULATED` question shows `reason_code = "FDA_VALUE_UNAVAILABLE"`, not a number.
- `status = "complete"` after previously-blocked: user corrects upstream input →
  `SYSTEM_CALCULATED` field transitions from blocked state to showing a numeric value.

---

## 7. Docker Integration Extension

Extend `.github/workflows/docker-integration.yml` with a 4D-3 smoke step:

- Create a `ChecklistExecution` with a `ChecklistVersion` containing a
  `FDA_DERIVED_DEFAULT` question and a `SYSTEM_CALCULATED` question with a valid
  `calculation_binding_identifier` in the registry (e.g. `"percentage_w_w"`).
- Verify that after creation, the `FDA_DERIVED_DEFAULT` response has a non-null
  `raw_value` (or a documented non-match state).
- Verify that the `SYSTEM_CALCULATED` `CalculationOutcome.status` is either `"complete"`
  or `"data_required"` or `"error"` — never `"data_required"` with a blank `reason_code`
  once the population pass has run (i.e., at least `reason_code = "DATA_REQUIRED"` is set).
- Patch the `USER_REQUIRED` quantity → verify the `SYSTEM_CALCULATED` `CalculationOutcome`
  updates in the response list: `status` changes as expected and `reason_code` matches.
- Verify that attempting to PATCH a `CalculationOutcome` resource directly returns
  404 or 405.
- All synthetic data; no real FDA records involved.

---

## 8. Test Coverage and Gate

- Backend coverage gate: existing 55% threshold. 4D-3's new code should be covered at
  approximately 90%+ on new lines, consistent with the 4D-2 rate.
- The `CalculationStatus` translation function must reach 100% branch coverage.
- Import-linter: all existing contracts must continue to pass after 4D-3 additions.
  Verify `formulations` does not import `iig_checklist`; verify no new reverse imports.
- Ruff lint/format: all 4D-3 code must be clean before any PR opens. No `# noqa`
  suppressions without an explanatory comment.
- OpenAPI schema: must regenerate cleanly with any new endpoints or serializer fields.
- `CalculationOutcome.status` values in the schema must reflect the four
  `iig_checklist.enums.CalculationStatus` choices, not engine strings.

---

## 9. Second-Review Test Requirements (M-3, M-4, M-5, stale version)

The following normative test cases resolve findings M-3, M-4, and M-5 from the second
adversarial discovery review, and add an explicit stale-version test that was missing
from the original strategy. All four tests are **mandatory**; they must pass before any
4D-3 implementation PR may be opened.

### 10.1 M-3 — Dependency Depth Rejection at Activation

**Requirement:** `ChecklistVersion` activation must reject any dependency graph whose
longest path exceeds `MAX_DEPENDENCY_DEPTH = 5`.

**Fixture:** Construct a synthetic `ChecklistVersion` containing six `SYSTEM_CALCULATED`
questions linked in a linear chain (Q₁ → Q₂ → Q₃ → Q₄ → Q₅ → Q₆) so that the
maximum depth is 6, exceeding the limit.

**Test file:** `backend/iig_checklist/tests/test_checklist_version_activation.py`

**Test name:** `test_activation_rejects_dependency_depth_exceeding_limit`

**Assertions:**
1. Calling the activation service on the synthetic version raises a validation error
   (or returns a structured failure) with `error_code = "DEPENDENCY_DEPTH_EXCEEDED"`.
2. The `ChecklistVersion.status` remains in its pre-activation state (not `"active"`).
3. A depth-5 chain (Q₁ → Q₂ → Q₃ → Q₄ → Q₅) is accepted without error.

**What it proves:** The numeric constant is enforced at activation, not just documented.
A depth-6 graph is impossible to reach at runtime.

### 10.2 M-4 — Deterministic Topological Ordering

**Requirement:** Stable topological ordering must produce identical output across
repeated invocations with identical inputs; alphabetical `code` tiebreaker must be
verified.

**Fixture:** A three-question dependency graph with one root question (`Q_ROOT`) and
two leaf questions (`Q_ALPHA`, `Q_BETA`) that both depend on `Q_ROOT` and have no
dependency on each other. In a deterministic topological ordering with alphabetical
tiebreaking, `Q_ALPHA` must always precede `Q_BETA`.

**Test file:** `backend/iig_checklist/tests/test_dependency_graph.py`

**Test name:** `test_topological_order_is_stable_and_deterministic`

**Assertions:**
1. Call the topological sort function with the above graph at least 10 times with
   identical inputs; collect all results.
2. Assert that all 10 results are identical (`len(set(map(tuple, results))) == 1`).
3. Assert that `Q_ALPHA` appears before `Q_BETA` in every result (alphabetical
   tiebreaker enforced).
4. Assert that `Q_ROOT` appears before both leaf nodes.

**What it proves:** Cascade recalculation order is reproducible across process
restarts, parallel workers, and repeated invocations — determinism is a property of
the sort function, not of iteration order over dicts or sets.

### 10.3 M-5 — NOT_APPLICABLE Transition Preserves Prior Raw Value in History

**Requirement:** When a `ChecklistResponse` that already has a non-null `raw_value`
transitions to `NOT_APPLICABLE` (applicability evaluator returns `"not_applicable"`),
a `ChecklistResponseHistory` row must be created in the same transaction preserving
the prior value.

**Fixture:**
1. Create a synthetic `ChecklistExecution` with a `USER_REQUIRED` question
   (code = `Q_AMOUNT`) that has an `ApplicabilityRule` with `outcome_if_false =
   "applicable"` and `outcome_if_true = "not_applicable"`, conditioned on a
   `FormulationVersion` field.
2. Submit an answer for `Q_AMOUNT` (synthetic `raw_value = {"value": "5.0"}`).
3. Modify the formulation context such that the applicability condition evaluates to
   `True` (triggering `NOT_APPLICABLE`).
4. Trigger the population pass (or the applicability re-evaluation service, once
   implemented).

**Test file:** `backend/iig_checklist/tests/test_population_not_applicable.py`

**Test name:** `test_not_applicable_transition_creates_history_with_prior_value`

**Assertions:**
1. `ChecklistResponse.is_not_applicable == True` after the transition.
2. `ChecklistResponse.not_applicable_reason == rule.reason_code` (non-empty string,
   max 100 characters, fits within `MAX_NOT_APPLICABLE_REASON_CHARS = 200`).
3. A `ChecklistResponseHistory` row exists with `prior_raw_value = {"value": "5.0"}`
   (the value from step 2).
4. The history row and the response update share the same transaction: if the history
   write is rolled back, the response update is also rolled back (assert via
   `transaction.atomic()` with forced rollback in a separate test variant).
5. An audit event `iig_checklist.response.applicability_changed` was scheduled via
   `transaction.on_commit()` (assert that the signal or callback was registered).

**What it proves:** No regulated user-entered value is silently discarded when
applicability changes. Every transition is auditable.

### 9.4 Stale `expected_version` — withdrawn from this section

The stale-`expected_version` control has **exactly one** normative test definition, in
§10.3 (TST-145). The earlier duplicate that appeared here was written against a service
and test file that do not exist in the repository; it is withdrawn. Do not reinstate a
second definition of this control, and route all coverage through
`update_checklist_response()` and
`backend/iig_checklist/tests/test_update_checklist_response.py`.

---

## 10. Third-Review Test Requirements (C-1, C-2, M-A … M-E)

These tests resolve the Critical and Major findings of the third adversarial review.
They are mandatory. Identifiers `TST-101` … `TST-321` correspond one-to-one with the
acceptance matrix in Part 21 of the implementation specification.

### 10.1 C-1 — Registry identifier versus calculation name

Verified defect: `create_execution()` writes
`calculation_name=q.calculation_binding_identifier`, and `CalculationOutcome.clean()`
accepts only the six approved function names. A registry-key identifier therefore aborts
execution creation.

**Test file:** `backend/iig_checklist/tests/test_calculation_registry.py`

| Test ID | Test name | Assertion |
|---|---|---|
| TST-116 | `test_identifier_never_written_as_calculation_name` | For every registry entry, the created outcome's `calculation_name` equals `entry["calculation_name"]`, never the registry key |
| TST-120 | `test_identifier_to_calculation_name_mapping_exact` | All six identifiers map to the exact approved function names; identifier and name differ in all six cases |
| TST-122 | `test_registry_self_check_rejects_invalid_entry` | An entry whose `calculation_name` is outside `_CALCULATION_NAMES` raises at import |
| TST-126 | `test_registry_resolved_before_outcome_creation` | A valid key produces an outcome that passes `full_clean()` |
| TST-127 | `test_unknown_key_aborts_creation_atomically` | Unknown key → structured 400 `unknown_registry_identifier`; **zero** `ChecklistExecution`, `ChecklistResponse` and `CalculationOutcome` rows remain |
| TST-128 | `test_invalid_calculation_name_aborts_creation_atomically` | Entry with a bad `calculation_name` → atomic abort, no partial rows |
| TST-129 | `test_runtime_unknown_key_fails_closed` | Runtime unknown key → `status="error"`, `reason_code="UNKNOWN_REGISTRY_IDENTIFIER"`, no unhandled exception |
| TST-130 | `test_alias_semantics_identical` | A compatibility alias resolves to an entry with identical `calculation_name`, `function`, `input_resolvers`, `dependencies`, `required_units` |

### 10.2 C-2 — Governed response-update service

Verified state: no `enter_response()` exists; `ChecklistResponseUpdateView.patch()`
performs no transaction, no lock, no version check.

**Test file:** `backend/iig_checklist/tests/test_update_checklist_response.py`

| Test ID | Assertion |
|---|---|
| TST-133 | No test or fixture references an `enter_response()` symbol |
| TST-134 | The governed service exists and is importable |
| TST-135 | The service performs lookup, state, permission, version, lock, validation, recalculation, history, increment, transaction and audit |
| TST-136 | The view delegates: no model mutation and no `emit()` call inside the view body |
| TST-137 | PATCH of an `fda_derived_default` or `system_calculated` response by a non-override actor → 403 `server_controlled_value` |
| TST-269 | Lock acquisition order is execution → responses (pk asc) → outcomes (pk asc) |
| TST-270 | All writes occur inside one `transaction.atomic()` |
| TST-272 | An exception after the response write rolls back both the response and every outcome |
| TST-274 | Concurrent updates on one execution serialize on the execution lock |

### 10.3 `expected_version` contract

| Test ID | Assertion |
|---|---|
| TST-142 | `expected_version` is required on the governed request serializer |
| TST-144 | Omitted → HTTP 400 `expected_version_required`; version unchanged; no history; no audit |
| TST-145 | **Sole normative stale-version definition.** See the expanded specification immediately below. |
| TST-146 | Matching version succeeds and increments `version` by exactly one |
| TST-147 | Frontend handles 409 by reloading; no automatic retry |
| TST-271 | The version comparison is made against the row returned by `select_for_update()` |

#### TST-145 — stale `expected_version` (single normative definition)

**Test file:** `backend/iig_checklist/tests/test_update_checklist_response.py`
**Test name:** `test_stale_expected_version_returns_409_and_no_writes`

**Fixture:** a `ChecklistExecution` in `draft`; a `USER_REQUIRED` `ChecklistResponse`
with `version = 3` that is a declared dependency of a `SYSTEM_CALCULATED` question whose
`CalculationOutcome` is already `complete`.

**Invocation path:** PATCH through `ChecklistResponseUpdateView`, which delegates to
`update_checklist_response()`. The control is exercised end-to-end through the adapter,
not by calling the service directly.

**Assertions:**
1. HTTP 409 with `error_code = "stale_version"` for `expected_version = 2`.
2. `ChecklistResponse.raw_value` is unchanged — no response mutation.
3. `ChecklistResponse.version` is still `3` — no version increment.
4. No `ChecklistResponseHistory` row exists.
5. No recalculation ran.
6. The dependent `CalculationOutcome` is byte-for-byte unchanged, including `value`,
   `status`, `reason_code`, `generated_at` and `input_provenance`.
7. No success audit event was emitted.

**Negative control:** `expected_version = 3` succeeds with HTTP 200 and increments
`version` to `4`.

### 10.4 M-A — Completeness gate for calculated and FDA-derived answers

**Test file:** `backend/iig_checklist/tests/test_execution_completeness.py`

| Test ID | Scenario | Expected |
|---|---|---|
| TST-214 | Required calculated question, applicable, `status="complete"`, `value` non-null | Submission permitted |
| TST-215a | Required calculated, `status="data_required"` | Blocked; error names question code and `reason_code` |
| TST-215b | Required calculated, `status="error"` | Blocked |
| TST-215c | Required calculated, no outcome row | Blocked |
| TST-215d | Required calculated, `status="complete"` but `value` null | Blocked |
| TST-215e | Required calculated, applicability `review_required` | Blocked |
| TST-216 | Required FDA-derived populated and no marker | Permitted; unpopulated → blocked |
| TST-217 | Response persisted `not_applicable` with reason | Permitted, matching existing behavior |
| TST-218 | Gate execution issues no `run_preview()` call | Persisted state only |

### 10.5 M-B — REVIEW_REQUIRED submission gate

| Test ID | Assertion |
|---|---|
| TST-219 | Any response carrying a `REVIEW_REQUIRED:` marker blocks submission |
| TST-220 | Blocking occurs for `question.required = False` exactly as for `True` |
| TST-221 | HTTP 400 `review_required_unresolved`, listing affected response public UUIDs and `ApplicabilityRule.code` values |
| TST-222 | The error payload contains no `raw_value` content |
| TST-223 | Execution status is unchanged and no success audit event is emitted |
| TST-224 | No API affordance exists to clear the marker manually within 4D-3 |
| TST-225 | Correcting the governing context and re-running authorized recalculation clears the marker and unblocks submission |

### 10.6 M-C — Historical applicability reproducibility

**Test file:** `backend/iig_checklist/tests/test_applicability_persistence.py`

| Test ID | Assertion |
|---|---|
| TST-181 | A `ChecklistResponse` with `is_not_applicable=False` and a non-empty `not_applicable_reason` passes `full_clean()` — confirming the marker design needs no migration |
| TST-183 | A 100-character `reason_code` yields a 116-character marker, within the 200-character limit |
| TST-184 | Activation rejects a rule whose composed marker would exceed 200 characters |
| TST-187 | In `draft`, recomputation through the governed service updates the persisted marker |
| TST-188 | **Drift test:** approve an execution; change the active FDA release so the live context would flip the outcome; re-read the execution; the serialized `applicability_outcome` is unchanged, and `run_preview()` is not called during the read |
| TST-189 | Derivation: `is_not_applicable=True` → `not_applicable`; marker prefix → `review_required`; rule-governed with neither → `applicable`; no rule → `no_rule` |
| TST-190 | No serialized payload reports `is_not_applicable=false` together with `applicability_outcome="not_applicable"` |
| TST-191 | An unpersisted live result is never returned as the record's applicability |
| TST-192 | Every rule-governed response carries a persisted outcome before submission is allowed |
| TST-193 | `applicability_outcome` is absent from every writable serializer field set |

### 10.7 M-D — Applicability re-evaluation and history

**Test file:** `backend/iig_checklist/tests/test_applicability_reevaluation.py`

| Test ID | Assertion |
|---|---|
| TST-194 | Re-evaluation occurs on creation, on a dependency response update, and on authorized recalculation — and on nothing else |
| TST-195 | No re-evaluation occurs for `submitted_for_review` or any terminal status |
| TST-196 | An FDA release change alone triggers no re-evaluation |
| TST-200 | Execution creation writes no `ChecklistResponseHistory` row |
| TST-201 | A persisted applicability transition populates **all twelve** required fields: `response`, `prior_raw_value`, `new_raw_value`, `prior_is_not_applicable`, `new_is_not_applicable`, `prior_not_applicable_reason`, `new_not_applicable_reason`, `prior_version`, `new_version`, `correction_reason`, `amended_by`, `source_classification_snapshot` |
| TST-202 | `amended_by` equals the authenticated triggering actor, and is **not** `execution.created_by` when a different user triggered the change |
| TST-203 | `correction_reason` equals `APPLICABILITY_REEVALUATED` |
| TST-205 | `prior_version` and `new_version` bracket the increment |
| TST-206 | Forcing a rollback leaves neither the history row nor the response change |
| TST-207 | Mutating or deleting an existing history row raises `GovernedHistoryMutationForbidden` |

### 10.8 M-E — Client-writable applicability fields

| Test ID | Assertion |
|---|---|
| TST-176 | PATCH supplying `is_not_applicable` or `not_applicable_reason` for a rule-governed response → 403 `applicability_server_controlled` |
| TST-177 | PATCH declaring N/A on a response with no applicability rule remains permitted |
| TST-178 | PATCH supplying a `not_applicable_reason` beginning `REVIEW_REQUIRED:` → 403 `reserved_reason_prefix`, for governed and ungoverned responses alike |
| TST-179 | A user-declared N/A on an ungoverned response survives a subsequent population pass |
| TST-186 | No client request can create or clear the reserved marker |

### 10.9 N/A raw-value transitions

| Test ID | Assertion |
|---|---|
| TST-208 | Transition to N/A sets `raw_value = null` and passes `full_clean()` |
| TST-209 | The prior `raw_value` is present in `ChecklistResponseHistory.prior_raw_value` |
| TST-210 | `not_applicable_reason` is set from `ApplicabilityRule.reason_code` |
| TST-211 | Transition back to applicable does **not** restore `raw_value` from history |
| TST-212 | Transition back clears both flags and records prior values in history |

### 10.10 Outcome invariants and duplicates

| Test ID | Assertion |
|---|---|
| TST-150 | No test asserts validation via a bare `save()`; validation assertions call `full_clean()` or the governed service |
| TST-151 | No documentation or code claims a `CalculationOutcome` unique constraint |
| TST-153 | **Planted failure:** insert a second `CalculationOutcome` row for the same response and `calculation_name` directly (the schema permits it), then invoke the governed service; the service raises `duplicate_calculation_outcome` and does not guess |
| TST-154 | `python manage.py makemigrations --check --dry-run` reports no pending migration |
| TST-156 | A non-complete status carrying a non-null `value` is rejected with `invalid_outcome_value` before `full_clean()` |

### 10.11 Reason-code vocabulary

| Test ID | Assertion |
|---|---|
| TST-163 | `ALLOWED_REASON_CODES` contains exactly the fifteen approved codes |
| TST-164 | Every code is uppercase ASCII with underscores and at most 100 characters |
| TST-165 | A reason code outside the allow-list is rejected by the governed service |
| TST-166 | No request serializer accepts a `reason_code` field |
| TST-167 | No stored `reason_code` contains exception text, a stack frame, or a file path |

### 10.12 Maximum dosage units resolver

Verified schema: `FormulationVersion.maximum_dosage_units_per_day` is nullable;
`DosingRegimen.maximum_units_per_day` is required, `> 0` by check constraint, and
one-to-many per version with no lifecycle field. All fixtures are synthetic.

**Test file:** `backend/iig_checklist/tests/test_max_dosage_units_resolver.py`

| Test ID | Scenario | Expected |
|---|---|---|
| TST-324 | Version scalar present, no regimens | Scalar used; source type `formulation_version` |
| TST-329a | Scalar null, one regimen | Regimen value used; source type `dosing_regimen` |
| TST-329b | Scalar null, three regimens (10, 25, 15) | **25** selected as worst case |
| TST-332a | Scalar and regimen equal | That value used; both provenances recorded; `source_disagreement` false |
| TST-332b | Scalar 10, regimen 25 | **25** used (regimen higher) |
| TST-332c | Scalar 25, regimen 10 | **25** used (scalar higher) |
| TST-330 | Two regimens tied at the highest value | Lowest `public_id` selected; repeated runs select the same row |
| TST-335 | No scalar and no regimen | Engine yields `MAX_DAILY_UNITS_MISSING`; stored `status = "data_required"`, `reason_code = "DATA_REQUIRED"`; provenance detail `MAX_DAILY_UNITS_REQUIRED` |
| TST-327 | Regimen row with a value that cannot be coerced to a valid positive `Decimal` | Excluded from selection; recorded invalid; if no valid candidate remains, fails closed with detail `MAX_DAILY_UNITS_SOURCE_INVALID` |
| TST-326 | Regimen belonging to another tenant via `formulation_version__product__tenant` | Not selected, not counted, and absent from provenance |
| TST-333 | Scalar and regimen differ | Higher value used and `source_disagreement = true` recorded with both values |
| TST-331 | Three regimens with distinct `patient_population` labels | Worst case selected across all populations; populations appear as provenance only, never as a filter |
| TST-342 | Resolver run ten times against unchanged data | Identical selected value and identical provenance ordering every run |
| TST-343 | Approved execution, then a new higher `DosingRegimen` is added | Persisted `CalculationOutcome.value` and provenance are unchanged |
| TST-323 | Static check | No code path resolves maximum units from the version scalar alone |
| TST-334 | Selection audit | Never the lower value, never an average, never creation-order selection |
| TST-336 | Engine mapping | No new stored status or `reason_code` value is introduced |
| TST-337 | Provenance separation | Detail code appears in `input_provenance`, never in `CalculationOutcome.reason_code` |
| TST-338 | Provenance content | All fields required by M4D3-MDU-016 present |
| TST-339 | Provenance | `resolver_version` recorded |
| TST-340 | Provenance | No internal primary key present |
| TST-341 | Serializer | Client receives sanitized summary only |
| TST-328 | Request serializer | A dosing value in the request payload is rejected |
| TST-325 | Resolver | No lifecycle/status filter is applied to `DosingRegimen` |

### 10.13 Applicability reason-code format validation

**Test file:** `backend/iig_checklist/tests/test_applicability_rule_validation.py`

| Test ID | Input `reason_code` | Expected |
|---|---|---|
| TST-353 | `EXCIPIENT_NOT_IN_IID` | Accepted at activation |
| TST-355 | `REVIEW:REQUIRED` | Rejected — colon |
| TST-357a | `REVIEW_REQUIRED` | Rejected — reserved, `error_code = "reserved_reason_code"` |
| TST-357b | `REVIEW_REQUIRED:FOO` | Rejected — reserved prefix |
| TST-356a | `excipient_not_in_iid` | Rejected — lowercase |
| TST-356b | `EXCIPIENT NOT IN IID` | Rejected — whitespace |
| TST-354a | 100-character conforming code | Accepted (boundary) |
| TST-354b | 101-character code | Rejected |
| TST-358 | 100-character code composed into a marker | Result is 116 characters and passes `full_clean()` within the 200-character limit |
| TST-359 | Client-supplied `reason_code` or composed marker | Rejected |

### 10.14 Blank route and dosage form

**Test file:** `backend/iig_checklist/tests/test_controlled_term_resolution.py`

| Test ID | Scenario | Expected |
|---|---|---|
| TST-345a | `product.route = ""` | Treated as missing; `status = "data_required"`; provenance detail `ROUTE_NOT_PROVIDED` |
| TST-345b | `product.dosage_form = ""` | Treated as missing; provenance detail `DOSAGE_FORM_NOT_PROVIDED` |
| TST-345c | Both blank | Both details recorded; single `data_required` outcome |
| TST-349a | Non-blank unknown route code | Engine canonical `ROUTE_MISMATCH` → `status = "error"` |
| TST-349b | Route code whose `ControlledRoute.lifecycle != "active"` | Same as unknown code — `.first()` returns `None` and this is not success |
| TST-349c | Valid active route and dosage form | Resolution succeeds |
| TST-346 | Static check | A blank value is never passed to `run_preview()` as a resolved argument |
| TST-347 | Resolver | A `None` lookup result is never treated as successful resolution |
| TST-348 | Resolver | No fallback or default controlled term is substituted |
| TST-344 | Documentation | Blank-capable fields recorded as verified |

### 10.15 Input-resolver test matrix

Resolves MAJ-A. All fixtures synthetic. Canonical units are full words (`gram`,
`milligram`) per `iid_assessment/unit_conversion.py`.

**Test file:** `backend/iig_checklist/tests/test_calculation_input_resolution.py`

**Form A — question response (TST-362)**

| Case | Expected |
|---|---|
| Valid decimal response | Resolved as `Decimal` |
| Missing response | `INPUT_RESPONSE_MISSING` → `data_required` |
| `is_not_applicable` response | `INPUT_RESPONSE_NOT_APPLICABLE` → `data_required` |
| `REVIEW_REQUIRED:` marker present | `INPUT_REVIEW_REQUIRED` → `data_required` |
| Non-numeric `raw_value` | `INPUT_VALUE_INVALID` → `error` |
| Response on another tenant's execution | `INPUT_TENANT_MISMATCH` → `error` |
| Form A pointed at a `SYSTEM_CALCULATED` question | Rejected at activation; `raw_value` is never accepted as a calculation result |

**Form B — formulation field (TST-363)**

| Case | Expected |
|---|---|
| Valid `FormulationComponent.quantity_per_dosage_unit` | Resolved and converted |
| Valid `FormulationVersion.total_dosage_unit_weight` | Resolved and converted to `gram` |
| Missing component | `FORMULATION_COMPONENT_MISSING` → `data_required` |
| Blank `quantity_unit` | `INPUT_UNIT_MISSING` → `data_required` |
| Unit outside the allow-list | `INPUT_UNIT_UNSUPPORTED` → `error`, `reason_code = UNIT_MISMATCH` |
| Mass field with a volume target and no density | `DENSITY_REQUIRED` → `error`, `reason_code = NOT_COMPARABLE` |
| Component under another tenant | `INPUT_TENANT_MISMATCH` → `error` |

**Form C — maximum daily units (TST-364)** — all branches of §10.12 retained; additionally
assert the resolver is invoked through `resolve_calculation_inputs()` and that no registry
entry restates the selection logic.

**Form D — assessment snapshot (TST-365)**

| Case | Expected |
|---|---|
| Valid `iid_potency_amount` | Resolved |
| Valid `iid_mde` | Resolved |
| No snapshot for the execution | `ASSESSMENT_SNAPSHOT_MISSING` → `data_required` |
| Snapshot with a different `tenant` | `INPUT_TENANT_MISMATCH` → `error`; no field value leaks |
| Snapshot present but field null/blank | `ASSESSMENT_FIELD_MISSING` → `data_required` |
| Client-supplied snapshot UUID in the request | Rejected; resolver uses only the transaction-scoped object |
| Live IID row changed after snapshot creation | Resolved value still comes from the snapshot |

`AssessmentSnapshot` has **no** stale or review-required status field, so no test shall
assert one. The former "stale/review-required snapshot" case is replaced by these
real-field conditions:

| Case | Field actually checked | Expected |
|---|---|---|
| Snapshot `iid_release_public_id` ≠ selected active release | `iid_release_public_id` | `ASSESSMENT_SNAPSHOT_RELEASE_MISMATCH` → `error` / `SNAPSHOT_RESOLUTION_FAILED` |
| Snapshot `formulation_component_public_id` ≠ resolved subject component | `formulation_component_public_id` | `ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH` → `error` / `SNAPSHOT_RESOLUTION_FAILED` |
| Snapshot `tenant` ≠ `execution.tenant` | `tenant` | `ASSESSMENT_SNAPSHOT_TENANT_MISMATCH` → `error` / `TENANT_ISOLATION_VIOLATION` |
| Required IID field null | `iid_potency_amount` / `iid_mde` | `ASSESSMENT_FIELD_MISSING` → `data_required` |
| Required unit field blank | `iid_potency_unit` / `iid_mde_unit` | `INPUT_UNIT_MISSING` → `data_required` |

**Form E — prior calculation outcome (TST-366)**

| Case | Expected |
|---|---|
| Exactly one `complete` outcome with non-null value | Resolved |
| Zero outcome rows | `UPSTREAM_CALCULATION_MISSING` → `data_required` |
| Two rows for the same response and `calculation_name` | `UPSTREAM_CALCULATION_DUPLICATE` → `error`; no arbitrary pick |
| Upstream `data_required` | `UPSTREAM_CALCULATION_INCOMPLETE` → `data_required` |
| Upstream `error` | `UPSTREAM_CALCULATION_INCOMPLETE` → `data_required` |
| `complete` with null `value` | `UPSTREAM_CALCULATION_INCOMPLETE` → `data_required` |
| Upstream unit not convertible to `required_unit` | `INPUT_UNIT_DIMENSION_MISMATCH` → `error`, `UNIT_MISMATCH` |
| Upstream outcome on another tenant's execution | `INPUT_TENANT_MISMATCH` → `error` |
| Dependency ordering | Upstream resolved before dependants in every run |

**Form F — constant (TST-367)** — a registry-declared constant resolves; no request
payload can introduce or override one.

**Unit conversion (TST-377 … TST-387)**

| Case | Expected |
|---|---|
| `gram` → `milligram` | ×1000 exactly, `Decimal` |
| `milligram` → `gram` | ÷1000 exactly, `Decimal` |
| Same-unit pass-through | Value unchanged, still `Decimal` |
| Unknown unit | `UNIT_UNKNOWN` → `UNIT_MISMATCH` |
| Mass → volume without density | `DENSITY_REQUIRED` → `NOT_COMPARABLE` |
| Missing unit | `VALUE_MISSING`/`INPUT_UNIT_MISSING` → `DATA_REQUIRED` |
| Precision and rounding | Deterministic, repeatable, no float anywhere on the path |
| Provenance | Original value, original unit, converted value, converted unit and rule version recorded |

**End-to-end (TST-388 … TST-392, TST-369 … TST-376)**

| Case | Expected |
|---|---|
| All six functions | Receive fully resolved kwargs matching M4D3-INP-001 names exactly |
| Missing-kwarg `TypeError` | Unreachable — the pipeline blocks invocation before the call |
| Representative synthetic inputs | Correct result for each of the six functions |
| Any resolver failure | Calculation function is not invoked |
| Provenance | Contains every source and every conversion applied |
| `calculate_daily_exposure` outcome | Stored `unit` is `gram` per day, giving Form E an explicit source unit |
| Dependency graph | Derived graph equals the documented graph: daily_exposure → {percentage_of_mde, difference_from_mde}; the two MDE calculations do not depend on each other |

**Snapshot ordering (TST-399 … TST-402)** — the six-step order is observed; no live IID
read occurs after the snapshot step; a forced rollback discards both snapshot and
outcomes; snapshot-dependent calculations run after their Form E upstream.

### 10.16 Subject component selection (MAJ-B)

**Test file:** `backend/iig_checklist/tests/test_component_selection.py`

| Test ID | Case | Expected |
|---|---|---|
| TST-415 | Valid component reference in the same execution and formulation | Resolved; provenance carries the component public UUID |
| TST-417a | Referenced component belongs to another `FormulationVersion` | `FORMULATION_COMPONENT_WRONG_FORMULATION` → `error` / `FORMULATION_COMPONENT_RESOLUTION_FAILED` |
| TST-417b | Referenced component belongs to another tenant | `FORMULATION_COMPONENT_TENANT_MISMATCH` → `error` / `TENANT_ISOLATION_VIOLATION` |
| TST-417c | `component_type = "active"` where `inactive` required | `FORMULATION_COMPONENT_TYPE_MISMATCH` → `error` / `FORMULATION_COMPONENT_RESOLUTION_FAILED` |
| TST-419a | Component-reference response missing | `FORMULATION_COMPONENT_MISSING` → `data_required` |
| TST-419b | Component-reference `raw_value` null | `FORMULATION_COMPONENT_MISSING` → `data_required` |
| TST-415b | Malformed or non-UUID `public_id` | `FORMULATION_COMPONENT_REFERENCE_INVALID` → `error` |
| TST-420a | Registry component code matching two components | `FORMULATION_COMPONENT_AMBIGUOUS` → `error`; no component chosen |
| TST-420b | Duplicate component code within one formulation | Rejected at activation |
| TST-427 | One execution, two calculated questions bound to two different inactive components | Two distinct outcomes, each with its own component provenance |
| TST-430 | Formulation with five inactive components | No question is created or expanded automatically |
| TST-418 | Formulation with several inactive components and no selector | Fails closed; never selects the first row, lowest pk, or `display_order` head |
| TST-421 | Provenance | Contains the correct component public UUID, `component_type`, selector type and selector-source response UUID |
| TST-423a | Failed component resolution | Calculation function is never invoked |
| TST-423b | Failed component resolution | No partial `CalculationOutcome` and no success audit |

### 10.17 Snapshot determinism (MAJ-C)

| Test ID | Case | Expected |
|---|---|---|
| TST-440 | Two successive governed recalculations | Two distinct `AssessmentSnapshot` rows; neither reuses the other |
| TST-441 | Resolver invocation | Reads the in-memory object; no `AssessmentSnapshot` query is issued during resolution |
| TST-442 | Query audit | No broad lookup by tenant/component/release after creation; no `.first()` on that model |
| TST-443 | Ordering | The nine steps of M4D3-SNO-009 occur in order |
| TST-444 | Consistency checks | Tenant, component and release each verified before use |
| TST-445 | Client payload carrying a snapshot UUID | Rejected |
| TST-446a | Downstream calculation raises | Snapshot and all outcomes roll back together |
| TST-446b | Transaction | The `iid_assessment` helper joins the outer transaction and does not commit independently |
| TST-439 | Pre-existing duplicate snapshots in the database | Resolution is unaffected, because no lookup occurs |

### 10.18 Failure-mapping matrix (MAJ-D)

A single parameterized test shall cover **every** entry of the M4D3-IFV-003 table.

**Test file:** `backend/iig_checklist/tests/test_resolver_failure_mapping.py`
**Test name:** `test_resolver_detail_code_maps_deterministically`

For each of the 28 mapped detail codes, assert: the stored `status` equals the table's
value; the stored `reason_code` equals the table's value; `value` is null for every
non-complete outcome; the exact detail code appears in server-side provenance; no raw
exception text or stack frame is stored anywhere; `full_clean()` passes; the status is
never `complete`; and no client input can substitute any of these values.

Required negative controls:

| Test ID | Assertion |
|---|---|
| TST-450a | `INPUT_TENANT_MISMATCH` never yields `NOT_COMPARABLE` — it yields `TENANT_ISOLATION_VIOLATION` |
| TST-450b | `FORMULATION_COMPONENT_TENANT_MISMATCH` and `ASSESSMENT_SNAPSHOT_TENANT_MISMATCH` likewise |
| TST-449a | `UPSTREAM_CALCULATION_DUPLICATE` never yields `DATA_REQUIRED` — it yields `DUPLICATE_UPSTREAM_OUTCOME` |
| TST-449b | `ASSESSMENT_SNAPSHOT_DUPLICATE` yields `SNAPSHOT_RESOLUTION_FAILED`, distinct from `ASSESSMENT_SNAPSHOT_MISSING` → `DATA_REQUIRED` |
| TST-447 | `INPUT_VALUE_INVALID` (malformed) and `INPUT_VALUE_NOT_COMPARABLE` (scientific) map to different canonical codes |
| TST-448 | An undefined internal condition yields `UNKNOWN_INTERNAL_FAILURE` → `INPUT_RESOLUTION_FAILED`, never `complete` |
| TST-450c | `INPUT_RESOLVER_UNKNOWN` yields `INPUT_RESOLUTION_FAILED`, not `UNKNOWN_REGISTRY_IDENTIFIER` |

The test shall be data-driven from the specification table so that adding a detail code
without a mapping fails the suite.

### 10.19 Component rebinding (MAJ-F)

**Test file:** `backend/iig_checklist/tests/test_component_rebinding.py`

Fixture: an execution in `draft` with a component-reference response bound to inactive
component **A**, a `calculate_daily_exposure` question listing that selector in
`recalculation_triggers`, and `calculate_percentage_of_mde` / `calculate_difference_from_mde`
depending on it through `calculation_dependencies`.

| Test ID | Case | Expected |
|---|---|---|
| TST-464a | Selector changed A → B | Direct `daily_exposure` outcome recalculates against B |
| TST-464b | Same change | Both downstream MDE outcomes recalculate |
| TST-468 | Current provenance | References component B only — new component UUID, new selector-response UUID, new quantity/unit, new conversion provenance |
| TST-469a | Current snapshot | `source_assessment_snapshot_public_id` belongs to a snapshot whose `formulation_component_public_id` is B |
| TST-464c | Prior result | Component A's value is not retained as current on any affected outcome |
| TST-469b | Historical evidence | Component A's `AssessmentSnapshot` row still exists, unmutated |
| TST-467a | Version | The component-reference response version increments by exactly one |
| TST-467b | History | A `ChecklistResponseHistory` row records the prior and new component-reference `raw_value` |
| TST-467c | Audit | Success audit emits only after commit |
| TST-465a | Stale `expected_version` | HTTP 409; zero changes to reference, outcomes, provenance or snapshot |
| TST-471a | Component from another `FormulationVersion` | Full rollback; prior binding and prior outcomes remain current |
| TST-471b | Component from another tenant | Tenant-safe error; full rollback; no provenance leakage |
| TST-471c | `component_type = "active"` where `inactive` required | Full rollback |
| TST-471d | Snapshot creation fails | Full rollback; no orphan snapshot row persists |
| TST-471e | Structural calculation failure requiring rollback | All prior state restored exactly |
| TST-472 | Input-resolution failure with a row in the M4D3-IFV-003 table | Rebinding **commits**; affected outcomes persist with the mapped status, canonical reason code, null value and new-component provenance |
| TST-466 | Rebinding attempted after submission | Rejected, `response_immutable` / 400 |
| TST-470 | Selector re-submitted with the identical component | No recalculation, no version increment, no history row, no audit |
| TST-467d | Two calculated questions bound to the same selector | Both recalculate |
| TST-467e | Downstream ordering | Graph nodes processed in stable topological order |
| TST-469c | Provenance sweep | No prior-component UUID and no prior snapshot UUID remains anywhere in current `input_provenance` |

### 10.20 Trigger and selector configuration

| Test ID | Assertion |
|---|---|
| TST-451 | `calculation_dependencies` contains only Form E targets |
| TST-452 | `recalculation_triggers` contains every Form A question code and every component-selector question code |
| TST-453 | Both sets are declared independently and may overlap without being interchangeable |
| TST-455 | A resolver reading a response absent from `recalculation_triggers` fails activation |
| TST-456 | Both sets are validated against resolver declarations at activation |
| TST-457 | An unknown trigger question code fails activation with `UNKNOWN_TRIGGER_CODE` |
| TST-458 | The graph contains only `SYSTEM_CALCULATED` response nodes; trigger nodes are excluded from cycle detection and depth |
| TST-461 | A registry entry declaring `registry_component_code` is rejected at activation with `component_selector_form_disabled` |
| TST-462 | `response_reference` is the only selector form that activates successfully |
| TST-463 | Static check: no component code is derived from `ingredient_name`, `resolved_unii`, `display_order`, pk or creation order |

---

## 11. Acceptance Matrix Reconciliation

A mechanical comparison was run between the normative requirement identifiers defined in
`docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md` and the identifiers listed in its Part 21
acceptance matrix.

| Metric | Value |
|---|---|
| Normative requirement IDs defined | 374 |
| Acceptance matrix IDs | 374 |
| Missing (defined but absent from matrix) | 0 |
| Duplicate requirement definitions | 0 |
| Duplicate matrix rows | 0 |
| Orphan matrix IDs (in matrix but undefined) | 0 |
| Matrix rows missing a required cell | 0 |

Per-block counts: API 5, APP 13, AUD 7, CAR 10, CMP 6, DAG 10, DEP 12, FCR 14, FE 9,
HST 9, IFV 7, INP 15, MAP 10, MDL 13, MDU 24, MIG 8, NA 5, OUT 8, POP 8, PRV 4, PST 13,
RBD 9, RCL 7, REG 19, REV 5, RFV 7, RSN 10, RTE 6, SEC 5, SER 9, SNO 12, SNP 7, SRC 14,
SUB 7, SVC 8, TRG 7, TRL 6, TXN 6, UNC 11, VER 8.

Nineteen rows are classified **Review assertion** in the specification's Part 21 preamble:
they record verified source facts and map to source-inspection evidence rather than an
executable test. All remaining rows are normative controls requiring implementation.

This reconciliation shall be re-run and the table updated whenever either document
changes.

---

## 12. What This Test Strategy Explicitly Does Not Cover

- Override/deviation workflow tests (4D-4 scope).
- Manual resolution of a `REVIEW_REQUIRED` state (4D-4 scope; blocking in 4D-3).
- Export and SHA-256 checksum tests (4D-4 scope).
- Real FDA data ingestion scenarios.
- Production client formulation data scenarios.
- 21 CFR Part 11 electronic signature compliance tests.
- Any test that asserts an automatic safety or approval conclusion.
- Asynchronous calculation execution paths (`CalculationStatus.CALCULATING`).
- Generic `CalculationOutcome` write endpoint tests (no such endpoint exists).
- System-only background recalculation without an authenticated actor (out of scope).
