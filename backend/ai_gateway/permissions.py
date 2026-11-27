"""Who may touch the AI gateway's endpoints.

* The platform switch and the metrics are platform-level: superuser only, the
  same platform grant `iig_checklist.permissions.can_author_platform_master`
  uses. Metrics carry tenant identifiers across the deployment, so no tenant
  role may read them.
* The health check makes a real model call when AI is on, so it costs money:
  Tenant Admin of the current tenant only.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role


def is_platform_admin(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False) and user.is_superuser)


class IsPlatformAdmin(BasePermission):
    message = "Only a platform administrator may do this."

    def has_permission(self, request, view):
        return is_platform_admin(request.user)


class IsTenantAdmin(BasePermission):
    message = "Only a Tenant Admin may run the AI health check."

    def has_permission(self, request, view):
        from authorization.models import MembershipRole
        from tenancy.context import TenantScopeMissing, current_tenant

        user = request.user
        if not user or not user.is_authenticated:
            return False
        try:
            tenant = current_tenant()
        except TenantScopeMissing:
            return False
        return MembershipRole.objects.filter(
            membership__tenant=tenant,
            membership__user=user,
            membership__is_active=True,
            role__name=Role.BuiltIn.TENANT_ADMIN,
        ).exists()
