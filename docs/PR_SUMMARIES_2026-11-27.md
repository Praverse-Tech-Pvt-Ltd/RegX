# Open pull requests: summaries (2026-11-27)

**Status:** all twelve are open against `regx-main` and none is merged. After #171, #176 and #179 were merged today, **none of them conflicts** with `regx-main` (checked on GitHub and with a local merge test).

**Where the facts come from:** each PR's description and the session's recorded runs.
- "Full local CI" means the repository's own workflow steps, run on this machine one job at a time; GitHub Actions are off.
- "Browser check" means a real browser on a stack rebuilt from the branch.

**Order:** #166 and #168 first, then the docs and tests PRs, then the rest.

---

## #166 — IID preview keeps the typed unit
- **Files:** `frontend/src/app/(regx)/iid-assessments/preview/page.tsx`, `frontend/tests/unit/fda-iid.test.tsx`, `frontend/e2e/iid-preview-typed-unit.spec.ts`
- **What it does:** choosing what the quantity means no longer silently changes the unit the user typed. If the typed unit does not fit the meaning, the preview is refused at the unit field and no comparison is shown.
- **Tests:**
  - **Old code failed for the right reason:** yes. On the old code, 0.077 gram + "mg per dose unit" became 0.077 mg and was reported "at or below", 1,000 times too small. Two old unit tests asserted that old behaviour and were changed.
  - **Full local CI:** pass. Backend 4,970 passed; frontend vitest and Playwright 272; docker integration.
  - **Browser:** pass, with old code against the branch in `docs/evidence/PR166_BROWSER.md`.
- **What could go wrong:**
  - **Users will notice:** a mismatched unit is now refused instead of being auto-switched, so they must correct the unit.
  - **Data and rollback:** no stored data and no migration. Rollback = revert the commit.
- **Depends on:** nothing.

## #168 — An empty checklist version cannot be submitted, approved or activated
- **Files:** `backend/iig_checklist/views.py`, `backend/iig_checklist/tests/test_version_not_empty.py`, setup changes in `tests/conftest.py`, `test_api.py`, `test_clone_api.py`, `test_lifecycle.py`, `test_platform_mutation_authorization.py`; `.github/workflows/docker-integration.yml` (smoke step 4b); `frontend/e2e/iig-checklist-version-not-empty.spec.ts`
- **What it does:** a checklist version with no questions is refused at submit, approve and activate (400 `version_has_no_questions`), and the page shows the server's sentence. An empty version could otherwise replace a real one.
- **Tests:**
  - **Old code failed for the right reason:** yes. The old code accepted all three steps (5 backend tests, 1 Playwright).
  - **Full local CI:** pass. Backend 4,975 passed; Playwright 272; docker integration with the new step 4b.
  - **Browser:** pass, with old code against the branch in `docs/evidence/PR168_BROWSER.md`.
- **What could go wrong:**
  - **Users will notice:** an existing **draft** version with no questions can no longer be submitted until a question is added. A version that is **already active** is not re-checked and stays as it is.
  - **Test setup:** ten existing tests needed one question added to their setup, and the CI smoke workflow file changed.
  - **Data and rollback:** no migration. Rollback = revert.
- **Depends on:** nothing.

---

## #177 — Calculation release gate (tests only)
- **Files:** `backend/iid_assessment/tests/test_calc_release_gate.py`
- **What it does:** 15 IID preview cases with hand-worked expected answers: at the limit, just above, g / µg / mcg, % and mg/mL refused, not in the IID, wrong route or dosage form, daily maximum only, and at and above the daily maximum. No product code changes.
- **Tests:**
  - **Old code failed for the right reason:** not applicable, because these tests pin current behaviour. A deliberate boundary bug (`>` to `>=`) makes 4 of them fail, so they catch real errors.
  - **Full local CI:** pass. Backend 4,985 passed, the previous 4,970 plus these 15.
  - **Browser:** not applicable.
