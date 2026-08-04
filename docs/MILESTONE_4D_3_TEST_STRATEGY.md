# Milestone 4D-3 Test Strategy

**Status: DISCOVERY COMPLETE. Pending second adversarial review before implementation specification.**

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

## 3. Recalculation Tests (`test_recalculation.py`)

Location: `backend/iig_checklist/tests/test_recalculation.py`

Tests for the cascade recalculation path triggered by `enter_response()` on `draft`
executions (S-03, S-04, OQ-3 resolved):

- `enter_response()` with a `USER_REQUIRED` answer that feeds into one
  `SYSTEM_CALCULATED` question: after the call, `CalculationOutcome.status = "complete"`
  and `value` is non-null (assuming valid inputs).
- `enter_response()` with a `USER_REQUIRED` answer that feeds into two
  `SYSTEM_CALCULATED` questions: both `CalculationOutcome` rows are updated.
- `enter_response()` when the new value produces a blocked calculation (e.g. user sets
  quantity to `None`): `CalculationOutcome.status = "data_required"` (not `"error"` —
  the blocking condition is missing input, which translates to `"data_required"`);
  `reason_code = "DATA_REQUIRED"`; `value = None`.
- `enter_response()` producing a mismatch result: `CalculationOutcome.status = "error"`;
  `reason_code` = canonical engine status string; `value = None`.
- No recalculation triggered when execution is `submitted_for_review` (responses are
  locked): `enter_response()` on a `submitted_for_review` execution returns
  `response_immutable` / 400.
- Recalculation on a `returned` execution (valid recalculable state): `enter_response()`
  succeeds and recalculation runs.
- Concurrent `enter_response()` calls on the same execution: only one proceeds at a time
  (serialized by `select_for_update()` on the execution — T-06 mitigation). Test using
  `transaction=True`.
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

## 9. What This Test Strategy Explicitly Does Not Cover

- Override/deviation workflow tests (4D-4 scope).
- Export and SHA-256 checksum tests (4D-4 scope).
- Real FDA data ingestion scenarios.
- Production client formulation data scenarios.
- 21 CFR Part 11 electronic signature compliance tests.
- Any test that asserts an automatic safety or approval conclusion.
- Asynchronous calculation execution paths (`CalculationStatus.CALCULATING`).
- Generic `CalculationOutcome` write endpoint tests (no such endpoint exists).
