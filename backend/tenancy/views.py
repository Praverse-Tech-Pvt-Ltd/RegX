"""Tenant management endpoints."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Tenant, TenantMembership
from .serializers import MembershipSerializer, TenantCreateSerializer, TenantSerializer


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

    s = TenantCreateSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    tenant = s.save()
    TenantMembership.objects.create(tenant=tenant, user=request.user)
    return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)


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
