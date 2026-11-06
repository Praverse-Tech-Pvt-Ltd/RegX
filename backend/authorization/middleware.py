"""Refuse state-changing API calls from Reviewer/VP accounts that have not enrolled in MFA.

Why a middleware and not a permission class: every view sets its own
`permission_classes`, so a project-wide DRF default would be overridden almost
everywhere. Authentication is session-only (`SessionAuthentication`, the same
session `AuthenticationMiddleware` reads), so `request.user` here is the user
every view will see. `test_mfa_roles.py` pins that assumption: adding another
authentication class must revisit this gate.

Exempt: safe methods (GET/HEAD/OPTIONS), and the `auth/` and `mfa/` endpoints,
which are how a blocked user signs in, signs out and enrols.
"""

from django.http import JsonResponse

from .mfa_policy import ERROR_CODE, ERROR_DETAIL, requires_mfa_enrolment

API_PREFIX = "/api/regx/v1/"
EXEMPT_PREFIXES = (API_PREFIX + "auth/", API_PREFIX + "mfa/")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class MFAEnrolmentMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in SAFE_METHODS
            and request.path.startswith(API_PREFIX)
            and not request.path.startswith(EXEMPT_PREFIXES)
            and requires_mfa_enrolment(getattr(request, "user", None))
        ):
            return JsonResponse({"detail": ERROR_DETAIL, "error_code": ERROR_CODE}, status=403)
        return self.get_response(request)
