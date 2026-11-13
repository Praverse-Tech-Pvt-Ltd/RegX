"""
Role -> permission matrix tests for the template registry domain.

Verifies the exact mapping from Milestone 3 section 4: Doer can
inventory/import but not approve/activate; Reviewer can review but not
activate; VP can approve/activate/supersede/retire/export reconciliation;
Tenant Admin can inventory/import/review/export but not approve/activate/
supersede/retire; Platform Support has no content access at all.
"""

import pytest

from templates_registry.permissions import (
    PERM_ACTIVATE,
    PERM_APPROVE,
    PERM_EXPORT_RECONCILIATION,
    PERM_IMPORT,
    PERM_INVENTORY,
    PERM_NORMALIZE,
    PERM_RETIRE,
    PERM_REVIEW,
    PERM_SUPERSEDE,
    PERM_VIEW,
    PERM_VIEW_RAW,
    has_template_permission,
)


@pytest.mark.django_db
class TestDoerPermissions:
    def test_doer_has_inventory_and_import(self, tenant_a, user_a, doer_membership):
        assert has_template_permission(user_a, tenant_a, PERM_VIEW)
        assert has_template_permission(user_a, tenant_a, PERM_INVENTORY)
        assert has_template_permission(user_a, tenant_a, PERM_IMPORT)

    def test_doer_cannot_approve_or_activate(self, tenant_a, user_a, doer_membership):
        # PLANTED VIOLATION (detected): doer attempting approve/activate.
        assert not has_template_permission(user_a, tenant_a, PERM_APPROVE)
        assert not has_template_permission(user_a, tenant_a, PERM_ACTIVATE)
        assert not has_template_permission(user_a, tenant_a, PERM_SUPERSEDE)
        assert not has_template_permission(user_a, tenant_a, PERM_RETIRE)
        assert not has_template_permission(user_a, tenant_a, PERM_EXPORT_RECONCILIATION)


@pytest.mark.django_db
class TestReviewerPermissions:
    def test_reviewer_has_review_and_view_raw(self, tenant_a, reviewer_user, reviewer_membership):
        assert has_template_permission(reviewer_user, tenant_a, PERM_VIEW_RAW)
        assert has_template_permission(reviewer_user, tenant_a, PERM_NORMALIZE)
        assert has_template_permission(reviewer_user, tenant_a, PERM_REVIEW)

    def test_reviewer_cannot_activate_without_separate_authorization(
        self, tenant_a, reviewer_user, reviewer_membership
    ):
        # PLANTED VIOLATION (detected): reviewer attempting activation.
        assert not has_template_permission(reviewer_user, tenant_a, PERM_ACTIVATE)
        assert not has_template_permission(reviewer_user, tenant_a, PERM_APPROVE)
        assert not has_template_permission(reviewer_user, tenant_a, PERM_IMPORT)


@pytest.mark.django_db
class TestVPPermissions:
    def test_vp_has_full_approval_chain(self, tenant_a, vp_user, vp_membership):
        for perm in (
            PERM_VIEW,
            PERM_VIEW_RAW,
            PERM_REVIEW,
            PERM_APPROVE,
            PERM_ACTIVATE,
            PERM_SUPERSEDE,
            PERM_RETIRE,
            PERM_EXPORT_RECONCILIATION,
        ):
            assert has_template_permission(vp_user, tenant_a, perm), perm

    def test_vp_cannot_inventory_or_import(self, tenant_a, vp_user, vp_membership):
        # VP approves/activates content prepared by a Doer -- it does not
        # itself run the inventory/import steps.
        assert not has_template_permission(vp_user, tenant_a, PERM_INVENTORY)
        assert not has_template_permission(vp_user, tenant_a, PERM_IMPORT)


@pytest.mark.django_db
class TestTenantAdminPermissions:
    def test_tenant_admin_can_manage_assignments_but_not_bypass_approval(
        self, tenant_a, user_b, tenant_admin_membership
    ):
        assert has_template_permission(user_b, tenant_a, PERM_INVENTORY)
        assert has_template_permission(user_b, tenant_a, PERM_IMPORT)
        assert has_template_permission(user_b, tenant_a, PERM_REVIEW)
        assert has_template_permission(user_b, tenant_a, PERM_EXPORT_RECONCILIATION)

        # PLANTED VIOLATION (detected): tenant admin attempting to bypass
        # the regulatory approval chain.
        assert not has_template_permission(user_b, tenant_a, PERM_APPROVE)
        assert not has_template_permission(user_b, tenant_a, PERM_ACTIVATE)
        assert not has_template_permission(user_b, tenant_a, PERM_SUPERSEDE)
        assert not has_template_permission(user_b, tenant_a, PERM_RETIRE)


@pytest.mark.django_db
class TestPlatformSupportAndFailClosed:
    def test_platform_support_has_no_content_access(self, tenant_a, user_a):
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=user_a)
        role, _ = Role.objects.get_or_create(
            tenant=None, name="platform_support", defaults={"is_system": True}
        )
        MembershipRole.objects.get_or_create(membership=membership, role=role)

        for perm in (PERM_VIEW, PERM_INVENTORY, PERM_IMPORT, PERM_VIEW_RAW, PERM_APPROVE):
            assert not has_template_permission(user_a, tenant_a, perm)

    def test_fail_closed_for_unauthenticated_or_missing_tenant(self, tenant_a, user_a):
        assert has_template_permission(None, tenant_a, PERM_VIEW) is False
        assert has_template_permission(user_a, None, PERM_VIEW) is False

    def test_fail_closed_for_user_with_no_membership(self, tenant_a, user_a):
        # user_a exists but has no TenantMembership/role at all in tenant_a.
        assert has_template_permission(user_a, tenant_a, PERM_VIEW) is False

    def test_inactive_membership_denied(self, tenant_a, user_a):
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        membership = TenantMembership.objects.create(tenant=tenant_a, user=user_a, is_active=False)
        role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
        MembershipRole.objects.create(membership=membership, role=role)
        # PLANTED VIOLATION (detected): a deactivated membership must not
        # grant permission even though a role assignment still exists.
        assert has_template_permission(user_a, tenant_a, PERM_APPROVE) is False
