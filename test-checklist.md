# Test Checklist — REGX

Written to be run top to bottom by someone who has not seen this code. Every
command here was executed on 2026-09-09 and the expected output is what it
actually printed, not what it ought to print.

**Branch:** `regx/feat/legacy-port-and-sso`. **Platform:** Windows + Git Bash +
Docker. On Windows, `MSYS_NO_PATHCONV=1` in front of `docker compose exec` is
not optional — see §0.

---

## 0. Three things that will waste your afternoon

Read these before running anything.

1. **Source is baked into the images.** Editing a `.py` file changes nothing
   until you `docker compose build <service> && docker compose up -d <service>`.
   There is no volume mount for application code.

2. **After recreating any container, restart nginx.** It caches upstream
   container IPs at startup. A recreated backend or company_site will serve
   **404 through nginx while answering 200 directly**, which reads exactly like
   a broken route. `docker compose restart nginx`.

3. **`MSYS_NO_PATHCONV=1` on every `docker compose exec`.** Git Bash rewrites
   `/app/foo` into `C:/Users/.../foo` before Docker sees it. The failure looks
   like a missing file inside the container.

---

## 1. Stack comes up

```bash
docker compose up -d
docker compose ps --format "{{.Service}} {{.State}}"
```

Expect all seven running:

```
backend running
celery running
company_site running
frontend running
nginx running
postgres running
redis running
```

**Migrations do not run on start.** Healthy ≠ migrated — `readiness` only checks
connectivity. If this is a fresh database:

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T backend python manage.py migrate
```

```bash
curl -s http://localhost:8000/api/regx/v1/health/
```

```
{"status":"ok"}
```

---

## 2. Shared sign-in — the main change of this session

One email and password must work in **both** applications. This is the part
most worth breaking on purpose.

### 2.1 Sign in to REGX directly

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Content-Type: application/json" \
  -d '{"email":"sso.doer@praverse.test","password":"RegxSso2026"}' \
  http://localhost:8000/api/regx/v1/auth/login/
```

Expect `200`.

### 2.2 The same credentials on the legacy login

```bash
J=$(mktemp)
CSRF=$(curl -s -c "$J" http://localhost:8080/adminmaster/login/ \
  | grep -o 'csrfmiddlewaretoken" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
curl -s -b "$J" -c "$J" -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  -X POST http://localhost:8080/adminmaster/login/ \
  -e http://localhost:8080/adminmaster/login/ \
  --data-urlencode "csrfmiddlewaretoken=$CSRF" \
  --data-urlencode "username=sso.doer@praverse.test" \
  --data-urlencode "password=RegxSso2026"
rm -f "$J"
```

Expect `302 http://localhost:8080/ratools/`.

### 2.3 Role mapping lands each account in the right place

Repeat 2.2 for each. The redirect target **is** the assertion — it is decided by
the role REGX reported.

| Account (password `RegxSso2026`) | REGX role | Expected redirect |
|---|---|---|
| `sso.admin@praverse.test` | `tenant_admin` | `/adminmaster/adminbase` |
| `sso.doer@praverse.test` | `doer` | `/ratools/` |
| `sso.vp@praverse.test` | `vp` | `/ratools/` |

An admin landing on `/ratools/` means the role lookup silently returned nothing
and everyone fell back to `company_user`. That is the failure mode this session
already hit once — see `decisions.md`, the session-cookie entry.

### 2.4 Confirm what was actually provisioned

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T company_site python -c "
import django,os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','RAAI.settings_integration'); django.setup()
from AdminMaster.models import CustomUser, AssignChecker
for u in CustomUser.objects.filter(username__startswith='sso.').order_by('username'):
    print('%-28s role=%-16s staff=%-5s usable_pw=%-5s reports=%d' % (
        u.username, u.role, u.is_staff, u.has_usable_password(),
        len(AssignChecker.objects.get(user=u).assigned_report)))
" 2>&1 | grep sso
```

```
sso.admin@praverse.test      role=admin            staff=True  usable_pw=False reports=72
sso.doer@praverse.test       role=company_user     staff=False usable_pw=False reports=72
sso.vp@praverse.test         role=company_checker  staff=False usable_pw=False reports=72
```

Three assertions in that output:

- **`usable_pw=False`** — the mirrored account has no local password, so the
  local fallback cannot become a second way into a REGX identity. If this ever
  reads `True`, the delegation has a hole in it.
- **`reports=72`** — the `AssignChecker` row exists. Without it several RATools
  views return 500, because they call `AssignChecker.objects.get(user=...)`
  unguarded.
- **`staff`** is True only for the mapped admin.

### 2.5 Negative cases — these must all be refused

Run 2.2's block with each of these. Expect **`200`** (the login page
re-rendered) containing `Invalid Credential`, **not** a 302.

| Case | Username | Password |
|---|---|---|
| Wrong password | `sso.doer@praverse.test` | `WrongPassword1` |
| Unknown user | `nobody@praverse.test` | `RegxSso2026` |
| Mirrored account, local password | `sso.admin@praverse.test` | anything |

The third is the important one. It proves REGX is genuinely the only authority
for a mirrored identity.

### 2.6 Legacy accounts still work through the fallback

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T company_site python create_demo_users.py
```

