"""Fixtures for the FDA inspection corpus. Synthetic data only.

Mirrors `deficiencies/tests/conftest.py`. A distinct tenant slug, because every
suite can run in the same session.
"""

from datetime import date

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


@pytest.fixture
def tenant(db):
    return _make_tenant("Inspection Test Tenant", "inspection-test")


@pytest.fixture
def doer(db, tenant):
    user = _make_user("doer@inspection.test", "Inspection Doer")
    _membership_with_role(tenant, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def outsider(db):
    """A real, authenticated user with no membership in `tenant`."""
    return _make_user("outsider@inspection.test", "Outsider")


@pytest.fixture
def client(doer, tenant):
    return _client(doer, tenant)


@pytest.fixture
def corpus(db):
    """Two inspections across two years, three systems, four observations, plus
    one warning letter. Values are chosen so filter assertions cannot pass by
    coincidence."""
    from inspections.models import (
        Form483Inspection,
        Form483Observation,
        Form483System,
        WarningLetter,
    )

    acme = Form483Inspection.objects.create(
        company_name="Acme Pharma Ltd",
        city="Hyderabad",
        state="Telangana",
        type_of_establishment="API Manufacturer",
        date_of_inspection=date(2023, 6, 14),
        investigator_name="A Investigator",
    )
    quality = Form483System.objects.create(inspection=acme, system="Quality System")
    Form483Observation.objects.create(
        system=quality,
        observation_number=1,
        content="Sterility test failures were not adequately investigated.",
    )
    Form483Observation.objects.create(
        system=quality,
        observation_number=2,
        content="Written procedures for cleaning validation are not followed.",
    )
    production = Form483System.objects.create(inspection=acme, system="Production System")
    Form483Observation.objects.create(
        system=production,
        observation_number=1,
        content="Equipment maintenance records are incomplete.",
    )

    beta = Form483Inspection.objects.create(
        company_name="Beta Labs Inc",
        city="Boston",
        state="MA",
        type_of_establishment="Finished Dosage Manufacturer",
        date_of_inspection=date(2024, 2, 3),
        investigator_name="B Inspector",
    )
    lab = Form483System.objects.create(inspection=beta, system="Laboratory Control System")
    Form483Observation.objects.create(
        system=lab,
        observation_number=1,
        content="Out-of-specification results lack a documented conclusion.",
    )

    WarningLetter.objects.create(
        company_name="Gamma Manufacturing",
        recipient_name="Chief Executive",
        date_of_issue=date(2024, 5, 20),
        country="India",
        body="Your firm failed to establish adequate written procedures.",
    )
    return {"acme": acme, "beta": beta}
