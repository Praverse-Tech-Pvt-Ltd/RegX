# Milestone 4D-3 Implementation Specification

**Status: SPECIFICATION REVISED after failed adversarial review. Pending second adversarial specification review before implementation.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Scope register:** `docs/MILESTONE_4D_3_SCOPE_REGISTER.md`
**Threat model:** `docs/MILESTONE_4D_3_THREAT_MODEL.md`
**Test strategy:** `docs/MILESTONE_4D_3_TEST_STRATEGY.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`
**Base SHA:** `c0adef4448153368c5bb280219c154f60be052f1` (Milestone 4D-2 merge)
**Prior specification head:** `4a15d0e` — adversarial review result **FAIL** (2 Critical, 5 Major, 11 Minor)

This document is the normative implementation specification for Milestone 4D-3.
Requirements use "shall" for mandatory obligations. Every requirement carries a unique
stable identifier and appears exactly once in the acceptance matrix (Part 21). No
implementation code is created by this document. Implementation remains unauthorized.

## Revision note — findings resolved in this revision

| Finding | Resolution | Part |
|---|---|---|
| C-1 registry identifier written into `calculation_name` | Registry entries carry an explicit `calculation_name`; identifier is never copied; `create_execution()` correction is mandated | Part 3 |
| C-2 `enter_response()` does not exist | All references removed; new governed service `update_checklist_response()` specified; view becomes a thin adapter | Part 4 |
| C-2b `expected_version` presented as additive | Acknowledged as a controlled breaking contract change with a defined deployment strategy | Part 5 |
| M-A required calculated questions unsubmittable | Completeness gate extension specified | Part 11 |
| M-B no REVIEW_REQUIRED submission gate | Mandatory blocking gate regardless of `question.required` | Part 12 |
| M-C read-time recomputation breaks historical reproducibility | State-dependent evaluation; persisted state governs submitted and terminal executions | Part 9 |
| M-D history not implementable, trigger undefined | Re-evaluation triggers defined; all twelve history fields specified; attribution rule fixed | Part 10 |
| M-E applicability fields client-writable | Governed field ownership specified | Part 8 |
| Minor 1 `approval_metadata` as data-source value | Corrected to `question.answer_type` guards | Part 2 |
| Minor 2 N/A `raw_value` behavior | Both transition directions specified | Part 10 |
| Minor 3 bare `save()` as validation assertion | Corrected; `full_clean()` required | Part 6 |
| Minor 4 `CalculationOutcome` uniqueness | Verified absent; code-level discipline specified | Part 6 |
| Minor 5 non-complete value invariant | Reassigned to the service layer | Part 6 |
| Minor 6 no reason-code allow-list | Closed vocabulary defined | Part 7 |
| Minor 7 dependency constant collision | Renamed with explicit module | Part 13 |
| Minor 8 unevidenced limits | Rationale stated as a governance decision | Part 13 |
| Minor 9 `run_preview()` inputs unspecified | All resolvers defined | Part 14 |
| Minor 10 snapshot write vs consumer-only scope | Ownership clarified | Part 15 |
| Minor 11 test-strategy section order | Corrected in the test strategy document | — |

## Second revision note — findings resolved after the second adversarial review

Prior head `51a4fcc` was reviewed **FAIL** (0 Critical, 2 Major, 5 Minor).

| Finding | Resolution | Part |
|---|---|---|
| MAJ-1 test strategy still specified tests against the nonexistent `enter_response()` | All references removed from both documents; §3 rewritten against `update_checklist_response()`; duplicate stale-version test withdrawn so exactly one normative definition remains | Part 4; test strategy §3, §9, §10.3 |
| MAJ-2 `maximum_dosage_units_per_day` had two competing sources with no selection rule | Conservative worst-case resolver specified over both `FormulationVersion.maximum_dosage_units_per_day` and `DosingRegimen.maximum_units_per_day`, with tie-breaker, disagreement flag, provenance and fail-closed behavior | Part 14.1 |
| Minor 1 no `reason_code` format validation | Pattern `^[A-Z][A-Z0-9_]{0,99}$` plus reserved-prefix rejection at activation | Part 9.2.1 |
| Minor 2 M4D3-SRC-006 hedge too broad | Narrowed to genuinely unresolved runtime data; verified non-nullability recorded | M4D3-SRC-006, M4D3-SRC-014 |
| Minor 3 duplicate stale-version coverage | Single normative definition retained | Test strategy §10.3 |
| Minor 4 blank `route`/`dosage_form` undefined | Blank treated as missing governed data; no fallback | Part 14.2 |
| Minor 5 backend and frontend tests merged | Split into separate sequence steps | Part 22 |

## Third revision note — findings resolved after the final adversarial review

Prior head `c214a62` was reviewed **FAIL** (0 Critical, 1 Major, 3 Minor).

| Finding | Resolution | Part |
|---|---|---|
| MAJ-A the two-form resolver vocabulary could not supply the kwargs of any approved calculation | Six allow-listed resolver forms, a complete kwarg mapping for all six functions, a governed unit-conversion layer reusing `iid_assessment/unit_conversion.py`, one unified `resolve_calculation_inputs()` pipeline, resolver-derived dependency edges, snapshot ordering, and a closed resolver-failure vocabulary | Part 3A |
| Minor 1 conservative-policy justification unrecorded | Monotonicity rationale recorded with source evidence, plus a governance rule for future consumers | M4D3-MDU-022 … 024 |
| Minor 2 scope register X-12 gloss unreconciled | "Consumer only" gloss replaced with an explicit boundary | Scope register X-12 clarification |
| Minor 3 documentation rows presented as executable tests | Sixteen rows classified as **Review assertion** with source-inspection evidence | Part 21 preamble |

---

## Part 1 — Scope

### 1.1 In scope

| Ref | Item |
|---|---|
| SCOPE-IN-01 | Draft-answer generation at execution creation |
| SCOPE-IN-02 | Automatic `FDA_DERIVED_DEFAULT` population |
| SCOPE-IN-03 | `SYSTEM_CALCULATED` computation |
| SCOPE-IN-04 | Synchronous in-draft cascade recalculation |
| SCOPE-IN-05 | Governed applicability evaluation and persisted applicability state |
| SCOPE-IN-06 | Source snapshot creation and provenance |
| SCOPE-IN-07 | `CalculationStatus` translation layer |
| SCOPE-IN-08 | `CalculationOutcome` read-only serialization |
| SCOPE-IN-09 | `CALCULATION_BINDING_REGISTRY` definition and validation |
| SCOPE-IN-10 | Frontend display for populated, calculated and review-required answers |
| SCOPE-IN-11 | Dependency-graph DAG validation at `ChecklistVersion` activation |
| SCOPE-IN-12 | New governed response-update service and thin view adapter |
| SCOPE-IN-13 | `expected_version` optimistic-lock contract on governed response updates |
| SCOPE-IN-14 | Completeness-gate extension for calculated and FDA-derived answers |
| SCOPE-IN-15 | Submission gate blocking unresolved `REVIEW_REQUIRED` |
| SCOPE-IN-16 | Correction of the existing `create_execution()` identifier handling |

### 1.2 Out of scope

| Ref | Excluded item | Deferred to |
|---|---|---|
| SCOPE-OUT-01 | Arbitrary formula builder | Never |
| SCOPE-OUT-02 | Tenant-authored executable logic | Never |
| SCOPE-OUT-03 | `eval`, `exec`, dynamic import from user-controlled values | Never |
| SCOPE-OUT-04 | Arbitrary SQL or expression evaluation | Never |
| SCOPE-OUT-05 | Manual override of calculated or FDA-derived values | 4D-4 |
| SCOPE-OUT-06 | Deviation workflow | 4D-4 |
| SCOPE-OUT-07 | Automatic approval based on calculation outcome | Never |
| SCOPE-OUT-08 | Final regulatory conclusion | Never |
| SCOPE-OUT-09 | Finalization workflow | 4D-4 |
| SCOPE-OUT-10 | Report or export generation | 4D-4 |
| SCOPE-OUT-11 | Dashboards | Not in 4D |
| SCOPE-OUT-12 | Push or webhook notifications | Not in 4D |
| SCOPE-OUT-13 | Asynchronous calculation engine (`calculating` reserved, never set) | Future |
| SCOPE-OUT-14 | New calculation-definition database model | Never in 4D-3 |
| SCOPE-OUT-15 | New database field | Never in 4D-3 |
| SCOPE-OUT-16 | Django migration | Never in 4D-3 |
| SCOPE-OUT-17 | Generic `PATCH`/`PUT` endpoint for `CalculationOutcome` | Never |
| SCOPE-OUT-18 | New calculation formulas beyond the six approved functions | Never in 4D |
| SCOPE-OUT-19 | Direct writes by `iig_checklist` to `iid_assessment` model classes | Never |
| SCOPE-OUT-20 | System-only background recalculation with no authenticated actor | Never in 4D-3 |
| SCOPE-OUT-21 | Manual resolution of a `REVIEW_REQUIRED` state | 4D-4 |

---

## Part 2 — Data-model usage

**M4D3-MDL-001** `ChecklistQuestion.calculation_binding_identifier`
(`CharField(max_length=100, blank=True)`) shall store only a governed registry key.
It shall never store a JSON payload, expression, SQL fragment, or any value absent
from `CALCULATION_BINDING_REGISTRY` at activation time.

**M4D3-MDL-002** `ChecklistResponse.data_source_type_snapshot` is immutable after
creation. No 4D-3 code path shall modify it.

**M4D3-MDL-003** Guards for reviewer-conclusion and approval-metadata questions shall
inspect `question.answer_type` against `AnswerType.REVIEWER_CONCLUSION` and
`AnswerType.APPROVAL_METADATA`. They shall never test `data_source_type_snapshot`
for the values `"reviewer_conclusion"` or `"approval_metadata"`: `DataSourceClassification`
contains only `fda_derived_default`, `user_required`, `system_calculated`,
`reviewer_confirmed`, `evidence_derived`.

**M4D3-MDL-004** No 4D-3 service shall write to a `ChecklistResponse` whose
`question.answer_type` is `REVIEWER_CONCLUSION` or `APPROVAL_METADATA`.

**M4D3-MDL-005** A `ChecklistResponse` with `data_source_type_snapshot = "user_required"`
and a non-null `raw_value` shall never be overwritten by population or recalculation.

**M4D3-MDL-006** `SYSTEM_CALCULATED` responses shall keep `raw_value = null` at all
times; results live exclusively in `CalculationOutcome`.

**M4D3-MDL-007** `CalculationOutcome.status` shall be one of the four
`iig_checklist.enums.CalculationStatus` values. The value `"calculating"` shall never
be written by any 4D-3 code path.

**M4D3-MDL-008** Engine strings from `iid_assessment.calculations.CalculationStatus`
shall never be assigned to `CalculationOutcome.status`; the Part 7 translation
function is the only permitted path.

**M4D3-MDL-009** `CalculationOutcome.inputs` and `input_provenance` shall contain only
server-generated values. No client-supplied content shall reach either field.

**M4D3-MDL-010** 4D-3 shall only update `CalculationOutcome` rows created by
`create_execution()`; it shall never create additional rows for an existing response.

**M4D3-MDL-011** `ApplicabilityRule.condition_json` shall be interpreted using the
runtime grammar in `backend/iig_checklist/applicability.py`: composite nodes are
`{"operator": "all"|"any", "conditions": [...]}` and leaf nodes are
`{"field": ..., "op": ..., "value": ...}`.

**M4D3-MDL-012** No implementation code shall reference a `condition_checksum` field;
`ApplicabilityRule` has no such field. Governed identity is `code` plus `rule_version`.

**M4D3-MDL-013** Applicability outcomes shall be read from `ApplicabilityRule.outcome_if_true`
and `outcome_if_false`; the governed reason string is `ApplicabilityRule.reason_code`
(`max_length=100`).

---

## Part 3 — Calculation binding registry (C-1)

### 3.1 Verified defect being corrected

**M4D3-REG-001** The existing `create_execution()` at
`backend/iig_checklist/services.py:419` passes
`calculation_name=q.calculation_binding_identifier` into `CalculationOutcome`, which is
validated by `CalculationOutcome.clean()` against `_CALCULATION_NAMES` — the six
approved *function* names. A registry-key identifier such as `"percentage_w_w"` is not
a member of that set and therefore aborts execution creation with `ValidationError`.
This conflation shall be corrected as part of 4D-3.

**M4D3-REG-002** The implementation shall keep three concepts distinct at all times:
the **registry identifier** (stored on `ChecklistQuestion.calculation_binding_identifier`),
the **calculation function name** (a member of `_CALCULATION_NAMES`), and
**`CalculationOutcome.calculation_name`** (which shall equal the calculation function
name).

**M4D3-REG-003** The registry identifier shall never be copied into
`CalculationOutcome.calculation_name`. The value written shall always be the
`calculation_name` field of the resolved registry entry.

### 3.2 Registry structure

**M4D3-REG-004** `CALCULATION_BINDING_REGISTRY` shall be a module-level Python `dict`
in a new module `backend/iig_checklist/calculation_registry.py`. It shall not be a
database table and shall not be mutable at runtime.

**M4D3-REG-005** Each entry shall provide exactly these fields:

| Field | Type | Purpose |
|---|---|---|
| `calculation_name` | `str` | Must be a member of `_CALCULATION_NAMES`; written to `CalculationOutcome.calculation_name` |
| `function` | `Callable` | Direct reference to the approved calculation function |
| `formula_version` | `str` | Must equal `iid_assessment.calculations.FORMULA_VERSION` |
| `binding_version` | `str` | Immutable binding version (M4D3-REG-008) |
| `input_resolvers` | `dict[str, InputResolver]` | Function kwarg name → resolver specification |
| `dependencies` | `list[str]` | `ChecklistQuestion.code` values feeding this calculation |
| `required_units` | `dict[str, str]` | Expected unit per unit-bearing input |
| `output_unit` | `str` | Expected result unit; may be empty |
| `rounding_rule` | `str` | Rounding descriptor written to the outcome |
| `allowed_answer_type` | `str` | `AnswerType` value permitted on the bound question |
| `allowed_data_source` | `str` | Shall be `"system_calculated"` |

Conceptual shape (illustrative only, not code to be copied verbatim):

```
CALCULATION_BINDING_REGISTRY = {
    "percentage_w_w": {
        "calculation_name": "calculate_percentage_w_w",
        "function": calculate_percentage_w_w,
        "formula_version": FORMULA_VERSION,
        "binding_version": "1.0.0",
        ...
    },
}
```

**M4D3-REG-006** Registry identifiers shall be lowercase ASCII slugs of letters and
underscores, at most 100 characters, compatible with `CharField(max_length=100)`.

**M4D3-REG-007** The approved identifier → `calculation_name` mapping for this release
shall be exactly:

