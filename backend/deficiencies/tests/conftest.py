"""Fixtures for the deficiency corpus domain. Synthetic data only.

Mirrors `regulatory_cases/tests/conftest.py` so the suites read the same way.
A distinct tenant slug, because every suite can run in the same session.
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
    role, _ = Role.objects.get_or_create(tenant=None, name=role_name, defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


def _client(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


@pytest.fixture
def tenant(db):
    return _make_tenant("Deficiency Test Tenant", "deficiency-test")


@pytest.fixture
def doer(db, tenant):
    user = _make_user("doer@deficiency.test", "Deficiency Doer")
    _membership_with_role(tenant, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def outsider(db):
    """A real, authenticated user with no membership in `tenant`."""
    return _make_user("outsider@deficiency.test", "Outsider")


@pytest.fixture
def client(doer, tenant):
    return _client(doer, tenant)


@pytest.fixture
def corpus(db):
    """A small corpus spanning both roadmaps, with values chosen so the filter
    and facet assertions cannot pass by coincidence."""
    from deficiencies.models import DeficiencyCorpus, DeficiencyRecord

    rows = [
        (
            "anda",
            "Solid Oral-Deficiency",
            "Tablet",
            "Drug Product",
            "Dissolution",
            "Minor",
            "Dissolution profile was not provided for the 25 mg strength.",
        ),
        (
            "anda",
            "Solid Oral-Deficiency",
            "Capsule",
            "Drug Substance",
            "Impurities",
            "Major",
            "Specification for total impurities is not justified.",
        ),
        (
            "anda",
            "Injectable - General Deficiency",
            "Injection",
            "Microbiology",
            "Sterility",
            "Major",
            "Sterility assurance data are incomplete.",
        ),
        (
            "major_cr",
            "Topicals-Deficiency",
            "Cream",
            "Drug Product",
            "Packaging",
            "Minor",
            "Container closure integrity testing was not submitted.",
        ),
    ]
    for c, cat, form, section, dtype, dcat, body in rows:
        DeficiencyRecord.objects.create(
            corpus=DeficiencyCorpus(c),
            main_category=cat,
            dosage_form=form,
            cmc_section=section,
            deficiency_type=dtype,
            category_of_deficiency=dcat,
            deficiency=body,
        )
    return DeficiencyRecord.objects.all()
