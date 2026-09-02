"""Submission package permissions.

Same shape as every domain app before it: dot-form codenames, an in-code role
map, a fail-closed helper and thin BasePermission subclasses. No new roles.

**PACKAGE PERMISSION IS NEVER DOCUMENT PERMISSION.** Adding an entry cites an
exact `DocumentVersion`, so it needs `submission_packages.manage_entries` AND
`documents.view`, checked independently. Exporting streams every file in the
package, so it needs `submission_packages.export` AND `documents.view` -- and if
the caller cannot retrieve one entry, the whole export is refused rather than
quietly shortened. Holding one has never implied the other and does not start
here.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "submission_packages.view"
PERM_CREATE = "submission_packages.create"
PERM_EDIT = "submission_packages.edit"
PERM_MANAGE_ENTRIES = "submission_packages.manage_entries"
PERM_REVIEW = "submission_packages.review"
PERM_FREEZE = "submission_packages.freeze"
PERM_CANCEL = "submission_packages.cancel"
PERM_EXPORT = "submission_packages.export"

ALL_PERMISSIONS = [
    PERM_VIEW,
    PERM_CREATE,
    PERM_EDIT,
    PERM_MANAGE_ENTRIES,
    PERM_REVIEW,
    PERM_FREEZE,
    PERM_CANCEL,
    PERM_EXPORT,
]

#: DOER assembles: create, edit, add and remove entries, and send for review.
#: REVIEWER looks at a finished assembly and is the role that may freeze it --
#: freezing is the act of saying "this composition is settled", which is a
#: review decision, not a build step. VP and TENANT_ADMIN can cancel and export.
#: PLATFORM_SUPPORT observes and holds no document permission of its own, so it
#: can read a package and cannot see what is in it.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [
        PERM_VIEW,
        PERM_CREATE,
        PERM_EDIT,
        PERM_MANAGE_ENTRIES,
        PERM_REVIEW,
        PERM_EXPORT,
    ],
    Role.BuiltIn.REVIEWER: [PERM_VIEW, PERM_REVIEW, PERM_FREEZE, PERM_EXPORT],
    Role.BuiltIn.VP: [PERM_VIEW, PERM_FREEZE, PERM_CANCEL, PERM_EXPORT],
    Role.BuiltIn.TENANT_ADMIN: ALL_PERMISSIONS,
    Role.BuiltIn.PLATFORM_SUPPORT: [PERM_VIEW],
}


def register_permission_codenames() -> None:
    """Register codenames for the discovery endpoint. Enforcement reads
    ROLE_PERMISSIONS, not this table."""
    from authorization.models import Permission

    for codename in ALL_PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            defaults={"description": f"Submission packages: {codename.split('.', 1)[1]}"},
        )


def has_package_permission(user, tenant, codename: str) -> bool:
    """Fail closed: no user, no tenant, no active membership -> no permission."""
    if not user or not user.is_authenticated or tenant is None:
        return False

    from authorization.models import MembershipRole
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.filter(tenant=tenant, user=user, is_active=True).first()
    if membership is None:
        return False

    role_names = MembershipRole.objects.filter(membership=membership).values_list(
        "role__name", flat=True
    )
    return any(codename in ROLE_PERMISSIONS.get(name, []) for name in role_names)


class _PackagePermission(BasePermission):
    codename = PERM_VIEW

    def has_permission(self, request, view):
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except TenantScopeMissing:
            return False
        return has_package_permission(request.user, tenant, self.codename)


class CanViewPackages(_PackagePermission):
    codename = PERM_VIEW
    message = "You do not have permission to view submission packages."


class CanCreatePackages(_PackagePermission):
    codename = PERM_CREATE
    message = "You do not have permission to create submission packages."


class CanEditPackages(_PackagePermission):
    codename = PERM_EDIT
    message = "You do not have permission to edit submission packages."


class CanManageEntries(_PackagePermission):
    codename = PERM_MANAGE_ENTRIES
    message = "You do not have permission to change package entries."


class CanReviewPackages(_PackagePermission):
    codename = PERM_REVIEW
    message = "You do not have permission to review submission packages."


class CanFreezePackages(_PackagePermission):
    codename = PERM_FREEZE
    message = "You do not have permission to freeze submission packages."


class CanCancelPackages(_PackagePermission):
    codename = PERM_CANCEL
    message = "You do not have permission to cancel submission packages."


class CanExportPackages(_PackagePermission):
    codename = PERM_EXPORT
    message = "You do not have permission to export submission packages."
