# Calculator Gap Report

> **Scope:** SOW 2.2 (IIG checklist calculation engine) and SOW 2.3 (HTML
> calculators — dissolution, impurity, stability/shelf-life).
> **Type:** inspection record. No code, migration, UI, formula or
> approval-status change accompanies this document.
> **Inspected at:** `regx-main` `de15742`; **re-verified at `fff12fd`** after
> PRs #53–#57 landed. Every claim below was re-checked against the new base
> rather than assumed to survive it: the calculation surface is untouched by
> what landed (empty diff across `iid_assessment/` and the calculation
> modules and tests), the registry still holds exactly six bindings, the test
> count is still 279, `SCOPE-OUT-18` is unchanged, the gate still reads 0 of
> 20, Items 13 and 14 are still PENDING, and the SOW 2.3 searches return the
> same counts with no calculator added.
> **Companions:** [SOW_SECTION_2_STATUS.md](SOW_SECTION_2_STATUS.md),
> [IID_CALCULATION_RULES.md](IID_CALCULATION_RULES.md),
> [MILESTONE_4D_3_IMPLEMENTATION_SPEC.md](MILESTONE_4D_3_IMPLEMENTATION_SPEC.md),
> [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md)

## 1. Why this document exists

"Calculators" names two unrelated things in the SOW, and the difference decides
what may be built.

SOW 2.2's calculation engine **exists, is specified and is tested**. What it
lacks is regulatory approval of which calculation applies to which question —
a sign-off activity, not an engineering one.

SOW 2.3's calculators **do not exist and cannot currently be written**, because
no approved formula specification for them exists anywhere in this repository or
in the legacy codebase. Writing them would mean choosing regulatory thresholds,
which is not an engineering decision to make.

Conflating the two would make the second look like remaining work on the first.
It is not. They are blocked on different people.

## 2. SOW 2.2 — IIG checklist calculation engine

### 2.1 Status

| Dimension | State |
|---|---|
| Engineering implementation | **Complete** |
| Approved formulas | **Exactly six** |
| Implementation properties | Pure, `Decimal`-only, versioned, fail-closed |
| Test coverage | **279 tests** |
| Regulatory / content approval | **NOT complete** |
| Approval Register Item 13 (`SYSTEM_CALCULATED` bindings) | **PENDING** |
| Approval Register Item 14 (dependencies / ordering) | **PENDING** (blocked on 12–13) |
| Validated production use | **Not claimed** |

### 2.2 The six approved formulas

Enumerated from the live registry
(`iig_checklist/calculation_registry.py:218`, `CALCULATION_BINDING_REGISTRY`),
not transcribed from a document:

| Identifier | Function | Formula version | Binding version |
|---|---|---|---|
| `percentage_w_w` | `calculate_percentage_w_w` | 1.0.0 | 1.0.0 |
| `daily_exposure` | `calculate_daily_exposure` | 1.0.0 | 1.0.0 |
| `percentage_of_iid_potency` | `calculate_percentage_of_potency` | 1.0.0 | 1.0.0 |
| `difference_from_iid_potency` | `calculate_difference_from_potency` | 1.0.0 | 1.0.0 |
| `percentage_of_iid_mde` | `calculate_percentage_of_mde` | 1.0.0 | 1.0.0 |
| `difference_from_iid_mde` | `calculate_difference_from_mde` | 1.0.0 | 1.0.0 |

Definitions are in [IID_CALCULATION_RULES.md](IID_CALCULATION_RULES.md);
implementation is `iid_assessment/calculations.py`.

### 2.3 Implementation properties

- **Decimal only.** No float arithmetic in the formulas or in the supporting
  `iid_assessment/unit_conversion.py`.
- **Versioned.** Every result carries `formula_identifier` and
  `formula_version`; the registry carries a separate `binding_version`.
