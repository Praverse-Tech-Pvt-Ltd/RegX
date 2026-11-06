# Credential inventory

**Date:** 2026-11-06. **Author:** Claude Code session for Maanav. **Status:** report only. No credential was revoked, rotated, removed or used.

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
