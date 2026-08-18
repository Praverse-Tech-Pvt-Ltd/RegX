# Deployment Boundaries

The environment contract, reconstructed from the code and `compose.yaml` rather
than from prior documentation.

Verified against `regx-main` `6452afe7a1632acd16f7b53c22583f2fcf4ba863`.

> **Correction.** An earlier version of this document listed `DATABASE_URL` as a
> required secret. **Nothing reads it.** The backend reads `DB_NAME`, `DB_USER`,
> `DB_PASSWORD`, `DB_HOST` and `DB_PORT` (`regx/settings/base.py`). The same
> version also omitted `POSTGRES_PASSWORD` and `COMPANY_SECRET_KEY`, both of
> which are hard-required by compose — so a first deployment following it failed
> at `docker compose build`, before any container started.

---

## 1. Environments

| Environment | Settings module | Notes |
|---|---|---|
| Development | `regx.settings.development` | `DEBUG=True`, relaxed CSP |
| Test (CI) | `regx.settings.test` | in-memory cache, eager Celery, test DB |
| Production | `regx.settings.production` | strict CSP, HTTPS-only cookies |
| Company site | `RAAI.settings_integration` | the copied company Django app; own DB, own session cookie |

---

## 2. Hard-required — no default, must be supplied

These four are guarded in `compose.yaml` with `:?`. Compose **refuses to
interpolate** without them, so the stack fails at `config`/`build` time with the
variable named — before anything starts.

| Variable | Service | Secret | Phase | Purpose |
|---|---|:-:|---|---|
| `DJANGO_SECRET_KEY` | backend, celery | **SECRET** | runtime | RegX Django signing key |
| `POSTGRES_PASSWORD` | postgres, backend, celery | **SECRET** | runtime | PostgreSQL superuser password; also supplied to the apps as `DB_PASSWORD` |
| `MFA_ENCRYPTION_KEY` | backend, celery | **SECRET** | runtime | Fernet key encrypting MFA secrets at rest. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `COMPANY_SECRET_KEY` | company_site | **SECRET** | runtime | The company app's own Django signing key, passed to it as `SECRET_KEY` |

**Nothing else is required to bring the stack up.** Verified: with only these
four set and no `.env` file, `docker compose config` succeeds; with none set it
fails naming `DJANGO_SECRET_KEY`.

### `POSTGRES_PASSWORD` and `DB_PASSWORD` are the same credential

They are **one secret with two names**, and only `POSTGRES_PASSWORD` is
settable:

- `postgres` receives it as `POSTGRES_PASSWORD` — the password the server is
  created with;
- `backend` and `celery` receive it as `DB_PASSWORD: ${POSTGRES_PASSWORD}` — the
  password the apps connect with.

Setting `DB_PASSWORD` in your environment has **no effect** under compose; the
mapping is fixed in the file. Running the backend *outside* compose is the only
case where `DB_PASSWORD` is set directly.

### `COMPANY_SECRET_KEY` contract

Compose-required (`:?`). It reaches the container as `SECRET_KEY`, which
`RAAI/settings.py` reads through `config("SECRET_KEY")`. It is deliberately
**separate from `DJANGO_SECRET_KEY`**: the two applications sign their own
sessions independently, which is what keeps their auth domains distinct.

`DEBUG` defaults to `False` in `settings_integration.py` and compose sets it to
`"False"` explicitly. It does not affect whether the key is required.

---

## 3. Optional — safe defaults, override per environment

| Variable | Service | Secret | Phase | Default | Purpose |
|---|---|:-:|---|---|---|
| `INTEGRATED_APP_URL` | frontend | no | **build + runtime** | `http://localhost:8080` | The origin the browser calls. Becomes `NEXT_PUBLIC_API_URL` |
| `COMPANY_BASE_URL` | company_site | no | runtime | `http://localhost:8080` | Read by a context processor on every company render; **has no code default**, so compose must supply one |
| `COMPANY_SERVER_MODE` | company_site | no | runtime | `LOCAL` | `SERVER` in the company app. `PRODUCTION` enables its device-token second step |

### Backend variables compose sets internally

Not deployment inputs under compose — listed so the contract is complete, and
because they **are** required when running the backend outside compose.

| Variable | Default | Compose value | Secret |
|---|---|---|:-:|
| `DB_NAME` | `regx` | `regx` | no |
| `DB_USER` | `regx` | `regx` | no |
| `DB_PASSWORD` | `""` | `${POSTGRES_PASSWORD}` | **SECRET** |
| `DB_HOST` | `localhost` | `postgres` | no |
| `DB_PORT` | `5432` | `5432` | no |
| `REDIS_URL` | `redis://localhost:6379/0` | `redis://redis:6379/0` | no |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | `localhost,127.0.0.1,backend` | no |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | `http://localhost:3000,http://localhost:8080` | no |
| `DJANGO_SETTINGS_MODULE` | — | `regx.settings.production` | no |

