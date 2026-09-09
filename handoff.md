# Project Handoff — REGX

Session date: 2026-09-09. Repo: `Praverse-Tech-Pvt-Ltd/RegX`, branch
`regx/feat/legacy-port-and-sso` (off `regx-main`, 17 commits, 87 files, +8,004).

> **Read this first.** The repo contains **two unrelated codebases with no common
> git ancestor**. `main` is the legacy iPharmaAI Django monolith; `regx-main` is
> the REGX platform. They are 379 commits and 2,579 files apart. This handoff is
> about **`regx-main` only**. The `main`-branch documents (`SETUP.md`,
> `constraints.md`, `decisions.md`) describe the legacy app and do not apply here.

Companion documents written for whoever picks this up:

| File | What it is for |
|---|---|
| `test-checklist.md` | Every command to run and the exact output to expect. **Start here.** |
| `constraints.md` | What must not be changed without asking. Read before proposing anything. |
| `decisions.md` | Why each non-obvious choice was made, and what was rejected. |
| `ROUTES.md` | Every company_site URL with its exact trailing slash and port. |
| `docs/COMPANY_SITE_AUTH_INTEGRATION.md` | The shared sign-in, in detail. |
| `docs/DEVELOPMENT.md` | Setup, corrected against what actually works. |

## 1. Goal

Two goals ran across this work, in order:

1. **Port the features that exist in the legacy `main` monolith but have no
   equivalent in `regx-main`**, converting each to the REGX stack rather than
   copying legacy code across.
2. **Make the legacy app usable alongside REGX** — it is carried into this
   branch verbatim as `company_site/`, and much of it did not run.

Scope for (1) was set after a feature-delta analysis: roughly **three quarters
of `main` is already superseded** by better implementations in `regx-main` and
is deliberately **not** ported.

| Ported | Skipped (already superseded in REGX) |
|---|---|
| Deficiency database | ANDA / IIG / DMF / Validation / VP checklists |
| FDA 483 corpus | Doer / Reviewer / VP roles |
| Warning letters | Part 11 audit trail |
| Controlled correspondence | |
| Product comparison | |
| Gap analysis (rebuilt, not ported) | |

All of these are done. Constraint held throughout: **keep the REGX tech stack as
it is**; legacy patterns were converted to REGX conventions, not imported.

## 2. Current State

**Branch:** `regx/feat/legacy-port-and-sso`, 17 commits ahead of `regx-main`, open as PR #49.
**Stack:** `docker compose`, 7 services — backend, frontend, company_site,
nginx, postgres, redis, celery.

### Ports

| Port | Serves | Notes |
|---|---|---|
| **3000** | REGX React frontend | Sign in at `/signin` |
| **8000** | REGX API direct | `/api/docs/` is the Swagger UI |
| **8080** | nginx → company_site (legacy tools) | Refuses user management and `/admin/` |
| **8090** | nginx → company_site admin console | `/adminmaster/` and `/admin/` |

8080 and 8090 are the **same application** on two listeners; the split exists so
user management can be firewalled separately. There is no separate codebase
behind 8090.

### Working, verified this session

- **One sign-in for both applications.** The company login at
  `/adminmaster/login/` no longer checks passwords itself — it delegates to
  REGX's auth API and mirrors the identity into a local `CustomUser`. Same
  email and password works at `/signin` and at `/adminmaster/login/`.
- REGX stack builds and runs from clean; all seven services come up.
- All six ported feature APIs respond, with tenant isolation verified in both
  directions (member reads; non-member and header-less request both refused).
- company_site logs in at all (it returned 500 for everyone before — 134 model
  fields had no database column).
- Trailing-slash tolerance: both `/path` and `/path/` now resolve everywhere.

### Known gaps — read before testing

- **MFA is not enforced anywhere in REGX.** `identity.User.mfa_required` is set
  when someone enrols, but no permission class or middleware reads it. No
  protected operation is gated on MFA today. The company login refuses an
  `mfa_required` account outright, which makes it *stricter* than REGX itself.
  **This gap is real, known, and unfixed** — it is a decision, not an oversight.
- **No React page consumes the ported APIs.** Backend only. The screens for
  deficiencies, 483s, warning letters, controlled correspondence and product
  comparison do not exist yet.
- **Checklist, template, document and FDA-data screens are empty.** They need
  governed multi-step construction or a real dataset import, not seeding.