| Registry identifier | `calculation_name` |
|---|---|
| `percentage_w_w` | `calculate_percentage_w_w` |
| `daily_exposure` | `calculate_daily_exposure` |
| `percentage_of_iid_potency` | `calculate_percentage_of_potency` |
| `difference_from_iid_potency` | `calculate_difference_from_potency` |
| `percentage_of_iid_mde` | `calculate_percentage_of_mde` |
| `difference_from_iid_mde` | `calculate_difference_from_mde` |

No other identifier is valid in this release.

**M4D3-REG-008** Each entry shall declare an immutable `binding_version`. It shall be
incremented whenever `input_resolvers`, `dependencies`, `required_units`,
`output_unit`, or `rounding_rule` change, independently of `formula_version`.

**M4D3-REG-009** A module-level self-check shall assert at import time that every
entry's `calculation_name` is a member of `_CALCULATION_NAMES` and that every
`formula_version` equals `FORMULA_VERSION`. A violation shall raise at import,
failing the deployment rather than producing invalid outcomes.

### 3.3 Input resolvers

**M4D3-REG-010** An `InputResolver` shall be one of exactly the six allow-listed forms
defined in Part 3A. The earlier two-form vocabulary was insufficient: it could not
express FDA/IID-derived values, prior calculation results, the maximum-daily-units
resolver, or unit conversion, and therefore could not supply the kwargs of any of the six
approved calculations. No form outside Part 3A is valid without a governed specification
change.

**M4D3-REG-011** Resolvers shall use only named model fields and allow-listed source
kinds. No `eval`, `exec`, dynamic import, `getattr` from an untrusted string, SQL
fragment, or template expression is permitted.

### 3.4 Resolution and failure behavior

**M4D3-REG-012** Registry lookups shall use explicit `.get()` with `None` handling.

**M4D3-REG-013** `create_execution()` shall resolve the registry entry **before**
constructing the `CalculationOutcome`, and shall write
`calculation_name = entry["calculation_name"]`.

**M4D3-REG-014** An unknown registry identifier encountered during execution creation
shall abort the entire creation transaction with a structured error
(`error_code = "unknown_registry_identifier"`, HTTP 400). No execution, response, or
outcome row shall remain.

**M4D3-REG-015** A registry entry whose `calculation_name` is not a member of
`_CALCULATION_NAMES` shall abort execution creation atomically with
`error_code = "invalid_calculation_name"`.

**M4D3-REG-016** An unknown identifier encountered during population or recalculation
of an already-created execution shall fail closed on that outcome only:
`status = "error"`, `reason_code = "UNKNOWN_REGISTRY_IDENTIFIER"`, `value = null`. It
shall not raise an unhandled exception.

**M4D3-REG-017** A registry key rename shall require either a compatibility alias
whose target entry has identical `calculation_name`, `function`, `input_resolvers`,
`dependencies` and `required_units`, or a governed admin update of the stored
identifier on affected `ChecklistQuestion` rows before the old key is removed. An
alias with differing semantics is prohibited; silent reinterpretation is prohibited.

### 3.5 Activation validation

**M4D3-REG-018** `ChecklistVersion` activation shall validate every `SYSTEM_CALCULATED`
question: the identifier exists in the registry; the entry's `allowed_answer_type`
matches `question.answer_type`; all declared `dependencies` exist as question codes in
the same `ChecklistVersion`; no cross-version dependency exists; the graph is acyclic;
and the graph respects the Part 13 limits.

**M4D3-REG-019** Activation shall be rejected with a structured error naming the
specific sub-reason if any check in M4D3-REG-018 fails, and the `ChecklistVersion`
shall remain in its pre-activation status.

---

## Part 3A — Input resolution (MAJ-A)

### 3A.1 Verified calculation contracts

**M4D3-INP-001** The six approved functions have exactly these signatures, confirmed
against `backend/iid_assessment/calculations.py`. Kwarg names are normative and shall not
be altered or invented:

| Function | Kwargs |
|---|---|
| `calculate_percentage_w_w` | `quantity_per_unit_grams`, `total_dosage_unit_weight_grams` |
| `calculate_daily_exposure` | `quantity_per_dosage_unit`, `maximum_dosage_units_per_day` |
| `calculate_percentage_of_potency` | `converted_proposed_quantity`, `selected_iid_potency_amount` |
| `calculate_difference_from_potency` | `selected_iid_potency_amount`, `converted_proposed_quantity` |
| `calculate_percentage_of_mde` | `converted_proposed_daily_exposure`, `selected_iid_mde` |
| `calculate_difference_from_mde` | `selected_iid_mde`, `converted_proposed_daily_exposure` |

**M4D3-INP-002** No kwarg shall remain without an approved resolver. A registry entry
whose `input_resolvers` does not cover every kwarg of its bound function shall fail the
import-time self-check (M4D3-REG-009).

### 3A.2 Allow-listed resolver forms

**M4D3-INP-003** Form A — question response:
`{"source": "question_response", "question_code": ..., "value_field": "raw_value",
"expected_type": ..., "required_unit": ..., "unit_source": ...}`. It resolves a
`ChecklistResponse` for the named question in the current execution, scoped to
`execution.tenant`. It shall never be used to read a `SYSTEM_CALCULATED` response as a
calculation result, because `raw_value` is permanently null for those responses
(M4D3-MDL-006). It fails closed when the response is missing, `is_not_applicable`,
carries a `REVIEW_REQUIRED:` marker, or holds a value that cannot be coerced to
`expected_type`.

**M4D3-INP-004** Form B — formulation field:
`{"source": "formulation_field", "object": "formulation_version"|"formulation_component",
"field": ..., "unit_field": ..., "required_unit": ...}`. It reads a named field from the
execution's `FormulationVersion` or the subject `FormulationComponent`, scoped through
`formulation_version__product__tenant = execution.tenant`. It fails closed on a missing
object, a missing field value, or a missing unit where `required_unit` is declared.

**M4D3-INP-005** Form C — maximum daily units:
`{"source": "maximum_daily_units", "resolver_version": ...}`. It invokes the conservative
resolver defined in Part 14.1 and returns the selected `Decimal` together with its
provenance. Registry entries shall not restate or duplicate that selection logic.

**M4D3-INP-006** Form D — assessment snapshot:
`{"source": "assessment_snapshot", "field": ..., "unit_field": ..., "required_unit": ...}`.
It reads persisted governed IID/FDA values from the `AssessmentSnapshot` created for the
current execution under Part 3A.6. Permitted `field` values are exactly
`iid_potency_amount` and `iid_mde`, with `unit_field` values `iid_potency_unit` and
`iid_mde_unit` respectively — the actual field names on `iid_assessment.AssessmentSnapshot`.
The snapshot's `tenant` shall equal `execution.tenant`. This form shall never perform a
live IID lookup. It fails closed when the snapshot is absent, belongs to another tenant,
or the named field is null or blank.

**M4D3-INP-007** Form E — prior calculation outcome:
`{"source": "calculation_outcome", "question_code": ..., "field": "value",
"required_status": "complete", "required_unit": ..., "unit_source": ...}`. It reads
`CalculationOutcome.value` for the named `SYSTEM_CALCULATED` question in the same
execution. It requires exactly one matching outcome row, `status = "complete"`, and a
non-null `value`. It fails closed on zero rows, more than one row (M4D3-OUT-005),
`data_required`, `error`, a null value, or a unit that cannot be converted to
`required_unit`.

**M4D3-INP-008** Form F — constant:
`{"source": "constant", "value": ..., "type": "decimal"|"string", "binding_version": ...}`.
Constants shall be hard-coded in the version-controlled registry. No tenant or client may
author one, no free-form runtime value is permitted, and no expression shall be evaluated.

**M4D3-INP-009** Forms A, B, D and F read stored or declared data. Only Form E creates a
calculation-to-calculation dependency edge (Part 3A.5). Form C creates no edge.

### 3A.2.1 Complete kwarg mapping

**M4D3-MAP-001** `calculate_percentage_w_w` — `quantity_per_unit_grams` resolves by
Form B from `FormulationComponent.quantity_per_dosage_unit` with
`unit_field = quantity_unit`, converted to `gram`; `total_dosage_unit_weight_grams`
resolves by Form B from `FormulationVersion.total_dosage_unit_weight` with
`unit_field = total_dosage_unit_weight_unit`, converted to `gram`.

**M4D3-MAP-002** `calculate_daily_exposure` — `quantity_per_dosage_unit` resolves by
Form B from `FormulationComponent.quantity_per_dosage_unit` with
`unit_field = quantity_unit`, converted to `gram`; `maximum_dosage_units_per_day`
resolves by Form C with no conversion.

**M4D3-MAP-003** `calculate_percentage_of_potency` — `converted_proposed_quantity`
resolves by Form B from `FormulationComponent.quantity_per_dosage_unit`, converted to the
unit given by the snapshot's `iid_potency_unit`; `selected_iid_potency_amount` resolves by
Form D from `AssessmentSnapshot.iid_potency_amount` with no conversion.

**M4D3-MAP-004** `calculate_difference_from_potency` — identical resolved inputs to
M4D3-MAP-003; only the kwarg order differs.

**M4D3-MAP-005** `calculate_percentage_of_mde` — `converted_proposed_daily_exposure`
resolves by Form E from the `calculate_daily_exposure` outcome
(`required_status = "complete"`), converted from `gram` per day to the unit given by the
snapshot's `iid_mde_unit`; `selected_iid_mde` resolves by Form D from
`AssessmentSnapshot.iid_mde` with no conversion.

**M4D3-MAP-006** `calculate_difference_from_mde` — identical resolved inputs to
M4D3-MAP-005; only the kwarg order differs.

**M4D3-MAP-007** `calculate_daily_exposure` returns a `CalculationResult` with no `unit`
set. Its stored `CalculationOutcome.unit` shall therefore be written by the governed
service as `gram` per day, derived from the canonical target unit of
`quantity_per_dosage_unit`, so that the Form E resolver has an explicit source unit to
convert from.

**M4D3-MAP-008** Every mapping above uses kwarg names taken verbatim from
M4D3-INP-001 and model field names taken verbatim from `formulations.models` and
`iid_assessment.models`. No alternative or invented name shall be used.

### 3A.3 Unit conversion

**M4D3-UNC-001** All unit conversion required by a kwarg contract shall be performed by
the **input-resolution service**, never by a calculation function and never by the
frontend.

**M4D3-UNC-002** Conversion shall use the existing approved service
`backend/iid_assessment/unit_conversion.py` via
`convert(value, from_unit, to_unit, *, density_g_per_ml=None) -> ConversionResult`.
4D-3 shall not introduce a second conversion implementation or table.

**M4D3-UNC-003** The allow-listed unit vocabulary is that module's:
`MASS_UNITS` = `microgram`, `milligram`, `gram`, `kilogram` (base `gram`);
`VOLUME_UNITS` = `microlitre`, `millilitre`, `litre` (base `litre`);
`COUNT_UNITS` = `tablet`, `capsule`, `unit`, `actuation`, `dose`. Canonical unit strings
are spelled in full — `"gram"`, not `"g"`; `"milligram"`, not `"mg"`. Abbreviated unit
tokens shall not appear in registry entries.

**M4D3-UNC-004** Source unit and target unit shall both be explicit in the resolver
declaration. No unit shall be inferred or defaulted.

**M4D3-UNC-005** Arithmetic shall be `Decimal` only; no float shall appear on any
conversion or resolution path.

**M4D3-UNC-006** Canonical target units per kwarg:

| Kwarg | Target unit |
|---|---|
| `quantity_per_unit_grams` | `gram` |
| `total_dosage_unit_weight_grams` | `gram` |
| `quantity_per_dosage_unit` | `gram` |
| `maximum_dosage_units_per_day` | count; no conversion |
| `converted_proposed_quantity` | the snapshot's `iid_potency_unit` |
| `selected_iid_potency_amount` | as stored; no conversion |
| `converted_proposed_daily_exposure` | the snapshot's `iid_mde_unit` |
| `selected_iid_mde` | as stored; no conversion |

The `converted_` kwargs convert the proposed value **into the IID reference unit**, so
each comparison is made between like quantities.

**M4D3-UNC-007** A `ConversionResult` with `ok = False` shall prevent invocation of the
calculation function.

**M4D3-UNC-008** Conversion failures shall map as follows, preserving the engine's
existing canonicalization: `DIMENSION_MISMATCH`, `CONVERSION_NOT_SUPPORTED` and
`UNIT_UNKNOWN` produce `status = "error"` with `reason_code = "UNIT_MISMATCH"`;
`VALUE_MISSING` produces `status = "data_required"` with `reason_code = "DATA_REQUIRED"`;
`DENSITY_REQUIRED` and `BASIS_REQUIRED` produce `status = "error"` with
`reason_code = "NOT_COMPARABLE"`. This is the only path by which `UNIT_MISMATCH` is
produced in 4D-3.

**M4D3-UNC-009** Mass↔volume conversion requires an explicitly supplied approved density;
4D-3 shall introduce no new density source and shall fail closed with `DENSITY_REQUIRED`
when one is absent.

**M4D3-UNC-010** No client shall supply, override, or influence a conversion factor.

**M4D3-UNC-011** Every applied conversion shall record in provenance the original value,
original unit, converted value, converted unit and the conversion rule version.

### 3A.4 Unified input-resolution pipeline

**M4D3-INP-010** A single service
`resolve_calculation_inputs(execution, response, registry_entry, actor)` shall own all
input resolution. Part 14.1 maximum-daily-units resolution, snapshot resolution and
prior-outcome resolution shall all be invoked **through** this pipeline. No parallel or
ad hoc resolution mechanism shall remain.

**M4D3-INP-011** The pipeline shall, in order: validate the registry entry; resolve each
kwarg through its allow-listed form; enforce tenant scope on every access; enforce
applicability state; perform unit conversion; collect provenance; validate the resolved
Python/domain type; detect missing or ambiguous data; and return an immutable
resolved-input object.

**M4D3-INP-012** The pipeline shall never invoke the calculation function when any
required kwarg is unresolved. Partial kwargs shall never be passed, so a missing-kwarg
`TypeError` is unreachable.

**M4D3-INP-013** The pipeline shall be pure with respect to the database: it reads and
resolves but performs no write.

**M4D3-INP-014** Resolved inputs and their provenance shall be recorded in
`CalculationOutcome.inputs` and `CalculationOutcome.input_provenance` respectively.

### 3A.5 Dependency edges

**M4D3-DEP-001** The dependency graph shall be **derived from resolver declarations**,
not authored separately. A registry entry's `dependencies` shall equal the set of
`question_code` values appearing in its Form E resolvers.

**M4D3-DEP-002** Form A, B, C, D and F resolvers shall create no calculation-to-calculation
edge.

**M4D3-DEP-003** The actual graph for the approved registry is:

```
calculate_daily_exposure
    ├─→ calculate_percentage_of_mde
    └─→ calculate_difference_from_mde
```

`calculate_percentage_of_mde` and `calculate_difference_from_mde` both consume the same
upstream daily-exposure outcome and shall **not** depend on each other.
`calculate_percentage_w_w`, `calculate_percentage_of_potency` and
`calculate_difference_from_potency` have no calculation dependencies.

