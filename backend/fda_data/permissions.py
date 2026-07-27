"""FDA data-governance domain permissions.

Platform-level reference data: any authenticated tenant member may VIEW
active/approved FDA data (read-only), but only elevated roles may
register/import/review/approve/activate/export it. Tenant users can never
edit platform FDA master data regardless of role.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "fda_data.view"
PERM_REGISTER = "fda_data.register"
PERM_IMPORT = "fda_data.import"
PERM_REVIEW = "fda_data.review"
PERM_APPROVE = "fda_data.approve"
PERM_ACTIVATE = "fda_data.activate"
PERM_VIEW_RAW = "fda_data.view_raw"
PERM_EXPORT_RECONCILIATION = "fda_data.export_reconciliation"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_VIEW, PERM_REGISTER, PERM_IMPORT],
    Role.BuiltIn.REVIEWER: [PERM_VIEW, PERM_VIEW_RAW, PERM_REVIEW, PERM_EXPORT_RECONCILIATION],
    Role.BuiltIn.VP: [
        PERM_VIEW,
        PERM_VIEW_RAW,
        PERM_REVIEW,
        PERM_APPROVE,
        PERM_ACTIVATE,
        PERM_EXPORT_RECONCILIATION,
    ],
    Role.BuiltIn.TENANT_ADMIN: [PERM_VIEW],  # cannot bypass FDA data approval chain
    Role.BuiltIn.PLATFORM_SUPPORT: [],
}


def has_fda_data_permission(user, tenant, codename: str) -> bool:
    """Fail-closed: reuses the same tenant-membership-based role lookup as
    templates_registry, just against this domain's own ROLE_PERMISSIONS
    map (FDA data has no tenant-owned rows, but the acting user must still
    be an active member of SOME tenant holding the required role)."""
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


class _FdaDataPermissionBase(BasePermission):
    required_codename: str = ""

    def has_permission(self, request, view) -> bool:
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except (TenantScopeMissing, Exception):
            return False
        return has_fda_data_permission(request.user, tenant, self.required_codename)


class CanViewFdaData(_FdaDataPermissionBase):
    required_codename = PERM_VIEW


class CanRegisterFdaData(_FdaDataPermissionBase):
    required_codename = PERM_REGISTER


class CanImportFdaData(_FdaDataPermissionBase):
    required_codename = PERM_IMPORT


class CanReviewFdaData(_FdaDataPermissionBase):
    required_codename = PERM_REVIEW


class CanApproveFdaData(_FdaDataPermissionBase):
    required_codename = PERM_APPROVE


class CanActivateFdaData(_FdaDataPermissionBase):
    required_codename = PERM_ACTIVATE


class CanViewRawFdaData(_FdaDataPermissionBase):
    required_codename = PERM_VIEW_RAW


class CanExportFdaReconciliation(_FdaDataPermissionBase):
    required_codename = PERM_EXPORT_RECONCILIATION


class CanProposeSubstanceMapping(BasePermission):
    """Proposing a substance/UNII synonym mapping candidate requires either
    import or review standing -- a Doer who just imported a release and
    noticed an unresolved identity, or a Reviewer proactively proposing a
    correction, may both propose. Proposing never itself approves anything
    (see mapping_transitions.py) -- this permission only gates creating a
    new PROPOSED row, never a status transition."""

    def has_permission(self, request, view) -> bool:
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except (TenantScopeMissing, Exception):
            return False
        return has_fda_data_permission(
            request.user, tenant, PERM_IMPORT
        ) or has_fda_data_permission(request.user, tenant, PERM_REVIEW)
