"""IID assessment domain permissions."""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_PREVIEW = "iid_assessment.preview"
PERM_CONFIRM_MATCH = "iid_assessment.confirm_match"
PERM_OVERRIDE = "iid_assessment.override"
PERM_VIEW_CALCULATIONS = "iid_assessment.view_calculations"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_PREVIEW, PERM_VIEW_CALCULATIONS],
    Role.BuiltIn.REVIEWER: [PERM_PREVIEW, PERM_VIEW_CALCULATIONS, PERM_CONFIRM_MATCH],
    Role.BuiltIn.VP: [PERM_PREVIEW, PERM_VIEW_CALCULATIONS, PERM_CONFIRM_MATCH, PERM_OVERRIDE],
    Role.BuiltIn.TENANT_ADMIN: [PERM_PREVIEW, PERM_VIEW_CALCULATIONS],
    Role.BuiltIn.PLATFORM_SUPPORT: [],
}


def has_iid_assessment_permission(user, tenant, codename: str) -> bool:
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


class _IidAssessmentPermissionBase(BasePermission):
    required_codename: str = ""

    def has_permission(self, request, view) -> bool:
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except (TenantScopeMissing, Exception):
            return False
        return has_iid_assessment_permission(request.user, tenant, self.required_codename)


class CanPreviewIidAssessment(_IidAssessmentPermissionBase):
    required_codename = PERM_PREVIEW


class CanConfirmIidMatch(_IidAssessmentPermissionBase):
    required_codename = PERM_CONFIRM_MATCH


class CanOverrideIidAssessment(_IidAssessmentPermissionBase):
    required_codename = PERM_OVERRIDE


class CanViewIidCalculations(_IidAssessmentPermissionBase):
    required_codename = PERM_VIEW_CALCULATIONS
