# REGX independent QA report

**19 November 2026 · regx-main · d14e2864e87f67211b3b8687e57543380cda1e3e**

## 1. Summary

**Verdict — hold release acceptance.** The core formulation approval flow and its PostgreSQL immutability safeguards worked. Live testing found that REGX can show an IID comparison for an earlier input, silently reinterpret a conflicting quantity, and create a checklist definition that cannot be executed. IIG calculations also failed on valid formulation unit spellings offered by the application.

| Severity | Confirmed | Suspected | Total |
| --- | ---: | ---: | ---: |
| Blocker | 0 | 0 | 0 |
| Major | 8 | 4 | 12 |
| Minor | 7 | 0 | 7 |
| Cosmetic | 0 | 0 | 0 |
| **Total** | **15** | **4** | **19** |

Confirmed findings have live HTTP, browser or PostgreSQL evidence, and source references where relevant. Suspected findings come from the code review. The severity counts exclude recovered test-environment errors and informational dependency warnings.

QA used a clean checkout of the fetched `regx-main` tip, a separate loopback-only Compose project named `regx-codex`, locally generated demo accounts and fixtures, and cached copies of the public FDA files documented by the repository (July 2026 IID SHA-256 prefix 4f3a8e37 and August 2026 Orange Book ZIP prefix 84e616aa). The company site started with a newly migrated empty SQLite database in its QA volume. The repository's packaged company database was kept out of the runtime and smoke tests. I set AI to off with provider `stub`. Both app containers tested for the OpenAI key reported it absent. GitHub Actions stayed disabled. No application code or existing development database was changed. The QA containers were removed after verification. Synthetic named volumes and the clean QA checkout were retained.

## 2. Part 1 — Existing checks

| Check | Result | Evidence |
| --- | --- | --- |
| Backend `ruff check` | **Pass** | `All checks passed!` |
| Backend `ruff format --check` | **Pass** | 625 files already formatted |
| Backend `lint-imports` | **Pass** | 16 contracts kept, 0 broken |
| Backend `makemigrations --check --dry-run` | **Pass** | `No changes detected` |
| Full backend pytest, `regx.settings.test`, one run | **Pass** | 4,657 passed, 2 skipped, 0 failed, 6 warnings in 29m 17s. 96.08% coverage against a 55% gate. |
| Frontend `npm ci` | **Pass** | 472 packages installed. npm reported 16 advisories across the installed tree (7 moderate, 6 high, 3 critical). Exploitability and production exposure were outside this installation check. |
| Frontend `npm run type-check` | **Pass** | `tsc --noEmit`, exit 0 |
| Frontend `npm run lint` | **Pass** | No ESLint warnings or errors. Next emitted its `next lint` deprecation notice. |
| Frontend Vitest | **Pass** | 645 passed across 34 files |
| Frontend production build | **Pass** | Exit 0, 30/30 static pages generated |
| Frontend Playwright E2E | **Pass** | 260 passed in 7.8 minutes. This suite uses the repository's mocked API. |
| Backend dependency locks | **Pass** | Regenerated `base.txt`, `test.txt`, `dev.txt` using the supplied script. All 3 matched byte for byte. |
| Company-site dependency lock | **Pass** | Regenerated `requirements.docker.txt`. The file matched byte for byte. |
| Company-site smoke and AIDatabase tests | **Pass** | 52 passed, 0 failed. Container ran with `--network none` and no `OPENAI_API_KEY`. |
| Compose build and startup | **Pass** | 4 application images built and 7/7 default services healthy. Fresh REGX migrations and demo seed also passed. |
| `scripts/real_stack_smoke.sh --flows` | **Pass** | 15 passed in 5.0 minutes. All 150 attempted page visits met the script's load criteria. |

