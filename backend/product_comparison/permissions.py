"""Product comparison permissions.

Same shape as the other domain apps: dot-form codenames, an in-code role map, a
fail-closed helper and thin BasePermission subclasses.

Unlike the FDA reference corpora, a comparison is the tenant's own work, so
writing is a tenant capability. Doers create and edit; reviewers and VPs read.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "product_comparison.view"
PERM_MANAGE = "product_comparison.manage"

ALL_PERMISSIONS = [PERM_VIEW, PERM_MANAGE]

#: Which built-in roles hold which permission.
ROLE_PERMISSIONS = {
    Role.BuiltIn.DOER: {PERM_VIEW, PERM_MANAGE},
    Role.BuiltIn.REVIEWER: {PERM_VIEW},
    Role.BuiltIn.VP: {PERM_VIEW},
    Role.BuiltIn.TENANT_ADMIN: {PERM_VIEW, PERM_MANAGE},
    Role.BuiltIn.PLATFORM_SUPPORT: {PERM_VIEW},
}


def has_product_comparison_permission(user, tenant, codename: str) -> bool:
    """Fail closed: no user, no tenant, no active membership -> no permission."""
    if not user or not user.is_authenticated or tenant is None:
        return False

    from authorization.models import MembershipRole
    from tenancy.models import TenantMembership

    try:
        membership = TenantMembership.objects.get(tenant=tenant, user=user, is_active=True)
    except TenantMembership.DoesNotExist:
        return False

    role_names = MembershipRole.objects.filter(membership=membership).values_list(
        "role__name", flat=True
    )
    for name in role_names:
        if codename in ROLE_PERMISSIONS.get(name, []):
            return True
    return False


def _tenant(request):
    from tenancy.context import current_tenant

    try:
        return current_tenant()
    except Exception:
        return None


class _Base(BasePermission):
    codename = None

    def has_permission(self, request, view):
        return has_product_comparison_permission(
            getattr(request, "user", None), _tenant(request), self.codename
        )


class CanViewProductComparisons(_Base):
    codename = PERM_VIEW


class CanManageProductComparisons(_Base):
    codename = PERM_MANAGE