**M4D3-DEP-004** Maximum path depth in the approved graph is therefore **2** and the
maximum reachable calculated node count from any single question is **3**.
`CALCULATION_MAX_DEPENDENCY_DEPTH = 5` and `CALCULATION_MAX_CASCADE_NODES = 10` are
retained as governed limits providing headroom above the documented graph, consistent
with M4D3-DAG-002.

**M4D3-DEP-005** Graph validation shall occur at `ChecklistVersion` activation, with the
defensive runtime revalidation of M4D3-DAG-010 retained.

**M4D3-DEP-006** A Form E resolver naming a question that is absent from the version, or
that is not `SYSTEM_CALCULATED`, shall be rejected at activation with
`error_code = "UNKNOWN_DEPENDENCY_CODE"`.

### 3A.6 Snapshot ordering

**M4D3-SNO-001** Because potency and MDE calculations consume snapshot fields, the
population pass shall observe this exact order: resolve the live FDA/IID source; create
or reuse the governed `AssessmentSnapshot` through the approved `iid_assessment` service;
obtain its `public_id`; resolve snapshot-derived calculation inputs; execute the potency
and MDE calculations; persist each `CalculationOutcome` with the snapshot UUID and
provenance.

**M4D3-SNO-002** After the snapshot step, no potency or MDE calculation shall read live
IID data directly. All such inputs shall come from the persisted snapshot via Form D.

**M4D3-SNO-003** Snapshot creation and the dependent calculation persistence shall occur
within the same `transaction.atomic()` block as the rest of the population pass
(M4D3-POP-001), so a rollback discards both.

**M4D3-SNO-004** Calculations requiring a snapshot shall run only after
`calculate_daily_exposure` has completed where a Form E dependency exists, honoring the
topological order of M4D3-DAG-006.

### 3A.7 Resolver failure vocabulary

**M4D3-IFV-001** A closed vocabulary `ALLOWED_INPUT_FAILURE_CODES` shall be defined
alongside the pipeline, containing exactly: `INPUT_RESPONSE_MISSING`,
`INPUT_RESPONSE_NOT_APPLICABLE`, `INPUT_REVIEW_REQUIRED`, `INPUT_VALUE_INVALID`,
`INPUT_UNIT_MISSING`, `INPUT_UNIT_UNSUPPORTED`, `INPUT_UNIT_DIMENSION_MISMATCH`,
`FORMULATION_COMPONENT_MISSING`, `FORMULATION_FIELD_MISSING`,
`ASSESSMENT_SNAPSHOT_MISSING`, `ASSESSMENT_FIELD_MISSING`,
`UPSTREAM_CALCULATION_MISSING`, `UPSTREAM_CALCULATION_INCOMPLETE`,
`UPSTREAM_CALCULATION_DUPLICATE`, `INPUT_TENANT_MISMATCH`, `INPUT_RESOLVER_UNKNOWN`.

**M4D3-IFV-002** Failure codes are provenance metadata. They shall never be written to
`CalculationOutcome.reason_code` and shall never appear in `ALLOWED_REASON_CODES`.

**M4D3-IFV-003** Missing-data failures — `INPUT_RESPONSE_MISSING`,
`INPUT_RESPONSE_NOT_APPLICABLE`, `INPUT_UNIT_MISSING`, `FORMULATION_COMPONENT_MISSING`,
`FORMULATION_FIELD_MISSING`, `ASSESSMENT_SNAPSHOT_MISSING`, `ASSESSMENT_FIELD_MISSING`,
`UPSTREAM_CALCULATION_MISSING`, `UPSTREAM_CALCULATION_INCOMPLETE` — shall produce
`status = "data_required"` with `reason_code = "DATA_REQUIRED"`.

**M4D3-IFV-004** `INPUT_REVIEW_REQUIRED` shall produce `status = "data_required"` with
`reason_code = "DATA_REQUIRED"`, consistent with M4D3-POP-003 blocking calculation for a
review-required question.

**M4D3-IFV-005** Invalid or unsupported conditions — `INPUT_VALUE_INVALID`,
`INPUT_UNIT_UNSUPPORTED`, `INPUT_UNIT_DIMENSION_MISMATCH`,
`UPSTREAM_CALCULATION_DUPLICATE`, `INPUT_TENANT_MISMATCH`, `INPUT_RESOLVER_UNKNOWN` —
shall produce `status = "error"` with the canonical `reason_code` selected per
M4D3-UNC-008 for unit failures and `UNKNOWN_ENGINE_STATUS` is **not** used; duplicate,
tenant-mismatch and unknown-resolver conditions shall use
`reason_code = "UNKNOWN_REGISTRY_IDENTIFIER"` where configuration is at fault and
`NOT_COMPARABLE` where data is at fault.

**M4D3-IFV-006** No resolver exception text, stack trace or internal message shall be
stored as a governed reason code or exposed to a client.

---

## Part 4 — Governed response-update service (C-2)

### 4.1 Verified current state

**M4D3-SVC-001** No `enter_response()` service exists in the repository. The current
write path is `ChecklistResponseUpdateView.patch()` in `backend/iig_checklist/views.py`,
which performs `full_clean()` and `save()` with **no** `transaction.atomic()`, **no**
`select_for_update()`, **no** `expected_version`, and **no** version increment. No
requirement in this specification shall attribute locking, versioning, transactional or
recalculation behavior to that view as it exists today.

### 4.2 New service

**M4D3-SVC-002** A new governed service `update_checklist_response()` shall be added to
`backend/iig_checklist/services.py`. Its name may differ, but the responsibility
boundary defined here is mandatory.

**M4D3-SVC-003** `update_checklist_response()` shall own, in order: tenant-scoped
execution lookup; tenant-scoped response lookup; execution-state validation; permission
validation; `expected_version` validation; execution lock; response lock; response
payload validation; governed applicability handling; dependent recalculation; history
creation where required; response version increment; all writes inside a single
`transaction.atomic()`; and audit dispatch via `transaction.on_commit()`.

**M4D3-SVC-004** `ChecklistResponseUpdateView.patch()` shall be reduced to a thin API
adapter that deserializes the request, calls the governed service, maps service
exceptions to structured HTTP responses, and serializes the result. It shall contain no
business logic, no direct model mutation, and no audit emission.

**M4D3-SVC-005** The governed service shall reject any write to a response whose
`data_source_type_snapshot` is `fda_derived_default` or `system_calculated` from an
actor without an override permission, with `error_code = "server_controlled_value"` and
HTTP 403. This check shall live in the service, not only in the serializer.

**M4D3-SVC-006** The `system_derived_value` and `override_reason` fields shall not be
written by 4D-3; the override path is deferred to 4D-4.

**M4D3-SVC-007** A new module `backend/iig_checklist/answer_sources.py` shall provide
pure resolver functions for FDA-derived defaults, dispatched through an explicit
question-code mapping dict. No dynamic reflection shall be used.

**M4D3-SVC-008** Resolver functions shall be pure: no database writes, no audit
emission, no model mutation.

---

## Part 5 — `expected_version` contract change

**M4D3-VER-001** The ordinary response PATCH does not currently accept or require
`expected_version`; only the reviewer-conclusion endpoint does. Introducing it is a
**controlled breaking API contract change**, not an additive one. This specification
shall not describe it as purely additive.

**M4D3-VER-002** `expected_version` shall be a required integer field on the governed
response-update request serializer.

**M4D3-VER-003** Backend and frontend changes shall deploy atomically in the same
release; the frontend shall be updated to send `expected_version` before or with the
backend change.

**M4D3-VER-004** A request omitting `expected_version` shall be rejected with HTTP 400
and `error_code = "expected_version_required"`. No write shall occur. Silent overwrite
is prohibited.

**M4D3-VER-005** A request whose `expected_version` does not equal the locked
`ChecklistResponse.version` shall be rejected with HTTP 409 and
`error_code = "stale_version"`. No response write, no history row, no version
increment, and no success audit shall occur.

**M4D3-VER-006** A successful governed response update shall increment
`ChecklistResponse.version` by exactly one.

**M4D3-VER-007** The frontend shall handle 409 by reloading the response list and
surfacing a conflict message; it shall not retry automatically with a new version.

**M4D3-VER-008** The API contract change shall be recorded in release notes and in the
regenerated OpenAPI schema.

---

## Part 6 — `CalculationOutcome` handling

**M4D3-OUT-001** Every governed `CalculationOutcome` write shall call `full_clean()`
before `save()`.

**M4D3-OUT-002** A bare `Model.save()` shall never be used as evidence of validation.
Tests asserting validation failure shall invoke `full_clean()` or the governed service.

**M4D3-OUT-003** Verified schema fact: `CalculationOutcome` has no `Meta` class and
migration `0002_execution.py` adds no constraint for it. There is therefore **no
database uniqueness** on `(response, calculation_name)`, and `response` is a plain
`ForeignKey`. The specification shall not claim a one-to-one or unique constraint.

**M4D3-OUT-004** Because no database constraint exists, uniqueness shall be maintained
by code discipline: the governed service shall select existing outcome rows for the
locked response in ascending primary-key order and update in place, never create.

**M4D3-OUT-005** If more than one `CalculationOutcome` row is found for a single
response and `calculation_name`, the governed service shall fail closed with
`error_code = "duplicate_calculation_outcome"` and shall not guess which row is
authoritative.

**M4D3-OUT-006** No migration shall be added to introduce the missing constraint;
schema change is unauthorized in 4D-3.

**M4D3-OUT-007** Verified schema fact: `CalculationOutcome.clean()` validates only
`calculation_name`. The rule "`value` is null unless `status = "complete"`" is **not**
a model invariant and `full_clean()` will not enforce it. The specification shall not
describe it as an existing model invariant.

**M4D3-OUT-008** The governed translation and update path shall enforce, before
`full_clean()`, that `value` is non-null only when `status = "complete"`, and shall
reject a non-null `value` for any other status with
`error_code = "invalid_outcome_value"`.

---

## Part 7 — Status translation and reason codes

### 7.1 Translation function

**M4D3-TRL-001** A pure function `translate_engine_status()` shall live in a new module
`backend/iig_checklist/calculation_translation.py`, with no database access and no side
effects. It shall return `(stored_status, reason_code, value)`.

**M4D3-TRL-002** The translation shall implement exactly this mapping. No branch shall
default to `"complete"`.

| Engine result string | Stored `status` | `reason_code` | `value` |
|---|---|---|---|
| `OK` | `complete` | `""` | engine value |
| `DATA_REQUIRED` | `data_required` | `DATA_REQUIRED` | `null` |
| `INGREDIENT_UNRESOLVED` | `error` | `INGREDIENT_UNRESOLVED` | `null` |
| `ROUTE_MISMATCH` | `error` | `ROUTE_MISMATCH` | `null` |
| `DOSAGE_FORM_MISMATCH` | `error` | `DOSAGE_FORM_MISMATCH` | `null` |
| `UNIT_MISMATCH` | `error` | `UNIT_MISMATCH` | `null` |
| `FDA_VALUE_UNAVAILABLE` | `error` | `FDA_VALUE_UNAVAILABLE` | `null` |
| `NOT_COMPARABLE` | `error` | `NOT_COMPARABLE` | `null` |
| `REGULATORY_REVIEW_REQUIRED` | `error` | `REGULATORY_REVIEW_REQUIRED` | `null` |
| any other string | `error` | `UNKNOWN_ENGINE_STATUS` | `null` |

**M4D3-TRL-003** The engine class exposes aliases whose *resolved string values* are
already members of the table above (`UNIT_CONVERSION_FAILED` → `UNIT_MISMATCH`;
`IID_VALUE_MISSING` and `IID_VALUE_INVALID` → `FDA_VALUE_UNAVAILABLE`;
`PROPOSED_VALUE_MISSING` and `MAX_DAILY_UNITS_MISSING` → `DATA_REQUIRED`;
`BASIS_UNCLEAR` → `NOT_COMPARABLE`; `RELEASE_NOT_ACTIVE` and `RECORD_SUPERSEDED` →
`REGULATORY_REVIEW_REQUIRED`). The function shall operate on string values only and
shall not enumerate alias attribute names.

**M4D3-TRL-004** `CalculationResult.generated_at` is a string. A valid ISO-8601 value
carrying a UTC offset or `Z` suffix shall be parsed to a timezone-aware `datetime`
before assignment.

**M4D3-TRL-005** An empty, malformed, or timezone-naive `generated_at` shall produce
`status = "error"`, `reason_code = "INVALID_GENERATED_AT"`, `value = null`, and
`generated_at = null`. The enclosing transaction shall continue; only that outcome is
marked in error.

**M4D3-TRL-006** No client-supplied timestamp shall ever populate
`CalculationOutcome.generated_at`.

### 7.2 Closed reason-code vocabulary

**M4D3-RSN-001** A module-level frozen set `ALLOWED_REASON_CODES` shall be defined in
`backend/iig_checklist/calculation_translation.py` containing exactly:

`DATA_REQUIRED`, `INGREDIENT_UNRESOLVED`, `ROUTE_MISMATCH`, `DOSAGE_FORM_MISMATCH`,
`UNIT_MISMATCH`, `FDA_VALUE_UNAVAILABLE`, `NOT_COMPARABLE`,
`REGULATORY_REVIEW_REQUIRED`, `UNKNOWN_ENGINE_STATUS`, `UNKNOWN_REGISTRY_IDENTIFIER`,
`INVALID_GENERATED_AT`, `DEPENDENCY_DEPTH_EXCEEDED`, `CASCADE_NODE_LIMIT_EXCEEDED`,
`DEPENDENCY_CYCLE`, `APPLICABILITY_REEVALUATED`.

**M4D3-RSN-002** Reason codes shall be uppercase ASCII with underscores, at most 100
characters, fitting `CalculationOutcome.reason_code`
(`CharField(blank=True, max_length=100)`).

**M4D3-RSN-003** The governed service shall reject any `reason_code` outside
`ALLOWED_REASON_CODES`, except the empty string used for a `complete` outcome.

**M4D3-RSN-004** No client shall be able to supply a reason code through any request
payload.

**M4D3-RSN-005** Raw exception text, stack traces and free-form internal messages shall
never be written to `reason_code`.

**M4D3-RSN-006** A second closed vocabulary `ALLOWED_RESOLVER_DETAIL_CODES` shall be
defined in the same module for governed detail codes recorded in `input_provenance`.
It shall contain exactly: `MAX_DAILY_UNITS_REQUIRED`, `MAX_DAILY_UNITS_SOURCE_INVALID`,
`MAX_DAILY_UNITS_SOURCE_AMBIGUOUS`, `MAX_DAILY_UNITS_SOURCE_DISAGREEMENT`,
`ROUTE_NOT_PROVIDED`, `DOSAGE_FORM_NOT_PROVIDED`.

**M4D3-RSN-007** Detail codes are provenance metadata only. They shall never be written
to `CalculationOutcome.reason_code`, shall never appear in
`ALLOWED_REASON_CODES`, and shall never alter the engine's canonical status mapping.

