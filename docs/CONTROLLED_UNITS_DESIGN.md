# Controlled units: minimum design for real IID comparisons

**Date:** 2026-11-06. **Status:** design only; nothing built. **Asked for by:** Pratham's second direction (`docs/decisions/2026-11-07-pratham-direction-2.md` §6).
**Based on:** the unit strings actually present in the July 2026 FDA IID file (`docs/IID_BLOCKER_ANALYSIS.md`). Sizes are **estimates** for one experienced developer.

**Principle:** never force incompatible units together. A comparison is made only between quantities of the **same representation** (same kind, same basis), after an **exact** conversion. Anything else is refused with a reason, never guessed.

## 1. What already exists (no need to rebuild)

- `fda_data.ControlledUnit` (code, symbol, dimension `mass` / `volume` / `count` / `percentage` / `concentration`, `conversion_factor_to_base`, aliases) and `fda_data.UnitMapping` (raw value → controlled unit, proposed / approved, versioned like route and dosage-form mappings).
- `iid_assessment/unit_conversion.py`: Decimal-only, fail-closed conversion; mass↔mass and volume↔volume; mass↔volume only with an explicit approved density; % w/w only from compatible masses with an explicit total.
- `IIDPrecedentRecord.potency_unit_raw` / `potency_unit_normalized` / `mde_unit_raw` / `mde_unit_normalized` and the `potency_unit_missing` calculability status.

**Why it is not enough today:** the `ControlledUnit` table is empty (units "on hold"), and a single unit row cannot express what the IID file states. `mg/5ml` is an amount **per a stated volume**; `%w/v` is a percentage **with a basis**. These need a structured representation, not a longer list of symbols.

## 2. The IID unit strings to support

| Kind | IID strings (records) | Meaning |
|---|---|---|
| **Per dose unit, mass** | `mg` (1,914) | mg of ingredient per dosage unit (tablet, capsule, dose) |
| **Per dose unit, volume** | `ml` (7) | mL of ingredient per dosage unit |
| **Percentage with basis** | `%w/w` (872), `%w/v` (596), `%v/v` (11) | Percentage; the basis is part of the unit |
| **Concentration, mass per volume** | `mg/5ml` (177), `mg/1ml` (125), `mg/15ml` (9), `mg/120ml` (8), `mg/100ml` (4), `mg/2.5ml` (2), `mg/0.1ml`, `mg/0.2ml`, `mg/10ml`, `mg/20ml`, `mg/140ml`, `mg/1000ml` (1 each) | mg per stated volume |
| **Volume per volume** | `ml/5ml` (11), `ml/1ml` (4), `ml/15ml` (2) | mL per stated volume |
| **Maximum daily exposure** | `mg` (4,059, in the MDE column) | mg per day |
| **Refused (no stated basis)** | `mg/mg` (16) | mg per mg **of what**? |
| **No value** | `NA` (850), `ADJ PH` (357) | Not a unit; no numeric limit |

## 3. Minimum model

**A. Seed `ControlledUnit` rows** (data migration, reviewer-approved list): `mg`, `mcg`, `g` (mass); `ml`, `l` (volume); `dose_unit` (count); `day` (time, for per-day). Exact factors only (1 g = 1,000 mg; 1 mL = 0.001 L).

**B. New value type: `QuantityExpression`** (a small, immutable model or a validated JSON field on the record; one per limit):

| Field | Example `mg/5ml` | Example `%w/v` | Example `mg` (potency) | Example MDE |
|---|---|---|---|---|
| `kind` | `concentration` | `percentage` | `per_dose_unit` | `per_day` |
| `numerator_unit` → ControlledUnit | mg | — | mg | mg |
| `denominator_amount` | 5 | — | 1 | 1 |
| `denominator_unit` → ControlledUnit | ml | — | dose_unit | day |
| `percentage_basis` | — | `w/v` | — | — |
| `amount` (Decimal) | as published | as published | as published | as published |
| `normalised_amount` | amount ÷ 5 → **per 1 mL** | unchanged | unchanged | unchanged |

**C. `UnitMapping` gains a target `QuantityExpression` template** (kind, numerator, denominator amount/unit, basis) instead of a single unit. Each raw string (`mg/5ml`) is mapped once, reviewed and approved like routes. Parsing of `<mass>/<number><volume>` proposes the template; **a human approves it**.

