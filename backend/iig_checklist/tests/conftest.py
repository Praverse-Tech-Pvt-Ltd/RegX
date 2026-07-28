"""Fixtures for iig_checklist domain tests. Synthetic content only."""

import pytest


@pytest.fixture
def tenant_a(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha")


@pytest.fixture
def tenant_b(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Beta", slug="tenant-beta")


def _make_user(email, full_name):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(email=email, password="TestPass1234!", full_name=full_name)


@pytest.fixture
def user_a(db):
    return _make_user("checklist-user-a@example.com", "User A")


@pytest.fixture
def reviewer_user(db):
    return _make_user("checklist-reviewer@example.com", "Reviewer")


@pytest.fixture
def vp_user(db):
    return _make_user("checklist-vp@example.com", "VP")


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
def doer_membership(db, tenant_a, user_a):
    return _membership_with_role(tenant_a, user_a, "doer")


@pytest.fixture
def reviewer_membership(db, tenant_a, reviewer_user):
    return _membership_with_role(tenant_a, reviewer_user, "reviewer")


@pytest.fixture
def vp_membership(db, tenant_a, vp_user):
    return _membership_with_role(tenant_a, vp_user, "vp")


@pytest.fixture
def api_client_doer(user_a, tenant_a, doer_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_a)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def api_client_reviewer(reviewer_user, tenant_a, reviewer_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=reviewer_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def api_client_vp(vp_user, tenant_a, vp_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=vp_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def tenant_definition(db, tenant_a, user_a):
    from iig_checklist.models import ChecklistDefinition

    return ChecklistDefinition.objects.create(
        code="IIG-ORAL-SOLID",
        title="IIG Oral Solid (synthetic)",
        scope_type="tenant",
        tenant=tenant_a,
        created_by=user_a,
    )


@pytest.fixture
def draft_version(db, tenant_definition, user_a):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=1,
        created_by=user_a,
    )
