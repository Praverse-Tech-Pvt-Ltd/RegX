"""Dossier blueprint permissions.

Same shape as `submission_dossiers/permissions.py` and the domain apps before it:
dot-form codenames, an in-code role map, a fail-closed helper and thin
BasePermission subclasses. No new roles are invented.

**Blueprint permission grants nothing about cases or dossiers.** Instantiation
touches three domains, so it is gated three times -- see
`services.instantiate_version` and the note on the two-gate rule below.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "dossier_blueprints.view"
PERM_CREATE = "dossier_blueprints.create"
PERM_EDIT = "dossier_blueprints.edit"
PERM_MANAGE_SECTIONS = "dossier_blueprints.manage_sections"
PERM_CREATE_VERSION = "dossier_blueprints.create_version"
PERM_ACTIVATE = "dossier_blueprints.activate"
PERM_RETIRE = "dossier_blueprints.retire"
PERM_INSTANTIATE = "dossier_blueprints.instantiate"
PERM_ARCHIVE = "dossier_blueprints.archive"

ALL_PERMISSIONS = [
    PERM_VIEW,
    PERM_CREATE,
    PERM_EDIT,
    PERM_MANAGE_SECTIONS,
    PERM_CREATE_VERSION,
    PERM_ACTIVATE,
    PERM_RETIRE,
    PERM_INSTANTIATE,
    PERM_ARCHIVE,
]

#: Authoring a blueprint is ordinary build work, so DOER does it. Publishing one
#: is not: an ACTIVE version is what every future dossier in the tenant gets
#: stamped from, so activation and retirement sit with REVIEWER/VP/TENANT_ADMIN,
#: matching where "this is finished" already sits for dossiers and cases.
#:
#: Instantiation is granted widely because it creates a dossier, and creating a
#: dossier is DOER work -- but holding it is not sufficient on its own. The
#: caller must independently hold `submission_dossiers.create` and
#: `regulatory_cases.view`, checked separately.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [
        PERM_VIEW,
        PERM_CREATE,
        PERM_EDIT,
        PERM_MANAGE_SECTIONS,
        PERM_CREATE_VERSION,
        PERM_INSTANTIATE,
    ],
    Role.BuiltIn.REVIEWER: [PERM_VIEW, PERM_ACTIVATE, PERM_RETIRE, PERM_INSTANTIATE],
    Role.BuiltIn.VP: [PERM_VIEW, PERM_ACTIVATE, PERM_RETIRE, PERM_ARCHIVE],
    Role.BuiltIn.TENANT_ADMIN: ALL_PERMISSIONS,
    #: View only, exactly as for dossiers. It holds no `submission_dossiers`
    #: create permission, so it cannot instantiate even though it can read a
    #: blueprint -- which is the two-gate rule doing its job.
    Role.BuiltIn.PLATFORM_SUPPORT: [PERM_VIEW],
}


def register_permission_codenames() -> None:
    """Register codenames for the discovery endpoint. Enforcement reads
    ROLE_PERMISSIONS, not this table."""
    from authorization.models import Permission

    for codename in ALL_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            defaults={"description": f"Dossier blueprints: {codename.split('.', 1)[1]}"},
        )


def has_blueprint_permission(user, tenant, codename: str) -> bool:
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


class _BlueprintPermission(BasePermission):
    codename = ""

    def has_permission(self, request, view):
        return has_blueprint_permission(request.user, _tenant(request), self.codename)


class CanViewBlueprints(_BlueprintPermission):
    codename = PERM_VIEW


class CanCreateBlueprints(_BlueprintPermission):
    codename = PERM_CREATE


class CanEditBlueprints(_BlueprintPermission):
    codename = PERM_EDIT


class CanManageBlueprintSections(_BlueprintPermission):
    codename = PERM_MANAGE_SECTIONS


class CanCreateBlueprintVersions(_BlueprintPermission):
    codename = PERM_CREATE_VERSION


class CanActivateBlueprintVersions(_BlueprintPermission):
    codename = PERM_ACTIVATE


class CanRetireBlueprintVersions(_BlueprintPermission):
    codename = PERM_RETIRE


class CanInstantiateBlueprints(_BlueprintPermission):
    codename = PERM_INSTANTIATE


class CanArchiveBlueprints(_BlueprintPermission):
    codename = PERM_ARCHIVE