The first Ruff attempt exited 2 because the container's unprivileged user could not create `/app/.ruff_cache`. Both checks passed with `--no-cache` on the same files. The pytest skips were a governance fixture whose role already has case view permission and an Orange Book locale check that required a non-English locale. The six warnings were five Django constraint deprecations and pytest trying to collect the imported TestStatus enum. Other QA setup retries corrected the test harness inputs or file paths. They are excluded from the product issue counts. The real-stack smoke used a fresh second synthetic tenant in the same Compose stack to keep independent QA fixtures from changing the smoke script's starting state.

## 3. Part 2 — Independent checks on the running stack

| Feature | Normal path verified | Negative and edge paths verified |
| --- | --- | --- |
| Sign-in and security | Doer sign-in. MFA enrolment yielded 10 recovery codes. A correct TOTP and one recovery code authenticated separate fresh sessions. A second MFA-enrolled Tenant Admin reset another admin's device. API docs and schema returned 200 after login. | Wrong passwords 1–5 returned 400. Attempt 6 and the correct-password retry returned 429 with `Retry-After`. Sign-in succeeded after the configured cooldown. Password-only MFA-pending login had no authenticated session. Wrong TOTP, reused recovery code, self-reset, Reviewer reset, unenrolled second-admin reset and short reset reason were refused. Reviewer, VP, Tenant Admin and Platform Support received `mfa_enrolment_required` on writes before enrolment. A reset target also had to re-enrol before writing. Registration and tenant creation returned 403. An edited `?tenant=qa-other` displayed “No access to this organisation”. API calls without membership returned 403 and lookups of a known foreign formulation/document through the second tenant returned 404. Anonymous docs and schema returned 403. |
| Formulations | Created solid and liquid products and draft versions. Saved mg, g, kg, µg, mL and L, plus %w/w, %w/v, %v/v and mg/5mL using active quantity meanings. The API accepted 1 kg, 1,000 L and 2,000,000 µg. Daily limits 1 and 1,000 saved. | Unknown unit, zero and negative amounts, amounts above 1,000,000 normalized mg or mL, percentage above 100, percentage without a basis and per-volume amount on a tablet or capsule returned 400. Plain POWDER and GRANULE nevertheless accepted a per-volume amount (QA-19). Daily limits 0, −1 and 1,000.0001 were rejected. **0.5 saved**, and explicit percentage bases could conflict (QA-04, QA-07). |
| Formulation approval | An independent Doer/VP submitted a version created by a different Doer/VP. A Reviewer returned it with a reason, the draft accepted another component, and an independent VP approved after resubmission. A Reviewer also rejected a separate version. History recorded the transitions. Approving the replacement superseded the prior version and the existing IIG execution retained its original formulation version. | Approval before submission returned 409. No components, missing return/reject reason and missing approval note returned 400. Reviewer, creator with VP role, and a separate submitter with VP role each received 403 on approval. API rejected component writes under review and after approval. PATCH of the approved version returned 405. Direct PostgreSQL UPDATE of the approved version/component and DELETE of the approved version were rejected by triggers. The malformed approval note returned 500 (QA-11). |
| IID import and review | Imported 9,071 public July 2026 IID rows. Activated FDA SPL route/form and REGX controlled-unit lists. Reviewer submitted proposals for review and VP approved 59 routes, 105 dosage forms and 20 units. Re-resolved both releases. Deliberate re-import of the line-ending copy with a reason created a fresh release. Activation superseded the earlier release. PostgreSQL verified both lineage and supersession links, a populated reason, a shared content fingerprint and different source checksums. Audit recorded one re-import event with reason and one activation for the replacement. | Exact duplicate and line-ending copy each exited 3 with `same content even if line endings or trailing spaces differ`. Deliberate import without a reason exited 1. Early activation, loader approving/activating even with VP role, Reviewer approval, a Doer starting mapping review and mapping approval before review were refused. Submitting without acknowledging 67 unlinked records returned 409. `DROPS` remained unmapped. |
| IID preview | ACACIA oral tablet, row 55, returned 35 mg below, 70 mg exactly at, and 77 mg above the 70 mg limit. 0.077 g converted exactly to 77 mg. ACETIC ACID oral elixir, row 107, restated 0.214 mg/1mL as 1.07 mg/5mL. A repeating decimal was marked as rounded for display. The comparable API results included the required technical-only label, FDA row locator and release UUID. The browser displayed the label and row. | %w/v versus %w/w refused with `DIFFERENT_BASIS`. Daily-only magnesium stearate stated that per-day comparison is unsupported. Unknown ingredient, unmapped DROPS and unknown route gave distinct reasons. Zero was refused. A completed result cleared on edit. A pending response could restore a stale result, and a superseded release gave a wrong explanation (QA-03, QA-04, QA-13, QA-14). |
| IIG checklist | Created an execution on the new approved formulation. Saved answers persisted after a browser reload. Gap analysis changed from 2 unanswered and 0% complete to 0 unanswered and 100%. Doer submitted, Reviewer returned, Doer resubmitted and independent VP approved. Verified six numeric outcomes against three hand calculations below. | Draft formulation, VP creating execution, duplicate active execution, invalid answer shape, missing required answers, Doer approval, approval by a Doer/VP who submitted, and return without reason were refused. Definition authoring lost the scope until the synthetic fixture was classified locally (QA-01). Common formulation unit spellings produced six calculation errors (QA-02). |
| Orange Book | Imported 48,761 FDA products with 0 row failures. `AMZEEQ`, `212379` and `NDA212379` found the same product, flagged as both RLD and RS. The API returned 23,217 discontinued products, 7,829 RLD and 4,508 RS in this release, with the corresponding flag present in sampled results. Selecting the genuine active-release product succeeded. The browser rendered the AMZEEQ detail and marked a discontinued search row Yes. | Unknown trade/application, wrong prefix, random product UUID, mismatched release and application, wrong role and an existing public product in a second inactive QA release were refused or returned empty results. Patents, exclusivity and the SOW 2.3 calculators had no functional REGX routes in the scope reviewed. A product search page already exists, with fewer search fields than the API (QA-12, QA-17). |
| Documents | Doer uploaded valid text PDF, image-only PDF, DOCX and XLSX. Celery completed all four. The image-only PDF had one page, zero text pages and an API `no_extractable_text` warning. The browser displayed “Warning: no extractable text”. Tenant Admin also uploaded successfully. | A text file and a fake PDF signature returned 422. VP and Platform Support uploads returned 403. A different tenant received 404 for a known document. An MFA-enrolled Reviewer received 403 on both upload and attachment despite the UI offering Upload document (QA-05). |
| AI foundation | **Conditional coverage did not apply.** GitHub PR #129 was OPEN with `mergedAt: null` and its feature branch was absent from the tested history. | No foundation endpoint or provider execution was exercised. The running project used `REGX_AI_ENABLED=false`, `REGX_AI_PROVIDER=stub` and no OpenAI key. The company-site suite ran without network access. |

