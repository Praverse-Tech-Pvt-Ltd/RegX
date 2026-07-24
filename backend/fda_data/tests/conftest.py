"""Fixtures for fda_data domain tests. Synthetic, non-confidential data only."""

import io
import json

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


@pytest.fixture
def vp_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="vp@example.com", password="TestPass1234!", full_name="VP"
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
def doer_membership(db, tenant_a, user_a):
    return _membership_with_role(tenant_a, user_a, "doer")


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
def api_client_vp(vp_user, tenant_a, vp_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=vp_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def orange_book_rows():
    """Synthetic rows shaped like the official Orange Book products file --
    no real FDA data."""
    return [
        {
            "Ingredient": "SYNTHETIC-ACETAMINOPHEN",
            "DF;Route": "TABLET;ORAL",
            "Trade_Name": "Synthacet",
            "Applicant": "Synthetic Pharma Inc",
            "Strength": "500MG",
            "Appl_Type": "A",
            "Appl_No": "099999",
            "Product_No": "001",
            "TE_Code": "AB",
            "Approval_Date": "Jan 1, 2000",
            "RLD": "Yes",
            "RS": "Yes",
        },
        {
            "Ingredient": "SYNTHETIC-ACETAMINOPHEN",
            "DF;Route": "TABLET;ORAL",
            "Trade_Name": "Synthacet Forte",
            "Applicant": "Synthetic Pharma Inc",
            "Strength": "650MG",
            "Appl_Type": "A",
            "Appl_No": "099999",
            "Product_No": "002",
            "TE_Code": "AB",
            "Approval_Date": "Approved Prior to Jan 1, 1982",
            "RLD": "No",
            "RS": "No",
        },
    ]


@pytest.fixture
def iid_rows():
    """Synthetic rows shaped like the official FDA IID export."""
    return [
        {
            "Ingredient Name": "SYNTHETIC-STARCH",
            "UNII": "SYN0001",
            "CAS Number": "9005-25-8",
            "Route": "ORAL",
            "Dosage Form": "TABLET",
            "Potency": "50",
            "Unit": "MG",
            "Maximum Daily Exposure": "200",
            "MDE Unit": "MG",
        },
        {
            "Ingredient Name": "SYNTHETIC-BLANK-POTENCY",
            "UNII": "SYN0002",
            "Route": "ORAL",
            "Dosage Form": "TABLET",
            "Potency": "",
            "Unit": "",
        },
    ]


def make_release_file(rows) -> io.BytesIO:
    return io.BytesIO(json.dumps(rows, sort_keys=True).encode("utf-8"))