**D. On `IIDPrecedentRecord`:** `potency_expression` and `mde_expression` (nullable), filled by the existing re-resolve step from **approved** unit mappings only. `calculability_status` gains `potency_basis_unknown` (for `mg/mg`) and keeps `potency_unit_missing` for unmapped strings.

**E. On the formulation side:** each ingredient quantity is stored with the same `QuantityExpression` kinds, and the product's **maximum daily dose** as a structured amount + unit + per-day (needed for Q8; the White Paper spec Q6 already proposes this).

**Migration:** additive only (new nullable fields and a new table; seed rows in a data migration). Existing rows keep their raw strings; nothing is rewritten except by the governed re-resolve step after approval. Rollback drops the new fields.

## 4. Allowed vs refused conversions

| From → To | Allowed? | Rule |
|---|---|---|
| mass ↔ mass (mg, mcg, g) | **Allowed** | Exact factor |
| volume ↔ volume (mL, L) | **Allowed** | Exact factor |
| Concentration `mg/5ml` → `mg/mL` | **Allowed** | Divide by the stated volume (exact) |
| Volume ratio `ml/5ml` → `mL/mL` | **Allowed** | Divide by the stated volume (exact) |
| `mL/mL` ↔ `%v/v` | **Allowed only with reviewer approval** | Mathematically ×100; listed for approval because it changes the representation the FDA chose |
| `mg/mL` ↔ `%w/v` | **Allowed only with reviewer approval** | 1 %w/v = 10 mg/mL by definition (g per 100 mL); same as White Paper C3; needs sign-off |
| `%w/w` ↔ `mg per dose unit` | **Refused** unless the formulation supplies an approved total unit weight; then computed per formulation, never stored as an IID conversion | Needs a basis the IID does not state |
| `%w/v` ↔ `%w/w` | **Refused** | Needs density |
| mass ↔ volume (mg ↔ mL) | **Refused** unless an approved density is supplied (existing rule) | |
| per dose unit ↔ per day | **Only via the Q8 rule** (amount per unit × maximum units per day), once approved | Needs the product's maximum daily dose |
| `mg/mg` → anything | **Refused** | Basis unknown; reviewer must state it |
| Percentage of one basis ↔ another basis | **Refused** | Different physical quantities |

Every refusal returns a reason code (the existing `BASIS_REQUIRED`, `DENSITY_REQUIRED`, `DIMENSION_MISMATCH`, `CONVERSION_NOT_SUPPORTED`) and is shown to the user as "cannot compare: <reason>".

## 5. What can be built now vs what needs regulatory approval

| Work | Build now (engineering) | Needs approval before activation |
|---|---|---|
| `QuantityExpression` model, migration, parser proposing templates for the 21 IID strings | Yes | — |
| Seed unit list (mg, mcg, g, mL, L, dose unit, day) | Yes (as proposed data) | Reviewer approves the list |
| Unit mappings for the 21 strings | Proposals generated now | **Reviewer approves each** (like the 164 route/form mappings) |
| Re-resolve filling `potency_expression` / `mde_expression` | Yes (code) | Runs only on approved mappings |
| Like-for-like comparison (per-unit mass, concentration, same-basis percentage) | Yes (code, behind the existing approval gates) | Comparison rule approved (content gate / Register 13) |
| `%v/v` ↔ `mL/mL`, `%w/v` ↔ `mg/mL` | Code ready, switched off | Reviewer approval |
| Per-day comparison | Code after Q8 is answered | **Q8 written confirmation** (iCretegy + reviewer) |
| `mg/mg` basis | — | Reviewer states the basis, or it stays refused |

## 6. Size [Estimate]

| Piece | Size |
|---|---|
| Model + additive migration + seed data migration | 1–2 days |
| Parser and unit-mapping proposals (same flow as `propose_iid_mappings`) | 1–2 days |
| Re-resolve extension and calculability statuses | 1–2 days |
| Formulation-side quantity expressions and structured maximum daily dose | 2–3 days |
| Like-for-like comparison wiring in `iid_assessment` + refusal reasons in API/UI | 2 days |
| Tests (each IID string, every refused pair, Decimal precision, migration rollback) | 2 days |
| **Total** | **about 9–13 days** (1.5–2.5 fortnights for one developer), plus reviewer time for approvals |

**First demonstrable result:** the 1,914 records with `mg` per dose unit, once their route and dosage-form mappings and the `mg` unit mapping are approved: REGX retrieves the IID record, compares the formulation's mg per dose unit against it, and shows the source row, the numbers and "at or below / above". Never "acceptable".
