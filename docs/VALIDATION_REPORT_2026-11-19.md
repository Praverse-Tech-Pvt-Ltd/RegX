# Validation report, 2026-11-19: GPT blind test, Orange Book, built-in formulas

Report only. No product code was changed in this session.

**How it was run**
- One clean stack built from `regx-main@d14e286`: compose project `regx-val`, on its own ports, with a fresh database. It was migrated and seeded with `seed_regx_demo`.
- Public FDA data only:
  - IID July 2026 (`IIR_OCOMM.csv`, 9,071 rows);
  - SPL route and dosage-form lists;
  - REGX's controlled-units list;
  - Orange Book `EOBZIP_2026_08` (`products.txt`, 48,761 rows).
- Every release went through the full lifecycle: import, validate, submit-review, approve, activate.
- All approvals were **LOCAL TEST approvals**, signed by the demo Reviewer and VP. That covers 184 route, dosage-form and unit mappings. 67 IID rows with the plain dosage form `DROPS` stay unmapped, as before.
- No client data was used.

Raw evidence (requests, responses, scripts) is kept outside the repository, in `D:/Praverse/session-work/2026-11-19/s25/` and in the external-test folder. It is also in the session hand-off.

---

## Part 1: GPT blind test (40 cases)

**The cases**
- An independent tester wrote 40 cases from `iid_sample.csv` (58 public IID rows) and `RULES_FOR_TESTER.md` only.
- The tester wrote down expected answers before anything was run. The cases were not edited.
- Each case went through the real preview API, `POST /api/regx/v1/iid-assessments/preview/`, the same way the preview page sends it.

### Result

| | |
|---|---|
| **Pass rate (37 scored cases)** | **37 / 37 (100%)** |
| Rule-unclear cases (T031, T032, T040), excluded from the rate | 0 / 3 match the tester's expectation. In all three, REGX's behaviour is defensible. Each needs a rule decision (below). |
| Numerical discrepancies | **None.** All 22 comparable cases give exactly the tester's value. |
| Failures from missing or unapproved reference mappings | **None among the scored cases.** T031 tests the unmapped `DROPS` form on purpose, and gets the documented reason. |

A case passes only if all three of these match:
- the result;
- the reason code, when the tester gave one;
- the displayed value, compared as a number, when the tester gave one.

Per-case tables, arithmetic and evidence are in `gpt_comparison.md` and `gpt_actual.csv`, in the external-test folder.

### Mapping table: the tester's result names and what REGX returns

The five names come from REGX's own tester rules (`RULES_FOR_TESTER.md` section 7). The API does not return them, so one fixed rule maps every response:

| Tester name | REGX response | Reason code from | One-to-one? |
|---|---|---|---|
| `AT_OR_BELOW` | HTTP 200; `potency_comparison.comparable = true`, `result = at_or_below` | none | **No.** The decision is `REVIEW_REQUIRED` whenever no daily-maximum check can run. It is `PASS_WITH_IID_PRECEDENT` only when that check runs and passes. See finding F-3. |
| `ABOVE` | HTTP 200; `comparable = true`, `result = above`; decision `EXCEEDS_IID_PRECEDENT` | none | Yes |
| `CANNOT_COMPARE` | HTTP 200; `comparable = false` | `potency_comparison.reason_code` | **No.** The match status is `EXACT_MATCH`, or `POTENCY_UNAVAILABLE` when the IID row has no usable potency. The decision is `NOT_COMPARABLE`. |
| `INVALID_INPUT` | HTTP 400 with a field message; nothing is looked up | (message) | Yes |
| `NO_MATCH` | HTTP 200 with no potency comparison (no IID record selected) | `match_reason_code` | **No.** It covers several match statuses: `NO_MATCHING_IID_PRECEDENT`, `DOSAGE_FORM_MISMATCH`, `ROUTE_MISMATCH`, `REVIEW_REQUIRED` and `INGREDIENT_AMBIGUOUS`. |

**Field names.** The tester's `expected_display_value` is the field the rules call `expected_value`. It is compared with `potency_comparison.proposed_value`: the amount restated in the IID record's unit and volume.

**Inputs the cases do not give.** These were sent the way the page sends them:
- route and dosage-form names are turned into codes;
- the meaning is left blank for "per dosage unit", and otherwise set to the listed meaning for the basis;
- the unit is sent as typed;
- the total dosage-unit weight is 1000 mg (the page requires it; it affects only % w/w);
- the maximum units per day is left blank.