**IIG hand checks** used a 0.250 g unit weight and 4 units/day. The execution returned the values below with all six outcomes complete when the inputs used the canonical spelling `gram`.

| Ingredient per dose | Weight fraction × 100 | Ingredient × 4 units/day |
| --- | ---: | ---: |
| 0.025 g | 10% w/w | 0.100 g/day |
| 0.050 g | 20% w/w | 0.200 g/day |
| 0.0075 g | 3% w/w | 0.030 g/day |

## 4. Findings

### QA-01 — Major · CONFIRMED · IIG definition authoring drops execution scope

**Steps.** As a Doer, create a tenant-owned definition with `execution_scope=formulation_version` or `formulation_component`. Complete the definition's review and activation, then start an execution on an approved formulation.

**Expected.** The valid scope is stored and used to enforce the appropriate execution rules. **Actual.** The create response was HTTP 201 with `execution_scope: ""` for both valid choices. Starting an execution on the active definition returned HTTP 400 `execution_scope_unclassified`. For downstream tests only, I set the scope of newly created synthetic tenant fixtures in the isolated database. The subsequent execution requests used the live API and normal approval flow.

**Evidence.** `backend/iig_checklist/serializers.py:53` accepts the field, `frontend/src/lib/api.ts:1698` exposes it, and `backend/iig_checklist/views.py:255` constructs the model without it.

