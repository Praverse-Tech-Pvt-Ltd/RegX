# Milestone 4D-3 Implementation Specification

**Status: SPECIFICATION COMPLETE. Pending adversarial specification review before implementation.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Scope register:** `docs/MILESTONE_4D_3_SCOPE_REGISTER.md`
**Threat model:** `docs/MILESTONE_4D_3_THREAT_MODEL.md`
**Test strategy:** `docs/MILESTONE_4D_3_TEST_STRATEGY.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`
**Base SHA:** `c0adef4448153368c5bb280219c154f60be052f1` (Milestone 4D-2 merge)
**Discovery head:** `b30fd01`
**Second adversarial discovery review result:** PASS WITH MINOR CORRECTIONS

This document is the normative implementation specification for Milestone 4D-3. It
supersedes the discovery document for all implementation decisions. Requirements use
"shall" for mandatory obligations. Every requirement is uniquely identified with a
stable prefix and number. No implementation code appears in this document. No runtime
behavior is created by this document.

This specification resolves all five minor findings from the second adversarial
discovery review (M-1 through M-5) and makes normative decisions on all deferred
design questions.

---

## Part 1 — Confirmed Scope

### 1.1 In-Scope Items

| ID | Item |
|---|---|
| M4D3-S-001 | Draft-answer generation at execution creation |
| M4D3-S-002 | Automatic `FDA_DERIVED_DEFAULT` population |
| M4D3-S-003 | `SYSTEM_CALCULATED` computation |
| M4D3-S-004 | Synchronous in-draft cascade recalculation |
| M4D3-S-005 | Applicability evaluation required for population |
| M4D3-S-006 | Source snapshot creation and provenance |
| M4D3-S-007 | `CalculationStatus` translation layer |
| M4D3-S-008 | `CalculationOutcome` read-only serialization |
| M4D3-S-009 | `CALCULATION_BINDING_REGISTRY` definition and validation |
| M4D3-S-010 | Required frontend display changes for populated and calculated answers |
| M4D3-S-011 | Dependency graph DAG validation at `ChecklistVersion` activation |
| M4D3-S-012 | Non-overwrite rules for `USER_REQUIRED`, `REVIEWER_CONCLUSION`, and `APPROVAL_METADATA` |
| M4D3-S-013 | Idempotency of repeated population passes with identical inputs |
| M4D3-S-014 | `generated_at` ISO-8601 string parsing and error handling |
| M4D3-S-015 | Reproducibility chain (formula version, registry binding version, stored inputs) |

### 1.2 Explicit Exclusions

| ID | Excluded item | Deferred to |
|---|---|---|
| M4D3-S-016 | Arbitrary formula builder | Never |
| M4D3-S-017 | Tenant-authored executable logic | Never |
| M4D3-S-018 | `eval`, `exec`, dynamic import from user-controlled values | Never |
| M4D3-S-019 | Arbitrary SQL or expression evaluation | Never |
| M4D3-S-020 | Manual override of calculated or FDA-derived values | 4D-4 |
| M4D3-S-021 | Deviation workflow | 4D-4 |
| M4D3-S-022 | Automatic approval based on calculation outcome | Never |
| M4D3-S-023 | Final regulatory conclusion | Never |
| M4D3-S-024 | Finalization workflow | 4D-4 |
| M4D3-S-025 | Report or export generation | 4D-4 |
| M4D3-S-026 | Dashboards | Not in 4D |
| M4D3-S-027 | Push or webhook notifications | Not in 4D |
| M4D3-S-028 | Asynchronous calculation engine (`CALCULATING` status reserved) | Future |
| M4D3-S-029 | New calculation-definition database model | Never in 4D-3 |
| M4D3-S-030 | New database field | Never in 4D-3 |
| M4D3-S-031 | Django migration | Never in 4D-3 |
| M4D3-S-032 | Generic `PATCH` or `PUT` endpoint for `CalculationOutcome` | Never |
| M4D3-S-033 | New calculation formulas beyond the six in `iid_assessment.calculations` | Never in 4D |
| M4D3-S-034 | 4D-4 UI elements (override, deviation, export triggers) | 4D-4 |
| M4D3-S-035 | `CalculationStatus.CALCULATING` ever set by 4D-3 code | Never in 4D-3 |

---

## Part 2 — Data-Model Usage

### 2.1 `ChecklistQuestion`

**M4D3-M-001** `ChecklistQuestion.calculation_binding_identifier` is an existing
`CharField(max_length=100, blank=True)`. It shall store only a short, governed
registry key string (e.g. `"percentage_w_w"`). It shall not store a JSON payload,
executable expression, SQL fragment, or any value not present in the
`CALCULATION_BINDING_REGISTRY` at activation time.

**M4D3-M-002** A `SYSTEM_CALCULATED` question with a blank
`calculation_binding_identifier` shall be rejected by the existing `ChecklistQuestion.clean()`
validation and must not appear in an activated `ChecklistVersion`.

### 2.2 `ChecklistResponse`

**M4D3-M-003** `data_source_type_snapshot` is immutable after creation. No 4D-3
service shall overwrite it.

**M4D3-M-004** `USER_REQUIRED` values (`data_source_type_snapshot = "user_required"`)
shall never be overwritten by the population pass, the recalculation pass, or any
4D-3 service.

**M4D3-M-005** `REVIEWER_CONCLUSION` and `APPROVAL_METADATA` response rows shall
never be touched by any 4D-3 service.

**M4D3-M-006** `FDA_DERIVED_DEFAULT` values written by the population pass may only
be replaced by an explicit governed recalculation call, never by a client PATCH.
`enter_response()` shall reject any PATCH from a `Doer`-level actor on a
`FDA_DERIVED_DEFAULT` response with `error_code = "invalid_raw_value_shape"` / 400.
This check shall be enforced in the service layer, not only in the serializer.

**M4D3-M-007** `SYSTEM_CALCULATED` response `raw_value` shall remain `null` at all
times; calculation results are stored exclusively in `CalculationOutcome`.

**M4D3-M-008** The `is_not_applicable = True` path is exclusive to `NOT_APPLICABLE`
applicability outcomes. The `REVIEW_REQUIRED` applicability outcome shall never set
`is_not_applicable = True`. See §6.3 for the normative `REVIEW_REQUIRED` design.

**M4D3-M-009** When `is_not_applicable = True` is set, `not_applicable_reason` shall
be populated from `ApplicabilityRule.reason_code` (governed structured code,
max 100 characters). `MAX_NOT_APPLICABLE_REASON_CHARS = 200` (verified in
`execution_constants.py`), so no truncation occurs. `full_clean()` shall be called
before every save. **[M-2 resolved: compatible.]**

### 2.3 `CalculationOutcome`

**M4D3-M-010** `CalculationOutcome.status` uses `iig_checklist.enums.CalculationStatus`
choices exclusively: `"data_required"`, `"calculating"`, `"complete"`, `"error"`.
The `"calculating"` value shall never be set by any 4D-3 code path.

**M4D3-M-011** Engine-layer status strings from
`iid_assessment.calculations.CalculationStatus` shall never be written directly to
`CalculationOutcome.status`. The translation function defined in §5 is the only
permitted path.

**M4D3-M-012** `CalculationOutcome.value` shall be `null` whenever
`status = "error"` or `status = "data_required"`. A non-null `value` is only valid
when `status = "complete"`.

**M4D3-M-013** `CalculationOutcome.inputs` and `CalculationOutcome.input_provenance`
shall contain only server-generated values. No client-supplied content shall be
written to these fields. `input_provenance` shall always include a
`"_registry_binding_version"` key set to the binding version of the registry entry
used (see §13).