- **Warning letters are empty — 0 rows.** The `WarningLetter` model and the
  `import_inspections --only warning_letters` path both exist, but the legacy
  sqlite snapshot used for the port did not carry `AIDatabase_warningletter`,
  so the import skipped it silently. Loading them needs a snapshot that has it.
- **4 AIDatabase lookups still fail.** The restored workbooks are missing the
  `Country`, `FEI Number` and `Organization Name` columns the views read. This
  needs a corrected export from the client — no amount of code fixes it.
- **`/ratools/appendix_white_paper`** is a dead template link, and
  `media/Module_Simplification` content is not in the repo. Both render an
  empty state rather than 500 now, which is as far as code can take it.
- **The restored `.xlsx` workbooks are gitignored** and exist only on this
  machine. A fresh clone will not have them. Decide whether they should be
  committed or supplied at deploy — see `constraints.md`.

### Environment assumptions that bite

- Docker daemon must be running (Rancher Desktop or Docker Desktop).
- `.env` must exist locally with four generated secrets (`DJANGO_SECRET_KEY`,
  `POSTGRES_PASSWORD`, `MFA_ENCRYPTION_KEY` as a real Fernet key,
  `COMPANY_SECRET_KEY`). Gitignored; values are not in this repo.
- **Migrations do not run on container start.** `docker compose up` reports
  every service healthy against an empty schema — `readiness` only checks
  connectivity. Run `manage.py migrate` explicitly.
- **Source is baked into the images, not volume-mounted.** Any Python change
  needs `docker compose build <service>` then `up -d`. Editing a file and
  reloading the browser does nothing.
- **After recreating a container, restart nginx.** It caches upstream IPs and
  will serve 404s for a service that is running perfectly. This wasted time
  twice this session.
- **On Windows, prefix container commands with `MSYS_NO_PATHCONV=1`.** Git Bash
  rewrites `/tmp/x` into a Windows path before Docker sees it.
- **`pytest` is not in the runtime image.** It is a dev dependency, and
  installing it needs `-u root` — the container's user has `HOME=/nonexistent`,
  so a plain `pip install` fails on a path unrelated to what you asked for.
  Pass `--no-cov -p no:cacheprovider` when running: `/app` is read-only, and
  the `INTERNALERROR` coverage raises is not a test failure. See
  `test-checklist.md` §7.
- **Force `-e DJANGO_SETTINGS_MODULE=regx.settings.test` on every pytest run.**
  `pyproject.toml` sets it, but the container's environment sets
  `regx.settings.production` and the environment wins. Production has no
  `CELERY_TASK_ALWAYS_EAGER`, so queued tasks never run and 7
  `external_integrations` tests fail in ways that read like real bugs. They
  pass with the right settings. This one costs an hour if you trust the output.
- **Run `ruff check` and `ruff format --check` before pushing.** CI's first job
  runs both, and neither is in the runtime image. Seventeen commits reached CI
  before anyone ran them, and the job failed on 34 errors plus 26 unformatted
  files. `test-checklist.md` §6 has the one-line command.
- **Only one pytest run at a time.** Every run builds the same `test_regx`
  database, so a second concurrent run errors at setup on *every* test —
  including ones unrelated to your change. That pattern means another run is
  going, not a regression.

### Unverified

- Nothing here has run outside local Docker.
- The deficiency import was verified against the legacy sqlite snapshot only;
  the `--xlsx` path has no test coverage.

### Test suite — 2026-09-09

```
3810 passed, 1 skipped, 5 warnings in 840.84s (0:14:00)
```

**Green, with nothing to explain away.** Two environment fixes were needed to
get an honest run, both now in place: `compose.yaml` mounts `./docs:/docs:ro`
so the documentation-consistency tests can find their file, and every pytest
invocation must pass `-e DJANGO_SETTINGS_MODULE=regx.settings.test`.

The suite caught one real gap on the way — the four ported apps had migrations
but were in no module's regulatory-claim guard, so nothing was scanning them for
phrases asserting an FDA verdict. Now in `GOVERNED_MODULES`. No offending
phrase was present; this closed a coverage gap, not a defect.

Full detail, including what the first two runs got wrong and why:
`test-checklist.md` §7.

## 3. Active Files

### Shared sign-in (this session)

