"""Test settings."""

from decouple import config  # noqa: F401 — re-exported for DATABASES block below
from .base import *  # noqa: F401, F403

DEBUG = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CELERY_TASK_ALWAYS_EAGER = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="regx_test"),
        "USER": config("DB_USER", default="regx"),
        "PASSWORD": config("DB_PASSWORD", default="gate_test_pass"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Allow unsafe-eval only in test (for snapshot testing if needed)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-eval'")

LOGGING = {}  # Silence logging during tests

# Override to predictable test value
MFA_ENCRYPTION_KEY = "test_key_not_for_production_use_only_32b"
APP_VERSION = "test"
