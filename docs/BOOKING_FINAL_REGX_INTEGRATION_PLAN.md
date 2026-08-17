# Booking-Final → REGX Integration Plan

Status: approved architecture, implementation in progress
Branch: `regx/feat/company-site-integration`
Base commit: `d2b80d45e1d993a2bff11a08fb4f819f3a158359`

## 1. Scope and hard boundaries

| Role | Absolute path |
| --- | --- |
| Company source (READ-ONLY) | `C:\Users\devp0\OneDrive\Documents\NEX\RegX\Booking final\booking-demo-final` |
| REGX destination (only project modified) | `C:\Users\devp0\OneDrive\Documents\NEX\RegX\RegX` |

The company source is not a git repository, so "unmodified" is proven with a
SHA-256 inventory of all 1764 non-`__pycache__`, non-`.venv` files taken before
any work started and re-run at the end. Nothing is ever written to that tree;
even the route-inventory extractor parses `urls.py`/`views.py` as **text** so
that no `__pycache__` is produced there.

## 2. What each project actually is

### Company project — `booking-demo-final`

| Property | Value |
| --- | --- |
| Framework | Django 5.1.3 (monolith, server-rendered) |
| Settings module | `RAAI.settings`, `ROOT_URLCONF = RAAI.urls` |
| Apps | `RATools`, `AIDatabase`, `AdminMaster` (+ contrib) |
| Templates | Django templates, `DIRS = [BASE_DIR/"templates"]`, `APP_DIRS=True`, 110 files |
| Context processor | `AIDatabase.context_processors.base_url` |
| Auth | Django session auth, `AUTH_USER_MODEL = AdminMaster.CustomUser`, login at `/adminmaster/login/` |
| Database | SQLite `db.sqlite3` (7.4 MB, real FDA-483 content) |
| Static | `STATIC_URL=/static/`, `STATICFILES_DIRS=[BASE_DIR/static]` — **486 MB** |
| Media | `MEDIA_URL=/media/` — **199 MB** |
| CSS/JS | Bootstrap 5, Material Design Icons, Themify, Font Awesome, `assets/css/style.css` (743 KB), Lenis (CDN), Three.js r128 (CDN) |
| Integrations | Microsoft Graph mail, SMTP, Celery + Redis (demo-reminder beat), CKEditor, DRF + Token auth |
| Startup | `python manage.py runserver` / gunicorn `RAAI.wsgi` |
| Routes | 347 total (RATools 167, AIDatabase 96, AdminMaster 84); 217 `@login_required` |

Critically, the company **homepage `/` is data-driven** — `RATools.views.home`
computes total observations and distinct company counts from the cached FDA-483
dataframes. Audit IQ, the investigator/warning-letter dashboards and all 217
gated legacy tools are likewise backed by `db.sqlite3`. None of these can be
reproduced without carrying the company application and its data.

### REGX project — destination

| Property | Value |
| --- | --- |
| Git remote | `https://github.com/Praverse-Tech-Pvt-Ltd/RegX.git` |
| Starting branch | `regx/feat/milestone-5a-p1-content-engine-prerequisites` (3 commits ahead of `origin/regx-main`, 0 behind — newest authoritative code) |
| Starting SHA | `d2b80d45e1d993a2bff11a08fb4f819f3a158359` |
| Working tree | clean at branch creation |
| Backend | Django + DRF, **API-only** (`/api/regx/v1/`), no templates/HTML |
| Backend auth | Session auth (`SessionAuthentication`), `AUTH_USER_MODEL = identity.User`, cache-backed sessions in Redis, MFA via Fernet (`MFA_ENCRYPTION_KEY`) |
| Backend apps | `identity`, `tenancy`, `authorization`, `audit`, `workflows`, `documents`, `document_storage`, `templates_registry`, `fda_data`, `formulations`, `iid_assessment`, `iig_checklist`, `common` |
| Frontend | Next.js 15.1 App Router, React 19, 34 routes, **no design system** (`globals.css` is 2 lines, one shared component) |
| Database | PostgreSQL 16 (SQLite explicitly unsupported) |
| Cache/broker | Redis 7 |
| Containers | `compose.yaml`: postgres, redis, backend, celery, frontend + `postgres_data`, `document_storage` volumes |

The REGX frontend has **no shell at all** today — no navbar, no sidebar, no
theme. Adding the company shell is therefore purely additive to the frontend
and requires no rewrite of existing page logic.

## 3. Chosen architecture — Option C (hybrid), site-led

**The company Django application is carried into the REGX project verbatim and
run as its own container. The REGX Next.js frontend keeps serving the new
operational modules, restyled into the original `/ratools/` shell. A single
nginx front door unifies both on one origin.**

