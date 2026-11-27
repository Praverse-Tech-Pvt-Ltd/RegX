# Calculation release gate (2026-11-27)

**What this is:** 15 cases for the IID preview, each with an expected answer worked by hand from REGX's written rules. They are implemented as one test file, `backend/iid_assessment/tests/test_calc_release_gate.py`, in its own tests-only PR (case numbers match).

**What it proves, and what it does not:**
- It proves REGX gives the answers its **own rules** say it should: at the exact limit, just above it, across mass units, and where it must refuse.
- It does **not** prove the rules are regulatorily correct. **The expected answers below need the regulatory reviewer's sign-off** before they can count as the release gate.

**Run on 2026-11-27:**
- All 15 pass on `regx-main` (4ff74d7).
- A deliberate bug (`>` changed to `>=` in the limit check at `backend/iid_assessment/decisions.py:188`) makes cases 1, 3, 5 and 13 fail. The test catches an off-by-limit error. The code was restored straight after.

## The rules the answers come from

| Rule | Where |
|---|---|
| Match only on exact ingredient + controlled route + controlled dosage form + active release; no record → "no match" | `backend/iid_assessment/matching.py:79-96` |
| A record with a daily maximum but no per-unit value is not compared (per-day rule is open, Q8) | `matching.py:124-133`, `comparison.py:57-60` |
| Compare only same family (mass / volume / percentage) and same basis (per dose unit / per volume / w/w …); mass units convert by exact factors | `backend/iid_assessment/comparison.py:36-72`, `unit_conversion.py:78-98` |
| % w/w = amount ÷ total dosage-unit weight × 100 (both in grams) | `calculations.py:77-102`, called at `assess.py:249-262` |
| Daily exposure = amount per unit × maximum units per day | `calculations.py:104-128` |
| % of IID per-unit value = amount ÷ IID per-unit value × 100; difference = IID value − amount | `calculations.py:130-183` |
| % of IID daily maximum and difference: same, with daily exposure; only when the record has a daily maximum **and** the per-unit comparison ran | `calculations.py:185-237`, `assess.py:280-316` |
| Decision order: no match → not comparable (refused comparison) → review (no per-unit value) → exceeds (amount > per-unit value) → exceeds (daily exposure > daily maximum) → review (no daily maximum) → pass | `backend/iid_assessment/decisions.py:100-235` |

"Above" means strictly more than the limit: an amount equal to the limit is "at or below" (`decisions.py:188`).

## Synthetic data (one made-up active IID release, route ORAL, dosage form TABLET)

| Excipient | IID per-unit value | IID daily maximum |
|---|---|---|
| A | 50 mg per dose unit | none |
| B | none | 200 mg per day |
| C | 50 mg per dose unit | 200 mg per day |
| D | (in the ingredient list, no record) | — |

- **Shapes:** A and B are the two shapes the real July 2026 file has. C (both values) does not occur in it (F-3), so C is the only way to test the pass and the daily-maximum branch.
- **Also in the data:** route BUCCAL and dosage form CAPSULE exist but have no record.
- **Every case:** total dosage-unit weight 250 mg (0.25 g).

## The 15 cases, worked by hand

| # | Case | Input | Hand working | Expected |
|---|---|---|---|---|
| 1 | Exactly at the per-unit limit | A, 50 mg | 50 = 50, not above → at or below. % of IID = 50 ÷ 50 × 100 = **100**. Difference = 50 − 50 = **0**. % w/w = 50 ÷ 250 × 100 = **20**. A has no daily maximum → cannot pass | **Review required** |
| 2 | Just above | A, 50.001 mg | 50.001 > 50 → above. Difference = 50 − 50.001 = **−0.001** | **Exceeds IID precedent** |
| 3 | Grams, at the limit | A, 0.05 g | 0.05 g × 1000 = **50 mg** → at or below. % w/w = 0.05 ÷ 0.25 × 100 = **20** | **Review required** |
| 4 | Grams, just above | A, 0.050001 g | 0.050001 × 1000 = **50.001 mg** > 50 | **Exceeds IID precedent** |
| 5 | Micrograms, at the limit | A, 50000 µg | 50000 ÷ 1000 = **50 mg** → at or below | **Review required** |
| 6 | Micrograms, just above (typed "mcg") | A, 50001 mcg | 50001 ÷ 1000 = **50.001 mg** > 50 | **Exceeds IID precedent** |
| 7 | Percent against a mass limit | A, 20 % w/w | percentage family ≠ mass family → refused `DIFFERENT_FAMILY`; no % of IID | **Not comparable** |
| 8 | Per-volume on a solid | A, 10 mg per 5 mL | per volume ≠ per dose unit → refused `DIFFERENT_BASIS`; no % of IID | **Not comparable** |
| 9 | Excipient not in the IID | D, 10 mg | no record for D → no candidate | **No match** |
| 10 | Wrong route | A, 10 mg, BUCCAL | A's only record is ORAL → no candidate | **No match** |
| 11 | Wrong dosage form | A, 10 mg, CAPSULE | A's only record is TABLET → no candidate | **No match** |
| 12 | Daily maximum only (F-3) | B, 10 mg, 1 unit/day | no per-unit value → refused `DAILY_EXPOSURE_ONLY_NEEDS_Q8`. Still calculated: % w/w = 10 ÷ 250 × 100 = **4**; daily exposure = 10 × 1 = **10**. % of daily maximum: **not calculated** | **Not comparable** |
| 13 | Exactly at the daily maximum | C, 50 mg, 4/day | per unit: 50 = 50 → at or below. Daily = 50 × 4 = **200**; 200 = 200, not above. % of daily max = 200 ÷ 200 × 100 = **100**; difference = **0** | **Pass with IID precedent** |
| 14 | Above the daily maximum | C, 50 mg, 5/day | per unit at or below. Daily = 50 × 5 = **250** > 200. % = 250 ÷ 200 × 100 = **125**; difference = 200 − 250 = **−50** | **Exceeds IID precedent** |
| 15 | Within the per-unit limit, no daily maximum (F-3) | A, 25 mg, 2/day | 25 ≤ 50. % of IID = **50**; difference = **25**. No daily maximum on A → % of daily max not calculated | **Review required** ("…maximum daily exposure precedent is unavailable…") |

