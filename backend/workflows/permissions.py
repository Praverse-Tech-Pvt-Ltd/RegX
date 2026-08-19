"""Workflows domain permissions.

Same shape as `formulations/permissions.py`: dot-form codenames, an in-code
role map, a fail-closed helper and thin BasePermission subclasses.

On the two conventions in this repository: `authorization/seed.py` seeds
colon-form codenames (`workflow:submit`) into the `Permission` table, while all
six domain apps enforce with dot-form codenames and an in-code map. Enforcement
follows the domain apps. The three legacy `workflow:*` seed rows predate this
milestone and are deliberately left in place -- deleting seeded permissions
could strip grants from existing role assignments. See
docs/MILESTONE_6_WORKFLOW_ENGINE_DISCOVERY.md §C.
"""

from rest_framework.permissions import BasePermission

from authorization.models import Role

PERM_VIEW = "workflows.view"
PERM_CREATE = "workflows.create"
PERM_EDIT_DRAFT = "workflows.edit_draft"
PERM_SUBMIT = "workflows.submit"
PERM_REVIEW = "workflows.review"
PERM_APPROVE = "workflows.approve"
PERM_REJECT = "workflows.reject"
PERM_CANCEL = "workflows.cancel"
PERM_ASSIGN = "workflows.assign"

ALL_PERMISSIONS = [
    PERM_VIEW,
    PERM_CREATE,
    PERM_EDIT_DRAFT,
    PERM_SUBMIT,
    PERM_REVIEW,
    PERM_APPROVE,
    PERM_REJECT,
    PERM_CANCEL,
    PERM_ASSIGN,
]

#: Mirrors the intent already seeded for the legacy `workflow:*` codenames --
#: doer submits, reviewer and vp decide -- extended to the states this
#: milestone adds. No new roles are invented.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [
        PERM_VIEW,
        PERM_CREATE,
        PERM_EDIT_DRAFT,
        PERM_SUBMIT,
        PERM_CANCEL,
    ],
    Role.BuiltIn.REVIEWER: [
        PERM_VIEW,
        PERM_REVIEW,
        PERM_APPROVE,
        PERM_REJECT,
        PERM_CANCEL,
        PERM_ASSIGN,
    ],
    Role.BuiltIn.VP: [
        PERM_VIEW,
        PERM_REVIEW,
        PERM_APPROVE,
        PERM_REJECT,
        PERM_CANCEL,
        PERM_ASSIGN,
    ],
    Role.BuiltIn.TENANT_ADMIN: [
        PERM_VIEW,
        PERM_CREATE,
        PERM_EDIT_DRAFT,
        PERM_SUBMIT,
        PERM_CANCEL,
        PERM_ASSIGN,
    ],
    Role.BuiltIn.PLATFORM_SUPPORT: [PERM_VIEW],
}

#: Action -> permission required to perform it.
ACTION_PERMISSIONS = {
    "submit": PERM_SUBMIT,
    "begin_review": PERM_REVIEW,
    "approve": PERM_APPROVE,
    "reject": PERM_REJECT,
    "cancel": PERM_CANCEL,
    "return_to_draft": PERM_EDIT_DRAFT,
}


def register_permission_codenames() -> None:
    """Register codenames in the Permission table so the effective-permissions
    endpoint can surface them to the frontend, as `documents` does.

    Registration is for discovery only -- enforcement reads ROLE_PERMISSIONS.
    """
    from authorization.models import Permission

    for codename in ALL_PERMISSIONS:
        Permission.objects.get_or_create(codename=codename)


def has_workflow_permission(user, tenant, codename: str) -> bool:
    """Fail closed: no user, no tenant, no active membership -> no permission."""
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


def permitted_actions(user, tenant, structural_actions) -> list[str]:
    """Intersect structurally-legal actions with what this caller may do.

    Used to tell the UI which controls to render. It is a convenience, never the
    control: every action endpoint re-checks its own permission server-side.
    """
    return [
        action
        for action in structural_actions
        if action in ACTION_PERMISSIONS
        and has_workflow_permission(user, tenant, ACTION_PERMISSIONS[action])
    ]


class _WorkflowPermissionBase(BasePermission):
    required_codename: str = ""

    def has_permission(self, request, view) -> bool:
        from tenancy.context import current_tenant

        try:
            tenant = current_tenant()
        except Exception:
            return False
        return has_workflow_permission(request.user, tenant, self.required_codename)


class CanViewWorkflows(_WorkflowPermissionBase):
    required_codename = PERM_VIEW


class CanCreateWorkflows(_WorkflowPermissionBase):
    required_codename = PERM_CREATE


class CanEditDraftWorkflows(_WorkflowPermissionBase):
    required_codename = PERM_EDIT_DRAFT


class CanAssignWorkflows(_WorkflowPermissionBase):
    required_codename = PERM_ASSIGN