### QA-02 — Major · CONFIRMED · IIG built-in calculations reject formulation unit spellings

**Steps.** Approve a 250 mg formulation with 4 units/day and inactive amounts of 25 mg, 0.05 g and 7,500 µg. Run a component-scoped checklist with the `percentage_w_w` and `daily_exposure` bindings and select each component.

**Expected.** The recognized same-dimension units produce the six values in the hand-check table. **Actual.** All six API outcomes were `status=error`, `reason_code=UNIT_MISMATCH`, `value=null`. As a control, entering the same weight and component quantities in canonical `gram` yielded 6/6 correct numbers.

**Evidence.** `backend/iig_checklist/calculation_inputs.py:595` and `backend/iig_checklist/unit_adapter.py:80` pass stored spellings through to the converter. `backend/iid_assessment/unit_conversion.py:15` and `:74` use canonical names. `backend/iid_assessment/comparison.py:69` supplies aliases on the separate IID comparison path.

### QA-03 — Major · CONFIRMED · A pending IID response repopulates a stale result

**Steps.** On IID preview, run ACACIA oral tablet at 77 mg. Change the amount to 35 mg while the real POST is pending. The browser used 1.2 seconds of simulated network latency to reproduce the timing consistently. The request and response passed through to the real backend.

**Expected.** The result stays cleared after the amount changes until a new run finishes for 35 mg. **Actual.** The input showed 35 mg. The HTTP 200 response for 77 mg rendered “Proposed 77 mg per dose unit is above the IID value of 70 mg per dose unit”. Editing after a completed response cleared it correctly.

**Evidence.** Browser request payload `77`, live input `35`, visible result `77`. `frontend/src/app/(regx)/iid-assessments/preview/page.tsx:194` clears on change and `:269` applies the pending response without checking which inputs it used.

### QA-04 — Major · CONFIRMED · Conflicting quantity fields can change the IID verdict

**Steps.** Preview ACACIA oral tablet with 0.077 g and compare that control with the same request plus the active “mg per dose unit” meaning. On a liquid draft, send component unit `%w/w` with the active `%w/v` meaning.

**Expected.** Each conflicting request is refused with an error that identifies the inconsistent unit or basis. **Actual.** The control compared 77 mg to 70 mg and returned `above`. The conflict returned HTTP 200 and compared 0.077 mg to 70 mg as `at_or_below`. The conversion metadata still named grams as the original unit. Component creation returned HTTP 201 and saved the conflicting percentage as `%w/v`.

**Evidence.** `backend/iid_assessment/serializers.py:36` checks that the meaning exists, and `backend/iid_assessment/assess.py:198` applies its unit independently of the raw input. `backend/formulations/serializers.py:259` collapses the percentage spelling to `percent` before checking the chosen meaning.

### QA-05 — Major · CONFIRMED · Reviewer document uploads are denied

**Steps.** Sign in as an MFA-enrolled Reviewer. Use the visible **Upload document** button with a valid PDF. Try adding a version to an existing document as the same user.

**Expected.** Reviewers can attach documents under the owner decision recorded on 18 November. **Actual.** Both POSTs returned HTTP 403 `permission_denied`. The upload button was visible and the browser reproduced the same refusal. Doer and Tenant Admin succeeded with a valid PDF. VP remained restricted.

**Evidence.** `PROJECT_OVERVIEW.md:797` records the decision. `backend/documents/permissions.py:33` grants the Reviewer only read permissions. `frontend/src/app/(regx)/documents/page.tsx:140` offers the action.

### QA-06 — Major · CONFIRMED · An approved IIG definition can be ineligible for activation

**Steps.** Create a tenant checklist version using a request body with an effective date, add questions, submit and approve. Try to activate. Separately, approve a version containing a built-in calculation binding whose required selector question is missing and try to activate it.

