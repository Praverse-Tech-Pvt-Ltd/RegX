# Calculation map: losartan potassium 100 mg film-coated tablet (2026-11-27)

**Product used:** SAMPLE losartan potassium 100 mg film-coated tablet. Synthetic amounts, not a real formula.

**Reference:** COZAAR, NDA 020386, product 003, 100 mg. It is the RLD and RS in our Orange Book data (`EOBZIP_2026_08.zip`).

**Why this product:**
- Plain paracetamol tablets are not in the Orange Book: they are sold over the counter without an approved application.
- The owner chose losartan.

The run itself is in `docs/evidence/CALC_RUN_LOSARTAN_2026-11-27.md`. All `file:line` references are on `regx-main` at 4ff74d7. FE = `frontend/src/app/(regx)/`.

## 1. What each field is

**TYPED** = typed or picked by the user. **OB** = fetched from the Orange Book. **IID** = fetched from the IID. **CALC** = calculated by REGX. **NOT DONE** = the screen suggests it, but nothing computes it.

### Formulation screens
| Field | What it is | Where |
|---|---|---|
| Product code, name, active ingredient, intended route, intended dosage form | TYPED (free text; route/form never checked) | FE `formulations/new/page.tsx:65-108` |
| Reference search results: trade name, application, strength, RLD/RS, discontinued | OB (active release only; strength is the raw text, e.g. "100MG") | FE `formulations/[publicId]/page.tsx:223-250`; `backend/fda_data/views.py:426-471`, `fda_data/serializers.py:109-147` |
| "Application 020386-003" after selection | OB (only the identifiers are kept) | FE `formulations/[publicId]/page.tsx:169-172`; `backend/formulations/views.py:154-157` |
| Justification, confirmation tick | TYPED | FE `formulations/[publicId]/page.tsx:260-267` |
| Total dosage-unit weight, unit, maximum dosage units/day | TYPED | FE `formulations/[publicId]/page.tsx:325-338`; `formulations/serializers.py:171-198` |
| Components: type, ingredient name, amount, unit, meaning | TYPED (the meaning list comes from the in-force unit list) | FE `formulations/[publicId]/versions/[versionPublicId]/page.tsx:239-288` |
| **% w/w** column (labelled CALCULATED) | **NOT DONE**: always "not yet calculated"; nothing writes `percentage_w_w_snapshot` | FE `…/versions/[versionPublicId]/page.tsx:212-217`; `backend/formulations/models.py:252` |
| Dosing regimen | TYPED (never multiplied or checked against the maximum) | FE `…/versions/[versionPublicId]/page.tsx:306-335` |
| Governed maximum daily units | CALC, **not shown**: the higher of the version value and any regimen value | `backend/common/max_daily_units.py:124`; `formulations/dosing.py:56-80` |
| "Run IID assessment preview →" | Link only; it passes `versionId`, which the preview never reads, so **every value must be typed again** | FE `…/versions/[versionPublicId]/page.tsx:351`; FE `iid-assessments/preview/page.tsx:183-184` |

### IID preview
| Field | What it is | Where |
|---|---|---|
| Ingredient name, route, dosage form, amount, unit, meaning, total weight + unit, maximum units/day | TYPED | FE `iid-assessments/preview/page.tsx:329-412` |
| Active FDA release ID | Filled in (a UUID, editable); no file name, no date | FE `preview/page.tsx:240-245, 342-345` |
| Candidate / selected IID record: ingredient, per-unit value (potency), daily maximum (MDE) | IID | FE `preview/page.tsx:53-73, 446-488`; `backend/iid_assessment/matching.py:79-116, 148-177` |
| Like-for-like comparison ("at or below" / "above") | CALC: the amount is restated in the IID's unit (exact factors) and compared; "at or below" means ≤ | FE `preview/page.tsx:133-176, 491`; `backend/iid_assessment/comparison.py:180-274` |
| Percentage w/w | CALC: amount in g ÷ total weight in g × 100 | FE `preview/page.tsx:494`; `iid_assessment/calculations.py:77-102`, `assess.py:249-262` |
| Daily exposure | CALC: amount × maximum units/day (shown with **no unit**) | FE `preview/page.tsx:495`; `calculations.py:104-128` |
| Percentage of IID potency, difference | CALC: amount ÷ IID per-unit × 100; IID per-unit − amount. Only if the comparison ran | FE `preview/page.tsx:496-497`; `calculations.py:130-183`, `assess.py:280-290` |
| Percentage of IID MDE, difference | CALC on paper, **never on real data**: the daily-maximum meaning is deliberately left empty until the per-day rule (Q8) is decided, so the step fails closed | FE `preview/page.tsx:498-499`; `calculations.py:185-237`; `matching.py:166-177` |
| Decision and note | CALC (fixed rules, in a fixed order) | FE `preview/page.tsx:502-519`; `backend/iid_assessment/decisions.py:84-235` |

