"""Authorization endpoints: list roles and permissions."""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Permission, Role


@extend_schema(tags=["authorization"])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def role_list_view(request):
    roles = Role.objects.filter(is_system=True).values("name", "description")
    return Response(list(roles))


@extend_schema(tags=["authorization"])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def permission_list_view(request):
    perms = Permission.objects.values("codename", "description")
    return Response(list(perms))