| File | Status | Purpose |
|---|---|---|
| `company_site/AdminMaster/regx_auth.py` | Created | Posts credentials to REGX, maps the role, provisions the mirror `CustomUser` |
| `company_site/AdminMaster/views.py` | Modified | `_authenticate()` — REGX first, local fallback. `login()` otherwise unchanged |
| `backend/authorization/views.py` | Modified | `my_roles_view` — the caller's own role names |
| `backend/authorization/urls.py` | Modified | Routed `/permissions/mine/` |
| `backend/authorization/tests/test_authorization.py` | Modified | 5 tests for the above. 9 passed |
| `company_site/RAAI/settings_integration.py` | Modified | `REGX_AUTH_URL`; blank disables delegation |
| `compose.yaml` | Modified | Passes `REGX_AUTH_URL` to company_site |

### Test suite (this session)

| File | Status | Purpose |
|---|---|---|
| `backend/common/tests/test_regulatory_claim_guard.py` | Modified | Four ported apps added to `GOVERNED_MODULES` — they were under no guard |
| `compose.yaml` | Modified | Mounts `./docs:/docs:ro` so the doc-consistency tests can find their file |

### Ported features

| Directory | Purpose |
|---|---|
| `backend/deficiencies/` | FDA deficiency corpus, 7,458 rows. Platform-level, not tenant-scoped |
| `backend/inspections/` | Form 483 — 187 inspections, 851 observations. Warning letters: model and importer exist, **0 rows loaded** (see §2) |
| `backend/product_comparison/` | 49+33 legacy columns normalised into attribute rows |
| `backend/controlled_correspondence/` | Published guidance (platform) + drafts (tenant) |
| `backend/iig_checklist/gap_analysis.py` | Rebuilt. No model, no migration — computed on demand |

### company_site repair

| File | Purpose |
|---|---|
| `company_site/add_missing_columns.py` | Adds the 134 columns the shipped sqlite lacks. Additive only; **back up `db.sqlite3` first** |
| `company_site/create_demo_users.py` | Creates the three legacy demo accounts with their `AssignChecker` rows |
| `company_site/dump_routes.py` | Regenerates `ROUTES.md` from the live URLconf |
| `company_site/RAAI/slash_tolerance.py` | Makes the trailing slash optional |
| `infra/nginx/nginx.conf` | The 8080/8090 split |

Root `diagnose.py` and `gpt_input_data*.xlsx` are legacy-branch artefacts, left
untracked on purpose.

## 4. Changes Made

Thirteen commits. The ones whose reasoning is not obvious from the diff:

**Shared sign-in delegates rather than shares a session.** The two Django apps
sign with different `SECRET_KEY`s over different session stores; making one
cookie work in both would mean weakening one side's configuration. Only the
credential check is shared — each app still issues its own session.

**Mirrored accounts get an unusable local password**, so the local fallback can
never become a second way into a REGX identity. The fallback stays for the
Django superuser, pre-existing company accounts, and REGX outages.

**`/permissions/mine/` had to be added.** `/permissions/roles/` lists which
roles exist and `/permissions/effective/` lists what the caller may do; neither
answers "which role am I", and inferring it from a permission set breaks the
moment a role is edited.

**Two legacy models collapsed into one** in `deficiencies`. `AIDatabase.ANDA`
and `AIDatabase.MajorCR` were structurally identical, differing only in source
roadmap. One model, `corpus` discriminator.

**Reference corpora are platform-level, not tenant-scoped.** Published FDA
material is the same category as `fda_data.FDADataSourceRelease`. Every tenant
reads the same corpus; none can edit it.

**Classification left as free text.** 76 distinct `deficiency_type` spellings,
including near-duplicates differing only by whitespace. Normalising it is a
governance exercise with an approval trail, not a silent step in a port.

**Gap analysis rebuilt, not ported.** The legacy version scores 2 of 6 checklist
families and is tied to models that are not coming across.

**483 storage redesigned.** The legacy app serves it from in-process pandas
DataFrames with `.pkl` snapshots, which does not survive multiple gunicorn
workers. Database-backed here.

## 5. Failed Attempts

Recorded so they are not repeated.

**0. Ran the full test suite against the wrong settings module.**
`pyproject.toml` sets `regx.settings.test`, but the container's environment sets
`regx.settings.production` and the environment wins. Production has no
`CELERY_TASK_ALWAYS_EAGER`, so queued tasks never ran and 7
`external_integrations` tests failed with messages that read like genuine bugs
(`ingest was never called`, `DocumentVersion matching query does not exist`).
Nearly reported them as pre-existing failures. **Establish that the harness is
right before drawing any conclusion from what it reports.**

