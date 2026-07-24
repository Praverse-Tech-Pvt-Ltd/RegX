"""
Template registry domain permissions.

Role mapping (per Milestone 3 spec):
- doer               : inventory and prepare imports where authorized;
                        cannot approve/activate
- reviewer           : review normalization/reconciliation; cannot
                        activate unless separately authorized
- vp                 : approve, activate, supersede, retire
- tenant_admin       : manage assignments; cannot bypass approval rules
- platform_support   : no automatic content access (metadata-only; no
                        approved future support-access process exists yet)
"""

from rest_framework.permissions import BasePermission

from authorization.models import MembershipRole, Role
from tenancy.models import TenantMembership

PERM_INVENTORY = "templates.inventory"
PERM_IMPORT = "templates.import"
PERM_VIEW_RAW = "templates.view_raw"
PERM_NORMALIZE = "templates.normalize"
PERM_REVIEW = "templates.review"
PERM_APPROVE = "templates.approve"
PERM_ACTIVATE = "templates.activate"
PERM_SUPERSEDE = "templates.supersede"
PERM_RETIRE = "templates.retire"
PERM_EXPORT_RECONCILIATION = "templates.export_reconciliation"

# Base view permission is implied by any of these -- there is no separate
# "templates.view" codename; read access follows from having any role at
# all in the tenant (enforced by requiring tenant membership, not a
# specific permission, for the plain list/detail endpoints).
PERM_VIEW = "templates.view"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_VIEW, PERM_INVENTORY, PERM_IMPORT],
    Role.BuiltIn.REVIEWER: [PERM_VIEW, PERM_VIEW_RAW, PERM_NORMALIZE, PERM_REVIEW],
    Role.BuiltIn.VP: [
        PERM_VIEW,
        PERM_VIEW_RAW,
        PERM_REVIEW,
        PERM_APPROVE,
        PERM_ACTIVATE,
        PERM_SUPERSEDE,
        PERM_RETIRE,
        PERM_EXPORT_RECONCILIATION,
    ],
    Role.BuiltIn.TENANT_ADMIN: [
        PERM_VIEW,
        PERM_INVENTORY,
        PERM_IMPORT,
        PERM_VIEW_RAW,
        PERM_NORMALIZE,
        PERM_REVIEW,
        PERM_EXPORT_RECONCILIATION,
        # Deliberately excludes PERM_APPROVE/PERM_ACTIVATE/PERM_SUPERSEDE/
        # PERM_RETIRE -- tenant admins manage assignments, they do not
        # bypass the regulatory approval chain.
    ],
    Role.BuiltIn.PLATFORM_SUPPORT: [],  # no content access
}


def has_template_permission(user, tenant, codename: str) -> bool:
    """Return True if user has the given template-registry permission in
    this tenant. Fail-closed: any missing user/tenant/membership/role
    returns False."""
    if not user or not user.is_authenticated:
        return False
    if tenant is None:
        return False

    try:
        membership = TenantMembership.objects.get(tenant=tenant, user=user, is_active=True)
    except TenantMembership.DoesNotExist:
        return False

    roles = MembershipRole.objects.filter(membership=membership).select_related("role")
    for mr in roles:
        if codename in ROLE_PERMISSIONS.get(mr.role.name, []):
            return True
    return False


def user_roles_in_tenant(user, tenant) -> list[str]:
    """Return the list of role names the user holds in this tenant."""
    if not user or not user.is_authenticated or tenant is None:
        return []
    try:
        membership = TenantMembership.objects.get(tenant=tenant, user=user, is_active=True)
    except TenantMembership.DoesNotExist:
        return []
    return list(
        MembershipRole.objects.filter(membership=membership).values_list("role__name", flat=True)
    )


class _TemplatePermissionBase(BasePermission):
    required_codename: str = ""

    def _get_tenant_from_request(self, request):
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            return current_tenant()
        except (TenantScopeMissing, Exception):
            return None

    def has_permission(self, request, view) -> bool:
        tenant = self._get_tenant_from_request(request)
        if not tenant:
            return False
        return has_template_permission(request.user, tenant, self.required_codename)


class CanViewTemplates(_TemplatePermissionBase):
    required_codename = PERM_VIEW


class CanInventorySources(_TemplatePermissionBase):
    required_codename = PERM_INVENTORY


class CanImportSources(_TemplatePermissionBase):
    required_codename = PERM_IMPORT


class CanViewRawSource(_TemplatePermissionBase):
    required_codename = PERM_VIEW_RAW


class CanNormalize(_TemplatePermissionBase):
    required_codename = PERM_NORMALIZE


class CanReview(_TemplatePermissionBase):
    required_codename = PERM_REVIEW


class CanApprove(_TemplatePermissionBase):
    required_codename = PERM_APPROVE


class CanActivate(_TemplatePermissionBase):
    required_codename = PERM_ACTIVATE


class CanSupersede(_TemplatePermissionBase):
    required_codename = PERM_SUPERSEDE


class CanRetire(_TemplatePermissionBase):
    required_codename = PERM_RETIRE


class CanExportReconciliation(_TemplatePermissionBase):
    required_codename = PERM_EXPORT_RECONCILIATION
