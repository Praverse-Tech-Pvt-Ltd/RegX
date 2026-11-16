# Development Guide

Getting REGX running from a clean clone. Every step below was executed against a
fresh checkout; the notes marked **Gotcha** are failures that actually occurred,
not hypotheticals.

## Requirements

- Python 3.12+
- Node.js 22+
- Rancher Desktop or Docker Desktop, **with the daemon running**
- PostgreSQL 16 — supplied by compose, not installed locally

> **SQLite is not supported.** `.env.example` says so and the settings enforce
> it. There is no local-development shortcut around Postgres.

---

## Quick start (Docker, full stack)

```bash
cp .env.example .env          # then fill in the four required secrets, below
docker compose up --build -d
docker compose exec backend python manage.py migrate
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/api/docs/ |
| company_site | http://localhost:8001 |
| nginx | http://localhost:8080 |

**Gotcha — migrations do not run on start.** `docker compose up` reports every
service `healthy` against a completely empty schema, because `/readiness/` checks
that it can *connect* to Postgres, not that any table exists. Without the
`migrate` line above, the first query fails with
`relation "authorization_role" does not exist`. Run it explicitly on any fresh
volume.

**Gotcha — backend source is baked into the image, not mounted.** Editing a
Python file has no effect until you rebuild:

```bash
docker compose build backend celery && docker compose up -d backend celery
```

---

## The four required secrets

`compose.yaml` guards these with `:?`, so `docker compose config` fails and names
any one that is missing. Placeholder values are rejected — a placeholder secret is
worse than a missing one, because it starts successfully.

| Variable | Generate with |
|---|---|
| `DJANGO_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `POSTGRES_PASSWORD` | `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `MFA_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `COMPANY_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |

`MFA_ENCRYPTION_KEY` must be a valid Fernet key — urlsafe-base64 of exactly 32
bytes. An arbitrary random string will pass `check_env.py` and fail at runtime.

### Validating

```bash
python scripts/check_env.py
```

**Gotcha — this reads `os.environ`, not `.env`.** Running it straight after
`cp .env.example .env` reports all four variables missing on a perfectly correct
setup. Either export them into the shell first, or rely on
`docker compose config`, which reads `.env` and applies the same guards.

---

## Backend only (no compose)

Postgres and Redis still have to come from somewhere — usually
`docker compose up -d postgres redis`.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt

python manage.py migrate
python manage.py runserver
```

Supply `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` yourself when
running outside compose — compose normally provides them.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Creating a first login

There is no `createsuperuser` path that produces a usable account on its own: the
API is tenant-scoped, so a user also needs a tenant, an active membership and at
least one role. Roles and permissions are seeded by migration (5 roles, 58
permissions); tenants and users are not.

```python
# docker compose exec -T backend python manage.py shell
from django.db import transaction
from identity.models import User
from tenancy.models import Tenant, TenantMembership
from authorization.models import Role, MembershipRole

with transaction.atomic():
    tenant, _ = Tenant.objects.get_or_create(slug="acme", defaults={"name": "Acme"})
    user, _ = User.objects.get_or_create(email="admin@acme.test",
                                         defaults={"full_name": "Admin", "is_staff": True})
    user.set_password("<choose-one>")
    user.save()
    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user,
                                                           defaults={"is_active": True})
    for name in ("tenant_admin", "doer", "reviewer", "vp"):
        MembershipRole.objects.get_or_create(membership=membership,
                                             role=Role.objects.get(name=name))
```

**Gotcha — tenant-scoped endpoints need a header.** A valid session is not
enough. `TenantMiddleware` resolves the tenant from `X-Tenant-Slug`, and without
it every domain endpoint returns 403 — which is indistinguishable from a
permissions problem:

```bash
curl -b cookies -H 'X-Tenant-Slug: acme' \
  http://localhost:8000/api/regx/v1/iig-checklists/definitions/
```

---

## Signing in: one account, two applications

The compose stack runs two Django applications. REGX is the platform;
`company_site/` is the legacy monolith, carried across intact and served by
nginx on ports 8080 and 8090.

