"""Fixtures for the operations dashboard.

Synthetic data only. Section codes are generic -- A, A.1, B -- and encode no
CTD, CEP, DMF or ANDA structure: none ships in this milestone and none is
implied by a test.

The dashboard reads seven domains, so the fixtures build real rows through each
domain's own service rather than inserting them directly. A dashboard tested
against hand-made rows would pass while disagreeing with every other screen.
"""

import pytest
from rest_framework.test import APIClient

OPS_API = "/api/regx/v1/submission-operations"


def _make_tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _make_user(email, full_name):
    from identity.models import User

    return User.objects.create_user(email=email, password="TestPass1234!", full_name=full_name)


def _membership_with_roles(tenant, user, role_names):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
    for role_name in role_names:
        role, _ = Role.objects.get_or_create(name=role_name, defaults={"description": role_name})
        MembershipRole.objects.create(membership=membership, role=role)
    return membership


def _client(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


@pytest.fixture
def tenant_a(db):
    return _make_tenant("Ops Tenant A", "ops-tenant-a")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Ops Tenant B", "ops-tenant-b")


@pytest.fixture
def admin_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("ops-admin-a@example.test", "Ops Admin A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.TENANT_ADMIN])
    return user


@pytest.fixture
def admin_b(db, tenant_b):
    from authorization.models import Role

    user = _make_user("ops-admin-b@example.test", "Ops Admin B")
    _membership_with_roles(tenant_b, user, [Role.BuiltIn.TENANT_ADMIN])
    return user


@pytest.fixture
def doer_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("ops-doer-a@example.test", "Ops Doer A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.DOER])
    return user


@pytest.fixture
def support_a(db, tenant_a):
    """PLATFORM_SUPPORT: holds the dashboard permission and very little else."""
    from authorization.models import Role

    user = _make_user("ops-support-a@example.test", "Ops Support A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.PLATFORM_SUPPORT])
    return user


@pytest.fixture
def client_admin_a(admin_a, tenant_a):
    return _client(admin_a, tenant_a)


@pytest.fixture
def client_admin_b(admin_b, tenant_b):
    return _client(admin_b, tenant_b)


@pytest.fixture
def client_support_a(support_a, tenant_a):
    return _client(support_a, tenant_a)


# ---------------------------------------------------------------------------
# Domain builders -- always through the owning service
# ---------------------------------------------------------------------------
def make_case(tenant, actor, title="Synthetic case"):
    from regulatory_cases import services as cases

    return cases.create_case(tenant=tenant, actor=actor, title=title)


def make_dossier(case, tenant, actor, title="Synthetic dossier", **kw):
    from submission_dossiers import services as ds

    return ds.create_dossier(case=case, tenant=tenant, actor=actor, title=title, **kw)


def make_section(dossier, tenant, actor, code, *, required=True, parent=None, **kw):
    from submission_dossiers import services as ds

    return ds.create_section(
        dossier=dossier,
        tenant=tenant,
        actor=actor,
        section_code=code,
        title=f"Section {code}",
        required=required,
        parent=parent,
        **kw,
    )


def set_section(section, tenant, actor, **kw):
    from submission_dossiers import services as ds

    return ds.update_section(section=section, tenant=tenant, actor=actor, **kw)


def add_blocker(section, tenant, actor, title="Synthetic blocker"):
    from submission_dossiers import services as ds

    return ds.create_blocker(section=section, tenant=tenant, actor=actor, title=title)


def overview_of(client):
    response = client.get(f"{OPS_API}/overview/")
    assert response.status_code == 200, response.data
    return response.data


def attention_of(client, **params):
    response = client.get(f"{OPS_API}/attention/", params)
    assert response.status_code == 200, response.data
    return response.data


def reasons_of(payload) -> list[str]:
    return [row["reason_code"] for row in payload["results"]]