**M4D3-M-014** `full_clean()` shall be called before every `CalculationOutcome.save()`
in any 4D-3 code path. The `AssessmentSnapshot.clean()` defect (guard unreachable
because `full_clean()` was skipped) must not recur.

**M4D3-M-015** `CalculationOutcome` rows are created by 4D-2 at execution creation
time. 4D-3 shall only update existing rows — never create new ones during population
or recalculation.

### 2.4 `ApplicabilityRule`

**M4D3-M-016** `ApplicabilityRule.condition_json` uses the runtime grammar from
`backend/iig_checklist/applicability.py`: composite nodes are
`{"operator": "all"|"any", "conditions": [...]}` and leaf nodes are
`{"field": ..., "op": ..., "value": ...}`. No other shape is valid. The grammar from
the overarching 4D design document (`{"all": [...]}` / `{"any": [...]}`) is
**not** the runtime contract.

**M4D3-M-017** The `ApplicabilityRule` model has no `condition_checksum` field. All
references to `condition_checksum` in implementation code are forbidden.

**M4D3-M-018** Applicability outcomes shall be read from `ApplicabilityRule.outcome_if_true`
and `ApplicabilityRule.outcome_if_false`. The governed reason for N/A state is
`ApplicabilityRule.reason_code`.

---

## Part 3 — Calculation Binding Registry

### 3.1 Registry Location and Structure

**M4D3-REG-001** The `CALCULATION_BINDING_REGISTRY` shall be a Python `dict`
defined in a new server-side module `backend/iig_checklist/calculation_registry.py`.
It shall be a module-level constant, not a database table. No tenant or client may
add, modify, or inject entries.

**M4D3-REG-002** Each registry entry shall map a short identifier string to a
`TypedDict` (or equivalent dataclass) with the following fields:

| Field | Type | Description |
|---|---|---|
| `function` | `Callable` | Direct reference to one of the six approved calculation functions |
| `binding_version` | `str` | Immutable binding version (see M4D3-REG-003) |
| `formula_version` | `str` | Must equal `iid_assessment.calculations.FORMULA_VERSION` |
| `input_resolvers` | `dict[str, InputResolver]` | Mapping of function kwarg name to resolver specification |
| `dependencies` | `list[str]` | `ChecklistQuestion.code` values whose answers feed this calculation |
| `output_unit` | `str` | Expected unit string (may be empty) |
| `rounding_rule` | `str` | Human-readable rounding description |
| `allowed_answer_type` | `str` | `AnswerType` value expected on the question |
| `allowed_data_source` | `str` | Must be `"system_calculated"` |

**M4D3-REG-003** Each registry entry shall declare an immutable `binding_version`
string (e.g. `"1.0.0"`). This value must be incremented whenever the entry's
`input_resolvers` or `dependencies` change, even if `formula_version` does not
change. The `binding_version` shall be stored in
`CalculationOutcome.input_provenance` under the server-controlled key
`"_registry_binding_version"`. No tenant or client may supply or modify this key.
**[M-1 resolved: registry binding version captured in provenance without a new column.]**

**M4D3-REG-004** Identifier format: short ASCII slug, lowercase letters and
underscores only, maximum 100 characters, compatible with
`CharField(max_length=100)`.

**M4D3-REG-005** Approved identifier values for the current release:

| Identifier | Calculation function |
|---|---|
| `"percentage_w_w"` | `calculate_percentage_w_w` |
| `"daily_exposure"` | `calculate_daily_exposure` |
| `"percentage_of_iid_potency"` | `calculate_percentage_of_potency` |
| `"difference_from_iid_potency"` | `calculate_difference_from_potency` |
| `"percentage_of_iid_mde"` | `calculate_percentage_of_mde` |
| `"difference_from_iid_mde"` | `calculate_difference_from_mde` |

No other identifier is valid in this release.

### 3.2 Input Resolver Specification

**M4D3-REG-006** An `InputResolver` shall be one of two forms:

- **Question resolver:** `{"source": "question", "question_code": "<code>"}` — reads
  `ChecklistResponse.raw_value` for the named question on the current execution.
- **Formulation resolver:** `{"source": "formulation", "field": "<field_name>"}` — reads
  the named field from `FormulationVersion` or `FormulationComponent`.

No other resolver form is valid.

**M4D3-REG-007** Input resolvers shall use only named model fields. No `getattr`
from a user-supplied string, no `eval`, no dynamic import, no `exec`, no SQL
fragment, and no template expression is permitted in any resolver.

### 3.3 Security Requirements

**M4D3-REG-008** All registry lookups shall use `CALCULATION_BINDING_REGISTRY.get(key)`
with explicit `None` handling, never `CALCULATION_BINDING_REGISTRY[key]` without a
try/except that would allow unhandled propagation.

**M4D3-REG-009** An unknown identifier encountered at runtime shall fail closed:
set `CalculationOutcome.status = "error"` and `reason_code = "UNKNOWN_REGISTRY_IDENTIFIER"`.
It shall not raise an unhandled exception that aborts execution creation.

**M4D3-REG-010** A mismatch between the stored identifier and the resolved function
(e.g. after a registry refactor) shall fail closed with the same error as an unknown
identifier.

### 3.4 Activation-Time Validation

**M4D3-REG-011** When a `ChecklistVersion` is activated, the activation service shall
validate every `SYSTEM_CALCULATED` question:

1. `calculation_binding_identifier` is present in `CALCULATION_BINDING_REGISTRY`.
2. All declared `dependencies` (question codes) exist in the same `ChecklistVersion`.
3. No cross-version dependency references exist.
4. The dependency graph forms a DAG (no cycles); see §10.
5. Maximum dependency graph depth does not exceed `MAX_DEPENDENCY_DEPTH`; see §10.

**M4D3-REG-012** Activation shall be rejected with a structured error
(`error_code = "REGISTRY_VALIDATION_FAILED"`, including the specific sub-reason) if
any check in M4D3-REG-011 fails. The `ChecklistVersion` shall remain in its current
pre-activation state.

**M4D3-REG-013** A registry key rename in a new deployment shall require either:
(a) a compatibility alias in the registry mapping the old key to the current entry, or
(b) updating the stored `calculation_binding_identifier` on affected
`ChecklistQuestion` rows via a governed admin operation before the old key is removed.
Silent reinterpretation of an existing identifier is prohibited.

---

## Part 4 — Answer Source Resolver Functions

**M4D3-SVC-001** A new module `backend/iig_checklist/answer_sources.py` shall provide
module-level resolver functions:

```
resolve_fda_derived(
    question: ChecklistQuestion,
    formulation_version: FormulationVersion,
    context: dict,
) -> Any | None
```

```
resolve_identity_match(
    question: ChecklistQuestion,
    formulation_version: FormulationVersion,
) -> IIDIngredient | None
```

**M4D3-SVC-002** The mapping from question code to resolver shall be a small,
explicit dispatch dict in `answer_sources.py`. No dynamic reflection. No `getattr`
from question code. No `eval`.

**M4D3-SVC-003** Resolvers shall call only the following approved read-only services:
`fda_data.substance_matching.resolve_substance_identity()`,
`iid_assessment.matching.find_iid_candidates()`, and direct field access on
`FormulationVersion` / `FormulationComponent` model instances.

**M4D3-SVC-004** Resolvers shall be pure functions. They shall not write to the
database, emit audit events, or alter any Django model instance.

