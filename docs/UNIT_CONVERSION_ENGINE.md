# Unit Conversion Engine

`iid_assessment/unit_conversion.py`. Decimal only, no float arithmetic
anywhere. Every conversion either succeeds with an explicit result or fails
closed with one of a fixed set of reason codes — nothing is ever guessed.

## Unit vocabulary

| Dimension | Units (keyed by canonical `ControlledUnit.code`, lowercase) |
|---|---|
| mass | `microgram`, `milligram`, `gram`, `kilogram` |
| volume | `microlitre`, `millilitre`, `litre` |
| count | `tablet`, `capsule`, `unit`, `actuation`, `dose` |

Lookup keys are the canonical `code`, not the display `symbol` — callers
(e.g. `iid_assessment.matching.MatchCandidate`) must pass `.code` (e.g.
`"milligram"`), never `.symbol` (e.g. `"MG"`). `dimension_of(unit)` returns
`None` for anything not in this table, and every conversion path treats that
as `UNIT_UNKNOWN`.

## Entry point: `convert(value, from_unit, to_unit, *, density_g_per_ml=None)`

1. `from_unit`/`to_unit` missing → `UNIT_UNKNOWN`.
2. Either unit unrecognized → `UNIT_UNKNOWN`.
3. Same dimension:
   - `count`: exact unit-string match required (`"tablet"` → `"tablet"`
     only) — no cross-count-unit conversion (a tablet is never converted to
     a capsule). Mismatched count units → `CONVERSION_NOT_SUPPORTED`.
   - `mass`/`volume`: delegates to `convert_mass_or_volume`.
4. Cross dimension, exactly `{mass, volume}`: requires `density_g_per_ml`;
   missing → `DENSITY_REQUIRED`. Otherwise delegates to
   `convert_with_density`.
5. Any other cross-dimension pair (e.g. mass↔count) → `DIMENSION_MISMATCH`.

## Reason codes (`ConversionReasonCode`)

`UNIT_UNKNOWN`, `DIMENSION_MISMATCH`, `BASIS_REQUIRED`, `DENSITY_REQUIRED`,
`CONVERSION_NOT_SUPPORTED`, `VALUE_MISSING`, `INVALID_VALUE`. A
`ConversionResult` is always returned — `ok=True` with `converted_value`
set, or `ok=False` with `reason_code` set and `converted_value=None`. There
is no third state.

## Mass↔volume conversion (`convert_with_density`)

Requires an explicitly supplied `density_g_per_ml` (grams per millilitre).
No default density is ever assumed, even for water-like or common
excipients. Value normalizes to grams/millilitres internally, then applies
density; a non-positive density is `INVALID_VALUE`.

## Percentage w/w (`calculate_percentage_w_w` in this module)

Requires both the component and total values to already be mass-dimension
units and the total to be non-zero. A non-mass unit on either side is
`BASIS_REQUIRED` — the function never assumes what basis was intended.

## What this module never does

- Never applies a default or "common" density.
- Never infers a unit from context (e.g. assuming a bare number is
  milligrams).
- Never mixes float and Decimal — every numeric input passes through
  `Decimal(str(value))`; a value that can't convert cleanly is
  `INVALID_VALUE`, not silently coerced.
- Never converts a `count` unit into a different `count` unit (a tablet is
  never treated as fungible with a capsule).

See `iid_assessment/tests/test_unit_conversion.py` (21 tests) for the full
matrix: mass/volume/count conversions, dimension mismatch, missing
basis/density, unsupported conversions, and Decimal precision.