### The three rule-unclear cases

| Case | Tester expected | REGX | Assessment |
|---|---|---|---|
| T031 GLYCERIN, NASAL, DROPS | CANNOT_COMPARE `ROUTE_OR_FORM_UNMAPPED` | NO_MATCH: `DOSAGE_FORM_MISMATCH` / `DOSAGE_FORM_NOT_MAPPED` | **REGX follows the rule.** Rules section 5 names this exact case: the IID's plain `DROPS` gives `DOSAGE_FORM_NOT_MAPPED`. The tester was misled because the cannot-compare table also lists `ROUTE_OR_FORM_UNMAPPED`, and that code can never occur in the preview: matching uses only mapped routes and forms (`backend/iid_assessment/matching.py:81-82`), so `backend/iid_assessment/comparison.py:228-229` is never reached. **Clarify the rules sheet** (C-1). |
| T032 blank amount | CANNOT_COMPARE `PROPOSED_VALUE_MISSING` | INVALID_INPUT (HTTP 400, "A valid number is required.") | **Rules and product disagree.** The amount is a required field (`backend/iid_assessment/serializers.py:20`), and the page does not let the user submit it empty. `PROPOSED_VALUE_MISSING` is unreachable from the preview. **Decide, then fix the sheet** (C-2). |
| T040 CORIANDER OIL, TOPICAL, ELIXIR | NO_MATCH `NO_RECORD_FOR_ROUTE_AND_FORM` | NO_MATCH `RECORDS_NOT_LINKED` | **REGX follows the written rule, but the rule is too broad.** The full IID file has a CORIANDER OIL, ORAL, **DROPS** row (not in the tester's sample). It is unmapped, so REGX says some records "cannot be checked". But an ORAL row can never be a TOPICAL precedent (`backend/iid_assessment/reasons.py:153-157` counts every unlinked record). **Decide** (C-3). |

---

## Part 2a: Orange Book

| Check | Result |
|---|---|
| Import the real FDA file (`EOBZIP_2026_08`, `products.txt`) | **Pass.** 48,761 rows parsed and 48,761 imported, 0 failed. The raw file has 48,762 lines including the header. Then validate, submit-review (Doer), approve, activate (VP). |
| Search by trade name | **Pass (API).** `AMZEEQ` and `amzeeq` each return 1 product (AMZEEQ N212379-001). `AMZ` returns 10, the same as a substring count in the raw file. An unknown name returns 0. |
| Search by application number | **Pass (API).** `212379`, `N212379`, `NDA212379` and `nda 212379` each return AMZEEQ N212379-001. `A212379`, `ANDA212379`, `21237`, `2123790` and `X212379` each return 0. |
| RLD, RS and discontinued flags against the raw file, 5 products | **Pass, 5/5.** See the table below. |
| Reference-product selection accepts only real active-release products | **Pass, 7/7.** Refused (HTTP 400, nothing stored): a random UUID; a product from a registered but **not active** release; a wrong release ID; a wrong application number; a prefixed `N212379`; a wrong product number. Accepted: AMZEEQ 212379-001 from the active release. |

**The 5 products checked against the raw file**

| Product | Raw file (RLD / RS / Type) | REGX (rld / rs / discontinued) |
|---|---|---|
| N212379-001 AMZEEQ | Yes / Yes / RX | true / true / false |
| N050801-001 EVOCLIN | Yes / No / DISCN | true / false / true |
| A215328-001 BUDESONIDE | No / Yes / RX | false / true / false |
| A210928-001 AZELAIC ACID | No / No / DISCN | false / false / true |
| N021812-001 MEN'S ROGAINE | Yes / Yes / OTC | true / true / false |

The 5 products cover:
- both flags set, RLD only, RS only, and neither;
- each marketing type: RX, OTC and discontinued.

They do not cover every combination in the file. For example, "RLD only, RX" was not checked.

**Test set-up note.** For the "not active release" check, a second Orange Book release was registered and left inactive. It is a copy of `products.txt` with its last line removed. The identical file is refused as a duplicate, and the deliberate re-import from #135 is IID-only by design.

**Gaps found (from the page source; not clicked through in a browser this session):**
- **F-4.** The Orange Book search page has **no trade-name or application-number field.** The API supports both, but the page offers only ingredient, route code, dosage-form code, strength, application type, RLD and discontinued (`frontend/src/app/(regx)/fda-data/orange-book/page.tsx`).
- **F-5.** "Select reference product" on a formulation asks the user to **type four identifiers by hand**: application number, product number, the Orange Book product UUID and the FDA release UUID (`frontend/src/app/(regx)/formulations/[publicId]/page.tsx:168-186`). The product UUID appears only in the URL of the Orange Book detail page. Typing the natural form `N212379` is refused, because the stored number is `212379`. This is the same pattern that was fixed for the IID preview's release ID.

**What is NOT built**
- **Patents and exclusivity.** `Patent.txt` and `Exclusivity.txt` in the same ZIP are deliberately ignored. There is no patent or exclusivity model (`backend/fda_data/parsers.py:40-44`). The dataset types exist only as names in `backend/fda_data/models.py:28-29`.
- **New-data detection.** Nothing checks fda.gov for a newer file: no scheduled task and no fetch. Every release is loaded by an operator command (`import_fda_release`).
- **Lookup page.** A search page *does* exist (`/fda-data/orange-book`, with a product detail page), but it lacks trade-name and application-number search (F-4). "Not built" is therefore not accurate. "Built, but incomplete" is.
- **White-paper calculations.** Nothing in REGX. White papers exist only in the legacy company_site (`/ratools/general_white_paper_*`), and REGX does not use them.

---

## Part 2b: Calculators and built-in formulas

### The SOW 2.3 calculators are not built

- There is no dissolution calculator, no impurity calculator and no stability-trend calculator, and nothing to port from the legacy code (`docs/EXTERNAL_BLOCKER_READINESS.md` section 2, P9: "For SOW 2.3 itself: nothing exists").
- **Why:** they are waiting on the client (iCretegy) for an approved formula specification for each calculator. They also need a separately approved engineering scope, because `SCOPE-OUT-18` caps formulas at the six approved ones. Building them on guesses is prohibited.

### The six built-in formulas

These are the IIG checklist formulas in `CALCULATION_BINDING_REGISTRY`, implemented in `backend/iid_assessment/calculations.py`. Each was run at two levels:
- **engine:** the registry function itself, inside the backend container;
- **end to end:** through the real preview API, which calls the same functions.

Every expected value was worked out by hand first.

| Formula | Hand-checked examples | Edge cases | Result |
|---|---|---|---|
| A `percentage_w_w` = quantity ÷ unit weight × 100 (in grams) | 0.063 ÷ 0.250 × 100 = **25.2**; 0.0005 ÷ 0.2 × 100 = **0.25**. End to end: 63 mg in a 250 mg unit = 25.2; 77 mg in 350 mg = **22**; 0.0035 g in 0.5 g = **0.7** | unit weight 0 → blocked (`NOT_COMPARABLE`), never a division error; no quantity → `DATA_REQUIRED`; amount per volume → refused (`NOT_PER_DOSE_UNIT`) | **Pass** |
| B `daily_exposure` = quantity × max units per day | 63 × 3 = **189**; 0.5 × 12 = **6**. End to end: 189; 77 × 2 = **154**; 0.0035 g × 4 = **0.014 g** | no max units per day → `DATA_REQUIRED`, never 0 | **Pass** |
| C `percentage_of_iid_potency` = proposed ÷ IID potency × 100 | 63 ÷ 70 × 100 = **90**; 77 ÷ 70 × 100 = **110**. End to end: 90, 110; 3.5 mg ÷ 70 × 100 = **5** | IID potency 0 → blocked; 10 ÷ 30 → 33.333… (exact Decimal, 28 digits) | **Pass** |
| D `difference_from_iid_potency` = IID potency − proposed | 70 − 63 = **7**; 70 − 77 = **−7**. End to end: 7, −7, 66.5 | no proposed amount → `DATA_REQUIRED` | **Pass** |
| E `percentage_of_iid_mde` = daily exposure ÷ IID MDE × 100 | 189 ÷ 600 × 100 = **31.5**; 900 ÷ 600 × 100 = **150** | no MDE → blocked, never 0 | **Pass (engine only).** See F-3. |
| F `difference_from_iid_mde` = IID MDE − daily exposure | 600 − 189 = **411**; 600 − 900 = **−300** | no daily exposure → `DATA_REQUIRED` | **Pass (engine only).** See F-3. |

**Totals:** engine 20/20 checks pass; end to end 17/17 checks pass.

**Observation.** The engine itself accepts −5 units per day (and returns −315). The API refuses a negative or zero value before the engine runs (`iid_assessment/amount_limits.py`), so a user cannot reach it.

**Not exercised.** On a clean install, no checklist definition binds a calculation. The demo seed's `DEMO-` checklist has none, and activating unreviewed content is barred by the content gate. So the checklist's own binding path (registry → input resolver → stored answer) was not run end to end. It is covered by the existing tests in `backend/iig_checklist/tests/test_4d3_calculation_*.py`.

---

## Confirmed product defects (fix next)

| # | Defect | Evidence | Severity |
|---|---|---|---|
| **F-1** | **The IID preview ignores the typed unit when a meaning is chosen.** With the meaning "mg per dose unit", a typed "0.03 g" is read as 0.03 mg. The result is a false **at or below** (correct: 30 mg is above the IID limit of 0.03 mg). "20 mcg" is read as 20 mg and gives a false **above**. Formulation components already refuse a unit that disagrees with the meaning (`fda_data/controlled_units.py:514` `stated_amount_problem`, used at `backend/formulations/serializers.py:315`). The preview serializer has no such check (`backend/iid_assessment/serializers.py:50-74`); the amount is read in the meaning's unit (`backend/iid_assessment/assess.py:199-203`, `comparison.py:109-123`). The page pre-fills the unit when a meaning is chosen, but the user can edit it afterwards. | probe on the live stack, 5 requests (`probe_meaning_unit.txt`) | **High.** A false "at or below" is the one wrong answer this screen must never give. |
| **F-4** | The Orange Book search page has no trade-name or application-number search, although the API supports both. | page source, above | Medium (the feature exists only in the API) |
| **F-5** | Reference-product selection needs two UUIDs typed by hand, and refuses the natural "N212379". | page source and API test, above | Medium (usability) |

The 37 scored GPT cases did not find F-1. Every per-dosage-unit case used the page default (no meaning), and every case with a meaning typed the meaning's own unit. The tester rules never say what happens when the two disagree.

## Rule clarifications that need Pratham's or the reviewer's decision

| # | Question | Current behaviour | Recommendation |
|---|---|---|---|
| **C-1** | Should `ROUTE_OR_FORM_UNMAPPED` stay in the tester rules? | It cannot occur in the preview: an unmapped record is never matched, and the user gets `DOSAGE_FORM_NOT_MAPPED` or `ROUTE_NOT_MAPPED` instead. | Say so in the rules sheet, or remove the code from the table. |
| **C-2** | Is a blank amount `INVALID_INPUT` or `CANNOT_COMPARE / PROPOSED_VALUE_MISSING`? | `INVALID_INPUT` (HTTP 400, "A valid number is required."); the page blocks it first. | Keep `INVALID_INPUT` and fix the rules sheet. Reword the API message to "Enter an amount". |
| **C-3** | Should `RECORDS_NOT_LINKED` count unlinked IID records that could never match the requested route and form? | Yes: any unlinked record of the ingredient counts (T040: an ORAL DROPS row is counted for a TOPICAL ELIXIR request). | Count only unlinked records whose mapped parts still fit the request. T040 would then get `NO_RECORD_FOR_ROUTE_AND_FORM`. Also fix the grammar slip "1 of its records have". |
| **F-3** | With real data, the result can never be "Pass with IID precedent", and formulas E/F never run. | No row in the IID July 2026 file has both a potency and a maximum daily exposure (0 of 9,071). E/F run only after a potency comparison, and `PASS_WITH_IID_PRECEDENT` needs a usable daily maximum (`backend/iid_assessment/decisions.py:201-232`). So every within-limit result is "Review required". | Conservative, so not a defect, but the owner should know. It depends on the per-day rule (Q8) still being decided. State it in the user help text and the tester rules. |
| **C-4** | Reference selection: should a prefixed application number (`N212379`) be accepted? | Refused ("Does not match"), while search accepts it. | Accept the same spellings as search, or fill the field from the chosen search result (part of F-5). |

---

## What this report does not cover

- **The browser.** Every check here went through the API or the page source. The preview, Orange Book and formulation pages were not clicked through this session.
- **Snapshots.** The persisted assessment snapshot path was not tested. It reads the meaning from the stored component, where F-1 cannot happen.
- **CI.** Not run: GitHub Actions are disabled, and this is a docs-only change.