```
  regx_admin     role=admin            reports=72 staff=True
  regx_user      role=company_user     reports=72 staff=False
  regx_checker   role=company_checker  reports=72 staff=False
```

Re-run this rather than trusting the passwords in the file — they drifted from
the database once already. Then run 2.2 with `regx_admin` / `RegxAdmin#2026`
and expect `302 .../adminmaster/adminbase`.

### 2.7 A REGX outage must not lock everyone out

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T company_site python -c "
import django,os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','RAAI.settings_integration'); django.setup()
from django.test import override_settings
from AdminMaster import regx_auth, views
with override_settings(REGX_AUTH_URL='http://nonexistent-host:9999'):
    try:
        regx_auth.authenticate('x','y'); print('FAIL: no exception')
    except regx_auth.RegxUnavailable: print('outage raises RegxUnavailable: ok')
    u = views._authenticate('regx_admin','RegxAdmin#2026')
    print('outage fallback to local:', 'ok' if u and u.username=='regx_admin' else 'FAIL')
with override_settings(REGX_AUTH_URL=''):
    print('disabled returns None:', 'ok' if regx_auth.authenticate('a','b') is None else 'FAIL')
    print('disabled local login:', 'ok' if views._authenticate('regx_user','RegxUser#2026') else 'FAIL')
print('role map:', regx_auth._legacy_role(['doer','tenant_admin']),
                   regx_auth._legacy_role(['vp']),
                   regx_auth._legacy_role([]),
                   regx_auth._legacy_role(['unknown_future_role']))
" 2>&1 | grep -Ev "Warning|warn|BROKER"
```

```
outage raises RegxUnavailable: ok
outage fallback to local: ok
disabled returns None: ok
disabled local login: ok
role map: admin company_checker company_user company_user
```

The `role map` line reads: most privileged role wins; `vp` is a checker; no
roles and an unrecognised role both fall back to the least privileged.

A `RegxUnavailable` log line appears between them. That is the code reporting
the outage, not a failure.

### 2.8 Known gap — do not mistake this for a bug you introduced

**REGX sets `mfa_required` and never checks it.** No permission class or
middleware gates any protected operation on MFA today:

```bash
grep -rn "mfa_required" backend --include=*.py | grep -v migrations
```

Four hits: the model field, the serializer, and the two lines in
`mfa_verify_view` that set it. **Nothing reads it to make a decision.**

The company login refuses an `mfa_required` account outright, which makes it
stricter than REGX itself. That is deliberate; the gap on the REGX side is
recorded in `handoff.md` §6 as a decision someone still has to make.

---

## 3. REGX API

Get an authenticated session once and reuse it:

```bash
J=$(mktemp)
curl -s -c "$J" http://localhost:8000/api/regx/v1/auth/csrf/ > /dev/null
TOK=$(grep csrftoken "$J" | awk '{print $7}')
curl -s -b "$J" -c "$J" -H "X-CSRFToken: $TOK" -H "Content-Type: application/json" \
  -d '{"email":"sso.doer@praverse.test","password":"RegxSso2026"}' \
  http://localhost:8000/api/regx/v1/auth/login/ -o /dev/null -w "login %{http_code}\n"
```

Expect `login 200`. Then:

```bash
curl -s -b "$J" http://localhost:8000/api/regx/v1/permissions/mine/
```

```
{"roles":["doer"]}
```

```bash
curl -s -b "$J" -H "X-Tenant-Slug: praverse-demo" \
  "http://localhost:8000/api/regx/v1/deficiencies/?page_size=1" | head -c 120