---

## Part 5 — Status Translation Layer

### 5.1 Module Location

**M4D3-TRL-001** The translation function shall live in a dedicated new module
`backend/iig_checklist/calculation_translation.py`. It shall be a pure function
with no database access, no side effects, and 100% branch coverage in tests.

### 5.2 Translation Function Signature

```
def translate_engine_status(
    engine_result: CalculationResult,
) -> tuple[str, str, Decimal | None]:
    """Returns (stored_status, reason_code, value).
    stored_status is always one of the four iig_checklist.enums.CalculationStatus values.
    Never returns an engine-layer string as stored_status.
    Fail-closed: unknown engine status maps to ("error", "UNKNOWN_ENGINE_STATUS", None).
    """
```

### 5.3 Exhaustive Translation Table

**M4D3-TRL-002** The translation function shall implement the following complete
mapping. No default branch may produce `"complete"`. Unknown inputs shall fail
closed to `"error"`.

| Engine result string | Stored `CalculationOutcome.status` | Stored `reason_code` | `value` |
|---|---|---|---|
| `"OK"` | `"complete"` | `""` (blank) | from `engine_result.value` |
| `"DATA_REQUIRED"` | `"data_required"` | `"DATA_REQUIRED"` | `null` |
| `"INGREDIENT_UNRESOLVED"` | `"error"` | `"INGREDIENT_UNRESOLVED"` | `null` |
| `"ROUTE_MISMATCH"` | `"error"` | `"ROUTE_MISMATCH"` | `null` |
| `"DOSAGE_FORM_MISMATCH"` | `"error"` | `"DOSAGE_FORM_MISMATCH"` | `null` |
| `"UNIT_MISMATCH"` | `"error"` | `"UNIT_MISMATCH"` | `null` |
| `"FDA_VALUE_UNAVAILABLE"` | `"error"` | `"FDA_VALUE_UNAVAILABLE"` | `null` |
| `"NOT_COMPARABLE"` | `"error"` | `"NOT_COMPARABLE"` | `null` |
| `"REGULATORY_REVIEW_REQUIRED"` | `"error"` | `"REGULATORY_REVIEW_REQUIRED"` | `null` |
| any other string | `"error"` | `"UNKNOWN_ENGINE_STATUS"` | `null` |

### 5.4 Alias Canonicalization

**M4D3-TRL-003** The following Python class attributes on
`iid_assessment.calculations.CalculationStatus` are aliases. The translation
function shall treat each alias's resolved string value as the canonical form before
applying the table in §5.3.

| Python alias | Resolved string (key in §5.3 table) |
|---|---|
| `CalculationStatus.UNIT_CONVERSION_FAILED` | `"UNIT_MISMATCH"` |
| `CalculationStatus.IID_VALUE_MISSING` | `"FDA_VALUE_UNAVAILABLE"` |
| `CalculationStatus.IID_VALUE_INVALID` | `"FDA_VALUE_UNAVAILABLE"` |
| `CalculationStatus.PROPOSED_VALUE_MISSING` | `"DATA_REQUIRED"` |
| `CalculationStatus.MAX_DAILY_UNITS_MISSING` | `"DATA_REQUIRED"` |
| `CalculationStatus.BASIS_UNCLEAR` | `"NOT_COMPARABLE"` |
| `CalculationStatus.RELEASE_NOT_ACTIVE` | `"REGULATORY_REVIEW_REQUIRED"` |
| `CalculationStatus.RECORD_SUPERSEDED` | `"REGULATORY_REVIEW_REQUIRED"` |

Because the engine stores the resolved string (not the attribute name) in
`CalculationResult.status`, the translation function operates on string values only.
The alias table is informational; the implementation need not enumerate alias names.

### 5.5 Generated-At Failure (M-1 partial)

**M4D3-TRL-004** If `CalculationResult.generated_at` is malformed, empty, or a
naive (timezone-unaware) datetime string, the calculation outcome shall be treated
as an error:

- `CalculationOutcome.status = "error"`
- `CalculationOutcome.reason_code = "INVALID_GENERATED_AT"`
- `CalculationOutcome.value = null`
- `CalculationOutcome.generated_at = null`
- The enclosing `transaction.atomic()` block shall continue (the response row is
  still written; only the calculation outcome is marked error).

This decision replaces the earlier discovery wording that allowed a fallback to
`null` with a logged warning. The normative behavior is an error outcome.
**[generated-at behavior resolved.]**

**M4D3-TRL-005** A valid `CalculationResult.generated_at` ISO-8601 string shall be
parsed to a timezone-aware `datetime` object using Python's standard library before
assignment to `CalculationOutcome.generated_at`. A naive datetime string (no UTC
offset or Z suffix) shall be rejected and treated as malformed (M4D3-TRL-004).
Client-supplied timestamps are prohibited; this field is populated exclusively from
calculation function output.

---

## Part 6 — Applicability Runtime Evaluator

### 6.1 Module Location

**M4D3-APP-001** The runtime evaluator shall be a new function
`evaluate_applicability(rule: ApplicabilityRule, context: dict) -> str` added to
`backend/iig_checklist/applicability.py`. It shall be a pure function with no
database access, no side effects, no `eval`, no `exec`, and no dynamic attribute
access.

### 6.2 Grammar and Evaluation

**M4D3-APP-002** The evaluator shall mirror the grammar enforced by the existing
`validate_condition_json()` validator exactly:

- **Composite node:** `{"operator": "all"|"any", "conditions": [<node>, ...]}`
- **Leaf node:** `{"field": "<name>", "op": "<op>", "value": <v>}` (no `"value"` key
  for `exists`/`not_exists`)

Any node not matching one of these shapes is a validator defect and shall raise a
`RuntimeError` (not a `ValidationError`) to distinguish a runtime-vs-validation
contract breach.

**M4D3-APP-003** The evaluator shall use the same operator dispatch table as the
validator: `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists`, `gt`, `gte`, `lt`,
`lte` on `all`/`any` composites.

**M4D3-APP-004** If the evaluated condition is `True`, the evaluator shall return
`rule.outcome_if_true`. If `False`, it shall return `rule.outcome_if_false`. The
return value shall be one of the `ApplicabilityOutcome` choices: `"applicable"`,
`"not_applicable"`, or `"review_required"`.

**M4D3-APP-005** A missing field in the context dict shall be treated as absent:
`None` for existence checks; an absent value for comparison checks (comparison
returns `False`).

### 6.3 Outcome Consumption

#### 6.3.1 `APPLICABLE`

**M4D3-APP-006** When `evaluate_applicability()` returns `"applicable"`:
- `ChecklistResponse.is_not_applicable` shall remain `False`.
- `ChecklistResponse.not_applicable_reason` shall not be set.
- Population and calculation shall proceed normally for this question.

#### 6.3.2 `NOT_APPLICABLE`

**M4D3-APP-007** When `evaluate_applicability()` returns `"not_applicable"`:
- `ChecklistResponse.is_not_applicable` shall be set to `True`.
- `ChecklistResponse.not_applicable_reason` shall be set to the value of
  `ApplicabilityRule.reason_code` (verified max 100 chars; fits within
  `MAX_NOT_APPLICABLE_REASON_CHARS = 200`).
- Population of `raw_value` for this question shall not proceed.
- If the response already has a non-null `raw_value` from a prior user entry, the
  transition shall create a `ChecklistResponseHistory` row before overwriting the
  response state. The prior `raw_value`, `is_not_applicable`, and version shall be
  preserved in the history row. This write shall be atomic with the response update.
