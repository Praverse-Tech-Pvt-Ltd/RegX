"""
Run this on the machine where routes appear to be missing:

    python diagnose.py                 # full report
    python diagnose.py /ratools/foo    # also check one specific URL

Read-only. Makes no changes and no network calls.
"""
import os, sys, django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "RAAI.settings")
django.setup()

from django.conf import settings
from django.urls import get_resolver

print("=" * 62)
print("RegX diagnostic")
print("=" * 62)

# 1. Is the checked-out code current?
import subprocess
def git(*a):
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()
    except Exception:
        return "?"
print(f"\n[code]   branch : {git('rev-parse','--abbrev-ref','HEAD')}")
print(f"         commit : {git('log','--oneline','-1')}")
print(f"         dirty  : {'yes' if git('status','--short') else 'no'}")

# 2. Do the fixed symbols exist in this checkout?
import RATools.views as v
print("\n[fixes]  checker_has_open_review present :",
      hasattr(v, "checker_has_open_review"))
import RATools.admin  # noqa
from django.contrib import admin as dj_admin
from RATools import models as m
print("         RegulatoryRole registered in admin:",
      m.RegulatoryRole in dj_admin.site._registry)

# 3. Database health — the usual cause of 500s
from django.apps import apps
from django.db import connection
try:
    existing = set(connection.introspection.table_names())
    missing_t, missing_c = [], []
    with connection.cursor() as c:
        for mod in apps.get_models():
            t = mod._meta.db_table
            if t not in existing:
                missing_t.append(t); continue
            have = {r.name for r in connection.introspection.get_table_description(c, t)}
            missing_c += [f"{t}.{f.column}" for f in mod._meta.local_fields
                          if f.column not in have]
    print(f"\n[db]     file   : {settings.DATABASES['default']['NAME']}")
    print(f"         tables : {len(existing)}   (a healthy build has 80)")
    print(f"         missing tables : {len(missing_t)}   missing columns : {len(missing_c)}")
    if missing_t or missing_c:
        print("         >>> STALE DATABASE. Fix:")
        print("             rm db.sqlite3 && python manage.py migrate --run-syncdb")
        print("             then SETUP.md steps 6 and 7")
except Exception as e:
    print(f"\n[db]     ERROR: {type(e).__name__}: {e}")

# 4. Seed data — empty checklists look like broken pages
try:
    from RATools.models import ANDAReportQuestions
    from AdminMaster.models import CustomUser, AssignChecker
    q = ANDAReportQuestions.objects.count()
    print(f"\n[data]   checklist questions : {q}" + ("   >>> run SETUP.md step 6" if q == 0 else ""))
    users = CustomUser.objects.count()
    no_ac = [u.username for u in CustomUser.objects.all()
             if not AssignChecker.objects.filter(user=u).exists()]
    print(f"         users : {users}"
          + (f"   >>> no AssignChecker row (will 500): {no_ac}" if no_ac else ""))
except Exception as e:
    print(f"\n[data]   ERROR: {type(e).__name__}: {e}")

# 5. Routing
print(f"\n[routes] APPEND_SLASH = {getattr(settings, 'APPEND_SLASH', True)}"
      "   (False => /path/ is NOT redirected to /path)")
pats = []
def walk(res, pre=""):
    for p in res.url_patterns:
        if hasattr(p, "url_patterns"):
            walk(p, pre + str(p.pattern))
        else:
            pats.append(pre + str(p.pattern))
walk(get_resolver())
print(f"         total registered routes : {len(pats)}")

# 6. Optional: check a specific URL the user says is missing
if len(sys.argv) > 1:
    from django.urls import resolve, Resolver404
    target = sys.argv[1]
    # Git Bash / MSYS rewrites a leading "/" into a Windows path, so
    # "/ratools/x" arrives as "C:/Program Files/Git/ratools/x". Recover the
    # real path by keeping everything from the first known app prefix.
    for prefix in ("ratools/", "aidatabase/", "adminmaster/", "admin/"):
        idx = target.find(prefix)
        if idx != -1:
            target = "/" + target[idx:]
            break
    if not target.startswith("/"):
        target = "/" + target
    print(f"\n[check]  {target}")
    for candidate in (target, target.rstrip("/"), target.rstrip("/") + "/"):
        try:
            match = resolve(candidate)
            print(f"         OK   {candidate}  ->  {match.func.__name__}")
        except Resolver404:
            print(f"         404  {candidate}")
print("\n" + "=" * 62)