**M4D3-RSN-008** Detail codes shall follow the same casing and length rules as
M4D3-RSN-002 and shall never be supplied by a client.

---

## Part 8 — Applicability evaluation and field ownership (M-E)

**M4D3-APP-001** A pure function `evaluate_applicability(rule, context) -> str` shall be
added to `backend/iig_checklist/applicability.py`. It shall have no database access, no
side effects, no `eval`, no `exec`, and no dynamic attribute access.

**M4D3-APP-002** The evaluator shall mirror the grammar enforced by
`validate_condition_json()` exactly and shall use the same operator set: `eq`, `neq`,
`in`, `not_in`, `exists`, `not_exists`, `gt`, `gte`, `lt`, `lte`, with `all`/`any`
composites.

**M4D3-APP-003** A node matching neither the composite nor the leaf shape indicates a
validator contract breach and shall raise `RuntimeError`, distinguishing it from a
`ValidationError`.

**M4D3-APP-004** The evaluator shall return `rule.outcome_if_true` when the condition
evaluates true and `rule.outcome_if_false` otherwise; the returned value shall be one of
`applicable`, `not_applicable`, `review_required`.

**M4D3-APP-005** A field absent from the context shall be treated as absent: `None` for
existence checks, and `False` for comparison operators.

**M4D3-APP-006** The applicability context shall be assembled from exactly the six
fields in field-registry version 1: `product.route`, `product.dosage_form`,
`product.release_type`, `iid.match_status`, `iid.has_mde`, `iid.has_potency`.

**M4D3-APP-007** The context dict shall be assembled once per governed evaluation pass
and shall never be persisted.

### 8.1 Governed field ownership

**M4D3-APP-008** For any response whose `question.applicability_rule` is non-null, the
fields `is_not_applicable` and `not_applicable_reason` are **server-owned**. The
governed applicability service is their only writer.

**M4D3-APP-009** The governed response-update service shall reject a client-supplied
`is_not_applicable` or `not_applicable_reason` for a rule-governed response with
`error_code = "applicability_server_controlled"` and HTTP 403.

**M4D3-APP-010** For a response with no applicability rule, a client-declared N/A shall
remain permitted subject to existing answer-type and execution-state rules.

**M4D3-APP-011** The governed service shall reject any client-supplied
`not_applicable_reason` beginning with the reserved prefix `REVIEW_REQUIRED:` for any
response, rule-governed or not, with `error_code = "reserved_reason_prefix"`.

**M4D3-APP-012** The population pass shall not overwrite a user-declared N/A on a
non-rule-governed response merely because `raw_value` is null.

**M4D3-APP-013** Population eligibility for a response shall be determined by checking
all of: applicability governance and current outcome; `is_not_applicable`;
`not_applicable_reason` including any reserved marker; `data_source_type_snapshot`;
existing `raw_value`; and execution status.

---

## Part 9 — Applicability persistence and historical reproducibility (M-C)

### 9.1 Verified model compatibility

**M4D3-PST-001** Verified schema fact: `ChecklistResponse.clean()` gates both N/A rules
on `is_not_applicable` being true — rule 2 (`raw_value` must be null) and rule 3
(reason required) are inactive when `is_not_applicable` is false. The field
`not_applicable_reason` is `CharField(null=True, blank=True, max_length=200)`. Storing a
reason string while `is_not_applicable` is false is therefore **permitted by the current
model** and requires no migration.

### 9.2 REVIEW_REQUIRED representation

**M4D3-PST-002** A `REVIEW_REQUIRED` outcome shall be persisted as a reserved marker in
`not_applicable_reason` of the form `REVIEW_REQUIRED:<ApplicabilityRule.reason_code>`,
with `is_not_applicable` remaining false and `raw_value` unchanged.

**M4D3-PST-003** The marker length is bounded: the 16-character prefix plus a
`reason_code` of at most 100 characters yields at most 116 characters, within
`MAX_NOT_APPLICABLE_REASON_CHARS = 200`.

**M4D3-PST-004** `ChecklistVersion` activation shall reject any `ApplicabilityRule`
whose composed marker would exceed `MAX_NOT_APPLICABLE_REASON_CHARS`, with
`error_code = "reason_marker_too_long"`.

**M4D3-PST-005** The marker shall be written only by the governed applicability service,
and `full_clean()` shall be called before every such save.

**M4D3-PST-006** No client PATCH shall write or clear the marker (see M4D3-APP-011).

### 9.2.1 Reason-code format validation

**M4D3-RFV-001** `ApplicabilityRule.reason_code` is `CharField(max_length=100)` with no
format validator in the current model. Activation-time validation shall require the
pattern `^[A-Z][A-Z0-9_]{0,99}$`.

**M4D3-RFV-002** The pattern is length-compatible with the field: it admits 1 to 100
characters inclusive, matching `max_length=100` exactly.

**M4D3-RFV-003** The pattern excludes the colon character, so a governed `reason_code`
can never introduce ambiguous marker syntax into `not_applicable_reason`.

**M4D3-RFV-004** The pattern excludes whitespace and lowercase characters.

**M4D3-RFV-005** Activation shall additionally reject any `reason_code` equal to
`REVIEW_REQUIRED` or beginning with `REVIEW_REQUIRED`, with
`error_code = "reserved_reason_code"`, so the reserved marker prefix can never collide
with a governed reason code.

**M4D3-RFV-006** The persisted marker form remains
`REVIEW_REQUIRED:<reason_code>`; with a maximum 100-character reason code the composed
marker is at most 116 characters, within `MAX_NOT_APPLICABLE_REASON_CHARS = 200`.

**M4D3-RFV-007** No client shall supply either a `reason_code` or a composed marker
through any request payload.

### 9.3 State-dependent evaluation

**M4D3-PST-007** For executions in `draft` or `returned`, applicability may be
recomputed from the current governed context through the governed service, and any
resulting change shall follow the Part 10 history, version and audit requirements.

**M4D3-PST-008** For executions in `submitted_for_review`, `approved`, `rejected`,
`cancelled` or `superseded`, the API shall expose the **persisted** applicability state
only. No read-time recomputation shall occur and no live FDA or IID data shall
influence the displayed historical applicability.

**M4D3-PST-009** The derived read-only field `applicability_outcome` shall be computed
from persisted state as follows: `is_not_applicable = True` → `not_applicable`;
`not_applicable_reason` starting with `REVIEW_REQUIRED:` → `review_required`; a
rule-governed response with neither → `applicable`; no rule → `no_rule`.

**M4D3-PST-010** No serialized payload shall simultaneously report
`is_not_applicable = false` and `applicability_outcome = "not_applicable"`; the derivation
in M4D3-PST-009 makes this combination unreachable.

**M4D3-PST-011** In editable states, a live evaluation result that differs from the
persisted state is advisory until the governed service persists it; the API shall never
present an unpersisted live result as the record's applicability.

**M4D3-PST-012** The governed evaluation pass shall persist the evaluated outcome
before an execution may be submitted, so every submitted execution carries a persisted
applicability state for every rule-governed response.

**M4D3-PST-013** `applicability_outcome` shall be read-only in every serializer and
shall never be writable by any client.

---

## Part 10 — Applicability re-evaluation and history (M-D)

### 10.1 Triggers

**M4D3-REV-001** Applicability re-evaluation shall occur at exactly these points:
initial execution creation; a governed response update whose changed response is a
declared applicability dependency; and an explicitly triggered authorized recalculation
on a `draft` or `returned` execution.

**M4D3-REV-002** No applicability re-evaluation shall occur automatically for
`submitted_for_review` or any terminal execution.

**M4D3-REV-003** No FDA or IID source refresh shall itself trigger re-evaluation; a
refresh takes effect only through an explicitly authorized recalculation in an editable
state.

**M4D3-REV-004** A governed applicability service shall own re-evaluation and be the
sole writer of `is_not_applicable`, `not_applicable_reason` and the reserved marker.

**M4D3-REV-005** 4D-3 shall not introduce any system-only background recalculation that
lacks an authenticated triggering actor.

### 10.2 History

**M4D3-HST-001** `ChecklistResponseHistory` was introduced for reviewer-conclusion
amendments; its docstring states one row per amendment and never on first entry. 4D-3
extends its governed reuse to persisted applicability transitions. This reuse shall be
documented in the model docstring update accompanying implementation.

**M4D3-HST-002** At initial execution creation no history row shall be written, because
responses are created with `raw_value = null` and `is_not_applicable = False` and no
prior state exists.

**M4D3-HST-003** When the persisted applicability state of an existing response changes,
a `ChecklistResponseHistory` row shall be created in the same transaction, populating
every required field: `response`, `prior_raw_value`, `new_raw_value`,
`prior_is_not_applicable`, `new_is_not_applicable`, `prior_not_applicable_reason`,
`new_not_applicable_reason`, `prior_version`, `new_version`, `correction_reason`,
`amended_by`, `source_classification_snapshot`.

**M4D3-HST-004** `amended_by` shall be the authenticated actor who triggered the
governed response update or the authorized recalculation. `execution.created_by` shall
never be recorded as the actor unless that user actually triggered the operation.

**M4D3-HST-005** `correction_reason` shall be the server-generated code
`APPLICABILITY_REEVALUATED` for system applicability transitions. A fabricated
human-authored correction reason shall never be written.

**M4D3-HST-006** `source_classification_snapshot` shall be set from the response's
existing `data_source_type_snapshot`.

**M4D3-HST-007** `prior_version` shall be the pre-update version and `new_version` the
incremented value; the response version shall increment on every persisted applicability
transition.

**M4D3-HST-008** History creation and the response update shall be atomic; no history
row shall be visible without its corresponding response state, and neither shall persist
if the transaction rolls back.

**M4D3-HST-009** `ChecklistResponseHistory` rows shall remain append-only; the existing
`GovernedHistoryMutationForbidden` guards shall not be bypassed.

### 10.3 N/A raw-value behavior

**M4D3-NA-001** When a response transitions to `NOT_APPLICABLE`, `raw_value` shall be
set to `null`, because `ChecklistResponse.clean()` rule 2 forbids a non-null
`raw_value` when `is_not_applicable` is true.

**M4D3-NA-002** The prior `raw_value` shall be preserved in
`ChecklistResponseHistory.prior_raw_value` before it is cleared, so no regulated value
is silently lost.

**M4D3-NA-003** `not_applicable_reason` shall be set from `ApplicabilityRule.reason_code`
on a `NOT_APPLICABLE` transition, satisfying `clean()` rule 3.

**M4D3-NA-004** When a response transitions from `NOT_APPLICABLE` back to `APPLICABLE`,
`raw_value` shall not be automatically restored from history; the response returns to a
data-required or governed population state and subsequent population follows the normal
source rules.

**M4D3-NA-005** On a transition back to `APPLICABLE`, `is_not_applicable` shall be set
false and `not_applicable_reason` cleared, with the prior values recorded in history.

---

## Part 11 — Completeness gate (M-A)

**M4D3-CMP-001** The existing `_check_execution_completeness()` requires a non-null
`raw_value` for every required response not marked N/A. Because `SYSTEM_CALCULATED`
responses keep `raw_value` null permanently (M4D3-MDL-006), a required calculated
question can never satisfy the current gate. The gate shall be extended by 4D-3.

**M4D3-CMP-002** A required `SYSTEM_CALCULATED` response shall be considered complete
only when all of: its persisted applicability outcome is `applicable`; a
`CalculationOutcome` row exists; `status = "complete"`; and `value` is non-null.

**M4D3-CMP-003** A required `SYSTEM_CALCULATED` response shall be considered incomplete
when `status` is `data_required`, `error`, or `calculating`; when no outcome row exists;
when `value` is null; or when its persisted applicability outcome is `review_required`.
The structured error shall name the question code and the outcome `reason_code`.

**M4D3-CMP-004** A required `FDA_DERIVED_DEFAULT` response shall be considered complete
only when the server-populated `raw_value` is non-null and no `REVIEW_REQUIRED` marker
is present.

**M4D3-CMP-005** Responses persisted as `NOT_APPLICABLE` shall continue to satisfy the
gate under the existing rule requiring a non-empty `not_applicable_reason`.

**M4D3-CMP-006** The completeness gate shall evaluate persisted state only; it shall
never trigger a live recomputation.

---

## Part 12 — Submission gate for REVIEW_REQUIRED (M-B)

**M4D3-SUB-001** An execution shall not transition to `submitted_for_review` while any
response carries an unresolved `REVIEW_REQUIRED` marker.

**M4D3-SUB-002** The gate shall apply regardless of `question.required`. An optional
question in `REVIEW_REQUIRED` state shall block submission exactly as a required one
does.

**M4D3-SUB-003** A blocked submission shall return a structured validation error with
`error_code = "review_required_unresolved"` and HTTP 400, listing the affected response
public UUIDs and the governing `ApplicabilityRule.code` values.

**M4D3-SUB-004** The error payload shall not include raw regulated answer values.

**M4D3-SUB-005** A blocked submission shall produce no status transition and no success
audit event.

**M4D3-SUB-006** Because override and reviewer confirmation are deferred to 4D-4,
`REVIEW_REQUIRED` is a terminal blocking state within 4D-3: the execution remains in
`draft` or `returned`, no automatic population or calculation occurs for the affected
response, and no approval is possible. 4D-3 shall not present any manual resolution
path.

**M4D3-SUB-007** The only 4D-3 resolution is correction of the governing source or
context followed by an authorized recalculation in an editable state.

---

## Part 13 — Dependency graph

**M4D3-DAG-001** The limits shall be named `CALCULATION_MAX_DEPENDENCY_DEPTH = 5` and
`CALCULATION_MAX_CASCADE_NODES = 10`, defined in
`backend/iig_checklist/calculation_registry.py`. These names shall be used to avoid
collision with `applicability.MAX_RECURSION_DEPTH = 5`, which bounds condition-tree
nesting and is unrelated.

**M4D3-DAG-002** The specification records these as a **governance decision, not an
empirical measurement**: the six approved calculations have shallow direct dependencies
and no current chain exceeds one calculated dependency level, so depth 5 and 10 affected
nodes provide bounded headroom. The values shall be revisited through a governed
specification change if real checklist content approaches them.

**M4D3-DAG-003** A dependency graph whose longest path exceeds
`CALCULATION_MAX_DEPENDENCY_DEPTH` shall be rejected at activation with
`error_code = "DEPENDENCY_DEPTH_EXCEEDED"`.

**M4D3-DAG-004** A graph exceeding `CALCULATION_MAX_CASCADE_NODES` reachable calculated
nodes from any single question shall be rejected at activation with
`error_code = "CASCADE_NODE_LIMIT_EXCEEDED"`.

**M4D3-DAG-005** Topological ordering shall use Kahn's algorithm or an equivalent
iterative algorithm; unbounded recursion is prohibited.

**M4D3-DAG-006** Nodes of equal topological precedence shall be ordered by ascending
`ChecklistQuestion.code`, producing identical output across repeated invocations.

