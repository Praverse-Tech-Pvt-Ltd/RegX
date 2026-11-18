# Hands-on browser test of REGX — 2026-11-18

**What this is:** an exploratory test of REGX in a real browser, done the way a user would: clicking, typing, uploading, switching roles. Nothing was fixed. This report only records what happened.

**Who ran it:** Claude Code (twenty-second session), for the owner.

## How the test was run

- **Code under test:** `regx-main` at `66b32d6` (#132 merged).
- **Stack:** a separate, fresh compose project `regx-qa`, migrated and seeded with `seed_regx_demo`. The dev database was backed up first and restored at the end; it was not used for testing.
- **Browser:** the built-in browser pane of the Claude desktop app. Mostly 1280×800; one pass at phone size (375×812). No Playwright scripts.
- **Users:** the four demo users only (`doer`, `reviewer`, `vp`, `tenant_admin` `@demo.regx.invalid`).
- **Data:** demo seed and synthetic test values only.
  - For the IID previews, the public FDA IID file (July 2026) and the public FDA SPL route and dosage-form pages were loaded with the operator commands.
  - They were taken through the approval chain with **local test approvals**: through the API, not the browser, because that part is operator set-up.
  - No client data was used anywhere.
- **Test files:** five tiny synthetic files, all marked "QA synthetic, not client data":
  - a text PDF;
  - an image-only PDF;
  - a Word file;
  - a text file renamed `.pdf`;
  - a fake `.exe`.

  The browser pane has no operating-system file dialog, so each file was attached to the upload field with a script (a `DataTransfer` object), which is equivalent to choosing it in the dialog.
- **Sign-out:** REGX has no sign-out button (see QA-08). Every role change used the same endpoint a sign-out button would call (`POST /api/regx/v1/auth/logout/`).
- **Screenshots:** in `D:/Praverse/session-work/2026-11-18/qa-browser/`, referenced below by file name. Screenshots of the MFA set-up screens that show a secret key were not kept.

## Summary

| Severity | Count | Meaning |
|---|---|---|
| Blocker | 1 | A main task cannot be finished at all. |
| Major | 10 | Wrong data gets in, a result can be misread, or a common task is very hard. |
| Minor | 13 | Works, but confusing, inconsistent or unhelpful. |
| Cosmetic | 4 | Looks wrong; no effect on the outcome. |
| **Total** | **28** | |

**What worked well**
- **Speed:** every sidebar page loaded in under 0.6 s, and every API call took under 0.5 s. Nothing came near 3 s.
- **Tenant isolation in the URL:**
  - an unknown `?tenant=` gives a clear "No access to this organisation … Nothing from it has been loaded";
  - a `<script>` tag in `?tenant=` is shown as plain text;
  - removing `?tenant=` sends you to the organisation list.
- **MFA:**
  - the gate blocks writes for Reviewer, VP and Tenant Admin, with a clear banner;
  - a wrong code, a valid code, a recovery code, and re-use of a recovery code all behave correctly;
  - sign-in returns you to the page you asked for.
- **Server-side permissions held every time.** Every forbidden action I tried was refused by the server:
  - Doer: approving their own checklist; creating platform-master content;
  - Reviewer: editing the Doer's answers; uploading a document;
  - VP: creating a product;
  - Tenant Admin: superseding.
- **Double-clicks never created duplicates:**
  - Generate analysis;
  - Submit for review;
  - Approve;
  - Create formulation version.
- **Uploads:** `.exe` and a fake PDF were refused, and an image-only PDF was flagged "No extractable text, likely scanned".
- **Special characters:** é, µ, emoji, quotes and `<b>` were stored and shown safely, with no HTML injection.
- **Amount rules from #132:**
  - 900,000 kg is refused, with the converted value in the message;
  - 0 and negative amounts are refused;
  - a 20-digit number is refused;
  - 150 is refused when the meaning is chosen as % w/w.
- **The checklist round trip worked end to end on the seeded formulation:** Doer submits → Reviewer returns with a reason → Doer resubmits → VP approves.
- **Every comparable IID result carried the label** "technically comparable (not regulatorily approved)".

## Issues

Each issue has its page, role, steps, expected and actual result, severity and screenshot.

### Blocker

#### QA-01 — A new formulation can never have the IIG checklist run on it
- **Page / role:** Formulation version → "Run IIG checklist on this version" / Doer
- **Steps:**
  1. Create a product record.
  2. Create a formulation version.
  3. Add components.
  4. Click "Run IIG checklist on this version →".
- **Expected:** a way to send the version for approval, then run the checklist.
- **Actual:**
  - The page says "This formulation version is not approved, so a checklist cannot be run on it yet."
  - No screen and no API approves a formulation version.
  - Only the demo seed's formulation can be checklisted.
  - This is the known gap (§11 item 32). The owner approved Option A on 2026-11-18, and it is not built yet.
- **Severity:** blocker
- **Screenshot:** — (text captured in the session notes)

### Major

#### QA-02 — The component "Unit" is free text: nonsense and mismatched units are accepted
- **Page / role:** Formulation version → Add component / Doer
- **Steps:** on a 250 mg tablet version, add these components, each with "What the quantity means" left at its default ("Per dosage unit"):
  - 150 `furlongs`;
  - 100 `mg/5mL`;
  - 150 `% w/w`.
- **Expected:**
  - an unknown unit is refused;
  - a per-volume unit is refused, or warned about, on a per-dosage-unit tablet line;
  - a percentage over 100 is refused.
- **Actual:**
  - All three were saved: "150.000000 furlongs", "100.000000 mg/5mL", "150.000000 % w/w".
  - "furlongs" was still accepted after the controlled unit list was made active.
  - The 100 % cap only applies when the unit is typed exactly as `%` or `percent`, or when "%w/w" is picked in the meaning list. Typing `% w/w` in the Unit box gets past it.
- **Severity:** major. Wrong data goes straight into the formulation that IID comparisons and checklists read.
- **Screenshot:** `14_components_150pct_ww_and_mg5ml_accepted.jpg`, `12_component_form_one_meaning_only.jpg`

#### QA-03 — A negative "Maximum dosage units/day" is accepted
- **Page / role:** Product record → Create formulation version / Doer
- **Steps:** enter total weight 250 and maximum dosage units/day `-5`, then Create version.
- **Expected:** refused ("must be greater than zero").
- **Actual:** the version was created, and its page says "Maximum -5.0000 dosage units/day".
- **Severity:** major. The daily-exposure calculation uses this value.
- **Screenshot:** `11_version_negative_units_per_day_accepted.jpg`

#### QA-04 — Components and versions cannot be edited or deleted
- **Page / role:** Formulation version / Doer
- **Steps:** add a wrong component (for example the "furlongs" one above), then look for a way to change or remove it.
- **Expected:** edit or delete while the version is a draft.
- **Actual:**
  - Component rows have no actions.
  - The version page has only "Add component", "Add dosing regimen" and the two "Run …" links.
  - A typo stays in the formulation for good, unless the user starts a new product record.
- **Severity:** major
- **Screenshot:** `14_components_150pct_ww_and_mg5ml_accepted.jpg`

#### QA-05 — The IID preview keeps showing the previous result after an invalid entry
- **Page / role:** IID Assessments → Preview / Doer
- **Steps:**
  1. Run a valid preview (ACACIA, ORAL, TABLET, 77 mg): the result says "above".
  2. Change the quantity to `0` (or `-1`, `12,5`, or a 20-digit number) and click Run preview.
- **Expected:** the error is shown and the old result is cleared.
- **Actual:**
  - The error appears ("The amount must be greater than zero.").
  - Below it, the old result stays on screen: "Proposed 77 mg per dose unit is above the IID value …", with its label and calculations.
  - With the quantity left empty, no error is shown at all, and the old result stays.
- **Severity:** major. A user can copy a conclusion that does not belong to the numbers in the form.
- **Screenshot:** `33_iid_preview_stale_result_under_error.jpg`

#### QA-06 — The IID preview's reasons for "no comparison" are misleading
- **Page / role:** IID preview / Doer
- **Steps and results:**
  - **Unmapped dosage form** (ALCOHOL, ORAL, `DROPS`, mg/1mL; the IID has DROPS rows, but they are not mapped):
    - shows "DOSAGE-FORM MISMATCH — DOSAGE_FORM_MISMATCH: route and dosage form must match exactly";
    - the user typed exactly what the IID says.
  - **Route spelling REGX doesn't know** (`PER OS`):
    - shows "ROUTE_MISMATCH: route and dosage form must match exactly";
    - there is no "not a recognised route" message and no suggestion (ORAL).
  - **Ingredient not in the IID** (`SYNTHETIC UNKNOWN EXCIPIENT 123`):
    - shows "Review required — Ingredient identity/synonym mapping requires reviewer confirmation";
    - it never says the ingredient was not found.
  - **Daily-exposure-only record:** "… needs the per-day rule (Q8)". "Q8" is an internal decision-intake number.
- **Expected:** a plain reason a user can act on, for example:
  - "IID rows for DROPS are not yet mapped to a dosage form";
  - "'PER OS' is not a recognised route";
  - "no IID row for this ingredient".
- **Actual:** see the steps above. Raw codes (`DOSAGE_FORM_MISMATCH`) are shown on screen.
- **Severity:** major. In a decision-support screen, a wrong reason sends the user to the wrong fix.
- **Screenshot:** — (screen text recorded in the session notes)

#### QA-07 — Whether the reference data is linked cannot be seen; a fresh install fails silently
- **Page / role:** FDA Data → Releases; IID preview; Add component / Doer and VP
- **Steps:**
  1. On a fresh install, open IID preview and Add component.
  2. Load the IID file before the route and dosage-form mappings are approved, then activate it.
  3. Run any preview.
- **Expected:**
  - the screen says that no IID release, or no unit list, is active;
  - an active IID release whose rows have no route or dosage-form links is flagged.
- **Actual:**
  - **Fresh install:**
    - the preview asks the user to type an "Active FDA release ID" (a UUID) by hand;
    - "What the quantity means" offers only "Per dosage unit";
    - nothing says why.
  - **IID loaded before the mappings:**
    - the release is ACTIVE, showing "Records 0/9071";
    - **every** preview returns "No exact ingredient/route/dosage-form IID precedent record exists", with no hint that the cause is missing links;
    - the fix (`reresolve_terminology`) only works before the release is submitted. It needed a re-import, and the duplicate-file guard refused the identical file.
  - **After the fix:** the release shows "3748/9071", and that count is not explained.
- **Severity:** major. A user cannot tell "the FDA has no precedent" from "our reference data is not linked".
- **Screenshot:** `08_iid_preview_form.jpg`, `12_component_form_one_meaning_only.jpg`

#### QA-08 — No sign-out, no "who am I", no link to MFA settings
- **Page / role:** every REGX page / all roles
- **Steps:** sign in, then look for sign-out, the current user's name or role, or MFA settings.
- **Expected:** a user menu with name, role, organisation, "Two-step sign-in" and "Sign out".
- **Actual:**
  - None of these exist.
  - The header is the company-site navigation ("Audit IQ", "ANDA CTD SmartTemplate", "RegX", "Schedule Consultation").
  - The only way to sign out is to wait for the 8-hour session to end.
  - Optional MFA (Doer) is reachable only by typing `/mfa/setup`.
- **Severity:** major. On a shared computer the next person inherits the session.
- **Screenshot:** `06_dashboard_empty.jpg`

#### QA-09 — At phone width the main pages cannot really be used
- **Page / role:** Documents, IID preview (all pages share the layout) / Tenant Admin
- **Steps:**
  1. Set the window to 375×812 and open Documents.
  2. Click "Collapse sidebar".
- **Expected:** the sidebar hides behind the menu button, and the page content shows first.
- **Actual:**
  - The full sidebar is drawn above the content. The page starts 1,634 px down, about two screens.
  - "Collapse sidebar" leaves a blank screen and pushes the content to 1,870 px. The collapsed state is remembered on later pages.
  - Once scrolled down, the IID form is usable in two cramped columns, and the Documents table needs sideways scrolling.
  - At about 800 px wide (a half-screen window) the same "sidebar first" layout appears.
- **Severity:** major
- **Screenshot:** `36_phone_sidebar_first.jpg`, `37_phone_collapse_sidebar_blank.jpg`, `38_phone_iid_form_after_scrolling.jpg`, `18_narrow_pane_sidebar_pushes_content.jpg`

#### QA-10 — When the session ends mid-task, the user gets a technical message and no way back
- **Page / role:** Formulation version → Add dosing regimen / Doer
- **Steps:**
  1. Open a form in tab 1.
  2. Sign out in tab 2.
  3. Click Save in tab 1.
- **Expected:** "Your session has ended. Sign in again to save", with a sign-in link that keeps the entered values.
- **Actual:**
  - "Authentication credentials were not provided." appears under the form.
  - There is no link, and nothing tells the user to sign in.
  - The typed values are kept, which is good.
  - The next sidebar click goes to `/signin?next=…`, which is correct.
- **Severity:** major
- **Screenshot:** `23_signed_out_mid_task_raw_message.jpg`

#### QA-11 — Irreversible actions run on a single click
- **Page / role:** Checklist execution / VP, Tenant Admin
- **Steps:** on an approved execution, click "Supersede". Or on a submitted one, click "Reject".
- **Expected:** a confirmation step that names the record and says the action cannot be undone.
- **Actual:**
  - The request is sent immediately.
  - For the Tenant Admin, the server refused it.
  - For the VP, it would have superseded the approved record on one click.
  - "Reject" needs no reason, while "Return" and "Approve" need text.
- **Severity:** major. The data is append-only by design, so a mis-click cannot be undone.
- **Screenshot:** `34_vp_approved_checklist.jpg`

### Minor

#### QA-12 — Error messages show internal field names
- **Page / role:** most forms / all roles
- **Examples:**
  - "non_field_errors: Invalid credentials." on sign-in;
  - "total_dosage_unit_weight: A valid number is required.";
  - "quantity_per_dosage_unit: quantity_per_dosage_unit must be greater than zero.";
  - "proposed_quantity_per_unit: The amount must be greater than zero.";
  - "File signature does not match declared content type.".
- **Expected:** plain sentences next to the field, such as "Enter a number" or "Must be more than zero".
- **Actual:**
  - The raw API field key is shown in front of the message.
  - "Zero" gets two different sentences: one in the formulation form and the #132 sentence in the IID preview.
  - Only the first error is shown.
- **Severity:** minor
- **Screenshot:** `04_signin_wrong_password_raw_key.jpg`, `10_version_letters_raw_field_key.jpg`, `13_component_900000kg_refused.jpg`

#### QA-13 — Screens offer actions the role cannot do, and some refusals give the wrong reason
- **Page / role:** several / Doer, Reviewer, VP
- **Examples:**
  - The Doer sees Approve / Return / Reject on their own submitted checklist; clicking Approve gives "You do not have permission to perform this action."
  - The Doer opening Terminology Mappings sees all the filters and "+ Propose substance mapping", then "You do not have permission …".
  - The VP sees "New product record" and is refused on Create.
  - On a returned checklist, the Reviewer sees editable answers and "Submit for review".
    - Saving gives "This response is owned by the server and cannot be edited." That is wrong: the real reason is role and ownership.
    - The edited text stays in the box as if saved.
- **Expected:** hide or disable actions the role cannot take, and give the real reason when refusing.
- **Severity:** minor. The server enforces the rules; the screen misleads.
- **Screenshot:** `21_doer_sees_approve_buttons_refused.jpg`, `29_reviewer_edit_refused_misleading_message.jpg`

#### QA-14 — Reviewer upload fails with only "Upload failed"
- **Page / role:** Documents → Upload document / Reviewer
- **Steps:** upload a valid PDF as the Reviewer.
- **Expected:**
  - Per the owner's decision of 2026-11-18, Reviewers should be able to upload. That pull request is not built yet.
  - Until then, the message should say why the upload was refused.
- **Actual:**
  - The API returns 403; the dialog says only "Upload failed".
  - The "Upload document" button is shown to the Reviewer.
- **Severity:** minor
- **Screenshot:** `30_reviewer_upload_failed_generic.jpg`

#### QA-15 — IID calculations show numbers without units, raw tokens and a confusing sign
- **Page / role:** IID preview / Doer
- **Examples:**
  - "Difference from IID potency 7.000000": no unit.
    - It is +7 when the proposal is below the limit, and −7.000000 when it is above, so a negative number means "over".
  - "Percentage w/w 25.200 percent_w_w", "110.000 percent_of_potency": raw tokens.
  - "Unit conversion 40.500000 mg = 40.5 mg/5mL": mixes two units.
  - "ACACIA — 70 milligram potency, MDE UNAVAILABLE MDE".
  - Quantities are shown with 6 decimals ("250.000000 milligram", "0.000100 kg").
- **Expected:**
  - every number has its unit;
  - "over by 7 mg" or "7 mg below";
  - sensible rounding;
  - "MDE" spelled out.
- **Severity:** minor. It matches the owner's wording check: numbers shown without their unit.
- **Screenshot:** `31_iid_preview_below_limit.jpg`, `32_iid_preview_above_limit.jpg`

#### QA-16 — The checklist execution screen shows internal values
- **Page / role:** IIG Checklists → Executions / all roles
- **Examples:**
  - "Formulation version 48ece4c2-89ff-…" (a UUID, here and in the list);
  - "Status submitted_for_review";
  - "Submitted at 2026-11-18T09:35:12.679485Z" (raw UTC, while other pages show local dates);
  - answers shown as "true";
  - the New Execution form shows two raw "… Public ID" text boxes.
- **Expected:** product name and version number, "Submitted for review", a local date and time, and "Yes".
- **Severity:** minor
- **Screenshot:** `20_checklist_execution_unstyled_required_q1.jpg`

#### QA-17 — The dashboard is empty for every role
- **Page / role:** Dashboard / all roles
- **Steps:** sign in and open the dashboard.
- **Expected:** a short list of what is waiting for this user: items to review, returned items, drafts.
- **Actual:**
  - Only "Welcome to RegX. Select a workflow item from the sidebar."
  - The useful "attention queue" exists, but it is on Submission Operations.
- **Severity:** minor
- **Screenshot:** `06_dashboard_empty.jpg`

#### QA-18 — The Tenant Admin has no admin screens
- **Page / role:** sidebar / Tenant Admin
- **Steps:** sign in as Tenant Admin and look for users, roles or the audit trail.
- **Expected:** at least a read-only list of members and roles, and access to the audit trail.
- **Actual:**
  - The sidebar is the same as every other role's.
  - Adding or disabling a user needs `manage.py` (by design for creation, but nothing is visible).
- **Severity:** minor
- **Screenshot:** `35_tenant_admin_dashboard_no_admin_pages.jpg`

#### QA-19 — Rough edges in MFA set-up and sign-in
- **Page / role:** `/mfa/setup`, `/mfa` / Reviewer, VP, Tenant Admin
- **Problems:**
  - No QR code, only a 32-character key and an "open in authenticator app" link. Most users scan.
  - A wrong code shows "Invalid OTP." at the top of the card. The user is at the bottom, so it is off screen.
  - The wording changes from screen to screen: "two-step sign-in", then "Two-factor authentication" / "OTP Code".
  - The recovery-code box keeps the placeholder "000000", although codes are 20 characters.
  - The MFA-required error says "Set it up at /mfa/setup" as a raw path, not a link. The banner does have a link.
- **Severity:** minor
- **Screenshot:** `28_mfa_signin_wrong_code.jpg` (the set-up screenshot with the error was not kept: it shows the test key), `25_reviewer_write_blocked_mfa.jpg`

#### QA-20 — Upload details
- **Page / role:** Documents / Doer
- **Problems:**
  - A `.docx` uploaded with "Document type" left at PDF is accepted and listed as "PDF".
  - The image-only PDF warning ("No extractable text, likely scanned") shows only on the detail page. The list says "ready".
  - The detail page shows "Processing…" and does not update itself; you have to reload.
- **Severity:** minor
- **Screenshot:** `17_docx_uploaded_as_type_pdf.jpg`

#### QA-21 — The home page leads to the legacy tools, not to REGX
- **Page / role:** `http://localhost:8080/` / not signed in
- **Steps:** on the home page, click "RegX" in the header, or "Explore RegX".
- **Expected:** REGX sign-in (`/signin`).
- **Actual:**
  - It goes to `/ratools/` (the legacy tool menu).
  - "Request access" on the REGX sign-in page goes to the legacy demo-request form.
  - The REGX sidebar also lists the legacy "Regulatory Tools / Company Suite" items under the REGX pages.
- **Severity:** minor
- **Screenshot:** `01_home_company_site.jpg`, `02_regx_nav_goes_to_ratools.jpg`

#### QA-22 — Formulation version screen details
- **Page / role:** Formulation version / Doer
- **Problems:**
  - The "% w/w CALCULATED" column says "not yet calculated" for every row, although the total weight (250 mg) is set. When it gets calculated is not explained.
  - The Unit box keeps the previous row's unit, which makes it easy to enter the wrong unit on the next row.
  - "Run IID assessment preview →" passes the version, but pre-fills nothing: no component picker, no weight.
- **Severity:** minor
- **Screenshot:** `14_components_150pct_ww_and_mg5ml_accepted.jpg`

#### QA-23 — Form fields have no accessible labels
- **Page / role:** New product record, Create version, Add component, Upload / all
- **Actual:** the text boxes are announced as "textbox" with no name. The visible label is not tied to its input.
- **Severity:** minor (screen-reader users cannot tell the fields apart)
- **Screenshot:** —

#### QA-24 — Wording near approval states
- **Page / role:** Product records, checklist execution / all
- **Observations:**
  - The product list shows status "approved". The checklist execution shows "Status approved" and "Approved by", with no "internal" qualifier nearby. The gap-analysis disclaimer is further down the page.
  - The status names are allowed by the rules (internal state names), but a reader skimming the page sees "approved" on its own.
  - The "Exceeds IID precedent" box says "approval cannot be automatic", which means internal approval.
  - "Cannot compare" results carry no "technically comparable …" label. That is arguably correct, since nothing was compared, but noted for the owner.
- **Not found:** "compliant", "acceptable", "validated" (other than in disclaimers), or any agency-approval claim.
- **Severity:** minor
- **Screenshot:** `34_vp_approved_checklist.jpg`

### Cosmetic

#### QA-25 — Long names are cut off or widen tables
- A 300-character product name with no spaces is clipped in the page heading.
- In Product records, it widens the table to 3,048 px, so Status and Reference product move off screen.
- **Screenshot:** `09_product_long_name_special_chars.jpg`, `24_reviewer_mfa_banner_long_name_table.jpg`

#### QA-26 — Organisation shown as "DEMO-Tenant (demo) (demo) — active"
- **Screenshot:** `05_after_signin_tenants_page.jpg`

#### QA-27 — The checklist execution page is unstyled
- It uses browser-default buttons, selects and headings, unlike every other page.
- **Screenshot:** `20_checklist_execution_unstyled_required_q1.jpg`

#### QA-28 — A stale error stays after it is fixed
- "Response required for question Q1." stays at the top after Q1 has been answered and saved.
- **Screenshot:** `20_checklist_execution_unstyled_required_q1.jpg`

## Things that work but confused me

- After sign-in you land on "Your organisations" and must click the only organisation before anything shows.
- On a fresh install, the IID preview needs a release ID typed by hand. Once a release is active, it is pre-filled.
- The Doer can open the Terminology Mappings page, which then fails to load (see QA-13).
- After a Reviewer returns a checklist, the Doer has no place to attach the evidence the reviewer asked for.
- The decision box says "Review required … Reviewer escalation required before proceeding" even for a result below the limit, because the IID rows have no daily maximum. It is correct by the rules, but reads like a problem.
- The FDA Releases page lists the active IID release as "3748/9071" with no explanation of the two numbers.
- The sidebar's "Templates" and "Migration Batches" show helpful empty-state text; "Dashboard" does not.

## Not tested (and why)

- **Cross-tenant record IDs** (opening another organisation's record by its ID): the demo has one organisation.
- **The real 8-hour session expiry:** simulated with a sign-out from a second tab.
- **The real operating-system file picker:** not available in the browser pane (see "How the test was run").
- **VP and Tenant Admin uploads, keyboard-only use, screen reader:** not in the session's scope or time.
- **Company-site (legacy) pages** beyond the link check: per `constraints.md`, legacy routes are not opened without knowing what they do.

## Top 5 to fix first

1. **QA-01 — Formulation approval (Option A).**
   - It blocks the main end-to-end task for any real formulation.
   - The design is already approved by the owner.
   - Everything downstream (checklist, the real-stack smoke's "blocked" step) waits on it.
2. **QA-02 + QA-03 — Validate formulation inputs.**
   - Use the controlled unit list for the component unit, check the unit against "what the quantity means", and refuse a negative maximum units/day.
   - Bad numbers here silently poison every IID comparison and checklist built on the formulation.
   - It is a small, server-side change with clear tests.
3. **QA-05 — Clear the IID result when the input changes or fails validation.**
   - Today the screen can show a conclusion for numbers that are no longer in the form.
   - That is the most direct way a user could record a wrong conclusion. It is a front-end-only fix.
4. **QA-06 + QA-07 — Make IID "no comparison" reasons and reference-data state visible.**
   - Users cannot tell "no FDA precedent" from "our data isn't linked" or "you typed a route we don't know".
   - Showing the real reason, and flagging an active release with unlinked rows, turns silent failure into an actionable message.
5. **QA-08 + QA-10 — Sign-out, a user menu, and a clear "session ended, sign in again".**
   - Basic security hygiene for a regulated, multi-user tool.
   - Today a user cannot sign out at all, and an expired session shows a technical message.

QA-04 (editing or deleting draft components) is next in line. Without it, every input mistake in QA-02 becomes permanent.
