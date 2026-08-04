# Milestone 4D-3 Test Strategy

**Status: DISCOVERY. No implementation authorized.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Scope register:** `docs/MILESTONE_4D_3_SCOPE_REGISTER.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`

This document defines the test strategy for Milestone 4D-3. It follows the same layered
approach established in `docs/MILESTONE_4D_1_TEST_STRATEGY.md` and described in
`docs/MILESTONE_4D_2_DISCOVERY.md §19`. All fixtures are synthetic; no real FDA data,
no real client formulation data, and no real regulatory checklist content is used at any
point in this test suite.

Test file names and locations are proposed here. Final locations are subject to revision
in the implementation specification.

---

## 1. Guiding Principles

These are inherited from the 4D-1 and 4D-2 test strategies and apply equally to 4D-3:

1. **No automatic safety or regulatory-approval conclusion.** No test may assert that a
   populated or computed answer constitutes an automatic determination of safety, FDA
   approval, or excipient acceptability. The closest any test may assert is a specific
   `CalculationStatus` string or a specific `raw_value` shape.

2. **No fabricated pass values.** A blocked calculation (`status != "OK"`) must produce
   `value = None` and a non-empty `reason_code`. No test may accept `0`, an empty string,
   or `"OK"` as a valid representation of a blocked calculation.

3. **`full_clean()` must be invoked.** Every `CalculationOutcome.save()` in the
   population and recalculation paths must call `full_clean()` before `save()`. At least
   one test must prove that a direct `save()` without `full_clean()` on an invalid
   `CalculationOutcome` is caught — i.e., that the guard is actually reachable.

4. **Synthetic fixtures only.** No real `IIDIngredient`, `IIDPrecedentRecord`, or
   `SubstanceSynonymMapping` data is committed to the test database. All test cases use
   synthetic names modeled on the paracetamol/acetaminophen worked example from
   `docs/MILESTONE_4D_DISCOVERY.md §19`.

5. **No formula logic in tests.** Tests do not reimplement any of the six calculation
   formulas. They assert the `CalculationOutcome.value` and `status` returned by the
   production code, not a client-computed expected result.

6. **Planted failures required.** Every blocked-calculation status must have at least one
   test that verifies the blocked result is produced correctly and not silently swallowed
   as a pass.

---

## 2. Unit / Service Tests

### 2a. Applicability runtime evaluator (`test_applicability_evaluator.py`)

Location: `backend/iig_checklist/tests/test_applicability_evaluator.py`

New tests for the `evaluate_condition()` function (S-06, §5 of discovery document):

- `all`-composite with all conditions true → `True`.
- `all`-composite with one condition false → `False`.
- `any`-composite with one condition true → `True`.
- `any`-composite with all conditions false → `False`.
- `eq` on `product.route` matching context value → `True`.
- `eq` on `product.route` not matching → `False`.
- `exists` on `iid.match_status` when context value is not None → `True`.
- `exists` on `iid.match_status` when context value is None → `False`.
- `not_exists` on `iid.has_mde` when context value is None → `True`.
- `gt` / `gte` / `lt` / `lte` on a numeric context field — boundary values.
- Field not present in context → treated as absent/None, not as an error.
- Nested composite (depth > 1): `all` containing an `any` → correct evaluation.
- Maximum-depth tree (depth = 5) evaluates correctly.
- Depth-6 tree was already blocked at validation time (this test confirms the validator
  rejects it; the evaluator is never called on an invalid tree).
- Planted failure: cyclic binding in `calculation_binding` is caught at
  `ChecklistVersion` activation (this test belongs in lifecycle tests — see §2b).

### 2b. Population pass — unit tests (`test_population_service.py`)

Location: `backend/iig_checklist/tests/test_population_service.py`

Tests for the `populate_draft_answers()` service (or equivalent function, per OQ-1):

**FDA_DERIVED_DEFAULT population:**

- A `FDA_DERIVED_DEFAULT` question whose `resolve_substance_identity()` returns an exact
  match: `raw_value` is set to the resolved `IIDIngredient.public_id`; `entered_by` is
  `None` (system-generated); audit event `iig_checklist.response.fda_populated` is
  emitted.