- Audit shall be emitted via `transaction.on_commit()` after the transaction commits.

#### 6.3.3 `REVIEW_REQUIRED`

**M4D3-APP-008** `REVIEW_REQUIRED` is a derived, recomputed state. It shall **not**
be stored in any `ChecklistResponse` field. **[REVIEW_REQUIRED persistence resolved:
no new database field; state recomputed at read time.]**

**M4D3-APP-009** When `evaluate_applicability()` returns `"review_required"` during
the population pass:
- `ChecklistResponse.is_not_applicable` shall remain `False`.
- `ChecklistResponse.not_applicable_reason` shall not be modified.
- `ChecklistResponse.raw_value` shall remain unchanged.
- No `FDA_DERIVED_DEFAULT` population or `SYSTEM_CALCULATED` computation shall
  proceed for this question.

**M4D3-APP-010** At API read time, the execution response serializer shall
re-evaluate the `ApplicabilityRule` for each question against the assembled context
and include a derived read-only field `applicability_outcome` in the response
representation. Valid values: `"applicable"`, `"not_applicable"`,
`"review_required"`, `"no_rule"` (when no `ApplicabilityRule` is linked). This field
shall not be writable by any client.

**M4D3-APP-011** A client PATCH shall never be able to forge a `"review_required"`
applicability outcome. The state is derived from the governed `ApplicabilityRule` row
and the assembled context, never from client input.

**M4D3-APP-012** The frontend shall display "Review required" visibly when
`applicability_outcome = "review_required"`. The question shall not be displayed as
applicable or not-applicable. No population value shall be displayed.

### 6.4 Context Assembly

**M4D3-APP-013** The applicability context dict shall be assembled from:
- `FormulationVersion` fields: `product.route`, `product.dosage_form`,
  `product.release_type`.
- FDA match result fields from `run_preview()` / `find_iid_candidates()`:
  `iid.match_status`, `iid.has_mde`, `iid.has_potency`.

**M4D3-APP-014** Context assembly shall happen once per population pass. The context
dict is an in-memory value; it shall not be stored in the database.

---

## Part 7 — Population Pass

### 7.1 Pass Sequence

**M4D3-POP-001** The population pass at execution creation shall execute the
following steps inside a single `transaction.atomic()` block:

1. Create the `ChecklistExecution` and pre-create all `ChecklistResponse` and
   `CalculationOutcome` rows (existing 4D-2 behavior; unchanged).
2. Assemble the applicability context dict (M4D3-APP-013).
3. For each question in the version (in defined display order):
   a. If an `ApplicabilityRule` is linked, call `evaluate_applicability()`.
   b. If outcome is `"not_applicable"`: apply M4D3-APP-007; skip steps 4–6 for
      this question.
   c. If outcome is `"review_required"`: apply M4D3-APP-009; skip steps 4–6 for
      this question.
   d. If outcome is `"applicable"` or no rule: continue.
4. For all `FDA_DERIVED_DEFAULT` questions that passed applicability: call resolver
   functions (M4D3-SVC-001) to populate `raw_value`; if resolver returns `None`,
   leave `raw_value = null` with no error.
5. For all `SYSTEM_CALCULATED` questions that passed applicability and whose
   upstream inputs are now non-null: look up the registry entry, resolve inputs,
   call the calculation function, run the translation function, produce
   `(stored_status, reason_code, value)`.
6. For each `CalculationOutcome` to be updated: populate all fields, call
   `full_clean()`, then `save()`.
7. After the `transaction.atomic()` block commits, emit audit events via
   `transaction.on_commit()`.

**M4D3-POP-002** Step 4 shall complete for all eligible questions before step 5
begins. This order is deterministic: `FDA_DERIVED_DEFAULT` values that feed
`SYSTEM_CALCULATED` calculations are resolved first.

**M4D3-POP-003** The entire population pass (steps 1–7) shall occur within the same
`transaction.atomic()`. If any step raises an uncaught exception, the full
transaction shall roll back. No partial population state shall be committed.

### 7.2 Non-Overwrite Rules

**M4D3-POP-004** The population pass shall never overwrite a `ChecklistResponse`
whose `data_source_type_snapshot = "user_required"` that already has a non-null
`raw_value`.

**M4D3-POP-005** The population pass shall never touch responses with
`data_source_type_snapshot` in `{"reviewer_confirmed", "approval_metadata"}`.

**M4D3-POP-006** An execution whose status is not in `{"draft", "returned"}` shall
reject any population or recalculation call. The service shall raise a
`ValueError` with `error_code = "execution_not_recalculable"`.

### 7.3 Idempotency

**M4D3-POP-007** Re-running the population pass with identical inputs (same
`FormulationVersion`, same active FDA release, same `AssessmentSnapshot`) shall
produce no new `ChecklistResponseHistory` rows.

**M4D3-POP-008** Re-running with identical calculation inputs shall not increment
`ChecklistResponse.version`.

**M4D3-POP-009** Re-running with identical inputs shall not emit any audit event.

**M4D3-POP-010** Re-running with identical inputs shall not modify
`CalculationOutcome.inputs`, `input_provenance`, or `source_assessment_snapshot_public_id`.

### 7.4 Audit Events

**M4D3-POP-011** For each `FDA_DERIVED_DEFAULT` question that received a non-null
`raw_value` from the population pass, a single audit event
`iig_checklist.response.fda_populated` shall be emitted via `transaction.on_commit()`.

**M4D3-POP-012** No `iig_checklist.response.entered` event shall be emitted for
system-populated answers. The distinction between system-generated and user-entered
values must be auditable through the event type alone.

**M4D3-POP-013** For each `SYSTEM_CALCULATED` question whose `CalculationOutcome`
is updated from `"data_required"` to a new status, a single audit event
`iig_checklist.calculation.completed` (status = `"complete"`),
`iig_checklist.calculation.data_required` (status = `"data_required"` with reason),
or `iig_checklist.calculation.error` (status = `"error"` with reason) shall be
emitted via `transaction.on_commit()`.

---

## Part 8 — Cascade Recalculation

**M4D3-RCL-001** The 4D-3 implementation shall extend `enter_response()` to trigger
cascade recalculation on every `USER_REQUIRED` or `EVIDENCE_DERIVED` answer update
on a `draft` or `returned` execution.

**M4D3-RCL-002** The recalculation sequence within `enter_response()` shall:

1. Acquire `select_for_update()` on the `ChecklistExecution` row before reading any
   `ChecklistResponse` values used as calculation inputs.
2. Write and validate the triggering `USER_REQUIRED`/`EVIDENCE_DERIVED` response.
3. Using the `CALCULATION_BINDING_REGISTRY`, identify all `SYSTEM_CALCULATED`
   questions whose declared `dependencies` include the updated question code.
4. Process affected questions in stable topological order (M4D3-DAG-004).
5. Re-run the calculation and translation for each affected question.
6. Call `full_clean()` and update the `CalculationOutcome` row in place.
7. All writes shall be inside a single `transaction.atomic()`.
8. Emit audit events via `transaction.on_commit()` after the transaction commits.

**M4D3-RCL-003** A recalculation audit event `iig_checklist.calculation.recalculated`
shall be emitted for each `CalculationOutcome` that changes value or status.
No event shall be emitted if the result is identical to the prior outcome.

**M4D3-RCL-004** The recalculation loop shall include a defensive visited-set cycle
check. If the loop attempts to visit a question already in the visited set, it shall
set that question's `CalculationOutcome.status = "error"`,
`reason_code = "CYCLE_DETECTED"`, and stop further cascade.