**Expected.** Creation persists the submitted date or explicitly rejects that field. The reviewer can resolve missing prerequisites while the version can still be returned or edited. **Actual.** Create silently ignored the effective date. Submit and approve returned 200, while activation returned HTTP 400 “effective_date is required before activation.” The invalid calculation fixture also reached approved and then returned `REGISTRY_VALIDATION_FAILED` on activation. Editing by PATCH before submitting and providing the selector allowed valid controls to activate. Approved is outside the editable/returnable states, so repairing the same approved version is unavailable through those actions.

**Evidence.** `backend/iig_checklist/views.py:450` ignores the create body, `:492` restricts editing and `:592` checks date at activation. `backend/iig_checklist/views.py:595` checks calculation bindings at activation. `backend/iig_checklist/transitions.py:34` restricts return to under-review versions.

### QA-07 — Major · CONFIRMED · Maximum dosage units/day can be below 1

**Steps.** Create a formulation version with maximum dosage units/day of 0.5. Use the same value in the browser version form.

**Expected.** Values outside 1–1,000 are rejected. **Actual.** The API returned 201 with a draft. The browser accepted 0.5 and navigated to the created version. Values of 0, −1 and above 1,000 were refused. A subminimum value can feed daily-exposure calculations.

**Evidence.** `backend/iid_assessment/amount_limits.py:73` enforces greater than zero. `backend/formulations/serializers.py:192` uses that shared rule. `frontend/src/app/(regx)/formulations/[publicId]/page.tsx:263` displays the field.

### QA-08 — Major · SUSPECTED · Concurrent formulation approvals may leave two approved versions

**Review scenario.** Two different versions of one product are eligible for approval at the same time. **Expected.** The product ends with a single approved version and consistent supersession history. **Risk.** Approval locks the target row and currently approved siblings. It does not lock the product or enforce a conditional unique constraint. Transactions approving two different rows can both observe an empty approved set.

**Evidence.** `backend/formulations/approval.py:183` and `:198`, `backend/formulations/models.py:184`. Sequential supersession passed. I did not run concurrent approvals.

### QA-09 — Major · SUSPECTED · Some governed writes and their audit events can commit separately

**Review scenario.** An FDA terminology mapping changes state or a formulation component is added while audit event persistence fails. **Expected.** The governed change and its audit event commit or roll back together. **Risk.** Mapping transitions leave their transaction before writing the audit event. Component creation also precedes its audit insert without an enclosing application transaction. A later audit error could leave a durable change without the expected history.

**Evidence.** `backend/fda_data/views.py:900`, `:950`, `:952` and `backend/formulations/views.py:323`–`:334`. Normal audit history and direct audit-row immutability passed. I did not inject audit failures.

### QA-10 — Major · SUSPECTED · Fingerprint deduplication is not atomic for concurrent imports

**Review scenario.** Concurrent ordinary IID loads have the same normalized content and different source checksums. **Expected.** At most one ordinary load registers. **Risk.** The CLI checks for an existing fingerprint before its transaction. Fingerprint is an indexed column and has no conditional uniqueness for ordinary imports. Existing uniqueness on the raw checksum handles exact bytes. The separate active-release constraint still guards activation.

**Evidence.** `backend/fda_data/management/commands/import_fda_release.py:185`, `:190`, `:225`, `backend/fda_data/models.py:101` and `:171`–`:184`. Sequential exact and changed-line-ending duplicates were refused. I did not run concurrent imports.

### QA-11 — Minor · CONFIRMED · Malformed formulation approval note returns HTTP 500

**Steps.** As the independent VP, submit an approval request for a version under review with a numeric note. **Expected.** HTTP 400 and a field-level validation error. **Actual.** A numeric note produced HTTP 500. Retrying with a valid text note approved normally. The return and reject handlers share the raw string assumption.

**Evidence.** `backend/formulations/views.py:286`–`:297` forwards request data directly. `backend/formulations/approval.py:184` calls `.strip()` on that value.

### QA-12 — Minor · CONFIRMED · Orange Book UI misses two working search filters

