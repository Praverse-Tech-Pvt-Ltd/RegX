# Authentication and Sessions After the Company-Site Integration

Companion to `BOOKING_FINAL_REGX_INTEGRATION_PLAN.md`. This is the exact
description Phase 11 asks for: what authenticates what, which cookie carries
which session, and what is *not* changed.

## Summary

Two independent authentication systems coexist on one origin. This is a
consequence of the two applications having different user models over
different databases, not a design preference. REGX authentication is
unchanged and remains authoritative for every protected REGX operation.

| | Company site | REGX |
| --- | --- | --- |
| User model | `AdminMaster.CustomUser` | `identity.User` |
| Database | SQLite (`company_db` volume) | PostgreSQL |
| Session store | database-backed | Redis (`SESSION_ENGINE=cache`) |
| Session cookie | `company_sessionid` | `sessionid` (unchanged) |
| CSRF cookie | `company_csrftoken` | `csrftoken` (unchanged) |
| Login entry point | `/adminmaster/login/` | `/signin` |
| Second factor | none | MFA (`/mfa`, Fernet-encrypted secrets) |
| Tenancy | none | tenant scoping via `X-Tenant-Slug` |
| Governs | 217 gated legacy tools, company marketing pages | all REGX modules |

## Why the cookies are renamed

Both applications are Django and both default to `sessionid` and `csrftoken`.
Before the integration they lived on different origins, so the collision never
mattered. Behind one nginx origin, whichever app responded last would
overwrite the other's cookie, silently logging the user out of the other
application — and, worse, sending a session identifier issued by one app to
the other on every request.

The **company copy** is the side that was renamed
(`company_site/RAAI/settings_integration.py`), specifically so that the REGX
backend's authentication configuration stays byte-identical. Nothing in
`backend/regx/settings/` was touched.

## What governs a REGX operational page

Unchanged from before the integration:

1. The page is served by Next.js (`/documents`, `/iig-checklists/...`, etc.).
2. Its data comes from `/api/regx/v1/...`, which is the REGX DRF backend.
3. That API enforces, exactly as it did before:
   - `SessionAuthentication` against the REGX `sessionid` cookie;
   - MFA state, where the endpoint requires it;
   - tenant scope from the `X-Tenant-Slug` header;
   - capability/permission checks;
   - audit and `expected_version` concurrency semantics.

A company-site login grants **nothing** in REGX. `company_sessionid` is not
read by the REGX backend, is not accepted as authentication, and carries no
REGX authority. The converse also holds: a REGX session grants nothing on the
company site.

No MFA step is skipped, no tenant selection is bypassed, and no permission
check is relaxed anywhere in this integration.

## Same-origin consequences that *are* improvements

With nginx in front, the browser calls `/api/regx/v1/...` on the same origin
as the page. That means:

- no cross-origin preflight on API calls;
- the frontend CSP's `connect-src 'self'` covers the API;
- `SESSION_COOKIE_SAMESITE=Lax` is no longer working against a cross-site
  request, so the session cookie is sent on ordinary navigations as intended.

`CORS_ALLOWED_ORIGINS` is left in place for the standalone `:3000` development
and Playwright setups, which still cross origins.

## The honest cost: two logins

A user who works with both the legacy company tools and the new REGX modules
signs in twice — once at `/adminmaster/login/`, once at `/signin`. This is
visible, not hidden: unauthenticated access to a REGX operational route
redirects to `/signin` exactly as it does today, and the company tools
redirect to the company login exactly as they do today.

Unifying them into real single sign-on would mean either mapping
`AdminMaster.CustomUser` onto `identity.User` or introducing a shared identity
provider. Both change the REGX identity model, which Phase 15 puts off-limits
without prior approval, and both risk weakening the MFA/tenancy guarantees
that the REGX side exists to enforce. It is therefore recorded here as
follow-up work rather than attempted as part of a visual integration.

### If SSO is pursued later

The lowest-risk sketch, for whoever picks this up: keep `identity.User`
authoritative, add an OIDC/SAML provider in front of both applications, and
reduce the company site's login to a thin shim that trusts the provider.
Do not attempt to share a session cookie between the two Django apps — they
sign with different `SECRET_KEY`s over different session stores, and making
them agree would mean weakening one side's configuration to match the other.
