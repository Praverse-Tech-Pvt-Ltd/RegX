"""
REGX base Django settings.
Never import AIDatabase, legacy RAAI, or legacy AdminMaster here.
"""

from pathlib import Path

from corsheaders.defaults import default_headers
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECRET_KEY = config("DJANGO_SECRET_KEY")  # No insecure default in production

DEBUG = config("DEBUG", cast=bool, default=False)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ---------------------------------------------------------------------------
# Applications — REGX domains only
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    "csp",
    "drf_spectacular",
    # REGX domains
    "identity",
    "tenancy",
    "authorization",
    "audit",
    "workflows",
    "common",
    "documents",
    "templates_registry",
    "fda_data",
    "formulations",
    "iid_assessment",
    "iig_checklist",
    "regulatory_cases",
    "submission_dossiers",
]

MIDDLEWARE = [
    # First: wraps every other middleware, so the measured duration covers the
    # whole stack and the X-Request-ID header is set even on error responses.
    "common.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "tenancy.middleware.TenantMiddleware",
    "audit.middleware.AuditMiddleware",
]

ROOT_URLCONF = "regx.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_USER_MODEL = "identity.User"

WSGI_APPLICATION = "regx.wsgi.application"

# ---------------------------------------------------------------------------
# Database — PostgreSQL only; SQLite is prohibited
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="regx"),
        "USER": config("DB_USER", default="regx"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 10},
    }
}

# ---------------------------------------------------------------------------
# Caching / Redis
# ---------------------------------------------------------------------------
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "regx",
    }
}

# ---------------------------------------------------------------------------
# Session — HttpOnly, Secure, SameSite
# ---------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 28800  # 8 hours
# SESSION_COOKIE_SECURE is set per-environment (True in production)

CSRF_COOKIE_HTTPONLY = False  # Frontend JS must read the CSRF token
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="http://localhost:3000", cast=Csv())

# ---------------------------------------------------------------------------
# CORS — restricted to known frontend origin
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="http://localhost:3000", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False  # Explicit; never wildcard

# django-cors-headers' default allow-list does not include the tenant-scoping
# header the frontend sends on every document API request; without this, a
# real cross-origin browser blocks the preflight and every document request
# fails, even though same-process test clients (which don't enforce CORS)
# never catch it.
CORS_ALLOW_HEADERS = [*default_headers, "x-tenant-slug"]

# ---------------------------------------------------------------------------
# Content Security Policy
# ---------------------------------------------------------------------------
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)  # No unsafe-inline, no unsafe-eval in production
CSP_STYLE_SRC = ("'self'",)
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_OBJECT_SRC = ("'none'",)
CSP_BASE_URI = ("'self'",)
CSP_FORM_ACTION = ("'self'",)

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "common.exceptions.regx_exception_handler",
}

# ---------------------------------------------------------------------------
# Document platform
# ---------------------------------------------------------------------------
DOCUMENT_STORAGE_BACKEND = config("DOCUMENT_STORAGE_BACKEND", default="local")
DOCUMENT_LOCAL_STORAGE_ROOT = config(
    "DOCUMENT_LOCAL_STORAGE_ROOT",
    default=str(BASE_DIR / "document_storage"),
)
DOCUMENT_MAX_UPLOAD_BYTES = config("DOCUMENT_MAX_UPLOAD_BYTES", cast=int, default=50 * 1024 * 1024)
# Scanner: "stub" (dev default, marks all clean), "clamav" (requires running clamd)
DOCUMENT_SCANNER_BACKEND = config("DOCUMENT_SCANNER_BACKEND", default="stub")
DOCUMENT_CLAMAV_HOST = config("DOCUMENT_CLAMAV_HOST", default="127.0.0.1")
DOCUMENT_CLAMAV_PORT = config("DOCUMENT_CLAMAV_PORT", cast=int, default=3310)

# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "REGX API",
    "DESCRIPTION": "Regulatory Excellence Platform — independent REGX product API.",
    "VERSION": config("APP_VERSION", default="0.1.0"),
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/regx/v1/",
    "COMPONENT_SPLIT_REQUEST": True,
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", cast=bool, default=False)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
# By default a Celery worker takes over the root logger and installs its own
# text handler, which would leave worker output in a different format from the
# rest of the system and outside the allow-list formatter. Handing logging back
# to LOGGING below is what makes the worker emit the same structured records.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# ---------------------------------------------------------------------------
# MFA encryption key (Fernet symmetric key, base64-encoded)
# ---------------------------------------------------------------------------
MFA_ENCRYPTION_KEY = config("MFA_ENCRYPTION_KEY")

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# I18n / Static
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "collected_static"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# App version (for /api/regx/v1/version/)
# ---------------------------------------------------------------------------
APP_VERSION = config("APP_VERSION", default="0.1.0")
APP_ENVIRONMENT = config("APP_ENVIRONMENT", default="development")

# ---------------------------------------------------------------------------
# Operational logging
# ---------------------------------------------------------------------------
# Structured JSON to stdout, one event per line. Containers log to stdout;
# nothing here writes files, and no aggregation target is assumed.
#
# THIS IS NOT THE AUDIT TRAIL. audit.models.AuditEvent is the authoritative
# regulated record and is entirely independent of these handlers -- see
# docs/OPERATIONAL_LOGGING.md.
#
# disable_existing_loggers is False so module-level loggers already created at
# import time (documents.scanner, documents.tasks) keep working.
LOG_LEVEL = config("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "common.structured_logging.RequestIDRecoveryFilter"},
        "redaction": {"()": "common.structured_logging.RedactionFilter"},
    },
    "formatters": {
        "json": {"()": "common.structured_logging.JSONFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id", "redaction"],
        },
    },
    # Root catches everything not named below, including Celery's own loggers,
    # so worker output is formatted by the same allow-list formatter.
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "regx": {"level": LOG_LEVEL, "propagate": True},
        "django": {"level": "INFO", "propagate": True},
        # Django logs 4xx/5xx here and attaches the HttpRequest to the record.
        # The formatter's allow-list is what keeps that request object -- and
        # its headers, cookies and body -- out of the output.
        "django.request": {"level": "WARNING", "propagate": True},
        "django.security": {"level": "WARNING", "propagate": True},
        # Never DEBUG: this logger emits every SQL statement executed, which
        # means parameter values, in production and in development alike.
        "django.db.backends": {"level": "WARNING", "propagate": True},
        "celery": {"level": "INFO", "propagate": True},
    },
}