**Steps.** Open `/fda-data/orange-book?tenant=demo` and look for trade-name and application-number fields, then compare with the API. **Expected.** The product search UI supports the same requested search modes as the API. **Actual.** “Orange Book Product Search” exists. Its form offered Active ingredient, Route code, Dosage form code, Strength and Application type. The API found the same AMZEEQ row by trade name, plain application number and prefixed number.

**Evidence.** Browser input inventory, `frontend/src/app/(regx)/fda-data/orange-book/page.tsx:36` and `:85`, `backend/fda_data/views.py:426`. The presence of the product-search page differs from the brief's inventory.

### QA-13 — Minor · CONFIRMED · IID comparison omits its release ID in the result panel

**Steps.** Run a comparable preview and read the complete assessment result panel. **Expected.** The result identifies both the FDA source row and the release used. **Actual.** The browser displayed the technical label and `IID source row: row:55`. The returned release ID was in the API and prefilled in the editable input above, with no release identifier in the result itself.

**Evidence.** Browser DOM comparison, `frontend/src/app/(regx)/iid-assessments/preview/page.tsx:158` and `:317`, `backend/iid_assessment/comparison.py:207`.

### QA-14 — Minor · CONFIRMED · Superseded IID data produces a misleading no-match reason

**Steps.** Run the matching ACACIA oral-tablet preview with the earlier, now-superseded release UUID. **Expected.** Explain that this release is ineligible and identify the release selection as the problem. **Actual.** HTTP 200 with no comparison and “No IID record with this route and dosage form”. The exact row was present in that snapshot and matched with the active replacement.

**Evidence.** Response `NO_RECORD_FOR_ROUTE_AND_FORM`, `backend/iid_assessment/matching.py:83` excludes superseded releases and `backend/iid_assessment/reasons.py:142` explains the result from the supplied release without checking its status.

### QA-15 — Minor · CONFIRMED · REGX navigation has no sign-out action

**Steps.** Sign in and inspect REGX's authenticated navigation. **Expected.** A visible way to end the session. **Actual.** No Sign out or Log out link/button was rendered in the checked navigation. The logout API exists.

**Evidence.** Authenticated browser navigation returned zero controls named Sign out or Log out. `backend/identity/urls.py:10` registers logout. See also `PROJECT_OVERVIEW.md:781`.

### QA-16 — Minor · CONFIRMED · The first IID candidate click sends the previous selection

**Steps.** Open a preview with two exact candidates and click **Select this precedent** on one row. I used an approved two-row synthetic IID fixture and kept the public release active. **Expected.** The first request includes the selected row and displays that precedent. **Actual.** The first HTTP 200 response had no selected precedent and its request contained no selected ID. Clicking the same button again sent the ID and displayed the 10 mg record.

**Evidence.** Captured browser requests and responses, `frontend/src/app/(regx)/iid-assessments/preview/page.tsx:267` and `:442`. The handler updates state and immediately reads the previous render's selection.

### QA-17 — Minor · CONFIRMED · FDA release UI offers unimplemented patent and exclusivity dataset types

**Steps.** Inspect the release registration options and the REGX route/importer inventories. **Expected.** The release form offers implemented dataset types or visibly marks unavailable choices. **Actual.** The live browser rendered enabled options for `orange_book_patents` and `orange_book_exclusivity`. The corresponding product-data API paths returned 404. Patent and exclusivity workflows were outside the test scope per the brief.

**Evidence.** `frontend/src/app/(regx)/fda-data/releases/new/page.tsx:11` and `:12`, `backend/fda_data/urls.py:41`, `backend/fda_data/management/commands/import_fda_release.py:64`.

### QA-18 — Major · SUSPECTED · The database trigger leaves review stamps mutable under review

**Review scenario.** A database-level maintenance write touches the review metadata of a formulation version under review. **Expected.** The original submitter remains protected and the approval check uses that persisted identity. **Risk.** The trigger excludes the review stamps from its equality check and permits same-status updates while under review. Its approval branch evaluates the new submitter stamp. Independent submitter enforcement in the database therefore depends on preserving a stamp that the same trigger does not freeze.