- **Fail-closed.** A calculation that cannot run returns a documented status
  and reason code — `PROPOSED_VALUE_MISSING`, `IID_VALUE_MISSING`,
  `IID_VALUE_INVALID`, `BASIS_UNCLEAR`, `UNIT_MISMATCH`,
  `REGULATORY_REVIEW_REQUIRED` and the rest — never a silently omitted value
  and never a `0` standing in for "unknown".
- **Provenance-bound.** Results record their exact inputs, and
  `AssessmentSnapshot` freezes the output by copying it rather than referencing
  live rows, so a later FDA refresh or formulation edit cannot retroactively
  change a completed assessment.

### 2.4 Validation evidence

279 tests, counted by collection at `de15742`:

| Tests | File |
|---|---|
| 14 | `iid_assessment/tests/test_calculations.py` |
| 140 | `iig_checklist/tests/test_4d3_calculation_execution.py` |
| 110 | `iig_checklist/tests/test_4d3_calculation_inputs.py` |
| 15 | `iig_checklist/tests/test_4d3_calculation_projection.py` |
| **279** | **total** |

They assert computed values and terminal status (for example
`result.value == Decimal("25")` with `status == CalculationStatus.COMPLETE`),
and every blocked status and reason code above.

**This is engineering test evidence. It is not validation evidence in the
regulated sense, and no validated or production-ready status is claimed for the
calculation engine by this document or by the codebase.**

### 2.5 What is complete and what is not

**Complete:** the engine, its six formulas, the unit-conversion layer, the
governed maximum-daily-units selector (M4D3-MDU-001..024 — a selector feeding
an input, not a seventh formula), the dependency graph, and their tests.

**Not complete:** the regulatory decision recorded as Approval Register
**Item 13** — *which calculation applies to which question, and the regulatory
reason* — carrying interpretation risk **HIGH**, described there as *"the wrong
calculation produces a wrong regulated number."* **Item 14** (dependencies and
ordering) is derived from Item 13 and is therefore blocked behind it.

The wider gate is open: the register records **0 of 20 approved**, and states
that the count *"changes only when a named regulatory authority supplies a real
approval. It is not advanced by document completeness, engineering readiness or
milestone progress."*

### 2.6 One provenance caveat

[IID_CALCULATION_RULES.md](IID_CALCULATION_RULES.md) accurately describes what
`calculations.py` does — formula, version, blocked-status semantics — but it
carries **no citation to an external regulatory guidance document or a
client-approved formula sheet**. The six formulas are governed by an approved
*engineering* specification
([MILESTONE_4D_3_IMPLEMENTATION_SPEC.md](MILESTONE_4D_3_IMPLEMENTATION_SPEC.md)),
not by a traceable regulatory source.

That is not a defect, and nothing here suggests the formulas are wrong. It is
recorded because "specified" and "traceable to an approved regulatory source"
are different claims, and only the first is currently supported.

### 2.7 One stale docstring, deliberately not fixed here

`CalculationOutcome` (`backend/iig_checklist/models.py:971`) still reads:

```python
"""Calculation result placeholder created at execution creation.
Populated with actual values in 4D-3."""
```

4D-3 has been delivered, so the second sentence describes work that is done. The
first sentence remains accurate — a placeholder row *is* created at execution
creation and populated afterwards — so nothing behaves wrongly; the docstring
simply reads as though the engine were still pending, and it was the evidence
`SOW_SECTION_2_STATUS.md` quoted for the "placeholder" claim this report
corrects.

**It is not changed here.** P9 is docs-only and touching it would be a code
change. Recorded so the next phase that edits that module can correct it.

## 3. SOW 2.3 — HTML calculators

### 3.1 Status

| Calculator | Implementation | Approved formula specification |
|---|---|---|
| Dissolution | **None found** | **None found** |
| Impurity | **None found** | **None found** |
| Stability / shelf-life | **None found** | **None found** |

**Implementation status: BLOCKED ON CLIENT INPUT.**

### 3.2 What the search covered

At `de15742`, across `backend/`, `frontend/`, `company_site/` and `docs/`:

