"""Fixtures for the regulatory cases domain. Synthetic data only.

Mirrors `workflows/tests/conftest.py` so the two suites read the same way.
Distinct tenant slugs, because both suites can run in the same session.
"""

import pytest
from rest_framework.test import APIClient

from authorization.models import Role


def _make_tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _make_user(email, full_name):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="TestPass1234!", full_name=full_name
    )


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(
        tenant=tenant, name=role_name, defaults={"is_system": True}
    )
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


def _client(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


# --- tenants ---------------------------------------------------------------
@pytest.fixture
def tenant_a(db):
    return _make_tenant("Case Tenant Alpha", "rc-tenant-alpha")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Case Tenant Beta", "rc-tenant-beta")


# --- users -----------------------------------------------------------------
@pytest.fixture
def doer_a(db, tenant_a):
    user = _make_user("rc-doer-a@example.com", "Case Doer A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def vp_a(db, tenant_a):
    """Holds complete AND cancel; DOER holds neither."""
    user = _make_user("rc-vp-a@example.com", "Case VP A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.VP)
    return user


@pytest.fixture
def admin_a(db, tenant_a):
    user = _make_user("rc-admin-a@example.com", "Case Admin A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.TENANT_ADMIN)
    return user


@pytest.fixture
def support_a(db, tenant_a):
    """PLATFORM_SUPPORT: holds regulatory_cases.view and NO document,
    workflow or checklist permission anywhere. This is the live configuration
    the projection tests drive."""
    user = _make_user("rc-support-a@example.com", "Case Support A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.PLATFORM_SUPPORT)
    return user


@pytest.fixture
def doer_b(db, tenant_b):
    user = _make_user("rc-doer-b@example.com", "Case Doer B")
    _membership_with_role(tenant_b, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def outsider(db):
    """Authenticated but a member of no tenant."""
    return _make_user("rc-outsider@example.com", "Case Outsider")


# --- clients ---------------------------------------------------------------
@pytest.fixture
def client_doer_a(doer_a, tenant_a):
    return _client(doer_a, tenant_a)


@pytest.fixture
def client_vp_a(vp_a, tenant_a):
    return _client(vp_a, tenant_a)


@pytest.fixture
def client_admin_a(admin_a, tenant_a):
    return _client(admin_a, tenant_a)


@pytest.fixture
def client_support_a(support_a, tenant_a):
    return _client(support_a, tenant_a)


@pytest.fixture
def client_doer_b(doer_b, tenant_b):
    return _client(doer_b, tenant_b)


# --- domain objects --------------------------------------------------------
CASE_FIELDS = {
    "title": "Stability data package",
    "product_name": "Synthetic Product X",
    "market": "Synthetic Market",
    "submission_type": "Synthetic Submission Type",
}


@pytest.fixture
def case_a(db, tenant_a, doer_a):
    from regulatory_cases import services

    return services.create_case(tenant=tenant_a, actor=doer_a, **CASE_FIELDS)


@pytest.fixture
def case_b(db, tenant_b, doer_b):
    from regulatory_cases import services

    return services.create_case(tenant=tenant_b, actor=doer_b, **CASE_FIELDS)


@pytest.fixture
def workflow_a(db, tenant_a, doer_a):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.create(
        tenant=tenant_a, title="Synthetic workflow A", created_by=doer_a
    )


@pytest.fixture
def workflow_b(db, tenant_b, doer_b):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.create(
        tenant=tenant_b, title="Synthetic workflow B", created_by=doer_b
    )


def _make_document(tenant, title="Synthetic document"):
    from documents.models import Document

    return Document.objects.create(tenant=tenant, title=title, document_type="other")


@pytest.fixture
def document_a(db, tenant_a):
    return _make_document(tenant_a, "Tenant A document")


@pytest.fixture
def document_b(db, tenant_b):
    return _make_document(tenant_b, "Tenant B document")
