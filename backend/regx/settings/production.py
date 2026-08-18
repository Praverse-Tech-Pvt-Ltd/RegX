"""Production settings — extends base with hardened security."""

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
# Operational logging
# ---------------------------------------------------------------------------
# INFO to stdout. Inherited from base; stated explicitly because it is a
# production posture decision, not an accident of the default.
LOGGING["root"]["level"] = "INFO"  # noqa: F405
LOGGING["loggers"]["regx"]["level"] = "INFO"  # noqa: F405
