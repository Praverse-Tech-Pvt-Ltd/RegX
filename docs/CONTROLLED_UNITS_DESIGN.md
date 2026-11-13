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

## 7. Check of the 3,748 figure (2026-11-13, read-only)

- **Re-run:** a fresh read-only export of the 9,071 IID records from the local database is **identical** to the 2026-11-06 export (same rows; only row order differed), and the classification gives the same result: **3,748** records with a per-unit potency in a supported unit (category 5). The 164 proposed route/form mappings are still treated as applied, as before. Script and output: `classify.py`, `sample20.py`, `evidence_iid_rerun_20261113.txt`, `evidence_iid_sample20.txt` (review hand-off; the exported record files are not included).
- **"Supported" does not mean "comparable with every record in its group".** A record compares like for like only with records of the **same dimension** (mass per dose unit; volume per dose unit; mass per volume, where `mg/5ml` and `mg/1ml` convert exactly; percent **w/w**, **w/v** and **v/v** each on its own). Among the 3,748, grouped by route + dosage form (243 groups):
  - **3,663** have at least one other record of the same dimension in their group; **85** have nothing to compare against.
  - **60 groups (1,334 records) mix dimensions**, e.g. `%w/w` and `%w/v` in topical solutions, or `mg` and `mg/5ml` in oral solutions. Within those groups only same-dimension records compare; `%w/v` ↔ `mg/mL` becomes possible only after reviewer approval (section 4), and `%w/w` ↔ `%w/v` stays refused.
- **20-record sample** (seeded, one record per representation class plus 15 random; public FDA IID data):

| # | Record id | Route | Dosage form | Potency | Unit | Dimension | Comparable without an assumed conversion? |
|---|---|---|---|---|---|---|---|
| 1 | 269 | ORAL | SOLUTION | 0.11 | `mg/1ml` | mass per volume | Partly: 49 same-dimension records; 17 in other dimensions (incl. 12 in `mg` per dose unit) are not comparable |
| 2 | 322 | ORAL | TABLET, FILM COATED | 8 | `mg` | mass per dose unit | Yes (167 others) |
| 3 | 484 | ORAL | ELIXIR | 0.15 | `ml/5ml` | volume per volume | Barely: 1 other; 33 are mass-based |
| 4 | 537 | ORAL | TABLET | 7.14 | `mg` | mass per dose unit | Yes (396) |
| 5 | 575 | VAGINAL | SUPPOSITORY | 288.1 | `mg` | mass per dose unit | Yes (19) |
| 6 | 699 | ORAL | TABLET, FILM COATED | 41.25 | `mg` | mass per dose unit | Yes (167) |
| 7 | 948 | ORAL | SUSPENSION | 111.12 | `mg/5ml` | mass per volume | Partly: 57 same; 8 not |
| 8 | 1128 | SUBLINGUAL | TABLET | 1.6 | `mg` | mass per dose unit | Yes (50) |
| 9 | 1352 | TOPICAL | SWAB | 0.05 | `%w/w` | percent w/w | Yes (5) |
| 10 | 1372 | TOPICAL | SOLUTION | 0.7 | `%w/w` | percent w/w | Partly: 53 same; 20 in `%w/v` are not |
| 11 | 1945 | ORAL | TABLET, FILM COATED | 5.67 | `mg` | mass per dose unit | Yes (167) |
| 12 | 2951 | INTRADERMAL | INJECTION | 1.6 | `%w/v` | percent w/v | Partly: 5 same; 5 in `mg` are not |
| 13 | 3007 | TOPICAL | SOAP | 0.76 | `%w/w` | percent w/w | Yes (40) |
| 14 | 3276 | NASAL | SPRAY | 10 | `ml` | volume per dose unit | Barely: 1 other; 7 not |
| 15 | 4059 | TOPICAL | SOLUTION | 1.4 | `%w/w` | percent w/w | Partly: 53 same; 20 not |
| 16 | 4735 | ORAL | TABLET | 25 | `mg` | mass per dose unit | Yes (396) |
| 17 | 5312 | ORAL | TABLET, EXTENDED RELEASE | 6.75 | `mg` | mass per dose unit | Yes (135) |
| 18 | 5537 | ORAL | TABLET, FILM COATED | 0.7 | `mg` | mass per dose unit | Yes (167) |
| 19 | 5986 | TOPICAL | LIQUID | 1 | `%w/w` | percent w/w | Yes (14) |
| 20 | 8819 | OPHTHALMIC | SOLUTION | 0.45 | `%w/v` | percent w/v | Partly: 36 same; 19 in `%w/w` are not |

- **Verdict:** the 3,748 are real per-unit limits in units the minimal model can represent exactly, and 3,663 of them have a like-for-like comparator. The comparison must run **per dimension**, never across `%w/w` and `%w/v` or across per-dose and per-volume values. A first pass at this check of my own wrongly grouped `%w/w` with `%w/v`; it was corrected before these figures were written.

## 8. Demo labels: "technically comparable" vs reviewed results

Every comparison result carries **one basis**, worked out by the server (never typed by a user, never taken from the request):

| Basis | When | What the user sees | Where it can appear |
|---|---|---|---|
| `technical_demo` | **Any** input is not signed off: a route or dosage-form mapping in `proposed` status (TEST approvals included), the unit mapping, a conversion that still needs reviewer approval, or checklist content outside the 20-item gate | A badge on every row and a banner above the table: **"Technically comparable (not regulatorily approved). Demonstration only: the mappings and units used have not had regulatory sign-off."** The same sentence is written into every export (PDF/Excel header and each row's note) | Demo and internal environments. In production it is hidden unless an administrator switches on a demo flag, and then it keeps the same label |
| `reviewed` | **Every** input has documented sign-off (reviewer, date, decision record id) | A neutral label: **"Comparison inputs reviewed by [reviewer] on [date]."** with a link to the sign-off record. Still only "at or below / above the IID value", never "acceptable", "safe" or "approved by FDA" | Production |

Rules:
- **Fail closed:** if the server cannot prove every input is signed off, the result is `technical_demo`. Approval of one input never upgrades a result that also used an unapproved one.
- The basis and the list of unapproved inputs are returned by the API next to the numbers (field `basis` and `unreviewed_inputs`), so the UI, exports and the audit trail all show the same thing.
- The words stay within the platform's no-regulatory-claim rule (`common/tests/test_regulatory_claim_guard.py`): `reviewed` describes our internal sign-off, not an agency decision. The exact demo wording is checked against that guard when it is built.
- Tests when this is built: a result with one proposed mapping is `technical_demo`; all approved gives `reviewed`; the export carries the label; production hides demo results by default.
- **Not built.** Units build starts only after Pratham confirms on the call (direction, Step 6).
