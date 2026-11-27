# End-to-end calculation run: SAMPLE losartan potassium 100 mg film-coated tablet (2026-11-27)

**Generated from the browser run's own output** (`regress/e2eForm.js`, `e2eIID.js`, `e2eChecklist.js`), not typed by hand. Screenshots are in the review hand-off only (`review-handoff/evidence__shot__e2e_*.png`), not in git.

- **Stack:** `regx-v25`, rebuilt from a local, never-pushed merge of `regx-main` (4ff74d7) + #166 (the IID preview keeps the typed unit) + #169 (reference-product label). Public FDA data: Orange Book `EOBZIP_2026_08.zip`, IID July 2026 (`IIR_OCOMM.csv`, active release `2247adc0-e3fb-4baa-8dd1-8c3c7b613018`). Demo users only.
- **Product (SAMPLE, synthetic, not a real formula):** losartan potassium 100 mg, oral, film-coated tablet. Reference: COZAAR, NDA 020386, product 003, 100 mg, RLD and RS in the Orange Book.
- **All amounts are SAMPLE values** chosen for the run, not a real Cozaar or generic formula.

## 1. Formulation (as typed and as shown)

- product created: SAMPLE-LOS100-027460, LOSARTAN POTASSIUM, ORAL, TABLET, FILM COATED
- reference selected: N020386-003 (HTTP 200)
- version created: total dosage-unit weight 293.5 (SAMPLE), maximum 1 unit/day (SAMPLE)
- component Active LOSARTAN POTASSIUM 100 mg -> HTTP 201
- component Inactive MICROCRYSTALLINE CELLULOSE 120 mg -> HTTP 201
- component Inactive LACTOSE MONOHYDRATE 60 mg -> HTTP 201
- component Inactive MAGNESIUM STEARATE 4 mg -> HTTP 201
- component Inactive HYPROMELLOSE 2910 (6 MPA.S) 6 mg -> HTTP 201
- component Inactive TITANIUM DIOXIDE 2 mg -> HTTP 201
- component Inactive POLYETHYLENE GLYCOL 3350 1.5 mg -> HTTP 201
- approval region: Review and approval Status: Approved (internal) When What Who Reason / note 11/27/2026, 1:07:12 PM created doer@demo.regx.invalid 11/27/2026, 1:07:20 PM submitted for review doer@demo.regx.invalid 11/
- checklist execution: HTTP null at http://localhost:8080/iig-checklists/executions/new?tenant=demo&formulationVersion=a3b669b8-19d2-4822-8504-6a595ce94158
- Checklist: execution created with `DEMO-EXCIPIENT-REVIEW — DEMO-Excipient review (demo content) (v1)` (demo content) for `SAMPLE-LOS100-027460 — SAMPLE losartan potassium 100 mg film…`: HTTP 201.

| Component | Type | SAMPLE amount per tablet |
|---|---|---|
| LOSARTAN POTASSIUM | active | 100 mg |
| MICROCRYSTALLINE CELLULOSE | inactive | 120 mg |
| LACTOSE MONOHYDRATE | inactive | 60 mg |
| MAGNESIUM STEARATE | inactive | 4 mg |
| HYPROMELLOSE 2910 (6 MPA.S) | inactive | 6 mg |
| TITANIUM DIOXIDE | inactive | 2 mg |
| POLYETHYLENE GLYCOL 3350 | inactive | 1.5 mg |
| **Total dosage-unit weight (typed)** | | **293.5 mg** |

**What the screens showed:**
- **Product page, after choosing the reference:** only `Application 020386-003` with an "FDA SOURCE" badge. Not shown: trade name, strength, RLD/RS, the Orange Book file or its release date. The search table before choosing shows trade name, application, strength (raw text "100MG"), RLD/RS and discontinued, with no file name or date.
- **Version page:** the "% w/w CALCULATED" column says **"not yet calculated"** for all seven components, although the total weight (293.5 mg) is set. No calculation runs on the formulation screens.
- **Version page link "Run IID assessment preview →":** opens an empty preview form. Every value below was typed again by hand.
- **Checklist (demo content):** three questions, all typed answers. No fetched or calculated value. The header shows the formulation version as an ID, not the product name.

## 2. IID preview, per excipient (route ORAL, 1 unit/day, total 293.5 mg)

Each excipient was previewed under two IID dosage forms:
- **TABLET, FILM COATED:** the tablet as made.
- **TABLET:** what the Orange Book row for COZAAR says.

