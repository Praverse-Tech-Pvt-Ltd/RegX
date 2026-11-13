"""Fixtures for the workflows domain. Synthetic data only."""

import pytest


def _make_tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _make_user(email, full_name):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="TestPass1234!", full_name=full_name
    )


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(tenant=None, name=role_name, defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


def _client(user, tenant):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


@pytest.fixture
def tenant_a(db):
    return _make_tenant("Tenant Alpha", "wf-tenant-alpha")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Tenant Beta", "wf-tenant-beta")


@pytest.fixture
def doer_a(db, tenant_a):
    user = _make_user("wf-doer-a@example.com", "Doer A")
    _membership_with_role(tenant_a, user, "doer")
    return user


@pytest.fixture
def reviewer_a(db, tenant_a):
    user = _make_user("wf-reviewer-a@example.com", "Reviewer A")
    _membership_with_role(tenant_a, user, "reviewer")
    return user


@pytest.fixture
def second_reviewer_a(db, tenant_a):
    user = _make_user("wf-reviewer2-a@example.com", "Reviewer A2")
    _membership_with_role(tenant_a, user, "reviewer")
    return user


@pytest.fixture
def doer_b(db, tenant_b):
    user = _make_user("wf-doer-b@example.com", "Doer B")
    _membership_with_role(tenant_b, user, "doer")
    return user


@pytest.fixture
def outsider(db):
    """Authenticated but a member of no tenant. Everything must fail closed."""
    return _make_user("wf-outsider@example.com", "Outsider")


@pytest.fixture
def client_doer_a(doer_a, tenant_a):
    return _client(doer_a, tenant_a)


@pytest.fixture
def client_reviewer_a(reviewer_a, tenant_a):
    return _client(reviewer_a, tenant_a)


@pytest.fixture
def client_doer_b(doer_b, tenant_b):
    return _client(doer_b, tenant_b)


@pytest.fixture
def item_a(db, tenant_a, doer_a):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.create(tenant=tenant_a, created_by=doer_a, title="Synthetic item A")


@pytest.fixture
def item_b(db, tenant_b, doer_b):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.create(tenant=tenant_b, created_by=doer_b, title="Synthetic item B")