**M4D3-DAG-007** A cycle shall be rejected at activation with
`error_code = "DEPENDENCY_CYCLE"`, naming the questions involved.

**M4D3-DAG-008** A dependency referencing a question code absent from the same
`ChecklistVersion` shall be rejected at activation with
`error_code = "UNKNOWN_DEPENDENCY_CODE"`.

**M4D3-DAG-009** Cross-version dependency references are prohibited.

**M4D3-DAG-010** The runtime cascade shall maintain a visited set; re-entering a visited
node shall set that outcome to `status = "error"`,
`reason_code = "DEPENDENCY_CYCLE"`, and halt further cascade.

---

## Part 14 — FDA source resolution

**M4D3-SRC-001** The active FDA release shall be resolved as the single
`FDADataSourceRelease` with `dataset_type = "fda_iid"` and `status = "active"`.
Determinism is guaranteed by the existing partial unique constraint
`unique_active_release_per_dataset_type`.

**M4D3-SRC-002** If no active release exists, the calculation shall fail closed with
`status = "error"` and `reason_code = "FDA_VALUE_UNAVAILABLE"`. No population shall
occur.

**M4D3-SRC-003** The release UUID shall never be supplied by a client; it shall be
resolved server-side on every call.

**M4D3-SRC-004** `run_preview()` arguments shall be resolved as follows:
`active_release_public_id` from M4D3-SRC-001; `route_code` and `dosage_form_code` from
the execution's `FormulationVersion.product` subject to Part 14.2;
`proposed_quantity_per_unit` and `proposed_quantity_unit` from the
`FormulationComponent`; `total_dosage_unit_weight` and `total_dosage_unit_weight_unit`
from the `FormulationVersion` (verified non-nullable, M4D3-SRC-014);
`maximum_dosage_units_per_day` from the governed resolver in Part 14.1; and substance
identity fields from the `FormulationComponent`.

**M4D3-SRC-005** Any required `run_preview()` argument that cannot be resolved shall
produce `status = "data_required"` and `reason_code = "DATA_REQUIRED"` for the affected
outcome, without raising.

**M4D3-SRC-006** This requirement applies **only to runtime data that is genuinely
unresolved, invalid or ambiguous** — principally a maximum-dosage-units resolution
failure under M4D3-MDU-013 or an unresolvable controlled term under Part 14.2. Such a
condition shall fail closed under M4D3-SRC-005 and shall be surfaced through governed
provenance. It shall not be read as a general statement that the fields named in
M4D3-SRC-004 may be absent from the schema.

**M4D3-SRC-014** Verified schema facts, confirmed against
`backend/formulations/models.py`: `FormulationVersion.total_dosage_unit_weight` is
`DecimalField(max_digits=20, decimal_places=6)` — **non-nullable** — and carries
`CheckConstraint(total_dosage_unit_weight__gt=0)` named
`formulation_total_weight_positive`; `FormulationVersion.total_dosage_unit_weight_unit`
is `CharField(max_length=50)` and is **required** (no `blank=True`). Neither field may be
described as potentially unavailable.

**M4D3-SRC-007** All `AssessmentSnapshot` reads and writes shall filter by
`tenant = execution.tenant`.

**M4D3-SRC-008** `run_preview()` returning no match shall yield null calculation inputs;
the calculation shall still run and report `DATA_REQUIRED` or `INGREDIENT_UNRESOLVED`.

**M4D3-SRC-009** Multiple candidate precedent records shall be resolved by the existing
governed selection logic in `iid_assessment`; 4D-3 shall not implement its own.

**M4D3-SRC-010** A withdrawn, superseded or non-active source record shall map through
the translation table to `REGULATORY_REVIEW_REQUIRED`.

**M4D3-SRC-011** Once an execution leaves `draft`/`returned`,
`source_assessment_snapshot_public_id` shall not be updated.

**M4D3-SRC-012** A change to the active FDA release shall never automatically
recalculate an existing execution.

**M4D3-SRC-013** No 4D-3 code shall write to `fda_data` models.

### Part 14.1 — Maximum dosage units resolver

**M4D3-MDU-001** Verified schema facts. Two governed sources exist and both shall be
considered:

| Source | Definition | Cardinality |
|---|---|---|
| `FormulationVersion.maximum_dosage_units_per_day` | `DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)` | zero or one per version |
| `DosingRegimen.maximum_units_per_day` | `DecimalField(max_digits=10, decimal_places=4)`, required, with `CheckConstraint(maximum_units_per_day__gt=0)` named `dosing_regimen_max_units_positive` | zero or more per version, `related_name="dosing_regimens"`, no uniqueness on `formulation_version` |

A scalar-only resolution rule is prohibited.

**M4D3-MDU-002** Step 1 — the version-level candidate shall be `FormulationVersion.maximum_dosage_units_per_day`
when it is non-null and strictly greater than zero; otherwise the version-level candidate
is absent.

**M4D3-MDU-003** Step 1 — regimen candidates shall be every `DosingRegimen` row whose
`formulation_version` is the execution's `FormulationVersion`. Verified schema fact:
`DosingRegimen` has **no** status or lifecycle field, so no lifecycle filter shall be
invented; every related row is a governed candidate.

**M4D3-MDU-004** Step 1 — candidate rows shall be constrained to the execution tenant
through `formulation_version__product__tenant = execution.tenant`. A row failing this
constraint shall be excluded and shall contribute nothing to provenance.

**M4D3-MDU-005** Step 1 — any candidate value that is null, non-positive, or not a valid
`Decimal` shall be excluded from selection and recorded as invalid in provenance.

**M4D3-MDU-006** Step 1 — no dosing value shall ever be accepted from a client request
payload.

**M4D3-MDU-007** Step 2 — regimen resolution: with no eligible regimen the regimen
candidate is absent; with exactly one, its `maximum_units_per_day` is the regimen
candidate; with more than one, the **highest** valid `maximum_units_per_day` shall be
selected as the conservative worst-case exposure input.

**M4D3-MDU-008** Step 2 — where two or more regimens share the highest value, the
selected row shall be the one with the lowest `public_id` in ascending UUID order,
producing a deterministic and repeatable choice.

**M4D3-MDU-009** Step 2 — `DosingRegimen.patient_population` is
`CharField(max_length=255, blank=True)` with no controlled vocabulary, and neither
`ChecklistExecution` nor `ProductDevelopmentRecord` exposes a governed patient-population
selector. It shall therefore be treated as **provenance only and never as a filter**.
Worst-case selection across all populations shall be retained. Should a deterministic,
validated selector be introduced in a later milestone, filtering may be reconsidered
through a governed specification change.

**M4D3-MDU-010** Step 3 — reconciliation of the two candidates:

| Version candidate | Regimen candidate | Selected value | Provenance source type |
|---|---|---|---|
| present | absent | version scalar | `formulation_version` |
| absent | present | regimen value | `dosing_regimen` |
| present | present, equal | that value | `combined_conservative` |
| present | present, different | the **higher** of the two | `combined_conservative` |

**M4D3-MDU-011** Step 3 — when both candidates are present and differ, a controlled
provenance flag `source_disagreement = true` shall be recorded alongside both values.

**M4D3-MDU-012** Step 3 — the resolver shall never prefer the lower value, never average
or otherwise combine values arithmetically, and never select by row creation order or
database insertion order.

**M4D3-MDU-013** Step 4 — the resolver shall fail closed when neither candidate exists;
when every available value is invalid; when tenant ownership cannot be established; when
the formulation relationship is ambiguous; or when a required source record cannot be
deterministically resolved.

**M4D3-MDU-014** Step 4 — a fail-closed resolution shall leave
`maximum_dosage_units_per_day` unresolved so that the engine's own canonicalization
applies: `calculate_daily_exposure` returns `MAX_DAILY_UNITS_MISSING`, which resolves to
the string `DATA_REQUIRED` and translates to `status = "data_required"` with
`reason_code = "DATA_REQUIRED"`. The engine mapping shall be preserved unchanged and no
new stored status or reason value shall be introduced on `CalculationOutcome`.

**M4D3-MDU-015** The specific resolver failure shall be recorded as a governed detail
code in `input_provenance` (M4D3-RSN-006), not in `CalculationOutcome.reason_code`. No
database field and no migration shall be created for it.

**M4D3-MDU-016** Resolver provenance shall record: the selected source type
(`formulation_version`, `dosing_regimen`, or `combined_conservative`); the
`FormulationVersion` public UUID; the version scalar where present; the public UUIDs of
every considered `DosingRegimen`; their `patient_population` labels; every valid
candidate value; the selected value; whether the UUID tie-breaker was applied; the
`source_disagreement` flag; the resolver version; and the calculation registry
`binding_version`.

**M4D3-MDU-017** The resolver shall carry an explicit `resolver_version` string,
incremented whenever its selection logic changes, and recorded in provenance.

**M4D3-MDU-018** No internal database primary key shall appear in resolver provenance;
only public UUIDs and approved labels.

**M4D3-MDU-019** Clients shall receive only the sanitized provenance summary defined in
M4D3-SER-002; full resolver provenance remains server-side.

**M4D3-MDU-020** Repeated execution of the resolver against unchanged data shall select
an identical value and emit provenance entries in an identical, stable order.

**M4D3-MDU-021** A `DosingRegimen` added, altered or removed after an execution leaves
`draft`/`returned` shall not alter that execution's persisted calculation result or
stored provenance.

**M4D3-MDU-022** Recorded monotonicity rationale, verified against
`backend/iid_assessment/calculations.py` and `backend/formulations/models.py`:
`calculate_daily_exposure` computes `quantity_per_dosage_unit × maximum_dosage_units_per_day`;
`FormulationComponent.quantity_per_dosage_unit` is constrained strictly positive by
`CheckConstraint` `formulation_component_quantity_positive`; daily exposure therefore
increases monotonically with maximum daily units. `calculate_percentage_of_mde` computes
`(exposure / mde) × 100` and increases with exposure; `calculate_difference_from_mde`
computes `mde − exposure` and decreases with exposure, meaning less remaining headroom.
Selecting the highest daily-units candidate is therefore safety-conservative for every
current consumer, and no consuming calculation inverts.

**M4D3-MDU-023** The three remaining approved functions —
`calculate_percentage_w_w`, `calculate_percentage_of_potency` and
`calculate_difference_from_potency` — do not consume maximum daily units, so the resolver
does not affect them.

**M4D3-MDU-024** Governance rule: any new calculation that consumes maximum daily units
shall require a documented monotonicity review before it is bound in the registry. The
global highest-value resolver shall not be reused automatically for a calculation with
inverse or non-monotonic behavior; this specification and its tests shall be amended
first.

### Part 14.2 — Blank controlled-term behavior

**M4D3-RTE-001** Verified schema fact: `ProductDevelopmentRecord.route` and
`ProductDevelopmentRecord.dosage_form` are both `CharField(max_length=255, blank=True)`
and may therefore hold the empty string.

**M4D3-RTE-002** An empty or whitespace-only `route` or `dosage_form` shall be treated as
**missing governed source data**, not as a resolved value.

**M4D3-RTE-003** A blank value shall not be passed to `run_preview()` as a resolved
argument.

**M4D3-RTE-004** `run_preview()` resolves controlled terms with
`ControlledRoute.objects.filter(code=..., lifecycle="active").first()` and the equivalent
dosage-form lookup, both of which return `None` for an unmatched or empty code. A `None`
result shall never be treated as successful resolution.

**M4D3-RTE-005** No arbitrary fallback route or dosage form shall be selected, and no
default controlled term shall be substituted.

**M4D3-RTE-006** A blank route or dosage form shall produce
`status = "data_required"` with `reason_code = "DATA_REQUIRED"`, and the specific cause
shall be recorded as a governed detail code in provenance. A non-blank but unknown code,
and a code whose controlled term is not `lifecycle = "active"`, shall produce the
engine's existing canonical unresolved-term behavior, translating to
`ROUTE_MISMATCH` or `DOSAGE_FORM_MISMATCH` as applicable.

---

## Part 15 — AssessmentSnapshot ownership

**M4D3-SNP-001** `iig_checklist` may consume `iid_assessment` preview and calculation
services. The import direction remains one-way and no reverse import shall be
introduced.

**M4D3-SNP-002** `iig_checklist` shall not construct, save, or update `iid_assessment`
model classes directly.

**M4D3-SNP-003** Governed snapshot creation shall occur only through an approved
`iid_assessment` service or helper function that owns the write.

**M4D3-SNP-004** If no such service exists, adding one inside `iid_assessment` is part
of 4D-3's implementation surface; it shall not be replaced by a direct cross-app model
write.

**M4D3-SNP-005** `AssessmentSnapshot.created_by` shall be the authenticated actor who
triggered execution creation or the authorized recalculation. It shall be null only
where existing approved snapshot conventions explicitly allow a null creator.

**M4D3-SNP-006** `CalculationOutcome.source_assessment_snapshot_public_id` shall be set
to the resulting snapshot's `public_id`.

**M4D3-SNP-007** Scope exclusion SCOPE-OUT-19 forbids direct model writes by
`iig_checklist`; it does not forbid governed snapshot creation through an
`iid_assessment` service, and shall not be read as doing so.

---

## Part 16 — Population and recalculation

**M4D3-POP-001** The population pass at execution creation shall run inside a single
`transaction.atomic()` in this order: create execution and pre-create response and
outcome rows (with registry-resolved `calculation_name` per M4D3-REG-013); assemble the
applicability context; evaluate and persist applicability for each rule-governed
question; populate eligible `FDA_DERIVED_DEFAULT` answers; compute eligible
`SYSTEM_CALCULATED` answers; translate engine results; `full_clean()` and save each
outcome; and dispatch audit via `transaction.on_commit()`.

**M4D3-POP-002** All FDA-derived population shall complete before any calculation
begins.

**M4D3-POP-003** A persisted `not_applicable` or `review_required` outcome shall block
both population and calculation for that question.

**M4D3-POP-004** A persisted `applicable` outcome, or the absence of a rule, shall
permit population and calculation.

**M4D3-POP-005** An uncaught exception at any step shall roll back the entire
transaction; no partial population shall be committed.

**M4D3-POP-006** Population and recalculation shall be rejected for executions outside
`draft` and `returned` with `error_code = "execution_not_recalculable"`.

**M4D3-POP-007** Re-running population with identical inputs shall create no history
row, shall not increment any response version, shall emit no audit event, and shall not
modify `inputs`, `input_provenance` or `source_assessment_snapshot_public_id`.

**M4D3-POP-008** A `FDA_DERIVED_DEFAULT` resolver returning `None` shall leave
`raw_value` null with no error and no N/A marking.

**M4D3-RCL-001** The governed response-update service shall trigger cascade
recalculation when the updated response is a declared dependency of any
`SYSTEM_CALCULATED` question in the same execution.

**M4D3-RCL-002** Affected questions shall be processed in the stable topological order
of M4D3-DAG-006.

**M4D3-RCL-003** Recalculation shall update existing outcome rows in place, calling
`full_clean()` before each save.

