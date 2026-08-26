"""Dossier upgrade permissions.

Same shape as every domain app before it: dot-form codenames, an in-code role
map, a fail-closed helper and thin BasePermission subclasses. No new roles.

**Multi-gate by design.** Applying an upgrade writes governed dossier sections,
so it needs `dossier_upgrades.apply` AND `submission_dossiers.manage_sections`,
checked independently. Generating a plan reads a blueprint version, so it needs
`dossier_upgrades.generate` AND `dossier_blueprints.view`. Holding one has never
implied the other and does not start here.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "dossier_upgrades.view"
PERM_GENERATE = "dossier_upgrades.generate"
PERM_REVIEW = "dossier_upgrades.review"
PERM_APPLY = "dossier_upgrades.apply"
PERM_CANCEL = "dossier_upgrades.cancel"

ALL_PERMISSIONS = [PERM_VIEW, PERM_GENERATE, PERM_REVIEW, PERM_APPLY, PERM_CANCEL]

#: DOER generates and applies -- moving a dossier onto a newer outline is build
#: work, and it is gated again by `submission_dossiers.manage_sections`, which
#: DOER also holds. REVIEWER decides which proposed changes are accepted, which
#: is the review act this milestone exists for. VP and TENANT_ADMIN can cancel.
#: PLATFORM_SUPPORT observes.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_VIEW, PERM_GENERATE, PERM_REVIEW, PERM_APPLY],
    Role.BuiltIn.REVIEWER: [PERM_VIEW, PERM_REVIEW, PERM_CANCEL],
    Role.BuiltIn.VP: [PERM_VIEW, PERM_CANCEL],
    Role.BuiltIn.TENANT_ADMIN: ALL_PERMISSIONS,
    #: View only, and holds no `submission_dossiers.manage_sections` anywhere,
    #: so it cannot apply even a plan it can read -- the multi-gate rule doing
    #: its job.
    Role.BuiltIn.PLATFORM_SUPPORT: [PERM_VIEW],
}


def register_permission_codenames() -> None:
    """Register codenames for the discovery endpoint. Enforcement reads
    ROLE_PERMISSIONS, not this table."""
    from authorization.models import Permission

    for codename in ALL_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            defaults={"description": f"Dossier upgrades: {codename.split('.', 1)[1]}"},
        )


def has_upgrade_permission(user, tenant, codename: str) -> bool:
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
    return any(codename in ROLE_PERMISSIONS.get(name, []) for name in role_names)


def _tenant(request):
    from tenancy.context import current_tenant

    try:
        return current_tenant()
    except Exception:
        return None


class _UpgradePermission(BasePermission):
    codename = ""

    def has_permission(self, request, view):
        return has_upgrade_permission(request.user, _tenant(request), self.codename)


class CanViewUpgrades(_UpgradePermission):
    codename = PERM_VIEW


class CanGenerateUpgrades(_UpgradePermission):
    codename = PERM_GENERATE


class CanReviewUpgrades(_UpgradePermission):
    codename = PERM_REVIEW


class CanApplyUpgrades(_UpgradePermission):
    codename = PERM_APPLY


class CanCancelUpgrades(_UpgradePermission):
    codename = PERM_CANCEL