### Checklist screens (only demo content exists; the content gate is at 0 of 20)
| Field | What it is | Where |
|---|---|---|
| Status, versions, who/when, actions | System | FE `iig-checklists/executions/[executionPublicId]/page.tsx:90-248` |
| Manual answers, not-applicable reason, overrides, reviewer conclusion | TYPED | FE `…/ChecklistResponses.tsx:734-980` |
| Calculated answers (% w/w, daily exposure in g, % / difference of potency and MDE) | CALC, same formulas as the preview | FE `…/ChecklistResponses.tsx:808-809`; `backend/iig_checklist/calculation_registry.py:221-397` |
| FDA-derived default (IID potency, MDE, route) | IID, **stored but the value is not shown**: the screen says only "FDA-derived default. Server-owned and not editable here." | FE `…/ChecklistResponses.tsx:811-814`; `iig_checklist/services.py:674-693` |
| Gap analysis counts and per-question status | CALC: N/A → not applicable; applicability needs review → review; no answer → unanswered; "no" → gap; else no gap | FE `…/GapAnalysis.tsx:363-474`; `iig_checklist/gap_analysis.py:245-316` |

**Source and release date:** no fetched value on any of these screens shows the FDA file name or its publication date. The release record has `publication_date` (`backend/fda_data/models.py:124`), but nothing displays it, and for both FDA releases in our data it is empty.

## 2. What the Orange Book does not give, and where the user types it instead

- **No formula and no excipient amounts:** the Orange Book lists products, applications, strengths and RLD/RS flags only.
- **The user types every component** (name, type, amount, unit, meaning), the total weight and the maximum units per day, on the version page (FE `…/versions/[versionPublicId]/page.tsx:239-335`).
- **The proposed strength** is accepted by the API (`formulations/serializers.py:62-65`) but has no field on the screen.
- **Uploads do not fill fields.** Documents can be uploaded on the Documents page, but no formulation or IID code imports or reads the documents app (searched `backend/formulations/` and `backend/iid_assessment/`), so an uploaded formula has to be typed in again.

## 3. Why all 48,761 Orange Book products say `review_required` for strength, even "10MG"

**This is a side effect of a deliberate choice, not a review queue, and the label misleads.** How it happens:
1. The strength text is parsed. "100MG" gives amount 100 and unit text "MG" (`backend/fda_data/terminology.py:41-53`). That works: 26,331 products have an amount, including all three COZAAR rows (25, 50, 100).
2. `PARSED` also needs the unit text to be found in the controlled-unit list. `lookup_unit` only searches units with `active=True` (`terminology.py:81-99`). Otherwise the status is set to `REVIEW_REQUIRED` (`backend/fda_data/importer.py:313-339`).
3. `ControlledUnit.active` is left `False` **on purpose**: setting it would let the old IID matching path bypass the newer family-and-basis rule (`backend/fda_data/controlled_units.py:20-24`). On the test database: 2 units, 0 active, 0 products with a unit.
4. Nothing ever changes `strength_parse_status` after import. The only writer is `importer.py:335`.

So no reviewer will ever clear these. They will stay `review_required` until the unit lookup is changed or the data is re-imported with it.

