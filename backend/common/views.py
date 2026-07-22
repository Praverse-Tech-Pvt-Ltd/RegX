"""Health, readiness, and version endpoints."""

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(tags=["health"], responses={200: {"type": "object"}})
@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(request):
    return Response({"status": "ok"})


@extend_schema(tags=["health"], responses={200: {"type": "object"}})
@api_view(["GET"])
@permission_classes([AllowAny])
def readiness_view(request):
    checks = {}
    try:
        connection.ensure_connection()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    try:
        cache.set("regx_readiness_probe", "1", timeout=5)
        checks["cache"] = "ok"
    except Exception as e:
        checks["cache"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return Response(
        {"status": "ready" if all_ok else "degraded", "checks": checks},
        status=200 if all_ok else 503,
    )


@extend_schema(tags=["health"], responses={200: {"type": "object"}})
@api_view(["GET"])
@permission_classes([AllowAny])
def version_view(request):
    return Response(
        {
            "version": getattr(settings, "APP_VERSION", "unknown"),
            "environment": getattr(settings, "APP_ENVIRONMENT", "unknown"),
        }
    )
