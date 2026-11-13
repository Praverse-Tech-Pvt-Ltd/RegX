# Credential inventory

**Date:** 2026-11-06; section 8 added 2026-11-13. **Author:** Claude Code session for Maanav. **Status:** report only. No credential was revoked, rotated, removed or used.

**This document contains no credential value and no part of one.** Distinct values are told apart by a hash computed in memory during the scan and labelled A, B, C here. Lengths, prefixes and suffixes are deliberately not given.

## 1. How this was checked

- **What was scanned:** every text blob reachable from any ref in the repository: all `origin/*` branches, all tags (including `archive/*`), and the heads of all 106 pull requests (fetched read-only into local `refs/prheads/*`; nothing was pushed). 2,179 text-like blobs out of 6,733 objects. Binary files (SQLite databases, spreadsheets) were not scanned for text.
- **Patterns:** OpenAI keys (`sk-…` in all its forms), Django `SECRET_KEY` literals and `django-insecure-…` keys, SMTP/e-mail password assignments, AWS access key ids, GitHub tokens, private-key blocks, Azure client-secret literals, Fernet keys. Placeholders (`change-me`, `example`, `${…}`, `test-…`, `ci-…`) are skipped.
- **Running configuration:** `compose.yaml`, `.env.example`, `company_site/.env.example`, every workflow in `.github/workflows/`, `scripts/`, and the local (untracked) `.env`. Values were compared by hash only.
- **Limits:** the repository can only show what was committed. It cannot show where a key was used outside git (a laptop, a server, a Render or OpenAI account). Those checks need account access (section 5).

## 2. Summary