**M4D3-RCL-004** Recalculation shall produce no audit event and no version change when
`status`, `value`, `reason_code` and `generated_at` are all unchanged.

**M4D3-RCL-005** Terminal and submitted executions shall never be recalculated
automatically.

---

## Part 17 — Transactions and locking

**M4D3-TXN-001** Lock order shall be: the `ChecklistExecution` row via
`select_for_update()`; then affected `ChecklistResponse` rows in ascending primary-key
order; then `CalculationOutcome` rows in ascending primary-key order. This order shall
be observed without exception.

**M4D3-TXN-002** The triggering response write and all dependent outcome updates shall
occur inside one `transaction.atomic()`.

**M4D3-TXN-003** `expected_version` shall be validated against the **locked** response
row, after the lock is acquired and before any write.

**M4D3-TXN-004** An exception after the response write shall roll back both the response
update and every outcome update.

**M4D3-TXN-005** All audit events shall be dispatched via `transaction.on_commit()`;
no success audit shall fire after a rollback.

**M4D3-TXN-006** Concurrent governed updates on one execution shall serialize on the
execution lock.

---

## Part 18 — Serialization

**M4D3-SER-001** `CalculationOutcome` shall be serialized as a read-only nested object
exposing exactly: `public_id`, `calculation_name`, `formula_version`, `status`, `value`,
`unit`, `reason_code`, `rounding_rule`, `generated_at`,
`source_assessment_snapshot_public_id`, `registry_binding_version`, and
`provenance_summary`.

**M4D3-SER-002** `provenance_summary` shall be a server-assembled object containing only
`formula_version`, `registry_binding_version`, `source_snapshot_id`, and sanitized
per-input source labels.

**M4D3-SER-003** The raw `inputs` and `input_provenance` dictionaries shall never be
exposed to any client.

**M4D3-SER-004** No internal database primary key, storage path, registry function
reference, or cross-tenant metadata shall appear in any serialized payload.

**M4D3-SER-005** The `CalculationOutcome` serializer shall define no `create`, `update`
or `partial_update` method.

**M4D3-SER-006** `applicability_outcome` shall be included as a derived read-only field
on the response representation, computed per M4D3-PST-009.

**M4D3-SER-007** The `REVIEW_REQUIRED:` marker shall not be exposed verbatim; the API
shall expose the derived `applicability_outcome` and the governing rule
`reason_code` separately.

**M4D3-SER-008** The OpenAPI schema for `status` shall enumerate only the four stored
values.

**M4D3-SER-009** Pagination behavior shall remain unchanged.

---

## Part 19 — Audit

**M4D3-AUD-001** All 4D-3 audit events shall be dispatched via `transaction.on_commit()`.

**M4D3-AUD-002** Defined events: `iig_checklist.response.fda_populated`;
`iig_checklist.calculation.completed`; `iig_checklist.calculation.data_required`;
`iig_checklist.calculation.error`; `iig_checklist.calculation.recalculated`;
`iig_checklist.response.applicability_changed`;
`iig_checklist.response.review_required`; `iig_checklist.execution.submission_blocked`.

**M4D3-AUD-003** Payloads shall include execution and response public UUIDs, outcome
public UUID where applicable, prior and new response version, `calculation_name`,
`formula_version`, `registry_binding_version`, stored `status`, `reason_code`, and
`source_assessment_snapshot_public_id` where applicable.

**M4D3-AUD-004** Payloads shall exclude raw answer values, the full `inputs` and
`input_provenance` dictionaries, internal primary keys, storage paths, and cross-tenant
metadata.

**M4D3-AUD-005** System-populated answers shall never emit
`iig_checklist.response.entered`; the event type alone shall distinguish system-generated
from user-entered values.

**M4D3-AUD-006** No audit event shall be emitted for an unchanged recalculation result.

**M4D3-AUD-007** Operational failure audit, where emitted, shall be clearly
distinguished from success audit and shall never be dispatched through
`transaction.on_commit()` of a rolled-back transaction.

---

## Part 20 — API, frontend, security, migration

### 20.1 API

**M4D3-API-001** No generic write endpoint for `CalculationOutcome` shall exist; PATCH
or PUT shall return 404 or 405.

**M4D3-API-002** Existing response-list and response-detail endpoints shall include the
nested read-only outcome and the derived `applicability_outcome`.

**M4D3-API-003** Tenant-scoped lookup shall precede object disclosure; cross-tenant
identifiers shall return 404.

**M4D3-API-004** An in-tenant actor lacking permission shall receive 403.

**M4D3-API-005** Responses on executions outside `draft`/`returned` shall reject writes
with `error_code = "response_immutable"` and HTTP 400.

### 20.2 Frontend

**M4D3-FE-001** Provenance labels shall be displayed per `data_source_type_snapshot`:
FDA-derived (read-only), calculated, pre-filled, reviewer-confirmed.

**M4D3-FE-002** For calculated questions, the value and unit shall be shown when
`status = "complete"`; otherwise a legible label derived from `reason_code` shall be
shown. Zero, blank, or the word "complete" shall never stand in for a blocked
calculation.

**M4D3-FE-003** `applicability_outcome = "review_required"` shall render a "Review
required" state; the question shall not be shown as applicable or not-applicable, and no
populated value shall be displayed.

**M4D3-FE-004** A blocked submission shall surface the affected questions returned by
M4D3-SUB-003.

**M4D3-FE-005** The frontend shall send `expected_version` on every governed response
update and handle 409 per M4D3-VER-007.

**M4D3-FE-006** No frontend source file shall contain any of the six calculation
function names; a CI lint rule shall enforce this.

**M4D3-FE-007** The frontend shall reload from the server after an edit and shall never
compute a calculation result locally.

**M4D3-FE-008** DTO mapping shall remain centralized in the existing
`execution-mappers.ts` module.

**M4D3-FE-009** New and changed UI states shall satisfy the project's accessibility
checks, including accessible names for the review-required and calculation-error states.

### 20.3 Security

**M4D3-SEC-001** No `eval`, `exec`, dynamic import from a registry key, `getattr` from
an untrusted string, SQL fragment, or arbitrary expression shall appear in any 4D-3
module.

**M4D3-SEC-002** Every query touching executions, responses, outcomes or snapshots
shall be tenant-filtered.

**M4D3-SEC-003** No translation path passing through an unknown engine status shall
yield `status = "complete"`.

**M4D3-SEC-004** `input_provenance` keys beginning with an underscore are
server-controlled; any request supplying one shall be rejected.

**M4D3-SEC-005** The existing import-linter contracts shall continue to pass;
`iig_checklist` may import `fda_data`, `formulations`, `iid_assessment` and `documents`,
and none of those may import `iig_checklist`.

### 20.4 Reproducibility

**M4D3-PRV-001** The reproducibility chain shall consist of `calculation_name`,
`formula_version`, `inputs`, `input_provenance`, `rounding_rule`, `generated_at`,
`source_assessment_snapshot_public_id`, and the deployed code version. No new database
column shall be added.

**M4D3-PRV-002** `input_provenance` shall always include the reserved key
`_registry_binding_version` set to the resolved entry's `binding_version`, alongside a
per-input source descriptor.

**M4D3-PRV-003** A missing or unrecognized `_registry_binding_version` at read time
shall be logged as a data-integrity warning without raising.

**M4D3-PRV-004** `formula_version` and `binding_version` shall be governed
independently; a change to resolvers or dependencies requires a `binding_version`
increment even when `formula_version` is unchanged.

### 20.5 Migration and compatibility

**M4D3-MIG-001** No Django migration, no new database field, and no data backfill shall
be introduced by 4D-3.

**M4D3-MIG-002** Existing 4D-2 `CalculationOutcome` and `ChecklistResponse` rows shall
remain valid; historical rows require no transformation.

**M4D3-MIG-003** Deployment shall not automatically recalculate any existing execution;
approved, rejected, cancelled and superseded executions shall be unchanged.

**M4D3-MIG-004** The introduction of required `expected_version` is a **breaking API
contract change**. The specification shall not describe 4D-3's API changes as additions
only.

**M4D3-MIG-005** Backend and frontend shall deploy together; old clients shall receive
a structured validation error rather than silently overwriting.

**M4D3-MIG-006** The contract change shall be recorded in release notes and the API
contract documentation.

**M4D3-MIG-007** Rollback requires a coordinated backend and frontend rollback; no data
transformation is required because the schema is unchanged.

**M4D3-MIG-008** A legacy `calculation_binding_identifier` absent from the registry
shall fail closed per M4D3-REG-014 at creation and M4D3-REG-016 at runtime, never with
an unhandled exception.

---

## Part 21 — Acceptance matrix

Every normative requirement identifier appears exactly once below.

**Review-assertion rows.** Rows whose implementation component is `Review assertion`
record a verified architectural or source fact rather than a runtime control: that a
service does not exist, an existing field type or nullability, the absence of a database
constraint, an existing constant or migration fact, or the breaking nature of an API
change. Their evidence is source inspection recorded in the review checklist, not an
executable test, and no fabricated runtime test shall be authored for them. Every other
row remains a normative control requiring implementation and executable coverage. The
review-assertion rows are exactly these fourteen: M4D3-SVC-001, M4D3-VER-001,
M4D3-OUT-003, M4D3-OUT-007, M4D3-PST-001, M4D3-SRC-014, M4D3-RTE-001, M4D3-DAG-002,
M4D3-SNP-007, M4D3-MIG-004, M4D3-INP-001, M4D3-MDU-022, M4D3-MDU-023 and M4D3-DEP-004.

M4D3-REG-001 and M4D3-MDU-001 are **not** review assertions: each records a verified fact
*and* imposes a normative obligation (correcting `create_execution()`, and prohibiting a
scalar-only resolution rule), so both retain an executable implementation component.

