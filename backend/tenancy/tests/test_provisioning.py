"""Accounts and tenants are created only by platform operators.

Public self-registration (`POST /auth/register/`) and self-service tenant
creation (`POST /tenants/`) are refused with a clear error code, and nothing is
created. Operators use `manage.py create_tenant` and `create_tenant_user`.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from rest_framework import status

from authorization.models import MembershipRole
from tenancy.models import Tenant, TenantMembership

REGISTER = "/api/regx/v1/auth/register/"
TENANTS = "/api/regx/v1/tenants/"
User = get_user_model()


@pytest.mark.django_db
class TestSelfRegistrationDisabled:
    def test_valid_registration_is_refused_and_creates_nothing(self, api_client):
        resp = api_client.post(
            REGISTER, {"email": "new@example.com", "password": "NewPass1234!"}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == "self_registration_disabled"
        assert "administrator" in resp.data["detail"]
        assert not User.objects.filter(email="new@example.com").exists()

    def test_signed_in_user_cannot_register_another(self, auth_client):
        resp = auth_client.post(
            REGISTER, {"email": "x@example.com", "password": "NewPass1234!"}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert not User.objects.filter(email="x@example.com").exists()

    def test_get_is_not_allowed(self, api_client):
        assert api_client.get(REGISTER).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
class TestSelfServiceTenantCreationDisabled:
    def test_signed_in_user_cannot_create_a_tenant(self, auth_client):
        resp = auth_client.post(TENANTS, {"name": "Mine", "slug": "mine"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == "tenant_creation_restricted"
        assert not Tenant.objects.filter(slug="mine").exists()
        assert not TenantMembership.objects.exists()

    def test_superuser_cannot_create_one_over_the_api_either(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        resp = api_client.post(TENANTS, {"name": "Su", "slug": "su"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert not Tenant.objects.filter(slug="su").exists()

    def test_anonymous_is_refused(self, api_client):
        resp = api_client.post(TENANTS, {"name": "Anon", "slug": "anon"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert not Tenant.objects.filter(slug="anon").exists()

    def test_listing_own_tenants_still_works(self, auth_client, membership):
        resp = auth_client.get(TENANTS)
        assert resp.status_code == status.HTTP_200_OK
        assert [t["slug"] for t in resp.data] == [membership.tenant.slug]


@pytest.mark.django_db
class TestCreateTenantCommand:
    def test_creates_a_tenant_with_no_members(self):
        call_command("create_tenant", "--slug", "acme", "--name", "Acme Pharma")
        tenant = Tenant.objects.get(slug="acme")
        assert tenant.name == "Acme Pharma"
        assert tenant.status == Tenant.Status.ACTIVE
        assert not tenant.memberships.exists()

    def test_duplicate_slug_is_refused(self, tenant):
        with pytest.raises(CommandError, match="slug: .*already exists"):
            call_command("create_tenant", "--slug", tenant.slug, "--name", "Other name")


@pytest.mark.django_db
class TestCreateTenantUserCommand:
    def test_creates_user_membership_and_roles(self, tenant, monkeypatch):
        monkeypatch.setenv("NEW_PW", "Str0ng-Enough-Pass!")
        call_command(
            "create_tenant_user", "--tenant", tenant.slug, "--email", "Rev@Acme.Example",
            "--role", "reviewer", "--role", "doer", "--full-name", "R Rev",
            "--password-env", "NEW_PW",
        )  # fmt: skip
        user = User.objects.get(email="rev@acme.example")
        assert user.check_password("Str0ng-Enough-Pass!")
        assert user.full_name == "R Rev"
        roles = MembershipRole.objects.filter(membership__user=user, membership__tenant=tenant)
        assert sorted(roles.values_list("role__name", flat=True)) == ["doer", "reviewer"]

    def test_binds_the_platform_role_not_another_tenants_copy(self, tenant, user):
        """A tenant may define its own role with a built-in name (e.g. `vp`); the
        command must still bind the platform-wide built-in. (Tenant-scoped rows
        with is_system=True are now impossible: constraint role_system_has_no_tenant.)"""
        from authorization.models import Role

        other = Tenant.objects.create(name="Other", slug="other")
        Role.objects.create(name="vp", tenant=other, is_system=False)
        call_command(
            "create_tenant_user", "--tenant", tenant.slug, "--email", user.email,
            "--role", "vp",
        )  # fmt: skip
        bound = MembershipRole.objects.get(membership__user=user, membership__tenant=tenant)
        assert bound.role.tenant is None
        assert bound.role.name == "vp"

    def test_new_user_without_password_env_is_refused(self, tenant):
        with pytest.raises(CommandError, match="--password-env"):
            call_command(
                "create_tenant_user", "--tenant", tenant.slug, "--email", "a@b.example",
                "--role", "doer",
            )  # fmt: skip
        assert not User.objects.filter(email="a@b.example").exists()

    def test_unset_password_env_is_refused(self, tenant, monkeypatch):
        monkeypatch.delenv("NOT_SET_PW", raising=False)
        with pytest.raises(CommandError, match="--password-env"):
            call_command(
                "create_tenant_user", "--tenant", tenant.slug, "--email", "a@b.example",
                "--role", "doer", "--password-env", "NOT_SET_PW",
            )  # fmt: skip

    def test_weak_password_is_refused(self, tenant, monkeypatch):
        monkeypatch.setenv("WEAK_PW", "password")
        with pytest.raises(CommandError, match="Password rejected"):
            call_command(
                "create_tenant_user", "--tenant", tenant.slug, "--email", "a@b.example",
                "--role", "doer", "--password-env", "WEAK_PW",
            )  # fmt: skip
        assert not User.objects.filter(email="a@b.example").exists()

    def test_existing_user_keeps_password_and_gains_role(self, tenant, user):
        call_command(
            "create_tenant_user", "--tenant", tenant.slug, "--email", user.email,
            "--role", "vp",
        )  # fmt: skip
        user.refresh_from_db()
        assert user.check_password("TestPass1234!")
        assert MembershipRole.objects.filter(
            membership__user=user, membership__tenant=tenant, role__name="vp"
        ).exists()

    def test_unknown_role_is_refused(self, tenant):
        with pytest.raises(CommandError):
            call_command(
                "create_tenant_user", "--tenant", tenant.slug, "--email", "a@b.example",
                "--role", "superadmin",
            )  # fmt: skip

    def test_unknown_or_inactive_tenant_is_refused(self, tenant):
        tenant.status = Tenant.Status.SUSPENDED
        tenant.save(update_fields=["status"])
        with pytest.raises(CommandError, match="No active tenant"):
            call_command(
                "create_tenant_user", "--tenant", tenant.slug, "--email", "a@b.example",
                "--role", "doer",
            )  # fmt: skip