---

## Part 9 — Transactions and Locking

**M4D3-TXN-001** The required lock acquisition order is:
1. `ChecklistExecution` row (via `select_for_update()`).
2. Affected `ChecklistResponse` rows in ascending primary-key order.
3. `CalculationOutcome` rows in ascending primary-key order.

This order shall be respected without exception to prevent deadlocks.

**M4D3-TXN-002** The user response update and all dependent `CalculationOutcome`
updates shall occur inside the same `transaction.atomic()` block.

**M4D3-TXN-003** A stale `expected_version` value on an `enter_response()` call
(optimistic lock check: `ChecklistResponse.version != expected_version`) shall be
rejected with `error_code = "stale_version"` / 409 before any write occurs. No
partial state shall be committed on a stale-version rejection.

**M4D3-TXN-004** If any step of the recalculation raises an exception after the
triggering response has been written, the full `transaction.atomic()` block shall
roll back — both the response update and all `CalculationOutcome` updates.

**M4D3-TXN-005** Audit events shall be emitted via `transaction.on_commit()`.
No success audit event shall fire after a transaction rollback.

**M4D3-TXN-006** History and outcome writes shall be atomic with the response
update. No history row shall be visible without its corresponding response state.

**M4D3-TXN-007** Concurrent `enter_response()` calls on the same execution shall
be serialized by the `select_for_update()` on `ChecklistExecution`. A second call
must wait for the first to commit before it can acquire the lock.

---

## Part 10 — Dependency Graph

### 10.1 Numeric Limits

**M4D3-DAG-001** The following concrete limits shall be enforced. Rationale: the
approved registry contains six formulas with known, bounded input patterns; a depth
of 5 accommodates any plausible chain while protecting against runaway cascade; a
cascade node count of 10 accommodates all six formulas with buffer.

| Constant | Value | Enforced at |
|---|---|---|
| `MAX_DEPENDENCY_DEPTH` | 5 | `ChecklistVersion` activation |
| `MAX_CASCADE_NODES` | 10 | `ChecklistVersion` activation; runtime defensive check |

**M4D3-DAG-002** A `ChecklistVersion` whose dependency graph has any path longer
than `MAX_DEPENDENCY_DEPTH` shall be rejected at activation with
`error_code = "DEPENDENCY_DEPTH_EXCEEDED"`.

**M4D3-DAG-003** A `ChecklistVersion` whose dependency graph has more than
`MAX_CASCADE_NODES` total `SYSTEM_CALCULATED` nodes reachable from any single
question shall be rejected at activation with
`error_code = "CASCADE_NODE_COUNT_EXCEEDED"`.

### 10.2 DAG Validation

**M4D3-DAG-004** Stable topological ordering shall be produced using Kahn's algorithm
(or equivalent iterative algorithm; no recursion without a depth bound). Where two
nodes have equal topological precedence (no dependency between them), alphabetical
`code` order shall be the tiebreaker, ensuring deterministic output across repeated
invocations with identical graphs.

**M4D3-DAG-005** A cycle in the dependency graph shall be rejected at activation with
`error_code = "DEPENDENCY_CYCLE"` naming the questions involved.

**M4D3-DAG-006** A declared dependency referencing a `ChecklistQuestion.code` that
does not exist in the same `ChecklistVersion` shall be rejected at activation with
`error_code = "UNKNOWN_DEPENDENCY_CODE"`.

**M4D3-DAG-007** Cross-version dependency references (a dependency code that exists
in a different `ChecklistVersion`) are prohibited. Only question codes within the
same version are valid dependencies.

**M4D3-DAG-008** At runtime, the recalculation loop shall maintain a `visited` set.
Entering a node already in `visited` triggers the cycle-detected error (M4D3-RCL-004).
This defensive check applies even after activation-time validation passes.

---

## Part 11 — FDA Source Resolution

**M4D3-SRC-001** At population time, the system shall call `run_preview()` against
the currently active FDA release for the current `(FormulationComponent,
active_release)` tuple (live-first design; OQ-4 resolved).

**M4D3-SRC-002** Every `AssessmentSnapshot` lookup shall include
`tenant = execution.tenant` as a mandatory filter. A snapshot belonging to another
tenant shall never be used as the source for any calculation.

**M4D3-SRC-003** The result of `run_preview()` shall be frozen as an
`AssessmentSnapshot` (reusing an exact existing match for this
`(FormulationComponent, active_release, tenant)` tuple if one exists; creating a new
one otherwise). `CalculationOutcome.source_assessment_snapshot_public_id` shall be
set to the resulting snapshot's `public_id` unconditionally.

**M4D3-SRC-004** If `run_preview()` returns no match (`None` or empty candidates),
the relevant calculation inputs shall be `None`. The calculation shall proceed
(returning `DATA_REQUIRED` or `INGREDIENT_UNRESOLVED`); the snapshot shall still be
created (recording the no-match result).

**M4D3-SRC-005** If `run_preview()` returns multiple candidates, the governed
precedent-selection logic from `iid_assessment` shall select the active record. 4D-3
shall not implement its own selection logic.

**M4D3-SRC-006** Once an execution is submitted for review or moves to a terminal or
locked status, `CalculationOutcome.source_assessment_snapshot_public_id` shall not
be updated even if the underlying FDA release changes.

**M4D3-SRC-007** A change to the active FDA release after population shall not
automatically recalculate any existing `ChecklistExecution`. Only explicit
re-population (on a `draft` or `returned` execution, initiated by an authorized
actor) shall update the snapshot reference.

**M4D3-SRC-008** FDA data models (`fda_data` app) are platform-level. The
import-linter contract (`iig_checklist` may import `fda_data` read-only services)
shall remain unchanged. No 4D-3 code shall write to `fda_data` models.

---

## Part 12 — Reproducibility Chain (M-1 Resolution)

**M4D3-PRV-001** **[M-1 resolved.]** No new database column shall be added for
registry versioning. The approved reproducibility chain for each `CalculationOutcome`
consists of:

1. `CalculationOutcome.calculation_name` — identifies the approved function.
2. `CalculationOutcome.formula_version` — captures the mathematical formula version
   (from `iid_assessment.calculations.FORMULA_VERSION`).
3. `CalculationOutcome.inputs` — exact inputs passed to the calculation function,
   keyed by kwarg name.
4. `CalculationOutcome.input_provenance` — source descriptors for each input,
   including `"_registry_binding_version"` (M4D3-REG-003).
5. `CalculationOutcome.rounding_rule` — rounding descriptor from the registry entry.
6. `CalculationOutcome.generated_at` — timezone-aware UTC datetime of computation.
7. `CalculationOutcome.source_assessment_snapshot_public_id` — UUID of the
   `AssessmentSnapshot` used (where applicable).
8. Immutable deployed code version from source control and release metadata.

**M4D3-PRV-002** `input_provenance` shall always include:

```json
{
  "_registry_binding_version": "<binding_version from registry entry>",
  "<kwarg_name>": {
    "source": "question" | "formulation",
    "question_code": "<code>" | null,
    "field": "<field_name>" | null
  },
  ...
}
```

**M4D3-PRV-003** A missing or unrecognized `_registry_binding_version` in
`input_provenance` at read time shall be logged as a data-integrity warning. It
shall not cause a runtime error on read, but shall be flagged in monitoring.

**M4D3-PRV-004** Changing `input_resolvers` or `dependencies` for a registry entry
requires incrementing `binding_version`. This constraint shall be documented in the
registry module docstring and enforced by code review. No database-level enforcement
is required.

