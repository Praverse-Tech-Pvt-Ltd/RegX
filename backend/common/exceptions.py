"""REGX shared exception types and DRF exception handler."""

from rest_framework import status
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
    elif isinstance(exc, TenantScopeMissing):
        response = Response(
            {"error": {"status": 400, "detail": "Tenant context is required."}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return response