```
                       ┌────────────── nginx :8080 (single origin) ──────────────┐
                       │                                                          │
  /  /ratools/ ────────┤ company_site :8000  (Django 5.1.3, SQLite, verbatim)     │
  /aidatabase/ ...     │   → company homepage, Audit IQ, legacy RATools tools,    │
  /adminmaster/ ...    │     /static/ (486 MB), /media/ (199 MB), company login   │
  /static/ /media/     │                                                          │
                       │                                                          │
  /documents  /fda-data│ frontend :3000     (Next.js 15, REGX operational UI      │
  /formulations ...    │   → wrapped in the ported RAToolsBase shell)             │
                       │                                                          │
  /api/regx/v1/ ───────┤ backend :8000      (REGX DRF API — authoritative for     │
                       │   identity, MFA, tenancy, permissions, audit)            │
                       └──────────────────────────────────────────────────────────┘
```

Routing rule: **default → company Django**; an explicit allow-list of REGX
operational prefixes → Next.js; `/api/regx/v1/` → REGX backend.

### Why this option

1. **Maximum visual fidelity, by construction.** The company site is not
   reproduced — it *is* the company code, running. Navbar, footer, colors,
   typography, spacing, images, GIFs, CSS, responsive behaviour and hover
   states are bit-identical because they are the same files. Design drift is
   structurally impossible for the company surface.
2. **The DB-driven pages keep working.** The homepage stat counters, Audit IQ,
   investigator dashboards, warning letters and the 217 gated legacy tools run
   against the real SQLite content. No fabricated data, no dead links.
3. **Minimum rewrite.** Zero of the 110 company templates and zero of the 14 733
   lines of `RATools/views.py` are ported by hand. Zero of the 34 existing
   Next.js pages change their data logic.
4. **Minimum regression risk to REGX.** The REGX backend is not touched at all —
   no models, migrations, permissions, calculations, resolver semantics, audit
   or export logic change. The frontend change is additive (a layout + styles).
5. **Docker fits the existing shape.** The repo already runs a multi-service
   Compose stack; adding two services follows the established pattern and
   requires no manual Docker Desktop work.

### Rejected alternatives

- **Option A — port the REGX operational app into the company Django templates.**
  Rejected: would require rewriting all 34 Next.js pages (documents, FDA data,
  formulations, IID, checklist execution, overrides, reviewer conclusions,
  controlled export) as Django templates against a different user model and a
  different database. Enormous rewrite of tested, working code, and it would
  dissolve the deliberate API boundary documented in `LEGACY_BOUNDARY.md` and
  `DEPLOYMENT_BOUNDARIES.md`.
- **Option B — reproduce the whole company website in Next.js.** Rejected: 110
  templates including a 3 942-line homepage would have to be hand-ported, and
  the data-driven pages could not work at all without the company database.
  High effort *and* a visibly degraded company site — the worst of both.
- **Option C, frontend-led (shell-only port, no company service).** Considered
  and rejected with the user: it avoids dual sessions and a second container,
  but the homepage would lose its real FDA statistics and Audit IQ plus the
  legacy tools would have to ship disabled. It fails the primary success
  criterion ("the user sees the same company website they were given").

### Accepted costs

- ~685 MB of company `static/` + `media/` is copied into the repository. The
  user explicitly accepted duplication across both folders. No individual file
  exceeds 50 MB, so no GitHub per-file limit is hit.
- Two session systems coexist (see §6). This is unavoidable given two distinct
  `AUTH_USER_MODEL`s over two databases, and is mitigated rather than hidden.

## 4. Destination layout

```
RegX/RegX/
├── backend/                 unchanged (REGX API)
├── frontend/                Next.js — gains the company shell + RegX layout
│   └── src/app/(regx)/...   operational routes wrapped in the RAToolsBase shell
├── company_site/            NEW — company Django app, copied verbatim
│   ├── RAAI/ RATools/ AdminMaster/ AIDatabase/
│   ├── templates/ static/ media/ db.sqlite3 manage.py requirements.txt
│   └── Dockerfile           NEW (only file authored here)
├── infra/nginx/nginx.conf   NEW — single-origin front door
├── compose.yaml             + company_site, + nginx services
└── docs/BOOKING_FINAL_REGX_INTEGRATION_PLAN.md
```

Adaptations applied to the **copy** (never to the source), kept to the minimum:

| Change | Reason |
| --- | --- |
| `SESSION_COOKIE_NAME = "company_sessionid"`, `CSRF_COOKIE_NAME = "company_csrftoken"` | Both apps are Django and both default to `sessionid`/`csrftoken`. On one shared origin they would overwrite each other. Renaming the **company copy's** cookies leaves the REGX backend byte-identical (Phase 15). |
| `CELERY_BROKER_URL`/`RESULT_BACKEND` read from `REDIS_URL` env | The hard-coded `redis://127.0.0.1:6379/0` cannot resolve inside a container. |
| `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` via env | Required to serve behind nginx. |
| `Dockerfile` added | The company project has none; it is a new file, not an edit. |

Company markup, CSS, templates, views, models, migrations and static assets are
copied unchanged.

## 5. Route map

Authoritative split (full 347-row company table in
`docs/COMPANY_ROUTE_INVENTORY.md`):