```

Expect `{"count":7458,...`.

**Tenant isolation — both directions.** Omitting `X-Tenant-Slug` on a
tenant-scoped endpoint must be refused, not silently served:

```bash
curl -s -o /dev/null -w "no tenant header: %{http_code}\n" \
  -b "$J" http://localhost:8000/api/regx/v1/controlled-correspondence/drafts/
curl -s -o /dev/null -w "anonymous: %{http_code}\n" \
  http://localhost:8000/api/regx/v1/deficiencies/
rm -f "$J"
```

Both should be `403`. **A permission bug that denies is invisible to a smoke
test** — this session shipped one for a while. Always check that a *legitimate*
request succeeds too, not only that a bad one fails.

---

## 4. Ported data is present

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -c "
import django,os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','regx.settings.production'); django.setup()
from deficiencies.models import DeficiencyRecord
from inspections.models import Form483Inspection, Form483Observation, WarningLetter
from controlled_correspondence.models import BestPractice
print('deficiencies     ', DeficiencyRecord.objects.count())
print('form483          ', Form483Inspection.objects.count())
print('483 observations ', Form483Observation.objects.count())
print('warning letters  ', WarningLetter.objects.count())
print('best practices   ', BestPractice.objects.count())
" 2>&1 | tail -5
```

```
deficiencies      7458
form483           187
483 observations  851
warning letters   0
best practices    5
```

**`warning letters 0` is expected and is an open gap.** The importer supports
them (`import_inspections --only warning_letters`) but the legacy sqlite
snapshot used for the port did not carry that table, so the import skipped it
silently. Loading them needs a snapshot that has `AIDatabase_warningletter`.

---

## 5. company_site — the legacy tools

### 5.1 Both listeners answer

```bash
for u in http://localhost:8080/adminmaster/login/ \
         http://localhost:8090/adminmaster/login/ \
         http://localhost:8080/ratools/ ; do
  echo -n "$u -> "; curl -s -o /dev/null -w "%{http_code}\n" "$u"
done
```

All `200`. **Any 404 here is almost certainly stale nginx upstreams, not a
routing bug** — `docker compose restart nginx` and retry before investigating
anything else.

### 5.2 The trailing slash is optional

`APPEND_SLASH` is `False` and each route natively accepts exactly one form —
188 require the slash, 154 refuse it, with no learnable pattern.
`SlashToleranceMiddleware` makes both work.

```bash
curl -s -o /dev/null -w "with slash: %{http_code}\n"    http://localhost:8080/ratools/
curl -s -o /dev/null -w "without slash: %{http_code}\n" http://localhost:8080/ratools
```

Expect `200` and `301` (the redirect resolves). `ROUTES.md` lists every route
with its canonical form and which port serves it.

### 5.3 Known-broken, do not chase

| Route | Why |
|---|---|
| 4 AIDatabase lookups | The restored workbooks lack the `Country`, `FEI Number` and `Organization Name` columns the views read. Needs a corrected export from the client. |
| `/ratools/appendix_white_paper` | Dead template link. |
| `media/Module_Simplification` | Content is not in the repo. |

These render an empty state rather than 500. That is as far as code takes them.

### 5.4 If company_site returns 500 on every login

The shipped `db.sqlite3` predates 134 model fields. **Back up the database
file first**, then:

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T company_site python add_missing_columns.py --dry-run
MSYS_NO_PATHCONV=1 docker compose exec -T company_site python add_missing_columns.py
```

Additive only — one `ADD COLUMN` per missing field, nothing dropped or rebuilt.
Re-running is safe. Already applied on this machine; expect
`Nothing to add: the schema already matches the models.`

---

## 6. Backend test suite

`pytest` is **not** in the runtime image — it is a dev dependency. Three things
about getting it running, each of which fails in a way that does not name its
own cause:

**Install as root.** The container runs as a non-root user whose `HOME` is
`/nonexistent`, so a plain `pip install` dies on a path that has nothing to do
with what you asked for:

```
ERROR: Could not install packages due to an OSError:
[Errno 13] Permission denied: '/nonexistent'
```

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -u root backend pip install -q -r requirements/dev.txt
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest --version
```

Expect `pytest 8.3.5`. This installs into the **running container**, not the
image, so it is undone by `docker compose up -d --force-recreate backend` and
has to be redone after any rebuild.

**Force the test settings module.** This one produces *plausible failures*
rather than an error, which makes it the most expensive mistake on this page.

`pyproject.toml` sets `DJANGO_SETTINGS_MODULE = "regx.settings.test"`, but the
container's environment sets `regx.settings.production`, and the environment
wins. Production has no `CELERY_TASK_ALWAYS_EAGER`, so every task dispatched
through `transaction.on_commit(... .delay(...))` is queued and never runs.

The result is **7 failures in `external_integrations`** that read exactly like
real bugs — `ingest was never called`, `DocumentVersion matching query does not
exist`, `assert 'queued' == ExecutionStatus.FAILED`. Nothing is wrong with the
code. Pass the settings module explicitly:

```
-e DJANGO_SETTINGS_MODULE=regx.settings.test
```

With it, those 48 tests pass. If you see failures clustered in
`external_integrations` and they all involve work that was supposed to happen
asynchronously, check this before reading any application code.

**Pass `--no-cov` and `-p no:cacheprovider`.** `/app` is read-only: coverage
cannot write there, and the `INTERNALERROR` it raises is not a test failure.
The cache provider fails the same way, more noisily
(`could not create cache path /app/.pytest_cache/...`).

**Run one pytest at a time.** Every run builds the same `test_regx` database.
A second concurrent run fails at *setup*, before any test executes:

```
psycopg.errors.DuplicateDatabase: database "test_regx" already exists
psycopg.errors.ObjectInUse: database "test_regx" is being accessed by other users
```

Every test in the second run reports `ERROR`, including ones that have nothing
to do with your change. **This is not a regression** — it means another run is
still going. Wait for it and re-run.

### Running it

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -e DJANGO_SETTINGS_MODULE=regx.settings.test backend python -m pytest -q --no-cov -p no:cacheprovider
```

3,807 tests collected, roughly 14 minutes. Redirect to a file rather than
watching it scroll.

### Six failures you cannot fix from inside the container

`common/tests/test_task_reliability_doc.py` reads
`docs/TASK_RELIABILITY.md`, resolved as `parents[3]` from the test file. The
image copies only `backend/`, so inside the container that resolves to
`/docs/TASK_RELIABILITY.md`, which does not exist:

```
FileNotFoundError: [Errno 2] No such file or directory: '/docs/TASK_RELIABILITY.md'
```

Six of the eight tests in that file fail this way; the other two do not read
the document. They are documentation-consistency checks written to run from a
source checkout, where `docs/` sits beside `backend/`. Run them on the host, or
with the repository mounted — **not** by editing the path out of the test, which
would disable a check that is currently passing.

To confirm they pass rather than assuming it:

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -u root backend mkdir -p /docs
docker cp docs/TASK_RELIABILITY.md "$(docker compose ps -q backend)":/docs/TASK_RELIABILITY.md
MSYS_NO_PATHCONV=1 docker compose exec -T -e DJANGO_SETTINGS_MODULE=regx.settings.test backend python -m pytest common/tests/test_task_reliability_doc.py -q --no-cov -p no:cacheprovider
MSYS_NO_PATHCONV=1 docker compose exec -T -u root backend rm -rf /docs
```

Expect `8 passed`. Remove `/docs` afterwards, as above — leaving it behind makes
later runs pass for a reason that is not in the image.

### The sign-in tests specifically

The five `TestMyRolesView` tests added with the shared sign-in are the cheapest
check on that change. Run them **only when no other pytest is running**, per the
note above:

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -e DJANGO_SETTINGS_MODULE=regx.settings.test backend python -m pytest authorization/tests/test_authorization.py -q --no-cov -p no:cacheprovider
```

Nine tests: four pre-existing for `TestEffectivePermissionsView`, five new for
`TestMyRolesView`. If **all nine** error at setup, re-read the concurrency note
— that pattern is the shared test database, not your code.

### Status — full suite run 2026-09-09

```
6 failed, 3804 passed, 1 skipped, 5 warnings in 921.72s (0:15:21)
```

**All six failures are the `docs/` path problem above.** Copying
`docs/TASK_RELIABILITY.md` to `/docs/` inside the container and re-running gives
`8 passed`, so the documentation itself is correct and nothing is drifting —
the file simply is not in the image. **There are no real failures on this
branch.**

| Suite | Result |
|---|---|
| Full suite | 3,804 passed, 6 failed (all `docs/` path), 1 skipped |
| `common/tests/test_task_reliability_doc.py` with docs present | 8 passed |
| `external_integrations/` | 48 passed — **with the correct settings module** |
| `authorization/tests/test_authorization.py` | 9 passed |
| `deficiencies/` | 22 passed |

Test count rose from 3,807 to 3,811 because `test_regulatory_claim_guard` is
parametrised over `GOVERNED_MODULES`, and four ported apps were added to it.

**What the first run of this suite found.** `test_the_guard_covers_every_module_that_has_migrations`
failed with:

```
governed app(s) not covered by the regulatory claim guard:
controlled_correspondence, deficiencies, inspections, product_comparison
```

A real gap, and the reason that test exists: the four ported apps had
migrations but were in nobody's list, so nothing was scanning them for phrases
claiming an FDA verdict. They were added to `GOVERNED_MODULES` rather than
exempted as `foundation` — all four render FDA-derived text, which is exactly
where "FDA compliant" reaches a UI string without anyone deciding it should.
No offending phrase was present; this closed a coverage gap, not a defect.

---

## 7. Before calling anything done

- [ ] §2 passes in full, including every negative case in 2.5
- [ ] `usable_pw=False` for all mirrored accounts (2.4)
- [ ] Legitimate requests succeed, not just bad ones refused (§3)
- [ ] Full backend suite run at least once (§6)
- [ ] You can state, in your own words, what `_authenticate()` does and why the
      local fallback cannot be used to bypass REGX

If the last one is uncomfortable, read `company_site/AdminMaster/regx_auth.py`
top to bottom before merging. It is 190 lines and most of them are the reasoning.
