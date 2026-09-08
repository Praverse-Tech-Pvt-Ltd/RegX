# Project Handoff

Session date: 2026-09-08. Repo: `Praverse-Tech-Pvt-Ltd/RegX` (Django 5.1 monolith, project package `RAAI`).

## 1. Goal

Get the freshly-cloned RegX app running locally and fix the backend wiring that
prevented it from working, then harden it for deployment.

Constraints that shaped the work:

- The hardcoded OpenAI API key in `AIDatabase/filters.py` was to be left in
  place (explicit user instruction). It is **not** rotated and **not** removed.
- Changes were to stay surgical — fix what is broken, not refactor adjacent code.

## 2. Current State

**Branch:** `fix/backend-wiring-and-deploy-hardening`, pushed to origin.
**Commit:** `4193f09` — 16 files, +1002 / −168. Working tree clean.
**PR:** https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/45 — OPEN, MERGEABLE, not merged.

**Tests:** `python manage.py test` → **50 tests, OK** (observed at end of session).
Was 26/36 with 10 errors at session start.

**No CI exists** (`.github/workflows/` is absent), so the PR runs no checks. The
50 passing tests are from local runs only.

**Server:** running at http://127.0.0.1:8000 via `manage.py runserver` (background
process, will not survive a machine restart).

### Working

- Login and all authenticated pages, for all three roles.
- 36 checklist table routes × 3 roles, all HTTP 200 (verified by driving the app).
- Full flow end to end: create checklist → submit as doer → review → approve as
  checker → audit entry written.
- Django admin for the four `Regulatory*` models; audit trail, gap report and
  review gate are view-only (POST to change/delete returns 403).
- `manage.py check --deploy` clean except two deliberate HSTS opt-outs.

### Known defects (all pre-existing, none introduced this session)

- **Hardcoded OpenAI API key** in `AIDatabase/filters.py` (~line 14), plus more in
  commented code in `AIDatabase/views.py` (~5328, ~5464). Present in git history.
  Left in place per instruction. **Still needs rotating.**
- `CORS_ALLOW_ALL_ORIGINS = True`, set twice in `RAAI/settings.py`.
- No rate limiting anywhere.
- `AdminMaster` and `AIDatabase` have **no migrations** (gitignored, absent). Their
  schema exists only in the sqlite snapshots, which are 24 tables and 135 columns
  behind the current models. Only `RATools` has migrations.
- `APPEND_SLASH = False` with inconsistent coverage: of 171 RATools routes, 90 work
  only *without* a trailing slash, 80 only *with* one, 1 works both ways. A 404 is
  often just the wrong slash.
- `/ratools/module/` 500s for every role — `module_view` does `os.listdir()` on
  `media/Module_Simplification`, which is gitignored and absent. No code fix
  possible; the content is not in the repo.
- `statues[level][user_id][first_name]` keys workflow status by first name, so
  renaming a user orphans their in-flight reviews. Preserved as-is deliberately.

### Environment assumptions

- `.venv/` with `requirements.txt` installed; `.claude/launch.json` expects
  `.venv/Scripts/python.exe`.
- `.env` exists locally (copied from `.env.example`, all values blank). Gitignored.
- `db.sqlite3` is a **fresh** database built with `migrate --run-syncdb`, not the
  shipped snapshot. It contains no FDA 483 or warning-letter data. Reference data
  (question banks, deficiency tables — 7,679 rows) was ported from
  `db_17_1_2.sqlite3`. Backups: `db.sqlite3.bak.*`.
- `ENABLE_OBSERVATION_SUMMARIES=False` — **leave it off** unless a paid generation
  run is intended (see Failed Attempts).

### Unverified

- Nothing on this branch has run in production or behind a real TLS proxy. The
  `SECURE_PROXY_SSL_HEADER` / `SECURE_SSL_REDIRECT` combination is reasoned-about
  and unit-checked, not observed against Render.
- The migration gap for `AdminMaster` / `AIDatabase` was measured but not fixed.

## 3. Active Files

