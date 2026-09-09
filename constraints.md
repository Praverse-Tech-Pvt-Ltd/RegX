# Constraints — REGX (`regx-main`)

What must not change without asking first. Read this before proposing anything.

These are not style preferences. Each one is here because breaking it either
costs money, weakens a security guarantee, or destroys data that cannot be
regenerated from this repository.

> The `main` branch has its own `constraints.md`. It describes the legacy
> iPharmaAI monolith and **does not apply here**. The two branches share no git
> ancestor.

---

## Security

**Do not weaken `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, or any setting in
`backend/regx/settings/production.py` to make something work.**
This came up directly: the shared sign-in needed a session cookie back over a
plain-HTTP internal hop, and `requests` correctly refused to send it. The fix
was to re-present that one cookie on that one hop, in the client. Turning the
flag off would have been two characters and would have applied to every browser
session in production.

**Do not give a mirrored `CustomUser` a usable local password.**
`company_site/AdminMaster/regx_auth.py` calls `set_unusable_password()` on every
account it provisions. That is the single line making REGX genuinely
authoritative for those identities. If it goes, the local password check becomes
a second, unmonitored door into a REGX account.

**Do not remove the `mfa_required` refusal in the company login** without
replacing it with something at least as strict. The company login page collects
a password and nothing else; admitting an account that enrolled in MFA would
make it the weaker of two doors into the same identity.

**Do not treat `identity.User` as modifiable.** Phase 15 puts the REGX identity
model off-limits without prior approval. The shared sign-in was deliberately
built so that it changes only `company_site` code plus one additive read-only
endpoint in `authorization` — nothing in `identity`.

**Do not commit secrets.** `.env` holds four generated values
(`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `MFA_ENCRYPTION_KEY`,
`COMPANY_SECRET_KEY`) and is gitignored. The demo credentials in `handoff.md`
are for a local database only and must not be created anywhere deployed.

**The hardcoded OpenAI key in the legacy `AIDatabase/filters.py` stays as-is.**
The owner was told and chose to leave it. Do not rotate or remove it on your own
initiative; do not propose it again.

---

## Cost

**Never start a server and hit a route without knowing what that route does.**
A single `GET /` on the legacy app triggered **71 paid OpenAI calls** in one
session. Observation summaries are now gated behind
`ENABLE_OBSERVATION_SUMMARIES`, default off. Leave it off unless you are
deliberately testing that path, and know what a request will cost before you
make it.

---

## Data

**Back up `db.sqlite3` before running `add_missing_columns.py`.** It is additive
and re-running is safe, but it is still a schema change against the only copy of
the company's data on this machine.

**Do not re-run destructive importers casually.**
`import_inspections` calls `.objects.all().delete()` before `bulk_create`. It
replaces rather than merges.

**Do not normalise the deficiency classification vocabulary silently.** There
are 76 distinct `deficiency_type` spellings, including near-duplicates differing
only by whitespace. Cleaning that up is a governance exercise with an approval
trail, not a tidy-up during a port.

---

## Architecture

**Keep the REGX tech stack as it is.** Legacy patterns get converted to REGX
conventions; they do not get imported wholesale. Specifically: no CKEditor
`RichTextField` (React renders here), no in-process pandas DataFrames with
`.pkl` snapshots (they do not survive multiple gunicorn workers), no
Django-admin-shaped features.

**Do not share a session cookie between the two Django applications.** They sign
with different `SECRET_KEY`s over different session stores. Making them agree
means weakening one side's configuration to match the other. Only the credential
check is shared.

**Do not try to split the admin surface out of `company_site` again.** It was
attempted three times and failed three times — the whole prefix broke login, a
narrowed version 404'd the admin landing page, and the narrowed version then
404'd every console link. **The admin surface is not a separable subtree of this
application.** The working arrangement serves the whole app on both listeners
and has 8080 refuse the handful of user-management routes.

**Reference corpora are platform-level, not tenant-scoped.** Published FDA
material follows `fda_data.FDADataSourceRelease`: every tenant reads the same
rows and none can edit them. Do not add a tenant FK to one of these.

---

## Process

**Never report a test result without checking the harness first.** A full-suite
run against the wrong settings module produced seven failures that read as real
bugs, and six more from a file the image does not contain. Eleven of fourteen
failures were the environment. Before concluding anything from red output,
confirm `-e DJANGO_SETTINGS_MODULE=regx.settings.test`, the `/docs` mount, and
that no other pytest run is holding `test_regx`.

**Do not edit a passing test to make a red line go away.** The documentation
tests were failing on a path the image lacked; the fix was to mount the
directory, not to loosen the test's path resolution or let it skip. A guard
that is quietly disabled is worse than one that is loudly failing.

**A 200 is not a passing test.** Two bugs this session returned HTTP 200
throughout: a dropped report-type filter that bled data across reports, and a
facets endpoint returning 7,458 rows instead of the distinct set. Check the
*content* of a response, not its status.

**A permission bug that denies is invisible to a smoke test.** A permission
class read `request.tenant`, which does not exist, so every endpoint returned
403 while looking like correct fail-closed behaviour. Always verify that a
legitimate request *succeeds*, not only that a bad one fails.

**Show the real diff, not a summary of it.** Nobody should have to trust a prose
description of what changed.

**One logical change per request.** If a request is broad ("fix auth"), break it
down and confirm the breakdown before starting.