**They share one set of credentials.** The company login does not check
passwords itself — it posts them to `POST /api/regx/v1/auth/login/` and mirrors
the returned identity into a local `CustomUser`. The account you created above
therefore works in both places:

| | Sign in at |
|---|---|
| REGX frontend | http://localhost:3000/signin |
| Legacy tools | http://localhost:8080/adminmaster/login/ |
| Legacy admin console | http://localhost:8090/adminmaster/login/ |

Your REGX role decides what the legacy side gives you: `tenant_admin` and
`platform_support` become its `admin`, `doer` becomes `company_user`,
`reviewer` and `vp` become `company_checker`.

Sessions are **not** shared — each application issues its own cookie over its
own session store. Only the credential check is shared. `REGX_AUTH_URL` in
`compose.yaml` controls this; blank turns the delegation off and the company
login falls back to checking passwords locally.

Full detail, including why this is an API call rather than a shared cookie:
[COMPANY_SITE_AUTH_INTEGRATION.md](COMPANY_SITE_AUTH_INTEGRATION.md).

---

## Tests

```bash
cd backend
pytest
```

Under compose, the runtime image does not ship test tooling:

```bash
docker compose exec --user root backend pip install -r requirements/dev.txt
docker compose exec backend python -m pytest -q --no-cov
```

**Gotcha — `--no-cov` is not optional there.** `/app` is read-only for the app
user, so `coverage` cannot write its data file and raises `INTERNALERROR:
DataError: Couldn't use data file ...` *after* the tests have already passed. The
pass/fail line above it is the real result.

## Lint

```bash
cd backend
ruff check .
ruff format --check .
lint-imports
```

---

## Windows / Git Bash

**Gotcha — Git Bash rewrites absolute paths before Docker sees them.** A command
like:

```bash
docker compose exec backend python manage.py import_deficiencies --sqlite /tmp/data.sqlite3
```

arrives inside the container as
`C:/Users/<you>/AppData/Local/Temp/data.sqlite3` and fails with
`unable to open database file`, while the same path read via `python -c` works —
which makes it look like a permissions problem rather than a path problem. Prefix
the command:

```bash
MSYS_NO_PATHCONV=1 docker compose exec backend python manage.py import_deficiencies --sqlite /tmp/data.sqlite3
```

---

## A note on this repository

The repo contains **two unrelated codebases with no common git ancestor**:

| Branch | What it is |
|---|---|
| `regx-main` | **REGX** — this platform. Backend + frontend + compose |
| `main` | Legacy iPharmaAI Django monolith (`RATools`, `AIDatabase`, `AdminMaster`) |

`regx-main` has been the repository default branch since 2026-11-16, so a plain
`git clone` lands on REGX. Before that it was `main`, the legacy app, whose UI is
served on port 8000 — the same port REGX uses for its API. Opening `:8000` and getting a 404, or finding routes such as
`/ratools/...` missing, usually means the wrong branch is checked out rather
than a broken install.

`SETUP.md`, `constraints.md`, `decisions.md` and `handoff.md` on `main` describe
that legacy application and do not apply here.

## Read next

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System map |
| [DEPLOYMENT_BOUNDARIES.md](DEPLOYMENT_BOUNDARIES.md) | Which variables compose supplies vs. which you must set |
| [SECURITY_BASELINE.md](SECURITY_BASELINE.md) | Security posture |
| [SOW_SECTION_2_STATUS.md](SOW_SECTION_2_STATUS.md) | SOW section 2 progress against this codebase |
| [ROADMAP.md](ROADMAP.md) | Milestone history and scope boundaries |
| [COMPANY_SITE_AUTH_INTEGRATION.md](COMPANY_SITE_AUTH_INTEGRATION.md) | The shared sign-in, in detail |

Working on this branch specifically, in the repository root:

| Document | Contents |
|---|---|
| `test-checklist.md` | Every verification command with its expected output. Run this first. |
| `handoff.md` | Where things stand: done, open, broken, and what to avoid |
| `constraints.md` | What must not change without asking |
| `decisions.md` | Why each non-obvious choice was made |
| `ROUTES.md` | Every company_site URL, with its exact trailing slash and port |
