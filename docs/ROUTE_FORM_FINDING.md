# Route and dosage form: does the IID check from a formulation work? (2026-11-27)

**Answer: no.** The IID check run from a formulation (through an IIG checklist) never reaches an IID row. There are three reasons, and the first alone is enough to break it:
1. **REGX sends the wrong kind of value.** The product stores the route and dosage form as the text the user typed ("ORAL", "TABLET, FILM COATED"). The formulation path hands that text to the IID check as if it were a **code**. The IID check only accepts controlled codes (for example `C38288` for ORAL, `C42931` for TABLET, FILM COATED), so it finds no route, and the matcher stops with **"route mismatch"** before looking at any IID row.
2. **The screen cannot start the check.** The IID check runs only for a checklist execution about one ingredient (a "subject component"). The new-execution screen has no field for that ingredient, so the server refuses the request.
3. **No checklist asks for it.** No checklist in the system is set up per ingredient (all are per formulation version), and the authoring screen cannot set this (N-1).

**When the run reached the IID check through the API anyway** (reasons 2 and 3 worked around):
- The result was "not comparable" with a self-contradicting message: **"'ORAL' is not a recognised route. Choose a route from the list (for example ORAL)."**
- The three IID-derived answers on the checklist stayed **empty**, and the screen shows no sign that anything failed.

**With the right codes, the same request matches:** magnesium stearate, ORAL, TABLET, FILM COATED gives an IID row with a daily maximum of 96 mg. The data is there; REGX doesn't turn the typed text into a code on this path. The IID preview screen does convert text to codes (FE `iid-assessments/preview/page.tsx:253-259`), which is why the preview works and the formulation path does not.

Nothing was fixed. Under Pravis's order of work this is step 1, and until it is fixed REGX must not be shown to the client as working from a formulation (`PROJECT_OVERVIEW.md` §12 item 21).

## How it was tested

- **Stack:** `regx-v25` rebuilt from `regx-main` at 672847a, with public FDA data (IID July 2026, active release `2247adc0-e3fb-4baa-8dd1-8c3c7b613018`) and demo users only.
- **Scripts:** `regress/rfForm.js`, `rfChecklist.js`, `rfUiOnly.js` and `tools/rf_trace2.py`, in the review hand-off with their output. Screenshots are in the hand-off only.

| Step | How | Result |
|---|---|---|
| 1. SAMPLE formulation | **Browser (UI).** Doer creates the product "SAMPLE-RF-LOS100-693123" (losartan potassium, route typed "ORAL", dosage form typed "TABLET, FILM COATED"); selects COZAAR N020386-003 (100 mg, RLD and RS); creates a version (293.5 mg total, 1 unit/day); adds the active and 6 SAMPLE excipients; submits. VP approves | Approved version `7399d2e0-53af-4a94-8669-66276c1d4472` |
| 2. A checklist that runs the IID check | **API.** The authoring screen has no execution-scope field (N-1). Doer creates "SAMPLE – not real checklist content (route/form finding)" with scope `formulation_component`, and three FDA-derived questions bound to `iid.maximum_daily_exposure`, `iid.potency_amount` and `iid.route`. Doer submits; VP approves and activates | Active. A first attempt, made with a missing section field, also activated a version with **no questions**: the empty-version problem (N-2) that #168 fixes, still present on `regx-main` |
| 3. Run it from the screen | **Browser (UI).** New checklist execution: pick the SAMPLE checklist and the SAMPLE formulation version, click "Create execution" | **Refused (HTTP 400 `subject_component_required`).** The screen shows: "This checklist version contains component-specific content, so a governed subject component must be supplied." The page has no way to pick a component: it sends only the two version IDs (FE `iig-checklists/executions/new/page.tsx:77-81`) |
| 4. Run it with an ingredient | **API.** Same request plus `subject_component_public_id` = the version's MAGNESIUM STEARATE component | Execution created (HTTP 201). The IID snapshot was made: **match "ROUTE_MISMATCH", decision "NOT_COMPARABLE"**, note "'ORAL' is not a recognised route. Choose a route from the list (for example ORAL).". **All three IID answers are empty** (`raw_value: null`), and the execution screen shows each one only as "FDA-derived default. Server-owned and not editable here." |
| 5. What reached the matcher | **Trace** in the backend container, calling the same functions for that version and component (read-only) | See the next section |

