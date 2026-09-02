"""Submission operations dashboard permissions.

Same shape as every domain app before it: dot-form codenames, an in-code role
map, a fail-closed helper and thin BasePermission subclasses. No new roles.

**THE DASHBOARD PERMISSION IS A DOOR, NOT A KEY.**

`submission_operations.view` grants exactly one thing: the right to ask. It
grants no visibility into cases, dossiers, documents, workflows, checklists,
blueprints or upgrades. Every one of those stays behind its own module's view
permission, checked independently on every request.

That distinction is the whole design. A dashboard that aggregated across modules
under a single permission would be a permission-laundering machine: read access
to seven governed domains, granted by one codename nobody reviewed as such. So
holding this and nothing else produces a page that renders, says "unavailable"
in every panel, and leaks nothing -- not even a count, because a count is an
answer.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "submission_operations.view"

ALL_PERMISSIONS = [PERM_VIEW]

#: Everyone who works a case can see the operational picture of the work they
#: are already entitled to see -- and no more, because each module re-gates
#: itself. PLATFORM_SUPPORT is included on the same terms it holds every other
#: `.view`: it can open the dashboard, and what appears inside it is decided by
#: the module permissions it separately holds.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_VIEW],
    Role.BuiltIn.REVIEWER: [PERM_VIEW],
    Role.BuiltIn.VP: [PERM_VIEW],
    Role.BuiltIn.TENANT_ADMIN: [PERM_VIEW],
    Role.BuiltIn.PLATFORM_SUPPORT: [PERM_VIEW],
}


def register_permission_codenames() -> None:
    """Register codenames for the discovery endpoint. Enforcement reads
    ROLE_PERMISSIONS, not this table."""
    from authorization.models import Permission

    for codename in ALL_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            defaults={"description": f"Submission operations: {codename.split('.', 1)[1]}"},
        )


def has_operations_permission(user, tenant, codename: str) -> bool:
    """Fail closed: no user, no tenant, no active membership -> no permission."""
    if not user or not user.is_authenticated or tenant is None:
        return False

    from authorization.models import MembershipRole
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.filter(tenant=tenant, user=user, is_active=True).first()
    if membership is None:
        return False

    role_names = MembershipRole.objects.filter(membership=membership).values_list(
        "role__name", flat=True
    )
    return any(codename in ROLE_PERMISSIONS.get(name, []) for name in role_names)


class CanViewOperations(BasePermission):
    message = "You do not have permission to view submission operations."

    def has_permission(self, request, view):
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except TenantScopeMissing:
            return False
        return has_operations_permission(request.user, tenant, PERM_VIEW)
