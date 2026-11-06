"""Tenant management endpoints."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Tenant, TenantMembership
from .serializers import MembershipSerializer, TenantSerializer


@extend_schema(tags=["tenants"])
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tenant_list_view(request):
    if request.method == "GET":
        memberships = TenantMembership.objects.filter(
            user=request.user, is_active=True
        ).select_related("tenant")
        tenants = [m.tenant for m in memberships]
        return Response(TenantSerializer(tenants, many=True).data)

    # Self-service tenant creation is disabled: any signed-in user could create
    # a tenant and become its only member. Platform operators create tenants
    # with `manage.py create_tenant`. POST stays routed for a clear answer.
    return Response(
        {
            "detail": "Creating an organisation is restricted to platform administrators.",
            "error_code": "tenant_creation_restricted",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


@extend_schema(tags=["tenants"])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tenant_detail_view(request, public_id):
    try:
        tenant = Tenant.objects.get(public_id=public_id)
    except Tenant.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)

    if not TenantMembership.objects.filter(
        tenant=tenant, user=request.user, is_active=True
    ).exists():
        return Response({"detail": "Not a member."}, status=403)

    return Response(TenantSerializer(tenant).data)


@extend_schema(tags=["tenants"])
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def tenant_active_view(request):
    """Set the active tenant for the current session. Body: {tenant_id: uuid}."""
    tenant_id = request.data.get("tenant_id")
    if not tenant_id:
        return Response({"detail": "tenant_id is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        tenant = Tenant.objects.get(public_id=tenant_id)
    except (Tenant.DoesNotExist, Exception):
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if not TenantMembership.objects.filter(
        tenant=tenant, user=request.user, is_active=True
    ).exists():
        return Response(
            {"detail": "Not a member of this tenant."}, status=status.HTTP_403_FORBIDDEN
        )

    request.session["active_tenant_id"] = str(tenant.public_id)
    return Response(TenantSerializer(tenant).data)


@extend_schema(tags=["tenants"])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tenant_members_view(request, public_id):
    try:
        tenant = Tenant.objects.get(public_id=public_id)
    except Tenant.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)

    if not TenantMembership.objects.filter(
        tenant=tenant, user=request.user, is_active=True
    ).exists():
        return Response({"detail": "Not a member."}, status=403)

    memberships = TenantMembership.objects.filter(tenant=tenant).select_related("user")
    return Response(MembershipSerializer(memberships, many=True).data)
