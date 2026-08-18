"""Development settings — extends base."""

from .base import *  # noqa: F403

DEBUG = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Relax CSP in development to allow HMR / dev tools
CSP_SCRIPT_SRC = ("'self'", "'unsafe-eval'")  # ONLY in development
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")  # ONLY in development

INSTALLED_APPS += ["django.contrib.admin"]  # noqa: F405

MIDDLEWARE += ["django.contrib.messages.middleware.MessageMiddleware"]  # noqa: F405

# ---------------------------------------------------------------------------
# Operational logging
# ---------------------------------------------------------------------------
# INFO, not DEBUG. The sensitive-data policy is identical in development: a
# request body is no less confidential because DEBUG is True, and
# django.db.backends at DEBUG would print every SQL statement with its
# parameter values. Raise a single logger by hand when you need to.
LOGGING["root"]["level"] = "INFO"  # noqa: F405
LOGGING["loggers"]["regx"]["level"] = "DEBUG"  # noqa: F405  our own code only
