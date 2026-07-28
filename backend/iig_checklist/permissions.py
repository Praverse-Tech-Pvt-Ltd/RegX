"""IIG checklist definition-governance permissions -- same
tenant-membership-role-lookup shape as fda_data/permissions.py."""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW_DEFINITION = "iig_checklist.view_definition"
PERM_CREATE_DEFINITION = "iig_checklist.create_definition"
PERM_EDIT_DRAFT = "iig_checklist.edit_draft"
PERM_SUBMIT_REVIEW = "iig_checklist.submit_review"
PERM_REVIEW = "iig_checklist.review"
PERM_APPROVE = "iig_checklist.approve"
PERM_ACTIVATE = "iig_checklist.activate"
PERM_RETIRE = "iig_checklist.retire"
PERM_CLONE = "iig_checklist.clone"
PERM_DELETE_DRAFT = "iig_checklist.delete_draft"
PERM_VIEW_AUDIT = "iig_checklist.view_audit"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [
        PERM_VIEW_DEFINITION,
        PERM_CREATE_DEFINITION,
        PERM_EDIT_DRAFT,
        PERM_SUBMIT_REVIEW,
        PERM_CLONE,
        PERM_DELETE_DRAFT,
    ],
    Role.BuiltIn.REVIEWER: [PERM_VIEW_DEFINITION, PERM_REVIEW, PERM_VIEW_AUDIT],
    Role.BuiltIn.VP: [
        PERM_VIEW_DEFINITION,
        PERM_REVIEW,
        PERM_APPROVE,
        PERM_ACTIVATE,
        PERM_RETIRE,
        PERM_VIEW_AUDIT,
    ],
    Role.BuiltIn.TENANT_ADMIN: [PERM_VIEW_DEFINITION],
    Role.BuiltIn.PLATFORM_SUPPORT: [],
}


def has_iig_checklist_permission(user, tenant, codename: str) -> bool:
    """Fail-closed: same tenant-membership-based role lookup as
    fda_data. Platform-master content is still governed by a role held
    within *some* tenant the acting user belongs to -- this codebase has
    no role concept independent of tenant membership, so platform-level
    grants are represented the same way fda_data's platform-level data
    already is."""
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


class _IigChecklistPermissionBase(BasePermission):
    required_codename: str = ""

    def has_permission(self, request, view) -> bool:
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except (TenantScopeMissing, Exception):
            return False
        return has_iig_checklist_permission(request.user, tenant, self.required_codename)


class CanViewChecklistDefinition(_IigChecklistPermissionBase):
    required_codename = PERM_VIEW_DEFINITION


class CanCreateChecklistDefinition(_IigChecklistPermissionBase):
    required_codename = PERM_CREATE_DEFINITION


class CanEditChecklistDraft(_IigChecklistPermissionBase):
    required_codename = PERM_EDIT_DRAFT


class CanSubmitChecklistReview(_IigChecklistPermissionBase):
    required_codename = PERM_SUBMIT_REVIEW


class CanReviewChecklist(_IigChecklistPermissionBase):
    required_codename = PERM_REVIEW


class CanApproveChecklist(_IigChecklistPermissionBase):
    required_codename = PERM_APPROVE


class CanActivateChecklist(_IigChecklistPermissionBase):
    required_codename = PERM_ACTIVATE


class CanRetireChecklist(_IigChecklistPermissionBase):
    required_codename = PERM_RETIRE


class CanCloneChecklist(_IigChecklistPermissionBase):
    required_codename = PERM_CLONE


class CanDeleteChecklistDraft(_IigChecklistPermissionBase):
    required_codename = PERM_DELETE_DRAFT


class CanViewChecklistAudit(_IigChecklistPermissionBase):
    required_codename = PERM_VIEW_AUDIT
