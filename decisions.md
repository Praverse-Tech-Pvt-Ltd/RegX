# Decisions — REGX (`regx-main`)

Each entry: what was decided, what the alternative was, why this one won.
Newest first. Model tag noted because this project spans sessions and models.

> The `main` branch has its own `decisions.md` covering the legacy monolith.
> Different codebase, no shared git ancestor, does not apply here.

---

## 2026-09-09 — One sign-in, by delegation rather than shared identity

*Claude Opus 5*

**Decided:** the company login posts its credentials to REGX's auth API and
mirrors the returned identity into a local `CustomUser`. REGX is the sole
authority on who a person is and what their password is.

**Alternatives:**

1. *Map `AdminMaster.CustomUser` onto `identity.User`* — one user model. Rejected:
   changes the REGX identity model, which Phase 15 puts off-limits without prior
   approval, and would have to reconcile two incompatible key schemes (username
   vs email) across live data.
2. *An OIDC/SAML provider in front of both* — the textbook answer, and what
   `docs/COMPANY_SITE_AUTH_INTEGRATION.md` originally sketched. Rejected for
   now: it is a new piece of deployed infrastructure to answer a question that
   an HTTP call already answers. Still the right end state; recorded as the
   remaining step.
3. *Share a session cookie* — rejected outright. The two apps sign with different
   `SECRET_KEY`s over different session stores; making one cookie work in both
   means weakening one side's configuration.

**Why this won:** it touches no REGX identity code, ships as one new file plus a
four-line change to an existing view, and is reversible by setting
`REGX_AUTH_URL` blank.

---

## 2026-09-09 — Mirrored accounts get an unusable local password

*Claude Opus 5*

**Decided:** every provisioned `CustomUser` is saved with
`set_unusable_password()`.

**Alternative:** store the password locally too, so the app works if REGX is
down.

**Why this won:** a stored local password is a second, unmonitored door into a
REGX identity — it would survive a REGX password change or a disabled account.
Availability during an outage is handled instead by the local-check fallback,
which only reaches accounts REGX never knew about. Those two together give
availability without giving a mirrored account a bypass.

---

## 2026-09-09 — The local password check stays, as a fallback

*Claude Opus 5*

**Decided:** if REGX rejects the credentials or is unreachable, fall through to
the ordinary Django check.

**Alternative:** delegate exclusively — no local check at all.

**Why this won:** the Django superuser and every pre-existing company account
are unknown to REGX, and a REGX outage would otherwise lock out accounts this
application can still verify perfectly well on its own. It is not a bypass,
because of the decision above: a mirrored account has no usable local password,
so the fallback can never succeed for one.

**Tradeoff accepted:** this is not *strictly* single sign-on. Two credential
sets can still exist for pre-existing accounts. That is the price of not
locking anyone out during the transition.

---

## 2026-09-09 — Added `GET /api/regx/v1/permissions/mine/`

*Claude Opus 5*

**Decided:** a new read-only endpoint returning the caller's own role names.

**Alternatives:** infer the role from `/permissions/effective/`; or add role
data to the login response.

**Why this won:** `/permissions/roles/` says which roles exist and
`/permissions/effective/` says what the caller may do — neither answers "which
role am I", and reverse-engineering it from a permission set breaks the moment
a role's permissions are edited. Adding fields to the login response would mean
touching the `identity` serializer and changing REGX's public auth contract for
one consumer's benefit. The new endpoint lives in `authorization`, is scoped to
`request.user`, and discloses nothing the caller could not already infer.

---

## 2026-09-09 — Re-present the session cookie instead of turning off `SESSION_COOKIE_SECURE`

*Claude Opus 5*

**Decided:** after login, the shim re-sets the `sessionid` value in its own
cookie jar without the Secure flag, so the follow-up role request is
authenticated.

**Alternative:** set `SESSION_COOKIE_SECURE = False`, or add a dev-only
override.

**Why this won:** the flag exists to stop a *browser* leaking a cookie onto a
channel the server never chose. Here a server replays, on the one internal hop
it already used, a cookie it received over that same hop moments earlier — no
new channel is involved. Clearing the flag would have been simpler and would
have applied to every browser session in production.

