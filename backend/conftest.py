"""
Pytest fixtures for the REGX backend test suite.
Uses factory-boy for object creation; hits a real PostgreSQL database
(configured in regx/settings/test.py). No mocking of the database layer.
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="testuser@example.com",
        password="TestPass1234!",
        full_name="Test User",
    )


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        email="admin@example.com",
        password="AdminPass1234!",
    )


@pytest.fixture
def tenant(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Test Tenant", slug="test-tenant")


@pytest.fixture
def membership(db, user, tenant):
    from tenancy.models import TenantMembership

    return TenantMembership.objects.create(tenant=tenant, user=user)


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client