**Practical effect today: none.** No formulation, IID or checklist code reads `strength_amount` or `strength_parse_status`; they appear only on the Orange Book detail page. **FLAG FOR REVIEWER:** decide whether the label should say "unit not linked", or whether strengths should link to the reviewed unit list.

## 4. Which IID dosage form REGX matched for each excipient

**How matching works:**
- REGX matches the dosage form **exactly** as entered: no family substitution, and "TABLET" never finds "TABLET, FILM COATED" records (`backend/iid_assessment/matching.py:79-85`).
- Each IID raw form is linked to one controlled form only through an approved mapping (`backend/fda_data/terminology.py:58-78`).

| Excipient (SAMPLE amount) | Entered TABLET, FILM COATED → matched | Entered TABLET → matched | Correct? |
|---|---|---|---|
| Microcrystalline cellulose (120 mg) | TABLET, FILM COATED (daily max 992 mg) | TABLET (6184 mg) | **FLAG FOR REVIEWER** |
| Lactose monohydrate (60 mg) | TABLET, FILM COATED (968 mg) | TABLET (4384 mg) | **FLAG FOR REVIEWER** |
| Magnesium stearate (4 mg) | TABLET, FILM COATED (96 mg) | TABLET (980 mg) | **FLAG FOR REVIEWER** |
| Hypromellose 2910 (6 mPa·s) (6 mg) | TABLET, FILM COATED (345 mg) | TABLET (880 mg) | **FLAG FOR REVIEWER** |
| Titanium dioxide (2 mg) | TABLET, FILM COATED (36 mg) | TABLET (232 mg) | **FLAG FOR REVIEWER** |
| Polyethylene glycol 3350 (1.5 mg) | TABLET, FILM COATED (20 mg per unit) | TABLET (daily max 52 mg) | **FLAG FOR REVIEWER** |

**Why every row is flagged:**
- REGX matched exactly what was typed each time, so the matching itself is right.
- What is unclear is **which entry should be typed**. The Orange Book lists COZAAR as "TABLET", but the tablet is film-coated, and the IID values differ a lot between the two entries (for example magnesium stearate: 96 mg against 980 mg).
- The reviewer must say which IID dosage form applies to a film-coated tablet, and whether core and coat excipients use the same entry.

**The formulation path has its own problem:**
- It passes the product's free-text route and form straight in as codes (`backend/iid_assessment/services.py:182-205`).
- The controlled codes are NCI codes, such as `C42931` for TABLET, FILM COATED.
- So a product typed "ORAL" / "TABLET, FILM COATED" will not match unless the codes themselves are typed. Only the preview screen turns a name into a code (FE `preview/page.tsx:253-259`).
- **FLAG FOR REVIEWER / developer:** this has not been tested through the checklist on the stack.

## 5. What the IID and the Orange Book cannot do

**The IID** gives, for each ingredient, route and dosage form, either a highest amount per dosage unit or a highest daily exposure seen in approved products.
- **No row in the July 2026 file has both** (F-3). For this film-coated tablet, five of the six excipients have only a daily maximum. That is the common shape for core excipients in oral tablets: 401 of 852 ORAL / TABLET rows have only a daily maximum.
- **Until the per-day rule (Q8) is decided,** REGX cannot compare those at all, and a within-limit per-unit result can never be "within precedent", only "review required".
- **It is precedent, not safety.** The IID does not say an amount is safe or acceptable, does not cover excipients never used in an approved product, gives no values per strength or per patient group, and its dosage-form split (TABLET vs TABLET, FILM COATED) needs human judgement.

**The Orange Book** says which approved products exist, who holds them, their strength as text, and which is the RLD and the RS.
- **No formulation:** no excipients, no amounts, no tablet weight, no coating.
- **Sometimes it is not the user's product:** it lists over-the-counter monograph products (such as plain paracetamol) not at all, and gives some strengths as salt-equivalent text ("EQ 10MG BASE") that REGX does not turn into a number.
- **Its dosage form can differ from the product as made:** COZAAR is listed as "TABLET" although the tablet is film-coated.
- **It cannot confirm a generic's formula matches the RLD.** That needs the RLD label, or the applicant's own data, typed or uploaded by the user.