## What reaches the IID matcher (actual values)

| Where | What happens | Actual value in this run |
|---|---|---|
| Product (what the user typed) | stored as free text | route `'ORAL'`, dosage form `'TABLET, FILM COATED'` |
| `backend/iig_checklist/services.py:499` | execution creation calls `create_assessment_snapshot` for the subject component | component MAGNESIUM STEARATE |
| `backend/iid_assessment/services.py:197-198` | `_controlled_term(product.route)` and `_controlled_term(product.dosage_form)` | — |
| `backend/iid_assessment/services.py:182-191` | `_controlled_term` only trims the text and calls it "resolved" if it is not blank. It never looks the text up | returns `('ORAL', True)` and `('TABLET, FILM COATED', True)` |
| `backend/iid_assessment/services.py:204-205` | passed to `run_preview` as `route_code` and `dosage_form_code` | `route_code='ORAL'`, `dosage_form_code='TABLET, FILM COATED'` |
| `backend/iid_assessment/assess.py:64-67` | `run_preview` looks up `ControlledRoute` / `ControlledDosageForm` **by code** | both lookups return **None**. The real terms are `C38288` "ORAL" and `C42931` "TABLET, FILM COATED", found by their label, not their code |
| `backend/iid_assessment/matching.py:68-71` | `find_iid_candidates` with no route | **ROUTE_MISMATCH**, reason `ROUTE_UNMAPPED_OR_UNCONFIRMED`, **0 candidates** |
| Same matcher, if the text were first turned into codes (`C38288`, `C42931`) | for comparison only | **1 candidate:** MAGNESIUM STEARATE, TABLET, FILM COATED, daily maximum 96 mg (status POTENCY_UNAVAILABLE: a daily maximum only, so it would then stop at the per-day rule Q8) |

## What it means

- **Every IID check started from a formulation fails today.** Three callers go through `create_assessment_snapshot`, which builds its arguments with `_preview_arguments` (`backend/iid_assessment/services.py:281`): the saved-assessment API (`backend/iid_assessment/views.py:163`), checklist execution creation (`backend/iig_checklist/services.py:499`) and the checklist's calculation step (`backend/iig_checklist/calculation_execution.py:384`). It fails whatever the excipient, unless the user typed NCI codes such as `C38288` into the product's route and dosage-form boxes. No user would do that, and the screen doesn't suggest it.
- **The failure is quiet:**
  - The checklist answers stay empty, with no message on the execution screen.
  - The snapshot's note contradicts itself.
  - The code calls the route "resolved" (`services.py:191`) when it is only "not blank".
- **Even after the fix,** this product's core excipients would stop at the per-day rule (Q8): the IID gives only a daily maximum for them (`docs/CALC_MAP_LOSARTAN.md`).

## What a fix would involve (not done; for planning)

1. **Turn text into codes on this path, or store codes.**
   - Either `_controlled_term` looks the text up the way the preview screen does (label or code, exact match only),
   - or the product screen offers a pick-list of controlled routes and dosage forms and stores the code.
   - The second also stops new free text from getting in. Existing products need the lookup or a one-off mapping.
   - Either way, an unknown value must stay refused, never guessed.
2. **Let the new-execution screen pick the ingredient (subject component)** when the checklist needs one.
3. **Show the IID outcome on the execution screen,** including "no IID match" and why, instead of an empty FDA-derived answer.
4. **Make "resolved" mean resolved** (`services.py:191`).
5. **Tests first:** a formulation whose product says "ORAL" / "TABLET, FILM COATED" must reach the IID row (it fails today), and an unknown route must still be refused.

**Rough size:** item 1 with tests is about 1–2 days; items 2–3 about 2–3 days. This is an estimate, not a commitment.
