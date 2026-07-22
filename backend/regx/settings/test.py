"""Test settings."""

from .base import *  # noqa: F401, F403

DEBUG = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CELERY_TASK_ALWAYS_EAGER = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "regx_test",
        "USER": "regx",
        "PASSWORD": "regx_dev_password",
        "HOST": "localhost",
        "PORT": "5432",
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
