"""Production settings — extends base with hardened security."""

from decouple import config
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
DEBUG = False  # Must be False in production

# ---------------------------------------------------------------------------
# Cookie security
# ---------------------------------------------------------------------------
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True  # Inherited from base; explicit here for audit
SESSION_COOKIE_SAMESITE = "Lax"  # Inherited from base; explicit here for audit

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False  # JS must read the CSRF token

# ---------------------------------------------------------------------------
# CSP — strict; no dynamic code execution or inline styles
# ---------------------------------------------------------------------------
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)  # strict script-src
CSP_STYLE_SRC = ("'self'",)
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_OBJECT_SRC = ("'none'",)
CSP_BASE_URI = ("'self'",)
CSP_FORM_ACTION = ("'self'",)

# ---------------------------------------------------------------------------
# API schema and Swagger UI
# ---------------------------------------------------------------------------
# The schema maps every route, parameter and permission of the API. Here it is
# served only to a signed-in session (the default SessionAuthentication), so
# /api/schema/ and /api/docs/ answer 403 to anonymous callers. Development and
# test settings keep the drf-spectacular default (AllowAny).
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,  # noqa: F405
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
}

# ---------------------------------------------------------------------------
# Operational logging
# ---------------------------------------------------------------------------
# INFO to stdout. Inherited from base; stated explicitly because it is a
# production posture decision, not an accident of the default.
LOGGING["root"]["level"] = "INFO"  # noqa: F405
LOGGING["loggers"]["regx"]["level"] = "INFO"  # noqa: F405


# ---------------------------------------------------------------------------
# Malware scanning must be real here
# ---------------------------------------------------------------------------
# `StubScanner` reports every file CLEAN without inspecting it. That is a
# development convenience and it is indistinguishable, downstream, from a real
# clean result: the same `scan_status`, the same `document.scan.complete` audit
# event. Nothing later in the pipeline can tell the difference, so the only
# place to catch it is here, before the process serves a request.
#
# This raises at import, not at first upload, so a misconfigured deployment
# fails at deploy time rather than silently accepting evidence for weeks.
#
# ALLOW_STUB is the one escape hatch, and it exists because the local compose
# stack and the CI compose job both run THIS settings module (see compose.yaml)
# — not because a deployment may reasonably want it. Never set it in a deployed
# environment. If you are copying compose.yaml toward production, removing
# DOCUMENT_SCANNER_ALLOW_STUB is the first thing to do.
DOCUMENT_SCANNER_ALLOW_STUB = config("DOCUMENT_SCANNER_ALLOW_STUB", cast=bool, default=False)

if DOCUMENT_SCANNER_BACKEND == "stub" and not DOCUMENT_SCANNER_ALLOW_STUB:  # noqa: F405
    raise ImproperlyConfigured(
        "DOCUMENT_SCANNER_BACKEND is 'stub', which marks every uploaded file "
        "CLEAN without scanning it. Set DOCUMENT_SCANNER_BACKEND=clamav and "
        "point DOCUMENT_CLAMAV_HOST / DOCUMENT_CLAMAV_PORT at a running clamd. "
        "For local development only, set DOCUMENT_SCANNER_ALLOW_STUB=true."
    )