### Read by settings, not set by compose

All have defaults; set them only to change behaviour.

`DEBUG` (`False`) · `APP_ENVIRONMENT` (`development`) · `APP_VERSION` (`0.1.0`) ·
`CSRF_TRUSTED_ORIGINS` (`http://localhost:3000`) · `CELERY_TASK_ALWAYS_EAGER`
(`False`) · `DOCUMENT_STORAGE_BACKEND` (`local`) · `DOCUMENT_SCANNER_BACKEND`
(`stub`) · `DOCUMENT_CLAMAV_HOST` (`127.0.0.1`) · `DOCUMENT_CLAMAV_PORT`
(`3310`) · `DOCUMENT_MAX_UPLOAD_BYTES` (50 MB)

**`DOCUMENT_SCANNER_BACKEND` defaults to `stub`.** A production deployment that
accepts uploads must set a real scanner; the stub does not scan.

---

## 4. Browser-visible — never secret

| Variable | Phase | Why it cannot be secret |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | **build-time and runtime** | Next.js inlines every `NEXT_PUBLIC_*` value into the client bundle. It is served to every visitor. |

It is a **build arg as well as runtime env**, because inlining happens at build
time: setting it only at runtime leaves whatever was baked into the image. That
mismatch was a real defect during the site integration — the bundle kept calling
`:8000` cross-origin while compose said `:8080`.

Never put a credential in a `NEXT_PUBLIC_*` variable.

---

## 5. Company site — its own template

`company_site/.env.example` is the **company application's** template, carried
in with their code. It names `EMAIL_HOST_PASSWORD`, `AZURE_CLIENT_SECRET` and
other credentials belonging to features this deployment does not enable
(SMTP mail, Microsoft Graph booking mail). Under compose the company service
receives only the nine variables in §2–§3; the rest stay unset and those
features stay dormant.

Do not populate them without deciding you intend those features to run.

---

## 6. Outstanding credential rotation — NOT CONFIRMED

Carried forward from an earlier security pass. Neither is engineering-actionable
and no value is reproduced anywhere in this repository.

| Item | Status |
|---|---|
| Three historical OpenAI project keys found in the copied company code | **NOT CONFIRMED** — require provider-side revocation |
| Historical SMTP password found in the copied company code | **NOT CONFIRMED** — requires a provider-side change |

They were removed from this repository and purged from branch history before
first publication. **That does not invalidate them** — they remain in the
company's own read-only source, which is untouched.

Also outstanding: the **GitHub Support purge** of superseded objects from the
PR #22 force-push. **NOT CONFIRMED.**

---

## 7. First deployment

```bash
cp .env.example .env      # then replace every change-me value
docker compose config     # fails naming any missing hard-required variable
docker compose up -d
```

Open **http://localhost:8080** — the single origin. Not `:3000`, not `:8000`.

`scripts/check_env.py` validates the hard-required set before starting, and
rejects placeholder values:

```bash
python scripts/check_env.py
```

---

## 8. Production checklist

- [ ] `DEBUG=False` (default, but assert it)
- [ ] `SESSION_COOKIE_SECURE=True`
- [ ] `CSRF_COOKIE_SECURE=True`
- [ ] `ALLOWED_HOSTS` set to exact domains — not the compose defaults
- [ ] `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` set to real origins
- [ ] All four hard-required secrets generated fresh, never reused across environments
- [ ] `INTEGRATED_APP_URL` set to the real public origin **before building the frontend image** — it is inlined at build time
- [ ] `DOCUMENT_SCANNER_BACKEND` set to a real scanner if uploads are enabled
- [ ] PostgreSQL TLS enabled
- [ ] Redis AUTH enabled
- [ ] No `unsafe-eval` in `script-src`. Note the shipped CSP does use
      `script-src 'self' 'unsafe-inline'` — the reasoning is recorded in
      `frontend/next.config.ts`
- [ ] Backup and restore rehearsed for `postgres_data`, `document_storage` and
      `company_db` — procedure and scripts now exist, see
      `BACKUP_RESTORE_DR.md`. RPO, RTO, retention, off-site storage and
      backup encryption remain **PENDING BUSINESS / QA / IT APPROVAL**
- [ ] Operational log destination and retention agreed — the application logs
      structured JSON to stdout and configures no aggregation, see
      `OPERATIONAL_LOGGING.md`. Aggregation is **PENDING IT / OPERATIONS
      DECISION** and retention **PENDING QA / IT / SECURITY APPROVAL**
- [ ] `docker compose ps` reports all seven services healthy — every service now
      carries a healthcheck, see `SERVICE_HEALTH.md`. Note that per-container
      health is not an end-to-end guarantee, and that nginx must be restarted
      after any upstream container is recreated

---

## 9. What this document is not

It records the environment contract only. It is **not** a validated production
deployment: what has been verified here is `docker compose config` and image
build with dummy non-secret values, not a production rollout.
