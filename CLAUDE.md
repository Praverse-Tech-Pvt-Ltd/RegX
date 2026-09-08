# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Django 5.1 monolith (project package `RAAI`) serving two distinct products behind one login:

- **RATools** — "Regulatory Technical Tools AI": ANDA / DMF / IIG / Validation / VP checklists, product comparison, white papers, controlled correspondence, plus newer gap-analysis, Doer→Reviewer→VP review gates and a Part 11-style audit trail.
- **AIDatabase** — "483 Database AI": FDA Form 483 observations, warning letters, GMPC data, investigator analytics, deficiency lookup tables.
- **AdminMaster** — shared auth (`CustomUser`, `AUTH_USER_MODEL`) and the legacy multi-level checker assignment model (`AssignChecker`).

Routing is clean per app in `RAAI/urls.py` (`/ratools/`, `/aidatabase/`, `/adminmaster/`); marketing/static pages hang off the root.

## Commands

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows; repo's .claude/launch.json expects .venv/Scripts/python.exe
pip install -r requirements.txt
cp .env.example .env                                # then fill in values

python manage.py runserver 0.0.0.0:8000
python manage.py check
python manage.py migrate
python manage.py test                               # all tests (RATools + AIDatabase)
python manage.py test RATools.tests.RegulatoryRoleTests.test_role_can_be_assigned   # single test
```

`.env` is required — `manage.py` reads it via python-decouple. `settings.env()` treats a
present-but-blank value as unset, so the blank placeholders in `.env.example` fall back to
their declared defaults. With `DEBUG=False`, a blank/dev `SECRET_KEY` refuses to boot rather
than silently running on the insecure default.

Production build/start (see `build.sh`, `render.yaml`): `./build.sh` then `gunicorn RAAI.wsgi:application`.

Bulk data importers live in `AIDatabase/management/commands/` (`import_form_483`, `import_deficiency_data`, `import_major_cr`, `import_validation_data`, `import_investigator_themed_keywords`, `generate_gmpc_metrics`, `fda_483_dashboard_data_generator`) and read the `.xlsx` files sitting next to them.

## Database — read this before touching models

- `settings.DATABASES` points at `db.sqlite3`, which is **gitignored**. The repo ships snapshots (`db_17_1_2.sqlite3`, `db_old.sqlite3`, `db_corrupted.sqlite3`); local dev works by copying `db_17_1_2.sqlite3` to `db.sqlite3`.
- **Only `RATools` has migrations** (`0001_initial`, `0002_regulatorygapanalysisreport`). `AdminMaster/migrations/` and `AIDatabase/migrations/` are gitignored and absent — those apps' tables exist only in the sqlite snapshot. Their schema has drifted from `models.py`; generating fresh migrations against the snapshot has previously failed on a FK mismatch.
- Consequence: any new model needs a migration, and it must be verified against the real snapshot DB, not just a fresh one. Do not run `makemigrations` for `AdminMaster`/`AIDatabase` casually.

## Architecture notes worth knowing

**Views are enormous and procedural.** `RATools/views.py` is ~14.5k lines, `AIDatabase/views.py` ~7.3k. There is one view function per checklist route, and `RATools/urls.py` (~680 lines) enumerates a route trio (`show_*_table` / `add_*_checklist` / `delete_*_checklist`) per dosage form. `APPEND_SLASH = False`, so many routes are registered twice, with and without the trailing slash. When adding a route, follow that pattern rather than fighting it.

**Newer RATools work is deliberately modular** — put new logic here, not in `views.py`:
- `RATools/audit.py` — `log_event(...)` is the only sanctioned way to write `RegulatoryAuditTrail`. Entries are immutable: `save()` rejects updates, `delete()` is disabled.
- `RATools/gap_analysis.py` — ANDA/DMF checklist gap scoring; a "gap" is an explicit `"no"` answer, unanswered questions are excluded from both numerator and denominator.
- `RegulatoryReviewGate` / `RegulatoryRole` / `RegulatoryAuditTrail` attach to any target via generic FK (`content_type` + `object_id`), so new artifacts get review + audit without schema changes on the artifact model.

**Two parallel role systems exist.** Legacy: `CustomUser.role` (`admin` / `company_user` / `company_checker`) plus `AssignChecker` with 7 independent checker-level M2M fields and a flat `REPORT_CHOICES` list that mixes RATools and AIDatabase report types. New: `RegulatoryRole` (`doer` / `reviewer` / `vp`), scoped to RATools only, intentionally kept separate so 483 workflow behavior is not retroactively changed. Do not merge them without being asked.

**Deficiency data is misplaced by design-drift.** `AIDatabase.models.ANDA` and `AIDatabase.models.MajorCR` are deficiency lookup tables that semantically belong to RATools scope, and `ANDA` collides by name with three unrelated `RATools` checklist models (`ANDAReportQuestions` / `ANDAUserReports` / `ANDAUserAnswers`). Both apps use `from .models import *`, so name collisions are easy to cause. Be explicit about which `ANDA` you mean.

**Excel data is served from an in-process DataFrame cache**, not the DB. `AIDatabase/views.py` keeps module-level dicts (`EXCEL_DF_CACHE`, `GMPC_EXCEL_DF_CACHE`) keyed by a file-signature source key, persisted to `.pkl` snapshots, and refreshed via `refresh_form483_excel_cache` / `refresh_gmpc_excel_cache`. Those refreshes are wrapped as Celery tasks in `AIDatabase/tasks.py`. This is per-process state — it does not survive or share across gunicorn workers.

**Form 483 observations get LLM-summarized on cache build.** `AIDatabase/observation_summary.py`
`process_observation_summary(df, previous_df)` is called from `AIDatabase/views.py:568` during the Excel
cache refresh: it groups rows by company/observation context, calls `gpt-4.1-mini` for a summary constrained
to 20-35% of the source word count, and writes a `Summary` column. Results are memoized to
`tmp/summaries/summary_checkpoint.json` keyed by a hash of the merged text, so re-runs skip already-summarized
groups; `clear_summary_checkpoint()` resets it. This module reads `OPENAI_API_KEY` from the environment
(unlike `filters.py`, below), and no-ops with a warning when it is unset.

**Celery runs eager by default.** `CELERY_TASK_ALWAYS_EAGER=True` in `.env.example` and `render.yaml`, so tasks execute synchronously in-process and no Redis is needed. Set it to `False` and provide `CELERY_BROKER_URL` only once a broker exists.

**Login has two modes.** `AdminMaster/views.py` reads `config("SERVER")`; when it is `PRODUCTION` and the user is not `internal_team`, login is locked to a `device_token` cookie set on first login. Anything else (including unset) uses the simplified local path.

**Email has two paths.** Ordinary Django SMTP (`EMAIL_*` settings) for general mail, and Microsoft Graph (`RATools/graph_email.py`, `AZURE_*` settings) for demo-booking confirmations with an inline logo and `.ics` attachment built by `RATools/ics_builder.py`. Graph config is blank by default and raises at send time, not at import.

**Static files**: `whitenoise.storage.CompressedStaticFilesStorage` (not the Manifest variant) — vendored CSS references `.css.map` files that aren't shipped, and Manifest storage fails `collectstatic` on those. `static/` also carries a legacy gulp setup (`gulpfile.js`, `gulp-tasks/`) with no `package.json`; treat it as dead unless asked.

## Local test accounts

`ra_admin` / `ra_doer` / `ra_checker` (password `Test@1234`) exist in the local
`db.sqlite3` only. Roles matter: most tool views branch on `company_user` /
`company_checker` and 5 checks on `admin`, so use `ra_doer` or `ra_checker` to
exercise the checklists. Each needs an `AssignChecker` row — several views call
`AssignChecker.objects.get(user=...)` with no `try/except` and 500 without one.

Delete them before any deploy that reuses a local database:

```python
CustomUser.objects.filter(username__startswith="ra_").delete()
```

## Known issues (pre-existing, flagged in the audit reports)

- **`AIDatabase/filters.py` contains a live hardcoded OpenAI API key** (`openai.api_key = "sk-proj-..."`), with more in commented-out code at `AIDatabase/views.py:5328` and `:5464`. Per the project's own baseline report, this blocks AI-powered work until removed and rotated. `_get_openai_client()` reads that module-level key, so moving it to `OPENAI_API_KEY` in the environment is a one-line change there.
- Test coverage is limited to `RATools/tests.py` and `AIDatabase/tests.py`; `AdminMaster/tests.py` is empty boilerplate. There are no factories, fixtures, or pytest config.
- `django-ckeditor` bundles CKEditor 4.22.1 — `manage.py check` emits `ckeditor.W001` about unfixed security issues. Pre-existing, unrelated to most work.

`REGULATORY_TECHNICAL_TOOLS_BASELINE_REPORT.md` and `REGULATORY_TOOLS_CODEBASE_INSPECTION_REPORT.md` at the repo root hold the detailed audit of what exists vs. the project SOW; consult them before planning new RATools features. Note they predate the audit-trail/role/gap-analysis commits, so some "Missing" rows are now implemented.
