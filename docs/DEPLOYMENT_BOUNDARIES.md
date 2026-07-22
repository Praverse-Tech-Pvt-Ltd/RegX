# Deployment Boundaries

## Environments

| Environment | Settings module | Notes |
|---|---|---|
| Development | `regx.settings.development` | DEBUG=True, relaxed CSP |
| Test (CI) | `regx.settings.test` | In-memory cache, eager Celery, test DB |
| Production | `regx.settings.production` | Strict CSP, HTTPS-only cookies |

## Required secrets (all environments)

- `DJANGO_SECRET_KEY` — no default allowed
- `DATABASE_URL` — PostgreSQL only
- `MFA_ENCRYPTION_KEY` — Fernet key, no default allowed

## Production checklist

- [ ] `DEBUG=False`
- [ ] `SESSION_COOKIE_SECURE=True`
- [ ] `CSRF_COOKIE_SECURE=True`
- [ ] `ALLOWED_HOSTS` set to exact domains
- [ ] No `unsafe-eval` in script-src
- [ ] PostgreSQL TLS enabled
- [ ] Redis AUTH enabled
