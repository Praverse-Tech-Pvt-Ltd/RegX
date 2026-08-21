"""Regulatory case permissions.

Same shape as `workflows/permissions.py` and the five other domain apps:
dot-form codenames, an in-code role map, a fail-closed helper and thin
BasePermission subclasses.

**The separation that matters most here.** Holding a case permission grants
nothing about the resources a case links to. Seeing a case never implies seeing
its documents, its workflows or its checklists -- each is gated by that module's
own permission, checked independently. This is the same principle Milestone 7
applied to evidence, applied three times over.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "regulatory_cases.view"
PERM_CREATE = "regulatory_cases.create"
PERM_EDIT = "regulatory_cases.edit"
PERM_MANAGE_LINKS = "regulatory_cases.manage_links"
PERM_COMPLETE = "regulatory_cases.complete"
PERM_CANCEL = "regulatory_cases.cancel"

ALL_PERMISSIONS = [
    PERM_VIEW,
    PERM_CREATE,
    PERM_EDIT,
    PERM_MANAGE_LINKS,
    PERM_COMPLETE,
    PERM_CANCEL,
]

#: Mirrors the intent already expressed for workflows: DOER does the work,
#: REVIEWER and VP decide, TENANT_ADMIN administers, PLATFORM_SUPPORT observes
#: without content access. No new roles are invented.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [
        PERM_VIEW,
        PERM_CREATE,
        PERM_EDIT,
        PERM_MANAGE_LINKS,
    ],
    Role.BuiltIn.REVIEWER: [
        PERM_VIEW,
        PERM_COMPLETE,
    ],
    Role.BuiltIn.VP: [
        PERM_VIEW,
        PERM_COMPLETE,
        PERM_CANCEL,
    ],
    Role.BuiltIn.TENANT_ADMIN: [
        PERM_VIEW,
        PERM_CREATE,
        PERM_EDIT,
        PERM_MANAGE_LINKS,
        PERM_COMPLETE,
        PERM_CANCEL,
    ],
    #: Can see that cases exist. Holds no document, workflow or checklist
    #: permission anywhere in the platform, so the projection layer gives it
    #: opaque references and nothing else -- the same posture it has toward
    #: workflow evidence.
    Role.BuiltIn.PLATFORM_SUPPORT: [PERM_VIEW],
}


def register_permission_codenames() -> None:
    """Register codenames in the Permission table for discovery endpoints.

    Enforcement does not read that table -- it reads ROLE_PERMISSIONS below --
    so this exists purely so `/permissions/` can list what the platform defines.
    """
    from authorization.models import Permission

    for codename in ALL_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            defaults={"description": f"Regulatory cases: {codename.split('.', 1)[1]}"},
        )


def has_case_permission(user, tenant, codename: str) -> bool:
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


class _CasePermission(BasePermission):
    codename = ""

    def has_permission(self, request, view):
        return has_case_permission(request.user, _tenant(request), self.codename)


class CanViewCases(_CasePermission):
    codename = PERM_VIEW


class CanCreateCases(_CasePermission):
    codename = PERM_CREATE


class CanEditCases(_CasePermission):
    codename = PERM_EDIT


class CanManageCaseLinks(_CasePermission):
    codename = PERM_MANAGE_LINKS


class CanCompleteCases(_CasePermission):
    codename = PERM_COMPLETE


class CanCancelCases(_CasePermission):
    codename = PERM_CANCEL