| # | Credential | Service | Where (path:line) | Branches / tags still containing it | Live reference in current REGX config? | Owner action |
|---|---|---|---|---|---|---|
| 1 | OpenAI key **C** | OpenAI API | `main`: `AIDatabase/filters.py:37` (**uncommented, used by the code**), `AIDatabase/views.py:5465` (commented). Earlier version: `filters.py:14` | `origin/main`, tags `archive/docs/setup-and-sow-status`, `archive/fix/backend-wiring-and-deploy-hardening`, `archive/fix/claude-md-db-setup-instruction` | **No** (REGX and `company_site/` read only `OPENAI_API_KEY` from the environment; compose does not set it). **Yes on `main`**: any deployment of `main` uses this key from code | **Revoke** in the OpenAI account; check its usage history |
| 2 | OpenAI key **B** | OpenAI API | `main`: `filters.py:35,36`, `views.py:5328,5329,5464` (all commented). Earlier version: `filters.py:12,13` | same as #1 | No | **Revoke** (a commented key is still a valid key until revoked) |
| 3 | OpenAI key **A** | OpenAI API | `main`: `filters.py:34` (commented). Earlier version: `filters.py:11` | same as #1 | No | **Revoke** |
| 4 | SMTP password | E-mail account behind `EMAIL_HOST` (default `smtp.office365.com` on `main`) | `main`: `RAAI/settings.py:171` (commented literal at the tip); in earlier versions also at `:142,:149,:150` | same as #1 | No. `main` now reads `EMAIL_HOST_PASSWORD` from the environment (`:178`); `company_site/RAAI/settings.py:156` on `regx-main` does the same with a blank default; compose and `.env` do not set it | **Rotate** the mailbox password and review its sign-in log |
| 5 | Django `django-insecure-…` secret key (one value) | Django signing (sessions, password-reset tokens, CSRF) | `main`: `RAAI/settings.py:48` (`DEV_SECRET_KEY`, used when `SECRET_KEY` is unset; refused when `DEBUG` is False); earlier at `:27,:29`. **`regx-main`: `company_site/RAAI/settings.py:29`, as the default of `SECRET_KEY`** | `origin/main`, `origin/regx-main`, every current `regx/*` branch, the 3 archive tags above, `archive/regx/feat/final-validation-release` | **Not used by the current stack**: compose requires `COMPANY_SECRET_KEY` (`${COMPANY_SECRET_KEY:?…}`) and passes it as `SECRET_KEY`; the local `.env` value differs from the leaked one; no CI workflow, script or `.env.example` reuses it (hash check, 0 matches). Until 2026-11-06 it **would** have been used by any company_site run without `SECRET_KEY` set. **Update 2026-11-06 (branch `regx/fix/company-site-secret-key`): the fallback is removed from current code**; company_site now refuses to start without `SECRET_KEY`, and no tracked file on that branch contains the value (hash check over 1,228 text files). **It stays in git history** (`main` and earlier `regx-main` commits) | **Confirm** no deployment of `main` or company_site ever ran with it; **rotate** on any that did. Still needs the owner action in section 5 (history keeps the value; removing it from code does not make it safe) |
| 6 | Demo passwords for the legacy company_site admin and user | company_site login | `regx-main`: `company_site/create_demo_users.py:25-26` (added `efcfab4`, 2026-09-09) | `origin/regx-main` and its branches | Only when someone runs `create_demo_users.py` (manual; `test-checklist.md:163`) | **Confirm** these accounts exist only on local machines; if they exist on any shared environment, change the passwords there |
| 7 | Six local demo passwords in `handoff.md` | REGX demo users | `handoff.md` in 8 commits, first `cdf1b5f` (2026-09-08); removed by `4338202` (2026-10-12, PR #85). Still in history | history only (the tip has prose about passwords, no values) | No (the demo seed now takes `--password-env`) | **Confirm** the demo users were never created on a shared environment with those passwords |
| 8 | Fernet key for `MFA_ENCRYPTION_KEY` | REGX MFA secret encryption | `.github/workflows/docker-integration.yml:30,32,33` (15 commits, `1741a26` 2026-07-23 to `21040ce` 2026-09-17) | `origin/regx-main`, every `regx/*` branch, 3 release tags | CI only. **The local `.env` uses a different key** (hash check) | **Confirm** it was never copied into a real environment; it is a deliberate CI throwaway |
| 9 | 9 password hashes in `db_17_1_2.sqlite3` | legacy main users | `main` (binary file; overview §11 #2) | `origin/main` | No | **Confirm** whether those accounts are real; if so, force a password reset |
| 10 | User rows in the tracked `company_site/db.sqlite3` | company_site users | `regx-main` (overview §11 #10h) | `origin/regx-main` | Yes, it is the company_site database | Owner decision already open in §11 #10h |

**Not found anywhere in history:** AWS access keys, GitHub tokens, private-key blocks, Azure client-secret literals (`main` `RAAI/settings.py:188` reads `AZURE_CLIENT_SECRET` from the environment), any tracked `.env` file other than `.env.example` and `company_site/.env.example`.

**Accepted CI throwaways (not credentials for any real system):** the `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`/`DB_PASSWORD` and `COMPANY_SECRET_KEY` values in `.github/workflows/backend.yml`, `docker-integration.yml` and `operational-scripts.yml`.

## 3. Commits

All three OpenAI keys (#1–#3), the SMTP password (#4) and the `main` copy of the Django key (#5) were introduced in `dff6856` (2026-07-13; `b00c429` the same day for one location) and are still present in `4193f09` (2026-09-08), the last commit on `main` that touches those files. They have never been removed from `main`. The `regx-main` copy of #5 arrived with `company_site/`; it is removed from current code by `regx/fix/company-site-secret-key` (2026-11-06) but remains in history.

The repository is private and has no forks (checked 2026-11-06), so exposure is limited to people with read access to the repository, plus anyone who received a clone, a zip or a Docker image built from `main` (see overview §11 #10g for the image check).

## 4. Does any current compose or deployment config depend on them?

- **REGX (`regx-main`, `compose.yaml`): no.** Every secret comes from `.env` through required variables (`DJANGO_SECRET_KEY:?`, `MFA_ENCRYPTION_KEY:?`, `COMPANY_SECRET_KEY:?`). `OPENAI_API_KEY` and `EMAIL_HOST_PASSWORD` are not mentioned in `compose.yaml` and not set in `.env`. company_site reads `OPENAI_API_KEY` only from the environment (`company_site/AIDatabase/observation_summary.py:266-267`), and its CI job refuses to run if the key is set.
- **`main` (legacy): yes, in code.** OpenAI key C is a literal in `AIDatabase/filters.py:37`, so every deployment of `main` calls OpenAI with it. `main` has a `render.yaml` defining one Render web service (`booking-demo-final`, free plan) with a Render-generated `SECRET_KEY` (`generateValue: true`) and `DEBUG=False`, so a Render deployment would not use the leaked Django key, but would use key C. **Whether that Render service exists or still runs can only be checked in the Render account.**
- **Rotating any of these credentials does not affect the REGX stack.** It would break only a running deployment of `main` (OpenAI calls through key C, and e-mail if the password is set in that deployment's environment).

## 5. Owner actions (in priority order)

Nothing below was done by this session. These are for the owner (Pratham) or whoever holds the accounts.

1. **OpenAI account owner:** revoke keys A, B and C (the dashboard identifies a key by its name and last characters; match them against `main` `AIDatabase/filters.py:34-37` locally, not in chat or tickets). Review usage for unexpected spend since 2026-07-13.
2. **Microsoft 365 / mail admin for the account configured as `EMAIL_HOST_USER` on `main`:** rotate the password; review sign-in logs since 2026-07-13.
3. **Render account owner:** confirm whether `booking-demo-final` (or any service built from `main`) exists. If it does, it is running with key C; revoke first, then decide whether to keep the service.
4. **Owner:** confirm no environment ran company_site or `main` with the `django-insecure` key; rotate wherever it did.
5. **Owner:** confirm the demo accounts (#6, #7) and the database accounts (#9, #10) exist only locally, or reset them.
6. **Afterwards:** a history rewrite of `main` is a separate decision. Revocation makes the leaked values useless; rewriting history does not, and it changes every commit SHA.

## 6. Corrections to earlier documents

- `PROJECT_OVERVIEW.md` §8 said "literal SMTP passwords in `RAAI/settings.py:171,178`". At the tip, line 171 is a commented literal and line 178 is an environment lookup: **one** literal, commented.
- `PROJECT_OVERVIEW.md` §8 said "plus 3 commented keys in total". There are **3 distinct keys in total**: C is live (and also appears commented), A and B appear only on commented lines.
- `docs/DEPLOYMENT_BOUNDARIES.md` §6 claims the keys were purged. They were not: all three are at the tip of `origin/main` and in three archive tags.

## 7. Evidence

Scan scripts and raw output (no values) are in the session's review hand-off: `scan_history.py`, `scan_details.py`, and the running-config check.

## 8. Other org repositories (read-only scan, 2026-11-06)

**Scope:** the public repositories `iCretegy-AI483` and `iPharmaAi-booking-demo-page`, the private `booking-demo-final`, and every other org repository whose name relates to iCretegy, iPharmaAI, 483, RAAI or RATools: `483-AI-final`, `iCretegy-SaaS` (empty), and `Django-booking-demo-page` (same code family as `booking-demo-final`). Authorised by Maanav; **report only**: nothing was changed, pushed, forked, or made public/private.
**Method:** bare mirror clones into the session scratchpad (outside the repository); every blob reachable from every branch and tag scanned; values compared by in-memory hash with the known leaked values from section 2; **no value, partial value or file content printed**. Script: `scan_repo.py` (review hand-off).

### 8.1 Basic facts

| Repository | Visibility | Created | Last push | Forks | GitHub Pages | Collaborators | Refs / commits |
|---|---|---|---|---|---|---|---|
| `iCretegy-AI483` | **public** | 2026-02-11 | 2026-04-26 | 0 | not enabled | 4 | 2 / 28 |
| `iPharmaAi-booking-demo-page` | **public** | 2026-06-09 | 2026-06-23 | 0 | not enabled (homepage set to a Vercel site) | not visible to this token | 3 / 8 |
| `booking-demo-final` | private | 2026-07-13 | 2026-08-07 | 0 | not enabled | 4 | 1 / 12 |
| `Django-booking-demo-page` | private | 2026-06-24 | 2026-06-26 | 0 | not enabled | not visible | 1 / 2 |
| `483-AI-final` | private | 2026-04-27 | 2026-11-06 | 0 | not enabled | 4 | 150 / 2,760 |
| `iCretegy-SaaS` | private | 2026-02-11 | 2026-02-11 | 0 | not enabled | 4 | empty |

### 8.2 Public repositories

| ID | Repository | Finding | Location | Commits | Status | Owner action |
|---|---|---|---|---|---|---|
| **P1** | `iCretegy-AI483` (public) | **Google API key (`GEMINI_API_KEY`) in a committed `.env`** | `backend/.env` line 1 | added `88a8cc4` (2026-02-20); file removed `337a54e` (2026-02-20) | **History only, publicly readable**; not one of the known leaked values | **Revoke** the key in its Google Cloud project; check usage since 2026-02-20; decide whether the repo should stay public |
| P2 | `iCretegy-AI483` (public) | SQLite database `backend/demo.db` (69,632 B) | `backend/demo.db` | added `b813791`, removed `337a54e` (2026-02-20) | History only, publicly readable; **contents not read** | Owner checks whether it holds real or client data |
| P3 | `iCretegy-AI483` (public) | Client name "iCretegy" in code, tests and demo data (`backend/data/demo_paca.json` 22 mentions, `backend/tests/smoke_hybrid.py` 29, UI files) | several | tip | Public | Owner checks `demo_paca.json` is synthetic, not client data |
| **P4** | `iPharmaAi-booking-demo-page` (public) | `django-insecure` key as the default for `DJANGO_SECRET_KEY` (a **different** value from section 2 #5), with `DEBUG` defaulting to True | `auditmind_booking/settings.py:28` on branch `django-rewrite` | `f0b964c` (2026-06-23) | At the tip of `django-rewrite` | Confirm no deployment of that branch ran without `DJANGO_SECRET_KEY`; rotate where it did |
| P5 | `iPharmaAi-booking-demo-page` (public) | Client name mentions (`.env.local.example`, `ADMIN_SETUP_REQUEST.md`, booking API and e-mail code) | several | tip | Public | Owner checks no real contact or client details are in them |
| — | both public repos | No OpenAI key, no known leaked value, no client spreadsheets, no SOW copy, no deployment config files | — | — | — | — |

### 8.3 Private repositories

| ID | Repository | Finding | Location | At tips? | Note |
|---|---|---|---|---|---|
| R1 | `booking-demo-final` | **The same 3 OpenAI keys (A, B, C), the SMTP password and the `django-insecure` key** as `main` (section 2) | `AIDatabase/filters.py:11-14`, `AIDatabase/views.py:5328-5465`, `RAAI/settings.py:27-149` | Yes (`devp0/feat/publish-booking-demo-final`) | Shares commits `dff6856`, `b00c429` with RegX `main`: `main` was created from this repository |
| R2 | `booking-demo-final` | One further password literal (not a known value) | `RAAI/settings.py:149` | History only (`82cf43c`) | Owner checks what account it belongs to |
| R3 | `booking-demo-final` | **12 client spreadsheets**, 6 named "(For Cipla)"; 483 observation and warning-letter workbooks (largest 5,271,668 B) | `AIDatabase/management/commands/*.xlsx` | Yes | Same files as the local company_site image (overview §11 #10g) |
| R4 | `booking-demo-final` | 3 SQLite databases: `db_17_1_2.sqlite3` (7,159,808 B), `db_corrupted.sqlite3` (6,991,872 B), `db_old.sqlite3` (655,360 B) | repository root | Yes | Contents not read; `db_17_1_2` holds password hashes per overview §11 #2 |
| R5 | `Django-booking-demo-page` | **Same 3 OpenAI keys** and the `django-insecure` key; one password literal (not a known value) | `AIDatabase/filters.py`, `AIDatabase/views.py`, `RAAI/settings.py` | Yes (`main`) | Earlier copy (2026-06-24) of the same code |
| R6 | `Django-booking-demo-page` | The same 12 client spreadsheets (6 "For Cipla") and 3 Word templates | `AIDatabase/management/commands/`, `static/documents/` | Yes | — |
| R7 | `483-AI-final` | **A Google API key** (a **different** value from P1) in docs and an env template | `HANDOFF.md:82`, `backups/env.template:10`, `docs/DAY4_MOCK_FIX_EVAL_REPORT.md:59` | Yes (many branches) | 12 commits, `d2949bd5` (2026-06-18) to `45243611` (2026-10-11). **Revoke**; it is in a private repo but was committed in plain text |
| R8 | `483-AI-final` | 2 Django `SECRET_KEY` literals in a script and a test guide | `ops/release/run_differential_20261013.sh:57`, `docs/release/TEST_EXECUTION_GUIDE.md:13` | Yes | Owner confirms whether any environment used them |
| R9 | `483-AI-final` | 11 password and 11 token/API-key literals, **mostly in tests, eval and ops scripts** (e.g. `backend/tests/conftest.py`, `backend/ops/uat_final.py`, `backend/scripts/create_reviewer.py`, `frontend/src/lib/demoAuth.ts`) | various | Mostly yes | No known leaked value among them; owner triages which are real (demo/UAT accounts, JWT secrets) |
| R10 | `483-AI-final` | One `sk-` pattern inside a data file | `docs/gate1_20261024/unserved_classified.csv:2990` (and an index JSON) | Yes | Sits inside a URL path (likely an FDA warning-letter slug for a company named "SK…"), **probably not a key**; owner confirms |
| R11 | `483-AI-final` | **430 data-type files**: client QA reports (`Client_QA_Report.pdf`, `Client_QA_Sample.pdf`), an iCretegy feedback reconciliation (`backend/docs/release/ICRETEGY_FEEDBACK_RECONCILIATION_20261013.csv`), SQL data patches incl. "client findings" and UAT data, generated exports (some named after a pharmaceutical company), analytics logs | various | Many at tips | Contents not read. This repository **is the 483 AI product's code and data work**, so client content is expected; access must be restricted accordingly |
| R12 | `483-AI-final` | **Copies of the SOW**: `SOW.md`, `Conversation_Summary_iCretegy_Praverse_SOW.md`, plus SOW tracking CSVs | repository root, `backend/logs/analytics/` | Yes | Private; confidential contract text |
| R13 | `483-AI-final` | **Image-push workflow (historical):** `.github/workflows/deploy-staging.yml` built and pushed `ghcr.io/<org>/ipharmai-api` and `ipharmai-nginx` on push to `main` (GHCR login with secret `GHCR_TOKEN`) | added `aef00505` (2026-05-01), removed `54fec037` (2026-07-02) | No (removed) | **3 recorded runs, all failed before the push job** (2026-05-06 to 05-11, branch `Maanav`); no run on `main` recorded. Strong evidence nothing was pushed, **not proof**: GHCR must be checked. Repository Actions secrets (names only): `GHCR_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `TAVILY_API_KEY` |
| R14 | `483-AI-final` | Production deployment files | `docker-compose.prod.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `nginx/Dockerfile` | Yes | Where (if anywhere) these were deployed is not visible from the repository |
| — | `iCretegy-SaaS` | Empty repository | — | — | — |

"SOW copies": no SOW document or file named after it in any repository; the only hits are the phrase "statement of work" in `templates/terms_of_use.html` (legal text) and a summary checkpoint JSON in `booking-demo-final`, not the contract.

### 8.4 Deployment

- **No GitHub Pages** in any of them. **No deployment configuration** in the public repositories, `booking-demo-final` or `Django-booking-demo-page`. `483-AI-final` has Dockerfiles, production compose and (until 2026-07-02) a GHCR image-push workflow (R13).
- `iPharmaAi-booking-demo-page` lists a **Vercel** site as its homepage (a live deployment exists or existed; configured in Vercel, not in the repository).
- **Which repository the Render service `booking-demo-final` deploys from cannot be told from the repositories.** `render.yaml` exists only in RegX `main`; the service name matches the private repository `booking-demo-final`, which carries the same keys. Only the Render account shows the source repository and branch. If it deploys from either, **that service runs with OpenAI key C in code**.
- Vercel and Render accounts: added to the admin verification list (plan v2 §A.3).

### 8.5 What this changes

- The 3 OpenAI keys and the SMTP password are in **three** private repositories (`RegX` `main`, `booking-demo-final`, `Django-booking-demo-page`), not one; revocation remains the only fix (history rewriting would not make them safe).
- **New credentials:** the Gemini API key in a **public** repository (P1), and a different Google API key plus Django keys and test/UAT credentials in the private `483-AI-final` (R7–R9). Add them to the owner checklist.
- **`483-AI-final` is a separate, active 483 AI codebase** (last push 2026-11-06; evaluation, "think" acceptance sets, client QA, iCretegy feedback). It is not part of `RegX`; the execution plan's Part 1 status, which looked only at `company_site/`, must be re-assessed against it.
- **GHCR check is now specific:** look for packages `ipharmai-api` and `ipharmai-nginx` under the org (R13).
- Client spreadsheets (including the "For Cipla" workbooks) are in **two private repositories' git history and tips**, beyond the local image. Anyone with access to those repositories (4 collaborators where visible) has them. They are **not** in the public repositories scanned.
