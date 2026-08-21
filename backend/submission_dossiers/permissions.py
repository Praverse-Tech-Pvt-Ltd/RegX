"""Submission dossier permissions.

Same shape as `regulatory_cases/permissions.py` and the domain apps before it:
dot-form codenames, an in-code role map, a fail-closed helper and thin
BasePermission subclasses.

**Dossier permission grants nothing about linked resources.** Seeing a section
never implies seeing its documents, workflows or checklists -- each is gated by
that module's own permission, checked independently, for reading AND for
linking. Milestone 8 shipped that gate for reads but not for writes, which made
its link endpoint an existence oracle; that mistake is not repeated here.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "submission_dossiers.view"
PERM_CREATE = "submission_dossiers.create"
PERM_EDIT = "submission_dossiers.edit"
PERM_MANAGE_SECTIONS = "submission_dossiers.manage_sections"
PERM_MANAGE_LINKS = "submission_dossiers.manage_links"
PERM_MANAGE_BLOCKERS = "submission_dossiers.manage_blockers"
PERM_COMPLETE = "submission_dossiers.complete"
PERM_CANCEL = "submission_dossiers.cancel"

ALL_PERMISSIONS = [
    PERM_VIEW,
    PERM_CREATE,
    PERM_EDIT,
    PERM_MANAGE_SECTIONS,
    PERM_MANAGE_LINKS,
    PERM_MANAGE_BLOCKERS,
    PERM_COMPLETE,
    PERM_CANCEL,
]

#: Mirrors the split already expressed for regulatory cases: DOER builds the
#: dossier, REVIEWER and VP decide it is finished, TENANT_ADMIN administers,
#: PLATFORM_SUPPORT observes without content access. No new roles are invented
#: and no existing role gains a capability it did not already have in kind.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [
        PERM_VIEW,
        PERM_CREATE,
        PERM_EDIT,
        PERM_MANAGE_SECTIONS,
        PERM_MANAGE_LINKS,
        PERM_MANAGE_BLOCKERS,
    ],
    Role.BuiltIn.REVIEWER: [PERM_VIEW, PERM_MANAGE_BLOCKERS, PERM_COMPLETE],
    Role.BuiltIn.VP: [PERM_VIEW, PERM_COMPLETE, PERM_CANCEL],
    Role.BuiltIn.TENANT_ADMIN: ALL_PERMISSIONS,
    #: View only, and holds no document or checklist permission anywhere in the
    #: platform -- so the projection gives it opaque references and nothing else.
    Role.BuiltIn.PLATFORM_SUPPORT: [PERM_VIEW],
}


def register_permission_codenames() -> None:
    """Register codenames for the discovery endpoint. Enforcement reads
    ROLE_PERMISSIONS, not this table."""
    from authorization.models import Permission

    for codename in ALL_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            defaults={"description": f"Submission dossiers: {codename.split('.', 1)[1]}"},
        )


def has_dossier_permission(user, tenant, codename: str) -> bool:
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


class _DossierPermission(BasePermission):
    codename = ""

    def has_permission(self, request, view):
        return has_dossier_permission(request.user, _tenant(request), self.codename)


class CanViewDossiers(_DossierPermission):
    codename = PERM_VIEW


class CanCreateDossiers(_DossierPermission):
    codename = PERM_CREATE


class CanEditDossiers(_DossierPermission):
    codename = PERM_EDIT


class CanManageSections(_DossierPermission):
    codename = PERM_MANAGE_SECTIONS


class CanManageSectionLinks(_DossierPermission):
    codename = PERM_MANAGE_LINKS


class CanManageBlockers(_DossierPermission):
    codename = PERM_MANAGE_BLOCKERS


class CanCompleteDossiers(_DossierPermission):
    codename = PERM_COMPLETE


class CanCancelDossiers(_DossierPermission):
    codename = PERM_CANCEL