- `impurity` — 2 files, both legacy HTML templates, prose only.
- `dissolution` — 7 files: test fixtures and legacy templates; none computes
  anything.
- `shelf_life` — 0 occurrences.
- `ICH Q3A` / `ICH Q3B` / `ICH Q1A` / identification or qualification threshold
  logic — **0 occurrences in any code**.
- `docs/` for dissolution, impurity, shelf-life or the ICH threshold families —
  **one hit**, in `SOW_SECTION_2_STATUS.md`, recording their absence.

### 3.3 No legacy implementation exists either

`git ls-tree -r origin/main` returns **no** calculator, dissolution, impurity or
stability implementation files. The 59 `company_site/templates/RATools/*.html`
files are **document generators** — ANDA reports, IIG templates, validation
protocols, white papers — not calculators.

`SizeShapeScore.html` was checked specifically because its name suggests
scoring. It does not compute: "score" there refers to the physical score line
on a tablet, and the file is a template.

So SOW 2.3 is not a port. There is nothing to port.

### 3.4 Formulas must not be derived from guidance

Regulatory guidance is not a specification. Reading a threshold out of ICH Q3A,
Q3B or Q1A and encoding it would be **engineering choosing a regulatory
parameter**, which is precisely the decision this project has held away from
engineering everywhere else.

No formula for SOW 2.3 may be derived, inferred, reconstructed from a legacy
spreadsheet, or inverted from example outputs. It must be supplied and owned.

### 3.5 Required input before SOW 2.3 engineering may begin

Per calculator, all of the following. An item left blank blocks that calculator;
partial input does not authorise a partial build.

| # | Required | Notes |
|---|---|---|
| 1 | Calculator name | The name it will carry in the product |
| 2 | Exact formula | Written unambiguously, not by example |
| 3 | Variable definitions | Every symbol, and where its value comes from |
| 4 | Units | Per variable and for the result, using canonical unit names |
| 5 | Rounding rules | Precision, direction, and at which step it applies |
| 6 | Edge and error behaviour | Missing input, zero denominator, out-of-range, unit mismatch — and what the user is shown |
| 7 | Acceptance / interpretation rules | What the result *means*; any pass/fail or threshold reading |
| 8 | Source document | The document the formula comes from |
| 9 | Source version and date | Version identifier and publication date |
| 10 | Regulatory / client owner | The named person or role who owns the content |
| 11 | Approval / sign-off evidence | The approval itself, not a statement that one exists |

Items 6 and 7 are not optional detail. The existing engine's fail-closed
behaviour is a specified property, and a new calculator without defined edge
behaviour would either guess or emit a misleading number.

### 3.6 SOW 2.3 must not be built inside the existing registry

[MILESTONE_4D_3_IMPLEMENTATION_SPEC.md:159](MILESTONE_4D_3_IMPLEMENTATION_SPEC.md)
states:

> `| SCOPE-OUT-18 | New calculation formulas beyond the six approved functions | Never in 4D |`

[MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md) Item 13
restates it:

> **A seventh calculation cannot be added to satisfy content** (4D-3
> `SCOPE-OUT-18`: "Never in 4D"). A requirement needing one is separate approved
> engineering scope.

The registry is capped at six by approved scope. A dissolution, impurity or
stability calculator added to `CALCULATION_BINDING_REGISTRY` would breach that
boundary regardless of how good the formula was.

**SOW 2.3 therefore requires separately approved engineering scope in addition
to the formula specification in §3.5.** Two approvals, not one — and neither
substitutes for the other.

## 4. Summary

| SOW | Blocked on | Blocked on whom |
|---|---|---|
| 2.2 | Approval Register Items 13 and 14 | A named regulatory authority |
| 2.3 | Formula specification (§3.5) **and** separately approved engineering scope (§3.6) | Client / regulatory, then engineering scope approval |

Neither is blocked on engineering capacity. Nothing in this report authorises
building either.