---

## Part 13 — Serialization

### 13.1 `CalculationOutcome` Read-Only Nested Representation

**M4D3-SER-001** The `CalculationOutcome` shall be serialized as a read-only nested
object in the execution response-list and response-detail API. The exact approved
fields are:

| API field | Source | Notes |
|---|---|---|
| `public_id` | `CalculationOutcome.public_id` | UUID |
| `calculation_name` | `CalculationOutcome.calculation_name` | Governed function name |
| `formula_version` | `CalculationOutcome.formula_version` | e.g. `"1.0.0"` |
| `status` | `CalculationOutcome.status` | One of the four stored values |
| `value` | `CalculationOutcome.value` | `null` when not complete |
| `unit` | `CalculationOutcome.unit` | May be blank |
| `reason_code` | `CalculationOutcome.reason_code` | Blank when complete |
| `rounding_rule` | `CalculationOutcome.rounding_rule` | |
| `generated_at` | `CalculationOutcome.generated_at` | ISO-8601 UTC string or `null` |
| `source_assessment_snapshot_public_id` | `CalculationOutcome.source_assessment_snapshot_public_id` | UUID or `null` |
| `provenance_summary` | derived | See M4D3-SER-002 |
| `registry_binding_version` | from `input_provenance["_registry_binding_version"]` | String or `null` |

**M4D3-SER-002** `provenance_summary` shall be a server-assembled read-only object
containing only sanitized, approved labels:

```json
{
  "formula_version": "<version>",
  "registry_binding_version": "<version>",
  "source_snapshot_id": "<uuid or null>",
  "input_labels": {
    "<kwarg_name>": "<source label, e.g. 'from question Q_QUANTITY_PER_UNIT'>"
  }
}
```

`inputs` and `input_provenance` raw dicts shall **not** be exposed to the client.
Internal IDs, storage paths, registry function references, and cross-tenant metadata
shall not appear.

**M4D3-SER-003** The `CalculationOutcome` serializer shall be read-only. No
`create`, `update`, or `partial_update` method shall be defined on it.

**M4D3-SER-004** `applicability_outcome` shall be included as a derived read-only
field in the `ChecklistResponse` serialized representation. See M4D3-APP-010.

**M4D3-SER-005** Frontend DTO mapping shall remain centralized in a single mapper
module. No calculation value shall be locally recomputed or overridden on the client
side. No generic calculation PATCH endpoint shall be exposed.

**M4D3-SER-006** The OpenAPI schema for `CalculationOutcome.status` shall enumerate
only the four stored choices: `"data_required"`, `"calculating"`, `"complete"`,
`"error"`. Engine strings shall not appear in the schema.

---

## Part 14 — Audit Events

**M4D3-AUD-001** All 4D-3 audit events shall be dispatched via
`transaction.on_commit()`. No audit event shall be emitted before the enclosing
transaction commits.

**M4D3-AUD-002** Audit payloads shall include:
- Execution `public_id`
- Response `public_id`
- `CalculationOutcome.public_id` (where applicable)
- Prior and new `ChecklistResponse.version`
- `calculation_name`
- `formula_version`
- `registry_binding_version` (from `input_provenance`)
- Stored `status` (model enum value, not engine string)
- `reason_code`
- `source_assessment_snapshot_public_id` (where applicable)

**M4D3-AUD-003** Audit payloads shall exclude:
- Raw `raw_value` answer text
- Full `inputs` dict
- Full `input_provenance` dict
- Internal database PKs
- Storage paths
- Cross-tenant metadata

**M4D3-AUD-004** Defined event names and trigger conditions:

| Event name | Trigger |
|---|---|
| `iig_checklist.response.fda_populated` | FDA_DERIVED_DEFAULT answer written by population pass |
| `iig_checklist.calculation.completed` | `CalculationOutcome.status` transitions to `"complete"` |
| `iig_checklist.calculation.data_required` | `CalculationOutcome.status` set/remains `"data_required"` with a `reason_code` |
| `iig_checklist.calculation.error` | `CalculationOutcome.status` set to `"error"` |
| `iig_checklist.calculation.recalculated` | `CalculationOutcome` updated during cascade recalculation with any changed field |
| `iig_checklist.response.applicability_changed` | `is_not_applicable` transitions (NOT_APPLICABLE outcome) |
| `iig_checklist.response.review_required` | Applicability evaluator returns `"review_required"` |

**M4D3-AUD-005** No audit event shall be emitted for a recalculation that produces
no change to `status`, `value`, `reason_code`, or `generated_at`.

---

## Part 15 — API and Frontend

### 15.1 API Requirements

**M4D3-API-001** No new generic write endpoint for `CalculationOutcome` shall be
introduced. Any request to PATCH or PUT a `CalculationOutcome` resource shall return
404 or 405.

**M4D3-API-002** The existing execution response-list and response-detail endpoints
shall be extended to include the nested `CalculationOutcome` serialization (M4D3-SER-001)
and the `applicability_outcome` derived field (M4D3-SER-004).

**M4D3-API-003** Tenant lookup shall filter by `execution.tenant` before any
`CalculationOutcome` or `AssessmentSnapshot` is accessed. Cross-tenant access shall
return 404 (not 403) to avoid tenant-existence probing.

**M4D3-API-004** Requests from an in-tenant actor without the required permission
shall return 403, consistent with the existing 4D-2 pattern.

**M4D3-API-005** Terminal-status executions (`approved`, `rejected`, `cancelled`,
`superseded`) shall be read-only. PATCH requests on response rows of terminal
executions shall return 400 with `error_code = "response_immutable"`.

**M4D3-API-006** Stale `expected_version` on `enter_response()` shall return 409
with `error_code = "stale_version"`.

**M4D3-API-007** Pagination contract shall remain unchanged. No new pagination
parameters are introduced.

### 15.2 Frontend Requirements

**M4D3-FE-001** The frontend shall display each question's answer with its
`data_source_type_snapshot` provenance label:
- `FDA_DERIVED_DEFAULT` → "FDA-derived" badge (read-only).
- `SYSTEM_CALCULATED` → see M4D3-FE-002.
- `USER_REQUIRED` with `prefill_source` → "Pre-filled from formulation" hint (editable).
- `REVIEWER_CONFIRMED` → "Reviewer confirmed" label.

**M4D3-FE-002** For `SYSTEM_CALCULATED` questions:
- When `CalculationOutcome.status = "complete"`: display `value` and `unit`.
- When `status = "data_required"` or `"error"`: display the `reason_code` string
  with a user-legible label. Never display `0`, blank, or the word `"complete"`.

**M4D3-FE-003** When `applicability_outcome = "review_required"`: display "Review
required" label. The question shall not be shown as applicable or not-applicable.
No population value shall be displayed.

**M4D3-FE-004** No frontend component shall implement any of the six calculation
formulas. A CI lint rule shall verify that none of the six calculation function
names (`calculate_percentage_w_w`, `calculate_daily_exposure`,
`calculate_percentage_of_potency`, `calculate_difference_from_potency`,
`calculate_percentage_of_mde`, `calculate_difference_from_mde`) appear in any
frontend source file.

**M4D3-FE-005** After a user edits a `USER_REQUIRED` field, the frontend shall
reload the execution response list from the server. It shall not compute any
calculation result locally.

**M4D3-FE-006** The frontend DTO mapper shall be centralized. No calculation-related
mapping shall be duplicated across components.

---

## Part 16 — Security Requirements

