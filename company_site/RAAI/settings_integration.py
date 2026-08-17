"""Settings used when the company site runs inside the REGX stack.

The company project is carried into REGX verbatim: `RAAI/settings.py` is a
byte-for-byte copy of the file we were given and is deliberately NOT edited.
This module imports it and applies only the overrides that are strictly
required to run the same application as a container behind the shared nginx
origin. Every override below is justified in
`docs/BOOKING_FINAL_REGX_INTEGRATION_PLAN.md` §4.
"""

from decouple import Csv, config

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR, DATABASES

# ---------------------------------------------------------------------------
# Cookie namespacing
# ---------------------------------------------------------------------------
# The company site and the REGX backend are both Django and both default to
# the `sessionid` / `csrftoken` cookie names. Now that they answer on a single
# origin they would silently overwrite one another's cookies, logging users
# out of one app by using the other. The company copy is renamed rather than
# the REGX backend so that REGX authentication stays byte-identical.
SESSION_COOKIE_NAME = "company_sessionid"
CSRF_COOKIE_NAME = "company_csrftoken"

# ---------------------------------------------------------------------------
# Serving behind nginx
# ---------------------------------------------------------------------------
DEBUG = config("DEBUG", cast=bool, default=False)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,company_site,nginx",
    cast=Csv(),
)

# Required for the company POST forms (login, request-demo, contact) once the
# browser's origin (the nginx port) differs from the container's own host.
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:8080,http://127.0.0.1:8080",
    cast=Csv(),
)

# `RAAI/urls.py` appends django.conf.urls.static.static(...), which returns an
# empty list whenever DEBUG is False. With DEBUG off, /static/ and /media/ are
# therefore served by nginx straight off the copied trees (486 MB + 199 MB) —
# the right server for that job. STATIC_ROOT is kept only so collectstatic has
# a target if it is ever run.
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Database location
# ---------------------------------------------------------------------------
# Same SQLite database, same content — only relocated onto a named volume so
# that company logins, session rows and demo bookings survive an image
# rebuild. docker-entrypoint.sh seeds it from the copied db.sqlite3 on first
# start. The engine and every model are untouched.
DATABASES = {
    **DATABASES,
    "default": {
        **DATABASES["default"],
        "NAME": config("COMPANY_DB_PATH", default=str(BASE_DIR / "db.sqlite3")),
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
# The company settings hard-code redis://127.0.0.1:6379/0, which cannot
# resolve inside a container. Database 1 keeps the company broker separate
# from the REGX backend's database 0 on the shared Redis service. Note that no
# company worker or beat process is started by this integration; this only
# keeps the module importable and correct if one is ever run.
CELERY_BROKER_URL = config("COMPANY_REDIS_URL", default="redis://redis:6379/1")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
