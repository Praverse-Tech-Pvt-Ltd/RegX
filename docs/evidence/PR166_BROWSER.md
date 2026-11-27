# PR #166 in the browser: old code against the branch

**Owner condition A (2026-11-27).** Exact steps typed, then the screen on the old code (`regx-main`) and on the branch. Screenshots are **not in git**: they are in the review hand-off only, under the file names given here.

**What #166 changes:** choosing a meaning for the quantity must never change the unit the user typed. If the typed unit does not fit the meaning, the preview is refused at the unit field and no comparison is shown.

### Old code (`regx-main`, 4ff74d7)

Stack: `regx-v25` rebuilt from `regx-main` (4ff74d7), origin `http://localhost:8080`, run at 2026-11-27T04:46:41.291Z (UTC).

**Steps, as typed:**

1. Signed in as doer@demo.regx.invalid; opened "/iid-assessments/preview?tenant=demo".
2. Ingredient name: typed "ACACIA".
3. Route code: typed "ORAL".
4. Dosage form code: typed "TABLET".
5. Proposed quantity per unit: typed "0.077".
6. Proposed quantity unit: typed "gram".
7. What the proposed quantity means: picked "mg per dose unit".
8. Total dosage-unit weight: typed "250".
9. Clicked "Run preview".

| What | Result |
|---|---|
| Unit box right after choosing "mg per dose unit" | `mg` |
| Run preview, HTTP status | 200 |
| Message at the unit field | (none) |
| Potency comparison returned | {"comparable": true, "reason_code": null, "reason": "compared like for like (same family and basis)", "result": "at_or_below", "proposed_value": "0.077", "iid_value": "70", "unit": "mg per dose unit", "rounded_for_display": false, "conversion": "none needed", "label": "technically comparable (not regulatorily approved)", "iid_record_public_id": "01148c4e-b039-43a3-aeff-ae25879a0245", "iid_release_public_id": "2247adc0-e3fb-4baa-8dd1-8c3c7b613018", "iid_source_row": {"source_row_locator": "row:55", "ingredient_name": "ACACIA", "route": "ORAL", "dosage_form": "TABLET", "potency_amount": "70", "potency_unit": "mg", "maximum_daily_exposure": "", "maximum_daily_exposure_unit": ""}, "unit_list_release_public_id": "8be16f5f-c518-469a-8271-f0fac43d9a88", "proposed_meaning": "mg per dose unit"} |

**Screenshots:** after choosing the meaning `review-handoff/evidence__shot__evA166_old_1_after_choosing_meaning.png`; after Run preview `review-handoff/evidence__shot__evA166_old_2_after_run_preview.png`.

**Screen text after Run preview** (the page's main area, as rendered):

```text
IID Assessment Preview

Comparing your proposed formulation quantity against a selected FDA IID precedent record. This preview is not a regulatory decision and does not determine safety or approval — see the disclaimer on any "within precedent" result below.

Ingredient name (as listed in the IID) USER INPUT
Ingredient ID (optional, instead of the name)
Active FDA release ID
Route code (name or code, e.g. ORAL)
Dosage form code (name or code, e.g. TABLET)
Proposed quantity per unit
Proposed quantity unit
What the proposed quantity means
Per dosage unit (in the unit entered)
mg per dose unit
mg/0.1mL
mg/0.2mL
mg/1mL
mg/2.5mL
mg/5mL
mg/10mL
mg/15mL
mg/20mL
mg/100mL
mg/120mL
mg/140mL
mg/1000mL
%v/v
%w/v
%w/w
mL per dose unit
mL/1mL
mL/5mL
mL/15mL
Enter the amount in “mg”.
Total dosage-unit weight
Total weight unit
Maximum dosage units/day
Run preview
Match status: Exact match
About the active IID release: 67 of 9,071 records have no route or dosage-form link, so a preview can never match them; for those records a preview says there is no precedent even when the FDA lists one. What to do: 67 have a route or dosage form no reviewer has mapped yet (listed here): propose and approve those mappings on the Terminology Mappings page.
Selected IID precedent FDA SOURCE

ACACIA — 70 milligram potency, MDE UNAVAILABLE MDE

Like-for-like comparison CALCULATED

Proposed 0.077 mg per dose unit is at or below the IID value of 70 mg per dose unit.

Conversion: none needed

technically comparable (not regulatorily approved)

IID source row: row:55

IID release: 2247adc0-e3fb-4baa-8dd1-8c3c7b613018

Calculations
Unit conversion CALCULATED0.077000 mg = 0.077 milligram
Percentage w/w CALCULATED0.031
(exact value 0.030800)
 percent_w_w
Daily exposure CALCULATEDBlocked: DATA_REQUIRED
Percentage of IID potency CALCULATED0.110 percent_of_potency
Difference from IID potency CALCULATED69.923000

Review required

Within selected IID potency precedent, but maximum daily exposure precedent is unavailable for comparison.

Reviewer escalation required before proceeding.
```

### Branch (#166, b978ead)

Stack: `regx-v25` rebuilt from the #166 branch (b978ead), origin `http://localhost:8080`, run at 2026-11-27T04:50:34.640Z (UTC).

**Steps, as typed:**

1. Signed in as doer@demo.regx.invalid; opened "/iid-assessments/preview?tenant=demo".
2. Ingredient name: typed "ACACIA".
3. Route code: typed "ORAL".
4. Dosage form code: typed "TABLET".
5. Proposed quantity per unit: typed "0.077".
6. Proposed quantity unit: typed "gram".
7. What the proposed quantity means: picked "mg per dose unit".
8. Total dosage-unit weight: typed "250".
9. Clicked "Run preview".

| What | Result |
|---|---|
| Unit box right after choosing "mg per dose unit" | `gram` |
| Run preview, HTTP status | 400 |
| Message at the unit field | the amount must be entered in 'mg', the unit this meaning states (got 'gram') |
| Potency comparison returned | (none) |

**Screenshots:** after choosing the meaning `review-handoff/evidence__shot__evA166_branch_1_after_choosing_meaning.png`; after Run preview `review-handoff/evidence__shot__evA166_branch_2_after_run_preview.png`.

**Screen text after Run preview** (the page's main area, as rendered):

```text
IID Assessment Preview

Comparing your proposed formulation quantity against a selected FDA IID precedent record. This preview is not a regulatory decision and does not determine safety or approval — see the disclaimer on any "within precedent" result below.

Ingredient name (as listed in the IID) USER INPUT
Ingredient ID (optional, instead of the name)
Active FDA release ID
Route code (name or code, e.g. ORAL)
Dosage form code (name or code, e.g. TABLET)
Proposed quantity per unit
Proposed quantity unit
the amount must be entered in 'mg', the unit this meaning states (got 'gram')
What the proposed quantity means
Per dosage unit (in the unit entered)
mg per dose unit
mg/0.1mL
mg/0.2mL
mg/1mL
mg/2.5mL
mg/5mL
mg/10mL
mg/15mL
mg/20mL
mg/100mL
mg/120mL
mg/140mL
mg/1000mL
%v/v
%w/v
%w/w
mL per dose unit
mL/1mL
mL/5mL
mL/15mL
Enter the amount in “mg”.
Total dosage-unit weight
Total weight unit
Maximum dosage units/day
Run preview
```