**M4D3-SEC-001** No `eval`, `exec`, `importlib.import_module()` from a registry key,
`getattr()` from an untrusted string, SQL fragment, or arbitrary expression shall
appear in any 4D-3 service, resolver, evaluator, or registry lookup.

**M4D3-SEC-002** Tenant isolation shall be enforced at every data access point: all
`AssessmentSnapshot`, `ChecklistExecution`, `ChecklistResponse`, and
`CalculationOutcome` queries shall include a tenant filter.

**M4D3-SEC-003** `enter_response()` shall reject any `raw_value` for a
`FDA_DERIVED_DEFAULT` question from a non-override actor at the service layer. The
serializer-level check is insufficient alone.

**M4D3-SEC-004** No calculation result stored as `status = "complete"` shall result
from a translation path that passes through any unknown or unrecognized engine status.

**M4D3-SEC-005** The `_registry_binding_version` key in `input_provenance` is
server-controlled. Any request that supplies or modifies this key shall be rejected.

**M4D3-SEC-006** The import-linter contracts from 4D-1 and 4D-2 shall remain
unchanged: `iig_checklist` may import from `fda_data`, `formulations`,
`iid_assessment`, and `documents` (read-only services). None of those four apps
may import back into `iig_checklist`.

---

## Part 17 — Migration and Compatibility

**M4D3-MIG-001** No Django migration shall be created by 4D-3.

**M4D3-MIG-002** No new database field shall be added by 4D-3.

**M4D3-MIG-003** No backfill of existing `CalculationOutcome` rows shall be
performed during deployment.

**M4D3-MIG-004** Existing 4D-2 `CalculationOutcome` rows with
`status = "data_required"` are valid and remain compatible.

**M4D3-MIG-005** Deployment of 4D-3 shall not automatically recalculate any
existing `ChecklistExecution`.

**M4D3-MIG-006** Historical `approved`, `rejected`, `cancelled`, and `superseded`
executions shall be unchanged by the 4D-3 deployment.

**M4D3-MIG-007** An unknown legacy `calculation_binding_identifier` on an existing
`ChecklistQuestion` (e.g. from a pre-4D-3 record that was never activation-validated)
shall fail closed at runtime with `status = "error"`,
`reason_code = "UNKNOWN_REGISTRY_IDENTIFIER"`. It shall not raise an unhandled
exception.

**M4D3-MIG-008** A registry key rename in a new deployment requires a compatibility
alias (M4D3-REG-013) or a governed admin operation. Silent reinterpretation is
prohibited.

**M4D3-MIG-009** Rollback of the 4D-3 deployment requires no data transformation.
The 4D-2 schema is unchanged; reverting to the 4D-2 codebase restores the prior
behavior.

**M4D3-MIG-010** The API remains backward compatible. No existing 4D-2 response
field is removed or renamed. New nested fields are additions only.

---

## Part 18 — Test Gates

### 18.1 Mandatory Test Requirements

**M4D3-TST-001** Translation function: 100% branch coverage. Every engine status
string (including all aliases) has a dedicated unit test.

**M4D3-TST-002** Unknown engine status → `"error"` / `"UNKNOWN_ENGINE_STATUS"`. Must
never produce `"complete"`.

**M4D3-TST-003** Direct assignment of any engine string to `CalculationOutcome.status`
followed by `full_clean()` raises `ValidationError`.

**M4D3-TST-004** `full_clean()` on a translated `"complete"` outcome does not raise
`ValidationError`. Same for `"error"` and `"data_required"` outcomes.

**M4D3-TST-005** `value = null` for all non-`"complete"` translated outcomes.

**M4D3-TST-006** `"calculating"` is never produced by any 4D-3 code path.

**M4D3-TST-007** Evaluator: APPLICABLE → population proceeds; `is_not_applicable`
remains `False`.

**M4D3-TST-008** Evaluator: NOT_APPLICABLE → `is_not_applicable = True`;
`not_applicable_reason = rule.reason_code`; population skipped.

**M4D3-TST-009** Evaluator: REVIEW_REQUIRED → `is_not_applicable` remains `False`;
`raw_value` unchanged; population skipped; API returns
`applicability_outcome = "review_required"`.

**M4D3-TST-010** REVIEW_REQUIRED cannot be forged: client PATCH cannot produce
`applicability_outcome = "review_required"`. The field is read-only and derived.

**M4D3-TST-011** **[M-3 resolved.]** Activation of a `ChecklistVersion` whose
dependency graph exceeds `MAX_DEPENDENCY_DEPTH = 5` is rejected with
`error_code = "DEPENDENCY_DEPTH_EXCEEDED"`.

**M4D3-TST-012** Activation of a `ChecklistVersion` with a cycle is rejected with
`error_code = "DEPENDENCY_CYCLE"`.

**M4D3-TST-013** Activation of a `ChecklistVersion` with an unknown
`calculation_binding_identifier` is rejected.

**M4D3-TST-014** Activation of a `ChecklistVersion` with a dependency referencing a
non-existent question code is rejected.

**M4D3-TST-015** **[M-4 resolved.]** A known multi-node, multi-branch dependency
graph (at least three nodes with equal-priority alternatives) produces identical
stable topological ordering across at least 10 repeated invocations of the ordering
function with identical inputs.

**M4D3-TST-016** **[M-5 resolved.]** When an existing `ChecklistResponse` with a
non-null `raw_value` transitions to `NOT_APPLICABLE` (applicability rule returns
`"not_applicable"`): a `ChecklistResponseHistory` row is created within the same
transaction; the prior `raw_value` is preserved in `prior_raw_value`; the prior
`version` is preserved; the response `is_not_applicable = True` and
`not_applicable_reason = rule.reason_code` in the same transaction; no regulated
value is lost; audit is emitted via `transaction.on_commit()`.

**M4D3-TST-017** **[stale expected_version test.]** A PATCH to `enter_response()`
with `expected_version` that does not match the current `ChecklistResponse.version`
returns 409 / `error_code = "stale_version"`. No response row is modified.

**M4D3-TST-018** Registry binding version stored in
`input_provenance["_registry_binding_version"]` after a successful computation.

**M4D3-TST-019** Malformed `generated_at` string from calculation result produces
`CalculationOutcome.status = "error"`, `reason_code = "INVALID_GENERATED_AT"`,
`generated_at = null`.

**M4D3-TST-020** Naive datetime string (no UTC offset) from calculation result
produces the same error outcome as M4D3-TST-019.

**M4D3-TST-021** FDA_DERIVED_DEFAULT resolver returns non-null; `entered_by = null`;
audit event `iig_checklist.response.fda_populated` emitted after commit.

**M4D3-TST-022** FDA_DERIVED_DEFAULT resolver returns `None`; `raw_value = null`;
no `is_not_applicable` set; no error.

**M4D3-TST-023** SYSTEM_CALCULATED population: valid inputs → `status = "complete"`;
`reason_code = ""`; `value = non-null Decimal`; `formula_version` set.

**M4D3-TST-024** SYSTEM_CALCULATED population: missing upstream input →
`status = "data_required"`; `reason_code = "DATA_REQUIRED"`; `value = null`.

**M4D3-TST-025** Source snapshot belongs to the correct tenant; a snapshot from
another tenant is not reused.

**M4D3-TST-026** Re-running population with identical inputs produces no new
`ChecklistResponseHistory` rows and does not increment `ChecklistResponse.version`.

**M4D3-TST-027** USER_REQUIRED value not overwritten by population pass.

