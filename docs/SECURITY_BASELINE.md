# Security Baseline

## Authentication

- Email-based login via Django `authenticate()`.
- Session authentication only; JWT is not used.
- Sessions use secure HttpOnly cookies (`SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE=Lax`).
- Auth tokens are NEVER stored in localStorage or sessionStorage.

## CSRF

- Django CSRF middleware is active.
- The frontend fetches a CSRF token from `/api/regx/v1/auth/csrf/` and sends it as `X-CSRFToken` on all write requests.
- `CORS_ALLOWED_ORIGINS` is an explicit allowlist; `CORS_ALLOW_ALL_ORIGINS=False`.

## Content Security Policy

Production `script-src` does not include `unsafe-eval` or `unsafe-inline`.  
`frame-ancestors 'none'` — REGX pages cannot be embedded in iframes.  
`object-src 'none'` — no plugins.

## API identifiers

Internal BIGINT primary keys are never returned in API responses.  
All public identifiers use UUID `public_id`.

## MFA encryption

TOTP secrets are encrypted at rest with Fernet. The encryption key is a required env var with no insecure default.

## Prohibited patterns (enforced by guards in CI)

- `AIDatabase` import anywhere in REGX code
- SQLite engine in any settings file
- `unsafe-eval` in production CSP
- Hardcoded `SECRET_KEY` or `MFA_ENCRYPTION_KEY` defaults
- Auth token in localStorage/sessionStorage