- **What could go wrong:**
  - **For users:** nothing.
  - **Status of the answers:** they are consistency checks only until the regulatory reviewer signs off the expected answers (`docs/CALC_RELEASE_GATE.md`, #178). They will need updating if the per-day rule (Q8) changes the rules.
- **Depends on:** nothing. Its explanation doc is in #178.

## #170 — Scope of the IIG checklist authoring screens (docs)
- **Files:** `docs/IIG_AUTHORING_UI_SCOPE.md`
- **What it does:** describes the missing authoring screens (S1–S8) and API gaps (A1–A4), about 3–4 weeks of work. It requires sample content to be labelled "SAMPLE – not real checklist content". Scoping only, nothing built.
- **Tests:**
  - **Old code failed for the right reason:** not applicable.
  - **Full local CI:** pass. Backend 4,970 passed; vitest 645; Playwright 271; docker integration.
  - **Browser:** not applicable.
- **What could go wrong:**
  - **Behaviour and data:** none.
  - **Estimates:** they assume the client's content is close when the question editor is built.
- **Depends on:** nothing.

## #178 — Calculations first (docs)
- **Files:** `docs/CALC_MAP_LOSARTAN.md`, `docs/evidence/CALC_RUN_LOSARTAN_2026-11-27.md`, `docs/AI_AND_CALCULATIONS.md`, `docs/CALC_RELEASE_GATE.md`, `docs/OPEN_DECISIONS_DEFAULTS.md`, `docs/SECOND_DEVELOPER_ESTIMATE.md`
- **What it does:**
  - maps every field on the formulation, IID preview and checklist screens;
  - records one end-to-end browser run (SAMPLE losartan 100 mg, COZAAR as reference);
  - confirms no AI touches a number or status;
  - adds the release-gate answers, the five decision defaults and the second-developer estimate.
- **Tests:**
  - **Old code failed for the right reason:** not applicable.
  - **Full local CI:** pass (company_site jobs; docs only).
  - **Browser:** the run itself. All 15 calculated values match the hand working.
- **What could go wrong:**
  - **Behaviour:** none.
  - **Stale notes:** a few lines say `docs/OPEN_ISSUES_PLAN.md` is "in #176, not merged yet". #176 is now merged, so those notes are out of date, though harmless.
- **Depends on:** nothing.

## #180 — Credential register correction (docs)
- **Files:** `docs/CREDENTIAL_INVENTORY.md` (one line)
- **What it does:** row P1 now says the committed `.env` holding the Google key was removed in `89dbf8b` (2026-04-08), not `337a54e`.
- **Tests:**
  - **Old code failed for the right reason:** not applicable.
  - **Full local CI:** pass (company_site jobs).
  - **Browser:** not applicable.
- **What could go wrong:** nothing.
- **Depends on:** nothing.

---

## #167 — Supersede on an approved execution needs a confirmation and a typed reason
- **Files:** `backend/iig_checklist/migrations/0009_execution_supersede_reason.py`, `models.py`, `serializers.py`, `services.py`, `views.py`, `tests/test_execution_supersede_reason.py`; `frontend/src/app/(regx)/iig-checklists/executions/[executionPublicId]/page.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/api/execution-mappers.ts`, `frontend/e2e/iig-execution-supersede.spec.ts`
- **What it does:** superseding an approved execution opens a dialog that names it and needs a typed reason. The server refuses a missing reason (400 `missing_supersede_reason`), and stores the reason with its audit event in the same transaction.
- **Tests:**
  - **Old code failed for the right reason:** yes. One click superseded with no reason (7 backend tests; no dialog in Playwright).
  - **Full local CI:** pass. Backend 4,977 passed; Playwright 272; docker integration.
  - **Browser:** pass. API refusal, dialog, Cancel, supersede with the reason shown, audit row checked.
- **What could go wrong:**
  - **Users will notice:** an extra confirmation step.
  - **API clients:** any client calling supersede without a reason now gets 400.
  - **Migration `0009`:** adds one blank text field, and existing superseded executions keep an empty reason. Rollback = `migrate iig_checklist 0008`, which drops stored reasons, then revert.
- **Depends on:** nothing. **Must merge before #174.**

## #174 — VP can reinstate a superseded execution
- **Files:** everything in #167, plus `backend/iig_checklist/migrations/0010_execution_reinstate.py`, `audit.py`, `execution_transitions.py`, `permissions.py`, `urls.py`, `tests/test_execution_reinstate.py`, `tests/test_execution_reinstate_race.py`, `frontend/e2e/iig-execution-reinstate.spec.ts`
- **What it does:**
  - A VP can reinstate a superseded execution with a typed reason, recorded in the audit trail in the same transaction. The history and the supersede reason are kept.
  - It is refused (409) while another execution for the same checklist version and formulation is in progress or approved. The database's unique indexes make two live executions impossible even under simultaneous requests.
- **Tests:**
  - **Old code failed for the right reason:** yes. All 16 reinstate tests fail on the old code, and all 4 race tests fail with the database guard removed.
  - **Full local CI:** pass. Backend 4,997 passed; vitest 645; Playwright 275; docker integration.
  - **Browser:** pass, all 8 checks, including refusal while another execution is live and both reasons on screen.
- **What could go wrong:**
  - **A new power:** a VP can bring a superseded execution back.
  - **Changed wording:** #167's dialog no longer says "This cannot be undone." A test was updated to match.
  - **Migration `0010`:** adds three blank or null fields. Rollback = `migrate iig_checklist 0009`, which drops reinstate data, then revert.
- **Depends on:** **#167 must merge first.** The diff then shrinks to this PR's own changes.

## #169 — Five small issues from the 2026-11-25 regression
- **Files:** `backend/iig_checklist/serializers.py`, `backend/iig_checklist/tests/test_version_actor_emails.py`; `frontend/src/app/(regx)/documents/page.tsx`, `formulations/[publicId]/page.tsx`, `iig-checklists/versions/[versionPublicId]/page.tsx`, `frontend/src/lib/api.ts`; unit tests `documents-list`, `fda-iid`, `iig-checklists`, `tenant-navigation`; `frontend/e2e/small-fixes-2026-11-26.spec.ts`
- **What it does:**
  - N-9: the reference-product line is no longer labelled "REVIEWER CONFIRMED".
  - QA-13: the submitter no longer sees Approve, Reject or Return on their own version.
  - N-4: the version page shows who submitted, approved and activated.
  - N-5: list-shaped errors are shown, not "Request failed".
  - N-7: a signed-out documents page sends the user to sign-in.
- **Tests:**
  - **Old code failed for the right reason:** yes, for each of the five (vitest, backend KeyError, 3 of 4 Playwright).
  - **Full local CI:** pass. Backend 4,972 passed; vitest 652; Playwright 275; docker integration.
  - **Browser:** pass, all five.
- **What could go wrong:**
  - **Users will notice:** missing buttons for the submitter, a different label, and a redirect to sign-in.
  - **API:** gains read-only fields (additive). No migration. Rollback = revert.
- **Depends on:** nothing. It hides the buttons; #173 enforces the same rule on the server.

## #173 — The submitter cannot reject or return their own checklist version
- **Files:** `backend/iig_checklist/views.py`, `backend/iig_checklist/tests/test_submitter_cannot_reject_or_return.py`
- **What it does:** the server refuses Reject and Return by the person who submitted the version (400 `submitter_cannot_reject` / `submitter_cannot_return`). Self-approval was already refused.
- **Tests:**
  - **Old code failed for the right reason:** yes. Reject and Return by the submitter were accepted.
  - **Full local CI:** pass. Backend 4,976 passed; docker integration. No frontend change.
  - **Browser:** pass. Both refused with the sentence on screen and the status unchanged; control: another person can return it.
- **What could go wrong:**
  - **Small teams:** someone who holds both roles needs a second person to reject or return their own submission. Versions already under review that were submitted by such a person wait for someone else.
  - **Not covered:** checklist **executions** (§12 question).
  - **Data and rollback:** no migration. Rollback = revert.
- **Depends on:** nothing. Pairs with #169.

## #175 — Compose ports on 127.0.0.1 only
- **Files:** `compose.yaml` (7 lines)
- **What it does:** every service port is published on this machine only (`127.0.0.1`) instead of all network interfaces. Before, Postgres, Redis and the app were reachable from the local network while a developer stack ran.
- **Tests:**
  - **Old code failed for the right reason:** not a code test. The exposure was found in the compose settings. After the change, the LAN address is refused (curl exit 7) while localhost answers 200.
  - **Full local CI:** pass. Backend 4,970 passed; company_site jobs; docker integration; frontend pass on the second run (one flaky `tenant-gate` unit test on the first run, unrelated).
  - **Browser:** integrated Playwright, 20 of 20.
- **What could go wrong:**
  - **Developers will notice:** opening the stack from a phone or a second laptop no longer works; that needs a deliberate local override.
  - **Servers:** a server that relies on these compose ports from outside would lose access. Nothing in the repository does.
  - **Rollback:** revert.
- **Depends on:** nothing.

## #172 — Hook that blocks heredocs and stdin Python in Claude Code sessions
- **Files:** `.claude/hooks/block_stdin_scripts.py`, `.claude/hooks/test_block_stdin_scripts.py`, `.claude/settings.json`, `.gitignore`
- **What it does:** a check that runs before every shell command in a Claude Code session. It blocks heredocs and Python read from standard input, so scripts are always files that can be kept and re-run.
- **Tests:**
  - **Old code failed for the right reason:** yes. 25 failures before the hook existed; with it, 14 blocked, 10 allowed, 0 failures.
  - **Full local CI:** pass (company_site jobs).
  - **Live:** it blocked two real slips in this session.
- **What could go wrong:**
  - **Scope:** it affects only Claude Code sessions in this repository.
  - **False positives:** it also blocks a harmless command with `<<` inside quoted text; rewording gets past it.
  - **Rollback:** revert.
- **Depends on:** nothing.
