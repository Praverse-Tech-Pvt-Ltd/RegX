# RegX — setup on a new device

Runbook for getting this project running from a clean clone. Written to be
executed step by step; each step says how to confirm it worked.

**Python 3.12+ required** (3.13 tested locally, `render.yaml` pins 3.12.7).

---

## ⚠️ Read this before starting the server

**Starting the app can spend money.** With `ENABLE_OBSERVATION_SUMMARIES=True`, a
single page view fans out one OpenAI API call per FDA observation block — 8,362 in
the bundled workbook — synchronously inside the request, using a key hardcoded in
`AIDatabase/filters.py`. This has already cost real money once.

The flag defaults to `False` and **step 4 sets it explicitly**. Do not turn it on
without deciding to pay. To see the cost first:

```bash
python manage.py export_gpt_input_data --only-pending --out pending.xlsx
```

There is also a **live hardcoded OpenAI API key** in `AIDatabase/filters.py`. It is
retained deliberately (do not "clean it up" — it needs rotating at the provider
first, which deleting the line does not do).

---

## 1. Clone and check out the branch

The work is on a branch, **not** on `main`.

```bash
git clone https://github.com/Praverse-Tech-Pvt-Ltd/RegX.git
cd RegX
git checkout fix/backend-wiring-and-deploy-hardening
```

> If PR #45 has been merged by the time you read this, use `main` instead.
> `git log --oneline -1` should show `Add session handoff, constraints and decision log`
> or later.

**Confirm:** `git branch --show-current`

---

## 2. Virtual environment and dependencies

**Windows**
```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Installs Django 5.1.3, DRF, pandas, matplotlib, openai, celery and others.
Takes a few minutes (pandas and matplotlib build wheels).

**Confirm:** `python -c "import django; print(django.get_version())"` → `5.1.3`

> A `fuzzywuzzy` warning about "slow pure-python SequenceMatcher" on every command
> is expected and harmless.

---

## 3. Environment file

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

The shipped values are blank and that is fine — `settings.env()` treats a blank
value as unset and falls back to a working default. No editing needed for local
development.

Do **not** commit `.env`. It is gitignored.

**Confirm:** `python manage.py check` → 1 warning (`ckeditor.W001`), no errors.

---

## 4. Set the summary flag explicitly

Append to `.env` so it is unambiguous rather than relying on the default:

```bash
echo "ENABLE_OBSERVATION_SUMMARIES=False" >> .env
```

**Confirm:**
```bash
python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','RAAI.settings');django.setup();from django.conf import settings;print(settings.ENABLE_OBSERVATION_SUMMARIES)"
```
Must print `False`.

---

## 5. Build the database

**Do not use the shipped `db_*.sqlite3` files as `db.sqlite3`.** They are 24 tables
and 135 columns behind the current models — login and every authenticated page
will 500. Build fresh instead.

```bash
python manage.py migrate --run-syncdb
```

`--run-syncdb` is required: only `RATools` has migrations. `AdminMaster` and
`AIDatabase` have none, so their tables are created directly from the models.

**Confirm:** 80 tables, no drift —
```bash
python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "RAAI.settings"); django.setup()
from django.apps import apps
from django.db import connection
existing = set(connection.introspection.table_names())
missing_t, missing_c = [], []
with connection.cursor() as c:
    for m in apps.get_models():
        t = m._meta.db_table
        if t not in existing:
            missing_t.append(t); continue
        have = {r.name for r in connection.introspection.get_table_description(c, t)}
        missing_c += [f"{t}.{f.column}" for f in m._meta.local_fields if f.column not in have]
print(f"tables={len(existing)} missing_tables={len(missing_t)} missing_columns={len(missing_c)}")
PY
```
Expect `tables=80 missing_tables=0 missing_columns=0`.

---

## 6. Seed reference data

The fresh database is empty. The checklist **question banks** live only in the
tracked snapshot `db_17_1_2.sqlite3` — without them every checklist renders with no
questions. This copies only columns present in both schemas, so it is safe despite
the drift.

```bash
python - <<'PY'
import sqlite3
old = sqlite3.connect("db_17_1_2.sqlite3"); old.row_factory = sqlite3.Row
new = sqlite3.connect("db.sqlite3")

TABLES = [
    "RATools_andareportquestions", "RATools_dmfcatablequestion",
    "RATools_dmfreviewtablequestion", "RATools_validationreportquestions",
    "RATools_vpreportquestions", "RATools_generalreportquestions",
    "RATools_generaltable13", "RATools_generaltable14", "RATools_cctemplate",
    "AIDatabase_anda", "AIDatabase_majorcr",
]
total = 0
for t in TABLES:
    ocols = [r[1] for r in old.execute(f"pragma table_info({t})")]
    ncols = [r[1] for r in new.execute(f"pragma table_info({t})")]
    shared = [c for c in ocols if c in ncols]
    if not shared:
        print(f"  {t:36} SKIPPED (table missing)"); continue
    rows = old.execute(f"select {','.join(shared)} from {t}").fetchall()
    if not rows:
        print(f"  {t:36} 0 rows"); continue
    if new.execute(f"select count(*) from {t}").fetchone()[0]:
        print(f"  {t:36} SKIPPED (already populated)"); continue
    new.executemany(
        f"insert into {t} ({','.join(shared)}) values ({','.join('?'*len(shared))})",
        [tuple(r) for r in rows],
    )
    total += len(rows)
    print(f"  {t:36} {len(rows):>5} rows")
