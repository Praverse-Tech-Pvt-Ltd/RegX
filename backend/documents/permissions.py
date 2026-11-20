"""
Document domain permissions.

Granular permission codenames follow the pattern documents.<action>.

Role mapping:
- doer          : create, view, upload_version
- reviewer      : create, view, upload_version, view_previous_versions, view_processing_status
                  (owner decision 2026-11-18, QA-05: Reviewers attach documents; no archive/restore)
- vp            : view, view_previous_versions, view_processing_status
- tenant_admin  : all document permissions within tenant
- platform_support : no document content access (metadata-only, future break-glass required)
"""

from rest_framework.permissions import BasePermission

from authorization.models import MembershipRole, Permission, Role
from tenancy.models import TenantMembership

# ---------------------------------------------------------------------------
# Codename constants
# ---------------------------------------------------------------------------

PERM_CREATE = "documents.create"
PERM_VIEW = "documents.view"
PERM_UPLOAD_VERSION = "documents.upload_version"
PERM_ARCHIVE = "documents.archive"
PERM_RESTORE = "documents.restore"
PERM_VIEW_PROCESSING_STATUS = "documents.view_processing_status"
PERM_VIEW_PREVIOUS_VERSIONS = "documents.view_previous_versions"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_CREATE, PERM_VIEW, PERM_UPLOAD_VERSION],
    # QA-05 (owner decision 2026-11-18): a Reviewer may attach documents (upload and add
    # a version), in its own tenant; archive and restore stay with Tenant Admin.
    Role.BuiltIn.REVIEWER: [
        PERM_CREATE,
        PERM_VIEW,
        PERM_UPLOAD_VERSION,
        PERM_VIEW_PREVIOUS_VERSIONS,
        PERM_VIEW_PROCESSING_STATUS,
    ],
    Role.BuiltIn.VP: [PERM_VIEW, PERM_VIEW_PREVIOUS_VERSIONS, PERM_VIEW_PROCESSING_STATUS],
    Role.BuiltIn.TENANT_ADMIN: [
        PERM_CREATE,
        PERM_VIEW,
        PERM_UPLOAD_VERSION,
        PERM_ARCHIVE,
        PERM_RESTORE,
        PERM_VIEW_PROCESSING_STATUS,
        PERM_VIEW_PREVIOUS_VERSIONS,
    ],
    Role.BuiltIn.PLATFORM_SUPPORT: [],  # no document content access
}


def seed_document_permissions() -> None:
    """Idempotently create Permission records for document codenames."""
    for codename in (
        PERM_CREATE,
        PERM_VIEW,
        PERM_UPLOAD_VERSION,
        PERM_ARCHIVE,
        PERM_RESTORE,
        PERM_VIEW_PROCESSING_STATUS,
        PERM_VIEW_PREVIOUS_VERSIONS,
    ):
        Permission.objects.get_or_create(codename=codename)


def has_document_permission(user, tenant, codename: str) -> bool:
    """Return True if user has the given document permission in this tenant."""
    if not user or not user.is_authenticated:
        return False

    try:
        membership = TenantMembership.objects.get(tenant=tenant, user=user, is_active=True)
    except TenantMembership.DoesNotExist:
        return False

    roles = MembershipRole.objects.filter(
        membership=membership,
    ).select_related("role")

    for mr in roles:
        allowed = ROLE_PERMISSIONS.get(mr.role.name, [])
        if codename in allowed:
            return True

    return False


# ---------------------------------------------------------------------------
# DRF permission classes
# ---------------------------------------------------------------------------


class _DocumentPermissionBase(BasePermission):
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
        return has_document_permission(request.user, tenant, self.required_codename)

    def has_object_permission(self, request, view, obj) -> bool:
        # Object-level: ensure the document belongs to the request tenant
        tenant = self._get_tenant_from_request(request)
        if not tenant:
            return False
        doc_tenant = getattr(obj, "tenant", None) or getattr(
            getattr(obj, "document", None), "tenant", None
        )
        if doc_tenant is None or doc_tenant != tenant:
            return False
        return has_document_permission(request.user, tenant, self.required_codename)


class CanCreateDocument(_DocumentPermissionBase):
    required_codename = PERM_CREATE


class CanViewDocument(_DocumentPermissionBase):
    required_codename = PERM_VIEW


class CanUploadVersion(_DocumentPermissionBase):
    required_codename = PERM_UPLOAD_VERSION


class CanArchiveDocument(_DocumentPermissionBase):
    required_codename = PERM_ARCHIVE


class CanRestoreDocument(_DocumentPermissionBase):
    required_codename = PERM_RESTORE


class CanViewProcessingStatus(_DocumentPermissionBase):
    required_codename = PERM_VIEW_PROCESSING_STATUS


class CanViewPreviousVersions(_DocumentPermissionBase):
    required_codename = PERM_VIEW_PREVIOUS_VERSIONS
