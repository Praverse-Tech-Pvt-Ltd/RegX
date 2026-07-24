"""Fixtures for formulations domain tests. Synthetic data only."""

import pytest


@pytest.fixture
def tenant_a(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha")


@pytest.fixture
def tenant_b(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Beta", slug="tenant-beta")


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="user-a@example.com", password="TestPass1234!", full_name="User A"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="user-b@example.com", password="TestPass1234!", full_name="User B"
    )


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(
        tenant=tenant, name=role_name, defaults={"is_system": True}
    )
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


@pytest.fixture
def doer_membership_a(db, tenant_a, user_a):
    return _membership_with_role(tenant_a, user_a, "doer")


@pytest.fixture
def doer_membership_b(db, tenant_b, user_b):
    return _membership_with_role(tenant_b, user_b, "doer")


@pytest.fixture
def api_client_a(user_a, tenant_a, doer_membership_a):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_a)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def api_client_b(user_b, tenant_b, doer_membership_b):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_b)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_b.slug)
    return client