**Evidence.** `backend/formulations/migrations/0004_version_db_governance.py:47`, `:89`–`:93` and `:109`–`:110`. The API refused both dual-role self-approval cases. I did not attempt to change submitter stamps in PostgreSQL.

### QA-19 — Major · CONFIRMED · Per-volume amounts are accepted for some solid dosage forms

**Steps.** Create topical draft products with FDA SPL dosage form `POWDER` or `GRANULE`, without a reconstitution qualifier. Add a component with the active `mg/5mL` meaning. Use a capsule and `POWDER, FOR SOLUTION` as controls.

**Expected.** The plain solid forms reject a per-volume amount. The explicitly reconstituted control accepts it. **Actual.** Both plain solids returned HTTP 201 and stored `mg/5mL`. A capsule returned 400 and the reconstituted powder returned 201.

**Evidence.** `backend/formulations/dosage_forms.py:20` uses a keyword list that excludes powder and granule. Both are recognized FDA SPL dosage forms in the imported source (`C42972`, `C42938`).

## 5. Part 3 — Code review notes

- Followed tenant context and membership checks into formulations, FDA data, IIG, documents and the MFA policy. The tested tenant-owned resource paths failed closed, including lookups made from a valid second-tenant membership. FDA reference records are platform-level by design.
- Followed Option A permissions and lock boundaries into `formulations.approval` and PostgreSQL migration `0004_version_db_governance.py`. The service checks creator and submitter separately from role. Direct update/delete probes against an approved version and audit rows failed. The trigger documentation explicitly exempts direct version INSERT for fixtures. The application API only creates drafts. The approval concurrency and database review stamp risks are QA-08 and QA-18.
- Read the reference matcher, comparison and calculation adapters. Same-family/same-basis checks and rational comparison precede display rounding. The verified label explicitly qualifies comparable results. The defects are conflicting inputs before the comparison, stale browser state and missing result provenance (QA-03, QA-04, QA-13).
- Reviewed content hashing, release selection, mapping and audit writes. The normalized fingerprint sorts row hashes and normalizes line endings and trailing whitespace. The sequential duplicate and deliberate-reimport controls behaved as designed. Audit writes for formulation transitions and FDA release activation run inside their respective transactions. Mapping/component atomicity and concurrent ordinary import registration are QA-09 and QA-10.
- Reviewed the benchmark wording used in the tested output. Formulation “Approved (internal)” and the IID technical-only label distinguished the application's workflow or comparison from any regulatory verdict.

## 6. What worked well

The create → submit → return → resubmit → approve formulation path worked with separate identities. PostgreSQL enforced immutability independently of the API. The public FDA import and supersession preserved provenance. Valid like-for-like comparisons used exact arithmetic, and the image-only document warning matched the processing result.

## 7. Coverage limits

- AI foundation was outside the tested branch because PR #129 was open. The requested docs/AI_INTEGRATION_RUNBOOK.md was also absent from that commit. No stub-provider execution or AI prompt/response log claims are made.
- Patent, exclusivity and SOW 2.3 calculator workflows were excluded as requested. Coverage was limited to checking their availability. The actual Orange Book product search page was inspected because it was present.
- The controlled-unit list and mappings were approved by synthetic QA identities. Regulatory validation, client data, production deployments, ClamAV, concurrent approval/import races, audit-write fault injection and platform-wide permission scenarios beyond the fixture tenants were outside the run.
- The numeric checks above report the live IIG calculation controls after explicitly classifying synthetic tenant definitions in the QA database. That setup was required because the definition creation API discarded the supplied scope. FDA re-import lineage was verified in PostgreSQL and audit because the release response exposed `superseded_by_release` without the new release's parent or reason.
- The real-stack page crawler recorded 22 unreached role/detail-route combinations. It could not follow fixture links for Orange Book detail, IID assessment detail, migration batch detail, submission package detail and template detail, plus FDA mapping detail for two roles. The independent browser and API checks covered Orange Book detail for a Doer using a real product from the active release.

