# IID Calculation Rules

`iid_assessment/calculations.py`. Six pure, versioned, Decimal-only
formulas. Every function returns a `CalculationResult` — never a bare
number — carrying `value`, `unit`, `formula_identifier`, `formula_version`
(currently `"1.0.0"`), `inputs`, `input_provenance`, `rounding_rule`
(`"none (Decimal, unrounded)"`), `status`, `reason_code`, `generated_at`.
A blocked calculation is a documented status, never a silently-omitted
value or a `0` standing in for "unknown."

## The six formulas

| # | Formula ID | Definition |
|---|---|---|
| A | `percentage_w_w` | `quantity_per_unit_grams / total_dosage_unit_weight_grams * 100` |
| B | `daily_exposure` | `quantity_per_dosage_unit * maximum_dosage_units_per_day` |
| C | `percentage_of_iid_potency` | `converted_proposed_quantity / selected_iid_potency_amount * 100` |
| D | `difference_from_iid_potency` | `selected_iid_potency_amount - converted_proposed_quantity` |
| E | `percentage_of_iid_mde` | `converted_proposed_daily_exposure / selected_iid_mde * 100` |
| F | `difference_from_iid_mde` | `selected_iid_mde - converted_proposed_daily_exposure` |

## When a calculation is blocked instead of run

Per formula, any of these produces a `_blocked(...)` result instead of a
value:

- A required input is `None`/unparseable → `PROPOSED_VALUE_MISSING` (A–F,
  the proposed-side input) or `MAX_DAILY_UNITS_MISSING` (B specifically).
- The selected IID value is missing → `IID_VALUE_MISSING` (C, E; D and F
  treat a missing reference value the same way).
- The selected IID value is `<= 0` → `IID_VALUE_INVALID` (C, E).
- The denominator (`total_dosage_unit_weight_grams` in A) is `0` →
  `BASIS_UNCLEAR`.

`CalculationStatus` also defines `ROUTE_MISMATCH`, `DOSAGE_FORM_MISMATCH`,
`INGREDIENT_UNRESOLVED`, `UNIT_MISMATCH` (unit conversion failed),
`REGULATORY_REVIEW_REQUIRED` (release not active / record superseded) —
these are set by the orchestrating service (`assess.py`), not by the pure
formula functions themselves, since they depend on the matching result, not
just the numeric inputs.

## The full precondition list (do-not-calculate)

A calculation never runs — the orchestrator (`iid_assessment/assess.py`)
stops before it — when any of:

- route mismatch, dosage-form mismatch, or ingredient unresolved,
- unit conversion failed (`unit_conversion.ConversionResult.ok is False`),
- the selected IID value is missing or `<= 0`,
- the proposed value or maximum daily units is missing,
- the calculation basis is unclear (e.g. zero total weight),
- the source release is not approved/active,
- the selected FDA record is superseded without an explicit historical-run
  context.

## Provenance and immutability

Every `CalculationResult` records its exact `inputs` (stringified, never
re-derived later) and `formula_version`. `AssessmentSnapshot`
(`iid_assessment/models.py`) freezes the full calculation output — value,
unit, provenance, decision — by copying it, not by referencing a live FK, so
a later FDA data refresh or formulation edit can never retroactively change
a completed assessment. See `iid_assessment/tests/test_calculations.py` for
per-formula coverage of every status above.
