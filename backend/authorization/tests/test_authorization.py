"""Tests for authorization endpoints."""

import pytest
from rest_framework import status

from authorization.models import MembershipRole, Permission, Role, RolePermission


@pytest.mark.django_db
class TestEffectivePermissionsView:
    def test_unauthenticated_rejected(self, api_client):
        resp = api_client.get("/api/regx/v1/permissions/effective/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_empty_when_no_roles(self, auth_client):
        resp = auth_client.get("/api/regx/v1/permissions/effective/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_returns_permissions_via_role(self, auth_client, user, membership):
        role = Role.objects.create(name="tester", tenant=membership.tenant)
        perm, _ = Permission.objects.get_or_create(
            codename="test:effective-perm", defaults={"description": "Test effective perm"}
        )
        RolePermission.objects.create(role=role, permission=perm)
        MembershipRole.objects.create(membership=membership, role=role)

        resp = auth_client.get("/api/regx/v1/permissions/effective/")
        assert resp.status_code == status.HTTP_200_OK
        codenames = [p["codename"] for p in resp.data]
        assert "test:effective-perm" in codenames

    def test_no_numeric_ids_in_response(self, auth_client):
        resp = auth_client.get("/api/regx/v1/permissions/effective/")
        assert resp.status_code == status.HTTP_200_OK
        for item in resp.data:
            assert "id" not in item
            assert "pk" not in item


@pytest.mark.django_db
class TestMyRolesView:
    """The endpoint a relying application uses to translate a REGX identity."""

    def test_unauthenticated_rejected(self, api_client):
        resp = api_client.get("/api/regx/v1/permissions/mine/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_empty_when_no_roles(self, auth_client):
        resp = auth_client.get("/api/regx/v1/permissions/mine/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {"roles": []}

    def test_returns_own_role_names(self, auth_client, membership):
        role = Role.objects.create(name=Role.BuiltIn.REVIEWER, tenant=membership.tenant)
        MembershipRole.objects.create(membership=membership, role=role)

        resp = auth_client.get("/api/regx/v1/permissions/mine/")
        assert resp.data == {"roles": ["reviewer"]}

    def test_does_not_return_another_users_roles(self, auth_client, membership):
        """The caller's roles, not the tenant's."""
        from django.contrib.auth import get_user_model

        from tenancy.models import TenantMembership

        other = get_user_model().objects.create_user(
            email="other@roles.test", password="TestPass1234!", full_name="Other"
        )
        other_membership = TenantMembership.objects.create(tenant=membership.tenant, user=other)
        role = Role.objects.create(name=Role.BuiltIn.VP, tenant=membership.tenant)
        MembershipRole.objects.create(membership=other_membership, role=role)

        resp = auth_client.get("/api/regx/v1/permissions/mine/")
        assert resp.data == {"roles": []}

    def test_inactive_membership_is_excluded(self, auth_client, membership):
        role = Role.objects.create(name=Role.BuiltIn.DOER, tenant=membership.tenant)
        MembershipRole.objects.create(membership=membership, role=role)
        membership.is_active = False
        membership.save(update_fields=["is_active"])

        resp = auth_client.get("/api/regx/v1/permissions/mine/")
        assert resp.data == {"roles": []}
