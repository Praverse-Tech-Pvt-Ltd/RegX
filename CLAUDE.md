# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Which codebase and branch this is

The GitHub repo `Praverse-Tech-Pvt-Ltd/RegX` holds **two unrelated git histories with no common ancestor**:

- **`regx-main`**: REGX, the multi-tenant regulatory workflow platform. **All current work goes here.** Branch off `regx-main` (feature branches are named `regx/<type>/<topic>`).
- **`main`**: the repo's default branch, the legacy iPharmaAI Django monolith. Its `CLAUDE.md`, `SETUP.md`, `constraints.md` and `decisions.md` **do not apply here**. A plain `git clone` lands on `main`. If `:8000` returns 404 or `/ratools/...` routes are missing, you are usually on the wrong branch.

`regx/feat/legacy-port-and-sso` (PR #49) has been merged into `regx-main`. Do not build on that branch; `regx-main` is about 70 commits ahead of it.

**Read before proposing anything**, in this order:
1. `PROJECT_OVERVIEW.md` (repo root). The takeover overview: state, risks, open questions. Append to its Work Log at the end of each session; do not create a new overview file.
   - **`PROJECT_OVERVIEW.md` and this `CLAUDE.md` are tracked in git** (since 2026-11-05). A Work Log entry or rule change is therefore a commit: put it on the session's working branch, or in a small docs PR when the session has no branch. Never commit them straight to `regx-main`.
2. `docs/FINAL_ENGINEERING_CLOSURE_AUDIT.md` and `docs/P0_P14_HANDOFF.md`. The latest declared state (covers P0–P15).
3. `docs/EXTERNAL_BLOCKER_READINESS.md`. What is blocked, and on whom.
4. `constraints.md` (what you may not change without asking) and `decisions.md` (why things are the way they are).
5. `test-checklist.md`. Commands, plus the output each one should produce.

`handoff.md` dates from 2026-09-09. Its PR status and test counts are stale; the environment traps it lists are still accurate.

## Session start rule

**THE REVIEW HAND-OFF — DELETE FIRST, REBUILD LAST, EVERY SESSION.**
At the START of this session, DELETE both `review-handoff/` and
`review-handoff.zip` at the repository root. Do not read them, do not keep
anything from them, and do not update either in place. They describe the LAST
session and carrying anything over makes them lie about this one.

## Session end rule

**As the LAST step of every session in which work was done, build `review-handoff/` and `review-handoff.zip` at the repository root, from scratch.** Do it after the commits and the `PROJECT_OVERVIEW.md` Work Log entry, and just before stopping the services. If no work was done, build neither and say so.

**Every file goes in whole, never as an excerpt.** The only exception is a file over 5 MB (see below).

### What goes in

1. **Changed:** every file created or modified in the session, on any branch, tracked or untracked. That covers code, tests, migrations (with their rollback), docs, config, scripts and `.md` files, plus `PROJECT_OVERVIEW.md` and `CLAUDE.md`.
2. **Cited:** every file the session's findings or claims rest on. If the plan, the overview, the Work Log or a new doc says "file X does Y" or cites `file:line`, include file X in full, from the branch it was read on.
3. **Report:** every helper or sub-agent report, in full, not a summary. Extract the agent's final message from its transcript with a script; never paste it by hand.
4. **Evidence:** every script written during the session, plus its raw output (test runs, audits, live-check transcripts).
5. **Patches:** one `git format-patch` per commit (`patch__<sha>__<label>.patch`).
6. **Session log:** this session's Work Log section, extracted to `session-log__PROJECT_OVERVIEW.md__<date>.md`. **`PROJECT_OVERVIEW.md`'s Work Log is the only session log.** Do not create `docs/log/` files or any other session log.

### Naming

**Copies only, never moves.** Name each copy `<real path with / replaced by __>@<branch-or-source>`, for example `backend__fda_data__models.py@regx-main`.
- Take committed files from their branch with `git show <branch>:<path>`.
- Untracked files use `@working-tree-untracked`.
- Evidence is `evidence__<name>`; reports are `report__<name>.md`.
- **Replace a leading `.` with `dot`** so no copy is hidden (`.github/workflows/x.yml` becomes `dotgithub__workflows__x.yml@<branch>`).

### Safety

- **Never copy secrets.** Exclude every `.env*` file except `.env.example`.
- Before copying, scan each file for keys, passwords and tokens (e.g. `sk-…`, `AKIA…`, `SECRET_KEY = "…"`, `password = "…"`, private-key blocks). Replace every value with `<REDACTED>`, and note the redaction in `MANIFEST.md`.
- **A file over 5 MB** goes in as its first and last 200 lines, and `MANIFEST.md` says so.

### `MANIFEST.md`

- One row per file: **real path**, **branch or source**, **category** (`changed` / `cited` / `evidence` / `report` / `patch` / `log`), and **why a reviewer needs it**.
- State explicitly when there are no migrations or no tests.
- **Final citation check:** grep the session's Work Log, the plan and any new or changed docs for repository file paths, and confirm each cited path has a copy. List any missing path with the reason (for example "directory, not a file", "does not exist on that branch", "excluded: secret").

### Package and report

- Zip the folder to `review-handoff.zip` with **forward-slash entry names** (`review-handoff/<file>`).
- Verify that no entry contains a backslash and no name starts with `.`, and that the zip passes `zipfile.testzip()`.
- **Both are ignored through `.gitignore`** (with `branch-cleanup/`), so the exclusion applies to every clone. Never commit them. They sit outside the tsconfig, ESLint and ruff scopes.
- **Report in the chat summary** that both exist, with the file count, the zip's size in bytes, and the result of the citation check.

## Layout

- `backend/`: Django 5.2 + DRF. The project package is `regx` (`regx/settings/{base,development,production,test}.py`). Each domain is a top-level app. `demo_seed/` is a composition root that nothing may import.
- `frontend/`: Next.js 15 / React 19. Pages live under `src/app/(regx)/`. The whole API client is one file, `src/lib/api.ts`. Tests are in `tests/unit` (vitest) and `e2e/` (Playwright, API mocked with `page.route`).
- `company_site/`: the legacy monolith (`RAAI`, `RATools`, `AIDatabase`, `AdminMaster`), carried in and run as its own service on its own SQLite DB. It has no migrations folder and REGX code must never import it. Its smoke tests (`company_site/run_tests.sh`) run in CI on every PR, always with `OPENAI_API_KEY` unset.
- `infra/nginx/nginx.conf`: the single integrated origin.
  - `:8080` serves the REGX API (`/api/`), an **explicit allow-list of REGX page prefixes**, and company_site for everything else.
  - `:8090` serves the company_site admin console only.
- `docs/`: about 120 design, evidence and decision-intake docs. `docs/ARCHITECTURE.md` is the system map. Its module table is incomplete: 25 apps exist and the table lists 13.

## Commands

### Full stack (Docker)

```bash
cp .env.example .env          # set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, MFA_ENCRYPTION_KEY (Fernet key), COMPANY_SECRET_KEY
docker compose config --quiet # validates .env; scripts/check_env.py reads os.environ, not .env
docker compose up --build -d
docker compose exec backend python manage.py migrate                          # NOT run on start
docker compose exec backend python manage.py seed_regx_demo --password-env DEMO_PW   # demo tenant "demo", users *@demo.regx.invalid
```

- **Ports:**
  - `8080`: integrated origin (`/signin` for REGX)
  - `3000`: frontend direct
  - `8000`: API (`/api/docs/`)
  - `8001`: company_site direct
  - `8090`: legacy admin
- **Malware scanning:** compose runs the **stub** scanner by default (`DOCUMENT_SCANNER_ALLOW_STUB=true`). For real ClamAV, use `docker compose --profile scanning up` with `DOCUMENT_SCANNER_BACKEND=clamav`.
- **Traps that look like code bugs:**
  - **Source is baked into the images**, not mounted. After an edit, run `docker compose build backend celery && docker compose up -d backend celery`.
  - **Restart nginx after recreating any container** (`docker compose restart nginx`). Otherwise the service answers 404 through nginx and 200 when called directly.
  - **`MSYS_NO_PATHCONV=1` before `docker compose exec` on Windows Git Bash.** Otherwise `/app/...` is rewritten to `C:/...`.
  - **Readiness says "ready" on an empty schema.** It checks connectivity only. If you see `relation ... does not exist`, run `migrate`.
  - **Every tenant-scoped endpoint needs `X-Tenant-Slug`.** Without it you get a 403 that looks like a permissions bug.

### Backend

Run these from `backend/`. Postgres is required: **SQLite is prohibited for REGX** and the settings enforce it.

```bash
pip install -r requirements/dev.txt
ruff check . && ruff format --check .   # CI runs both; a failing `check` hides `format` results
lint-imports                             # 16 import-linter contracts
pytest                                   # pyproject sets regx.settings.test
pytest authorization/tests/test_authorization.py::TestMyRolesView -q --no-cov   # single test/class
python manage.py makemigrations --check --dry-run
```

**Dependencies are locked** (pip-tools). `backend/requirements/*.in` are the hand-edited inputs; `base.txt`, `test.txt` and `dev.txt` are generated lock files (exact versions plus sha256 hashes for every package, including indirect ones). Docker installs `base.txt` and CI installs `dev.txt`, both with `--require-hashes --no-deps`.

```bash
scripts/lock_backend_deps.sh                          # after editing a .in file (needs Docker)
scripts/lock_backend_deps.sh --upgrade-package kombu  # deliberately upgrade one package
```

- Never edit a `.txt` lock by hand. Commit each `.in` together with its regenerated `.txt`.
- The script runs `pip-compile` in `python:3.12-slim` (the backend image's base), so versions match production. It keeps already-locked versions unless told to upgrade, so a re-run with unchanged inputs changes nothing.
- CI job "Dependency locks match their inputs" regenerates the locks and fails on any diff.
- `company_site/` is locked the same way: `company_site/requirements.docker.in` → `requirements.docker.txt`, regenerated with `scripts/lock_company_site_deps.sh`.

In the compose container (the runtime image ships without pytest):

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -u root backend pip install -q -r requirements/dev.txt
MSYS_NO_PATHCONV=1 docker compose exec -T -e DJANGO_SETTINGS_MODULE=regx.settings.test backend \
  python -m pytest <path> -q --no-cov -p no:cacheprovider
```

- **`-e DJANGO_SETTINGS_MODULE=regx.settings.test` is mandatory.** Under the container's production settings Celery is not eager, and `external_integrations` tests fail in ways that look like real bugs.
- `--no-cov -p no:cacheprovider` are needed because `/app` is read-only. The coverage `INTERNALERROR` is not a test failure.
- **Run only one pytest at a time.** All runs share the `test_regx` database, and a concurrent run errors at setup with `DuplicateDatabase` / `ObjectInUse`.
- The full suite is 4,033 passed / 1 skipped at `regx-main@732133f` and took about 18 minutes on Windows Docker. Redirect output to a file; the progress lines lag badly.
- `common/tests/test_task_reliability_doc.py` reads `docs/TASK_RELIABILITY.md` via the `./docs:/docs:ro` mount. Do not loosen the test.
- Ruff cannot lint the source baked into the image. Lint the working tree; the docker one-liner is in `test-checklist.md` §6.

### Frontend

Run from `frontend/`:

- `npm ci`
- `npm run dev`
- `npm run type-check`
- `npm run lint`
- `npm run test` (vitest); a single file is `npx vitest run tests/unit/<file>`
- `npm run build`
- `npm run test:e2e` (Playwright; starts its own dev server on :3100 with the API mocked)
- `npm run test:e2e:integrated` (against the running nginx stack)

CI runs them in this order: type-check → lint → test → build → e2e.

**Adding a page:** a new top-level directory under `src/app/(regx)/` also needs a location in `infra/nginx/nginx.conf`. `tests/unit/nginx-route-coverage.test.ts` derives both lists and fails if they diverge.

## Architecture

**API:**
- Everything lives under `/api/regx/v1/` (`regx/api_v1_urls.py`), about 220 routes.
- `auth/`, `tenants/`, `permissions/`, `mfa/` and `documents/` have prefixes. Other apps mount at `""` and own their paths.
- Views are `@api_view` functions or `APIView`s, with per-method permission classes in `get_permissions()`. There are no ViewSets or routers.
- Public UUID `public_id`s only; BIGINT PKs never appear in responses.

**Tenancy is fail-closed:**
- `TenantMiddleware` resolves `X-Tenant-Slug` into a thread-local (`tenancy/context.py`).
- `current_tenant()` raises `TenantScopeMissing` if no tenant was set.
- Reference corpora (`fda_data`, `inspections`, `deficiencies`, CC best practices) are **platform-level**. Never add a tenant FK to them.

**Layering is enforced by import-linter** (`[tool.importlinter]` in `backend/pyproject.toml`; the dependency arrows are in `docs/ARCHITECTURE.md`):
- `common` imports no domain. `identity` does not import `tenancy` or `authorization`. `documents` never imports `workflows` or `submission_packages`; deletion protection goes through `DeletionProtectionRegistry`.
- Composition stacks outward: `regulatory_cases` → `submission_dossiers` → `dossier_blueprints` → `dossier_upgrades`.
- `submission_operations` (read model: no models, nothing stored), `submission_packages`, `external_integrations` (the only outbound network edge) and `demo_seed` are leaves. **Nothing may import them.**
- No REGX module may import `AIDatabase`, `RATools`, `AdminMaster` or `RAAI`.
- When you add an app, add it to `root_packages`, the ruff `known-first-party` list and the relevant contracts. The four ported apps (`deficiencies`, `inspections`, `controlled_correspondence`, `product_comparison`) are currently missing from `root_packages`.

**Writes go through `services.py`:**
- Do not write another app's rows directly. For example, `dossier_upgrades` mutates dossiers only through `submission_dossiers.services`.
- Every upload, from a user or a connector, goes through `documents.ingest` (validate → hash → store → version → queue scan). It has no bypass flag.

**Immutability is enforced in Postgres, not just in Python:**
- RunSQL migrations install triggers that make append-only or frozen data unchangeable at the database level.
- Covered: the audit trail, workflow transitions and evidence, case and section links, frozen packages, blueprint provenance, upgrade history, connector executions.
- A direct ORM `update()`/`delete()` on these rows fails at the DB. That is intended.

**Invariants guarded by tests** (full list in `docs/ARCHITECTURE.md`):
- Derived state (e.g. dossier `readiness`) is never in a write serializer.
- Packages bind to an exact `DocumentVersion`. FROZEN cannot be undone. Export is all-or-nothing.
- On the dashboard, `0` means none and `null` means "not entitled to know".
- **No regulatory or agency-approval claims.**
  - `common/tests/test_regulatory_claim_guard.py` and several per-module copies scan for banned phrasing, including in UI strings and docstrings.
  - READY, COMPLETED, ACTIVE and FROZEN are internal states only.
  - `APPROVED`/`SUBMITTED` are allowed only as internal workflow state names.

**Regulatory content gate:**
- No real checklist content may go live until the 20-item gate is signed off (`docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md`, 0 of 20 approved).
- Never activate unreviewed platform checklist content. The demo seed creates and activates its own `DEMO-` definition for exactly this reason.
- The seed's docstring mentions "six platform checklist definitions that ship with the database". No migration or command creates them, and a fresh database lists only the `DEMO-` definition. Where they come from is an open question.
- Calculators, the Word add-in and the stability/impurity AI are blocked on client decision intakes. Do not build them on assumptions.

**Auth:**
- Session cookies: HttpOnly, SameSite=Lax, 8h, stored in the Redis cache.
- The frontend fetches `/auth/csrf/` before each write and sends `X-CSRFToken`. Tokens never go in localStorage; CI checks this.
- MFA is TOTP. **Mandatory for Reviewer, VP, Tenant Admin and Platform Support** (SOW 4.3; the list is the setting `REGX_MFA_REQUIRED_ROLES`): `authorization.middleware.MFAEnrolmentMiddleware` refuses their POST/PUT/PATCH/DELETE under `/api/regx/v1/` (except `auth/` and `mfa/`) with 403 `mfa_enrolment_required` until they enrol at `/mfa/setup`; reads stay open. Optional for other roles. The gate reads the session user in middleware, so it relies on `SessionAuthentication` being the only DRF scheme (a test pins this). Tests that act as a Reviewer/VP through `force_authenticate` bypass the gate; use `force_login` to exercise it.
- **No self-registration and no self-service tenant creation:** `POST /auth/register/` → 403 `self_registration_disabled`; `POST /tenants/` → 403 `tenant_creation_restricted`. Operators use `manage.py create_tenant` and `create_tenant_user --password-env VAR`.
- RBAC has 5 system roles (`tenant_admin`, `platform_support`, `doer`, `reviewer`, `vp`), seeded by a `post_migrate` signal in `authorization/seed.py`, not by a migration.
- There is no SAML/OIDC SSO.

**Shared login with company_site:**
- `company_site/AdminMaster/regx_auth.py` POSTs the credentials to `/api/regx/v1/auth/login/`.
- It mirrors the identity into a `CustomUser` with an **unusable password**.
- It refuses `mfa_required` accounts.
- Only the credential check is shared; sessions are not. A blank `REGX_AUTH_URL` falls back to local passwords.

**Celery:**
- Redis broker. Tasks are dispatched with `transaction.on_commit(...delay())`. Test settings run eager.
- Task contracts live in `docs/TASK_RELIABILITY.md`, and a test keeps that doc in sync.
- company_site's own Celery tasks never run: compose starts no company worker or beat.

**Ported legacy features:**
- `deficiencies`, `inspections`, `controlled_correspondence` and `product_comparison` were converted to REGX conventions: no CKEditor, no in-process pandas/`.pkl` caches, no Django-admin-shaped features.
- They are **API-only**, with no REGX pages yet. Their corpora are empty until you run `import_*` commands. Those commands **delete before importing**.
- Gap analysis is a single engine, `iig_checklist/gap_analysis.py`.

## Hard constraints (summarised from `constraints.md`; read it in full)

- Do not weaken anything in `regx/settings/production.py` (cookie `Secure` flags, the scanner stub refusal) to make something work.
- `identity.User` is off-limits without prior approval.
- Do not share session cookies between the two Django apps. Do not try again to split company_site's admin surface into its own app; that failed three times.
- **Cost:** a single `GET /` on company_site once triggered 71 paid OpenAI calls. `constraints.md` names an `ENABLE_OBSERVATION_SUMMARIES` flag, but **it exists only on the legacy `main` branch and was never ported into `company_site/` here**. The only gate is that `OPENAI_API_KEY` is unset, which compose currently ensures. Never set that key in the company_site container, and never hit a company_site route without knowing what it does.
- The legacy OpenAI key in `main`'s `AIDatabase/filters.py` is the owner's call. Do not rotate or remove it on your own initiative, and do not propose it again.
- Back up `company_site/db.sqlite3` before running `add_missing_columns.py`. `import_inspections`, `import_deficiencies` and `import_best_practices` delete before inserting.
- Do not normalise the 76 `deficiency_type` spellings. That needs governance approval.
- Check the harness (settings module, `/docs` mount, any concurrent pytest) before you trust red test output. Never edit a passing test to make a failure go away.
- A 200 is not a pass: check the response content. Also confirm that a legitimate request *succeeds*, not only that a bad one is refused.
- One logical change per request. Show the real diff, not a summary.
- **Force-push** only with `--force-with-lease` pinned to the known tip (`--force-with-lease=<branch>:<sha>`), and only on a branch that has only our commits and no reviews. Never on `regx-main` or `main`.
- **Outgoing HTTP requests** (curl, scripts, fetch tools) use the generic User-Agent `REGX-dev-research`. They never include personal or company identifiers: no names, email addresses or tokens, in headers, URLs or bodies. (On 2026-10-13 a `curl` to fda.gov carried the owner's work email; it came from the account email in the assistant's session context, not from any repo file, git config or environment variable.)
- **Working files live under `D:/Praverse/session-work/<date>/`** (e.g. `D:/Praverse/session-work/2026-11-16/`): all working files, scripts, evidence and raw outputs, PR descriptions, and every git worktree (`git worktree add D:/Praverse/session-work/<date>/<name> <branch>`). **Never** under the OS temp folder (`%TEMP%`, `/tmp`) or the Claude scratchpad. The temp folder was wiped twice (between 2026-11-13 and 2026-11-16) and destroyed four worktrees' working copies and every session script. The review hand-off stays at the repository root as before.