- A `FDA_DERIVED_DEFAULT` question where the substance name has no approved mapping:
  `raw_value = None` (left blank); no `is_not_applicable` set; no fabricated value; an
  appropriate `CalculationStatus` propagates to dependent `SYSTEM_CALCULATED` questions.
- A `FDA_DERIVED_DEFAULT` question where applicability rule evaluates to `False`:
  `is_not_applicable = True` with `not_applicable_reason` set; `raw_value = None`.

**SYSTEM_CALCULATED computation:**

- A `SYSTEM_CALCULATED` question bound to `calculate_percentage_w_w`: when the upstream
  `USER_REQUIRED` quantity is 500 mg and `FormulationVersion.total_dosage_unit_weight` is
  650 mg, `CalculationOutcome.value = Decimal("76.9230769231")` (or the exact
  Decimal output of the production function — the test must use the actual returned value,
  not a hand-computed one), `status = "OK"`.
- A `SYSTEM_CALCULATED` question bound to `calculate_daily_exposure`: 500 mg × 6
  units → `value = Decimal("3000")`, `status = "OK"`.
- A `SYSTEM_CALCULATED` question where an upstream `FDA_DERIVED_DEFAULT` input resolved
  to None (no match): `CalculationOutcome.status = "INGREDIENT_UNRESOLVED"` or the
  correct propagated status; `value = None`.
- A `SYSTEM_CALCULATED` question where `total_dosage_unit_weight = 0` (denominator):
  `status = "BASIS_UNCLEAR"`, `value = None`.
- A `SYSTEM_CALCULATED` question where `max_daily_units` is None:
  `status = "MAX_DAILY_UNITS_MISSING"` (or whatever `CalculationStatus` the calculation
  function returns for this condition), `value = None`.
- `CalculationOutcome.formula_version` is set (not blank) after a successful computation.
- `CalculationOutcome.inputs` and `input_provenance` are non-empty dicts after a
  successful computation.
- `CalculationOutcome.generated_at` is set after a successful computation.
- `CalculationOutcome.source_assessment_snapshot_public_id` is set when the computation
  is derived from an `AssessmentSnapshot`.

**NOT_APPLICABLE propagation:**

- A `SYSTEM_CALCULATED` question whose applicability rule evaluates to `False` (e.g.
  `iid.has_mde = False` and rule requires `iid.has_mde exists`):
  `is_not_applicable = True`, `CalculationOutcome.status` unchanged (stays
  `DATA_REQUIRED`), `not_applicable_reason` is the structured rule identifier.
- A `SYSTEM_CALCULATED` question that is inapplicable vs. one that has missing upstream
  data: these must produce distinguishable `ChecklistResponse` states —
  `is_not_applicable = True` vs. `is_not_applicable = False, CalculationOutcome.status =
  DATA_REQUIRED`.

**Sequencing:**

- `FDA_DERIVED_DEFAULT` answers populated before `SYSTEM_CALCULATED` answers in the same
  pass: a `SYSTEM_CALCULATED` question that depends on a `FDA_DERIVED_DEFAULT` answer has
  a non-null `CalculationOutcome.value` after a single population pass.
- No partial population: if the population pass raises mid-execution, no partial state
  is committed (all writes are inside a single `transaction.atomic()`).

**`full_clean()` enforcement:**

- Direct call to `CalculationOutcome.save()` without `full_clean()` on an instance with
  an invalid `calculation_name` raises `ValidationError` (proves the guard in
  `CalculationOutcome.clean()` is reachable — the `AssessmentSnapshot` defect must not
  recur).

### 2c. Cyclic binding detection (`test_execution_lifecycle.py`, new cases)

- A `ChecklistVersion` with a `calculation_binding` cycle (A depends on B, B depends on
  A) is blocked at activation with a structured error.
- A valid `ChecklistVersion` with no cycle activates normally.
- A `ChecklistVersion` where a `SYSTEM_CALCULATED` question's binding references a
  non-existent question code is blocked at activation.

---

## 3. Recalculation Tests (`test_recalculation.py`)

Location: `backend/iig_checklist/tests/test_recalculation.py`

Tests for the cascade recalculation path triggered by `enter_response()` on `draft`
executions (S-03, S-04):

- `enter_response()` with a `USER_REQUIRED` answer that feeds into one
  `SYSTEM_CALCULATED` question: after the call, the `CalculationOutcome` for that
  question has `status = "OK"` and `value` is non-null.
