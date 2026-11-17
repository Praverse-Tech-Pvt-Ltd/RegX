"""REGX shared exception types and DRF exception handler."""

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler


class TenantScopeMissing(Exception):
    """Raised when tenant-scoped code is called without an active tenant context."""


class PermissionDenied(Exception):
    """Raised when a user lacks the required permission."""


def regx_exception_handler(exc, context):
    """Consistent JSON error envelope for all API errors."""
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "error": {
                "status": response.status_code,
                "detail": response.data,
            }
        }
        # A machine-readable reason, for the errors that have a single one.
        # Session authentication makes DRF answer a signed-out caller with 403,
        # the same status as "signed in but not allowed"; `code` is what tells
        # the two apart ("not_authenticated" vs "permission_denied"), so the
        # frontend sends only the first to the sign-in page.
        if isinstance(exc, APIException):
            codes = exc.get_codes()
            if isinstance(codes, str):
                response.data["error"]["code"] = codes
    elif isinstance(exc, TenantScopeMissing):
        response = Response(
            {"error": {"status": 400, "detail": "Tenant context is required."}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return response