**1. Splitting the admin surface onto its own listener — failed three times.**
Splitting the whole `/adminmaster/` prefix broke login; narrowing it 404'd the
admin landing page; the narrowed version then 404'd every console link.
Conclusion: **the admin surface is not a separable subtree of this application.**
The working arrangement serves the whole app on both listeners and has 8080
refuse the handful of user-management routes.

**2. Permission class read `request.tenant` — always denied.**
`TenantMiddleware` does not attach the tenant to the request; it goes through
`tenancy.context.current_tenant()`. Every endpoint returned 403 while looking
like correct fail-closed behaviour. **This is the dangerous shape** — a
permission bug that denies is invisible to a smoke test.

**3. `.objects.all()` without the report-type filter.** Cross-report data bleed.
Every affected view returned HTTP 200 throughout. **200s do not catch wrong data.**

**4. `cast(raw)` in the settings `env()` helper.** Would have shipped
`DEBUG=True` to production, because `bool("False")` is `True`. Reverted.

**5. Facets returned 7,458 rows instead of the distinct set.** `Meta.ordering`
leaks into `SELECT DISTINCT`. Fixed with `.order_by()`, pinned by a test.

**6. Starting a server without reading the request path** triggered 71 paid
OpenAI calls from a single `GET /`. Now gated behind
`ENABLE_OBSERVATION_SUMMARIES`, default off.

**7. Assuming the demo passwords in `create_demo_users.py` matched the
database.** They had drifted. Re-run the script rather than trusting the file.

**8. Session cookie not returned on the internal hop.** REGX sets
`SESSION_COOKIE_SECURE = True`, so `requests` correctly refuses to send it back
over plain HTTP between containers, and the role lookup arrived
unauthenticated. Fixed by re-presenting the cookie on that one hop — **not** by
weakening the setting.

## 6. Next Steps

1. **Run `test-checklist.md` end to end.** It is written to be executed top to
   bottom by someone who has not seen this code.

2. **Keep the suite green.** It ends clean as of 2026-09-09, which is worth
   protecting: a suite with a few permanently-red lines is one whose next real
   failure nobody notices. If something goes red, check the two environment
   notes in `test-checklist.md` §7 before reading application code — eleven of
   the first run's fourteen failures were the environment, not the code.

3. **Decide the MFA question.** REGX sets `mfa_required` and never checks it.
   Either wire enforcement into the permission layer or record deliberately that
   MFA is optional. Leaving it half-built is the worst of the three.

4. **Decide what happens to the gitignored `.xlsx` workbooks.** A fresh clone
   cannot run the AIDatabase screens without them.

5. **Get a corrected AIDatabase export** with `Country`, `FEI Number` and
   `Organization Name`. Four lookups stay broken until it arrives.

6. **Build the React pages** for the six ported APIs. All endpoints are live and
   documented at `/api/docs/`.

7. **Open the PR against `regx-main`** if it is not already open.

## 7. Local access

**One credential set now works for both applications.**

| Where | Sign in at |
|---|---|
| REGX frontend | http://localhost:3000/signin |
| Legacy tools | http://localhost:8080/adminmaster/login/ |
| Legacy admin console | http://localhost:8090/adminmaster/login/ |

Test accounts created this session (REGX identities, mirrored into company_site
on first company sign-in):

| Email | Password | REGX role | Company role | Lands on |
|---|---|---|---|---|
| `sso.admin@praverse.test` | `RegxSso2026` | `tenant_admin` | `admin` | `/adminmaster/adminbase` |
| `sso.doer@praverse.test` | `RegxSso2026` | `doer` | `company_user` | `/ratools/` |
| `sso.vp@praverse.test` | `RegxSso2026` | `vp` | `company_checker` | `/ratools/` |

Legacy-only accounts, still working through the local fallback:

| Username | Password | Role |
|---|---|---|
| `regx_admin` | `RegxAdmin#2026` | admin |
| `regx_user` | `RegxUser#2026` | company_user |
| `regx_checker` | `RegxUser#2026` | company_checker |

These are **local demo credentials for a local database**. They are not
deployed anywhere and must not be created in any environment that is.

Tenant-scoped REGX endpoints require the header **`X-Tenant-Slug: praverse`**.
API docs: http://localhost:8000/api/docs/
