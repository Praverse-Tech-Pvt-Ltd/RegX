"""Fixtures for blueprint tests.

Synthetic data only. Section codes are generic -- A, A.1, B -- and deliberately
carry no CTD, CEP, DMF or ANDA structure: none ships in this milestone and none
is implied by a test.
"""

import pytest
from rest_framework.test import APIClient

from dossier_blueprints import services

BLUEPRINT_API = "/api/regx/v1/dossier-blueprints"
VERSION_API = "/api/regx/v1/dossier-blueprint-versions"
SECTION_API = "/api/regx/v1/dossier-blueprint-sections"


def _make_tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _make_user(email, full_name):
    from identity.models import User

    return User.objects.create_user(email=email, password="TestPass1234!", full_name=full_name)


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
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
    return _make_tenant("Blueprint Tenant A", "bp-tenant-a")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Blueprint Tenant B", "bp-tenant-b")


@pytest.fixture
def doer_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("bp-doer-a@example.test", "Blueprint Doer A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def reviewer_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("bp-reviewer-a@example.test", "Blueprint Reviewer A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.REVIEWER)
    return user


@pytest.fixture
def admin_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("bp-admin-a@example.test", "Blueprint Admin A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.TENANT_ADMIN)
    return user


@pytest.fixture
def vp_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("bp-vp-a@example.test", "Blueprint VP A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.VP)
    return user


@pytest.fixture
def support_a(db, tenant_a):
    """Holds `dossier_blueprints.view` and no dossier or case permission, so it
    is the natural probe for the two-gate instantiation rule."""
    from authorization.models import Role

    user = _make_user("bp-support-a@example.test", "Blueprint Support A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.PLATFORM_SUPPORT)
    return user


@pytest.fixture
def doer_b(db, tenant_b):
    from authorization.models import Role

    user = _make_user("bp-doer-b@example.test", "Blueprint Doer B")
    _membership_with_role(tenant_b, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def admin_b(db, tenant_b):
    from authorization.models import Role

    user = _make_user("bp-admin-b@example.test", "Blueprint Admin B")
    _membership_with_role(tenant_b, user, Role.BuiltIn.TENANT_ADMIN)
    return user


@pytest.fixture
def client_doer_a(doer_a, tenant_a):
    return _client(doer_a, tenant_a)


@pytest.fixture
def client_admin_a(admin_a, tenant_a):
    return _client(admin_a, tenant_a)


@pytest.fixture
def client_reviewer_a(reviewer_a, tenant_a):
    return _client(reviewer_a, tenant_a)


@pytest.fixture
def client_support_a(support_a, tenant_a):
    return _client(support_a, tenant_a)


@pytest.fixture
def client_doer_b(doer_b, tenant_b):
    return _client(doer_b, tenant_b)


@pytest.fixture
def client_admin_b(admin_b, tenant_b):
    return _client(admin_b, tenant_b)


# ---------------------------------------------------------------------------
# Cases (from Milestone 8) -- instantiation targets
# ---------------------------------------------------------------------------
def _make_case(tenant, actor, title="Synthetic case"):
    from regulatory_cases import services as case_services

    return case_services.create_case(
        tenant=tenant, actor=actor, title=title, description="Synthetic"
    )


@pytest.fixture
def case_a(db, tenant_a, admin_a):
    return _make_case(tenant_a, admin_a)


@pytest.fixture
def case_b(db, tenant_b, admin_b):
    return _make_case(tenant_b, admin_b)


# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------
@pytest.fixture
def blueprint_a(db, tenant_a, admin_a):
    return services.create_blueprint(
        tenant=tenant_a, actor=admin_a, name="Synthetic outline A", description="Synthetic"
    )


@pytest.fixture
def blueprint_b(db, tenant_b, admin_b):
    return services.create_blueprint(
        tenant=tenant_b, actor=admin_b, name="Synthetic outline B", description="Synthetic"
    )


@pytest.fixture
def draft_a(db, blueprint_a, tenant_a, admin_a):
    return services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)


@pytest.fixture
def draft_b(db, blueprint_b, tenant_b, admin_b):
    return services.create_version(blueprint=blueprint_b, tenant=tenant_b, actor=admin_b)


def make_section(version, tenant, actor, code, *, parent=None, required=True, **kw):
    return services.create_section(
        version=version,
        tenant=tenant,
        actor=actor,
        parent=parent,
        section_code=code,
        title=f"Section {code}",
        required=required,
        **kw,
    )


@pytest.fixture
def populated_draft_a(db, draft_a, tenant_a, admin_a):
    """A small generic outline: A, A.1, A.2, B, B.1.

    Deliberately meaningless codes. The engine must be able to represent any
    structure without shipping one.
    """
    a = make_section(draft_a, tenant_a, admin_a, "A")
    make_section(draft_a, tenant_a, admin_a, "A.1", parent=a)
    make_section(draft_a, tenant_a, admin_a, "A.2", parent=a, required=False)
    b = make_section(draft_a, tenant_a, admin_a, "B")
    make_section(draft_a, tenant_a, admin_a, "B.1", parent=b)
    return draft_a


@pytest.fixture
def active_a(db, populated_draft_a, tenant_a, admin_a):
    return services.activate_version(version=populated_draft_a, tenant=tenant_a, actor=admin_a)