- `enter_response()` with a `USER_REQUIRED` answer that feeds into two
  `SYSTEM_CALCULATED` questions: both `CalculationOutcome` rows are updated.
- `enter_response()` when the new value produces a blocked calculation (e.g. user sets
  quantity to `None`): `CalculationOutcome.status` becomes the correct blocked status,
  `value = None`.
- No recalculation triggered when execution is `submitted_for_review` (responses are
  locked): any attempted `enter_response()` on a `submitted_for_review` execution returns
  `response_immutable` / 400 (already in 4D-2; this test confirms the 4D-3 recalculation
  path does not bypass this gate).
- Recalculation on a `returned` execution (valid `draft`-equivalent state):
  `enter_response()` succeeds and recalculation runs.
- Concurrent `enter_response()` calls on the same execution: only one succeeds in
  recalculating at a time (serialized by `select_for_update()` on the execution —
  T-06 mitigation). Test using `transaction=True`.
- Atomic rollback: if the calculation step raises an exception after the
  `USER_REQUIRED` write, neither the response update nor the `CalculationOutcome`
  update is committed (full `transaction.atomic()` rollback).

---

## 4. API Tests

### 4a. Execution creation with population (`test_execution_api.py`, extended)

These are extensions to the existing `test_execution_api.py` (4D-2):

- `POST /executions/`: response body includes `CalculationOutcome` embedded or
  retrievable — responses that were `DATA_REQUIRED` pre-population now show a computed
  value (or a blocked status) after the population pass runs at creation.
- `GET /executions/<uuid>/responses/`: each response shows `raw_value` for
  `FDA_DERIVED_DEFAULT` questions (non-null after population).
- `GET /executions/<uuid>/responses/` for a `SYSTEM_CALCULATED` question: response
  includes `CalculationOutcome` sub-representation with `value`, `status`,
  `formula_version`, `calculation_name`.
- `FDA_DERIVED_DEFAULT` response `entered_by` is `null` in the serialized output
  (system-generated, not a user).
- `USER_REQUIRED` question with `prefill_source = "formulation_component"`: response
  `raw_value` is `null` (the prefill is a UI hint, not a server-side pre-fill by the
  population pass; this test guards that the frontend, not the backend, pre-fills these).

### 4b. Recalculation visible through API (`test_response_api.py`, extended)

- `PATCH /executions/<uuid>/responses/<uuid>/` with a `USER_REQUIRED` value: subsequent
  `GET /executions/<uuid>/responses/` shows the updated `CalculationOutcome.value` for
  the dependent `SYSTEM_CALCULATED` question.
- `PATCH` with a value that produces a blocked result: `CalculationOutcome.status` is
  the blocked status string, `value` is null, in the subsequent GET.

### 4c. Audit event verification

- After a population pass, `AuditEvent` of type `iig_checklist.response.fda_populated`
  exists for each `FDA_DERIVED_DEFAULT` question that received a non-null value.
- No `iig_checklist.response.entered` event is emitted for system-populated answers
  (population is not the same as user entry).
- After a recalculation-triggering `PATCH`, audit event `iig_checklist.response.updated`
  exists for the triggering `USER_REQUIRED` response, and no separate event is emitted
  for the system-updated `SYSTEM_CALCULATED` outcomes (calculation updates are internal
  bookkeeping, not governed user actions).

---

## 5. Planted Failure Tests

Every `CalculationStatus` blocked value must have at least one test that verifies it is
produced correctly and surfaced in the API (not silently converted to a pass):

