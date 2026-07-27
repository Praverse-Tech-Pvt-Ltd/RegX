"""Formulations domain permissions."""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_CREATE = "formulations.create"
PERM_EDIT_DRAFT = "formulations.edit_draft"
PERM_VIEW = "formulations.view"
PERM_SUBMIT_REVIEW = "formulations.submit_review"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_VIEW, PERM_CREATE, PERM_EDIT_DRAFT, PERM_SUBMIT_REVIEW],
    Role.BuiltIn.REVIEWER: [PERM_VIEW],
    Role.BuiltIn.VP: [PERM_VIEW],
    Role.BuiltIn.TENANT_ADMIN: [PERM_VIEW, PERM_CREATE, PERM_EDIT_DRAFT, PERM_SUBMIT_REVIEW],
    Role.BuiltIn.PLATFORM_SUPPORT: [],
}


def has_formulation_permission(user, tenant, codename: str) -> bool:
    if not user or not user.is_authenticated or tenant is None:
        return False
    from authorization.models import MembershipRole
    from tenancy.models import TenantMembership

    try:
        membership = TenantMembership.objects.get(tenant=tenant, user=user, is_active=True)
    except TenantMembership.DoesNotExist:
        return False
    roles = MembershipRole.objects.filter(membership=membership).select_related("role")
    for mr in roles:
        if codename in ROLE_PERMISSIONS.get(mr.role.name, []):
            return True
    return False


class _FormulationPermissionBase(BasePermission):
    required_codename: str = ""

    def has_permission(self, request, view) -> bool:
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except (TenantScopeMissing, Exception):
            return False
        return has_formulation_permission(request.user, tenant, self.required_codename)


class CanViewFormulations(_FormulationPermissionBase):
    required_codename = PERM_VIEW


class CanCreateFormulations(_FormulationPermissionBase):
    required_codename = PERM_CREATE


class CanEditDraftFormulations(_FormulationPermissionBase):
    required_codename = PERM_EDIT_DRAFT


class CanSubmitFormulationReview(_FormulationPermissionBase):
    required_codename = PERM_SUBMIT_REVIEW
