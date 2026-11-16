# Work Log archive

Entries moved unchanged and in order from the Work Log in `PROJECT_OVERVIEW.md` on 2026-11-16 (every entry dated before 2026-11-01). New entries always go into `PROJECT_OVERVIEW.md`; this is the only other log file allowed (`CLAUDE.md`, session end rule).

### 2026-10-08 — Discovery session (Claude Code, read-only)

**Setup**
- Ran `git fetch`. The local branch was already up to date with its own remote, but **71 commits behind `origin/regx-main`**.
- Analysed `origin/regx-main@732133f` in a scratchpad git worktree. No tracked files in the user's checkout were touched.

**Repo state checked:** git status, branches, log, stashes, open PRs (none).

**Five parallel read-only investigations:** API routes, env vars and secrets, database and integrations, code quality and dependency audit (pip-audit, `npm audit --package-lock-only`), and status/SOW/handoff. Key claims were spot-checked by hand:
- The flag is missing from code.
- SOW payment and timeline terms.
- The leaked key is at the `origin/main` tip.
- The public schema.

**Built and ran the stack** under a separate compose project, `regx-discovery`, with fresh volumes and the user's `.env`:
- migrate and demo seed
- sign-in through :8000 and :8080
- tenant isolation
- self-registration, tenant creation and login throttling probes

**Ran checks:** ruff, ruff format, import-linter, frontend type-check, lint, vitest, build, Playwright E2E, and the backend pytest suite. Results are in §9.

**Files created**
- `PROJECT_OVERVIEW.md` (this file).
- `CLAUDE.md` was created earlier the same day and updated to match regx-main.
- No existing file was modified. No lockfile changed (`package-lock.json` hash identical before and after `npm ci`).

**Left behind (all disposable)**
- Scratchpad worktree.
- Docker project `regx-discovery`: 7 containers plus volumes `regx-discovery_*`.
- `regx-discovery-*` images.
- Playwright Chromium in the user cache.

**Suggested first steps for the next session** (not done; they change code or config):
1. Rebase onto regx-main. *(Done 2026-10-08.)*
2. Bump Next to 15.5.x and Django to 5.2.x patch releases.
3. Add login throttling.
4. Decide on registration and MFA policy.
5. Make migrations run on deploy.

### 2026-10-08 — Cleanup, scope correction, Part 2 gap matrix (Claude Code)

**Owner-approved cleanup:**
- Ran `docker compose -p regx-discovery down -v`. The 7 containers, 3 volumes and the network were removed, and the 4 `regx-discovery-*` images were deleted (re-check showed 0 of each remaining).
- Removed the scratchpad worktree with `git worktree remove --force` (it held only build output and `node_modules`), then ran `git worktree prune`.
- Switched the checkout to `regx-main` and fast-forwarded it to `origin/regx-main@732133f`.
- **Untracked files survived unchanged**, verified by sha1 before and after: `CLAUDE.md`, `PROJECT_OVERVIEW.md`, `diagnose.py`, `gpt_input_data.xlsx`, `gpt_input_data_pending_only.xlsx`.
- Local branch `regx/feat/legacy-port-and-sso` was kept.
- Not removed: Playwright Chromium in the user cache.

**Scope correction (owner statement):**
- REGX = SOW Part 2 plus applicable §4/§5.
- Rewrote §0, §1, §10 and §11 item 1 accordingly.
- Dropped the "contract not delivered" framing for Parts 1 and 3 and replaced it with open question §12.8: "Where does the 483 AI live, if anywhere?"
- Added §12.8a on whether a phase-2 scope or date was agreed.
- Noted that Part 2 has no fixed contractual date (§2.11).

**Untracked files inspected (read-only, stdlib zip/XML parsing; nothing installed):**
- `diagnose.py` is a legacy-`main` diagnostics script.
- The `gpt_input_data*.xlsx` workbooks are cost dry-runs for the legacy 483 observation summariser (gpt-4.1-mini). Assumption: SOW §1, not §2.6.
- No secrets in either.

**New finding:** `ENABLE_OBSERVATION_SUMMARIES` exists on legacy `main` (`4193f09`) but was never ported to `company_site/` on regx-main. Corrected §7 and §11 #10 in this file, and the matching line in `CLAUDE.md` (untracked).

**Added §13, the SOW Part 2 gap matrix:**
- 34 rows covering 2.1–2.10, 4.2–4.4 and 5.1, each verified against code.
- Confirmed **zero LLM/AI code paths in REGX**.
- Confirmed the P7 gap score is deliberately withheld pending an approved formula.
- Confirmed that no audit API or export exists.
- Confirmed that MFA is opt-in only, that login and logout are not audited, and that §5.1 latency has never been measured.
- Added the build order and the 5 unblocking client questions.

**No tracked file was changed.** No dependencies were installed, and `OPENAI_API_KEY` was not set anywhere.

### 2026-10-12 — Security patching: items 1 (Next.js) and 2 (backend) (Claude Code)