**M4D3-TST-028** Population pass rejected on `submitted_for_review` execution with
`error_code = "execution_not_recalculable"`.

**M4D3-TST-029** No partial population committed if population pass raises mid-pass.

**M4D3-TST-030** Cascade recalculation: USER_REQUIRED update triggers SYSTEM_CALCULATED
update in same transaction; `status = "complete"` and `value` non-null.

**M4D3-TST-031** Concurrent `enter_response()` calls serialized by execution lock;
no duplicate `CalculationOutcome` state.

**M4D3-TST-032** Atomic rollback: if calculation step raises after response write,
neither response nor `CalculationOutcome` is committed.

**M4D3-TST-033** Recalculation emits no audit event when outcome is unchanged.

**M4D3-TST-034** Historical approved execution is unchanged after FDA source refresh.

**M4D3-TST-035** API: `GET` on response detail returns `CalculationOutcome` nested
with all M4D3-SER-001 fields present.

**M4D3-TST-036** API: `PATCH` to `CalculationOutcome` resource returns 404 or 405.

**M4D3-TST-037** Frontend: no calculation formula name appears in any frontend source
file (CI lint assertion).

**M4D3-TST-038** `full_clean()` guard reachable: direct invalid `CalculationOutcome`
save raises `ValidationError`.

**M4D3-TST-039** Planted-failure suite: every engine result string has one test
verifying correct stored `(status, reason_code, value)` triple including that
`value = null` for all non-complete rows (see §5 of the test strategy).

**M4D3-TST-040** Import-linter: all existing contracts pass after 4D-3 additions;
no new reverse imports.

### 18.2 Implementation Sign-Off Gates

Before any 4D-3 implementation PR may be opened, all of the following must pass in
CI:

1. Targeted new 4D-3 backend test suite (M4D3-TST-001 through M4D3-TST-039).
2. Full existing backend test suite (no regressions).
3. Backend coverage ≥ 55% overall; new 4D-3 code ≈ 90%+ on new lines.
4. Translation function: 100% branch coverage.
5. Import-linter (M4D3-TST-040).
6. Ruff lint and format (zero suppressions without explanatory comments).
7. Frontend unit tests (Vitest + React Testing Library + jest-axe).
8. TypeScript strict-mode compilation.
9. ESLint (no formula names; M4D3-TST-037).
10. Playwright E2E smoke tests.
11. Docker integration smoke test.

---

## Part 19 — Acceptance Matrix

| Req ID | Component | Test | Expected result | Control |
|---|---|---|---|---|
| M4D3-TRL-002 | `calculation_translation.py` | M4D3-TST-001 | All 9 engine results map to correct stored values | Data integrity |
| M4D3-TRL-002 | `calculation_translation.py` | M4D3-TST-002 | Unknown status → `"error"`, never `"complete"` | Security |
| M4D3-M-014 | `CalculationOutcome.clean()` | M4D3-TST-003/TST-038 | `ValidationError` on invalid status | Data integrity |
| M4D3-TRL-004 | Translation layer | M4D3-TST-019/TST-020 | Malformed/naive `generated_at` → error outcome | Data integrity |
| M4D3-APP-004 | `evaluate_applicability()` | M4D3-TST-007/TST-008/TST-009 | Correct branch outcome returned | Regulatory |
| M4D3-APP-010 | Response serializer | M4D3-TST-009/TST-010 | `applicability_outcome` derived; not forgeable | Security |
| M4D3-REG-011 | Activation service | M4D3-TST-011/TST-012/TST-013/TST-014 | Invalid version rejected with structured error | Security |
| M4D3-DAG-004 | Topological sort | M4D3-TST-015 | Identical order across 10 invocations | Correctness |
| M4D3-APP-007 | Population pass | M4D3-TST-016 | History row created on N/A transition with prior value | Regulatory |
| M4D3-TXN-003 | `enter_response()` | M4D3-TST-017 | Stale version → 409; no partial write | Data integrity |
| M4D3-PRV-002 | `input_provenance` writer | M4D3-TST-018 | `_registry_binding_version` in provenance | Reproducibility |
| M4D3-POP-007 | Population service | M4D3-TST-026 | Idempotent re-run; no new history or version bump | Regulatory |
| M4D3-POP-004 | Population service | M4D3-TST-027 | USER_REQUIRED never overwritten | Regulatory |
| M4D3-POP-006 | Population service | M4D3-TST-028 | Non-recalculable execution rejected | Data integrity |
| M4D3-TXN-002 | Transaction | M4D3-TST-029 | Mid-pass exception → full rollback | Data integrity |
| M4D3-TXN-007 | Concurrency | M4D3-TST-031 | Concurrent calls serialized | Data integrity |
| M4D3-TXN-004 | Transaction | M4D3-TST-032 | Calculation failure → full rollback | Data integrity |
| M4D3-AUD-005 | Audit emitter | M4D3-TST-033 | Unchanged outcome → no audit event | Regulatory |
| M4D3-SRC-006 | Source resolver | M4D3-TST-034 | Historical execution unchanged | Regulatory |
| M4D3-SER-003 | Response serializer | M4D3-TST-036 | No PATCH on `CalculationOutcome` | Security |
| M4D3-FE-004 | CI lint | M4D3-TST-037 | No formula names in frontend | Security |
| M4D3-SEC-006 | Import-linter | M4D3-TST-040 | No reverse imports | Architecture |
| M4D3-TRL-002 | Planted-failure suite | M4D3-TST-039 | Every engine result: correct triple | Security/Regulatory |

---

## Part 20 — Implementation Sequence

The following order is recommended. No step may be started before the preceding
step's code review is complete. This document does **not** authorize implementation;
that authorization is a separate gate.

1. **Constants and registry** — `execution_constants.py` additions (if any),
   `calculation_registry.py` with all six entries and their binding versions.
2. **Translation function** — `calculation_translation.py` with all mappings and
   the `INVALID_GENERATED_AT` error path.
3. **Applicability evaluator** — `evaluate_applicability()` in `applicability.py`.
4. **FDA source resolver** — `answer_sources.py` with resolver functions, tenant
   filter on all snapshot lookups.
5. **Population service** — `backend/iig_checklist/population_service.py` (or
   equivalent module), covering the full pass sequence (M4D3-POP-001), non-overwrite
   rules, idempotency, and audit event scheduling.
6. **Recalculation integration** — extend `enter_response()` in the execution
   service, adding lock acquisition, cascade identification, topological ordering,
   and the defensive cycle check.
7. **Serializers** — extend existing response serializers to include nested
   `CalculationOutcome` (M4D3-SER-001) and derived `applicability_outcome`
   (M4D3-SER-004); add `provenance_summary` (M4D3-SER-002).
8. **Frontend mapper and display** — centralized DTO mapper; `applicability_outcome`
   display; `SYSTEM_CALCULATED` status display; no formula code; lint rule.
9. **Backend tests** — full coverage of M4D3-TST-001 through M4D3-TST-040.
10. **Frontend tests** — Vitest unit tests; Playwright E2E for population flow and
    recalculation feedback.
11. **Docker smoke** — extend `docker-integration.yml` with 4D-3 smoke step.
12. **Independent implementation review** — second adversarial review of the
    implementation PR before merge.

---

## Part 21 — Gate Status

**Specification: COMPLETE. Pending adversarial specification review.**

**Ready for adversarial specification review: YES**
**Ready to write implementation code: NO — requires adversarial specification review and separate explicit authorization**
**Ready to create PR: NO**
**Migration required: NO**
**New database field required: NO**