| Category | Owner | Paths |
| --- | --- | --- |
| Company public | company_site | `/`, `/about-alpesh/`, `/termsofuse/`, `/privacy-policy/` |
| Company demo/contact | company_site | `/ratools/requestdemo`, `/ratools/contactus`, `/ratools/requestdemo/**` |
| Company Audit IQ + databases | company_site | `/aidatabase/**` (96 routes) |
| Company auth + admin | company_site | `/adminmaster/**` (84 routes), `/admin/` |
| Legacy RATools tools | company_site | `/ratools/**` (167 routes) incl. the `/ratools/` RegX landing |
| Company assets | company_site | `/static/**`, `/media/**` |
| **REGX documents** | frontend | `/documents`, `/documents/[publicId]` |
| **REGX FDA data** | frontend | `/fda-data/**` (releases, mappings, orange-book, reconciliation) |
| **REGX formulations** | frontend | `/formulations/**` |
| **REGX IID** | frontend | `/iid-assessments/**` |
| **REGX IIG checklists** | frontend | `/iig-checklists/**` (definitions, versions, executions) |
| **REGX migration** | frontend | `/migration-batches/**` |
| **REGX templates** | frontend | `/templates/**`, `/template-sources` |
| **REGX auth** | frontend + backend | `/signin`, `/mfa` |
| **REGX tenant admin** | frontend | `/tenants` |
| REGX API | backend | `/api/regx/v1/**`, `/api/schema/`, `/api/docs/` |

The existing Next.js route paths are **kept as-is** rather than moved under
`/ratools/regx/`. Moving them would touch every page, every link and every
existing E2E test for no functional gain; none of them collide with a company
path. The `/ratools/` *shell* is what Phase 7 mandates, and that is applied to
them via the layout.

## 6. Auth and session plan

- **Company session** — cookie `company_sessionid`, `AdminMaster.CustomUser`,
  SQLite, DB-backed sessions. Governs the company marketing pages and the 217
  gated legacy tools. Login at `/adminmaster/login/`.
- **REGX session** — cookie `sessionid` (unchanged), `identity.User`, Postgres,
  Redis-backed sessions, MFA, tenancy, capability gating. Governs **every**
  protected REGX operation. Login at `/signin`, MFA at `/mfa`.

REGX auth remains authoritative and unchanged: every operational page calls
`/api/regx/v1/**`, which continues to enforce session + MFA + tenant scope +
permissions exactly as it does today. Nothing is bypassed, weakened, or
short-circuited; no MFA step is skipped; tenant selection is untouched.

Two logins is the honest consequence of two distinct user models over two
databases. It is **not** hidden: the RegX area's shell shows REGX identity and
tenant state, and unauthenticated access to an operational route redirects to
`/signin` as it does today. Unifying the two into real SSO would require
changing the REGX identity model, which Phase 15 forbids without approval, so
it is recorded here as follow-up work rather than attempted now.

## 7. Docker impact

Existing services (postgres, redis, backend, celery, frontend) and both volumes
are unchanged; no volume is deleted; nothing is created by hand in Docker
Desktop. Two services are added:

- `company_site` — builds `./company_site`, gunicorn on 8000, mounts a named
  volume for its SQLite database so the copied data survives rebuilds.
- `nginx` — the single origin on `:8080`, routing per §5.

`docker compose config` is run to prove the merged file is valid.

## 8. Migration impact

None. No REGX migration is added, altered or removed. The company app ships
with its own already-applied SQLite database and its migrations are not re-run
against REGX Postgres — the two datastores stay entirely separate.

## 9. Implementation sequence

1. Integration plan + route inventory (this document).
2. Company site copied into `company_site/` + Dockerfile + nginx + compose.
3. The original `/ratools/` shell ported into the Next.js frontend.
4. Operational modules re-parented into the shell; sidebar/route wiring.
5. Auth/session integration and documentation.
6. Accessibility/responsive fixes.
7. Tests and evidence.

## 10. Key risks

| Risk | Mitigation |
| --- | --- |
| Session/CSRF cookie collision on one origin | Company copy uses renamed cookies; REGX backend untouched. |
| Repository size (~685 MB) | Verified: no file > 50 MB, so no GitHub per-file limit. Push left to the user's decision. |
| Company site expects `APPEND_SLASH = False` and mixes slashed/unslashed paths | nginx proxies paths verbatim; no rewriting of company URLs. |
| Shell port drifting from `RAToolsBase.html` | The frontend loads the **same** company CSS from `/static/` on the same origin and reuses the same class names and CSS variables, rather than re-authoring styles. |
| Legacy tools duplicating new REGX modules (e.g. IIG) | Both are surfaced and clearly labelled; no legacy link is removed and no new link claims unimplemented behaviour. |
| Company Celery beat competing with REGX celery | The company worker is **not** started; only its web service runs. Demo-reminder scheduling is out of scope for this integration. |

## 11. Rollback strategy

All work is on `regx/feat/company-site-integration`, committed in seven logical
commits, never squashed and never auto-merged. Rollback is
`git checkout regx/feat/milestone-5a-p1-content-engine-prerequisites` (or
deleting the branch); the REGX backend and Postgres volumes are untouched, so
nothing to unwind at the data layer. Dropping just the company surface is
`docker compose stop company_site nginx` plus reverting the compose commit —
the REGX stack then runs exactly as it does today on ports 3000/8000.
