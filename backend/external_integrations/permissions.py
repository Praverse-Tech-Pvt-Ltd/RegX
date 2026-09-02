"""External integration permissions.

Same shape as every domain app before it: dot-form codenames, an in-code role
map, a fail-closed helper, thin `BasePermission` subclasses. No new roles, and
no change to owner policy.

**CONNECTOR PERMISSION IS NEVER CONTENT PERMISSION.** Being allowed to run a
connector says nothing about being allowed to see what it carries. Transferring
a frozen package moves every cited document out of the deployment, so it needs
`external_integrations.execute` AND `submission_packages.export` AND
`documents.view`, each checked independently against its own app's role map.
Importing a document creates one, so it needs `external_integrations.execute`
AND `documents.create`.

That is the M13 lesson generalised: a caller who could not read a document
through the documents API must not be able to read it by asking a connector to
send it somewhere, and a caller who could not create a document must not be able
to create one by asking a connector to fetch it.

**CONFIGURING A DESTINATION IS AN ELEVATED ACT.** A connector points the server
at a network address and names a credential, so `create`, `edit` and `enable`
sit with TENANT_ADMIN alone. DOER can run an existing connector and read its
history; REVIEWER and VP can watch. PLATFORM_SUPPORT can see that connectors
exist and cannot run one -- and holds no document permission anywhere, so it
could not see the contents either way.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "external_integrations.view"
PERM_CREATE = "external_integrations.create"
PERM_EDIT = "external_integrations.edit"
PERM_ENABLE = "external_integrations.enable"
PERM_TEST = "external_integrations.test"
PERM_EXECUTE = "external_integrations.execute"
PERM_VIEW_HISTORY = "external_integrations.view_history"

ALL_PERMISSIONS = [
    PERM_VIEW,
    PERM_CREATE,
    PERM_EDIT,
    PERM_ENABLE,
    PERM_TEST,
    PERM_EXECUTE,
    PERM_VIEW_HISTORY,
]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [PERM_VIEW, PERM_TEST, PERM_EXECUTE, PERM_VIEW_HISTORY],
    Role.BuiltIn.REVIEWER: [PERM_VIEW, PERM_VIEW_HISTORY],
    Role.BuiltIn.VP: [PERM_VIEW, PERM_VIEW_HISTORY],
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
            defaults={"description": f"External integrations: {codename.split('.', 1)[1]}"},
        )


def has_integration_permission(user, tenant, codename: str) -> bool:
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


def may_view_documents(user, tenant) -> bool:
    """Delegated to the documents app, never reimplemented here.

    Copying another app's role map would mean this one drifts, and the drift
    would be silent and in the permissive direction.
    """
    from documents.permissions import has_document_permission

    return has_document_permission(user, tenant, "documents.view")


def may_create_documents(user, tenant) -> bool:
    from documents.permissions import has_document_permission

    return has_document_permission(user, tenant, "documents.create")


def may_export_packages(user, tenant) -> bool:
    from submission_packages.permissions import PERM_EXPORT, has_package_permission

    return has_package_permission(user, tenant, PERM_EXPORT)


class _IntegrationPermission(BasePermission):
    codename = PERM_VIEW

    def has_permission(self, request, view):
        from tenancy.context import TenantScopeMissing, current_tenant

        try:
            tenant = current_tenant()
        except TenantScopeMissing:
            return False
        return has_integration_permission(request.user, tenant, self.codename)


class CanViewConnectors(_IntegrationPermission):
    codename = PERM_VIEW
    message = "You do not have permission to view external integrations."


class CanCreateConnectors(_IntegrationPermission):
    codename = PERM_CREATE
    message = "You do not have permission to create external integrations."


class CanEditConnectors(_IntegrationPermission):
    codename = PERM_EDIT
    message = "You do not have permission to change external integrations."


class CanEnableConnectors(_IntegrationPermission):
    codename = PERM_ENABLE
    message = "You do not have permission to enable or disable external integrations."


class CanTestConnectors(_IntegrationPermission):
    codename = PERM_TEST
    message = "You do not have permission to test external integrations."


class CanExecuteConnectors(_IntegrationPermission):
    codename = PERM_EXECUTE
    message = "You do not have permission to run external integrations."


class CanViewExecutionHistory(_IntegrationPermission):
    codename = PERM_VIEW_HISTORY
    message = "You do not have permission to view external integration history."
