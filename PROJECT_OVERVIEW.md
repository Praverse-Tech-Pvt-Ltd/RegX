# PROJECT_OVERVIEW — REGX

Single source of truth for anyone taking over this project. **Future sessions: update this file in place and append to the Work Log at the bottom. Do not create new overview files.**

- Code analysed: `origin/regx-main` at `732133f` (2026-09-21, "final engineering closure audit", PR #77).
- Local checkout: `D:\Praverse\Regex` was switched to `regx-main`, fast-forwarded to `origin/regx-main@732133f` (2026-10-08). The older local branch `regx/feat/legacy-port-and-sso` is kept; it is fully merged.
- Legend: **[Verified]** means checked in this session by running something or reading the code. **Assumption** means inferred and not confirmed.

---

## 0. Context the new owner has not supplied yet

The discovery prompt's "Context I have" section came back empty. Until someone fills it in, these points are inferred from the repo and are not facts:

| Item | What the repo suggests | Status |
|---|---|---|
| Project purpose | SOW (2026-04-22) between Praverse (Pratham Shrivastav) and iCretegy Solutions (Alpesh Patel, CEO): an "AI solution for Inspection & Regulatory Database", fee INR 17,00,000 | From the SOW PDF in the repo root |
| **REGX scope** | **SOW Part 2 (Technical/Regulatory Tools, §2.1–2.11)**, plus §4 (security/compliance) and §5 (performance) where they apply to Part 2. Part 1 (483 Database AI) and Part 3 (client API program) are **not expected inside REGX** | **Stated by owner, 2026-10-08** |
| Who left | Assumption: **`Devpt1904`**, who wrote almost all of REGX between July and 2026-09-21. `praversetech2-sudo` merged the PRs. | Confirm |
| Hosting/deploy | **No REGX deployment exists** (see §8). The legacy app may run at ipharmaai.com (Assumption). | Confirm |
| Access | Real `.env` present locally with all 4 required secrets set. `gh` is authenticated as `Rabbitshah`. No cloud, OpenAI, Azure or SMTP credentials were found. | Confirm what else exists |
| Next goal | Unknown | **Owner must state** |

---

## 1. Project summary

- **What it is:** REGX is a multi-tenant regulatory-affairs workflow platform for pharma regulatory teams.
- **Who uses it:** staff at iCretegy's client companies, working in Doer, Reviewer and VP roles. iCretegy would also resell it through an API.
- **What it covers today:**
  - governed IIG checklists, with a calculation engine and gap analysis
  - FDA reference data (IID, Orange Book)
  - formulations and IID assessment
  - regulatory cases, submission dossiers, dossier blueprints and upgrades
  - submission packages, with a frozen manifest and ZIP export
  - a document platform with versioning and malware scanning
  - a workflow engine and an immutable audit trail
  - outbound connectors
  - an operations dashboard
- **Legacy app inside the repo:** the iPharmaAI Django monolith is carried in as `company_site/` and served beside REGX through nginx. One login works for both: company_site sends the password check to REGX's API. They do not share sessions.
- **Repository quirk:** the GitHub repo `Praverse-Tech-Pvt-Ltd/RegX` (private) holds **two unrelated histories**:
  - `main`, the default branch, is the legacy monolith.
  - `regx-main` is REGX.

  A plain `git clone` therefore lands on the wrong code.

**Bottom line (scope: SOW Part 2 + applicable §4/§5):**
- The last developer declared "ENGINEERING COMPLETE — EXTERNAL DECISIONS OUTSTANDING" (`docs/FINAL_ENGINEERING_CLOSURE_AUDIT.md`). That is accurate for the governed, non-AI platform:
  - checklists and IID automation
  - roles and review gates
  - FDA data
  - documents
  - audit
  - tenancy
- **What it leaves out: Part 2 is sold as "Technical Tools (Regulatory) – Ai Based" (SOW page 7), and REGX contains no AI or LLM code path at all** [Verified: no provider SDK in requirements, no calls in `backend/` or `frontend/src`]. These items are therefore not started:
  - §2.6 chatbot
  - §2.8 gap scoring, heatmap and playbook
  - §2.10 AI document features
- §2.3 calculators, §2.7 Word add-in and §2.9 stability/impurity are blocked on client inputs. See §13 for the full gap matrix.
- **Nothing is deployed.** 40% of the fee is payable "after deployment of Regulatory Ai Software" (SOW line 442).
- **Part 2's timeline was never fixed.** The SOW says it is "mutually decided once development starts in second phase" (§2.11), and that Part 2 scope "may be finalized later (in phase 2)" (page 7). So REGX is not overdue against a contract date. Whether a phase-2 scope or date was agreed is an open question.
- Parts 1 and 3 are outside REGX by owner statement. Where the 483 AI lives, if anywhere, is an open question (§12).

---

## 2. Tech stack [Verified from manifests]

| Layer | Tech |
|---|---|
| Backend | Python 3.12 (`python:3.12-slim`), Django 5.2.18, DRF 3.18.3, drf-spectacular 0.28 (OpenAPI), django-csp, django-cors-headers, psycopg 3.2.6, Celery 5.4 + kombu 5.6.2 + redis-py 5.2.1, cryptography 50.0.2 (Fernet for MFA secrets), pyotp (TOTP), gunicorn 23. Document parsing: pypdf 6.20.0 (6.21.4 in PR #100, §11 #10c), python-docx, openpyxl, python-pptx, filetype. (Django/DRF/pypdf/cryptography from PR #79, merged; kombu pin from #95, merged.) **Dependencies locked with pip-tools** (PR [#98](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/98), merged): `backend/requirements/*.in` inputs → `base.txt` / `test.txt` / `dev.txt` lock files with exact versions and sha256 hashes for all 50 runtime and 68 dev packages; Docker and CI install with `--require-hashes --no-deps`; regenerate with `scripts/lock_backend_deps.sh` |
| Backend dev | pytest 8.3.5, pytest-django, pytest-cov (gate 55%), factory-boy, freezegun, ruff 0.11.13, import-linter 2.3 (16 layer contracts), detect-secrets |
| Frontend | Next.js **15.5.27** on PR [#78](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/78) (regx-main is still on 15.1.0 until it merges) (App Router, standalone output), React 19.2, TypeScript 5.9. No UI library. Vitest 3 + Testing Library + jest-axe. Playwright 1.61 + axe-core |
| Data | PostgreSQL 16 (REGX). Redis 7 (Celery broker, cache, sessions). SQLite (company_site only) |
| Legacy (`company_site/`) | Django 5.1.3, DRF + simplejwt, django-ckeditor, crispy-forms, pandas, openai, celery. **15 packages unpinned** |
| Infra | Docker Compose, 7 services (+ optional `clamav` under `--profile scanning`). nginx 1.27 gives a single origin on :8080 and an admin listener on :8090 |
| CI | GitHub Actions: `backend.yml`, `frontend.yml`, `docker-integration.yml`, `operational-scripts.yml`. **Test only, no deploy** |
| Package managers | pip (requirements files, no lockfile), npm (`package-lock.json`) |

**Repo type:** a monorepo with a backend, a frontend, the legacy app and infra.

**Entry points:**
- `backend/manage.py`, `backend/regx/wsgi.py` (gunicorn), `backend/regx/celery.py`
- `frontend/src/app/layout.tsx` (`node server.js` in the image)
- `company_site/docker-entrypoint.sh` → gunicorn `RAAI.wsgi`
- `infra/nginx/nginx.conf`

---

## 3. Folder map (3 levels; vendored, build and migration folders omitted)

```
.github/workflows/        CI (4 workflows)
backend/                  Django project "regx" + 25 apps
  regx/settings/          base / development / production / test
  requirements/           base.txt, test.txt, dev.txt
  common/ identity/ tenancy/ authorization/ audit/          platform core
  documents/ templates_registry/ workflows/                 platform services
  fda_data/ formulations/ iid_assessment/ iig_checklist/    FDA + checklist domain
  regulatory_cases/ submission_dossiers/ dossier_blueprints/ dossier_upgrades/
  submission_packages/ submission_operations/ external_integrations/
  deficiencies/ inspections/ controlled_correspondence/ product_comparison/   ported from legacy (API only)
  demo_seed/              seed_regx_demo management command
  */tests/                pytest suites
frontend/
  src/app/(regx)/         46 pages (route group: dashboard, documents, fda-data, iig-checklists, ...)
  src/app/signin, mfa     auth pages
  src/components/         regx-shell (sidebar/layout), auth, ProvenanceLabel
  src/lib/api.ts          single 3.6k-line API client
  tests/unit/             vitest (23 files)
  e2e/                    Playwright (22 specs, API mocked via page.route)
company_site/             legacy iPharmaAI Django app (RAAI, RATools, AIDatabase, AdminMaster), db.sqlite3, templates, static, media
infra/nginx, infra/postgres   nginx.conf; init.sql (pgcrypto only)
scripts/                  check_env.py, backup.sh, restore.sh, release_verify.sh, company-asset tools
docs/                     ~120 design/evidence docs (ARCHITECTURE, DEVELOPMENT, per-module, milestone evidence, decision intakes)
root                      README, handoff.md, test-checklist.md, constraints.md, decisions.md, ROUTES.md, seed_sample_data.py, compose.yaml
```

---

## 4. Architecture and data flow

```
Browser ──► nginx :8080 ──┬─ /api/*            ─► backend (Django/DRF, gunicorn) ─► PostgreSQL 16
                          │                                    │  └► Redis (cache, sessions, Celery broker) ─► celery worker
                          ├─ 19 REGX page prefixes, /_next ─► frontend (Next.js)        └► document_storage volume
                          ├─ /static, /media   ─► files on disk
                          └─ everything else   ─► company_site (legacy Django, SQLite) ──(login)──► backend /api/regx/v1/auth/login/
        nginx :8090 ──► company_site admin console only (/adminmaster, /admin, /aidatabase, /ratools)
```

**Frontend → backend:**
- `fetch` with `credentials: "include"` and the Django session cookie (HttpOnly, SameSite=Lax, 8h).
- Before each write the client fetches `/auth/csrf/` and sends the token as `X-CSRFToken`.
- Each domain call carries an `X-Tenant-Slug` header. Pages read the slug from the `?tenant=` query string.
- Nothing is stored in localStorage; CI checks this.

**Tenancy:**
- `TenantMiddleware` resolves the tenant from `X-Tenant-Slug` into a thread-local (`backend/tenancy/context.py`).
- `current_tenant()` raises `TenantScopeMissing` if no tenant was set, so access fails closed.
- FDA, inspection and deficiency reference data is platform-level, with no tenant FK.

**Layering:**
- import-linter enforces the layers (`backend/pyproject.toml`).
- They stack outward: core → documents/workflows → `regulatory_cases` → `submission_dossiers` → `dossier_blueprints` → `dossier_upgrades`.
- `submission_operations` (a read-only dashboard) and `external_integrations` (the only outbound network edge) are leaves that nothing may import.
- Writes go through each app's `services.py`. Uploads go through a single `documents.ingest` pipeline.

**Integrity is enforced in the database:**
- About 20 RunSQL migrations install Postgres triggers that make the audit trail, workflow transitions, case and section links, frozen packages, blueprint provenance, upgrade history and connector executions append-only or immutable.

**Async work:**
- Celery tasks: document scanning and text extraction, connector executions.
- They are dispatched with `transaction.on_commit(...delay())`.

**Shared login:**
- `company_site/AdminMaster/regx_auth.py` POSTs the credentials to REGX.
- It then mirrors the user into a local `CustomUser` with an unusable password.
- It refuses `mfa_required` accounts.
- REGX roles map onto legacy roles: tenant_admin and platform_support become admin; doer becomes company_user; reviewer and vp become company_checker.

---

## 5. API list

- **Size:** 221 URL patterns under `/api/regx/v1/`, which is 273 method+path pairs, plus `/api/schema/` and `/api/docs/`.
- **View style:** function views (`@api_view`) and APIViews; there are no ViewSets.
- **Default permissions:** `SessionAuthentication` + `IsAuthenticated`. Per-method permission classes are listed below.
- **Public routes** (`AllowAny`): health/readiness/version, `auth/csrf`, `auth/register`, `auth/login`, and **also `/api/schema/` and `/api/docs/` [Verified: anonymous 200]**.
- **Notation:** `P = /api/regx/v1`, `{id}` = UUID `public_id`. Internal integer PKs are never exposed.

**Core**
| Method | Path | Purpose |
|---|---|---|
| GET | P/health/, P/readiness/, P/version/ | liveness; DB+cache readiness (**does not check that migrations ran**); version |
| GET | P/auth/csrf/ | issue CSRF cookie |
| POST | P/auth/register/ | **anonymous self-registration** |
| POST | P/auth/login/, P/auth/logout/ | session login/logout (**no throttle**) |
| GET | P/auth/me/ | current user |
| POST | P/mfa/enrol/ (alias P/mfa/setup/), P/mfa/verify/, P/mfa/recovery/ | TOTP enrol/verify (5 failures → 15 min lock), recovery codes |
| GET, POST | P/tenants/ | list my tenants / **create a tenant (any logged-in user)** |
| POST | P/tenants/active/ | set active tenant |
| GET | P/tenants/{id}/, P/tenants/{id}/members/ | tenant detail, members |
| GET | P/permissions/roles/, P/permissions/permissions/, P/permissions/effective/, P/permissions/mine/ | RBAC lookup |

**Documents:**
- `GET/POST P/documents/`: list, or multipart upload.
- `GET …/{id}/`, `GET/POST …/{id}/versions/`, `GET …/versions/{vid}/`, `…/status/`, `…/locators/`.
- `POST …/{id}/archive/`, `POST …/{id}/restore/`.

**Templates registry:**
- `GET P/templates/`, `GET …/{id}/`, `GET …/{id}/versions/`, and on a version `GET …/versions/{vid}/`, `…/sections/`, `…/items/`.
- Lifecycle, all POST on `…/versions/{vid}/`: `submit-review`, `approve`, `return`, `reject`, `activate`, `supersede`, `retire`.
- `GET/POST P/template-sources/`, `GET/POST P/migration-batches/`, `GET …/{id}/`, `…/results/`, `POST …/review/`, `GET …/reconciliation.csv`, `GET …/reconciliation.json`.

**FDA data:**
- `GET/POST P/fda-data/releases/`, `GET …/{id}/`.
- Release lifecycle, all POST on `…/{id}/`: `validate`, `submit-review`, `approve`, `activate`.
- `GET …/reconciliation.json` and `GET …/reconciliation.csv`.
- `GET P/fda-data/orange-book/products/` and `…/{id}/`; `GET P/fda-data/iid/records/` and `…/{id}/`.
- `GET P/fda-data/controlled-routes/`, `…/controlled-dosage-forms/`, `…/controlled-units/`.
- `GET P/fda-data/mappings/`, `POST …/mappings/substances/proposals/`, `GET …/mappings/{id}/`.
- Mapping lifecycle, all POST on `…/mappings/{id}/`: `submit-review`, `approve`, `reject`, `return`; plus `GET …/affected-records/`.

**Formulations / IID:**
- `GET/POST P/formulations/products/`, `GET …/{id}/`, `POST …/{id}/select-reference/`, `GET/POST …/{id}/versions/`.
- `GET P/formulations/versions/{id}/`, `GET/POST …/components/`, `GET/POST …/dosing-regimens/`.
- `POST P/iid-assessments/preview/`, `POST P/iid-assessments/snapshot/`, `GET P/iid-assessments/{id}/`.

**IIG checklists** (35 routes):
- **Definitions:** `GET/POST P/iig-checklists/definitions/`, `GET/DELETE …/{id}/`, `POST …/{id}/clone/`, `GET/POST …/{id}/versions/`.
- **Versions:** `GET/PATCH P/iig-checklists/versions/{id}/`.
- **Version lifecycle**, all POST: `submit-review`, `approve`, `return`, `reject`, `activate`, `supersede`, `retire`.
- **Sections, questions and rules:** `GET/POST …/versions/{id}/sections/`, `PATCH/DELETE P/iig-checklists/sections/{id}/`, `POST …/sections/{id}/questions/`, `PATCH/DELETE P/iig-checklists/questions/{id}/`, `GET/POST …/versions/{id}/applicability-rules/`, `POST P/iig-checklists/applicability-rules/validate/`.
- **Executions:** `GET/POST P/iig-checklists/executions/`, `GET …/{id}/`, `GET …/{id}/gap-analysis/`, `GET/POST …/{id}/gap-analyses/`, `GET …/gap-analyses/{aid}/`.
- **Execution lifecycle**, all POST: `submit-review`, `approve`, `return`, `reject`, `cancel`, `supersede`.
- **Responses and export:** `GET …/{id}/responses/`, `PATCH …/responses/{rid}/`, `GET …/{id}/export/`, `POST …/responses/{rid}/reviewer-conclusion/`, `POST …/responses/{rid}/override/`.
- **Capabilities:** `GET P/iig-checklists/capabilities/`.
- About 10 execution views check permissions inside the handler rather than through permission classes.

**Workflows:**
- `GET/POST P/workflows/`, `GET/PATCH …/{id}/`, `GET …/{id}/history/`.
- Transitions, all POST on `…/{id}/`: `submit`, `begin-review`, `approve`, `reject`, `cancel`, `return-to-draft`, `assign`.
- `GET/POST …/{id}/evidence/`, `DELETE …/evidence/{eid}/`.

**Regulatory cases:**
- `GET/POST P/regulatory-cases/`, `GET/PATCH …/{id}/`, `POST …/{id}/complete/`, `POST …/{id}/cancel/`.
- Links: `GET/POST/DELETE …/{id}/workflows|documents|checklists/[{lid}/]`.

**Submission dossiers:**
- `GET/POST P/regulatory-cases/{case}/dossiers/`, `GET/PATCH P/submission-dossiers/{id}/`, `POST …/complete/`, `POST …/cancel/`, `GET/POST …/sections/`.
- `GET/PATCH P/dossier-sections/{id}/`, `POST …/reorder/`, `POST …/retire/`, `GET/POST …/blockers/`.
- `POST P/section-blockers/{id}/resolve/`.
- Links: `GET/POST/DELETE P/dossier-sections/{id}/documents|workflows|checklists/[{lid}/]`.

**Dossier blueprints:**
- `GET/POST P/dossier-blueprints/`, `GET/PATCH …/{id}/`, `POST …/archive/`, `GET/POST …/versions/`.
- `GET P/dossier-blueprint-versions/{id}/`, `POST …/activate/`, `POST …/retire/`, `GET/POST …/sections/`, `POST …/instantiate/`.
- `PATCH P/dossier-blueprint-sections/{id}/`, `POST …/reorder/`, `POST …/retire/`.
- `GET P/submission-dossiers/{id}/blueprint-provenance/`.

**Dossier upgrades:**
- `GET/POST P/submission-dossiers/{id}/upgrade-plans/`, `GET …/upgrade-history/`.
- `GET P/dossier-upgrade-plans/{id}/`, `POST …/regenerate/`, `POST …/ready/`, `POST …/apply/`, `POST …/cancel/`.
- `POST …/items/{iid}/accept/`, `POST …/items/{iid}/reject/`.

**Submission operations** (read-only), all GET under `P/submission-operations/`: `overview/`, `attention/`, `cases/`, `dossiers/`, `owners/`, `recent-activity/`.

**Submission packages:**
- `GET/POST P/regulatory-cases/{id}/packages/`, `GET/PATCH P/submission-packages/{id}/`.
- Entries, all POST: `…/entries/`, `…/entries/{eid}/remove/`, `…/entries/{eid}/reorder/`.
- Lifecycle, all POST: `submit-for-review`, `return-to-draft`, `freeze`, `cancel`, `clone`.
- `GET …/validate/`, `GET …/manifest/`, `GET …/export/` (ZIP, all-or-nothing).

**External integrations:**
- `GET/POST P/external-integrations/`, `GET/PATCH …/{id}/`.
- POST on `…/{id}/`: `enable`, `disable`, `archive`, `test`.
- `GET/POST …/{id}/executions/` (60/min throttle on POST), `GET P/external-integration-executions/{id}/`, `POST …/cancel/`.

**Ported from legacy (API only; no REGX UI):**
- `GET P/deficiencies/`, `…/facets/`, `…/{id}/`.
- `GET P/inspections/form483/`, `…/form483/facets/`, `…/form483/{id}/`, `P/inspections/observations/`, `P/inspections/warning-letters/`, `…/{id}/`.
- `GET P/controlled-correspondence/best-practices/`, `…/categories/`; `GET/POST …/drafts/`; `GET/PATCH/DELETE …/drafts/{id}/`.
- `GET/POST P/product-comparisons/`, `GET/PATCH/DELETE …/{id}/`, `GET …/{id}/matrix/`, `PUT …/{id}/attributes/`.

**Frontend pages:**
- 46 `page.tsx` files under 19 prefixes. nginx serves exactly these prefixes from :8080 (`infra/nginx/nginx.conf:104-122`).
- `/submission-dossiers` and `/submission-packages` have detail pages only, with no list page.

**company_site (legacy):**
- Prefixes: `/`, `/ratools/` (172 routes), `/aidatabase/` (89), `/adminmaster/` (84), `/admin/` (Django admin).
- Full list: `ROUTES.md`. `APPEND_SLASH=False`, but the trailing slash was made optional on PR #49.
- **The public `GET /` (`RATools/views.py:216`) and the AIDatabase dashboards can call OpenAI `gpt-4.1-mini`** when the Excel cache is cold and `OPENAI_API_KEY` is set (`AIDatabase/observation_summary.py:350`).

Detailed per-route file:line references come from this session's route inventory. Regenerate with `python manage.py spectacular`; the schema has 273 operations.

---

## 6. Database

**REGX (PostgreSQL 16):**
- 23 apps with models, 50 migrations.
- **There are no data migrations.** Roles and permissions are seeded by a `post_migrate` signal (`backend/authorization/seed.py:34`). It creates 5 system roles: doer, reviewer, vp, tenant_admin and platform_support.
- **Tenant-scoped:** documents, workflows, iig_checklist executions, formulations, iid_assessment, cases, dossiers, blueprints, upgrades, packages, connectors, CC drafts, product comparisons.
- **Platform-level:** identity, fda_data, inspections, deficiencies, CC best practices.
- **Nullable tenant (NULL means platform row):** Role, ChecklistDefinition, RegulatoryTemplate.
- There are no generic FKs; typed link tables are used instead.

**Migrations do not run on container start.** You must run `migrate` by hand. Readiness reports "ready" against an empty schema **[Verified]**.

**Seed and import commands:**

| Command | Effect |
|---|---|
| `seed_regx_demo [--password-env VAR] [--dry-run]` | Creates the demo tenant, 4 users `*@demo.regx.invalid`, checklist, formulation, case RC-000001, workflow, dossier, package and connector. **[Verified]** |
| `import_fda_release --dataset-type … --source-reference …` | Orange Book `Products.txt` / IID CSV from local files only (append) |
| `import_inspections --sqlite` | **Deletes all** 483s and warning letters, then re-imports |
| `import_deficiencies --sqlite/--xlsx` | **Deletes** per corpus, then re-imports |
| `import_best_practices` | **Deletes all** best practices, then re-imports |
| `seed_sample_data.py` (repo root, via `manage.py shell <`) | Needs tenant `praverse` and user `admin@praverse.local` to exist already |

- **Fresh database:** FDA, Orange Book and IID tables are empty, and the deficiency and 483 corpora are empty until imported **[Verified: `/deficiencies/` returns 0 rows]**.
- **Warning letters:** 0 rows even after import. The source snapshot lacked the table.

**company_site (SQLite):**
- `company_site/db.sqlite3` (7.3 MB) is tracked in git and sanitized: 9 disabled users, no hashes.
- **No migrations folder exists in any legacy app.**
- The schema lacked 134 columns. They are repaired by hand with `add_missing_columns.py`; take a backup first.
- `docker-entrypoint.sh` seeds the `company_db` volume on first start only.

**File storage:**
- `backend/documents/storage.py` stores files locally in the `document_storage` volume, with a SHA-256 check.
- `S3CompatibleStorage` is a stub: every method raises `NotImplementedError`.

---

## 7. External services and integrations

| Service | Where | Status |
|---|---|---|
| Sessions + Redis | `backend/regx/settings/base.py:125-181` | live |
| MFA (TOTP, pyotp, Fernet-encrypted secrets) | `backend/identity/views.py:81-160` | live but **never enforced**; the SOW asks for it on Reviewer and VP |
| SSO (SAML/OIDC/Azure AD) | — | **absent**. The "SSO" branch name means only the shared password check |
| company_site → REGX login | `company_site/AdminMaster/regx_auth.py` | live in compose (`REGX_AUTH_URL`) |
| Malware scanning | `backend/documents/scanner.py`: stub or ClamAV (clamd TCP) | **stub in compose** (`DOCUMENT_SCANNER_ALLOW_STUB` defaults to `true`). ClamAV exists only under `--profile scanning` |
| OpenAI `gpt-4.1-mini` | `company_site/AIDatabase/observation_summary.py` only | effectively off: no key is passed to the container. The documented `ENABLE_OBSERVATION_SUMMARIES` flag exists only on the legacy `main` line (commit `4193f09`, 2026-09-08). It was **never carried into `company_site/` on regx-main** [Verified], so the only gate there is whether `OPENAI_API_KEY` is set |
| Email (SMTP Office365 + Microsoft Graph) | `company_site/RAAI/settings.py:150-168`, `RATools/graph_email.py` | configured; no credentials in compose, so effectively off. The REGX backend sends no email |
| company_site Celery (demo reminders, Excel refresh) | `company_site/RAAI/celery.py` | **no worker or beat runs in compose**, so queued tasks never execute |
| FDA data | `fda_data/management/commands/import_fda_release.py` | manual file import only; no fetching from fda.gov |
| Outbound connectors | `backend/external_integrations/` (SSRF-checked, pinned-IP HTTPS, env-var secrets) | framework only; no real destinations |
| Word add-in, AI chatbot, AI gap scoring, stability/impurity AI | — | **not built** |
| Payments, analytics | — | none |
| CDNs | frontend: Google Fonts. company_site: jsdelivr, cdnjs, jQuery, Tailwind and others | live, browser-side |

---

## 8. Configuration and secrets

**Real `.env`** at `D:\Praverse\Regex\.env`:
- Gitignored, and no `.env` is tracked.
- All keys have non-placeholder values.
- **The four required secrets are present:** `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `MFA_ENCRYPTION_KEY` (a valid Fernet key; the stack boots) and `COMPANY_SECRET_KEY`.

| Variable | Read at | Default / supplier | `.env.example` | Real `.env` |
|---|---|---|---|---|
| DJANGO_SECRET_KEY | backend `settings/base.py:16` | **required** | placeholder | present |
| MFA_ENCRYPTION_KEY | `base.py:284` | **required** (Fernet) | placeholder | present |
| POSTGRES_PASSWORD | compose → `DB_PASSWORD` | **required** | placeholder | present |
| COMPANY_SECRET_KEY | compose → company `SECRET_KEY` | **required by compose**, but the code has a hardcoded insecure default | placeholder | present |
| DB_NAME/USER/HOST/PORT/PASSWORD | `base.py:112-116` | compose hardcodes them | no | missing (fine under compose) |
| DEBUG, ALLOWED_HOSTS | `base.py:18-20` | False / localhost; compose sets | no | missing |
| REDIS_URL, REDIS_*_TIMEOUT_SECONDS | `base.py:125,149` | compose hardcodes URL; timeouts **not passed by compose** | yes | present |
| CSRF_TRUSTED_ORIGINS | `base.py:176` | localhost:3000 (sign-in via :8080 still works [Verified]) | no | missing |
| CORS_ALLOWED_ORIGINS | `base.py:181` | compose sets | yes | present |
| DOCUMENT_STORAGE_BACKEND / _LOCAL_STORAGE_ROOT / _MAX_UPLOAD_BYTES | `base.py:235-240` | local / BASE_DIR / 50 MB | no | missing |
| DOCUMENT_SCANNER_BACKEND, DOCUMENT_CLAMAV_HOST/PORT | `base.py:242-244` | compose `stub` / `clamav` / 3310 | no | missing |
| DOCUMENT_SCANNER_ALLOW_STUB | `production.py:63` | **compose defaults `true`**; not in `check_env.py` or the docs | no | missing |
| CELERY_TASK_ALWAYS_EAGER | `base.py:270` | False (True in test settings) | no | missing |
| APP_VERSION, APP_ENVIRONMENT, LOG_LEVEL | `base.py:252,315,330` | **not passed by compose**, so the stack reports `development` | yes (first two) | present |
| REGX_SERVICE_NAME | `common/structured_logging.py:218` | compose sets | no | missing |
| REGX_CONNECTOR_<ID>_<SUFFIX> | `external_integrations/secrets.py:36` | per connector | no | missing |
| NEXT_PUBLIC_API_URL / INTEGRATED_APP_URL | `frontend/src/lib/api.ts:14`; compose build arg | localhost:8000 / localhost:8080 | yes | present |
| BASE_URL (← COMPANY_BASE_URL) | `company_site/AIDatabase/context_processors.py:4` | **no code default**; compose `:-http://localhost:8080` | no | missing (compose default used) |
| SERVER (← COMPANY_SERVER_MODE) | `AdminMaster/views.py:103` | compose `LOCAL` | no | missing |
| REGX_AUTH_URL | `company_site/RAAI/settings_integration.py:114` | compose `http://backend:8000` | no | missing |
| COMPANY_DB_PATH, COMPANY_REDIS_URL | `settings_integration.py:71,83` | compose sets | no | missing |
| EMAIL_HOST/PORT/USE_TLS/USE_SSL/HOST_USER/HOST_PASSWORD | `company_site/RAAI/settings.py:151-156` | office365 / empty credentials | company `.env.example` only | missing |
| AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET, BOOKING_EMAIL_HOST_USER | `settings.py:164-168` | empty | company `.env.example` (blank) | missing |
| OPENAI_API_KEY | `AIDatabase/observation_summary.py:266` | None, so summaries are skipped | no | missing |
| MIGRATE_FLAG, MIGRATE_FLAG_WARNING_LETTER | `AIDatabase/views.py:4375,4970` | False | no | missing |
| REMINDER_TO_EMAILS / REMINDER_CC_EMAILS | `send_subscription_reminders.py:32` | **real @icretegy.com addresses hardcoded** | no | missing |
| COMPANY_DEMO_EMAIL / _PASSWORD | `create_demo_user.py:53` | command-only | no | missing |
| COMPOSE_PROJECT_NAME, REGX_HEALTH_WAIT_SECONDS, REGX_ALLOW_PROD_RESTORE | `scripts/*.sh` | regx / 60 / 0 | no | missing |

**Note:** `scripts/check_env.py` reads `os.environ`, not `.env`. Run `docker compose config` to validate the `.env` file.

**Hardcoded secrets (values not printed):**
1. **CRITICAL: `origin/main` on GitHub** (private repo), plus 3 branches merged into it. Introduced in commit `dff6856`.
   - Live OpenAI project key in `AIDatabase/filters.py:37`, plus 3 commented keys in total across `filters.py:34-36` and `views.py:5328-5329,5464-5465`.
   - Literal SMTP passwords in `RAAI/settings.py:171,178`.
   - `django-insecure` SECRET_KEY at `RAAI/settings.py:48`.
   - Tracked `db_17_1_2.sqlite3` contains 9 password hashes.
   - [Verified: the key pattern is present at the tip.] `constraints.md:46` says the owner chose to leave the key. `docs/DEPLOYMENT_BOUNDARIES.md` §6 says revocation is **"NOT CONFIRMED"** and wrongly claims the keys were purged.
2. **HIGH:** `company_site/RAAI/settings.py:29` on regx-main uses **the same leaked `django-insecure` key as its default**. Only compose's `:?` guard stops it being used.
3. **MEDIUM:**
   - `company_site/create_demo_users.py:25-26` has hardcoded demo passwords.
   - `handoff.md:338-350` lists 6 local demo passwords in plain text.
4. **LOW:**
   - Real third-party emails hardcoded as defaults in `send_subscription_reminders.py`.
   - CI throwaway values; acceptable.

regx-main itself has **no** `sk-` keys, AWS keys, private keys or Azure secrets in tracked files.

---

## 9. How to run, test, build and deploy

**Run (full stack):**
```bash
git checkout regx-main            # NOT main (legacy) and NOT the stale legacy-port branch
cp .env.example .env              # fill the 4 secrets (generators in docs/DEVELOPMENT.md)
docker compose config --quiet     # validates .env (check_env.py does not read .env)
docker compose up --build -d      # ~3 min cold build [Verified]
docker compose exec backend python manage.py migrate        # mandatory, not automatic
docker compose exec backend python manage.py seed_regx_demo --password-env DEMO_PW   # optional demo data
```

- **URLs:**
  - Integrated origin: http://localhost:8080 (REGX at `/signin`, legacy everywhere else)
  - Frontend direct: :3000
  - API: :8000 (`/api/docs/`)
  - Legacy direct: :8001
  - Legacy admin: :8090
- **Every tenant-scoped API call needs `X-Tenant-Slug`.** Without it you get 403.
- **Traps:**
  - Source code is baked into the images, so rebuild after any code edit.
  - Restart nginx after recreating any container; otherwise you get 404 through nginx.
  - On Git Bash, run `MSYS_NO_PATHCONV=1` before `docker compose exec`.
  - **Do not browse company_site pages casually.** With an OpenAI key set, they make paid API calls.

**Test:**
- **Backend:**
  - Install test tooling as root first: `docker compose exec -u root backend pip install -r requirements/dev.txt`.
  - Then run: `docker compose exec -e DJANGO_SETTINGS_MODULE=regx.settings.test backend python -m pytest -q --no-cov -p no:cacheprovider`.
  - The settings flag is mandatory.
  - Run only one pytest at a time, because all runs share the `test_regx` database.
- **Lint:** `ruff check . && ruff format --check . && lint-imports`, run from `backend/` against the working tree.
- **Frontend**, from `frontend/`:
  - `npm ci`
  - `npm run type-check`
  - `npm run lint`
  - `npm run test` (vitest)
  - `npm run build`
  - `npm run test:e2e` (Playwright, API mocked, own dev server on :3100)
  - `npm run test:e2e:integrated` (against the nginx stack)

**Results this session** (regx-main 732133f, Windows 11, Docker 29.5, Python 3.13 host, Node 24 host):

| Check | Result |
|---|---|
| `docker compose config` with real `.env` | PASS |
| `docker compose up --build` | PASS: all 7 services healthy in ~3 min |
| `migrate` on fresh volume | PASS: 65 migrations applied |
| `manage.py check --deploy` | 172 warnings: 170 drf-spectacular schema-guess warnings, plus `SECURE_HSTS_SECONDS` unset and `SECURE_SSL_REDIRECT` off (TLS is expected to end in front of nginx; no TLS config exists) |
| `seed_regx_demo` | PASS |
| Sign-in (direct :8000 and via nginx :8080), tenant isolation (403 without header or cross-tenant, 200 with header) | PASS |
| ruff check / ruff format --check / lint-imports | PASS: All checks passed; 550 files formatted; 16/16 contracts kept |
| Frontend `npm ci` (lockfile unchanged, hash verified) | PASS, with a warning: `next@15.1.0` deprecated for a security vulnerability |
| Frontend type-check / lint | PASS / PASS (0 warnings) |
| Frontend vitest | PASS: 23 files, 555 tests |
| Frontend `next build` | PASS |
| Frontend Playwright E2E (mocked) | PASS: 257/257 in 2.0 min (Chromium headless) |
| Backend pytest full suite (in container, test settings) | PASS: **4033 passed, 1 skipped** in 18m11s. Matches the closure audit's declared figure. 5 harmless collection warnings |

**Deploy:**
- **There is no deployment.** None of the 4 workflows deploy anything, and there is no cloud, Kubernetes or Terraform config on regx-main.
- `docs/RELEASE_ROLLBACK_RUNBOOK.md` §1: "Deployment automation: none".
- `handoff.md`: "Nothing here has run outside local Docker".
- **The documented manual process is a single-host compose deployment:**
  1. Set the secrets and run `scripts/check_env.py`.
  2. `docker compose up -d`, then `migrate`.
  3. Run `scripts/release_verify.sh`.
  4. Classify migrations for rollback (classes A and C).
  5. Restart nginx.
- **Rollback** has three levels: service, code+schema, and data restore.
- **Backups:**
  - `scripts/backup.sh` and `scripts/restore.sh` are manual, unencrypted, run on no schedule and keep no off-site copy.
  - They have been rehearsed on synthetic data only.
  - RPO and RTO are "PENDING" (the SOW requires RPO < 1h and RTO < 4h on AWS or Azure).
- **CI status:**
  - Last green runs: backend 2026-09-15, frontend and Docker 2026-09-17.
  - The final docs-only PRs (#69–#77) triggered no workflows.
  - No CI job runs a dependency audit.

---

## 10. Repo state and unfinished work

**Git:**
- **Local checkout (2026-10-12, seventh session):** `regx-main` at `eedbf9c`, the same as origin (PRs #78–#81 merged).
  - Untracked files: `CLAUDE.md`, `PROJECT_OVERVIEW.md`, `diagnose.py`, `gpt_input_data.xlsx`, `gpt_input_data_pending_only.xlsx`.
  - No stashes.
  - The previous branch `regx/feat/legacy-port-and-sso` is kept locally; it is fully merged.
- **PRs:** #49–#97 all merged. #82–#87 on 2026-10-13 05:58–05:59 UTC; #88–#91 on 2026-10-13 08:53–08:54 UTC; **#92–#97 on 2026-11-05** (owner). `regx-main` is now `5a4bc36`.
- **PRs #98 merged (2026-11-05).** Open: [#99](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/99) `regx/docs/track-claude-md-and-overview` (docs only). [#100](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/100) `regx/fix/pypdf-upgrade` (§11 #10c).
- **Branches (2026-11-05):** the merged branches of #88–#91 and of #92–#97 (including #95 `regx/fix/pin-kombu`) are deleted locally and on GitHub, tips verified in `regx-main` first (`branch-cleanup/BRANCH_INVENTORY.md`). **GitHub: 2 branches (`main`, `regx-main`). Local: those 2 plus `regx/chore/pip-tools-lock`.**
- **Branch inventory (2026-10-12, before cleanup):** 14 local and 88 remote branches, 91 distinct names.
  - KEEP 5 · SAFE TO DELETE 79 · REVIEW 7. Details are in `branch-cleanup/BRANCH_INVENTORY.md` and `branch-cleanup/restore.sh` (both outside git).
  - **Cleanup done 2026-10-12 (owner-approved):** 86 branches deleted (79 SAFE + 7 REVIEW). The 7 REVIEW branches are archived as verified tags `archive/<name>`. No force-push.
  - **Final (end of 2026-10-12):** **8 branches on GitHub, 8 local**, all of them either a base or the head of an open PR:
    - `main` and `regx-main`;
    - #82 `regx/fix/login-throttling`, #83 `regx/fix/schema-requires-login`, #84 `regx/fix/stub-scanner-guard`;
    - #85 `regx/chore/handoff-demo-passwords`, #86 `regx/feat/fda-release-metadata`, #87 `regx/docs/terminology-mapping-review`.
  - That is down from 91 distinct branch names.
  - **2026-10-13 (third session):** the 6 merged branches of PRs #82–#87 were deleted locally and on GitHub (tips verified in `regx-main` first; recorded in `branch-cleanup/BRANCH_INVENTORY.md`). **GitHub now has 5 branches:** `main`, `regx-main` and the heads of #88, #89, #90. **Local has 6:** the same 5 plus `regx/docs/iid-daily-exposure-rule`.
  - The 3 security branches were pushed after the inventory (PRs #82–#84). Two new local branches exist: `regx/docs/terminology-mapping-review` and `regx/feat/fda-release-metadata`.
  - Earlier note: 4 unmerged REGX branches, all docs-only or superseded.
  - About 60 merged feature branches are still on the remote; cleanup was deferred.
- **Last activity:** 2026-09-21 (`Devpt1904`). Commits from 09-15 to 09-21 are almost all decision-intake documents, not code.

**Declared complete** (`docs/P0_P14_HANDOFF.md`, closure audit):
- P0: real malware scanning path.
- P1: IIG demo readiness.
- P2: audit coverage.
- P3: navigation.
- P4: repeatable demo seed.
- P5: FDA file parsing.
- P6: connector verification.
- P7: gap analysis.
- P8: removed the legacy chatbot and an accidental OpenAI call.
- P14: nginx routing and doc consistency.
- P15: integrated-origin smoke test.

**Blocked on the client or owner (not engineering):**

| Blocker | Who decides | Doc |
|---|---|---|
| Regulatory content gate: **0 of 20 items approved**. No real checklist content may go live, so the IIG product is an engine without approved content | Named regulatory authority at iCretegy | `docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md` |
| Approval Register 13/14 (which calculation applies to which question) | Regulatory + engineering | `docs/APPROVAL_REGISTER_13_14_DECISION_INTAKE.md` |
| SOW 2.3 calculators | Client/regulatory owner | `docs/CALCULATOR_SPECIFICATION_INTAKE.md` |
| SOW 2.7 Word add-in (13 contract items) | Product, security and regulatory owners | `docs/WORD_ADDIN_CONTRACT_INTAKE.md` |
| SOW 2.9 stability/impurity AI (feasibility) | Client/SOW owner | `docs/STABILITY_IMPURITY_ASSISTANT_INTAKE.md` |
| Legacy RATools approvals disposition | Business/data owner | `docs/LEGACY_RATOOLS_DISPOSITION_INTAKE.md` |
| 13 operational policies (RPO, RTO, retention, release approver, SLA…) | Business / IT / QA | `docs/REGX_OWNER_POLICY_DECISION_PACKAGE.md` |
| Revoke 3 OpenAI keys and the SMTP password; purge the PR #22 force-push objects via GitHub Support | Credential/repo owner | `docs/DEPLOYMENT_BOUNDARIES.md` §6, closure audit §C |
| MFA: enforce for Reviewer/VP or formally waive | Security owner | `handoff.md` §6.3 |
| Corrected AIDatabase export; a snapshot with warning letters; real FDA/Orange Book files | Client | `handoff.md` §6 |

`docs/EXTERNAL_BLOCKER_READINESS.md` §0 states that **no named individual is assigned to any blocker**.

**Half-finished work and not-started Part 2 scope** (full detail in §13):
- **SOW 2.6 chatbot, 2.8 AI gap scoring, heatmap and playbook, 2.10 AI document management:** not started, and no AI path exists in REGX. Only 2.6 is called out as "not started" in the status doc; none is tracked as a blocker.
- **SOW §4.3 SSO, MFA enforcement, §4.4 audit export and compliance dashboard:** not started.
- **SOW §5.1 latency targets:** never measured.
- **Out of REGX scope by owner statement:** Parts 1 and 3. REGX does hold 483 and warning-letter *data* as an API (`backend/inspections/`, 187 inspections and 851 observations once imported). That data could feed a 483 AI wherever it is built.
- **The 4 ported APIs have no REGX UI** (deficiencies, inspections, controlled correspondence, product comparison). The sidebar sends users to 32 legacy `/ratools/...` pages instead.
- **Other loose ends:**
  - The restored `.xlsx` workbooks are gitignored and exist on one machine only.
  - 4 AIDatabase lookups are broken.
  - The demo seed approves a formulation by writing to the database directly, because no approval service exists.
  - The `--xlsx` deficiency import is untested.
- **Local untracked files** (inspected 2026-10-08, read-only):
  - **`diagnose.py`:** a read-only troubleshooting script for the **legacy `main` monolith**, not REGX. It loads `RAAI.settings`, checks `RATools.RegulatoryRole`, counts SQLite tables, and points to the legacy `SETUP.md`.
  - **`gpt_input_data.xlsx`** (8,362 observation blocks) and **`gpt_input_data_pending_only.xlsx`** (the 1,265 blocks still pending): dry-run cost exports from the legacy `export_gpt_input_data` command (on `main` only).
    - Sheets: `Overview` (model `gpt-4.1-mini`, temperature 0.7, 15,000-char cap, 3 retries, `ENABLE_OBSERVATION_SUMMARIES=0`), `GPT Input Data` (company, observation, word budgets, prepared prompt text, existing summary), and `Prompts` (system prompt "expert FDA GMP compliance summarizer…").
    - Source: `Final_File_FDA_Observations_15_12_2025.xlsx`. The 1,265 pending blocks would send about 2.2M characters (about 347k words).
    - **No secrets.** One cell (`N5353`) matched a "password" keyword pattern, but it is FDA observation prose.
  - **Assumption:** these relate to **SOW §1 (483 AI) summaries in the legacy app**, made to estimate OpenAI cost before running the summariser. They are **not** related to §2.6 chatbot work. Neither file is used by REGX.

---

## 11. Issues and risks, ranked

**Critical**
1. **Part 2 is sold as "AI Based", but REGX has no AI capability, and nothing is deployed.**
   - The governed platform is solid. However, §2.6, §2.8 and §2.10 (all the AI behaviour) are not started.
   - 40% of the fee is payable "after deployment of Regulatory Ai Software" (SOW line 442).
   - The SOW allows "recovery of payments" if the delivery does not align with scope (line 428).
   - Internal docs say "engineering complete" without mentioning the missing AI items, which risks a mismatch with what the client expects.
   - Part 2's timeline is "mutually decided" (§2.11), so there is no contractual overdue date.

   *(Business risk. The consequences are an Assumption; the contract terms are verified.)*
2. **Leaked credentials at the tip of `origin/main`.** Live-looking OpenAI key, SMTP passwords, Django secret, password hashes. Revocation is unconfirmed, and the docs wrongly claim a purge. Mitigated only by the repo being private.
3. ~~**Next.js 15.1.0.**~~ **Fixed: PR [#78](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/78) MERGED 2026-10-12:** next 15.1.0 → 15.5.27.
   - The original issue: npm audit reported 3 critical and 11 high, including GHSA-9qr9-h5gf-34mp (React flight RCE), the CVE-2025-29927 middleware bypass, and Windows/AVIF RCE advisories.
   - npm audit after the fix: 15 → 14 (critical 3 → 2). All 34 advisories against `next` itself are cleared.
   - **Still open:**
     - bundled postcss 8.4.31 (needs Next 16)
     - vitest/tinypool criticals (needs vitest 5; dev only)
     - the eslint-config-next glob chain (dev only)
     - the `next lint` deprecation, to be migrated with Next 16

**High**

4. Backend Django 5.2.3 has 33 advisories. pypdf 5.1.0 has 49 and **parses user uploads**. cryptography 44.0.3 has 6. DRF 3.15.2 has 2.
   - **Fixed: PR [#79](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/79) MERGED 2026-10-12** (after the MFA Fernet compatibility check passed): branch `regx/fix/backend-security-patch`, commit `609c0c0`. Moves to Django 5.2.18, DRF 3.18.3, pypdf 6.20.0 and cryptography 50.0.2.
   - pip-audit on `base.txt`: 90 → 0. The full suite still passes (4033 / 1 skipped), and a real-PDF upload extracts text correctly.
   - **Still open:** pytest 8.3.5 in `dev.txt` (1 advisory).
   - **company_site is not covered:** Django 5.1.3 (22 advisories; Assumption: 5.1 is past end of support), PyPDF2, simplejwt 5.3.1. Only a plan is wanted there, because company_site has no tests.
5. ~~**No login throttling or lockout.**~~ Twelve wrong passwords in a row all returned 400 [Verified]. Only MFA codes lock out.
   - **Fix in PR [#82](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/82) (open; rebased onto `eedbf9c` as `3d46eb5`):** per-account lockout, 5 failures → 15 min, 429 with `Retry-After`.
6. **Open self-registration plus self-service tenant creation** [Verified]. Any anonymous person can create an account and a tenant. No data leaks (a role-less user gets 403 everywhere), but no doc states this as policy. It is risky for a regulated B2B product.
7. **Uploads go unscanned by default.** Compose sets `DOCUMENT_SCANNER_ALLOW_STUB=true`, which overrides production's refusal to run the stub scanner. This is not in `check_env.py` or `DEPLOYMENT_BOUNDARIES.md`.
   - **Mitigation in PR [#84](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/84) (open; rebased as `6fd97f0`):**
     - a startup WARNING in every process running the stub;
     - `check_env.py --production` fails on the stub or on `ALLOW_STUB`;
     - the docs are updated.
   - **The compose default itself is unchanged** (owner decision).
8. **MFA is never enforced, not even for users who enrolled** [Verified 2026-10-12].
   - `login_view` (`backend/identity/views.py`) never checks `mfa_required`. An enrolled user gets a full session from the password alone: `password login: 200 mfa_required=True`.
   - A TOTP code is only ever checked at `POST /mfa/verify/`, after login, and nothing gates the session on it. No middleware or frontend redirect does either.
   - The SOW requires MFA for Reviewer and VP. **Owner decision needed**: enforcement design, including the company_site side effect that it refuses `mfa_required` accounts.
   - Fernet compatibility across the cryptography 44 → 50 upgrade was verified separately (PR #79).
   - **Bypass fixed 2026-11-05: PR [#96](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/96) (`regx/fix/mfa-login-enforcement`, `0c02062`), MERGED (`b6ffe26`).** Full backend suite 4,180 passed / 2 skipped. This is the bug fix only: **no role is forced to enrol.**
     - Enrolled user (verified device): `POST /auth/login/` with the right password → 200 `{"mfa_required": true, "mfa_pending": true, "email": …}` and **no session** (`/auth/me/` → 403). `POST /auth/login/mfa/ {"code"}` with a valid TOTP → session. Pending login expires after 5 minutes; a used code cannot be replayed.
     - Wrong, malformed and replayed codes count toward the #82 lockout. The right password no longer clears the counter for an enrolled user, so wrong passwords and wrong codes add up; only an accepted code clears it.
     - Users without a verified device: unchanged.
     - **company_site shared login:** still refuses enrolled users (verified live). The enrolled user sees **"Invalid Credential"** on the legacy login page, which is misleading (the password was right) but safe. They have no way into company_site at all.
     - Frontend: `/signin` sends an enrolled user to `/mfa` (keeps `?next`), and `/mfa` now calls the login second step.
     - **Still open:** recovery codes cannot be used at login (`/mfa/recovery/` needs a session and grants nothing), so a user who loses the device is locked out until someone removes the `MFADevice` row. MFA enrolment has no UI. Enforcement for Reviewer/VP (SOW 4.3b) is still an owner decision.
9. **company_site:**
   - insecure-key and `DEBUG=True` defaults outside compose
   - `@csrf_exempt` POST views
   - **0 tests** for about 22k lines of RATools/AdminMaster views
   - unpinned dependencies, so builds are not reproducible
   - a 7 MB SQLite database in git
   - no Celery worker, so queued jobs silently never run
10. **The documented OpenAI cost guard is missing from the code that runs.** `ENABLE_OBSERVATION_SUMMARIES` is described in `constraints.md:57` and `handoff.md:288`. It exists only on the legacy `main` branch (`4193f09`) and was never ported into `company_site/` on regx-main. Setting `OPENAI_API_KEY` there would let the public `GET /` trigger paid calls.
10a. **Celery worker broken on any fresh build: `kombu` drift** [Verified 2026-11-05].
    - `kombu` is not pinned; `celery[redis]==5.4.0` pulls in the latest. `kombu` 5.7.0 (released after the last green run, 2026-10-13) requires `redis-py >= 6.1`. We pin `redis==5.2.1`, so the worker dies at start-up with `VersionMismatch`.
    - **Impact:** the CI job "Build, start, and verify the production compose stack" fails on #92, #93 and #94, and `regx-main` itself builds a broken worker today. On the local stack the Celery container restart-loops. In production, documents would never be scanned or processed and connector runs would never execute.
    - **Fix:** PR [#95](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/95) (`regx/fix/pin-kombu`, `796761a`) pins `kombu==5.6.2`. **MERGED 2026-11-05** (`regx-main` = `4b942a5`; confirmed on GitHub before acting). Earlier the same day it was reported merged while still open; the merge was then watched for and acted on once GitHub showed it. Locally, a clean image build with the pin starts a worker that reports `ready`. #92, #93, #94, #96 and #97 were then updated from `regx-main` by a merge commit each (no force-push) so CI re-ran with the pin. **All checks green on all five** (Work Log, 2026-11-05 second session); none merged yet.
    - Root cause is #10b.
10b. **Only direct backend dependencies are pinned; indirect ones float** [Verified 2026-11-05].
    - **Status: MERGED 2026-11-05** as PR [#98](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/98) (`369b9c3`); branch deleted. All four CI checks green, including the new "Dependency locks match their inputs". Built as proposed below, with these specifics:
      - `backend/requirements/{base,test,dev}.in` are the old hand-edited files (`test.in` and `dev.in` constrained by the lock below them, so shared packages match). `base.txt` 50 packages / `test.txt` 59 / `dev.txt` 68, all with sha256 hashes. pip-tools 7.4.1 in `python:3.12-slim` (Python 3.12.16, pip 25.0.1, as the image).
      - **No version changed.** The locks were seeded from a fresh `--no-cache` build of `regx-main` (pip-compile keeps versions already locked). Every locked version equals what that image installs (50/50 runtime, 68/68 dev; 0 differences). kombu 5.6.2, redis 5.2.1, Django 5.2.18, DRF 3.18.3, pypdf 6.20.0, cryptography 50.0.2, celery 5.4.0 all kept. A second run changes nothing.
      - `backend/Dockerfile` and `.github/workflows/backend.yml` install with `--require-hashes --no-deps`. New CI job "Dependency locks match their inputs" regenerates the locks and fails on a diff. `scripts/lock_backend_deps.sh` (one command, Docker). Documented in `CLAUDE.md` "Commands".
      - **Proof:** clean `--no-cache` image build installs exactly the baseline set; Celery worker logs `Connected to redis` and `ready`, answers `inspect ping` with pong; `dev.txt` installs hash-checked with `pip check` clean; full backend suite 4,230 passed / 2 skipped; pip-audit identical before and after (#10c).
10c. **pypdf 6.20.0 now has 16 known advisories** [Verified 2026-11-05, pip-audit]. PR #79 moved pypdf to 6.20.0 when it had none; since then 16 GHSA advisories were published against it, fixed between 6.20.1 and 6.21.4. **pypdf parses user uploads** (`documents/tasks.py`), so this matters. Also open: pytest 8.3.5 (`PYSEC-2026-1845`, fixed in 9.0.3; dev only). Not upgraded in the lock PR, by instruction. **Status 2026-11-05: PR [#100](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/100) (`regx/fix/pypdf-upgrade`, `9421302`, from `regx-main@369b9c3`), open, not merged.** pypdf 6.20.0 → **6.21.4** (newest; fixes all 16) via `base.in` + `scripts/lock_backend_deps.sh`; it is the **only** version change in all three locks (no hash change for any other package; pypdf has no runtime dependencies on Python 3.12). pip-audit: `base.txt` 16 → **0**, `dev.txt` 17 → 1 (pytest only: its fix 9.0.3 is a major upgrade, so excluded by instruction). Clean build, worker ready, live 5-page PDF upload through the documents API: all pages extracted, text **identical page by page** to pypdf 6.20.0. Full suite 4,230 passed / 2 skipped. **Next:** a separate PR running `scripts/lock_backend_deps.sh --upgrade-package pypdf==6.21.4` (or newer), with the document-parsing tests and a real-PDF upload check.
10d. **company_site dependencies are not locked** (follow-up to #10b, out of scope of the lock PR). Its requirements are unpinned (§11 #9), so its builds drift the same way REGX's did. Same approach would apply (`.in` + hashed lock + script + CI check), but company_site has no tests, so a lock must be checked by hand against a working image first. The runtime image installs 50 packages; `base.txt` pins 19. About 31 (e.g. `kombu`, `billiard`, `vine`, `amqp`, `asgiref`, `sqlparse`) resolve to whatever is newest on build day, so two builds of the same commit can differ. The Dockerfile runs `pip install -r requirements/base.txt`; CI runs `pip install -r requirements/dev.txt`. **Proposal (not built):**
    - **Tool:** `pip-tools`. Keep the human-edited files as inputs (rename to `base.in`, `test.in`, `dev.in`, same content plus `-c` links), and generate fully pinned lock files `base.txt`, `test.txt`, `dev.txt` with `pip-compile --generate-hashes --strip-extras`. Every package, direct and indirect, gets an exact version and a sha256 hash. Compile on Linux with Python 3.12 (inside the backend image) so platform markers match production.
    - **Docker:** unchanged command, but install with `pip install --require-hashes --no-deps -r requirements/base.txt`. A missing or changed package then fails the build instead of silently installing something else.
    - **CI:** install `dev.txt` the same way. Add a job that runs `pip-compile --dry-run` (or compiles into a temp file and diffs) and fails if a `.in` file changed without regenerating its lock. Keep pip-audit (§11 #14) pointed at the lock files, which now describe exactly what ships.
    - **Developers:** edit `.in` files only, then run one script (e.g. `scripts/lock_backend_deps.sh`, running `pip-compile` in the backend image) and commit `.in` + `.txt` together. Upgrades become explicit (`pip-compile --upgrade-package kombu`), each reviewable as a diff. Nothing changes for day-to-day `pip install -r requirements/dev.txt`.
    - **Alternative:** a single `constraints.txt` from `pip freeze` of a known-good image, passed with `-c` in Docker and CI. Smaller change, but no hashes and no tooling to regenerate it consistently; recommended only as a stop-gap.
    - **company_site** (unpinned entirely, §11 #9) would need the same treatment separately.
    - **Scheduled:** build next session on its own branch (owner, 2026-11-05).
    - Size estimate: S–M. Risk: the first lock should be compiled from the currently working set (e.g. with `kombu==5.6.2`), then compared to `pip freeze` of the known-good image so nothing changes unintentionally.

**Medium**

11. ~~The OpenAPI schema and Swagger are public to anonymous users.~~ The full map of 273 operations is exposed [Verified].
    - **Fix in PR [#83](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/83) (open; rebased as `9c62f97`):** production settings only, `SERVE_PERMISSIONS=IsAuthenticated`. Development and test settings stay open.
12. Migrations do not run on start, and readiness says "ready" on an empty schema [Verified]. Easy to ship a broken release.
13. Backups are manual, unencrypted, run on no schedule and keep no off-site copy. RPO and RTO are undefined.
14. No dependency audit in CI. The final 9 PRs merged without CI running.
15. Errors are swallowed:
    - `documents/tasks.py` (5× `except Exception: pass` in text extraction)
    - 9 `_tenant()` helpers return None on any exception
    - **A PDF with no extractable text is reported as a full success** [Verified live 2026-11-05, pypdf 6.21.4 build]. A 2-page image-only PDF (text rendered as pixels, like a scanned 483; generated, since the two real FDA PDFs were never placed in `D:/Praverse/data/test-pdfs/` and the owner chose to skip them) uploaded through `POST /documents/`:
      - version `processing_status` **`complete`**, `failure_code` empty, processing job `success`;
      - 2 page locators, **0 characters on each**;
      - audit trail `document.version.created` → `scan.queued` → `scan.complete` → `processing.started` → **`processing.complete`**; no event, flag, field or log line says no text was extracted;
      - the same holds when `page.extract_text()` raises: `_process_pdf` in `backend/documents/tasks.py` catches it with `except Exception: pass` and stores an empty page.
      - **Effect:** a scanned 483 looks processed but is invisible to anything that searches or reads extracted text (gap analysis, future AI features), and no one is told.
    - **Proposal (not built):**
      - record per page why text is empty: `extraction_outcome` in the page locator's `structured_metadata` = `text` / `no_text_layer` (page has images but no text) / `extract_error` (exception, with the exception class only);
      - add a version-level summary to `source_metadata`: `pages_with_text`, `pages_without_text`, `pages_with_errors`;
      - when no page has text, keep `processing_status = complete` (the file *was* processed) but set a new field or flag `text_extraction = none` with the reason "no extractable text, likely scanned", emit `document.processing.no_text` (audited), and show a warning badge on the document page; partial cases ("3 of 12 pages have no text") get the same treatment at page level;
      - log a WARNING (no document content) instead of the silent `pass`;
      - **OCR:** not in the SOW as a named feature, and it would add a heavy dependency (e.g. Tesseract in the image, or a paid cloud OCR API, which is an owner decision on cost and data handling). Recommended: build the detection and warning first (S–M); treat OCR as a separate owner decision, since 483s are often scanned and §2.6/§2.8 depend on their text.16. Import-linter gaps: the 4 ported apps are outside `root_packages`, so no layering contract covers them.
17. Docs drift:
    - The `ARCHITECTURE.md` module table lists 13 of 25 apps.
    - `README.md` claims "shares no code with legacy" while `company_site/` is in the tree.
    - `handoff.md` (2026-09-09) says PR #49 is open and the suite has 3,811 tests.
    - `RELEASE_BLOCKERS.md`, `RELEASE_VALIDATION.md` and `ROADMAP.md` say CI is blocked, which is stale.
    - `DEPLOYMENT_BOUNDARIES.md` gets the env contract wrong.
18. The S3 storage backend is a stub, so all files live on a single-host Docker volume.
19. Data gaps: warning letters have 0 rows; the workbooks live on one machine; FDA tables are empty.
19a. **Fix in PR [#89](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/89) (open, 2026-10-13; `regx/fix/iid-importer`, `49328f5`):** the real July 2026 IID file now imports. Loaded locally through the full lifecycle: 9,071 / 9,071 rows, 0 field mismatches, release `bef6285c-2779-44f7-b9a7-e1bc6e4e126c` active. It also fixes: blank potency refusing the whole file (5,266 rows), plain numbers lost with units like `mg/5ml`, and UNII `NA` merging 819 ingredients. Full suite 4,142 passed / 2 skipped. **Open:** the 4,059 daily-exposure-only rows read `potency_missing`; a rule is proposed in the White Paper spec Q8 (§12).
19b. **Re-importing the same file never applies newly approved mappings, and for the IID it is not even refused** [Verified 2026-10-13, test database only; line numbers are on `regx/fix/iid-importer`]. `register_release` returns the existing release for the same (dataset type, checksum) (`backend/fda_data/importer.py:85`). `import_fda_release` then stops only if `record_count_imported` > 0 (`backend/fda_data/management/commands/import_fda_release.py:152-155`). That is true for the Orange Book ("Nothing to do"), but for the IID it is 0, because every row is `review_required` while no route is mapped. So the command runs the import again: `import_iid_rows` skips every row that already has a result (`importer.py:375-381`), changes nothing, adds one more `IMPORT_STARTED` audit event and prints "registered". A route and dosage-form mapping approved between the two runs was **not** applied (the record stayed `route_unmapped`). From the code (not run): the JSON release API (`backend/fda_data/views.py` release POST) has no guard at all: same payload → same release, a no-op import, HTTP 201. Proposal in §12. **Status (2026-10-13, fourth session):** the owner approved fixing the duplicate guard (command and JSON API → 409) and building the re-resolve command; **not started**, because the owner's gate requires #89 and #90 to be merged first. **Update (fifth session):** built, not pushed. Duplicate guard on `regx/fix/import-duplicate-guard` (`8940539`): any row result now blocks a repeat; the command prints a refusal naming the release and its status, and the JSON API returns 409 `duplicate_release`. Re-resolve on `regx/feat/reresolve-terminology` (`3caf357`). See §12. **Update 2026-11-05:** a refused duplicate now exits with **code 2** (errors stay 1), commit `914ba4c`; the contract change is stated in the PR. **Changed to code 3 the same day** (owner): Django's argument parser already exits 2 on a usage error (e.g. a missing required option), so 2 could not identify a duplicate. Codes are now 0 imported, 1 error, 2 usage error, 3 refused duplicate. Commit `89a03ea` on #92, tests updated, PR description notes why; `fda_data` 298 passed / 1 skipped. Pushed as PRs [#92](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/92) (duplicate guard) and [#93](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/93) (re-resolve), open, not merged.
19c. **The loaders recorded no user** [Verified 2026-10-13]. `load_spl_terminology` and `import_fda_release` ran without an actor, so releases had `imported_by` empty and "approver ≠ loader" held by procedure only. **Status 2026-11-05: PR [#97](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/97) (`regx/feat/loader-actor`, `db6918d`), open.** Full backend suite 4,187 passed / 2 skipped.
    - Both commands require `--actor <email>`: an existing, active user holding `fda_data.import` (Doer) through an active membership of an active tenant. Missing, unknown, inactive or unauthorised actors are refused before anything is written.
    - The actor is recorded as the release's `imported_by` and on its `registered` / `import_started` audit events.
    - `lifecycle.approve` (already) and now `lifecycle.activate` refuse the recorded loader, for FDA releases and SPL terminology releases alike. The API answers 403 `loader_cannot_approve` / `loader_cannot_activate`.
    - **Gap:** releases loaded before this change have no recorded loader, so the check cannot apply to them (the local SPL and IID releases).
    - **Merge note:** `import_fda_release.py` is also changed by #92; whichever merges second needs a small conflict resolution.

**Low**

20. About 1,400 lines of commented-out code across 106 blocks in company_site.
21. Thin tests: `audit` (4) and `authorization` (9). The coverage gate is 55%.
22. About 7 drifting copies of the "banned regulatory claim" phrase guard.
23. ~~About 60 stale merged branches on the remote.~~ **Done 2026-10-12:** 86 deleted, 8 remain on GitHub.
24. The Next.js `/` page is unreachable behind nginx. nginx `^~ /templates`-style prefixes have no trailing slash, so they also match `/templatesX`.
25. **Tenant-scoped roles named `doer`/`vp`/`tenant_admin` break `seed_regx_demo`** (`Role.MultipleObjectsReturned` at `backend/demo_seed/management/commands/seed_regx_demo.py:246`, which looks roles up by name only). Investigated 2026-10-12, read-only:
    - **What exists:** the local DB has roles 6–8 in tenant `praverse-demo`, all with `is_system=True`. That combination makes no sense: system roles should have no tenant.
    - **When:** they were created 2026-09-09 between 10:36:21.06 and 10:36:21.40 UTC. That is within 0.6 s of the tenant itself (10:36:20.87), and each one about 20 ms after its matching `sso.*@praverse.test` user. There are no audit events.
    - **How (Assumption):** an ad-hoc `manage.py shell` script from the 2026-09-09 shared-login session. For each test user it created a tenant-scoped role instead of attaching the system role.
    - **Can committed code create them? No.**
      - `authorization/seed.py:51` only ever creates `tenant=None` roles.
      - The authorization API is GET-only.
      - REGX has no Django admin.
      - Only shell or direct database access could.
      - The schema allows it, though: `unique_together = (tenant, name)` permits a tenant role with a system role's name.
    - **Fix (not started, per owner):** filter the seed's lookup on `tenant__isnull=True`. Optionally, add a DB constraint so `is_system=True` implies `tenant IS NULL`.

---

## 12. Open questions (need humans)

**For the owner / Praverse management**
1. Who left (Assumption: Devpt1904), and is that person reachable for questions?
2. What is the immediate goal: deploy what exists, build the SOW AI scope, or renegotiate scope?
3. Have any SOW payments been received? Which milestones has iCretegy accepted?
4. Have the 3 OpenAI keys and the SMTP password been revoked? Who owns the OpenAI and Office365 accounts?
5. Who are the named owners for the regulatory, security, product and business blockers? The docs say none are named.
6. Where should production run (AWS or Azure per SOW §5.2), and who owns that account?
7. Is open self-registration and tenant creation intended?
8. **Where does the 483 AI (SOW Part 1) live, if anywhere?** REGX holds the 483 data as an API but no AI. The only 483 AI code found is the legacy `gpt-4.1-mini` observation summariser in `company_site` (and on `main`), plus the cost-estimate workbooks `gpt_input_data*.xlsx`.
8a. Was a phase-2 scope or date for Part 2 agreed with iCretegy after the SOW (§2.11 leaves it "mutually decided")?

**Resolved**
- ~~Which Orange Book source?~~ **Resolved 2026-10-12:** the public FDA Orange Book download is primary, and iCretegy's Excel is an optional cross-check (owner reports written confirmation from iCretegy). No Excel importer will be built. *Open: where the written confirmation is stored. The owner was asked on 2026-10-12, but the path placeholder (`<PATH_FROM_PRATHAM>`) was not filled in.*

**New (Orange Book plan, 2026-10-12)**
- **Release metadata:**
  - `--publication-date` is built on local branch `regx/feat/fda-release-metadata` (`ce18aab`, not pushed).
  - **Correction:** the release API already returns the file name, checksum and notes to `view_raw` holders (Reviewer, VP). They are hidden from Doers **by design**, and a test guards that. My earlier "hidden" finding came from checking as a Doer.
  - **Open:** should Doers see them too? That would change a deliberate access rule.
  - **Open:** a dedicated field for the ZIP's internal file date would need a migration.
- **Terminology mappings:** **owner: Praverse regulatory reviewer, with sign-off by Pratham** (decided 2026-10-12).
  - The review workbook is at `D:/Praverse/data/fda/mappings/orange_book_terminology_review_2026-10-12.xlsx`, with the guide in `docs/TERMINOLOGY_MAPPING_REVIEW.md`.
  - **Open policy decisions:** multi-route and multi-form values, `INJECTION`, the percentage basis, new unit dimensions, and per-presentation strengths. Also: re-import or a re-resolve step after approval.
- **`handoff.md` demo passwords:** removed from the current file in PR [#85](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/85). History is not rewritten. **Action: change the local demo passwords.**
- **Controlled vocabulary: DECIDED 2026-10-13 (owner).** Recorded in `docs/TERMINOLOGY_VOCABULARY_DECISION.md` (PR [#88](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/88)).
  - **FDA SPL lists.** Route and dosage-form `code` = NCI Thesaurus code; the SPL term is the display name. The IID already uses SPL (routes 59/59, forms 105/106 exact); the Orange Book does not (routes 36/79, forms 75/117).
  - **Units: on hold**, a separate later PR (needs a migration).
  - **INJECTION (interim rule until iCretegy answers):** show all matching IID records, never auto-pick a limit, the reviewer confirms the route. `find_iid_candidates` is not changed yet.
  - **Review scope:** the reviewer fills in routes and dosage forms only. The workbook `D:/Praverse/data/fda/mappings/orange_book_terminology_review_spl_2026-10-13.xlsx` now says "ON HOLD — do not fill" at the top of the Units sheet (added 2026-10-13; sha256 now `a56c3cfe…ca249a1`).
  - **Licence (official pages, quoted in the doc):** FDA website content is public domain; NCI Thesaurus is CC BY 4.0, and the name is a trademark. Open: whether CC BY attribution must appear in the UI (a legal reading).
  - **Loader built** (`load_spl_terminology`, local branch `regx/feat/spl-terminology-seed`). Snapshot saved in `D:/Praverse/data/fda/spl/2026-10-13/` (downloaded 07:00:38 UTC). Loaded locally as **draft**: 121 routes and 158 dosage forms, identical to the source lists. **Not active until a VP approves and activates the two releases.**
- **INJECTION question for iCretegy:** the owner decided on 2026-10-13 to send it with the three conditions (interim rule above). Final draft in `docs/TERMINOLOGY_VOCABULARY_DECISION.md` §4. Proposed answer: "Orange Book 'INJECTION' matches all injectable IID routes and is flagged for reviewer confirmation", tightened with three conditions: (a) a fixed reviewer-approved list of injectable routes (IID data alone would include ORAL and RECTAL: 42 routes appear next to injectable forms); (b) show every matching IID record and never auto-pick the highest limit; (c) the reviewer confirms the product's real route. **Risk if accepted as worded:** an IV product could be checked against another route's higher limit. Also needs a matching-code change (`find_iid_candidates` takes one route). **Not sent yet** (as of 2026-10-13); owner to send.
- **Daily-exposure rule (proposed 2026-10-13, pending iCretegy and the regulatory reviewer):** `docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md` Q8 (PR [#91](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/91), open). Each IID row has either a per-unit limit (potency, 3,805 rows) or a per-day limit (maximum daily exposure, 4,059 rows), never both. The checklist runs the per-unit check when potency exists, and the per-day check (amount per unit × maximum dosage units per day vs the IID daily exposure) when daily exposure exists, using the product's structured maximum daily dose. Results read "at or below" / "above" with both numbers, never "acceptable". "Cannot compare" when the unit basis or the daily dose is missing. Several matching rows are each shown; nothing is auto-picked. Not built.
- **Re-import vs re-resolve (finding §11 #19b): BUILT 2026-10-13; pushed 2026-11-05 as PRs #92 / #93 (open).** Same-file imports are refused everywhere (`regx/fix/import-duplicate-guard`). `reresolve_terminology <release>` (`regx/feat/reresolve-terminology`) works only before submission for review, only fills empty route/dosage-form links from approved current mappings (never overwrites), writes one audit event per changed record plus a summary, and has `--dry-run`. Generic core, IID wired up, Orange Book not yet. **Safety guard:** submitting an IID release with unmapped records returns 409 `unmapped_rows` with the count; `confirm_unmapped: true` submits with a warning, and the count goes into the audit event. **Production order:** import → approve mappings → re-resolve → submit for review → approve → activate.
- **IID mapping proposals (2026-10-13, local):** `propose_iid_mappings` proposed **59 route and 105 dosage-form mappings** (exact matches to active SPL terms); **one value is not exact: `DROPS` (67 records)**; it needs a reviewer's choice (e.g. `SOLUTION/ DROPS` or `SUSPENSION/ DROPS` are separate SPL terms). Nothing was approved; a VP reviews them in the app. Run on the dev DB only. Pushed 2026-11-05 as PR [#94](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/94) (open). The re-resolve and duplicate-guard branches are PRs #93 and #92.
- **`DROPS`: stays unmapped (owner decision, 2026-11-05).** No mapping is created for the IID value `DROPS` (67 records). Each such record is resolved **per record at review** (the reviewer picks the SPL dosage form from the product), **pending regulatory reviewer confirmation** of this approach. The re-resolve tool leaves these records' dosage-form link empty, so the unmapped-rows guard (#93) will count them at submit-for-review.
- **How a VP approves terminology mappings today (checked 2026-11-05, read-only): one at a time, two steps each.**
  - **API:** only per-mapping endpoints: `POST /fda-data/mappings/<id>/submit-review/` (Reviewer or VP), then `POST /fda-data/mappings/<id>/approve/` (VP only, `CanApproveFdaData`; only from `under_review`, `backend/fda_data/mapping_transitions.py`). The approver may not be the user who submitted it (`self_approval_forbidden`, `backend/fda_data/views.py` `_MappingActionViewBase`). No bulk endpoint exists.
  - **UI** (`frontend/src/app/(regx)/fda-data/mappings/page.tsx`): a paginated table (25 per page, max 100) with one button per action per row, each opening a confirm dialog. No row selection.
  - **Cost today:** the 164 IID proposals need **328 single actions** (164 submits by a Reviewer, then 164 approvals by a different VP), each with its own dialog.
  - **Side finding:** the UI shows "Approve" on `proposed` rows too, but the API refuses approval from `proposed` (400). Cosmetic, not a bypass.
- **Proposal (NOT built): VP-only "Approve selected".**
  - **UI:** on the mappings page filtered to `status=under_review`, a checkbox per row and "Approve selected (N)". The table shows raw value, proposed SPL term and affected-record count. The confirm dialog lists every selected row with those three columns and the total record count, and needs an explicit "I have reviewed these N mappings" tick.
  - **API:** `POST /fda-data/mappings/approve-selected/ {"mapping_ids": [...], "reason": "..."}`, `CanApproveFdaData` only, at most 100 ids. All-or-nothing in one transaction: refused with the list of offending ids if any mapping is not `under_review`, was submitted by the requester, or does not exist.
  - **Audit:** one `fda_data.mapping.approved` event **per mapping** (same as today), each carrying a shared `batch_id` and the batch size in its payload. No single "batch approved" event replaces them.
  - **Not included:** bulk submit-for-review (Reviewer side) would halve the remaining clicks; owner to decide if wanted. Approving mappings still changes no existing record until re-resolve (#93) runs.
  - Estimate: S–M (one endpoint, one UI change, tests).
- **Work email in the curl User-Agent (asked 2026-10-13):** it came from the Claude Code session, which supplies the account email to the assistant. It is not in git config (`user.email` is the GitHub noreply address), not in any environment variable, script or `.curlrc`. The assistant typed it into the command. A rule now in CLAUDE.md "Hard constraints": outgoing HTTP requests use `REGX-dev-research` as the User-Agent and carry no names, emails or tokens.
- ~~Does FDA permit automated retrieval of the Orange Book ZIP?~~ **Superseded 2026-10-12:** openFDA's `download.json` gives a supported change signal (rate limit 1,000/day without a key). The ZIP stays a manual operator download.
- Register a free openFDA API key (120,000/day) for the optional lookup cross-check? It is an account, so this is an owner decision.
- Could the openFDA bulk JSON export ever be an automated source of record? Recommended: no, ZIP only (plan §2b). Owner to confirm.
- ~~Phase 1b before Phase 2?~~ **Resolved:** the owner approved it, and it is done (awaiting review).
- Which white-paper calculations, if any (plan §6, 7 open questions for iCretegy)? The legacy tool calculates nothing.

**For the client (iCretegy)**

9. Sign-off on the 20-item content gate and Approval Register items 13/14.
10. Calculator specs, the Word add-in contract, and stability/impurity feasibility.
11. A corrected AIDatabase export, a snapshot that includes warning letters, and real FDA/Orange Book source files.
12. Is ipharmaai.com the live legacy app (Assumption), and is REGX expected to replace it or sit beside it?
13. Does the contract need a Part 11 *attestation*, or only the controls?

**Could not determine from code alone**

14. Where the "six platform checklist definitions that ship with the database" come from. No migration or command creates them.
15. Whether any other environment (staging or a demo server) ever existed.
16. Whether the legacy `main` branch is still deployed from Render (it has `render.yaml`).

---

## 13. SOW Part 2 gap matrix

**Sources and status values:**
- **Source text:** SOW PDF pages 7–9 and 12–13, extracted 2026-10-08.
- **Verified against the code** at `regx-main@732133f`, not against docs alone.
- **Built:** code, API, UI and tests exist.
- **Partly built:** some of the requirement exists.
- **Not started:** no code found.
- **Blocked on client:** a *specific* input is missing that engineering cannot stand in for.

**Blocker type:**
- **Eng:** we can do it now, using demo or placeholder data where needed.
- **Client:** needs their input.

**Size** is an **estimate** for one experienced developer:
- S: under 1 day
- M: 1–3 days
- L: 1–2 weeks
- XL: more than 2 weeks

**Headline:** REGX has **no LLM, AI or ML call path** anywhere. `backend/requirements/*.txt` and `frontend/package.json` include no provider SDK, and nothing in `backend/` or `frontend/src` calls one. Every "AI" bullet below is therefore Not started, whatever the docs imply.

> **Note on Part 2's own terms:** the SOW says Part 2 scope "may be finalized later (in phase 2)" (page 7). §2.11 says the timeline will be "mutually decided". §2.8 (heatmap), §2.9 and §2.10 are marked "Will see later if this point is feasible".

| SOW ref | Requirement (short) | Status | Evidence | What is missing | Blocker | Size (est.) |
|---|---|---|---|---|---|---|
| 2.1 a | New **AI** platform for Technical Tools, built on iCretegy raw data | Partly built | 25-app platform. iCretegy source ingestion via `templates_registry` source packages and migration batches (`/template-sources/`, `/migration-batches/`, `docs/TEMPLATE_IMPORT_PIPELINE.md`) | The AI layer (see 2.6, 2.8, 2.10) | Eng | (counted in 2.6/2.8) |
| 2.1 b | Attractive, user-friendly UI; accepts PDF, Excel, Word, PPT | Partly built | Next.js UI, 46 pages, axe-checked. Documents accept pdf/docx/xlsx/pptx with text extraction (`documents/models.py:18-22`, `documents/tasks.py`) | UI for the 4 ported APIs (deficiencies, 483s, controlled correspondence, product comparison) | Eng | L |
| 2.1 c | Module-wise single premium toolkit, not scattered utilities | Partly built | REGX sidebar, but it mixes in **32 legacy `/ratools/...` links** (`frontend/src/components/regx-shell/RegxSidebar.tsx:178-230`) | One coherent REGX module set; retire or replace the legacy links (P13c disposition affects which ones) | Eng (Client for legacy-approval disposition) | L |
| 2.2 a | Auto-fill the IIG checklist per raw material from the FDA IIG database | Partly built (engine done) | Questions bind to `iid.*` via `prefill_source`. Execution creates a governed IID snapshot (`iig_checklist/services.py:378-514`). About 1,197 iig_checklist tests | **No real content may go live:** content gate 0 of 20 (`docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md`). IID data: the importer now reads the real July 2026 file (PR #89, merged; loaded and active locally, 9,071 rows). See the critical path in §14 | Client (approved content + IID source file) | S once inputs arrive |
| 2.2 b | Auto-fetch limits, route mapping, auto-calculate limits, cite IIG references | Built (engine) | `iid_assessment` matching (`/iid-assessments/preview/`, `docs/IID_MATCHING_ENGINE.md`), controlled routes and mappings (`/fda-data/mappings/`), 6-formula calculation registry (`iig_checklist/calculation_registry.py`), FDA SOURCE provenance labels in the UI. 145 + 172 tests | Approval Register 13/14 (which calculation applies to which question). Engineering path to real matching: §14 "Critical path to IIG matching" (steps 1–3 merged; 4–5 in open PRs #92–#94; 6 proposed) | Client; Eng | S–M |
| 2.3 | HTML calculators inside Technical Tools: dissolution, impurity, stability trend | Not started (REGX) | None in `backend/` or `frontend/src`. The legacy app has HTML tools (`company_site/templates/RATools/WhitePaper/`, `SizeShapeScore/`) | Calculator framework plus each calculator. Formulas, units and rounding need specs (`docs/CALCULATOR_SPECIFICATION_INTAKE.md`). The framework, and porting the existing legacy HTML tools, can start now | **Client** for specs; Eng for framework and ports | L (framework + ports); M per calculator after specs |
| 2.4 | Doer → Reviewer → VP hierarchy with review gates and traceable actions | Built | 5 roles (`authorization/seed.py`). Review gates on workflows, checklist versions and executions, templates, FDA releases, packages, upgrades. Immutable transition history (DB triggers) | Nothing for 2.4 itself. MFA for these roles is §4.3 | — | — |
| 2.5 a | Orange Book: minimal inputs → fetch reference data → automatic calculations "like in white paper & IIG checklist" | Partly built (see §14) | **Real FDA products data is loaded and active locally** (Phase 2, 2026-10-12): release `6d9fe36b-839d-4ced-8b7c-f3b326243be0`, 48,761 products, verified field by field against the file. Importer fixes in PR [#80](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/80), **merged** (`Type`/discontinued, approval dates with locale-independent parsing, trade-name and application-number search, validated reference selection). Plan and spec in PR [#81](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/81), **merged**. Terminology review prepared (workbook plus `docs/TERMINOLOGY_MAPPING_REVIEW.md`); **vocabulary decided 2026-10-13** (FDA SPL lists, NCI codes; PR #88) and the workbook regenerated against it (units on hold); SPL loader merged (PR #90) and active locally; per-unit / per-day IID check proposed (White Paper spec Q8); `--publication-date` merged (PR #86) | Patents/exclusivity (Phase 3), new-data detection plus operator upload (4), lookup page (5). **Terminology mappings: none approved, and the controlled vocabularies are empty**, so 0 products have a normalised route or dosage form and all strengths are review-required. The review is with the regulatory reviewer (sign-off by Pratham). A loader is needed, plus a re-import or re-resolve step after approval. **The legacy white paper performs no calculations**; proposed answers are in `docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md` | Eng (Phases 3–5, terminology mapping workflow); Client (white-paper spec confirmation; mapping approvals) | M–L + M + M–L, plus terminology (estimate M) |
| 2.5 b | iCretegy provides the FDA database Excel; Praverse keeps it updated | **Agreed: public FDA source** | Owner reports (2026-10-12) that iCretegy confirmed in writing that the public FDA Orange Book download is the primary source, with their Excel as an optional cross-check only. `import_fda_release` already ingests the FDA ZIP / `Products.txt` | Keeping the data updated is covered by plan Phase 4 (auto-fetch, human activation). **No Excel importer will be built** | — (resolved) | — |
| 2.6 a | Chatbot across the workflow: step-by-step guidance, explain requirements, gap assessments, resolution summaries | **Not started** | No LLM code, no chat UI, no provider dependency. The legacy chatbot was **removed** in P8 (`cd0448e`) | All of it: LLM integration, retrieval over REGX data (checklists, deficiency corpus, guidance), chat UI, grounding and citations, audit logging of prompts and responses, claim-guard compliance | Eng (provider choice and data policy is an owner decision, see Q5) | XL |
| 2.6 b | Single or bulk module upload "on iPharmaAI UI" for automatic gap assessment and resolution; minimal response time | Not started | Upload is single-file (`POST /documents/`). Gap analysis works on **checklist answers**, not on uploaded documents | Bulk upload; analysis of uploaded documents; resolution output. "iPharmaAI UI" is ambiguous (legacy `company_site` or the REGX frontend?) | Eng; Client to clarify where it lives | XL |
| 2.7 | Word plug-in: section guidance, predictive deficiency flags, gap analysis, references, zero hallucination, auto-versioning | Not started | None. `docs/WORD_ADDIN_CONTRACT_INTAKE.md` lists 13 open contract items | Office add-in, backend API for it, auth (depends on SSO in 4.3). An Eng prototype taskpane is possible, but distribution, security and data-handling decisions are specific missing inputs | **Blocked on client** (13 contract items) | XL |
| 2.8 a | ANDA/DMF gap score 0–100 for **uploaded documents**, drill-down by section, against iCretegy DB | Partly built | Checklist-based gap analysis with section breakdown, immutable snapshots and UI (P7: `iig_checklist/gap_analysis.py`, `/gap-analyses/`). **The score is deliberately withheld:** the legacy `score_percent` is kept for API compatibility only and is "not governed" (`gap_analysis.py:30-34, 379-396`) | Analysis of uploaded documents, not just checklist answers; the 0–100 score; per-section drill-down on documents. Can be built now with a clearly labelled demo formula. The production formula needs client sign-off | Eng (Client for the final formula) | XL |
| 2.8 b | Predictive deficiency heatmap by section *(feasibility TBD)* | Not started | The deficiency corpus exists as an API (`/deficiencies/`, `deficiencies` app). It is empty until `import_deficiencies` runs from the legacy snapshot | Section classifier, likelihood model over the deficiency history, heatmap UI | Eng (data is available locally) | L–XL |
| 2.8 c | AI resolution playbook per gap, with regulatory references | Not started | None | LLM generation grounded in the deficiency corpus and guidance, with citations. Reuses the 2.6 foundation | Eng (guidance corpus from client improves it) | L (after 2.6) |
| 2.9 a | Stability trend analyzer: ICH data → trend plots, shelf-life prediction, out-of-trend flags *(feasibility TBD)* | Not started | `docs/STABILITY_IMPURITY_ASSISTANT_INTAKE.md` (feasibility intake) | Everything. The SOW defers feasibility, and the intake lists specific decisions (data format, statistical method, assertion boundary) | **Blocked on client** | XL |
| 2.9 b | Impurity profiling against ICH Q3A/Q3B thresholds | Not started | None | Threshold engine and UI. The thresholds are public ICH tables, so an Eng prototype is possible. Feasibility is deferred by the SOW | Client (feasibility); Eng could prototype | L |
| 2.9 c | Part 11–compliant audit trail for all calculator inputs and outputs | Partly built | Immutable `AuditEvent` (DB triggers, `audit/migrations/0001_initial.py`) with actor, time and IP fields. Calculation outcomes persisted (`CalculationOutcome`). A Part 11 claim is deliberately withheld | Electronic-signature meaning and manifestation; audit review and export (see 4.4); validation documentation. Depends on 2.3 calculators existing | Client (attestation or controls only, Q in §12); Eng (export) | L |
| 2.10 a | Smart versioning: AI summary of what changed and its regulatory impact *(feasibility TBD)* | Partly built (versioning only) | `DocumentVersion`, duplicate detection, text extraction (`documents/`) | AI change summary and impact flag | Eng | L (after 2.6 foundation) |
| 2.10 b | Side-by-side diff of two versions with AI commentary | Not started | No diff or compare code in `documents/` | Text diff view plus AI commentary | Eng | L |
| 2.10 c | Auto-tag uploads by document type, CFR relevance, product category, pathway | Not started | `document_type` is **file format only** (pdf/docx/xlsx/pptx; `documents/models.py:18`) | Tag model plus a classifier (LLM or rules) | Eng | M–L |
| 4.2 a | Hard multi-tenant isolation (documents, query history, API keys) | Built | Fail-closed `TenantMiddleware`; tenant FKs; verified live (403 without the header and across tenants; 200 within the tenant) | No query history or client API keys exist to isolate yet. **Open self-service tenant creation** needs a policy decision (§11 #6) | Eng (Client policy) | S |
| 4.2 b | Customer data never used for model training without opt-in | N/A today | No AI in REGX | Becomes a requirement with 2.6/2.8/2.10: provider no-training setting, contract terms, opt-in flag | Eng (when AI is added) | S |
| 4.2 c | Zero Praverse-staff access to customer documents without VP-approved, audited break-glass | Partly built | `platform_support` role is metadata-only for documents: "future break-glass required" (`documents/permissions.py:11`) | Break-glass request, VP approval, time-boxed access, audit. Infra-level access (DB, volumes) is uncontrolled | Eng | M |
| 4.3 a | SSO via SAML 2.0 / OIDC (Okta, Azure AD, Google) | Not started | None. The "SSO" branch name means only the company_site → REGX password check | SAML/OIDC login, account linking, per-tenant IdP config | Eng (client IdP for production config) | L |
| 4.3 b | MFA enforced by default for Reviewer and VP | Partly built | TOTP enrol, verify and recovery (`identity/views.py`). `mfa_required` is set only when a user chooses to enrol. **Login now requires the TOTP code for enrolled users** (PR [#96](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/96), open; §11 #8) | Role-based enforcement (forced enrolment) for Reviewer/VP: owner decision. Enrolment UI; recovery-code login. **Side effect:** company_site refuses `mfa_required` accounts, so enforcing MFA would lock Reviewers and VPs out of legacy tools; design needed | Eng | M |
| 4.3 c | Granular feature-level RBAC | Built (code-defined) | Per-module codenames (e.g. `documents.view`, `documents.archive`) mapped to 5 roles in each `permissions.py`. Tests per module | Role-to-permission mapping is fixed in code, not admin-configurable. There are no "manage API keys" or "export reports" style permissions beyond what modules define | Eng | M (configurability) |
| 4.4 a | Immutable audit log of every query, response, export, user action and admin change, with user, time and IP | Partly built | `AuditEvent` immutable via triggers, with `actor_id`, `created_at` and `ip_address` (`audit/models.py:23-31`). Domain mutations logged across apps (per-app `audit_events.py`) | **Reads and queries are not logged; login and logout are not logged** (`identity/views.py` has no audit call) | Eng | M |
| 4.4 b | Audit log export (JSON/CSV); retention of at least 7 years | Not started | **No audit API at all.** `audit:view` is seeded (`authorization/seed.py:22`) but no endpoint uses it | Audit query and export endpoints plus UI; a retention policy (owner decision in `docs/REGX_OWNER_POLICY_DECISION_PACKAGE.md`) | Eng (Client for retention policy) | M |
| 4.4 c | Compliance dashboard: user activity, data-access patterns, anomaly alerts | Not started | `submission_operations` is a workflow dashboard, not a compliance one | Activity aggregation, anomaly rules, alerts | Eng | L |
| 5.1 | Document upload and index under 30 s per 50-page document | Not measured | Async scan and text extraction exist (`documents/tasks.py`). `docs/PERFORMANCE_BASELINE.md` measures **structure only, never timing** | A timed benchmark on a 50-page PDF | Eng | S |
| 5.1 | API response under 2 s p95 | Not measured | Same as above. No load test (`docs/RELEASE_BLOCKERS.md`) | Load test (k6/Locust) against a seeded stack | Eng | S–M |
| 5.1 | 99.9% monthly uptime | Not applicable yet | Nothing is deployed | Hosting decision, monitoring, deployment | Client/owner (hosting) | L (after decision) |
| 5.1 | Fast/Think query, alert delivery SLAs | Out of REGX scope | These are Part 1 (483 AI) features | — | — | — |

**Where the docs and the code disagree:**
- `docs/SOW_SECTION_2_STATUS.md` and the closure audit do not claim the AI items are done, but the closure audit **omits 2.6 and 2.8 entirely**. "Engineering complete" should therefore be read as "the non-AI platform is complete".
- `handoff.md` calls the shared password check "SSO". It is not SSO in the sense of SOW 4.3.
- The legacy-port branch title "legacy-port-and-sso" carries the same misleading label.

### Recommended build order (Engineering items)

Ordered for the fastest *visible* progress, with AI capability early:

1. **Load real-looking data, so existing features stop looking empty.**
   - Import the deficiency and 483 corpora from the local legacy snapshot.
   - Load the public FDA Orange Book and IID files.
   - *(S. Prerequisite for good demos and for grounding the AI.)*
2. **AI foundation in REGX.**
   - Build a provider adapter as a new leaf app, using the `external_integrations` style of edge and the import-linter rules.
   - Add a cost and kill-switch flag that actually exists in code, plus per-tenant isolation.
   - Audit-log every prompt and response (covers part of 4.4a).
   - Set the provider's no-training option (4.2b).
   - *(M. Unblocks 2.6, 2.8 and 2.10. Needs the provider decision, Q5 below. Build against a stub provider until then.)*
3. **§2.6 chatbot v1: "Explain this" assistant** on checklist execution and gap-analysis pages.
   - Grounded on the checklist definition, the deficiency corpus and gap snapshots, with citations.
   - Must pass the regulatory-claim guard.
   - *(L. The most visible AI win.)*
4. **§2.8c resolution playbook,** generated per gap from P7 gap snapshots plus the deficiency corpus. *(L. Reuses item 3.)*
5. **§2.10c auto-tagging and §2.10a AI change summary on upload,** hooked onto the existing text-extraction task. *(M–L.)*
6. **REGX pages for the 4 ported APIs** (deficiency search first) and cleanup of the sidebar's legacy links (§2.1). *(L.)*
7. **§2.8a document-based gap score 0–100,** with a visibly labelled "demo formula pending approval". *(XL.)*
8. **§2.10b version diff with AI commentary;** **§2.8b deficiency heatmap.** *(L each.)*

**Parallel security and readiness track** (small, and needed before any client deployment):
- login throttling
- MFA enforcement for Reviewer/VP (4.3b)
- audit export and login auditing (4.4a/b)
- authenticated `/api/schema/`
- dependency upgrades (Next, Django, pypdf)
- §5.1 timing benchmarks
- SSO (4.3a, L)

### Questions that unblock the most Client items

1. **Who at iCretegy is the named regulatory approver,** and when can they sign off the 20-item content gate plus Approval Register 13/14? *(Unblocks 2.2a/b and real checklist go-live; prerequisite for 2.3 and 2.9c.)*
2. **Which source data will iCretegy supply, and in what format?** IID (the Orange Book is now resolved: public FDA source), the deficiency database, FDA guidance corpus, and a corrected AIDatabase export. *(Unblocks 2.2, 2.5b, and better grounding for 2.6/2.8/2.7.)*
3. **Calculator specifications** (formula, units, rounding, source, owner) for dissolution, impurity and stability trend, plus a yes/no on §2.9 feasibility. *(Unblocks 2.3 and 2.9a/b/c.)*
4. **Word add-in contract:** distribution (AppSource or sideload), authentication (this ties to SSO), and data-handling rules. *(Unblocks 2.7.)*
5. **AI policy:**
   - Which LLM provider and hosting is acceptable for client data?
   - Is a "no training" contract enough, or must it be self-hosted?
   - Does "iPharmaAI UI platform" (2.6b, 2.7) mean the legacy `company_site` or the REGX frontend?

   *(Unblocks the design of 2.6, 2.8, 2.10 and 4.2b.)*

---

## 14. Orange Book progress (SOW 2.5)

Plan: `docs/ORANGE_BOOK_PLAN.md`. White-paper proposal for iCretegy: `docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md`. Both are on branch `regx/feat/orange-book-plan` (commits `aedf6ea`, `6eee2dc`), local, awaiting review.

| Phase | Branch | Status |
|---|---|---|
| 1. Discovery and design | `regx/feat/orange-book-plan` | **Merged:** docs-only PR [#81](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/81) (`eedbf9c`) |
| 1b. Importer fixes | `regx/fix/orange-book-importer` | **Merged:** PR [#80](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/80) (`ab99767`, 2026-10-12) |
| 1c. Release metadata | `regx/feat/fda-release-metadata` | **Merged:** PR [#86](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/86) (2026-10-13) |
| 1d. Terminology review | `regx/docs/terminology-mapping-review` | **PR [#87](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/87) merged 2026-10-13** (the guide; its on-hold note predates the vocabulary decision). Old workbook (2026-10-12, Orange Book terms as codes): routes 44/4/31, forms 99/1/17, units 5/2/45 (exact/likely/unclear). **Superseded 2026-10-13** by the SPL-based workbook `orange_book_terminology_review_spl_2026-10-13.xlsx`: routes 79 = **36 / 9 / 34**, dosage forms 117 = **75 / 10 / 32**, units 52 = **4 / 14 / 34**. Nothing loaded or approved |
| 1e. Vocabulary decision | `regx/docs/terminology-vocabulary-decision` | **Merged** 2026-10-13 08:53 UTC: PR [#88](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/88) |
| 1f. SPL vocabulary loader | `regx/feat/spl-terminology-seed` | **Merged** 2026-10-13 08:53 UTC: PR [#90](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/90). Locally: both releases **active** (121 routes, 158 forms), submitted by sso.doer, approved and activated by sso.vp |
| 1g. IID importer (prerequisite for IIG matching) | `regx/fix/iid-importer` | **Merged** 2026-10-13 08:53 UTC: PR [#89](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/89) |
| 1h. Per-unit / per-day IID check (proposal) | `regx/docs/iid-daily-exposure-rule` | **Merged** 2026-10-13 08:53 UTC: PR [#91](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/91). Pending iCretegy and the regulatory reviewer |
| 1i. Duplicate-import guard | `regx/fix/import-duplicate-guard` | **PR [#92](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/92) MERGED** (`a362e3d`) (`8940539`, `914ba4c`, `89a03ea`: refused duplicate exits 3; head `b0ef387`) |
| 1j. Re-resolve + unmapped-rows guard | `regx/feat/reresolve-terminology` | **PR [#93](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/93) MERGED** (`1beefd1`) (`3caf357`; head `ba70e02`) |
| 1k. IID mapping proposals | `regx/feat/iid-mapping-proposals` | **PR [#94](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/94) MERGED** (`96dce0a`) (`871959d`; head `37e39b7`). Local run: 59 + 105 proposed, `DROPS` stays unmapped (per-record at review) |
| 1l. Loader actor + loader ≠ approver/activator | `regx/feat/loader-actor` | **PR [#97](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/97) open, all CI green** (`db6918d`; conflict with #92 resolved, head `48c701c`; §11 #19c) |
| 2. Load real public data | none (no code; local stack built from the PR #80 branch) | **Done locally 2026-10-12.** Release `6d9fe36b-839d-4ced-8b7c-f3b326243be0` is **active**: 48,761 imported, 0 failed, import 5 min 50 s. Doer validate/submit, VP approve/activate. Counts and 3 lookups verified field by field (0 mismatches). Products only |
| 3. Patents and exclusivity | `regx/feat/orange-book-patents-exclusivity` | Not started (owner: not now). **Waits for:** activated SPL lists → reviewed workbook → approved Orange Book mappings |
| 4. New-data detection | `regx/feat/orange-book-auto-fetch` | Not started. **Reshaped by the openFDA research (plan §2b):** poll `api.fda.gov/download.json` `export_date`, then prompt an operator to upload the ZIP. The fda.gov ZIP download stays manual |
| 5. Lookup page | `regx/feat/orange-book-lookup-page` | Not started |

### Critical path to IIG matching (status 2026-11-05)

What has to be true before `iid_assessment` can match a formulation against real IID data, in order.

| # | Step | Status | Blocked on |
|---|---|---|---|
| 1 | **Vocabulary decided:** FDA SPL lists, `code` = NCI code | **Done.** PR [#88](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/88) merged | — |
| 2 | **IID importer reads the real file** | **Done.** PR [#89](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/89) merged; real July 2026 file active locally (9,071 rows) | — |
| 3 | **SPL route and dosage-form lists loaded and active** | **Done locally.** PR [#90](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/90) merged; both releases active on the dev stack (VP sso.vp approved and activated) | Same steps on any shared environment; once #97 merges, loads need `--actor` and the loader cannot approve/activate |
| 4 | **IID values mapped to the SPL lists** | **Proposed, not approved.** Command in PR [#94](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/94) (open); locally 59 route + 105 dosage-form proposals. `DROPS` (67 records) stays unmapped and is resolved per record at review | Merge #94; 164 mappings × (Reviewer submit + VP approve) = 328 single actions in today's UI; a VP-only "Approve selected" is proposed (§12), not built; regulatory reviewer to confirm the `DROPS` approach |
| 5 | **IID records resolved against the approved mappings** | **Tool built, not run** (PR [#93](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/93), open; duplicate guard PR #92); works only before review. The dev IID release is already active, so it stays unresolved (owner: reset local data later) | Merge #92/#93; then: import a fresh IID release → approve mappings → re-resolve → submit |
| 6 | **Records become calculable** | **Rule proposed** (White Paper Q8, merged in #91): per-unit check when potency exists, per-day check when daily exposure exists. Not built. Potency still needs controlled units (on hold) | iCretegy and reviewer answer on Q8; units PR; INJECTION answer (interim rule; `find_iid_candidates` unchanged) |

Orange Book matching (Phase 3) also needs the reviewed workbook and approved Orange Book mappings.

**Key facts:**
- **Source decision:** public FDA download is primary; no Excel importer.
- **FDA page** (checked live 2026-10-12, content current as of 08/18/2026): one ZIP with `Products.txt` (14 fields), `Patent.txt` (10) and `Exclusivity.txt` (5), tilde-delimited ASCII. No stated ZIP update cadence.
- **Real file verified** (2026-10-12): `EOBZIP_2026_08.zip`, at `D:/Praverse/data/fda/orange-book/2026-10-12/EOBZIP_2026_08.zip`, 1,097,768 bytes, SHA-256 `84e616aacf4f42bb85a94586c10abfc260f8fb9b60f07db3f10315ae70a3298e`. Products 48,761 / patents 22,303 / exclusivity 2,400 rows; ZIP members dated 2026-09-11.
- **An official openFDA Orange Book API exists** (`api.fda.gov/drug/orangebook.json`): products, patents and exclusivity; 48,761 records; matched the ZIP on 3 sample products (only `Type` vocabulary differs). Recommended as a cross-check and change detector, **not** as the source of record (plan §2b).
- **No REGX Celery beat exists.**

---

## Work Log

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

### 2026-11-05 — PRs #92–#95, MFA login bypass fixed, loader actor, kombu drift (Claude Code)

**Session start rule:** deleted `review-handoff/` (not present) and `review-handoff.zip` (present, dated 2026-10-13) without reading them.

**Step 1: housekeeping.**
- **Pushed with PRs into `regx-main` (not merged):** [#92](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/92) `regx/fix/import-duplicate-guard`, [#93](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/93) `regx/feat/reresolve-terminology` (`3caf357`), [#94](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/94) `regx/feat/iid-mapping-proposals` (`871959d`).
- **Duplicate guard, new commit `914ba4c`:** a refused duplicate raises `CommandError(returncode=2)`; errors stay 1. Changed test (on purpose): `backend/fda_data/tests/test_p5_import_readiness.py` `TestFileImportIdempotency::test_importing_the_same_bytes_twice_creates_one_release`; `backend/fda_data/tests/test_duplicate_import_guard.py` asserts 2 for duplicates and 1 for a parse error. PR #92 states the contract change. `fda_data` 298 passed / 1 skipped; ruff clean. Caveat: argparse usage errors also exit 2 (§11 #19b).
- **Deleted the merged branches of #88–#91** locally and on GitHub, each tip first confirmed equal on both sides and an ancestor of `origin/regx-main` (`b55898a`). Recorded in `branch-cleanup/BRANCH_INVENTORY.md` ("Deletion record (2026-11-05)").

**Step 2: MFA login bypass fixed.** Branch `regx/fix/mfa-login-enforcement`, commit `0c02062`, **local, not pushed** (owner: stop with the diff first). Bug fix only; no role forced to enrol. Details in §11 #8.
- `backend/identity/views.py`: for a user with a verified `MFADevice`, the password step answers `{"mfa_required": true, "mfa_pending": true, "email": …}` with no session (ends any existing one) and a 5-minute pending marker. New `POST /auth/login/mfa/` (`backend/identity/urls.py`) grants the session for a valid TOTP (current step ±1, replay refused). Wrong, malformed and replayed codes call `login_lockout.record_failure`; the right password no longer clears the counter for enrolled users.
- Frontend: `frontend/src/app/signin/page.tsx` sends an enrolled user to `/mfa` keeping `?next`; `frontend/src/app/mfa/page.tsx` calls `auth.loginMfa` (`frontend/src/lib/api.ts`); the return-target guard moved to `frontend/src/lib/returnTarget.ts` (also refuses `/mfa`).
- **Tests:** `backend/identity/tests/test_login_mfa.py` (16): password only gives no session; password + code gives a session; wrong and malformed code refused; no pending login; pending expiry; replay; password step ends an existing session; unverified device is not enrolment; lockout from wrong codes, from mixed wrong passwords + codes, not reset by the right password, cleared by a valid code; non-enrolled user unchanged; the two fields company_site reads. `frontend/tests/unit/signin-mfa.test.tsx` (5). Results: `identity` 46 passed; **full backend suite 4,180 passed / 2 skipped, 0 failed**; frontend type-check, lint and vitest (560) pass; ruff clean.
- **Live check** (local stack via nginx `:8080`, two throwaway users `*@check.regx.invalid`, deleted afterwards from REGX and company_site): enrolled, password only: 200 `mfa_pending`, `/auth/me/` 403; plus a valid code: 200 profile, `/auth/me/` 200; 5 wrong codes: 400 ×5, then the right code 429 and the password step 429; code with no pending login: 400 `mfa_not_pending`; non-enrolled: 200 profile + session. Browser: `/signin?next=/documents` to `/mfa?next=/documents` to a session (lands on `/tenants` because the test user has no tenant, `frontend/src/app/(regx)/documents/page.tsx:95`).
- **company_site shared login** (`company_site/AdminMaster/regx_auth.py`): `regx_auth.authenticate()` returns None for the enrolled user ("REGX requires MFA" logged) and provisions the plain user. Through the legacy form the enrolled user sees **"Invalid Credential"** (`company_site/AdminMaster/views.py`); the plain user is redirected to `/ratools/`. Safe; the message is misleading.

**Step 3: loader actor.** Branch `regx/feat/loader-actor`, commit `db6918d`, **local, not pushed**. Details in §11 #19c.
- `--actor <email>` required on `import_fda_release` and `load_spl_terminology`; resolved by `resolve_loader_actor` in `backend/fda_data/permissions.py` (exists, active, holds `fda_data.import` via an active membership of an active tenant). Recorded as `imported_by` and on the `registered` / `import_started` events (`import_started` now also carries `actor_email`, `backend/fda_data/importer.py`).
- `backend/fda_data/lifecycle.py`: `approve` and `activate` refuse the recorded loader (`SeparationOfDutiesError`); the API returns 403 `loader_cannot_approve` / `loader_cannot_activate` (`backend/fda_data/views.py`). Releases without a recorded loader are not blocked.
- **Tests:** `backend/fda_data/tests/test_loader_actor.py`, for both commands: missing, unknown, inactive, no permission (VP, Reviewer, no membership), suspended tenant, recorded on release and audit; approver = loader refused; activator = loader refused; approver ≠ loader accepted; SPL terms go active; API 403s; no recorded loader not blocked. Existing command tests pass `--actor` via `backend/fda_data/tests/_loader.py` (contract change). Results: `fda_data` 315 passed / 1 skipped; **full backend suite 4,187 passed / 2 skipped, 0 failed**; ruff, import-linter (16 kept) and `makemigrations --check` clean.
- **Live (dev DB, nothing written):** missing `--actor`: usage error, exit 2; unknown actor: exit 1 "no user with this email"; `sso.vp@praverse.test` (VP only): exit 1 "does not hold 'fda_data.import'". Same for `load_spl_terminology`.

**Step 4: bulk approval check (read-only).** One mapping at a time, two steps each (Reviewer/VP submit, then a different VP approves); no bulk endpoint, no row selection in the UI (`frontend/src/app/(regx)/fda-data/mappings/page.tsx`, `backend/fda_data/views.py`, `backend/fda_data/mapping_transitions.py`). 164 proposals = 328 actions. Proposal for a VP-only "Approve selected" (one audit event per mapping) and the `DROPS` decision recorded in §12. Nothing built, nothing approved.

**CI failure on #92–#94 and the kombu fix.**
- The compose-stack CI job failed on all three PRs: the Celery worker died with `VersionMismatch` (kombu 5.7.0 needs redis-py ≥ 6.1; we pin 5.2.1). Upstream drift since 2026-10-13; `regx-main` is affected too. §11 #10a.
- First fix was pushed to #94 (`1e0b5eb`) under Auto-fix. **Owner redirected:** the pin now lives in its own PR [#95](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/95) (`regx/fix/pin-kombu`, `796761a`, from `regx-main`, only `backend/requirements/base.txt`). `1e0b5eb` was **dropped from #94 with `git push --force-with-lease`** (lease pinned to `1e0b5eb`; the branch had only our commits and no reviews or comments); #94 is `871959d` only again and its description no longer mentions the pin.
- Verified: a clean image build with the pin resolves kombu 5.6.2 + redis 5.2.1, and a worker started with the compose environment reports `ready`. #92 and #93 were not touched; after #95 merges, #92–#94 get updated from `regx-main`.
- **Follow-up proposal (not built):** lock all backend dependencies with pip-tools lock files and hashes. §11 #10b.

**Not done (per the prompt):** nothing merged; MFA and loader-actor branches not pushed; no mapping approved; no real data re-resolved; no change to which roles must use MFA; bulk approval and dependency locking not built.

**Overview updated:** §11 (#8 MFA bypass status, new #10a kombu drift, new #10b dependency locking, #19b exit code, #19c status), §12 (`DROPS`, bulk-approval finding and proposal, PR status), §13 (2.2b, 4.3b), §14 (rows 1i–1l, critical path).

**Working files:** session scratchpad (outside the repo). Temporary worktrees `D:/Praverse/regx-wt-ci` and `D:/Praverse/regx-wt-pin` were used and removed. Docker Desktop was started for this session; services are stopped at the end.

**Later the same session (owner's follow-up instructions).** These supersede the "not pushed" notes above.
- **#95 reported merged, but it is not:** `gh pr view 95` shows OPEN with no merge commit and `git ls-remote` shows `regx-main` at `b55898a` (checked twice). So **#92, #93 and #94 were not updated from `regx-main`** (there is nothing new to merge); their compose-stack CI job still fails on the kombu crash. To do once #95 is merged: merge `regx-main` into #92–#94, #96 and #97 (no force-push) and report CI.
- **#92 exit code 2 → 3:** commit `89a03ea` (`backend/fda_data/management/commands/import_fda_release.py`, both duplicate tests). Codes: 0 imported, 1 error, 2 usage error (argument parser), 3 refused duplicate. PR #92 description updated with the reason. `fda_data` 298 passed / 1 skipped (run in a throwaway image built from the branch); ruff clean.
- **Pushed with PRs from current `regx-main` (`b55898a`, the branches already started there):** [#96](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/96) `regx/fix/mfa-login-enforcement` (`0c02062`) and [#97](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/97) `regx/feat/loader-actor` (`db6918d`). Each description covers the change, no migration, tests, live checks, and that the compose job fails until #95 merges.
- **`CLAUDE.md` "Hard constraints":** new rule: force-push only with `--force-with-lease` pinned to the known tip, only on a branch that has only our commits and no reviews; never on `regx-main` or `main`.
- **Not done (owner: next session):** the pip-tools dependency lock (§11 #10b).
- **CI at session end:** see the session summary; Auto-fix in the desktop app watches #92–#97.

### 2026-11-05 (second session) — #95 merged, five PRs updated and green (Claude Code)

**Session start rule:** the session resumed mid-task; `review-handoff/` and the zip from the first session are deleted and rebuilt from scratch at the end, not updated.

- **#95 confirmed merged on GitHub before acting** (`regx-main` = `4b942a5`, contains `kombu==5.6.2`).
- **Updated from `regx-main` by a merge commit each, no force-push:** #92 `b0ef387`, #93 `ba70e02`, #94 `37e39b7`, #96 `7d2bea6`, #97 `3ded827`.
- **"Lint, type-check, and test" was not failing.** The owner saw 0/2 (#92, #97) and 0/3 (#96) and read them as failures. GitHub's check-runs API at the previous heads showed: #92 `89a03ea` test job **success** (07:36 UTC); #97 `db6918d` test job **success** (07:32 UTC); #96 `0c02062` test job **still in progress** at that moment and **success** when it finished (07:42 UTC), frontend job success. The only failure on each was the compose-stack job (the kombu crash, §11 #10a). The counter shows passing checks; while one job had failed and the rest were unfinished it read 0. No code was changed for this.
- **#92 renamed** to "fix(fda_data): refuse importing the same FDA file twice (exit 3)".
- **Final CI on the new heads (GitHub check-runs, all `completed/success`; merge state CLEAN):**
  - #92: compose stack ✓, lint/type-check/test ✓
  - #93: compose stack ✓, lint/type-check/test ✓
  - #94: compose stack ✓, lint/type-check/test ✓
  - #96: compose stack ✓, lint/type-check/test ✓, frontend type-check/lint/build/E2E ✓
  - #97: compose stack ✓, lint/type-check/test ✓
- **Not merged.** The owner's merge order is #92 → #93 → #94 → #96 → #97, each only when green, re-checking the next one after each merge. #92, #93 and #97 all change `backend/fda_data/management/commands/import_fda_release.py`, so a conflict is likely once the first of them lands.
- The background CI watcher from the first session stopped when that session ended; the results above were read directly from GitHub afterwards.
- No services were started this session.

### 2026-11-05 (third session) — owner merged #92–#96; #97 conflict resolved (Claude Code)

**Session start rule:** the hand-off from the previous session is deleted and rebuilt from scratch at the end.

- **Owner merged** #92 (`a362e3d`), #93 (`1beefd1`), #94 (`96dce0a`) and #96 (`b6ffe26`) into `regx-main`, in that order.
- **#97 then conflicted** (Auto-fix reported it). Merged the freshly fetched `regx-main` into `regx/feat/loader-actor`; no rebase, no force-push. New head `48c701c`.
  - **Conflict** in `backend/fda_data/management/commands/import_fda_release.py`, resolved keeping both sides: #92's duplicate guard (exit 3, "EXIT CODES" docstring, old "Nothing to do" check removed) and #97's `--actor` (`resolve_loader_actor`, `imported_by=actor`, actor passed to `import_rows`, "loaded by" line).
  - **22 tests broke after the merge without any git conflict.** 21 tests written in #92, #93 and #94 (`backend/fda_data/tests/test_duplicate_import_guard.py`, `backend/fda_data/tests/test_reresolve.py`, `backend/fda_data/tests/test_iid_mapping_proposals.py`) called the command without the now-required `--actor`; they pass it via `backend/fda_data/tests/_loader.py`. One #97 test (`backend/fda_data/tests/test_loader_actor.py`) submitted an IID release with unmapped rows, which #93's guard answers with 409; it now sends `confirm_unmapped`. No assertion weakened; the guard is unchanged.
  - **Results:** `fda_data` 342 passed / 1 skipped; **full backend suite 4,230 passed / 2 skipped, 0 failed**; ruff and import-linter (16 kept) clean.
- **#97 CI at `48c701c`:** compose stack ✓, lint/type-check/test ✓; GitHub merge state CLEAN. Ready for the owner to merge; not merged by Claude Code.
- **Next session:** pip-tools dependency lock (§11 #10b) on its own branch.
- Docker Desktop was started for the tests; services are stopped at the end.

### 2026-11-05 (fourth session) — branch cleanup, pip-tools dependency lock (Claude Code)

**Session start rule:** deleted `review-handoff/` and `review-handoff.zip` without reading them.

**Gate:** confirmed on GitHub that #92–#97 are merged (#92 `a362e3d`, #93 `1beefd1`, #94 `96dce0a`, #95 `4b942a5`, #96 `b6ffe26`, #97 `5a4bc36`); `regx-main` = `5a4bc36`.

**Step 1: branch cleanup.** Deleted the six branches of #92–#97 (including #95's `regx/fix/pin-kombu`) locally and on GitHub, each tip first confirmed equal on both sides and an ancestor of `origin/regx-main`. Recorded in `branch-cleanup/BRANCH_INVENTORY.md` ("Deletion record (2026-11-05, second)"). **Remaining: GitHub `main`, `regx-main`; local the same plus the new `regx/chore/pip-tools-lock`.**

**Step 2: dependency lock (§11 #10b).** Branch `regx/chore/pip-tools-lock` from `regx-main@5a4bc36`, commit `1fc8f52`. After the owner reviewed the diff and results: **pushed, PR [#98](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/98) open, not merged.**
- `backend/requirements/base.in`, `backend/requirements/test.in`, `backend/requirements/dev.in`: the old hand-edited files (renamed with `git mv`), with a header; `test.in` / `dev.in` use `-r` on the input below and `-c` on its lock, so shared packages match across locks.
- `backend/requirements/base.txt` (50 packages), `backend/requirements/test.txt` (59), `backend/requirements/dev.txt` (68): generated by pip-tools 7.4.1 with `--generate-hashes --strip-extras --allow-unsafe`, inside `python:3.12-slim` (Python 3.12.16, pip 25.0.1).
- **Versions kept:** the locks were seeded from `pip freeze` of a fresh `--no-cache` build of `regx-main`; pip-compile keeps versions already in its output. Compared package by package with that image: **0 differences** (50/50 runtime, 68/68 dev). kombu 5.6.2, redis 5.2.1, Django 5.2.18, DRF 3.18.3, pypdf 6.20.0, cryptography 50.0.2, celery 5.4.0. A second run of the script changed nothing.
- `backend/Dockerfile`: `pip install --require-hashes --no-deps -r requirements/base.txt`. `.github/workflows/backend.yml`: CI installs `dev.txt` the same way; new job "Dependency locks match their inputs" runs the script and fails on `git diff`; the workflow now also triggers on changes to itself and to the script.
- `scripts/lock_backend_deps.sh`: one command, Docker; extra arguments go to pip-compile (e.g. `--upgrade-package kombu`). Documented in `CLAUDE.md` "Commands".
- **Proof:**
  - clean `--no-cache` build of backend and celery: hash-checked install succeeded; installed packages identical to the baseline image;
  - stack up: Celery worker logs `Connected to redis://redis:6379/0` and `celery@… ready.`, and `celery inspect ping` answers `pong`;
  - `dev.txt` installed hash-checked into the container (as CI does): success, `pip check` clean, environment identical to the baseline dev install;
  - **full backend suite: 4,230 passed / 2 skipped, 0 failed**;
  - pip-audit (2.9.0) before (`regx-main` requirement files) and after (locks): **identical**, 17 known vulnerabilities in `dev.txt` (16 pypdf 6.20.0, 1 pytest 8.3.5) and 16 in `base.txt` (pypdf).
- **New finding (§11 #10c):** pypdf 6.20.0 (from #79) now has 16 advisories, fixed by 6.21.4; pypdf parses user uploads. Not upgraded here, by instruction.
- **Follow-up logged (§11 #10d):** company_site dependencies are not locked.

**CI on #98 (`1fc8f52`), all green:** "Dependency locks match their inputs" ✓ (on GitHub's Linux runner the script regenerated the locks and `git diff` found no change), lint/type-check/test ✓, compose stack ✓, "Shell syntax, pre-flight checker, restore guards" ✓. Merge state CLEAN.

**pypdf upgrade (§11 #10c): not started.** The owner's gate: start `regx/fix/pypdf-upgrade` only after #98 is merged. At session end #98 is open, so the work stopped here.

**Not done (per the prompt):** no mapping approvals, no re-resolve on real data, no Phase 3; nothing merged.

**Overview updated:** §2 (backend row), §10 (PRs, branches), §11 (#10b status, new #10c pypdf, new #10d company_site lock).

**Working files:** session scratchpad (outside the repo). Images `regx-baseline` (throwaway) and the rebuilt compose images. Services stopped at the end.

### 2026-11-05 (fifth session) — CLAUDE.md and overview tracked (#99), pypdf 6.21.4 (Claude Code)

**Session start rule:** deleted `review-handoff/` and `review-handoff.zip` without reading them.

**Gate:** confirmed on GitHub that #98 is merged (`369b9c3`); deleted its branch `regx/chore/pip-tools-lock` locally and on GitHub (tip in `regx-main`).

**Step 1: track `CLAUDE.md` and `PROJECT_OVERVIEW.md`.** Branch `regx/docs/track-claude-md-and-overview` from `regx-main@369b9c3`, commit `6303a3c`, PR [#99](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/99) (docs only, not merged).
- **Secret scan before committing** (both files): `sk-…` keys (one hit, the words "risk-evaluation-" in a sentence), AWS keys, GitHub tokens, private-key blocks, password/secret/token/api_key assignments with a value, long base64/hex strings (only paths and git SHAs), email addresses (only `admin@praverse.local`, `sso.vp@praverse.test`, `lockcheck@example.invalid`), and the throwaway live-check password of the first session (absent). **Nothing to redact.** Past leaks are described by file and line only. People are named by role or GitHub username, with no contact details.
- `.gitignore` now ignores `/review-handoff/`, `/review-handoff.zip` and `/branch-cleanup/` for every clone (they were only in this clone's `.git/info/exclude`).
- `CLAUDE.md`: notes that both files are tracked, so a Work Log entry or rule change is a commit (session branch, or a small docs PR); the hand-off rule points at `.gitignore`.
- **Working-copy note:** on `regx-main` (until #99 merges) both files are still untracked in this checkout. Overview updates from later sessions are pushed to the #99 branch too, so the PR stays current.

**Step 2: pypdf upgrade (§11 #10c).** Branch `regx/fix/pypdf-upgrade` from `regx-main@369b9c3`, commit `9421302`. After the owner reviewed the diff and results: **pushed, PR [#100](https://github.com/Praverse-Tech-Pvt-Ltd/RegX/pull/100) open, not merged.**
- `backend/requirements/base.in`: `pypdf==6.20.0` → `pypdf==6.21.4` (newest release; the highest fix version among the 16 advisories is 6.21.4). Ran `scripts/lock_backend_deps.sh`.
- **Every version change in the locks** (`backend/requirements/base.txt`, `test.txt`, `dev.txt`): pypdf 6.20.0 → 6.21.4 in each; **nothing else** changed (no version, no hash). pypdf has no runtime dependencies on Python 3.12, so none were added. Re-running the script changes nothing, so the CI lock check passes.
- **pytest not included:** its fix (PYSEC-2026-1845) is 9.0.3, a major upgrade from 8.3.5, not a patch.
- **pip-audit 2.9.0 (`--require-hashes`):** `base.txt` before 16 (pypdf) → after **0**; `dev.txt` before 17 → after 1 (pytest 8.3.5 only).
- **Clean `--no-cache` build** of backend and celery: hash-checked install; installed set equals the pre-upgrade baseline except pypdf 6.21.4. Worker: `Connected to redis://redis:6379/0`, `celery@… ready.`, `inspect ping` → pong; both containers import pypdf 6.21.4.
- **Live PDF check** (local stack via nginx `:8080`, User-Agent `REGX-dev-research`): a 5-page PDF with known text per page (embedded TrueType font, page 4 in two columns; made with matplotlib from the repo `.venv`), uploaded through `POST /api/regx/v1/documents/` by a throwaway `tenant_admin` in a throwaway tenant, before (images with pypdf 6.20.0) and after (6.21.4). Both: 201, scan `clean`, processing `complete`, 5 page locators (`Page 1`–`Page 5`, `page_number` 1–5), every expected line found on its page. **Extracted text identical page by page** (5/5; 159/104/114/111/50 characters). Page 4 reads row by row across the two columns in both versions. The throwaway tenant, its 2 documents and the user were deleted afterwards.
- `backend/documents/tasks.py` (`_process_pdf`) is the code path exercised: `pypdf.PdfReader`, one page locator per page with `extract_text()`.
- **Full backend suite: 4,230 passed / 2 skipped, 0 failed.**

**Step 3: real-world PDF check.** The two public FDA PDFs were not in `D:/Praverse/data/test-pdfs/` (the folder does not exist; no PDFs under `D:/Praverse/data`). **Owner: skip the real PDFs.** The scanned-document question was answered instead with a generated 2-page image-only PDF (text drawn as pixels; pypdf reads 0 characters and 2 images per page), uploaded through the documents API on the pypdf 6.21.4 stack:
  - pages detected 2; characters per page 0 / 0; first 200 characters of pages 1 and 2: empty;
  - final status: scan `clean`, processing **`complete`**, `failure_code` empty, processing job `success`;
  - audit events: `document.version.created`, `document.scan.queued`, `document.scan.complete`, `document.processing.started`, `document.processing.complete`; no event, field, flag or log line says no text was extracted (the only celery warning is the stub scanner's);
  - findings and a proposal (not built) added to §11 #15; OCR left as an owner decision.
  - Throwaway tenant, its documents and user deleted afterwards (both live checks).

**Not done (per the prompt):** nothing merged; no mapping approvals, no re-resolve, no Phase 3.

**Overview updated:** §2 (backend row), §10 (PRs), §11 (#10b merged, #10c PR #100, #15 empty-text extraction).

**Working files:** session scratchpad (outside the repo). Services stopped at the end.
