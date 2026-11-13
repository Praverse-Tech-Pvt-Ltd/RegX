"""
Fixtures for document domain tests.

All fixtures use synthetic data. No client documents or regulatory content.
"""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


# ---------------------------------------------------------------------------
# Fixture file helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_pdf_bytes():
    return _read_fixture("valid.pdf")


@pytest.fixture
def valid_docx_bytes():
    return _read_fixture("valid.docx")


@pytest.fixture
def valid_xlsx_bytes():
    return _read_fixture("valid.xlsx")


@pytest.fixture
def valid_pptx_bytes():
    return _read_fixture("valid.pptx")


@pytest.fixture
def mime_mismatch_bytes():
    return _read_fixture("mime_mismatch.pdf")


@pytest.fixture
def corrupt_office_bytes():
    return _read_fixture("corrupt_office.docx")


@pytest.fixture
def oversized_bytes():
    """51 MB of zeros — exceeds the 50 MB limit."""
    return b"\x00" * (51 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------


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
        email="user-a@example.com",
        password="TestPass1234!",
        full_name="User A",
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="user-b@example.com",
        password="TestPass1234!",
        full_name="User B",
    )


@pytest.fixture
def doer_membership(db, user_a, tenant_a):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.create(tenant=tenant_a, user=user_a)
    role, _ = Role.objects.get_or_create(
        name="doer",
        tenant=None,
        defaults={"is_system": True},
    )
    MembershipRole.objects.create(membership=membership, role=role)
    return membership


@pytest.fixture
def reviewer_membership(db, user_b, tenant_a):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.create(tenant=tenant_a, user=user_b)
    role, _ = Role.objects.get_or_create(
        name="reviewer",
        tenant=None,
        defaults={"is_system": True},
    )
    MembershipRole.objects.create(membership=membership, role=role)
    return membership


@pytest.fixture
def admin_membership(db, user_a, tenant_a):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=user_a)
    role, _ = Role.objects.get_or_create(
        name="tenant_admin",
        tenant=None,
        defaults={"is_system": True},
    )
    MembershipRole.objects.create(membership=membership, role=role)
    return membership


@pytest.fixture
def api_client_a(user_a, tenant_a):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_a)
    client.tenant = tenant_a
    return client


@pytest.fixture
def api_client_b(user_b, tenant_b):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_b)
    client.tenant = tenant_b
    return client


@pytest.fixture
def local_storage(tmp_path, settings):
    settings.DOCUMENT_STORAGE_BACKEND = "local"
    settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "doc_store")
    return tmp_path / "doc_store"
