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

# Milestone 4D-2 -- Execution permissions
PERM_CREATE_EXECUTION = "iig_checklist.create_execution"
PERM_EDIT_EXECUTION = "iig_checklist.edit_execution"
PERM_SUBMIT_EXECUTION = "iig_checklist.submit_execution"
PERM_REVIEW_EXECUTION = "iig_checklist.review_execution"
PERM_APPROVE_EXECUTION = "iig_checklist.approve_execution"
PERM_CANCEL_EXECUTION = "iig_checklist.cancel_execution"
PERM_SUPERSEDE_EXECUTION = "iig_checklist.supersede_execution"
PERM_VIEW_EXECUTION = "iig_checklist.view_execution"
#: MILESTONE_4D_DISCOVERY.md §17 -- controlled export requires its own dedicated
#: permission, "not implicit from `view`", matching the
#: `fda_data.export_reconciliation` pattern. Holding view_execution must never by
#: itself confer authority to emit a checksummed regulatory artifact.
PERM_EXPORT_CHECKLIST = "iig_checklist.export_checklist"

# Deliberately NOT granted to any built-in role below. Platform-master
# checklist definitions are globally visible to every tenant, so
# authoring them requires a distinct, explicit platform-level grant --
# never inferred from ordinary Doer/Reviewer/VP/Tenant Admin/Platform
# Support role membership, and never from PERM_CREATE_DEFINITION or
# PERM_CLONE alone. See can_author_platform_master() below, which is the
# single authoritative check for this action (used by both the direct-
# create and clone code paths -- see views.py).
PERM_CREATE_PLATFORM_DEFINITION = "iig_checklist.create_platform_definition"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.BuiltIn.DOER: [
        PERM_VIEW_DEFINITION,
        PERM_CREATE_DEFINITION,
        PERM_EDIT_DRAFT,
        PERM_SUBMIT_REVIEW,
        PERM_CLONE,
        PERM_DELETE_DRAFT,
        # 4D-2
        PERM_CREATE_EXECUTION,
        PERM_EDIT_EXECUTION,
        PERM_SUBMIT_EXECUTION,
        PERM_CANCEL_EXECUTION,
        PERM_VIEW_EXECUTION,
    ],
    Role.BuiltIn.REVIEWER: [
        PERM_VIEW_DEFINITION,
        PERM_REVIEW,
        PERM_VIEW_AUDIT,
        # 4D-2
        PERM_REVIEW_EXECUTION,
        PERM_VIEW_EXECUTION,
    ],
    Role.BuiltIn.VP: [
        PERM_VIEW_DEFINITION,
        PERM_REVIEW,
        PERM_APPROVE,
        PERM_ACTIVATE,
        PERM_RETIRE,
        PERM_VIEW_AUDIT,
        # 4D-2
        PERM_APPROVE_EXECUTION,
        PERM_SUPERSEDE_EXECUTION,
        PERM_VIEW_EXECUTION,
        # 4D-4 §17. Granted to VP only, matching the established
        # templates_registry/fda_data export convention where Doer can run the
        # work and Reviewer can view it, but neither may emit the artifact.
        # Doer and Reviewer both hold PERM_VIEW_EXECUTION and still cannot
        # export, which is exactly the "not implicit from view" requirement.
        PERM_EXPORT_CHECKLIST,
    ],
    Role.BuiltIn.TENANT_ADMIN: [
        PERM_VIEW_DEFINITION,
        # 4D-2
        PERM_VIEW_EXECUTION,
    ],
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


def can_author_platform_master(user) -> bool:
    """The single, authoritative platform-level authorization check.

    Fail-closed and deliberately independent of tenant membership and of
    every ROLE_PERMISSIONS entry above: an ordinary Doer, Reviewer, VP,
    Tenant Admin, or Platform Support role -- in any tenant -- never
    satisfies this, no matter what other iig_checklist permission they
    hold. Platform-level authority is represented the same way the rest
    of this codebase represents authority that is not tenant-scoped
    (see identity/managers.py's superuser flag), rather than by
    inventing a parallel, tenant-role-shaped concept of "platform role."

    A future migration MAY additionally grant PERM_CREATE_PLATFORM_DEFINITION
    to a specific custom Role and have this function also consult
    has_iig_checklist_permission() for it -- today, no such grant exists,
    so this function is the whole story.
    """
    return bool(user and getattr(user, "is_authenticated", False) and user.is_superuser)


def can_create_definition_for_scope(*, actor, scope_type: str) -> bool:
    """Centralized scope-authorization rule for both the direct-create
    and clone code paths (views.py) -- the only place either path may
    decide whether an actor may author a definition in the given scope.
    Ordinary tenant-scoped authoring is governed by the caller's own
    PERM_CREATE_DEFINITION/PERM_CLONE check plus tenant-context scoping;
    this function governs platform_master authoring only."""
    from .enums import ChecklistScopeType

    if scope_type == ChecklistScopeType.PLATFORM_MASTER:
        return can_author_platform_master(actor)
    return True


def can_mutate_definition_scope(*, actor, definition, tenant, required_permission: str) -> bool:
    """Single authoritative object-scope mutation check for every
    governed checklist object (definition, version, section, question,
    applicability rule) that resolves to a ChecklistDefinition.

    Visibility (ChecklistDefinitionManager.visible_to() and the related
    managers built on it) deliberately exposes platform_master rows to
    every tenant so they can be *read* -- that visibility must never be
    mistaken for mutation authority. This function is the one place that
    makes the distinction:

    - the actor must hold the ordinary action permission (edit_draft,
      create_definition, submit_review, review, approve, activate,
      retire, delete_draft, ...) in their current tenant context, same
      as before this function existed;
    - if the resolved definition is platform_master, the actor must
      ALSO satisfy can_author_platform_master() -- the same platform
      grant required to create/clone platform_master content in the
      first place. Neither Reviewer/VP/Tenant Admin/Platform Support
      role membership nor an unrelated action permission ever implies
      platform authority;
    - if the resolved definition is tenant-scoped, the actor's current
      tenant context must match the definition's own tenant (defense in
      depth -- the visible_to()-based object lookups already guarantee
      this by construction, since a tenant-scoped row from a different
      tenant is never returned in the first place).

    No database writes happen here; this is a pure authorization
    decision, always evaluated before entering the mutation's
    transaction and before any audit event is emitted.
    """
    from .enums import ChecklistScopeType

    if not has_iig_checklist_permission(actor, tenant, required_permission):
        return False
    if definition.scope_type == ChecklistScopeType.PLATFORM_MASTER:
        return can_author_platform_master(actor)
    return definition.tenant_id == getattr(tenant, "id", None)


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


# 4D-2 execution permission classes
class CanCreateExecution(_IigChecklistPermissionBase):
    required_codename = PERM_CREATE_EXECUTION


class CanEditExecution(_IigChecklistPermissionBase):
    required_codename = PERM_EDIT_EXECUTION


class CanSubmitExecution(_IigChecklistPermissionBase):
    required_codename = PERM_SUBMIT_EXECUTION


class CanReviewExecution(_IigChecklistPermissionBase):
    required_codename = PERM_REVIEW_EXECUTION


class CanApproveExecution(_IigChecklistPermissionBase):
    required_codename = PERM_APPROVE_EXECUTION


class CanCancelExecution(_IigChecklistPermissionBase):
    required_codename = PERM_CANCEL_EXECUTION


class CanSupersedeExecution(_IigChecklistPermissionBase):
    required_codename = PERM_SUPERSEDE_EXECUTION


class CanViewExecution(_IigChecklistPermissionBase):
    required_codename = PERM_VIEW_EXECUTION