**How it surfaced:** the role lookup returned 403 and every account mapped to
the default role, so a `tenant_admin` landed on `/ratools/` instead of the admin
console. Worth knowing because the symptom looked like a role-mapping bug, not
an auth one.

---

## 2026-09-09 — MFA: refuse rather than admit, and leave REGX's gap alone

*Claude Opus 5*

**Decided:** the company login refuses any account REGX reports as
`mfa_required`. The absent enforcement on the REGX side is documented, not
fixed.

**Alternative:** admit them (parity with REGX, which does not enforce MFA
anywhere), or wire enforcement into REGX's permission layer.

**Why this won:** the company login collects a password and nothing else, so
admitting an enrolled account would make it the weaker of two doors into the
same identity. Being stricter than REGX is the right direction to err in.
Fixing REGX's enforcement is a genuine change to the security model and belongs
to whoever owns that decision, not to a sign-in integration.

**Finding, recorded plainly:** `identity.User.mfa_required` is set on enrolment
and **never read**. No permission class or middleware gates anything on it. No
protected operation in REGX requires MFA today.

---

## 2026-09-08 — Legacy `ANDA` and `MajorCR` collapsed into one model

*Claude Opus 5*

**Decided:** one `DeficiencyRecord` with a `corpus` discriminator.

**Alternative:** mirror the legacy pair.

**Why this won:** the two were structurally identical — same five
classification columns, same body — differing only in which roadmap the row
came from. Two identical tables would have doubled every query, serializer and
permission check for no gain.

---

## 2026-09-08 — Reference corpora are platform-level, not tenant-scoped

*Claude Opus 5*

**Decided:** deficiencies, 483s, warning letters and published guidance carry no
tenant FK.

**Alternative:** scope them per tenant like operational data.

**Why this won:** it is published FDA material — the same category as
`fda_data.FDADataSourceRelease`, which is already platform-level. Every tenant
reads the same corpus and none can edit it. Tenant work product
(`CorrespondenceDraft`) is scoped normally; the split runs along ownership.

---

## 2026-09-08 — Classification vocabulary left as free text

*Claude Opus 5*

**Decided:** no controlled vocabulary on `deficiency_type` and friends.

**Alternative:** normalise during import.

**Why this won:** 76 distinct spellings including near-duplicates differing only
by whitespace. Choosing which of two spellings is canonical is a regulatory
judgement that needs an approval trail. Doing it silently inside a data
migration hides it from exactly the people who should decide.

---

## 2026-09-08 — Gap analysis rebuilt rather than ported

*Claude Opus 5*

**Decided:** rebuilt on the `iig_checklist` engine, computed on demand, no model
and no migration.

**Alternative:** port the legacy implementation.

**Why this won:** the legacy version scores 2 of 6 checklist families and is
tied to models that are not being brought across. Porting it would have meant
importing its dependencies too, to get a worse result.

---

## 2026-09-08 — 483 data stored in the database, not in DataFrames

*Claude Opus 5*

**Decided:** database-backed models.

**Alternative:** keep the legacy design.

**Why this won:** the legacy app serves this from in-process pandas DataFrames
with `.pkl` snapshots. That does not survive multiple gunicorn workers — each
worker holds its own copy and they drift.

---

## 2026-09-08 — Trailing slash made optional by middleware, not by editing routes

*Claude Opus 5*

**Decided:** `SlashToleranceMiddleware` redirects a 404 to the other slash form
when that one resolves.

**Alternative:** rewrite the URLs so they are consistent.

**Why this won:** consistency would mean editing 188 route definitions and 128
template links in a codebase with no test coverage, where one missed link
becomes exactly the 404 the change was meant to remove. The middleware can only
turn a 404 into a working page — it cannot create one. Only GET and HEAD are
redirected; a redirected POST would lose or replay its body.

---

## 2026-09-08 — The admin surface is not split out

*Claude Opus 5*

**Decided:** serve the whole application on both listeners; 8080 refuses the
handful of user-management routes.

**Alternative:** a genuine subtree split, attempted three times.

**Why this won:** it is the only arrangement that works. Splitting the whole
`/adminmaster/` prefix broke login; narrowing it 404'd the admin landing page;
the narrowed version then 404'd every console link. **The admin surface is not a
separable subtree of this application** — its routes are interleaved with the
ones ordinary users need.