| File | Status | Purpose |
|---|---|---|
| `RAAI/settings.py` | Modified | `env()` blank-value helper; SECRET_KEY production guard; transport security block |
| `RATools/views.py` | Modified | 64 admin `else` branches; `checker_has_open_review()` replacing 26 unguarded lookups |
| `RATools/admin.py` | Modified | Registered 4 `Regulatory*` models; `_ReadOnlyModelAdmin` for the three that must not be edited unaudited |
| `AIDatabase/filters.py` | Modified | OpenAI v1 client port; search filter six-tuple unpack + literal fallback. **Holds the hardcoded key** |
| `AIDatabase/observation_summary.py` | Modified | `ENABLE_OBSERVATION_SUMMARIES` gate; prompts hoisted to module constants |
| `AIDatabase/context_processors.py` | Modified | `base_url` blank-value fallback |
| `AIDatabase/management/commands/export_gpt_input_data.py` | Created | Exports what would be sent to OpenAI, without calling it |
| `RATools/tests.py` | Modified | +6 tests for the checker guard |
| `AIDatabase/tests.py` | Modified | +8 tests for the search filter (was empty boilerplate) |
| `CLAUDE.md` | Created | Repo guide for future sessions; includes test-account cleanup one-liner |
| `.env.example` | Modified | Documents the new env vars |
| `AdminMaster/views.py` | Reviewed, unchanged | Login device-token gate; `internal_team` bypasses it in PRODUCTION |
| `AdminMaster/models.py` | Reviewed, unchanged | `AssignChecker` — several views call `.get()` on it with no `try/except` |

## 4. Changes Made

**Configuration**

- Added `settings.env()`: a present-but-blank `.env` value falls back to its
  default. `decouple` returns `""` for those, which produced an empty `SECRET_KEY`
  — every signing call raised `ImproperlyConfigured`, so login and sessions were
  dead. Routed all 15 config reads through it. Boot now fails loudly on a blank or
  dev `SECRET_KEY` when `DEBUG=False`.
- Added transport security defaulting to on in production: `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`.
  `SECURE_PROXY_SSL_HEADER` is set alongside the redirect — **without it a
  TLS-terminating proxy causes an infinite redirect loop**. HSTS starts at 1 hour,
  not a year, because `max-age` cannot be withdrawn early.

**Role handling**

- 64 views branched on `company_user` / `company_checker` with no `else`, so every
  `role="admin"` request raised `UnboundLocalError`. Added read-only oversight
  branches. Each query keeps its own view's report-type filter and drops only the
  user scoping; the `assigned_report` authorisation gate still applies.
- `checker_has_open_review()` replaces 26 copies of an unguarded status lookup that
  raised `TypeError`/`KeyError` when a checker opened an unsubmitted checklist.

**OpenAI**

- `ENABLE_OBSERVATION_SUMMARIES` (default off) gates summary generation.
- Ported `filters.py` from the removed `openai.ChatCompletion` to the v1 client and
  pinned `openai>=1.0,<4`. Fixed the caller, which assigned a six-tuple to one name
  and iterated it, producing `Q(content__icontains=[...])`.

**Admin**

- Registered the four `Regulatory*` models. Without `RegulatoryRole` there was no
  way to grant a doer/reviewer/vp role, leaving the review flow unreachable.
- Audit trail, gap report and review gate are view-only: `ModelAdmin.save_model()`
  would change a gate's status without writing a `RegulatoryAuditTrail` entry.

**Database** — rebuilt `db.sqlite3` from current models and ported 7,679 reference
rows from `db_17_1_2.sqlite3`, copying only columns present in both schemas.

**Also** — `base_url` fallback, two `{{BASE_URL}}` template typos that always
rendered empty, 14 tests, `CLAUDE.md`.

## 5. Failed Attempts