new.commit()
print(f"\ntotal restored: {total}")
PY
```

**Confirm:** `total restored: 7679`

| What you get | Rows |
|---|---|
| ANDA / DMF / Validation / VP / General question banks | 221 |
| FDA deficiency + Major CR tables | 7,458 |

> Still empty: FDA 483 observations and warning letters. Those screens will render
> but show nothing. Populate with `python manage.py import_*` (see
> `AIDatabase/management/commands/`) **only** with the summary flag off.

---

## 7. Create test accounts

Roles matter: the tool views branch on `company_user` (66 checks) and
`company_checker` (104), with only 5 on `admin`. Use the doer/checker accounts for
feature testing — the admin account shows *less*.

An `AssignChecker` row is **mandatory**: several views call
`AssignChecker.objects.get(user=...)` with no `try/except` and will 500 without one.

```bash
python - <<'PY'
import os, django, datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "RAAI.settings"); django.setup()
from AdminMaster.models import AssignChecker, CustomUser
from RATools.models import RegulatoryRole

PASSWORD = "ChangeMe#2026"          # local only — change it
ALL_REPORTS = [c[0] for c in AssignChecker.REPORT_CHOICES]
ALL_SAMPLES = [c[0] for c in AssignChecker.VIEW_SAMPLE_CHOICES]

def make(username, role, staff=False, reg_roles=()):
    u, _ = CustomUser.objects.get_or_create(username=username)
    u.role = role
    u.set_password(PASSWORD)
    u.is_staff = u.is_superuser = staff
    u.internal_team = False          # leave False: True bypasses the prod device lock
    u.subscription_end_date = datetime.date(2030, 12, 31)
    u.fda_deficiency_database = True
    u.complete_response_database = True
    u.save()
    a, _ = AssignChecker.objects.get_or_create(user=u)
    a.assigned_report = ALL_REPORTS
    a.view_sample_reports = ALL_SAMPLES
    a.save()
    for r in reg_roles:
        RegulatoryRole.objects.get_or_create(user=u, role=r)
    return u, a

accounts = [
    make("ra_admin",   "admin",           staff=True, reg_roles=("vp",)),
    make("ra_doer",    "company_user",                reg_roles=("doer",)),
    make("ra_checker", "company_checker",             reg_roles=("reviewer",)),
]
checker = accounts[2][0]
for _, a in accounts[:2]:
    for lvl in range(1, 8):
        getattr(a, f"assigned_checker_level_{lvl}").add(checker)
    a.save()

for u, a in accounts:
    print(f"  {u.username:11} role={u.role:16} reports={len(a.assigned_report)}")
PY
```

**Delete these before any deploy that reuses this database:**
```python
CustomUser.objects.filter(username__startswith="ra_").delete()
```

---

## 8. Run

```bash
python manage.py runserver 0.0.0.0:8000
```

Open **http://127.0.0.1:8000** and log in at `/adminmaster/login/`.

| Username | Role | Use for |
|---|---|---|
| `ra_doer` | company_user | Creating and submitting checklists |
| `ra_checker` | company_checker | Reviewing, approve/reject |
| `ra_admin` | admin + Django admin | Oversight, `/admin/` |

Password is whatever you set as `PASSWORD` in step 7.

---

## 9. Verify the install

```bash
python manage.py test        # expect: Ran 50 tests ... OK
python manage.py check       # expect: 1 warning (ckeditor.W001), 0 errors
```

Then in the browser, confirm the full workflow:

1. `/ratools/show_anda_mdi_and_dpi_table` as `ra_doer` → create a checklist
2. Open it → questions render (proves step 6 worked) → answer and submit
3. Log in as `ra_checker` → same report → Approve
4. `/ratools/audit-trail/` → the approval is listed

**Zero OpenAI calls should appear in the server log.** If you see
`[SUMMARY] Calling OpenAI API`, stop the server — step 4 did not take effect.

---

## 10. Gotchas that will otherwise cost you an hour

| Symptom | Cause |
|---|---|
| A URL 404s that clearly exists | `APPEND_SLASH = False` and slash coverage is inconsistent: of 171 `RATools` routes, 90 work **only without** a trailing slash, 80 **only with** one. Try flipping the slash |
| Every checklist page 500s for one user | That account has no `AssignChecker` row — see step 7 |
| `/ratools/module/` 500s for everyone | `module_view` lists `media/Module_Simplification`, which is gitignored and absent. Not fixable in code; the content is not in the repo |
| Checklists render with no questions | Step 6 was skipped |
| Login 500s / `ImproperlyConfigured` | Old `db.sqlite3` copied from a snapshot instead of built in step 5 |
| Search on Form 483 observations errors | Needs a valid OpenAI key; falls back to a literal search when unavailable |

---

## 11. Read next

| File | What it holds |
|---|---|
| `CLAUDE.md` | Architecture, commands, the migration situation |
| `constraints.md` | **Hard boundaries — read before changing anything** |
| `handoff.md` | Current state, what failed and why, next steps |
| `decisions.md` | Why things are built the way they are |
| `SOW-TECHNICAL-TOOLS-STATUS.md` | SOW section 2 progress |

---

## 12. Do not

- Do not run `makemigrations` for `AdminMaster` or `AIDatabase`. They have no
  committed migrations and their schema exists only in the drifted snapshots.
- Do not commit `.env`, `db.sqlite3`, or `db.sqlite3.bak.*`.
- Do not overwrite `db_17_1_2.sqlite3` — it is the only copy of the reference data.
- Do not enable `ENABLE_OBSERVATION_SUMMARIES` without deciding to pay.
- Do not push to `main`; branch and open a PR.