**Item 1: Next.js → PR [#78](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/78)** (branch `regx/fix/nextjs-security-patch`; open, not merged)
- **Versions** (looked up live): next and eslint-config-next 15.1.0 → 15.5.27. React 19.2.8 is unchanged because it already satisfies the peer range.
- **`next-env.d.ts`:** committed as Next 15.5 regenerates it. `next build` and `next dev` write the same line. `tsc` passes on a fresh checkout without `.next`.
- **Checks:** type-check, lint, vitest 555/555, build and Playwright E2E 257/257 all pass. npm audit 15 → 14 (critical 3 → 2).
- **Production image:** `docker compose up --build` gave 7/7 services healthy, with the container on next 15.5.27.
- **Browser check through `:8080`** (headless Chromium, real `/signin` form): `/dashboard`, `/iig-checklists` and `/documents` rendered their real headings and content with no failing API calls.
- **CI on #78 is green:** "Type-check, lint, build, E2E" and the production Docker-stack job.

**Item 2: backend → branch `regx/fix/backend-security-patch`, commit `609c0c0`** (local; **not pushed**, awaiting owner review)
- **Versions:** Django 5.2.3 → 5.2.18, DRF 3.15.2 → 3.18.3, pypdf 5.1.0 → 6.20.0 (there is no patched 5.x), cryptography 44.0.3 → 50.0.2.
- **Checks:** pip check clean, ruff and format clean, lint-imports 16/16, `makemigrations --check` no changes, `manage.py check` clean. Full suite 4033 passed / 1 skipped in 18m57s, identical to before.
- **pip-audit:** `base.txt` 90 → **0**. `dev.txt` has 1 left (pytest 8.3.5, out of scope).
- **Real-PDF check:** a 3-page Chromium-printed PDF uploaded via `POST /api/regx/v1/documents/` on the running stack. Celery scan went clean, processing completed, and 3 page locators hold the correct text per page. `source_metadata` holds page_count 3 plus Title, Creator and Producer.

**Findings along the way (not fixed; follow-ups):**
- **`seed_regx_demo` crashes** with `Role.MultipleObjectsReturned` when a tenant-scoped role shares a system role's name (`seed_regx_demo.py:246` looks roles up by name only).
  - The local DB has such copies (doer, vp, tenant_admin) in tenant `praverse-demo`.
  - Fix: filter on `tenant__isnull=True`. Small, and needs its own PR.
- **`handoff.md` gives the wrong tenant for the `sso.*@praverse.test` accounts.** It says `X-Tenant-Slug: praverse`; the accounts are members of `praverse-demo`.
- **`documents/tasks.py:328-330` swallows `extract_text()` errors silently.** A broken parser would show only as empty text. This is the existing §11 item 15.
- **Django 6 deprecation:** `CheckConstraint.check` → `.condition` in `formulations/models.py:149,208,233` and `templates_registry/models.py:484`. These were already warnings before the upgrade.
- **`next lint` is deprecated** and is removed in Next 16; migrate with `npx @next/codemod next-lint-to-eslint-cli` at that upgrade.

**Local environment state:**
- The normal `regx` compose stack is running.
- The local `regx_postgres_data` volume was migrated, gaining the 2 pending migrations (`fda_data.0004`, `iig_checklist.0008`).
- One test document now exists in tenant `praverse-demo`.
- The backend and celery images are built from the backend branch; the frontend image is built from the Next branch.

**Items 3–5 have not been started.**

**Review hand-off and session rule:**
- **Session rule added to `CLAUDE.md`** (owner request): at the start of every session, delete `review-handoff/` and `review-handoff.zip` without reading them.
  - This session: neither existed at the start.
- **Built `review-handoff/` and `review-handoff.zip`** at the repo root as the last step, using forward-slash zip entries.
  - They are ignored through `.git/info/exclude` (local), not `.gitignore`, so neither PR carries an unrelated change.
  - They sit outside the tsconfig, ESLint and ruff scopes (`frontend/`, `backend/`).
- **`docs/log/backend.md` does not exist on any branch.** The hand-off uses this Work Log section in its place. Owner to decide whether that log file should be created.
- **No migrations and no tests** were added or changed this session.
- **Docker stack stopped** at session end with `docker compose stop`. Volumes are kept.

### 2026-10-12 (second session) — MFA compatibility check, PR #79, items 3–5 (Claude Code)

**Session start rule:** deleted `review-handoff/` and `review-handoff.zip` from the previous session without reading them.

**Step 1: MFA Fernet compatibility across cryptography 44.0.3 → 50.0.2. Result: PASS.**
- On the old image (`regx-main`), enrolled `sso.vp@praverse.test` via `POST /mfa/enrol/` + `/mfa/verify/`. A 140-byte Fernet token was stored, with 10 recovery codes.
- Rebuilt the backend from `regx/fix/backend-security-patch` on the same `regx_postgres_data` volume.
- Fresh login, then `/mfa/verify/`: a valid TOTP returned 200 and a wrong code returned 400 "Invalid OTP.". Direct decryption with 50.0.2 returned the secret whose SHA-256 fingerprint matched the one taken at enrolment.
- **Test enrolment removed:** device and 10 recovery codes deleted, `mfa_required` reset. The DB has 0 MFA devices again. The secret file was deleted.
- **Harness note:** Python's cookie jar would not send the production `Secure` session cookie over http to localhost, so the script carries cookies by hand. That was harness-only, not an app issue.
- **New finding:** `login_view` never checks MFA. See §11 #8.

**Step 2: PR [#79](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/79) opened** for `regx/fix/backend-security-patch`. Its description is the commit message plus the MFA result. Not merged. CI is green: "Lint, type-check, and test" and the Docker stack job.

**Step 3: `CLAUDE.md` gained a "Session end rule".** It covers the review hand-off structure and the `.git/info/exclude` entries, and states that the Work Log is the only session log (no `docs/log/`).

**Step 4: items 3–5.** Each is on its own branch from `regx-main`, **committed locally and not pushed**, awaiting owner review.

| Item | Branch / commit | What | Verification |
|---|---|---|---|
| 3 login throttling | `regx/fix/login-throttling` `e5ee2f7` | Per-account lockout (normalised email): 5 failures in 15 min → locked 15 min, 429 + `Retry-After`. Correct password refused while locked. Success resets the counter. Django cache with atomic `incr` | 7 new tests (12-attempt block, Retry-After, refused-while-locked, success after window via freezegun, reset, per-account + case-insensitive, unknown email). Full suite **4040 passed / 1 skipped**. **Live:** 400×5 then 429×7; locked at 08:18:53 UTC, correct password at 08:37:29 → 200 |
| 4 schema behind login | `regx/fix/schema-requires-login` `edaee21` | `production.py` only: `SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"]=[IsAuthenticated]` | 4 new tests (production and development modules read in a subprocess, so the shared `LOGGING` dict isn't mutated). Full suite **4037 / 1**. **Live:** anonymous `/api/schema/` and `/api/docs/` → 403 on :8000 and :8080; signed in → schema 200 (273 operations), Swagger page 200 |
| 5 stub scanner | `regx/fix/stub-scanner-guard` `8ac9987` | Startup WARNING from `documents/apps.py` in every process running the stub. `check_env.py --production` fails on the stub or `ALLOW_STUB` (default mode unchanged). 2 new CI cases. `DEPLOYMENT_BOUNDARIES.md` §3/§7/§8 | 2 new tests. Full suite **4035 / 1**. `check_env` exercised in 6 modes. Workflow YAML parses. **Live:** warning logged once per process (2 gunicorn workers + 1 celery), showing `ALLOW_STUB=True` |

**Item 3 decision: shared login from company_site.**
- I chose **per-account, not per-IP**, keying. Behind nginx every browser login comes from nginx's container IP, and every company_site delegation comes from company_site's container IP with the user's real IP not forwarded. So an IP limit would lock everyone out at once.
- **Verified live:**
  1. `sso.doer` via `/adminmaster/login/` → 302 to `/ratools/`.
  2. A locked account via company_site is refused. `regx_auth` treats the 429 as "REGX unavailable" and falls back to the local check, which fails closed for mirrored accounts.
  3. Another user through the same company_site server immediately afterwards → 302, unaffected.
- **Trade-off:** someone who knows an email can lock that account for 15 minutes.
- A throwaway user (`lockcheck@example.invalid`) was registered for the live test and **deleted afterwards**.

**Seed/role investigation (per owner; no fix started):** see §11 #25. The tenant-scoped `doer`/`vp`/`tenant_admin` roles were created by an ad-hoc shell script on 2026-09-09 (Assumption, strongly supported by timestamps). No committed code path can create them.

**Other notes:**
- `scripts/check_env.py` has one pre-existing E501 / format issue on an untouched line (not linted by CI). Left alone.
- The `docs/DEPLOYMENT_BOUNDARIES.md` §3 claim that compose does not set the `DOCUMENT_CLAMAV_*` variables is still wrong (it does). Noted, not changed: separate change.

**Local state at session end:**
- The backend and celery images are built from `regx/fix/stub-scanner-guard`; the frontend image from the Next branch.
- The checkout is on `regx/fix/stub-scanner-guard`.
- The stack is stopped with `docker compose stop`.

**Open owner decisions:**
- MFA enforcement (now including enrolled users).
- Closing open registration and tenant creation.
- Credentials and the `main` branch.
- A company_site dependency upgrade plan.
- The compose `ALLOW_STUB` default.

**Cleanup note:** my `env -i … check_env.py` test cleared every environment variable, including `SystemDrive`. Windows then wrote Explorer cache files (4 `.db` files, 976 KB) into a literal `%SystemDrive%/ProgramData/...` folder at the repo root. It was untracked and is now deleted. **Do not use `env -i` on this Windows machine**; unset only the specific variables a test needs.

### 2026-10-12 (third session) — Orange Book Phase 1: discovery and plan (Claude Code)

**Session start rule:** deleted the previous `review-handoff/` and zip without reading them.

**Phase 1 (read-only).** Plan committed on `regx/feat/orange-book-plan` (`aedf6ea`, local, **not pushed**): `docs/ORANGE_BOOK_PLAN.md`.

**FDA live check** (<https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files>, "content current as of 08/18/2026"):
- One ZIP containing `Products.txt` (14 fields), `Patent.txt` (10) and `Exclusivity.txt` (5); tilde-delimited ASCII.
- No ZIP update frequency is stated.
- A scripted download (`/media/76860/download`) was redirected to FDA's abuse-detection page and ended in a 404. **No circumvention was attempted.** Actual header names remain unverified, and the 10-byte "Not Found" body that was saved was deleted.

**Importer gaps found** (code-verified):
- `Type` (RX/OTC/DISCN) is ignored, so discontinued is always False on real files (`adapters.py:48`).
- `approval_date` is never parsed.
- `Applicant_Full_Name` is not required.
- RLD/RS parsing expects `Yes`, but the FDA page says these products are "identified by 'RLD'". Unconfirmed.
- No `trade_name` or `application_number` filter.
- Reference-product selection is not validated (`formulations/serializers.py:69-74`).

**Beat:** no REGX Celery beat exists (`compose.yaml:92` runs the worker only; no beat schedule or package).

**Legacy white paper** (read-only agent review plus my own spot-check):
- It is a manual form plus maker/checker workflow.
- **No calculations** (the JavaScript only resizes text boxes; the view has no arithmetic), no Orange Book or IID data feed (values are typed in; patents/exclusivity are screenshot uploads), and no OpenAI.
- The SOW's "calculations like in white paper" therefore has no existing formula. The plan's §6 is a spec with 7 open questions for iCretegy.

**Owner decision recorded:** the public FDA download is the primary Orange Book source (iCretegy confirmed in writing, per the owner). §13 row 2.5b is now "Agreed: public FDA source", the Excel adapter is removed from planned work, and §12 lists it as resolved. No Excel importer will be built.

**`CLAUDE.md`:** the session end rule now replaces a leading `.` in copy names with `dot`.

**Decisions waiting for the owner:**
- Phase 1b (products fidelity) before or after Phase 2.
- FDA's automated-access terms (they gate Phase 4).
- Where iCretegy's written confirmation is stored.

**State:** no code changed. The stack was not started this session. The checkout is on `regx/feat/orange-book-plan`. The security branches (items 3–5) were untouched.

### 2026-10-12 (fourth session) — hand-off rule rewrite, white-paper spec; Phase 1b blocked (Claude Code)

**Session start rule:** deleted the previous `review-handoff/` and zip without reading them.

**Part A: session end rule rewritten in `CLAUDE.md`.** The hand-off now includes, as full files:
- **changed:** every file created or modified on any branch;
- **cited:** every file a finding or claim rests on;
- **report:** sub-agent reports in full, extracted from the transcript by script;
- **evidence:** every script and its raw output;
- one patch per commit, and the session's Work Log section.

It also adds:
- a MANIFEST row per file: real path, branch/source, category, why;
- a final citation check that greps the Work Log, the plan and new docs for paths and lists any without a copy;
- secret redaction, with `.env*` excluded;
- a 5 MB head/tail rule;
- no hidden names.

**Builder:** `handoff_builder.py` in the scratchpad (spec-driven), included as evidence in each hand-off.
- **Fix during the build:** the first version's `django-insecure-` pattern redacted its own regex text in the evidence copy. The pattern is tightened to require a real 20+ character key.
- **Phase 1 hand-off rebuilt under the new rule:** 75 files, 320,521 bytes. Citation check: 16 mentions, 15 resolved; the 1 unresolved is FDA's `abuse-detection-apology.html` web path, not a repo file.
- **Redactions:** the insecure-key default in `company_site/RAAI/settings.py`, and 4 test-fixture passwords in `backend/fda_data/tests/conftest.py`. These are not real secrets, but the rule redacts any password. Both are noted in the MANIFEST.

**Part B: Phase 1b importer fixes: BLOCKED, nothing built.**
- The prompt's ZIP path was the unfilled placeholder `<PATH_TO_ZIP>`. Per instructions, I did not download from fda.gov.
- A filename-only search (`EOBZIP*`, `*orange*book*.zip`, `Products.txt`) of `D:/Praverse`, Downloads, Desktop and Documents found nothing.
- The branch `regx/fix/orange-book-importer` has not been created. The plan's §1 still lists the real headers and values as unverified.

**Part C: white-paper spec.** `docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md` on `regx/feat/orange-book-plan` (`6eee2dc`, local, not pushed) gives a proposed answer to each of the 7 questions:
- RLD/RS auto-filled from the Orange Book (read-only, source release shown);
- patents and exclusivity as structured data, dated "per FDA data dated X";
- the Doer → Reviewer → VP chain kept;
- three non-judgemental calculations: strength match, total daily intake, % w/v;
- IID limit comparisons left to the IIG engine;
- the question bank versioned in the template registry;
- Part 11 controls with no attestation;
- a fixed conclusion wording.

Plan §6 now points to the spec. It is ready to send to iCretegy.

**Open:** the location of iCretegy's written confirmation (`<PATH_FROM_PRATHAM>` was not filled in); it stays an open question in §12.

**State:**
- The checkout is on `regx/feat/orange-book-plan`. The stack was not started.
- The security branches (items 3–5) were untouched; PRs #78 and #79 are unchanged.

### 2026-10-12 (fifth session) — real Orange Book file, openFDA research, Phase 1b importer fixes (Claude Code)

**Session start rule:** deleted the previous `review-handoff/` and zip without reading them.

**Input file (filename-only search, exactly one match):**
- Path: `D:/Praverse/data/fda/orange-book/2026-10-12/EOBZIP_2026_08.zip`
- Size: 1,097,768 bytes
- SHA-256: `84e616aacf4f42bb85a94586c10abfc260f8fb9b60f07db3f10315ae70a3298e`
- The ZIP was not copied into the repo. Nothing was downloaded from fda.gov file pages. It was extracted, for reading only, into a scratchpad folder outside the repo.

**Part 1: real files inspected.** Plan §1 was rewritten from verified facts only, and the assumptions were removed.
- **Format:** members are lower-case `products.txt` / `patent.txt` / `exclusivity.txt`, timestamped 2026-09-11. ASCII, CRLF line endings, no final newline, tilde-delimited.
- **Rows:** products 48,761 (14 columns), patents 22,303, exclusivity 2,400.
- **Type:** RX 24,757 · DISCN 23,217 · OTC 787.
- **RLD and RS:** only `Yes`/`No`. **The existing RLD/RS parsing was already correct**, so that risk is closed.
- **Approval dates:** 5,873 are "Approved Prior to Jan 1, 1982"; everything else parses. Patents have 2,805 empty submission dates.
- **Integrity:** no orphan patent or exclusivity rows, and every value fits its column.
- Plan branch commit `bd3be2e`.

**Part 2: openFDA research** (official pages plus 9 of the 30 allowed calls, no key). Plan §2b.
- **An official Orange Book endpoint exists:** `api.fda.gov/drug/orangebook.json`, covering products, patents and exclusivity. It has 48,761 records, matching the ZIP's product count; `last_updated` 2026-10-07.
- **3 products compared field by field:** no data mismatches. The 6 differences are all `Type` vocabulary ("HUMAN PRESCRIPTION DRUG" / "DISCONTINUED").
- **Schema vs data gaps:** `marketing_status` is undocumented, and the `*_definition` fields are absent.
- **Limits and terms:** 1,000 calls/day without a key, 120,000 with a free key. Terms don't explicitly address automated use, and every response says "assume all results are unvalidated".
- **Recommendation:**
  - (a) the ZIP stays the source of record;
  - (b) openFDA Orange Book as an optional lookup cross-check;
  - (c) `download.json` `export_date` drives "new data available" alerts that prompt an operator upload.
- **Plan impact:** not material for Phase 1b. Phase 4 changes from a ZIP download (blocked) to detection plus operator upload. That's why I continued to Part 3.

**Part 3: Phase 1b.** Branch `regx/fix/orange-book-importer`, commit `86a71e4`, local, **not pushed**.
- **Changes:**
  - `Type` is a required column, stored as `marketing_category`, and DISCN → `discontinued`;
  - approval dates are parsed, while unparseable ones are kept, flagged (`approval_date_unparsed` on the row result) and logged;
  - new `trade_name` and `application_number` search filters;
  - reference selection is validated against a real product in the active release.
- **Migration** `0005_orangebookproduct_marketing_category`, additive. Applied, rolled back to `0004` and re-applied on the local DB.
- **Fixtures:** copied byte-for-byte from the real file, with a `.gitattributes` `-text` rule so git keeps the CRLF bytes. Verified committed as `i/crlf`.
- **One existing test changed on purpose:** `test_select_reference_product_requires_explicit_call_never_auto` sent random UUIDs and expected 200. That was the bug.
- **Results:** `fda_data` + `formulations` 241 passed. **Full suite 4073 passed / 1 skipped** (+40 tests). ruff, format and lint-imports clean.
- **My own test bug, found and fixed before committing:** the helper's argument name collided with a payload key. The first run had 6 failures in the new file.

**Open:**
- Where iCretegy's written confirmation is stored (§12).
- Whether to register an openFDA API key.
- Whether openFDA bulk JSON may ever be a source (recommended: no).

**State:**
- The checkout is on `regx/fix/orange-book-importer`.
- The local stack has postgres, redis and backend running (backend built from this branch); everything is stopped at the end of the session.
- The local DB is migrated to `fda_data.0005`.
- The security branches and PRs #78 and #79 are untouched.

### 2026-10-12 (sixth session) — PRs #80/#81, locale-independent dates, Phase 2 real-data load (Claude Code)

**Session start rule:** deleted the previous `review-handoff/` and zip without reading them.

**Step 1: PRs** (not merged)
- **[#80](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/80)** `regx/fix/orange-book-importer`: importer fixes, add-column migration `0005` (reversible), one test changed on purpose.
  - **CI green:** "Lint, type-check, and test" passed in 33 m 34 s, with the full suite at **4075 passed, 2 skipped**; "Build, start, and verify the production compose stack" passed.
- **[#81](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/81)** `regx/feat/orange-book-plan`, docs only.
  - **No CI checks ran:** the workflows trigger on code paths only, the same as the earlier docs-only PRs.

**Step 2: locale.** Commit `d98608d` on #80.
- **The risk was real.** Under a German `LC_TIME` on this Windows host, `strptime("Oct 18, 2019", "%b %d, %Y")` failed ("does not match format").
- **Fix:** `parse_approval_date` now uses a fixed English month table, with no locale-aware call.
- **Tests:** all 12 months, an impossible date, and parsing under a non-English locale. The last one skips on Linux images, which have only C/POSIX, and that is documented in the test.
- `fda_data` + `formulations`: 243 passed, 1 skipped. Lint clean.

**Step 3: Phase 2, real products data on the local stack.**
- **Stack:** backend and celery built from `regx/fix/orange-book-importer` (`d98608d`); the frontend image is the existing one from the Next branch and wasn't needed. Migration `0005` was already applied, and nginx was restarted.
- **Source:** `D:/Praverse/data/fda/orange-book/2026-10-12/EOBZIP_2026_08.zip` was copied into the backend container's `/tmp` only (not the repo). In-container SHA-256 `84e616aacf4f42bb85a94586c10abfc260f8fb9b60f07db3f10315ae70a3298e`.
- **Dry run:** 48,761 rows parsed in about 2 s. Then `import_fda_release --dataset-type orange_book_products --source-name "FDA Orange Book, August 2026 edition" --source-reference …`.
- **Release `6d9fe36b-839d-4ced-8b7c-f3b326243be0`:**
  - extracted 48,761, imported 48,761, failed 0;
  - **import time 5 min 50 s** (11:05:53 → 11:11:43 UTC);
  - normalized payload SHA-256 `eec160b189cd88ec1c58e41bd1b536dcaa251ec04c07896136db91c6daaa5a97`;
  - 27,376 applications.
- **Lifecycle, via the API, tenant `praverse-demo`:**
  - `sso.doer`: validate → submit-review;
  - `sso.vp`: approve (11:12:15 UTC, with the dates in `notes`) → **activate** (11:12:16 UTC).
  - `platform_support` has no FDA-data permissions, so the chain is Doer → VP by design.
- **Release fields** (existing fields only):
  - `source_name` holds the label;
  - `original_filename` = `EOBZIP_2026_08.zip`;
  - `official_source_reference` holds the FDA URL, page date 08/18/2026, internal file date 2026-09-11 and download date 2026-10-12;
  - `retrieved_at` = 2026-10-12T11:05:55Z;
  - `notes` holds all the dates;
  - `publication_date` is **NULL**, because the command can't set it. A proposal is in §12.
- **Verification** (API unless marked DB):
  - **Counts:** 48,761 products. `discontinued=true` 23,217 and `discontinued=false` 25,544, matching the file.
  - **By category (DB, no API filter):** RX 24,757 · DISCN 23,217 · OTC 787. DISCN not marked discontinued: 0.
  - **Lookups:** `trade_name=AMZEEQ`, `application_number=NDA212379` and the discontinued `ANDA210928`. **0 mismatches** over 16 fields each against the raw file rows, and the applicant full names match (DB).
  - **Approval dates (DB):** NULL = **5,873**, all with the pre-1982 phrase; 0 NULL with any other text; **0 rows flagged `approval_date_unparsed`**.
- **New findings:**
  - **No approved terminology mappings.** 0 products have a normalised route or dosage form, and all 48,761 strengths are `review_required`, so the API's `route=` and `dosage_form=` filters return nothing.
  - **The release API hides** `original_filename`, the checksum, `notes`, `parser_identifier` and `publication_date`. *(Corrected in the seventh session: they are visible to `view_raw` holders, and only hidden from the Doer used in this check.)*
  - Both are in §12 / §13.
- **Only products were imported.** Patents and exclusivity are Phase 3, not started.

**Not touched:** PRs #78/#79, the security branches, company_site. The ZIP was not copied into the repo.

**State at session end:**
- The checkout is on `regx/fix/orange-book-importer`.
- **The local DB now holds the active real release.**
- The stack is stopped at the end of the session.

### 2026-10-12 (seventh session) — merges confirmed, branch inventory, security PRs #82–#84, terminology review, release metadata (Claude Code)

**Session start rule:** deleted the previous `review-handoff/` and zip without reading them.

**Step 0: sync.** `git fetch --all --prune`, then `regx-main` fast-forwarded `732133f` → `eedbf9c`.
- **PRs #78, #79, #80 and #81 are all MERGED (2026-10-12, 11:48–11:49 UTC), all as merge commits** (not squash or rebase). Each merge commit has two parents, and each PR head (`e44b7ca`, `609c0c0`, `d98608d`, `bd3be2e`) is an ancestor of `regx-main`.

**Step 1: branch inventory** (read-only; outputs in `branch-cleanup/`, excluded via `.git/info/exclude`)
- **Before cleanup:** 14 local and 88 remote branches, **91 distinct names**. PRs ever opened: 81, all MERGED (none open, none closed unmerged).
- **Categories:**
  - **KEEP 5:** `regx-main`, `main`, and the 3 local security branches, which had unpushed commits.
  - **SAFE TO DELETE 79:** merged PR with the tip equal to the merged head (squash-proof), or fully contained in `regx-main`.
  - **REVIEW 7:**
    - 3 legacy-`main` branches, all 0 ahead and merged (#45–#47);
    - `regx/design/milestone-4d-2-discovery`: 14 docs commits, all 4 files identical in `regx-main`;
    - `regx/feat/milestone-4d-3-discovery`: 20 docs commits, 1 file differs;
    - `regx/chore/milestone-4d-closeout`: 1 commit, 2 files differ;
    - `regx/feat/final-validation-release`: `c4fce03`, an nginx M9–M14 fix superseded by #64.
- `restore.sh` has 86 recreate lines (SAFE + REVIEW).
- **Nothing deleted; awaiting owner approval.** The REVIEW branches approved for deletion will get `archive/<name>` tags first.

**Step 2: security items 3–5** were rebased onto `eedbf9c` with **no conflicts**, re-tested, pushed, and opened as PRs (not merged):

| PR | Branch | Rebased commit | Local tests after rebase | CI (full suite; Docker) |
|---|---|---|---|---|
| [#82](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/82) | `regx/fix/login-throttling` | `3d46eb5` | identity + authorization 39 passed | **4082 passed / 2 skipped**; Docker pass |
| [#83](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/83) | `regx/fix/schema-requires-login` | `9c62f97` | common 110 passed | **4079 / 2**; Docker pass |
| [#84](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/84) | `regx/fix/stub-scanner-guard` | `6fd97f0` | documents 157 passed | **4077 / 2**; Docker pass; ops-scripts pass |

Harness note: my first combined `pytest common/tests/test_schema_access.py common` run reported only 4 tests. Re-running `common` alone gave 110 passed.

**Step 3: terminology mapping proposal** (read-only on data; nothing approved, created or loaded). Branch `regx/docs/terminology-mapping-review`, commit `c7ab8e8`, local.
- **How mapping works:** controlled codes plus mapping rows go proposed → reviewed → approved/rejected. Submitting for review needs Reviewer or VP; **approving is VP only**. Nothing is auto-approved, and mappings resolve **only at import**.
- **Findings:**
  - **The controlled vocabularies are empty** (0 routes, dosage forms and units). No code seeds them.
  - **There is no API to create route, dosage-form or unit mappings.**
  - **Approval won't update the 48,761 already-imported products** without a re-import or a new re-resolve step.
- **Proposals** (rules stated in the workbook; "unclear" used rather than guessing):
  - routes 79 (44 exact / 4 likely / 31 unclear; `INJECTION` alone is 7,231 products);
  - dosage forms 117 (99 / 1 / 17, the unclear being mostly combination packs);
  - units 52 (5 / 2 / 45).
- **Strengths:** 26,331 single number+unit, flagged only because no units exist. 22,430 in 592 other shapes; the top 30 come with proposed parsing rules, not implemented.
- **Workbook:** `D:/Praverse/data/fda/mappings/orange_book_terminology_review_2026-10-12.xlsx` (23,546 bytes; README plus Routes / Dosage forms / Units with the 9 requested columns and a Y/N dropdown, plus Strength patterns). Built in the backend container with openpyxl.
- **Guide:** `docs/TERMINOLOGY_MAPPING_REVIEW.md`. The planned loader only ever creates mappings in `proposed`; VP approval stays in-app.

**Step 4: release metadata.** Branch `regx/feat/fda-release-metadata`, commit `ce18aab`, local, **not pushed**.
- `import_fda_release --publication-date YYYY-MM-DD` fills the existing field (no migration). A bad date is refused before anything is written, and `--dry-run` writes nothing.
- **Correction of my own sixth-session finding:** file name, checksum and notes are **already** exposed read-only to `view_raw` holders (Reviewer, VP) and deliberately hidden from Doers (`test_default_serializer_hides_raw_source_fields`). I checked as a Doer last time.
  - My serializer change was **reverted** rather than break that rule.
  - New tests pin the visibility.
  - Exposing the fields to Doers is now an owner question.
- **Tests:** 9 new pass; `fda_data` 225 passed, 1 skipped. ruff, format and import contracts clean.

**Reported only:**
- `handoff.md` **is tracked** on `regx-main` (last changed in `b656f88`) and on `main`, with local demo passwords in plain text.
- Phase 3 not started. No mapping loaded.

**State:**
- The checkout is on `regx/feat/fda-release-metadata`.
- Local stack: postgres, redis and backend ran this session; stopped at the end.
- The local DB still holds the active Orange Book release.

### 2026-10-12 (eighth session) — branch cleanup done, PRs #85–#87, vocabulary research started (Claude Code)

**Session start rule:** deleted the previous `review-handoff/` and zip without reading them. Time budget: the owner asked to stop at 18:30 IST; the session started at 18:13.

**Step 1: branch cleanup (owner-approved), done.**
- **86 branches deleted** on GitHub and locally (79 SAFE + 7 REVIEW). No force-push. KEEP branches untouched.
- **Archive tags:** 7 annotated tags `archive/<name>` were created on the REVIEW tips, pushed, and **verified on GitHub before each deletion**:
  - `docs/setup-and-sow-status`, `fix/backend-wiring-and-deploy-hardening` (both at 6643851);
  - `fix/claude-md-db-setup-instruction` (0f3906d);
  - `regx/chore/milestone-4d-closeout` (ebc09da);
  - `regx/design/milestone-4d-2-discovery` (c46df2c);
  - `regx/feat/final-validation-release` (c4fce03);
  - `regx/feat/milestone-4d-3-discovery` (97653c0).
- **Errors:** 2 transient GitHub errors (`fatal error in commit_refs`). The retry deleted `regx/docs/p14b-documentation-consistency`. `regx/feat/deployment-environment-contract` had in fact been deleted by the first attempt (confirmed with `git ls-remote`).
- **Final: 8 branches on GitHub and 8 locally**, down from 91 names: main, regx-main, and the heads of open PRs #82–#87.
- `branch-cleanup/BRANCH_INVENTORY.md` and `restore.sh` were updated with a "deleted 2026-10-12" column and remain outside git.

**Step 4: demo passwords.** **PR [#85](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/85)** (`regx/chore/handoff-demo-passwords`).
- The 6 password cells in `handoff.md` now say "set via DEMO_PW at seed time". Nothing else changed.
- History is not rewritten. The PR asks for the local demo passwords to be changed.
- `git grep` for each value: **no other tracked file on regx-main contains them.**

**Step 2:**
- **PR [#86](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/86):** release `--publication-date` plus the visibility-pinning tests.
- **PR [#87](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/87):** the terminology guide, now with an **ON HOLD** note until the controlled vocabulary is decided.

**Step 3: controlled vocabulary research. Mostly NOT DONE (out of time).**
- Done: **no IID file exists** in the repo or `D:/Praverse/data/fda/`; the owner will download it.
- The INJECTION question is drafted in §12.
- **Still to do tomorrow:** FDA official route/dosage-form/unit sources, the exact-match comparison, IID comparison, the seeding proposal, `docs/TERMINOLOGY_VOCABULARY_DECISION.md`, and the regenerated workbook.

**Not done:** no mapping loaded or approved, no code list seeded, Phase 3 not started.

**State:** the checkout is on `regx/docs/terminology-mapping-review`. Services were not started this session.

### 2026-10-13 — controlled vocabulary research finished, decision doc, SPL workbook (Claude Code)

Continues the 2026-10-12 eighth-session prompt (Step 3 only; Steps 1, 2 and 4 were done yesterday).

**Session start rule:** no `review-handoff/` or zip from the previous session was present when checked; nothing was read.

**Step 3: controlled vocabulary research, done (read-only, nothing built).**
- **IID file:** the owner's download, `D:/Praverse/data/fda/iid/2026-10-12/iig_july_2026.zip` (382,910 bytes, sha256 `d08cf074…980c987e`). `IIR_OCOMM.csv`: 9,071 rows, members dated 2026-07-21. Extracted outside the repo; the ZIP was not copied into the repo.
- **Official sources:** the 4 FDA SPL pages (route 121 terms, page dated 10/29/2021; dosage forms 158, 02/03/2022; UCUM units 52, 10/24/2024; units of presentation 76, 03/27/2018). HTML tables, no licence stated. Saved and parsed as HTML; no fda.gov `/media/…/download` was used.
- **Exact matches (case-insensitive):** Orange Book routes 36/79, dosage forms 75/117, units 4/52. IID routes **59/59**, dosage forms **105/106** (only `DROPS`), potency units 2/23. The IID already uses SPL; the Orange Book does not.
- **INJECTION:** OB route `INJECTION` (7,231 products) and form `INJECTABLE` (7,995). SPL/IID have no injection route; injectables are named in the dosage form. In the IID, 42 routes appear next to injectable forms, including ORAL (2) and RECTAL (1). The proposed iCretegy answer is kept, with 3 conditions (fixed route list, never auto-pick the highest limit, reviewer confirms). **Risk:** as worded, an IV product could be checked against another route's higher limit.
- **Models:** route and dosage-form lists can be seeded **without a migration** (`code` = NCI code proposed, release-tracked via the existing `fda_route_terminology` / `fda_dosage_form_terminology` dataset types). **Units cannot be fully seeded** without a model change (no dimension for meq/IU/curie/rates, no version field, no per-presentation unit). A `load_spl_terminology` command is proposed, **not built**.
- **Finding:** `IID_REQUIRED_COLUMNS` in `backend/fda_data/parsers.py` does not match the real IID header, so an import would fail (header comparison only; no import run). Logged in §11 #19a. Not fixed.

**Outputs:**
- `docs/TERMINOLOGY_VOCABULARY_DECISION.md` on new local branch `regx/docs/terminology-vocabulary-decision`, commit `0cc3508`. **Not pushed; awaiting review.**
- New workbook `D:/Praverse/data/fda/mappings/orange_book_terminology_review_spl_2026-10-13.xlsx` (outside the repo; the 2026-10-12 file is kept). Counts (exact / likely / unclear): **routes 36 / 9 / 34, dosage forms 75 / 10 / 32, units 4 / 14 / 34.**
- Overview updated: §10, §11 (#19a new, #23 done), §12, §13 (2.2a, 2.5a), §14 (1d, 1e new, 3).

**Environment notes:**
- Docker was not running, so the workbook was written with openpyxl from a throw-away venv in `D:/Praverse/session-work/2026-10-13/venv` (outside the repo; no lockfile touched). Services were not started.
- The session's temporary scratchpad became unavailable mid-session. Working files were copied to `D:/Praverse/session-work/2026-10-13/` (outside the repo) and the scripts were re-run there.
- **Hand-off builder fix:** its OpenAI-key pattern matched `risk-evaluation-…` inside saved FDA page URLs (4 false redactions). Added a word-boundary guard (`(?<![A-Za-z0-9])sk-…`); real `sk-…` keys still match (checked).

**Not done (per the prompt):** no mapping loaded or approved, no code list seeded, Phase 3 not started. The INJECTION question has not been sent to iCretegy.

**Waiting on the owner:** review and push `regx/docs/terminology-vocabulary-decision`; merge PRs #82–#87; decide on SPL adoption and `code` = NCI code; send the INJECTION question; give the SPL workbook to the regulatory reviewer.

### 2026-10-13 (second session) — decisions recorded, PR #88, IID importer fixed, SPL loader built (Claude Code)

**Session start rule:** deleted `review-handoff/` and the zip without reading them (neither was present). Docker Desktop was not running; started it and confirmed the engine (29.5.3) before any work.

**Owner decisions recorded** (§12 and the decision doc): FDA SPL lists with `code` = NCI Thesaurus code; units on hold (separate PR, needs a migration); INJECTION question to go to iCretegy with the three conditions, interim rule = show all matching IID records, never auto-pick a limit, reviewer confirms the route, `find_iid_candidates` unchanged; reviewer fills in routes and dosage forms only.

**Also observed:** the owner merged PRs #82–#87 this morning (05:58–05:59 UTC); `regx-main` is now `1131ae6`.

**Step 1: decision doc pushed. PR [#88](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/88)** (`regx/docs/terminology-vocabulary-decision`, commits `0cc3508`, `9243c1e`; docs only).
- Added a "Decisions" section and quoted the licence wording from the official pages: FDA Website Policies (public domain, "Unless otherwise noted…", content current as of 01/19/2024) and the NCI Thesaurus terms of use (CC BY 4.0; the name is a trademark). Not confirmed: whether CC BY attribution must appear in the UI.
- Workbook `orange_book_terminology_review_spl_2026-10-13.xlsx`: the Units sheet now starts with "ON HOLD — do not fill" (row inserted; data validation and filter shifted). sha256 changed `d6cd3738…` → `a56c3cfe…`.

**Step 2: IID importer fixed. Local branch `regx/fix/iid-importer`, commit `49328f5`. NOT pushed.**
- **File:** exactly one IID file in `D:/Praverse/data/fda/iid/` (`2026-10-12/iig_july_2026.zip`, sha256 `d08cf074…980c987e`). Not copied into the repo.
- **Inspection** (`IIR_OCOMM.csv`): 9,071 rows, 10 columns, UTF-8 (pure ASCII), CRLF, ends with CRLF, 3,950 lines with quoted fields. Every row has either a potency (3,805) or a maximum daily exposure (4,059), never both; 1,207 have neither (potency unit `NA` 850, `ADJ PH` 357). All amounts are plain decimals. MDE unit is always `mg`. UNII is the text `NA` on 1,595 rows (819 names). CAS blank on 1,697. `RECORD_UPDATED` = `Y` on 70 rows. No duplicate rows; no repeated ingredient+route+form.
- **Five faults found, all fixed:** wrong column names; any blank potency refused the whole file; amounts parsed together with units, so `45 mg/5ml` lost the 45; no raw text for amounts; UNII `NA` used as an identifier (would merge 819 ingredients).
- **Change:** real header plus ZIP member reading (`parsers.py`); real names first with old aliases (`adapters.py`); `potency_amount_raw` and `mde_amount_raw` (`models.py`, migration `0006`, reversible: drops the two columns); amounts parsed on their own, anything else kept as text, flagged on the row result (`safe_detail`, result `review_required`) and logged; `POTENCY_UNPARSEABLE` used for an unparseable potency; UNII `NA` treated as blank (`importer.py`). Docs: `docs/ORANGE_BOOK_INGESTION.md` IID section; command help.
- **Tests changed on purpose:** `test_p5_import_readiness.py` pinned the old, wrong column names and "potency is required". They now use the real header; the JSON-API alias tests are unchanged.
- **New tests:** `test_iid_real_rows.py`, 44 tests, on 11 real rows copied byte-for-byte (fixture `fixtures/iid/iir_ocomm_sample.csv`, CRLF kept by `.gitattributes`) plus malformed cases.
- **Results:** fda_data 270 passed / 1 skipped; **full suite 4,142 passed / 2 skipped, 0 failed (16 min 42 s)**; ruff check and format clean; import-linter 16 kept; `makemigrations --check` clean.
- **Local load** (release `bef6285c-2779-44f7-b9a7-e1bc6e4e126c`): the command parsed 9,071 rows in about 60 s, 0 failed. Lifecycle via the real API (Django test client, `force_login` as `sso.doer` / `sso.vp`; no passwords used): VP approve before review → 400; Doer validate → 200; Doer submit-review → 200; Doer approve → 403; VP approve → 200; VP activate → 200 (**active**).
- **Verified against the file:** 9,071 / 9,071 records; potency 3,805 / 3,805 and MDE 4,059 / 4,059 (numbers and raw text); sums equal (potency 249,514.45; MDE 5,225,466); 1,790 names, 59 routes, 106 forms; **0 field mismatches over every row**. Spot checks: ACESULFAME POTASSIUM / ORAL / POWDER, FOR SUSPENSION (45 mg/5ml); NORFLURANE / RESPIRATORY (INHALATION) / AEROSOL, METERED (MDE 239,360 mg, RECORD_UPDATED Y); ACRYLATES COPOLYMER / ORAL / TABLET (UNII `NA` → blank, MDE 10 mg).
- **Read correctly but not obvious:** the command prints "imported 0" because every row is `review_required` (no route is mapped yet: all 9,071 are `route_unmapped`). 1,789 ingredients for 1,790 names, because two names share UNII `0F4M8SIS5K`.
- **Open:** 4,059 MDE-only rows will read `potency_missing` even after mapping; that rule needs a decision.

**Step 3: SPL loader built. Local branch `regx/feat/spl-terminology-seed`, commit `049a377`. NOT pushed.**
- **Source saved outside the repo:** `D:/Praverse/data/fda/spl/2026-10-13/` contains the route and dosage-form pages (HTML, downloaded 2026-10-13T07:00:38Z, page dates 2021-10-29 and 2022-02-03), CSVs derived from their tables, and `SOURCE.md` (URLs, sha256, licence).
- **Design:** `fda_data/spl_terminology.py` plus `load_spl_terminology`. A CSV snapshot is registered as a versioned release of the existing `fda_route_terminology` / `fda_dosage_form_terminology` types, with one row result per term. New codes are created as `draft`; existing terms are untouched at load. Only `lifecycle.activate` (approver ≠ loader) makes listed terms active, applies label changes (old label kept as an alias) and retires unlisted terms (never deleted). Same bytes twice → nothing changes. No units, no migration. The generic release API still refuses terminology (refusal text updated).
- **Tests:** `test_spl_terminology.py`, 22 tests, including idempotency, the activation gate, versioning (label change, removal, addition), the command and its dry run. Fixtures are lines from the saved CSVs.
- **Results:** fda_data 247 passed / 1 skipped; ruff and import-linter clean; `makemigrations --check` clean; **full suite 4,119 passed / 2 skipped, 0 failed (19 min 34 s)**.
- **Local run:** routes 121 loaded / 121 in source; dosage forms 158 / 158; codes and labels identical to the source lists; all `draft`. A second run reported "already loaded" and changed nothing. **Both releases left `registered`:** approving and activating the vocabulary is a VP decision.

**Mistake to report:** the `curl` that saved the two SPL pages sent the owner's work email to fda.gov in its User-Agent header. Nothing else was sent; it will not be repeated.

**Not done (per the prompt):** units, `find_iid_candidates`, loading any mapping, Orange Book re-import, Phase 3. Nothing pushed except PR #88.

**Overview updated:** §10 (PRs and branches), §11 #19a, §12 (decisions), §13 (2.2a, 2.2b, 2.5a), §14 (rows 1c–1g, 3, and the new "Critical path to IIG matching").

**Working files:** `D:/Praverse/session-work/2026-10-13/s2/` (outside the repo). Services were stopped at the end of the session.

### 2026-10-13 (third session) — PRs #89/#90, branch cleanup, User-Agent rule, re-import finding, daily-exposure proposal (Claude Code)

**Session start rule:** deleted `review-handoff/` and the zip without reading them (neither was present).

**Step 1: housekeeping.**
- **Pushed with PRs (not merged):**
  - [#89](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/89) `regx/fix/iid-importer` (`49328f5`);
  - [#90](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/90) `regx/feat/spl-terminology-seed` (`049a377`).
  - Each description covers what changed, the migration and rollback (#89: `fda_data/0006`; #90: none), intentionally changed tests (#89: the old IID parser tests; #90: none), test results and local load results.
- **Deleted the 6 merged branches** of PRs #82–#87, locally and on GitHub. Each tip was first confirmed to be an ancestor of `origin/regx-main` (`1131ae6`). No force-push. Recorded in `branch-cleanup/BRANCH_INVENTORY.md` ("Deletion record (2026-10-13)").
  - GitHub: 5 branches (`main`, `regx-main`, and the heads of #88, #89, #90).
  - Local: 6 (the same 5 plus `regx/docs/iid-daily-exposure-rule`).
- **Where the work email in the curl User-Agent came from:** the Claude Code session supplies the account email to the assistant, and the assistant typed it into the `curl` command. It is not in git config (`user.email` = the GitHub noreply address, from `C:/Users/maana/.gitconfig`), not in any environment variable, session script or `.curlrc` (none exists).
- **Rule added** to `CLAUDE.md` "Hard constraints": outgoing HTTP requests use the User-Agent `REGX-dev-research` and never carry names, emails or tokens.

**Step 2: re-import check (read-only; a throwaway probe test ran only against the pytest test database, not committed).** Same bytes are **not refused** by `register_release`; it returns the existing release.
- **Orange Book via the command:** stopped, because `record_count_imported` > 0 ("Nothing to do"). Nothing changed.
- **IID via the command:** **not stopped**, because `record_count_imported` is 0 while every row is `review_required`. The import runs again, skips every row that already has a result, changes no record, adds one `IMPORT_STARTED` audit event (3 → 4) and prints "registered". A route and dosage-form mapping approved between the runs was **not** applied (the ORAL/TABLET record stayed `route_unmapped`).
- **JSON API (code reading only):** no guard; a duplicate payload is a no-op and returns 201.
- **Proposal (not built):** a `reresolve_iid_terminology` command.
  - Only for releases still `registered` / `validated`; it only fills empty route and dosage-form links from approved mappings; one audit event per changed record. Details in §12.
  - Plus a small fix to the command's duplicate check, and a clear refusal from the JSON API.

**Step 3: not started, as instructed.** PR #90 is not merged, so the SPL releases were not activated and `regx/feat/iid-mapping-proposals` was not created. No mapping was proposed or approved.

**Step 4: daily-exposure rule (docs only).** New branch `regx/docs/iid-daily-exposure-rule` (the plan branch was merged in #81), commit `3a78246`, **not pushed**.
- Adds Q8 to `docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md`: per-unit check when the IID row has a potency, per-day check (amount per unit × maximum dosage units per day vs the IID maximum daily exposure) when it has a daily exposure, using the product's structured maximum daily dose.
- "Cannot compare" when the unit basis or the dose is missing; several matching rows each shown; results are "at or below" / "above", never "acceptable".
- Marked "proposed, pending iCretegy and regulatory reviewer confirmation". "Please return" now lists Q1–Q8.
- I read "stop at Step 2" as applying to Step 3 only; this step is a local docs branch and can be dropped.

**Not done (per the prompt):** no mapping approved, nothing re-imported, per-day check not built, no Phase 3.

**Overview updated:** §10, §11 (#19a status, new #19b), §12 (daily-exposure proposal, re-import proposal, email source), §13 (2.2a, 2.2b, 2.5a), §14 (rows 1f–1h, critical path table).

**Working files:** `D:/Praverse/session-work/2026-10-13/s3/` (outside the repo). The stack was started for the probe (image built from `regx/fix/iid-importer`) and stopped at the end.

### 2026-10-13 (fourth session) — PR #91 (Q8); stopped at the owner's gate (Claude Code)

**Session start rule:** deleted `review-handoff/` and the zip without reading them (neither was present).

**Gate check (GitHub, 13:27 IST):** PRs #89 (IID importer) and #90 (SPL loader) are **open, not merged**; `regx-main` is still `1131ae6`. The owner's prompt says: if either is not merged, do Step 1 only, then stop. Re-checked after the owner's "continue": still both open.

**Step 1: done.** Pushed `regx/docs/iid-daily-exposure-rule` (`3a78246`) and opened docs-only PR [#91](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/91) (White Paper spec Q8, proposed per-unit / per-day IID check). Not merged.

**Not started, waiting for #89 and #90 to merge:**
- Step 2: duplicate-import guard (`regx/fix/import-duplicate-guard`; command refuses when any row results exist; JSON API returns 409).
- Step 3: `reresolve` command plus the unmapped-rows warning on IID submit-for-review.
- Step 4: VP activation of the two SPL drafts and the IID mapping-proposal command.

**State:** GitHub has 6 branches (`main`, `regx-main`, heads of #88–#91). No code changed this session. Services were not started. Working files: `D:/Praverse/session-work/2026-10-13/s4/`.

### 2026-10-13 (fifth session) — duplicate guard, re-resolve, SPL activation, IID mapping proposals (Claude Code)

**Session start rule:** deleted `review-handoff/` and the zip without reading them (neither was present). **Gate:** confirmed on GitHub that #88, #89, #90 and #91 were merged by the owner (08:53–08:54 UTC); `regx-main` is `b55898a`. All three branches below start from it. **None is pushed.**

**Step 2: duplicate-import guard.** `regx/fix/import-duplicate-guard`, commit `8940539`.
- New `importer.find_imported_duplicate`: an existing release with the same (dataset type, checksum) that has ANY row results.
- `import_fda_release` checks it before registering. It prints "Refused: these exact bytes are already imported as release <id> (status: <status>, N row results). Nothing was changed." The exit code stays 0, as before, so the existing test contract holds. The old `record_count_imported` check is removed.
- The JSON release API returns **409 `duplicate_release`** with the release id and status, instead of a no-op 201.
- **Tests:** `test_duplicate_import_guard.py`, 6 tests: Orange Book re-run refused; IID re-run refused (the case the old check missed); a new file accepted; same bytes under another dataset type are not a duplicate; JSON duplicate 409 with nothing changed; a different payload accepted. No existing test changed.
- **Results:** fda_data 298 passed; **full suite 4,170 passed / 2 skipped, 0 failed**; ruff clean.

**Step 3: re-resolve.** `regx/feat/reresolve-terminology`, commit `3caf357`.
- `fda_data/reresolve.py` and `reresolve_terminology <release> [--dry-run]`:
  - only for releases not yet submitted for review (`registered`, `staged`, `validated`);
  - only fills empty route/dosage-form links from approved current mappings, and never changes or clears a link;
  - recomputes IID calculability;
  - one audit event per changed record (`fda_data.record.terminology_reresolved`, old → new plus the mapping id) and one summary event (`fda_data.release.terminology_reresolved`, only when something changed);
  - generic core plus a per-dataset entry: IID wired up, the Orange Book not.
- **Guard:** `POST …/submit-review/` on an IID release with unmapped records returns 409 `unmapped_rows` with the count. `confirm_unmapped: true` submits it, adds a `warning` to the response and records `unmapped_rows_confirmed` in the submit audit event (`lifecycle.submit_for_review` gained an optional `extra_payload`).
- **Tests:** `test_reresolve.py`, 13 tests: dry run; filling plus audit; idempotency; never overwrite; only approved current mappings; refused under review and active (function and command); Orange Book not wired; command dry run then apply; the guard without confirm, with confirm, a fully mapped release and an Orange Book release.
- **Results:** fda_data 305 passed; **full suite 4,177 passed / 2 skipped, 0 failed**; ruff and import-linter clean; `makemigrations --check` clean (no migration).

**Step 4: SPL activation and IID mapping proposals.** `regx/feat/iid-mapping-proposals`, commit `871959d`.
- **Local SPL activation, through the API** (Django test client `force_login`, no passwords):
  - routes release `9193181f…`: sso.doer validate → 200, submit-review → 200; sso.doer approve → **403**; sso.vp approve → 200, activate → 200 (09:19:37 UTC);
  - dosage forms `27874ae6…`: same sequence.
  - Result: **121 routes and 158 dosage forms active.**
  - Loader = `load_spl_terminology` at 07:10 UTC, which records no user (§11 #19c), so "approver ≠ loader" holds by procedure only.
- **Command** `propose_iid_mappings [--release] [--dry-run]`: for each distinct IID route and dosage-form value, a PROPOSED mapping only when it equals exactly one ACTIVE SPL label (case-insensitive, trimmed). Draft and retired terms are never used, and there are no aliases or fuzzy matches. Values with a current mapping in any status are skipped (idempotent). It never approves, and emits `fda_data.mapping.proposed` per proposal.
- **Tests:** `test_iid_mapping_proposals.py`, 8 tests (exact-only with a report; never approved and nothing resolves; idempotent; draft and retired terms ignored; case and spaces only; dry run; command report; no active release). Fixtures are real IID rows and real SPL lines.
- **Results:** fda_data 300 passed; **full suite 4,172 passed / 2 skipped, 0 failed**; ruff and import-linter clean.
- **Local run** (active IID release `bef6285c…`):
  - dry run: 59 / 105 would be proposed;
  - real run: **59 route and 105 dosage-form mappings PROPOSED**;
  - **not exact: `DROPS` (67 records)**; SPL has `SOLUTION/ DROPS` and `SUSPENSION/ DROPS`, a reviewer must choose;
  - a second run proposed 0 (already mapped 59 / 105);
  - mapping statuses: proposed only (0 approved); IID records with a route link: 0.

**Not done (per the prompt):** no mapping approved; nothing re-imported or re-resolved; per-day check not built; no Phase 3; no repair of the locally active IID release.

**Overview updated:** §10, §11 (#19b update, new #19c), §12 (re-resolve built, mapping proposals), §13 (2.2a, 2.2b, 2.5a), §14 (rows 1e–1k, critical path).

**Working files:** `D:/Praverse/session-work/2026-10-13/s5/` (outside the repo). A temporary git worktree (`D:/Praverse/regx-wt-proposals`) was used for Step 4 and removed. Services were stopped at the end.