## Points for the reviewer

- **"At the limit" counts as within.** Is "equal to the IID value" acceptable as within precedent? (Cases 1, 3, 5, 13.)
- **Cases 7 and 8: REGX refuses rather than converts.** It never turns % w/w or mg/mL into mg per unit. Confirm that is the wanted behaviour.
- **Case 12: a daily-maximum-only record is "not comparable".** This is the common case for core excipients in real oral tablets (see `docs/CALC_MAP_LOSARTAN.md`). It stays that way until the per-day rule (Q8) is decided.
- **Case 15: within the per-unit value is never "pass" without a daily maximum (F-3).** In the July 2026 file no record has both, so on real data a pass cannot occur today.
- **Not covered here:** multiple matching records (a reviewer must pick one), superseded releases, substance-name synonyms, density-based conversions, and volume units. Existing tests cover some of these: `test_matching_and_assess.py`, `test_one_path_comparison.py`, `test_unit_conversion.py`.

## Planned cases: not implemented yet (added 2026-11-27)

The owner set two rules on 2026-11-27 (Pratham, via Pravis). Both are working defaults and **not yet reviewed by the regulatory reviewer** (`PROJECT_OVERVIEW.md` §12 items 22–23). REGX does not do either today. The cases below become runnable tests when the code is built: Q8 is order-of-work step 4, and the side-by-side view comes later. Same synthetic data as above, plus a label maximum daily dose typed by the user.

**Q8 working default.** Daily amount = amount per unit × maximum units per day. Maximum units per day = label maximum daily dose ÷ strength per unit; the user may change it, with a saved reason.

| # | Case | Input | Hand working | Expected (planned) |
|---|---|---|---|---|
| Q1 | Daily maximum only, at it | B (daily max 200 mg), 50 mg per unit; label max 400 mg/day, strength 100 mg | units/day = 400 ÷ 100 = 4; daily = 50 × 4 = 200; 200 = 200 | "Within IID daily precedent" |
| Q2 | Daily maximum only, above | B, 60 mg per unit, same label | daily = 60 × 4 = 240 > 200 | "Above IID daily precedent: justification needed" |
| Q3 | Per-unit value only | A (50 mg per unit), 50 mg | per unit 50 = 50, as today | per-unit result, as today |
| Q4 | Both values, the worse wins | C (50 mg per unit, 200 mg/day), 50 mg, units/day 5 | per unit: at or below; daily = 250 > 200 | the daily result, "Above IID daily precedent: justification needed" |
| Q5 | No match | D, any amount | no record | "No IID match: review", and no guessed value |
| Q6 | User changes units/day | B, 50 mg, units/day changed from 4 to 3 with a reason | daily = 50 × 3 = 150 ≤ 200 | "Within IID daily precedent"; the change and its reason saved with the result |
| Q7 | Change without a reason | as Q6, no reason | — | refused |

**Film-coated side by side.**

| # | Case | Input | Expected (planned) |
|---|---|---|---|
| F1 | Orange Book "TABLET", IID has "TABLET" and "TABLET, FILM COATED" | an excipient with a row under each form | both results shown side by side; **no default selection**, and in particular not the more favourable one; the user must pick one with a reason, and the choice and reason are saved with the result |
| F2 | Only one of the two forms in the IID | an excipient with a "TABLET" row only | one result, no picker |

**Wording in every case:** each status is shown as support for a decision by a qualified person, never as an approval.

**Sign-off:** expected answers reviewed by ____________ (regulatory reviewer), date ________. Until signed, these are consistency checks only.
