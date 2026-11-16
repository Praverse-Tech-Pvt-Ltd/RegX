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

    `mfa_enrolment_required` is true for a user holding a role in
    `settings.REGX_MFA_REQUIRED_ROLES` with no verified
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


#: Roles allowed to reset another user's MFA (an administrator, never the user).
MFA_RESET_ROLES = ("tenant_admin", "platform_support")
MFA_RESET_REASON_MIN = 10


@extend_schema(tags=["authorization"])
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_reset_view(request, public_id):
    """Reset another user's MFA after they lost their authenticator and recovery codes.

    Rules (all checked here, independently of the MFA middleware):
    - the caller holds tenant_admin or platform_support in an active membership
      of a tenant where the target also has an active membership;
    - the caller is a different person from the target;
    - the caller has a verified MFA device (an administrator without MFA cannot
      remove someone else's);
    - a reason of at least 10 characters is given.
    Effect: the target's MFA device and recovery codes are deleted and
    `mfa_required` cleared. A Reviewer/VP/admin target is then blocked from
    writing until they enrol again (the #107 gate). Audited as
    `identity.mfa.reset` with actor, target, shared tenant and reason. Every refusal
    is audited as `identity.mfa.reset_refused` (actor, target, refusal code).
    """
    from django.contrib.auth import get_user_model
    from django.db import transaction

    from audit.middleware import log_event
    from identity.models import MFADevice
    from tenancy.models import TenantMembership

    caller = request.user

    def refuse(error_code, detail, status_code, target=None, tenant=None):
        # Every refusal is audited: who tried, which user, why. Never the reason text,
        # codes or secrets.
        log_event(
            "identity.mfa.reset_refused",
            resource_type="user",
            resource_id=str(target.public_id) if target else str(public_id),
            payload={"by": str(caller.public_id), "refused": error_code},
            user=caller,
            tenant=tenant,
        )
        return Response({"detail": detail, "error_code": error_code}, status=status_code)

    target = get_user_model().objects.filter(public_id=public_id).first()
    if target is None:
        return refuse("not_found", "Not found.", 404)
    if target.pk == caller.pk:
        return refuse("mfa_reset_self_forbidden", "You cannot reset your own MFA.", 403, target)
    if not MFADevice.objects.filter(user=caller, is_verified=True).exists():
        return refuse(
            "mfa_required_for_reset",
            "Set up your own MFA before resetting someone else's.",
            403,
            target,
        )
    target_tenants = TenantMembership.objects.filter(user=target, is_active=True).values(
        "tenant_id"
    )
    admin_membership = (
        MembershipRole.objects.filter(
            membership__user=caller,
            membership__is_active=True,
            membership__tenant_id__in=target_tenants,
            role__name__in=MFA_RESET_ROLES,
            role__tenant__isnull=True,
        )
        .select_related("membership__tenant")
        .first()
    )
    if admin_membership is None:
        return refuse(
            "mfa_reset_forbidden",
            "Only a tenant administrator of the user's organisation can reset MFA.",
            403,
            target,
        )
    shared_tenant = admin_membership.membership.tenant
    reason = str(request.data.get("reason", "")).strip()
    if len(reason) < MFA_RESET_REASON_MIN:
        return refuse(
            "reason_required",
            "Give a reason (at least 10 characters).",
            400,
            target,
            shared_tenant,
        )
    device = MFADevice.objects.filter(user=target).first()
    if device is None:
        return refuse("no_mfa_device", "This user has no MFA device.", 409, target, shared_tenant)
    tenant = admin_membership.membership.tenant
    with transaction.atomic():
        device.delete()  # cascades to the recovery codes
        target.mfa_required = False
        target.save(update_fields=["mfa_required"])
        log_event(
            "identity.mfa.reset",
            resource_type="user",
            resource_id=str(target.public_id),
            payload={"reason": reason, "by": str(caller.public_id)},
            user=caller,
            tenant=tenant,
        )
    return Response({"detail": "MFA reset. The user must set up MFA again before acting."})
