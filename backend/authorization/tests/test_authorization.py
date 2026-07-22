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
