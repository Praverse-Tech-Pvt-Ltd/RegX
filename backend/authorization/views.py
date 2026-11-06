"""Authorization endpoints: list roles, permissions, and effective permissions."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import mfa_policy
from .models import MembershipRole, Permission, Role


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


@extend_schema(tags=["authorization"])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def effective_permissions_view(request):
    """Return the set of permissions the current user has across all their tenant memberships."""
    membership_roles = MembershipRole.objects.filter(membership__user=request.user).select_related(
        "role"
    )
    roles = [mr.role for mr in membership_roles]
    perms = (
        Permission.objects.filter(role_permissions__role__in=roles)
        .values("codename", "description")
        .distinct()
        .order_by("codename")
    )
    return Response(list(perms))


@extend_schema(tags=["authorization"])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_roles_view(request):
    """Return the caller's own role names, across every active membership.

    `role_list_view` lists the roles that exist and `effective_permissions_view`
    lists what the caller may do; neither answers "which role am I". A relying
    application that has to translate a REGX identity into its own role model
    needs exactly that, and inferring it back from a permission set is guesswork
    the moment a role's permissions are edited.

    Read-only and scoped to `request.user`, so it discloses nothing the caller
    could not already infer about itself.
    """
    names = (
        MembershipRole.objects.filter(membership__user=request.user, membership__is_active=True)
        .values_list("role__name", flat=True)
        .distinct()
    )
    return Response({"roles": sorted(set(names))})


@extend_schema(tags=["authorization"])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mfa_status_view(request):
    """Whether the caller must enrol in MFA before acting (SOW 4.3).

    `mfa_enrolment_required` is true for a Reviewer or VP with no verified
    device; the UI uses it to show the enrolment banner. Read-only, own account.
    """
    user = request.user
    return Response(
        {
            "mfa_enrolled": mfa_policy.is_enrolled(user),
            "holds_mfa_required_role": mfa_policy.holds_mfa_required_role(user),
            "mfa_enrolment_required": mfa_policy.requires_mfa_enrolment(user),
        }
    )
