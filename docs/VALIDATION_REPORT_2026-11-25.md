# Validation report, 2026-11-25: full browser regression

Report only. No product code was changed for this report. The dependency fixes of the same session are a separate PR ([#164](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/164)); section 7 has their results.

## 1. How it was run

- **Code under test:** `regx-main@987c6bc` (#157 to #163 and #161 merged). PR #164 is **not** in this stack.
- **Stack:** a new compose project `regx-v25` with fresh volumes, built from that commit, migrated, and seeded with `seed_regx_demo`.
- **Users:** the four demo users (`doer`, `reviewer`, `vp`, `tenant_admin` `@demo.regx.invalid`).
  - Reviewer, VP and Tenant Admin were enrolled in MFA (TOTP) before testing.
  - The Doer was enrolled during the test (section 3, MFA flow).
- **Data: public FDA files only, loaded as in the 19 Nov validation:**
  - SPL route and dosage-form lists;
  - the REGX controlled-units list;
  - IID July 2026 (`IIR_OCOMM.csv`, 9,071 rows);
  - Orange Book `EOBZIP_2026_08` (48,761 products).
- **Approvals:** every release went import → validate → submit-review → approve → activate.
  - 184 route, dosage-form and unit mappings were approved.
  - All approvals were **LOCAL TEST approvals** by the demo Reviewer and VP.
  - The 67 IID rows with the plain form `DROPS` stay unmapped, as decided.
- **Test files:** five tiny synthetic files, each marked "QA synthetic, not client data":
  - a text PDF;
  - an image-only PDF;
  - a .docx;
  - a text file renamed .pdf;
  - a fake .exe.
- No client data was used.
- **Browser:** real Chromium (Playwright 1.61) at 1280×800, plus one pass at 375×812.
  - Every step clicks and types in the page, the way a user would.
  - Each step saves a screenshot and, where useful, the API response it caused.
  - The desktop app's browser pane was hidden for this session, so it could not be used. The Playwright scripts are session tools and are not committed.
- **The front end and port 8080:** the front-end image is built with the API at `http://localhost:8080`. A local port forward (8080 → the stack's 28080) let the browser use that origin.
- **No paid AI calls:** `OPENAI_API_KEY` was checked absent in both the company_site and backend containers before any page was opened.
- **Baseline check:** the 40 GPT blind-test cases on this stack give **37/37**, with no outcome changed from the first run. The same was true after the IID re-import in section 3.
- **Evidence:** in `D:/Praverse/session-work/2026-11-25/`.
  - `regress/shots/` holds 171 screenshots, named below without the `.png` extension.
  - `regress/out/` holds the step log `all_notes.log`, the API responses and the accessibility dumps.
  - `evidence/` holds the API probes, the re-import log and the GPT runs.
  - All of it is in the session hand-off.
  - No screenshot shows an MFA secret or a recovery code.

## 2. Summary

| | Fixed | Partly fixed | Still present | Not testable here | Total |
|---|---:|---:|---:|---:|---:|
| 18 Nov browser report (`docs/QA_BROWSER_TEST_2026-11-18.md`) | 8 | 5 | 15 | 0 | 28 |
| Codex QA (`docs/qa/QA_CODEX_REPORT.md`) | 12 | 1 | 0 | 6 | 19 |
| **New issues found today** | | | 10 | | 10 |

- **The 18 Nov blocker is gone.** A formulation created and approved in the browser today could have the IIG checklist run on it (QA-01).
- **Main flows that pass end to end:**
  - formulation approval by two users;
  - checklist version lifecycle with an effective date;
  - checklist execution round trip with return and resubmit;
  - the controlled export (API);
  - Orange Book search and reference selection;
  - Reviewer upload;
  - MFA enrol, verify and recovery code;
  - sign-out.
- **Still open, most important:**
  - irreversible actions still run on one click (QA-11: one click superseded an approved execution);
  - draft components cannot be edited or deleted (QA-04);
  - the phone layout (QA-09);
  - raw field names in error messages (QA-12).
- **New, most important:**
  - a checklist definition created in the UI can never be executed;
  - checklist content and the effective date cannot be entered in the UI at all;
  - a checklist version with no questions can be approved and activated;
  - the IID preview silently replaces a typed unit when a meaning is chosen, which can turn "above" into "at or below".
- **Speed:** every page loaded in under 2.2 s for every role. Most took 0.6–0.8 s; Terminology Mappings took about 2.1 s for Reviewer and VP.

## 3. Flows run

| Flow | Result | Evidence |
|---|---|---|
| Sign in as each role (MFA code for Reviewer/VP/Tenant Admin); every sidebar page | Pass | `p_<role>_*`, `01_pages.log` |
| Product → version (−5, 0.5, 0, 1001 units/day and letters refused) → components | Pass (refusals correct; see QA-12 wording) | `f_version_*`, `f_comp_*`, `evidence/api_probes.txt` |
| **Formulation approval by two users:** Doer submits; Doer cannot approve (no button; API 403); Reviewer sees Return/Reject only; VP approves with a note | **Pass**. History shows "approved (internal)" by the VP | `f_submitted_doer_view`, `f_submitted_reviewer_view`, `f_vp_approve_dialog`, `f_approved_vp_view`, `f_self_approve_api.json` |
| **Run the IIG checklist on that new version** | **Pass** (execution 201) | `e_page_draft`, `e_create.json` |
| **Checklist version create / submit / approve / activate with an effective date** | **Pass**, but the date and the questions had to be entered through the API (new issue N-1). v2 superseded v1 on activation. | `c_C_*`, `c_v2_*`, `c_B_version.json`, `c_v2_content.json` |
| Checklist execution: submit unanswered (refused: "Response required for question Q1."); answer; submit; Reviewer return (reason required); Doer sees the reason, resubmits; VP approves | Pass | `e_*`, `e2_*`, `e3_submit_unanswered` |
| **Controlled export** (approved execution) | **Pass:** VP 200, 1,462 bytes, `X-Regx-Export-Checksum` header; Doer 403 `export_permission_denied`; exactly **one** `iig_checklist.execution.exported` audit record; the refused 403 and 409 attempts wrote none. No export button in the UI (N-10). | `e2_export_vp.json`, `e2_export_doer.json` |
| **Orange Book search** by trade name (AMZEEQ), N212379, 212379 and NDA212379 (1 result each); by ingredient (131) | **Pass** | `o_search_*` |
| **Reference product** picked from the search results (AMZEEQ), and by typing "N212379" on a second product | **Pass** (both 200; product page shows Application 212379-001, the selector and the justification) | `o_ref_results_*`, `o_ref_selected_*` |
| **Reviewer document upload** | **Pass** (201). VP is still refused, as decided. | `d_reviewer_qa_text_pdf`, `d_vp_qa_text_pdf` |
| Doer uploads: text PDF, image-only PDF (warning on the detail page), .docx typed as PDF (accepted, see QA-20), renamed text file and .exe (refused) | Pass except QA-20 | `d_doer_*`, `d_list_after`, `d_image_only_detail` |
| **MFA (Doer):** enrol; wrong code refused; correct code turns MFA on; sign out; wrong code at sign-in; sign in with a recovery code; re-using that code refused ("Invalid or already-used recovery code."); TOTP sign-in | **Pass** | `m_signed_out`, `m_signin_wrong_code`; audit rows: enrolment started, activated, recovery code used (counts only) |
| **Sign out** (all roles have the button) | **Pass:** goes to /signin; `/auth/me` is 403 afterwards | `m_signed_out` |
| IID preview: ACACIA/ORAL/TABLET 77 mg above 70 mg; invalid amounts; late response; no-match reasons | Pass except N-3 and QA-15 | `i_*` |
| Deliberate IID re-import (same public file, governed path) so the first release becomes superseded; preview against it | Pass: `RELEASE_NOT_ACTIVE` naming the active release; GPT 37/37 afterwards | `evidence/qa14_reimport.txt` |

## 4. The 28 issues of 18 November

| QA | Status | Evidence (screenshot or response) |
|---|---|---|
| QA-01 No way to run the checklist on a new formulation | **Fixed** | Version approved by the VP in the browser, then an execution created on it: 201 (`f_approved_vp_view`, `e_create.json`) |
| QA-02 Free-text unit; mismatched units accepted | **Fixed** | Unit is a list (mg, g, kg, µg, mL, L, %). API: "furlongs" → 400 "Choose a unit from the list…"; typed "% w/w" 150 → 400 "A percentage cannot be more than 100"; mg/5mL on a tablet → 400 (`f_comp_mg5ml_on_tablet`, `f_comp_pct150_ww`, `api_probes.txt`) |
| QA-03 Negative units/day accepted | **Fixed** | Browser: field min 1, max 1000. API: −5, 0.5, 0 → 400 "must be at least 1"; 1001 → 400 (`f_version_neg5`, `api_probes.txt`) |
| QA-04 Components and versions cannot be edited or deleted | **Still present** | No action on any component row of a draft version (`f_version_components`) |
| QA-05 Old IID result stays under an error | **Fixed** | Amount 0, −1, "12,5", 20 digits and empty: the 77 mg result is cleared each time (`i_qa05_*`) |
| QA-06 Misleading no-comparison reasons | **Fixed** | DROPS: "Dosage form not yet mapped by a reviewer". PER OS: "'PER OS' is not a recognised route. Choose a route from the list (for example ORAL)". Unknown ingredient: "Ingredient not found in the active IID release". "Q8" no longer shown (`i_qa06_*`) |
| QA-07 Reference-data state invisible | **Fixed** (the fresh-install part was not re-tested: the stack is loaded) | The preview pre-fills the active release and carries `release_health` (67 unlinked rows). The releases list explains the counts: "9,071 rows read · 0 imported without a flag, 9,071 flagged for review · 67 not linked to a route or dosage form" (`x_releases_vp`) |
| QA-08 No sign-out, no "who am I", no MFA link | **Partly fixed** | Sign out exists for every role and works. Still no name, role or organisation in the shell, and no link to MFA settings (`01_pages.log`, shell lines) |
| QA-09 Phone width unusable | **Still present** | 375×812: the Documents heading starts at 1,668 px; after "Collapse sidebar" at 1,918 px; IID preview at 1,661 px (`x_phone_*`) |
| QA-10 Session ended mid-task: technical message, no way back | **Still present** | "Authentication credentials were not provided." No sign-in link. The typed values are kept (`s_qa10_session_ended`) |
| QA-11 Irreversible actions on one click | **Still present** | VP clicked **Supersede** on an approved execution: no confirmation, and the execution became `superseded` (synthetic data; `e_vp_supersede_after`). The Reviewer is offered only Return on a submitted execution |
| QA-12 Internal field names in errors | **Still present** | "non_field_errors: Invalid credentials." on sign-in (`s_signin_wrong_password`); "total_dosage_unit_weight: A valid number is required."; "quantity_per_dosage_unit: quantity_per_dosage_unit must be greater than zero."; "File signature does not match declared content type." Cause: `frontend/src/lib/api.ts:67-71` prefixes every message with its field key |
| QA-13 Actions shown that the role cannot do | **Partly fixed** | Fixed: VP no longer sees "New product record"; the Doer sees no Approve on their own formulation version. Still: the Doer sees Approve/Reject/Return on the checklist version they submitted, and Approve gives "You do not have permission…" (`c_v2_doer_approve_result`). On a returned execution the Reviewer can still type answers, and Save says "This response is owned by the server and cannot be edited." (`e_returned_reviewer`) |
| QA-14 Reviewer upload fails with "Upload failed" | **Partly fixed** | Reviewer upload works (201). The VP (refused by decision) still sees the button and gets only "Upload failed" (`d_vp_qa_text_pdf`) |
| QA-15 Numbers without units, raw tokens | **Still present** | "30.800 percent_w_w", "110.000 percent_of_potency", "Difference from IID potency −7.000000" (no unit, negative = over), "MDE UNAVAILABLE", six decimals everywhere; `DATA_REQUIRED` shown raw on the below-limit result (`i_acacia_77`, `i_qa06_below_limit`) |
| QA-16 Execution screen shows internal values | **Still present** | "Status submitted_for_review", "Submitted at 2026-11-25T06:25:49.035492Z", formulation version as a UUID. The New Execution form now has pickers, but the two raw "… Public ID" boxes remain (`e_page_draft`, `e2_after_answer`) |
| QA-17 Dashboard empty | **Still present** | "Welcome to RegX. Select a workflow item from the sidebar." (`x_dashboard_doer`) |
| QA-18 Tenant Admin has no admin screens | **Still present** | Same sidebar as the Doer's (`p_tenant_admin_nav.json`) |
| QA-19 Rough edges in MFA | **Partly fixed** | Fixed: the wrong-code message now sits above the code box, on screen ("Invalid code.", `m_signin_wrong_code`). Still: no QR code; wording "two-step sign-in" vs "Two-factor authentication" / "OTP Code"; recovery box placeholder "000000"; the API message still says "Set it up at /mfa/setup" (`backend/authorization/mfa_policy.py:29`) |
| QA-20 Upload details | **Still present** | A .docx with type left at PDF is stored and listed as PDF; the image-only warning shows on the detail page only, the list says "ready" (`d_list_after`, `d_image_only_detail`). Auto-refresh of "Processing…" not re-tested |
| QA-21 Home page leads to legacy tools | **Still present** | "RegX" and "Explore RegX" → `/ratools/`; "Request access" → `/ratools/requestdemo` (`frontend/src/app/signin/page.tsx:55`); the sidebar still lists the legacy items (`p_home`, `p_signin`) |
| QA-22 Version screen details | **Still present** | "% w/w CALCULATED" says "not yet calculated" for mass rows; the add-component form keeps the previous row's unit **and meaning** (see N-6) (`f_version_components`) |
| QA-23 Fields without accessible labels | **Fixed** | axe (WCAG 2 A/AA) on New product, Create version, Upload and IID preview: 0 violations (`x_axe_*.json`) |
| QA-24 Wording near approval states | **Partly fixed** | The formulation version now shows "Approved (internal)". The product list ("approved") and the execution page ("Status approved") still show the bare word |
| QA-25 Long names | **Still present** | 300-character name: heading scrollWidth 7,078 px in an 868 px box; product table 3,260 px wide (`x_long_name_*`) |
| QA-26 "DEMO-Tenant (demo) (demo) — active" | **Still present** | Tenants page (`p_doer__tenants`) |
| QA-27 Execution page unstyled | **Still present** | Browser-default buttons (grey, square corners) (`x_execution_styling`) |
| QA-28 Stale error stays after the fix | **Fixed** | After answering Q1 and saving, no error remains (`e2_after_answer`) |

## 5. The 19 Codex findings

| QA | Status | Evidence |
|---|---|---|
| QA-01 Definition authoring dropped the execution scope | **Fixed** (API) | Create with `execution_scope=formulation_version` → 201, stored; executions start. The UI form still cannot set it: N-1 |
| QA-02 Built-in calculations rejected mg / g / µg spellings | **Not re-tested live** | It needs a component-scoped checklist with registry bindings and their upstream questions, which the UI cannot author. Covered by the backend tests of #140 and #150, part of the full suite that passed (4,970) in #164's local CI |
| QA-03 A late response repopulated a stale result | **Fixed** | 2.5 s delay injected; amount changed from 77 to 35 while pending: the 77 mg result was not shown (`i_codex_qa03_late_response`) |
| QA-04 Conflicting quantity fields changed the verdict | **Partly fixed** | API: "gram" with the "mg per dose unit" meaning → 400 "the amount must be entered in 'mg'…" (`i_qa04_api_gram_with_mg_meaning.json`). In the browser the same entry still gives the wrong verdict: N-3 |
| QA-05 Reviewer uploads denied | **Fixed** | 201 (`d_reviewer_qa_text_pdf.json`) |
| QA-06 Effective date dropped; activation-only checks | **Fixed** (API) | Create with `effective_date` → stored; submit without it → 400 "effective_date is required before submitting for review." The browser shows only "Request failed" (N-5), and offers no date field (N-1) |
| QA-07 Units/day below 1 | **Fixed** | 0.5 → 400 (browser and API) |
| QA-08 Concurrent formulation approvals | **Not testable in a browser** (needs two simultaneous transactions) | Fixed by #159; its two-connection tests passed in the full suite. Sequential case today: one approved version |
| QA-09 Governed writes and audit committing separately | **Not testable in a browser** (needs injected audit failures) | Fixed by #160/#162/#163; fault-injection tests in the suite. Live: the export wrote its one record; MFA steps wrote theirs |
| QA-10 Non-atomic fingerprint dedupe | **Not testable in a browser** (needs concurrent imports) | Fixed by #158; tests in the suite. The governed deliberate re-import works (`qa14_reimport.txt`) |
| QA-11 Numeric approval note → 500 | **Fixed** | 400 "Enter this as text." (`f_numeric_note_api.json`) |
| QA-12 Orange Book UI missed trade-name / application-number search | **Fixed** | Both fields present and working (`o_search_*`) |
| QA-13 Result panel did not name its release | **Fixed** | Result panel shows "release: 2e0860c7-…" (`i_acacia_77`) |
| QA-14 Superseded release: misleading reason | **Fixed** | "The chosen IID release is not the active release … Choose the active IID release (2247adc0-…) instead." (`qa14_reimport.txt`) |
| QA-15 No sign-out | **Fixed** | Sign out button for every role; session ends |
| QA-16 First "Select this precedent" click sent the old selection | **Fixed in code; not reproducible live** | No IID July 2026 ingredient has two exact candidates for one route and form, and Codex used a synthetic fixture. The click now passes its row directly (`frontend/src/app/(regx)/iid-assessments/preview/page.tsx:262-290`) |
| QA-17 Unbuilt patent/exclusivity types offered | **Fixed** | Options: orange_book_products, orange_book_discontinued, fda_iid, fda_substance_identifiers, route and dosage-form terminology |
| QA-18 Review stamps mutable under review (DB) | **Not testable in a browser** (direct SQL) | Fixed by #157; its SQL tests in the suite |
| QA-19 Per-volume on POWDER / GRANULE | **Fixed** | POWDER, GRANULE, CAPSULE + mg/5mL → 400; POWDER, FOR SOLUTION → 201, as intended (`api_probes.txt`) |

## 6. New issues (not fixed in this PR)

| # | Severity | Issue | Steps | Expected | Actual | Where |
|---|---|---|---|---|---|---|
| N-1 | Major | **Checklist authoring has no UI, and a definition created in the UI can never be executed** | Doer: New definition → Create → Create new version → open v1 | A way to set the execution scope, the effective date, and to add sections and questions | The definition form has no scope field, so it is saved with `execution_scope: ""` (`c_definition_create.json`). An execution against it is refused `execution_scope_unclassified`. The version page offers only Submit for review and Retire; no date, no sections, no questions. Today's checklist had to be authored through the API | `frontend/src/app/(regx)/iig-checklists/new/page.tsx`, `…/versions/[versionPublicId]/page.tsx`; refusal at `backend/iig_checklist/views.py:1123` |
| N-2 | Major | **A checklist version with no questions can be submitted, approved and activated** | Version with an effective date and no sections → submit → VP approve → activate | Refused: nothing to execute | All three succeeded; the empty version became active, and would supersede a real one (`c_C_active`: "No sections defined yet." with status active) | The prerequisite check covers the date and calculation bindings only: `backend/iig_checklist/views.py:486-509` |
| N-3 | Major | **IID preview: choosing a meaning silently replaces the typed unit** (Codex QA-04 through the browser) | ACACIA/ORAL/TABLET, amount 0.077, unit "gram", then meaning "mg per dose unit"; Run preview | Refused, or a visible warning that the unit changed | The unit box changes to "mg" with no notice. The preview compares 0.077 mg with 70 mg: "at_or_below" instead of "above" (`i_codex_qa04.json`, `i_qa04_unit_after_meaning`) | `frontend/src/app/(regx)/iid-assessments/preview/page.tsx:397-398` |
| N-4 | Minor | Checklist version page always says "not yet submitted / approved / activated" | Open an active version | Who submitted, approved and activated it | All three show "not yet …" after activation (`c_v2_active`) | The page reads `submitted_by_email` etc. (`…/versions/[versionPublicId]/page.tsx:113-119`), which `ChecklistVersionSerializer` (`backend/iig_checklist/serializers.py:65`) never returns |
| N-5 | Minor | Errors returned as a list show as "Request failed" | Submit a checklist version without an effective date | "Effective date is required before submitting for review." | "Request failed" (server body: `{"detail": ["effective_date is required…"]}`, `evidence/checklist_submit_no_date_api.txt`) | `frontend/src/lib/api.ts:59-64` reads only a string or an object `detail` |
| N-6 | Minor | The add-component form keeps the previous meaning (and unit) | Add a %w/w component (refused at 150), Cancel, then add "10 %" without touching the meaning | The meaning resets to "Per dosage unit" | The new row silently gets %w/w and is saved (`f_comp_pct_no_meaning`). The API alone would refuse a % without a basis (`api_probes.txt`) | `frontend/src/app/(regx)/formulations/[publicId]/versions/[versionPublicId]/page.tsx:48`, `:99` |
| N-7 | Minor | Opening a page directly while signed out shows contradictory messages | Signed out, open `/documents?tenant=demo` | Redirect to sign-in (as a sidebar click does) | Shell with "Upload document", "Failed to load documents." and "No documents yet. Upload one to get started." No data is shown: every API call is 403 (`s_signed_out_documents_main`) | `frontend/src/app/(regx)/documents/page.tsx:87`, `:148` |
| N-8 | Minor | MFA recovery codes are shown before the first code is verified | Start setup, then leave | Codes shown once MFA is on | Ten codes are listed at step 2, before "Turn on MFA" | `frontend/src/app/mfa/setup/page.tsx:35`, `:109` |
| N-9 | Minor | A reference product chosen by a Doer is labelled "REVIEWER CONFIRMED" | Doer selects a reference product | A label that matches who confirmed it | "Selected by doer@… REVIEWER CONFIRMED" (`o_ref_selected_*`) | `frontend/src/app/(regx)/formulations/[publicId]/page.tsx:174` |
| N-10 | Minor | The controlled export has no UI | Open an approved execution as the VP | An export action | None; only `GET …/executions/<id>/export/` | Execution page |

## 7. Dependency results (PR #164)

| Area | Before | After | Left for the owner |
|---|---|---|---|
| Frontend (npm audit) | 16 (3 critical, 6 high, 7 moderate) | 3 (2 critical, 1 moderate) | vitest 3 → 5 (clears tinypool and @vitest/mocker; dev-only) |
| Backend `base.txt` (pip-audit) | 0 | 0 | — |
| Backend `dev.txt` | 1 (pytest 8.3.5) | 1 | pytest 8 → 9 (dev-only) |
| company_site lock | 89 | 57 | Django 5.1 → 5.2 LTS (5.1 is out of support), DRF 3.18, Pillow 13, PyPDF2 → pypdf |

- **Fixed in #164:**
  - next 15.5.27 → 15.5.29, which clears the image-optimizer RCE, the Server Actions DoS, the edge HttpOnly header exposure, the SVG bypass and the response-injection advisories;
  - `npm audit fix` without `--force`;
  - an npm override pinning postcss to 8.5.33;
  - company_site: Django 5.1.15, simplejwt 5.5.1 and certifi, with the lock regenerated with hashes.
- **Local CI for #164, all passed:**
  - backend job: 4,970 passed, 2 skipped;
  - backend lock check;
  - frontend job: type check, lint, 645 unit tests, build, 271 Playwright;
  - 20 integrated Playwright;
  - company_site lock check and 52 smoke tests;
  - Docker integration job;
  - GPT cases: 37/37.
- **Not merged yet:** #164 is waiting for the owner.

## 8. Still blocked on client input

- **SOW 2.3 calculators (dissolution, impurity, stability trend):**
  - not built;
  - formulas, units, rounding and worked examples are needed first (`docs/CALCULATOR_SPECIFICATION_INTAKE.md`);
  - no calculator code exists in `backend/` or `frontend/src`.
- **IIG checklist content:**
  - the 20-item content gate is still **0 of 20 approved** (`docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md`);
  - iCretegy's 2026-11-16 checklists are site-audit checklists, not IIG content (§11 item 29);
  - only the `DEMO-` definition and today's synthetic test definitions exist.
- **F-3, the potency vs daily-maximum gap (confirmed again today):**
  - no IID July 2026 row has both a potency and a maximum daily exposure;
  - so a result within the potency limit is always "Review required" ("maximum daily exposure precedent is unavailable", `i_qa06_below_limit`);
  - "Pass with IID precedent" can never occur on real data, and formulas E/F never run;
  - it depends on the per-day rule (Q8), still with iCretegy and the regulatory reviewer.

## 9. Open reviewer questions (PROJECT_OVERVIEW §12)

1. **Half-tablet dosing.** "Maximum dosage units/day" must be at least 1 (QA-07, #141), so 0.5 units a day is refused. Today's browser and API runs confirm this. The options are:
   - keep at least 1;
   - allow fractions above 0 with a floor such as 0.25;
   - allow any value above 0.
2. **m/m and m/v as percentage bases.** Since #139, "% m/m" reads as %w/w and "% m/v" as %w/v. Should only the w-spellings be accepted?
3. **Still open from the 19 Nov report:**
   - the rule decisions behind GPT cases T031, T032 and T040;
   - the `DROPS` per-record approach, pending the regulatory reviewer's confirmation;
   - the INJECTION route rule, pending iCretegy.

## 10. Not tested, and why

- **Codex QA-02, QA-08, QA-09, QA-10, QA-18:** they need concurrency, fault injection, direct SQL or registry-bound checklists. They are covered by the backend suite (section 5).
- **Codex QA-16 live:** no public IID data has two exact candidates.
- **QA-07 fresh-install state:** the stack was loaded first, by design of this run.
- **QA-20 auto-refresh of "Processing…":** the scan finished before the page was opened.
- **Checklist version Reject confirmation:** only the execution Supersede and Reject paths were exercised.
- **Cross-tenant IDs:** the demo has one organisation.
- **The real 8-hour expiry:** simulated with a sign-out from a second tab.
- **The real OS file picker:** files were attached to the file input directly.
- **Screen readers and keyboard-only use:** only the axe scan was run.
- **Legacy company_site pages:** only the "Audit IQ" sidebar link was opened, with no OpenAI key present.