**1. Starting the server before reading the request path — cost real money.**
With a working database, a single `GET /` triggered a synchronous pass over 8,362
observation blocks, calling OpenAI on the hardcoded key. **71 `gpt-4.1-mini` calls
were made before it was stopped.** Isolated and reproduced: no requests → 0 calls;
one `GET /` → 6 calls in 3 seconds. The stale snapshot had been masking this by
erroring out early — the broken schema was acting as an accidental billing brake.
Resolved by the `ENABLE_OBSERVATION_SUMMARIES` gate. **Not reverted; the 70
resulting summaries are committed in `tmp/summaries/summary_checkpoint.json` so
those blocks are not paid for twice.**

**2. `reports = Model.objects.all()` for admin — cross-report data bleed.**
The doer branch filters on *two* things (`report_name__report_name` and `user`);
dropping "the user filter" dropped both. An MDI/DPI checklist appeared on the
Microsphere, Liposome and General tables. Caught during self-review, not by the
route checks — HTTP 200s do not catch wrong-data bugs. Fixed by deriving each
admin query's filters from its own doer branch minus user scoping (35 queries).

**3. Simplifying `env()` to `cast(raw)` — would have shipped `DEBUG=True` to production.**
Attempted as a line-count reduction. `bool("False")` is `True`, so `DEBUG=False`
resolved to `True`, which would also have silently bypassed the `SECRET_KEY`
guard. **Reverted**; the double `config()` read is deliberate and now carries a
comment saying so.

**4. Handing over the `localdev` account without an `AssignChecker` row.**
Several views call `AssignChecker.objects.get(user=...)` with no `try/except`, so
the account 500'd on every checklist page — reported as "the routes are broken".
The account was also `role="admin"`, which hit failure #5 as well. `localdev` has
been deleted.

**5. Assuming `role="admin"` was the most capable account.** It is the least
useful for the tools: 104 view checks on `company_checker`, 66 on `company_user`,
5 on `admin`. Use `ra_doer` / `ra_checker` for feature testing.

**6. Patching the shipped sqlite snapshot was considered and rejected.** All three
snapshots are 24 tables / 135 columns behind the models, and `NOT NULL` defaults
would have been guesswork. A fresh DB plus a column-intersection port of reference
data was chosen instead.

## 6. Next Steps

1. **Rotate the OpenAI API key.** It is live in `AIDatabase/filters.py` and in git
   history, and it is now on a reachable code path. Rotate at the provider first —
   removing the line does not invalidate the key. Then move it to `OPENAI_API_KEY`
   in the environment; `_get_openai_client()` in `filters.py` and
   `_get_openai_api_key()` in `observation_summary.py` are the only two readers.
2. **Get PR #45 reviewed and merged**, or say what needs changing:
   https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/45
3. **Add a CI workflow** running `python manage.py test`. The repo has 50 tests and
   nothing runs them; the PR currently has no checks.
4. **Decide the migration story for `AdminMaster` and `AIDatabase`.** They have no
   migrations and the snapshots have drifted badly. Until this is resolved, nobody
   can rebuild the database from code, and new models in those apps are risky.
   Verify any generated migration against a real snapshot copy, not a fresh DB.
5. **Before deploying**, delete the local test accounts if the local DB travels
   with the deploy: `CustomUser.objects.filter(username__startswith="ra_").delete()`
6. **Repopulate FDA data** if the app needs real content — the importers are in
   `AIDatabase/management/commands/import_*` and read the bundled `.xlsx` files.
   Run with `ENABLE_OBSERVATION_SUMMARIES=False` unless a paid summary pass is
   intended; `python manage.py export_gpt_input_data --only-pending` shows the cost
   first (currently 1,265 of 8,362 blocks would call the API).
7. **Optional:** fix `CORS_ALLOW_ALL_ORIGINS`, add rate limiting, and guard
   `module_view` so a missing `media/Module_Simplification` renders empty instead
   of a 500.

### Test accounts (local `db.sqlite3` only)

`ra_admin` / `ra_doer` / `ra_checker`, login at `/adminmaster/login/`. The password
is local-only and deliberately not recorded in the repo — reset it with
`python manage.py changepassword ra_doer` if you don't have it.

Any account created by hand needs an `AssignChecker` row or it will 500 on the
checklist pages.
