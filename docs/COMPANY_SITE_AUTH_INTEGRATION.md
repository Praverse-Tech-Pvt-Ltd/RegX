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

## The journey from a company page into a REGX module

Improved in the pre-push hardening pass, without touching the auth model.

A visitor on a company page who clicks into a REGX module while holding no
REGX session is bounced to `/signin` — that part was already true. What
changed is that the bounce now carries where they were going:

```
/migration-batches?tenant=alpha
  → /signin?next=%2Fmigration-batches%3Ftenant%3Dalpha
  → (sign in)
  → /migration-batches?tenant=alpha
```

Previously every sign-in landed on `/tenants` regardless of intent, which
left the user to find their way back manually.

`next` is attacker-controllable, so `safeReturnTarget()` in
`frontend/src/app/signin/page.tsx` accepts only same-origin absolute paths. It
rejects anything not starting with `/`, anything starting with `//` or `/\`
(browsers treat both as protocol-relative and would leave the origin), and
`/signin` itself so the flow cannot loop. Anything rejected falls back to
`/tenants` — the previous behaviour. Five E2E cases cover this, including
three hostile targets.

No redirect loop exists in either direction: the company site's login is a
plain Django view that never consults REGX, and the REGX pages never redirect
to the company login.

Note that pages are inconsistent about which status triggers the bounce —
some use 401, some 403. That predates this work and was left alone.

## One sign-in, delegated to REGX

A user signs in once, with their REGX email and password, at either
`/adminmaster/login/` or `/signin`. The company login no longer checks the
password itself: it posts the submitted credentials to REGX's auth API
(`POST /api/regx/v1/auth/login/`), and on success looks up or creates the
`AdminMaster.CustomUser` that mirrors that REGX identity. REGX stays the sole
authority on who a person is and what their password is.

This replaces the two-login arrangement that was recorded here as the honest
cost of the first integration pass. What it does *not* do is share a session:
each application still issues its own cookie over its own session store, for
the reason given below.

### How the pieces fit

| | |
|---|---|
| Credential check | REGX `identity.User`, over the internal network |
| Company session | This application's own cookie, unchanged |
| Local `CustomUser` | A mirror, created on first sign-in, keyed on the REGX email |
| Local password | Set unusable, so it can never be an alternative way in |
| Roles | Read from `GET /api/regx/v1/permissions/mine/` and mapped |

`REGX_AUTH_URL` (see `compose.yaml`) turns this on and points at the backend
container. Set it blank and the login reverts to checking passwords locally,
which is exactly the behaviour this application had before.

### Role mapping

REGX's role model is the richer of the two, so the mapping collapses it:

| REGX role | Legacy role | Why |
|---|---|---|
| `tenant_admin` | `admin` | Administers users on both sides |
| `platform_support` | `admin` | Praverse staff; needs the admin console |
| `doer` | `company_user` | Prepares work |
| `reviewer` | `company_checker` | Reviews work |
| `vp` | `company_checker` | Approves work but does not administer users |

A REGX identity holding several roles gets the most privileged result. A role
this application has no equivalent for — including any added to REGX later —
falls back to `company_user`, the least privileged of the three.

The mirrored account also gets an `AssignChecker` row. That is not cosmetic:
several RATools views call `AssignChecker.objects.get(user=...)` unguarded and
return 500 without one.

`GET /api/regx/v1/permissions/mine/` was added for this. Neither
`/permissions/roles/` (which roles exist) nor `/permissions/effective/` (what
the caller may do) answers "which role am I", and inferring it back from a
permission set breaks the moment a role's permissions are edited.

### What is deliberately still separate

**Sessions.** The two Django apps sign with different `SECRET_KEY`s over
different session stores, and making one cookie work in both would mean
weakening one side's configuration to match the other. Only the credential
check is shared; each application issues its own session as it always did.

**The local password check**, which remains as a fallback for the accounts
REGX does not know — the Django superuser and any pre-existing company
account — and for the case where REGX is unreachable, so an outage does not
lock out the accounts this application can still verify on its own. It cannot
be used to get around REGX: mirrored accounts are saved with an unusable
password, so the local check can never succeed for one.

**MFA.** If REGX reports `mfa_required` for an account, the company login
refuses it rather than granting a session. That page collects a password and
nothing else, and letting it through would make it the weaker of the two doors
into the same identity.

Worth knowing, and out of scope here: `mfa_required` is set when a user
enrols, but nothing in REGX currently *checks* it — there is no permission
class or middleware gating protected operations on it. The refusal above is
therefore stricter than REGX itself is today, which is the right direction for
it to err in, but the enforcement gap on the REGX side is real and unfixed.

### If this is taken further

The remaining step, for whoever picks it up, is an OIDC/SAML provider in front
of both applications, which would remove the password from this application's
hands entirely rather than merely forwarding it. The delegation above is a
smaller change that does not touch `identity.User`, which Phase 15 puts
off-limits without prior approval.
