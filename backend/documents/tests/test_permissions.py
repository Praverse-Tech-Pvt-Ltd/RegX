"""Permission boundary tests for document domain roles."""

import pytest

from documents.permissions import (
    PERM_ARCHIVE,
    PERM_CREATE,
    PERM_RESTORE,
    PERM_UPLOAD_VERSION,
    PERM_VIEW,
    PERM_VIEW_PREVIOUS_VERSIONS,
    PERM_VIEW_PROCESSING_STATUS,
    has_document_permission,
)


@pytest.mark.django_db
class TestDoerPermissions:
    def test_doer_can_create(self, user_a, tenant_a, doer_membership):
        assert has_document_permission(user_a, tenant_a, PERM_CREATE)

    def test_doer_can_view(self, user_a, tenant_a, doer_membership):
        assert has_document_permission(user_a, tenant_a, PERM_VIEW)

    def test_doer_can_upload_version(self, user_a, tenant_a, doer_membership):
        assert has_document_permission(user_a, tenant_a, PERM_UPLOAD_VERSION)

    def test_doer_cannot_archive(self, user_a, tenant_a, doer_membership):
        # PLANTED: doer does not have archive permission
        assert not has_document_permission(user_a, tenant_a, PERM_ARCHIVE)

    def test_doer_cannot_restore(self, user_a, tenant_a, doer_membership):
        assert not has_document_permission(user_a, tenant_a, PERM_RESTORE)


@pytest.mark.django_db
class TestReviewerPermissions:
    def test_reviewer_can_view(self, user_b, tenant_a, reviewer_membership):
        assert has_document_permission(user_b, tenant_a, PERM_VIEW)

    def test_reviewer_can_view_previous_versions(self, user_b, tenant_a, reviewer_membership):
        assert has_document_permission(user_b, tenant_a, PERM_VIEW_PREVIOUS_VERSIONS)

    def test_reviewer_can_view_processing_status(self, user_b, tenant_a, reviewer_membership):
        assert has_document_permission(user_b, tenant_a, PERM_VIEW_PROCESSING_STATUS)

    def test_reviewer_cannot_create(self, user_b, tenant_a, reviewer_membership):
        # PLANTED: reviewer cannot create documents
        assert not has_document_permission(user_b, tenant_a, PERM_CREATE)

    def test_reviewer_cannot_upload_version(self, user_b, tenant_a, reviewer_membership):
        assert not has_document_permission(user_b, tenant_a, PERM_UPLOAD_VERSION)

    def test_reviewer_cannot_archive(self, user_b, tenant_a, reviewer_membership):
        assert not has_document_permission(user_b, tenant_a, PERM_ARCHIVE)


@pytest.mark.django_db
class TestTenantAdminPermissions:
    def test_admin_has_all_document_permissions(self, user_a, tenant_a, admin_membership):
        for perm in (
            PERM_CREATE,
            PERM_VIEW,
            PERM_UPLOAD_VERSION,
            PERM_ARCHIVE,
            PERM_RESTORE,
            PERM_VIEW_PROCESSING_STATUS,
            PERM_VIEW_PREVIOUS_VERSIONS,
        ):
            assert has_document_permission(user_a, tenant_a, perm), f"Admin missing: {perm}"


@pytest.mark.django_db
class TestPlatformSupportPermissions:
    def test_platform_support_has_no_document_permissions(self, db):
        from django.contrib.auth import get_user_model

        from authorization.models import MembershipRole, Role
        from tenancy.models import Tenant, TenantMembership

        User = get_user_model()
        user = User.objects.create_user(email="support@example.com", password="Pass1234!")
        tenant = Tenant.objects.create(name="Support Tenant", slug="support-tenant")
        membership = TenantMembership.objects.create(tenant=tenant, user=user)
        role, _ = Role.objects.get_or_create(
            name="platform_support",
            tenant=tenant,
            defaults={"is_system": True},
        )
        MembershipRole.objects.create(membership=membership, role=role)

        # PLANTED: platform support cannot access document content
        for perm in (PERM_CREATE, PERM_VIEW, PERM_UPLOAD_VERSION, PERM_ARCHIVE, PERM_RESTORE):
            assert not has_document_permission(user, tenant, perm), f"Support wrongly has: {perm}"


@pytest.mark.django_db
class TestCrossTenantPermissions:
    def test_user_in_tenant_a_has_no_access_in_tenant_b(
        self, user_a, tenant_a, tenant_b, doer_membership
    ):
        # PLANTED: cross-tenant permission check
        assert not has_document_permission(user_a, tenant_b, PERM_VIEW)
        assert not has_document_permission(user_a, tenant_b, PERM_CREATE)

    def test_unauthenticated_user_has_no_permissions(self, tenant_a):
        from django.contrib.auth.models import AnonymousUser

        anon = AnonymousUser()
        assert not has_document_permission(anon, tenant_a, PERM_VIEW)