| Req ID | Implementation component | Test | Expected result | Controlled risk |
|---|---|---|---|---|
| M4D3-MDL-001 | `ChecklistQuestion` usage | TST-101 | Identifier stores registry key only | Injection |
| M4D3-MDL-002 | Response services | TST-102 | Snapshot never modified | Data integrity |
| M4D3-MDL-003 | Guard predicates | TST-103 | Guards test `answer_type` | Correctness |
| M4D3-MDL-004 | Population service | TST-104 | Reviewer/approval rows untouched | Regulatory |
| M4D3-MDL-005 | Population service | TST-105 | User value never overwritten | Regulatory |
| M4D3-MDL-006 | Population service | TST-106 | Calculated `raw_value` stays null | Data integrity |
| M4D3-MDL-007 | Outcome writer | TST-107 | Only four stored statuses; never `calculating` | Data integrity |
| M4D3-MDL-008 | Outcome writer | TST-108 | Engine string rejected by `full_clean()` | Data integrity |
| M4D3-MDL-009 | Outcome writer | TST-109 | No client content in inputs/provenance | Security |
| M4D3-MDL-010 | Population service | TST-110 | Rows updated, never created | Data integrity |
| M4D3-MDL-011 | Evaluator | TST-111 | Runtime grammar honored | Correctness |
| M4D3-MDL-012 | Static check | TST-112 | No `condition_checksum` reference | Correctness |
| M4D3-MDL-013 | Evaluator | TST-113 | Outcomes read from rule fields | Regulatory |
| M4D3-REG-001 | `create_execution()` | TST-114 | Documented defect corrected | Correctness |
| M4D3-REG-002 | Registry module | TST-115 | Three concepts distinct | Correctness |
| M4D3-REG-003 | `create_execution()` | TST-116 | Identifier never written to `calculation_name` | Data integrity |
| M4D3-REG-004 | Registry module | TST-117 | Module-level immutable dict | Security |
| M4D3-REG-005 | Registry module | TST-118 | All entry fields present | Correctness |
| M4D3-REG-006 | Registry module | TST-119 | Identifier format and length valid | Data integrity |
| M4D3-REG-007 | Registry module | TST-120 | Exact identifier→name mapping | Correctness |
| M4D3-REG-008 | Registry module | TST-121 | Binding version immutable | Reproducibility |
| M4D3-REG-009 | Import-time self-check | TST-122 | Invalid entry raises at import | Data integrity |
| M4D3-REG-010 | Input resolvers | TST-123 | Only two resolver forms | Security |
| M4D3-REG-011 | Input resolvers | TST-124 | No dynamic evaluation | Security |
| M4D3-REG-012 | Registry lookup | TST-125 | Explicit `None` handling | Robustness |
| M4D3-REG-013 | `create_execution()` | TST-126 | Entry resolved before outcome creation | Correctness |
| M4D3-REG-014 | `create_execution()` | TST-127 | Unknown key aborts atomically, no rows remain | Data integrity |
| M4D3-REG-015 | `create_execution()` | TST-128 | Invalid `calculation_name` aborts atomically | Data integrity |
| M4D3-REG-016 | Population service | TST-129 | Runtime unknown key fails closed | Security |
| M4D3-REG-017 | Registry alias | TST-130 | Alias semantics identical; no reinterpretation | Regulatory |
| M4D3-REG-018 | Activation service | TST-131 | All activation checks enforced | Security |
| M4D3-REG-019 | Activation service | TST-132 | Structured rejection; status unchanged | Data integrity |
| M4D3-SVC-001 | Review assertion | TST-133 | No `enter_response()` claimed | Correctness |
| M4D3-SVC-002 | New service | TST-134 | Governed service exists | Architecture |
| M4D3-SVC-003 | New service | TST-135 | All responsibilities owned | Architecture |
| M4D3-SVC-004 | View adapter | TST-136 | View contains no business logic | Architecture |
| M4D3-SVC-005 | New service | TST-137 | Server-controlled value PATCH → 403 | Security |
| M4D3-SVC-006 | New service | TST-138 | Override fields untouched | Scope |
| M4D3-SVC-007 | `answer_sources.py` | TST-139 | Explicit dispatch, no reflection | Security |
| M4D3-SVC-008 | `answer_sources.py` | TST-140 | Resolvers pure | Correctness |
| M4D3-VER-001 | Review assertion | TST-141 | Breaking change acknowledged | Compatibility |
| M4D3-VER-002 | Request serializer | TST-142 | Field required | Data integrity |
| M4D3-VER-003 | Deployment | TST-143 | Atomic deploy documented | Compatibility |
| M4D3-VER-004 | New service | TST-144 | Missing → 400, no write | Data integrity |
| M4D3-VER-005 | New service | TST-145 | Stale → 409, no write/history/audit | Data integrity |
| M4D3-VER-006 | New service | TST-146 | Version increments by one | Data integrity |
| M4D3-VER-007 | Frontend | TST-147 | 409 reloads, no auto-retry | Correctness |
| M4D3-VER-008 | OpenAPI/release notes | TST-148 | Schema regenerated | Compatibility |
| M4D3-OUT-001 | Outcome writer | TST-149 | `full_clean()` before every save | Data integrity |
| M4D3-OUT-002 | Test suite | TST-150 | No bare-save validation assertion | Correctness |
| M4D3-OUT-003 | Review assertion | TST-151 | No uniqueness claimed | Correctness |
| M4D3-OUT-004 | New service | TST-152 | Update-in-place under lock | Data integrity |
| M4D3-OUT-005 | New service | TST-153 | Duplicate rows fail closed | Data integrity |
| M4D3-OUT-006 | Repository check | TST-154 | No migration added | Compatibility |
| M4D3-OUT-007 | Review assertion | TST-155 | Not claimed as model invariant | Correctness |
| M4D3-OUT-008 | Outcome writer | TST-156 | Non-complete with value rejected | Data integrity |
| M4D3-TRL-001 | Translation module | TST-157 | Pure function, no DB access | Architecture |
| M4D3-TRL-002 | Translation module | TST-158 | Full table; 100% branch coverage | Security |
| M4D3-TRL-003 | Translation module | TST-159 | Aliases canonicalize by value | Correctness |
| M4D3-TRL-004 | Translation module | TST-160 | Valid UTC/offset parsed tz-aware | Data integrity |
| M4D3-TRL-005 | Translation module | TST-161 | Empty/malformed/naive → error outcome | Data integrity |
| M4D3-TRL-006 | Translation module | TST-162 | No client timestamp accepted | Security |
| M4D3-RSN-001 | Translation module | TST-163 | Allow-list contains the 15 codes | Data integrity |
| M4D3-RSN-002 | Translation module | TST-164 | Casing and length valid | Data integrity |
| M4D3-RSN-003 | New service | TST-165 | Unknown code rejected | Data integrity |
| M4D3-RSN-004 | Request serializers | TST-166 | Client cannot supply reason code | Security |
| M4D3-RSN-005 | Outcome writer | TST-167 | No exception text stored | Security |
| M4D3-APP-001 | Evaluator | TST-168 | Pure, no dynamic evaluation | Security |
| M4D3-APP-002 | Evaluator | TST-169 | Grammar and operators match validator | Correctness |
| M4D3-APP-003 | Evaluator | TST-170 | Malformed node raises `RuntimeError` | Robustness |
| M4D3-APP-004 | Evaluator | TST-171 | Correct branch outcome returned | Regulatory |
| M4D3-APP-005 | Evaluator | TST-172 | Missing field treated as absent | Correctness |
| M4D3-APP-006 | Context assembly | TST-173 | Exactly the six registry fields | Correctness |
| M4D3-APP-007 | Context assembly | TST-174 | Context never persisted | Data integrity |
| M4D3-APP-008 | Applicability service | TST-175 | Fields server-owned | Security |
| M4D3-APP-009 | New service | TST-176 | Client write → 403 | Security |
| M4D3-APP-010 | New service | TST-177 | Non-rule N/A still permitted | Usability |
| M4D3-APP-011 | New service | TST-178 | Reserved prefix rejected | Security |
| M4D3-APP-012 | Population service | TST-179 | User N/A preserved | Regulatory |
| M4D3-APP-013 | Population service | TST-180 | All eligibility checks applied | Correctness |
| M4D3-PST-001 | Review assertion | TST-181 | Model compatibility verified | Correctness |
| M4D3-PST-002 | Applicability service | TST-182 | Marker persisted correctly | Regulatory |
| M4D3-PST-003 | Applicability service | TST-183 | Marker ≤ 200 chars | Data integrity |
| M4D3-PST-004 | Activation service | TST-184 | Over-long marker rejected | Data integrity |
| M4D3-PST-005 | Applicability service | TST-185 | Sole writer; `full_clean()` called | Security |
| M4D3-PST-006 | New service | TST-186 | Client cannot write/clear marker | Security |
| M4D3-PST-007 | Applicability service | TST-187 | Editable states recompute | Correctness |
| M4D3-PST-008 | Serializer | TST-188 | Submitted/terminal use persisted state only | Regulatory |
| M4D3-PST-009 | Serializer | TST-189 | Derivation rules correct | Correctness |
| M4D3-PST-010 | Serializer | TST-190 | Contradictory payload unreachable | Data integrity |
| M4D3-PST-011 | Serializer | TST-191 | Live result never presented as record | Regulatory |
| M4D3-PST-012 | Submission gate | TST-192 | State persisted before submission | Regulatory |
| M4D3-PST-013 | Serializer | TST-193 | Field read-only | Security |
| M4D3-REV-001 | Applicability service | TST-194 | Exactly three triggers | Correctness |
| M4D3-REV-002 | Applicability service | TST-195 | No submitted/terminal re-evaluation | Regulatory |
| M4D3-REV-003 | Applicability service | TST-196 | Source refresh alone does not trigger | Regulatory |
| M4D3-REV-004 | Applicability service | TST-197 | Sole writer enforced | Security |
| M4D3-REV-005 | Architecture | TST-198 | No actorless background recalculation | Regulatory |
| M4D3-HST-001 | Model docstring | TST-199 | Governed reuse documented | Correctness |
| M4D3-HST-002 | Population service | TST-200 | No history at creation | Correctness |
| M4D3-HST-003 | Applicability service | TST-201 | All twelve fields populated | Regulatory |
| M4D3-HST-004 | Applicability service | TST-202 | `amended_by` is triggering actor | Regulatory |
| M4D3-HST-005 | Applicability service | TST-203 | `APPLICABILITY_REEVALUATED` used | Regulatory |
| M4D3-HST-006 | Applicability service | TST-204 | Classification snapshot copied | Correctness |
| M4D3-HST-007 | Applicability service | TST-205 | Versions recorded and incremented | Data integrity |
| M4D3-HST-008 | Applicability service | TST-206 | Atomic with response update | Data integrity |
| M4D3-HST-009 | History model | TST-207 | Append-only guards intact | Regulatory |
| M4D3-NA-001 | Applicability service | TST-208 | `raw_value` nulled on N/A | Data integrity |
| M4D3-NA-002 | Applicability service | TST-209 | Prior value preserved in history | Regulatory |
| M4D3-NA-003 | Applicability service | TST-210 | Reason set from rule | Regulatory |
| M4D3-NA-004 | Applicability service | TST-211 | No auto-restore on return to applicable | Regulatory |
| M4D3-NA-005 | Applicability service | TST-212 | Flags cleared and recorded | Data integrity |
| M4D3-CMP-001 | Completeness gate | TST-213 | Gate extended | Correctness |
| M4D3-CMP-002 | Completeness gate | TST-214 | Complete only on all four conditions | Regulatory |
| M4D3-CMP-003 | Completeness gate | TST-215 | Every incomplete case blocks | Regulatory |
| M4D3-CMP-004 | Completeness gate | TST-216 | FDA-derived completeness rule | Regulatory |
| M4D3-CMP-005 | Completeness gate | TST-217 | N/A rule preserved | Compatibility |
| M4D3-CMP-006 | Completeness gate | TST-218 | Persisted state only | Regulatory |
| M4D3-SUB-001 | Submission gate | TST-219 | Unresolved marker blocks submission | Regulatory |
| M4D3-SUB-002 | Submission gate | TST-220 | Blocks regardless of `required` | Regulatory |
| M4D3-SUB-003 | Submission gate | TST-221 | Structured 400 with UUIDs and rule codes | Usability |
| M4D3-SUB-004 | Submission gate | TST-222 | No raw values in error | Security |
| M4D3-SUB-005 | Submission gate | TST-223 | No transition, no success audit | Data integrity |
| M4D3-SUB-006 | Submission gate | TST-224 | No manual resolution path offered | Scope |
| M4D3-SUB-007 | Recalculation | TST-225 | Correction + recalculation is the only path | Regulatory |
| M4D3-DAG-001 | Registry module | TST-226 | Constants named and located | Correctness |
| M4D3-DAG-002 | Review assertion | TST-227 | Rationale stated as governance decision | Correctness |
| M4D3-DAG-003 | Activation service | TST-228 | Depth > 5 rejected | Security |
| M4D3-DAG-004 | Activation service | TST-229 | Node count > 10 rejected | Security |
| M4D3-DAG-005 | Ordering function | TST-230 | Iterative algorithm, no unbounded recursion | Robustness |
| M4D3-DAG-006 | Ordering function | TST-231 | Deterministic across 10 runs | Correctness |
| M4D3-DAG-007 | Activation service | TST-232 | Cycle rejected, questions named | Security |
| M4D3-DAG-008 | Activation service | TST-233 | Unknown dependency rejected | Data integrity |
| M4D3-DAG-009 | Activation service | TST-234 | Cross-version dependency rejected | Data integrity |
| M4D3-DAG-010 | Recalculation | TST-235 | Runtime cycle fails closed | Robustness |
| M4D3-SRC-001 | Source resolver | TST-236 | Single active release resolved | Correctness |
| M4D3-SRC-002 | Source resolver | TST-237 | No active release fails closed | Data integrity |
| M4D3-SRC-003 | Source resolver | TST-238 | Release UUID never client-supplied | Security |
| M4D3-SRC-004 | Source resolver | TST-239 | Every argument resolved | Correctness |
| M4D3-SRC-005 | Source resolver | TST-240 | Unresolvable input → `DATA_REQUIRED` | Robustness |
| M4D3-SRC-006 | Governance | TST-241 | Gap escalated, not assumed | Regulatory |
| M4D3-SRC-007 | Source resolver | TST-242 | Tenant filter on all snapshot access | Security |
| M4D3-SRC-008 | Source resolver | TST-243 | No match handled without raising | Robustness |
| M4D3-SRC-009 | Source resolver | TST-244 | Existing selection logic reused | Correctness |
| M4D3-SRC-010 | Translation | TST-245 | Superseded → regulatory review | Regulatory |
| M4D3-SRC-011 | Source resolver | TST-246 | Snapshot frozen after draft | Regulatory |
| M4D3-SRC-012 | Deployment | TST-247 | Release change does not recalculate | Regulatory |
| M4D3-SRC-013 | Static check | TST-248 | No `fda_data` writes | Architecture |
| M4D3-SRC-014 | Review assertion | TST-322 | Non-nullability recorded; no availability hedge | Correctness |
| M4D3-INP-001 | Review assertion | TST-360 | Six signatures recorded verbatim | Correctness |
| M4D3-INP-002 | Import-time self-check | TST-361 | Entry missing a kwarg resolver raises at import | Data integrity |
| M4D3-INP-003 | Resolver form A | TST-362 | Question response resolved; N/A, review-required, missing, invalid fail closed | Regulatory |
| M4D3-INP-004 | Resolver form B | TST-363 | Formulation field resolved; tenant scoped; missing fails closed | Data integrity |
| M4D3-INP-005 | Resolver form C | TST-364 | Delegates to Part 14.1; logic not duplicated | Correctness |
| M4D3-INP-006 | Resolver form D | TST-365 | Snapshot fields resolved; no live IID lookup | Regulatory |
| M4D3-INP-007 | Resolver form E | TST-366 | Exactly one complete outcome required | Data integrity |
| M4D3-INP-008 | Resolver form F | TST-367 | Constants registry-authored only | Security |
| M4D3-INP-009 | Dependency derivation | TST-368 | Only form E creates an edge | Correctness |
| M4D3-MAP-001 | Registry entry | TST-369 | percentage_w_w kwargs mapped | Correctness |
| M4D3-MAP-002 | Registry entry | TST-370 | daily_exposure kwargs mapped | Correctness |
| M4D3-MAP-003 | Registry entry | TST-371 | percentage_of_potency kwargs mapped | Correctness |
| M4D3-MAP-004 | Registry entry | TST-372 | difference_from_potency kwargs mapped | Correctness |
| M4D3-MAP-005 | Registry entry | TST-373 | percentage_of_mde kwargs mapped | Correctness |
| M4D3-MAP-006 | Registry entry | TST-374 | difference_from_mde kwargs mapped | Correctness |
| M4D3-MAP-007 | Outcome writer | TST-375 | daily_exposure stored unit set to gram/day | Reproducibility |
| M4D3-MAP-008 | Registry entry | TST-376 | Verbatim kwarg and field names | Correctness |
| M4D3-UNC-001 | Input pipeline | TST-377 | Conversion owned by the pipeline only | Architecture |
| M4D3-UNC-002 | Input pipeline | TST-378 | Existing service reused; no second table | Architecture |
| M4D3-UNC-003 | Registry entry | TST-379 | Full-word unit vocabulary only | Data integrity |
| M4D3-UNC-004 | Registry entry | TST-380 | Source and target units explicit | Data integrity |
| M4D3-UNC-005 | Input pipeline | TST-381 | Decimal only; no float | Data integrity |
| M4D3-UNC-006 | Input pipeline | TST-382 | Canonical target unit per kwarg | Correctness |
| M4D3-UNC-007 | Input pipeline | TST-383 | Failed conversion blocks invocation | Data integrity |
| M4D3-UNC-008 | Input pipeline | TST-384 | Conversion failure mapping; sole UNIT_MISMATCH source | Regulatory |
| M4D3-UNC-009 | Input pipeline | TST-385 | Density required fails closed | Regulatory |
| M4D3-UNC-010 | Request serializers | TST-386 | No client conversion factor | Security |
| M4D3-UNC-011 | Input pipeline | TST-387 | Conversion recorded in provenance | Reproducibility |
| M4D3-INP-010 | Input pipeline | TST-388 | Single pipeline; no ad hoc resolver | Architecture |
| M4D3-INP-011 | Input pipeline | TST-389 | All eleven ordered steps performed | Correctness |
| M4D3-INP-012 | Input pipeline | TST-390 | Function never invoked with partial kwargs | Robustness |
| M4D3-INP-013 | Input pipeline | TST-391 | Pipeline performs no write | Architecture |
| M4D3-INP-014 | Outcome writer | TST-392 | Inputs and provenance persisted | Reproducibility |
| M4D3-DEP-001 | Registry validation | TST-393 | Dependencies derived from form E | Correctness |
| M4D3-DEP-002 | Registry validation | TST-394 | Non-E forms create no edge | Correctness |
| M4D3-DEP-003 | Registry entry | TST-395 | Documented graph matches registry | Correctness |
| M4D3-DEP-004 | Review assertion | TST-396 | Depth 2, nodes 3; limits retained as headroom | Correctness |
| M4D3-DEP-005 | Activation service | TST-397 | Validation at activation plus runtime defence | Security |
| M4D3-DEP-006 | Activation service | TST-398 | Bad form E target rejected | Data integrity |
| M4D3-SNO-001 | Population service | TST-399 | Six-step snapshot order observed | Regulatory |
| M4D3-SNO-002 | Population service | TST-400 | No live IID read after snapshot | Regulatory |
| M4D3-SNO-003 | Population service | TST-401 | Snapshot and outcomes share the transaction | Data integrity |
| M4D3-SNO-004 | Population service | TST-402 | Snapshot calculations follow topological order | Correctness |
| M4D3-IFV-001 | Input pipeline | TST-403 | Sixteen failure codes defined | Data integrity |
| M4D3-IFV-002 | Outcome writer | TST-404 | Failure codes never reach reason_code | Data integrity |
| M4D3-IFV-003 | Input pipeline | TST-405 | Missing-data failures map to data_required | Regulatory |
| M4D3-IFV-004 | Input pipeline | TST-406 | Review-required maps to data_required | Regulatory |
| M4D3-IFV-005 | Input pipeline | TST-407 | Invalid conditions map to error | Regulatory |
| M4D3-IFV-006 | Input pipeline | TST-408 | No exception text stored or exposed | Security |
| M4D3-MDU-022 | Review assertion | TST-409 | Monotonicity rationale recorded | Regulatory |
| M4D3-MDU-023 | Review assertion | TST-410 | Non-consumers identified | Correctness |
| M4D3-MDU-024 | Registry governance | TST-411 | New consumer requires monotonicity review | Regulatory |
| M4D3-MDU-001 | Dosage resolver | TST-323 | Both sources considered; scalar-only rule absent | Regulatory |
| M4D3-MDU-002 | Dosage resolver | TST-324 | Version candidate only when non-null and positive | Data integrity |
| M4D3-MDU-003 | Dosage resolver | TST-325 | All related regimens are candidates; no invented lifecycle filter | Correctness |
| M4D3-MDU-004 | Dosage resolver | TST-326 | Cross-tenant regimen excluded, no provenance leakage | Security |
| M4D3-MDU-005 | Dosage resolver | TST-327 | Invalid values excluded and recorded | Data integrity |
| M4D3-MDU-006 | Request serializers | TST-328 | No client-supplied dosing value | Security |
| M4D3-MDU-007 | Dosage resolver | TST-329 | None/one/highest-of-many selection | Regulatory |
| M4D3-MDU-008 | Dosage resolver | TST-330 | Deterministic public-UUID tie-breaker | Correctness |
| M4D3-MDU-009 | Dosage resolver | TST-331 | Population is provenance, never a filter | Regulatory |
| M4D3-MDU-010 | Dosage resolver | TST-332 | All four reconciliation cases correct | Regulatory |
| M4D3-MDU-011 | Dosage resolver | TST-333 | Disagreement flag recorded | Regulatory |
| M4D3-MDU-012 | Dosage resolver | TST-334 | Never lower, averaged, or creation-ordered | Regulatory |
| M4D3-MDU-013 | Dosage resolver | TST-335 | All five fail-closed conditions honored | Data integrity |
| M4D3-MDU-014 | Dosage resolver | TST-336 | Engine mapping preserved to `data_required` | Compatibility |
| M4D3-MDU-015 | Dosage resolver | TST-337 | Detail code in provenance, not `reason_code` | Data integrity |
| M4D3-MDU-016 | Dosage resolver | TST-338 | Full provenance content recorded | Reproducibility |
| M4D3-MDU-017 | Dosage resolver | TST-339 | Resolver version present | Reproducibility |
| M4D3-MDU-018 | Dosage resolver | TST-340 | No internal primary keys in provenance | Security |
| M4D3-MDU-019 | Outcome serializer | TST-341 | Client sees sanitized summary only | Security |
| M4D3-MDU-020 | Dosage resolver | TST-342 | Repeat runs identical value and ordering | Correctness |
| M4D3-MDU-021 | Source resolver | TST-343 | Later regimen change leaves historical result intact | Regulatory |
| M4D3-RTE-001 | Review assertion | TST-344 | Blank-capable fields recorded | Correctness |
| M4D3-RTE-002 | Source resolver | TST-345 | Blank treated as missing | Data integrity |
| M4D3-RTE-003 | Source resolver | TST-346 | Blank never passed as resolved | Data integrity |
| M4D3-RTE-004 | Source resolver | TST-347 | `None` lookup is not success | Robustness |
| M4D3-RTE-005 | Source resolver | TST-348 | No fallback term substituted | Regulatory |
| M4D3-RTE-006 | Source resolver | TST-349 | Blank, unknown and inactive term outcomes | Regulatory |
| M4D3-RSN-006 | Translation module | TST-350 | Detail vocabulary contains the six codes | Data integrity |
| M4D3-RSN-007 | Outcome writer | TST-351 | Detail codes never reach `reason_code` | Data integrity |
| M4D3-RSN-008 | Translation module | TST-352 | Detail codes formatted and server-only | Security |
| M4D3-RFV-001 | Activation service | TST-353 | Pattern enforced at activation | Data integrity |
| M4D3-RFV-002 | Activation service | TST-354 | 100-char accepted, 101-char rejected | Data integrity |
| M4D3-RFV-003 | Activation service | TST-355 | Colon rejected | Security |
| M4D3-RFV-004 | Activation service | TST-356 | Lowercase and whitespace rejected | Data integrity |
| M4D3-RFV-005 | Activation service | TST-357 | Reserved prefix rejected | Security |
| M4D3-RFV-006 | Applicability service | TST-358 | Composed marker ≤ 200 | Data integrity |
| M4D3-RFV-007 | Request serializers | TST-359 | Client cannot supply code or marker | Security |
| M4D3-SNP-001 | Import-linter | TST-249 | One-way import preserved | Architecture |
| M4D3-SNP-002 | Static check | TST-250 | No direct cross-app model write | Architecture |
| M4D3-SNP-003 | Snapshot service | TST-251 | Creation via approved service | Architecture |
| M4D3-SNP-004 | Snapshot service | TST-252 | Service added if absent | Architecture |
| M4D3-SNP-005 | Snapshot service | TST-253 | `created_by` is triggering actor | Regulatory |
| M4D3-SNP-006 | Outcome writer | TST-254 | Snapshot UUID recorded | Reproducibility |
| M4D3-SNP-007 | Review assertion | TST-255 | Scope exclusion clarified | Correctness |
| M4D3-POP-001 | Population service | TST-256 | Exact ordered pass in one transaction | Data integrity |
| M4D3-POP-002 | Population service | TST-257 | FDA population precedes calculation | Correctness |
| M4D3-POP-003 | Population service | TST-258 | N/A and review-required block both | Regulatory |
| M4D3-POP-004 | Population service | TST-259 | Applicable permits progression | Correctness |
| M4D3-POP-005 | Population service | TST-260 | Mid-pass exception rolls back fully | Data integrity |
| M4D3-POP-006 | Population service | TST-261 | Non-editable execution rejected | Data integrity |
| M4D3-POP-007 | Population service | TST-262 | Idempotent re-run | Regulatory |
| M4D3-POP-008 | Population service | TST-263 | `None` resolver leaves null, no error | Robustness |
| M4D3-RCL-001 | New service | TST-264 | Dependency change triggers cascade | Correctness |
| M4D3-RCL-002 | New service | TST-265 | Topological order respected | Correctness |
| M4D3-RCL-003 | New service | TST-266 | In-place update with `full_clean()` | Data integrity |
| M4D3-RCL-004 | New service | TST-267 | Unchanged result: no audit, no version change | Regulatory |
| M4D3-RCL-005 | New service | TST-268 | Terminal never auto-recalculated | Regulatory |
| M4D3-TXN-001 | New service | TST-269 | Lock order observed | Data integrity |
| M4D3-TXN-002 | New service | TST-270 | Single atomic block | Data integrity |
| M4D3-TXN-003 | New service | TST-271 | Version checked against locked row | Data integrity |
| M4D3-TXN-004 | New service | TST-272 | Full rollback on failure | Data integrity |
| M4D3-TXN-005 | Audit dispatch | TST-273 | No audit after rollback | Regulatory |
| M4D3-TXN-006 | New service | TST-274 | Concurrent updates serialize | Data integrity |
| M4D3-SER-001 | Outcome serializer | TST-275 | Exactly the approved fields | Security |
| M4D3-SER-002 | Outcome serializer | TST-276 | Sanitized summary only | Security |
| M4D3-SER-003 | Outcome serializer | TST-277 | Raw dicts never exposed | Security |
| M4D3-SER-004 | Outcome serializer | TST-278 | No internal identifiers leaked | Security |
| M4D3-SER-005 | Outcome serializer | TST-279 | No write methods defined | Security |
| M4D3-SER-006 | Response serializer | TST-280 | Derived field present | Correctness |
| M4D3-SER-007 | Response serializer | TST-281 | Marker not exposed verbatim | Security |
| M4D3-SER-008 | OpenAPI schema | TST-282 | Four stored values only | Correctness |
| M4D3-SER-009 | Response list view | TST-283 | Pagination unchanged | Compatibility |
| M4D3-AUD-001 | Audit dispatch | TST-284 | All events post-commit | Regulatory |
| M4D3-AUD-002 | Audit dispatch | TST-285 | All eight events defined | Regulatory |
| M4D3-AUD-003 | Audit payloads | TST-286 | Required metadata present | Regulatory |
| M4D3-AUD-004 | Audit payloads | TST-287 | Prohibited content absent | Security |
| M4D3-AUD-005 | Population service | TST-288 | System population distinguishable | Regulatory |
| M4D3-AUD-006 | Recalculation | TST-289 | No event when unchanged | Regulatory |
| M4D3-AUD-007 | Audit dispatch | TST-290 | Failure audit distinct from success | Regulatory |
| M4D3-API-001 | URL configuration | TST-291 | PATCH/PUT → 404/405 | Security |
| M4D3-API-002 | Response views | TST-292 | Nested outcome and derived field returned | Correctness |
| M4D3-API-003 | Response views | TST-293 | Cross-tenant → 404 | Security |
| M4D3-API-004 | Response views | TST-294 | Unauthorized in-tenant → 403 | Security |
| M4D3-API-005 | Response views | TST-295 | Immutable execution → 400 | Data integrity |
| M4D3-FE-001 | Execution detail UI | TST-296 | Provenance labels rendered | Usability |
| M4D3-FE-002 | Execution detail UI | TST-297 | Value or reason, never a fabricated pass | Regulatory |
| M4D3-FE-003 | Execution detail UI | TST-298 | Review-required state rendered | Regulatory |
| M4D3-FE-004 | Submission UI | TST-299 | Blocked submission surfaced | Usability |
| M4D3-FE-005 | API client | TST-300 | Sends version; handles 409 | Data integrity |
| M4D3-FE-006 | CI lint | TST-301 | No formula names in frontend | Security |
| M4D3-FE-007 | Execution detail UI | TST-302 | Server reload, no local computation | Regulatory |
| M4D3-FE-008 | `execution-mappers.ts` | TST-303 | Mapping centralized | Maintainability |
| M4D3-FE-009 | Accessibility tests | TST-304 | New states accessible | Accessibility |
| M4D3-SEC-001 | Static check | TST-305 | No dynamic evaluation anywhere | Security |
| M4D3-SEC-002 | All queries | TST-306 | Tenant filter present | Security |
| M4D3-SEC-003 | Translation module | TST-307 | Unknown never yields complete | Security |
| M4D3-SEC-004 | Request serializers | TST-308 | Underscore keys rejected | Security |
| M4D3-SEC-005 | Import-linter | TST-309 | Contracts pass | Architecture |
| M4D3-PRV-001 | Outcome writer | TST-310 | Chain complete, no new column | Reproducibility |
| M4D3-PRV-002 | Outcome writer | TST-311 | Binding version in provenance | Reproducibility |
| M4D3-PRV-003 | Serializer | TST-312 | Missing version warns, does not raise | Robustness |
| M4D3-PRV-004 | Registry governance | TST-313 | Versions governed independently | Reproducibility |
| M4D3-MIG-001 | Repository check | TST-314 | No migration, field or backfill | Compatibility |
| M4D3-MIG-002 | Compatibility test | TST-315 | Existing rows valid | Compatibility |
| M4D3-MIG-003 | Deployment test | TST-316 | Historical executions unchanged | Regulatory |
| M4D3-MIG-004 | Review assertion | TST-317 | Breaking change stated | Compatibility |
| M4D3-MIG-005 | Deployment | TST-318 | Old client gets structured error | Compatibility |
| M4D3-MIG-006 | Release notes | TST-319 | Contract change recorded | Compatibility |
| M4D3-MIG-007 | Rollback plan | TST-320 | Coordinated rollback, no transformation | Compatibility |
| M4D3-MIG-008 | Population service | TST-321 | Legacy identifier fails closed | Security |