| Excipient | Part | IID dosage form used | Matched IID row (FDA values) | Match | Decision shown |
|---|---|---|---|---|---|
| MICROCRYSTALLINE CELLULOSE | core | TABLET, FILM COATED | TABLET, FILM COATED: per-unit — ; daily max 992 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| LACTOSE MONOHYDRATE | core | TABLET, FILM COATED | TABLET, FILM COATED: per-unit — ; daily max 968 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| MAGNESIUM STEARATE | core | TABLET, FILM COATED | TABLET, FILM COATED: per-unit — ; daily max 96 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| HYPROMELLOSE 2910 (6 MPA.S) | film coat | TABLET, FILM COATED | TABLET, FILM COATED: per-unit — ; daily max 345 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| TITANIUM DIOXIDE | film coat | TABLET, FILM COATED | TABLET, FILM COATED: per-unit — ; daily max 36 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| POLYETHYLENE GLYCOL 3350 | film coat | TABLET, FILM COATED | TABLET, FILM COATED: per-unit 20 milligram; daily max — | EXACT_MATCH | **REVIEW_REQUIRED** |
| MICROCRYSTALLINE CELLULOSE | core | TABLET | TABLET: per-unit — ; daily max 6184 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| LACTOSE MONOHYDRATE | core | TABLET | TABLET: per-unit — ; daily max 4384 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| MAGNESIUM STEARATE | core | TABLET | TABLET: per-unit — ; daily max 980 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| HYPROMELLOSE 2910 (6 MPA.S) | film coat | TABLET | TABLET: per-unit — ; daily max 880 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| TITANIUM DIOXIDE | film coat | TABLET | TABLET: per-unit — ; daily max 232 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |
| POLYETHYLENE GLYCOL 3350 | film coat | TABLET | TABLET: per-unit — ; daily max 52 mg | POTENCY_UNAVAILABLE | **NOT_COMPARABLE** |

- **Decision notes shown:**
  - NOT_COMPARABLE: "cannot compare: the IID record states only a maximum daily exposure; comparing per day is not supported yet"
  - REVIEW_REQUIRED: "Within selected IID potency precedent, but maximum daily exposure precedent is unavailable for comparison."
- **Source and release date on screen:** none of the 12 preview screens shows the IID file name or any release or publication date.
  - It shows an editable "Active FDA release ID" box (a UUID) and the line "About the active IID release: 67 of 9,071 records…".
  - Where a comparison ran, it also shows "IID source row" and "IID release: <UUID>". **Finding:** the user cannot see which FDA file or which date a value came from.

## 3. Every calculation, and a hand check

Hand working: % w/w = amount ÷ 293.5 × 100, where 1 ÷ 293.5 × 100 = 0.3407155025… Daily exposure = amount × 1. The server's values are taken from the TABLET, FILM COATED previews.

| Excipient | Calculation | Hand value | Server value (full) | Match |
|---|---|---|---|---|
| MICROCRYSTALLINE CELLULOSE | percentage_w_w | 40.885860 | 40.88586030664395229982964225 | yes |
| MICROCRYSTALLINE CELLULOSE | daily_exposure | 120 | 120.0000000000 | yes |
| LACTOSE MONOHYDRATE | percentage_w_w | 20.442930 | 20.44293015332197614991482112 | yes |
| LACTOSE MONOHYDRATE | daily_exposure | 60 | 60.0000000000 | yes |
| MAGNESIUM STEARATE | percentage_w_w | 1.362862 | 1.362862010221465076660988075 | yes |
| MAGNESIUM STEARATE | daily_exposure | 4 | 4.0000000000 | yes |
| HYPROMELLOSE 2910 (6 MPA.S) | percentage_w_w | 2.044293 | 2.044293015332197614991482112 | yes |
| HYPROMELLOSE 2910 (6 MPA.S) | daily_exposure | 6 | 6.0000000000 | yes |
| TITANIUM DIOXIDE | percentage_w_w | 0.681431 | 0.6814310051107325383304940375 | yes |
| TITANIUM DIOXIDE | daily_exposure | 2 | 2.0000000000 | yes |
| POLYETHYLENE GLYCOL 3350 | percentage_w_w | 0.511073 | 0.5110732538330494037478705281 | yes |
| POLYETHYLENE GLYCOL 3350 | daily_exposure | 1.5 | 1.5000000000 | yes |
| POLYETHYLENE GLYCOL 3350 | percentage_of_iid_potency (IID 20 mg per unit) | 7.5 | 7.500 | yes |
| POLYETHYLENE GLYCOL 3350 | difference_from_iid_potency (IID 20 mg per unit) | 18.5 | 18.500000 | yes |
| POLYETHYLENE GLYCOL 3350 | comparison | 1.5 ≤ 20 → at or below | at_or_below (1.5 vs 20 mg per dose unit) | yes |

**Result: every server value matches the hand working.**

**Not calculated, and why** (from the run):
- **% of IID per-unit value, difference from it, % of IID daily maximum, difference from it:** not calculated for the five excipients whose IID row has only a daily maximum. REGX does not compare per day yet (the per-day rule, Q8).
- **% of IID daily maximum for PEG 3350 (film coated):** not calculated, because that IID row has no daily maximum.
- **Daily exposure:** shown with no unit on screen. It is in the unit typed, here mg.

## 4. Final status

- **Five excipients, under either dosage form:** **Not comparable**. Their IID rows give only a daily maximum. These are microcrystalline cellulose, lactose monohydrate, magnesium stearate, hypromellose 2910 (6 mPa·s) and titanium dioxide.
- **Polyethylene glycol 3350:**
  - Under TABLET, FILM COATED: within the per-unit value (7.5 % of 20 mg), then **Review required**, because no daily maximum is given (F-3).
  - Under TABLET: **Not comparable** (daily maximum only).
- **No excipient reaches "Within IID precedent" (pass).** On this product, with this IID release, REGX cannot clear any excipient automatically. A reviewer must judge all six.
