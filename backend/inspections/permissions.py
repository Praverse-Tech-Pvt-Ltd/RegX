"""FDA inspection corpus permissions.

Same shape as the other domain apps: dot-form codenames, an in-code role map, a
fail-closed helper and thin BasePermission subclasses.

Read is broad -- every in-tenant role needs to consult precedent -- but write is
platform-only. A tenant cannot edit published FDA records, so there is deliberately no
tenant-admin write path here.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "inspections.view"
PERM_IMPORT = "inspections.import"

ALL_PERMISSIONS = [PERM_VIEW, PERM_IMPORT]

#: Which built-in roles hold which permission. Platform support alone may import:
#: a corpus is published reference data, not tenant content.
ROLE_PERMISSIONS = {
    Role.BuiltIn.DOER: {PERM_VIEW},
    Role.BuiltIn.REVIEWER: {PERM_VIEW},
    Role.BuiltIn.VP: {PERM_VIEW},
    Role.BuiltIn.TENANT_ADMIN: {PERM_VIEW},
    Role.BuiltIn.PLATFORM_SUPPORT: {PERM_VIEW, PERM_IMPORT},
}


def has_inspection_permission(user, tenant, codename: str) -> bool:
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
        return has_inspection_permission(
            getattr(request, "user", None), _tenant(request), self.codename
        )


class CanViewInspections(_Base):
    codename = PERM_VIEW


class CanImportInspections(_Base):
    codename = PERM_IMPORT