Matrix reconciliation is reported in the test strategy, §11.

---

## Part 22 — Implementation sequence

Implementation remains unauthorized. When authorized, the order shall be:

1. `calculation_registry.py` — registry entries, identifier→`calculation_name` mapping,
   binding versions, `CALCULATION_MAX_DEPENDENCY_DEPTH`, `CALCULATION_MAX_CASCADE_NODES`,
   import-time self-check including full kwarg coverage (M4D3-INP-002).
1a. **Resolver vocabulary** — the six allow-listed forms of Part 3A.2 and the complete
   kwarg mappings of Part 3A.2.1.
1b. **Unit-conversion layer** — governed wrapper over
   `iid_assessment/unit_conversion.py`, canonical target units, and the failure mapping
   of M4D3-UNC-008.
1c. **Unified input-resolution service** — `resolve_calculation_inputs()` and
   `ALLOWED_INPUT_FAILURE_CODES`, absorbing maximum-daily-units, snapshot and
   prior-outcome resolution.
2. **`services.py` correction** — `create_execution()` resolves the registry entry and
   writes `entry["calculation_name"]`; unknown or invalid entries abort atomically.
3. `calculation_translation.py` — translation function, `ALLOWED_REASON_CODES`,
   `ALLOWED_RESOLVER_DETAIL_CODES`, `INVALID_GENERATED_AT` path.
4. `update_checklist_response()` governed service in `services.py`, and reduction of
   `ChecklistResponseUpdateView.patch()` in `views.py` to a thin adapter.
5. `expected_version` on the governed request serializer, with the 400 and 409 contracts.
6. Governed applicability service and persisted `REVIEW_REQUIRED:` marker, including
   `evaluate_applicability()` in `applicability.py`.
7. **`services.py` completeness-gate extension** in `_check_execution_completeness()`.
8. **Submission gate** for unresolved `REVIEW_REQUIRED` in `transition_execution()`.
9. Population service, calculation translation wiring and outcome updates.
10. FDA/IID and formulation source resolvers in `answer_sources.py`, including the
    Part 14.1 maximum-dosage-units resolver and Part 14.2 controlled-term handling.
11. Governed `iid_assessment` AssessmentSnapshot service.
12. Serializers — nested read-only outcome, `provenance_summary`,
    `applicability_outcome`.
13. Frontend — `execution-mappers.ts`, display states, `expected_version`, 409 handling,
    CI lint rule.
14. Backend targeted and full test suites per the test strategy.
15. Frontend unit and Playwright test suites.
16. Docker integration smoke extension.
17. Independent adversarial implementation review before merge.

Steps 2, 4, 7 and 8 modify existing 4D-2 runtime code and shall not be omitted.

---

## Part 23 — Gate status

**Ready for adversarial specification review:** YES
**Ready to write implementation code:** NO — requires a passing specification review and separate explicit authorization
**Ready to create a PR:** NO
**Migration required:** NO
**New database field required:** NO
**Breaking API contract change:** YES — `expected_version` (Part 5, M4D3-MIG-004)