| Status | Condition to plant | Expected `CalculationOutcome` |
|---|---|---|
| `DATA_REQUIRED` | Upstream question not yet answered | `status = "DATA_REQUIRED"`, `value = None` |
| `INGREDIENT_UNRESOLVED` | Substance name has no approved mapping | `status = "INGREDIENT_UNRESOLVED"`, `value = None` |
| `ROUTE_MISMATCH` | Proposed route != IID precedent route | `status = "ROUTE_MISMATCH"`, `value = None` |
| `DOSAGE_FORM_MISMATCH` | Proposed dosage form != IID precedent | `status = "DOSAGE_FORM_MISMATCH"`, `value = None` |
| `UNIT_MISMATCH` | Unit conversion fails (unsupported unit pair) | `status = "UNIT_MISMATCH"`, `value = None` |
| `FDA_VALUE_UNAVAILABLE` | IID precedent has null MDE / potency | `status = "FDA_VALUE_UNAVAILABLE"`, `value = None` |
| `BASIS_UNCLEAR` | `total_dosage_unit_weight = 0` | `status = "BASIS_UNCLEAR"`, `value = None` |
| `NOT_COMPARABLE` | Inputs outside comparison range | `status = "NOT_COMPARABLE"`, `value = None` |
| `REGULATORY_REVIEW_REQUIRED` | FDA release superseded after snapshot taken | `status = "REGULATORY_REVIEW_REQUIRED"`, `value = None` |

Location: `backend/iig_checklist/tests/test_planted_failures_4d3.py`

---

## 6. Frontend Tests

### 6a. Unit/accessibility (Vitest + React Testing Library + jest-axe)

- Execution detail page with a populated `FDA_DERIVED_DEFAULT` answer: renders provenance
  label "FDA-derived"; answer value displayed as read-only.
- Execution detail page with a `SYSTEM_CALCULATED` answer `status = "OK"`: renders
  `CalculationOutcome.value` formatted appropriately.
- Execution detail page with a `SYSTEM_CALCULATED` answer `status = "DATA_REQUIRED"`:
  renders the status code, never `0` or blank.
- Execution detail page with a `SYSTEM_CALCULATED` answer `status = "FDA_VALUE_UNAVAILABLE"`:
  renders the status code with a user-legible label.
- `USER_REQUIRED` question with `prefill_source = "formulation_component"`: renders
  a "Pre-filled from formulation" hint; the input is editable; the provenance label is
  NOT "FDA-derived."
- No formula computation in any frontend component: a code-level test (or linting rule)
  that verifies none of the six calculation function names appear in any frontend source
  file.

### 6b. Playwright E2E

- Create execution → population pass runs → checklist detail shows populated answers.
- Edit a `USER_REQUIRED` field → page reloads → dependent `SYSTEM_CALCULATED` field
  shows updated value from server.
- Blocked calculation scenario: enter a quantity that produces `FDA_VALUE_UNAVAILABLE`
  → `SYSTEM_CALCULATED` question shows the status code, not a number.

---

## 7. Docker Integration Extension

Extend `.github/workflows/docker-integration.yml` with a 4D-3 smoke step:

- Create a `ChecklistExecution` with a `ChecklistVersion` containing a
  `FDA_DERIVED_DEFAULT` question and a `SYSTEM_CALCULATED` question bound to
  `calculate_percentage_w_w`.
- Verify that after creation, the `FDA_DERIVED_DEFAULT` response has a non-null
  `raw_value` (or a documented non-match status).
- Verify that the `SYSTEM_CALCULATED` `CalculationOutcome.status` is either `"OK"` or
  a blocked status string — never `"DATA_REQUIRED"` once the population pass has run.
- Patch the `USER_REQUIRED` quantity → verify the `SYSTEM_CALCULATED` `CalculationOutcome`
  updates in the response list.
- All synthetic data; no real FDA records involved.

---

## 8. Test Coverage and Gate

- Backend coverage gate: existing 55% threshold. 4D-3's new code should be covered at
  the same rate as 4D-2's new code (approximately 90%+ on new lines, per the 92%
  overall rate on `regx-main`).
- Import-linter: all seven existing contracts must continue to pass after 4D-3 additions.
  Verify `formulations` does not import `iig_checklist` (existing contract); verify no
  new reverse imports introduced.
- Ruff lint/format: all 4D-3 code must be clean before any PR opens. No `# noqa`
  suppressions without an explanatory comment.
- OpenAPI schema: must regenerate cleanly with any new endpoints or serializer fields.

---

## 9. What This Test Strategy Explicitly Does Not Cover

- Override/deviation workflow tests (4D-4 scope).
- Export and SHA-256 checksum tests (4D-4 scope).
- Real FDA data ingestion scenarios.
- Production client formulation data scenarios.
- 21 CFR Part 11 electronic signature compliance tests.
- Any test that asserts an automatic safety or approval conclusion.
