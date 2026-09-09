"""Controlled Correspondence API tests.

The app has two halves with different ownership, and the tests are weighted
towards keeping them apart: published guidance must stay read-only, and drafts
must not leak between tenants.
"""

import pytest
from rest_framework.test import APIClient

from authorization.models import Role
from controlled_correspondence.models import BestPractice, CorrespondenceDraft
from controlled_correspondence.permissions import (
    PERM_MANAGE,
    PERM_VIEW,
    ROLE_PERMISSIONS,
)

PRACTICES = "/api/regx/v1/controlled-correspondence/best-practices/"
CATEGORIES = "/api/regx/v1/controlled-correspondence/best-practices/categories/"
DRAFTS = "/api/regx/v1/controlled-correspondence/drafts/"


def _tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _user(email):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="TestPass1234!", full_name=email
    )


def _member(tenant, user, role_name):
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
def alpha(db):
    tenant = _tenant("Alpha CC", "alpha-cc")
    user = _user("doer@alpha-cc.test")
    _member(tenant, user, Role.BuiltIn.DOER)
    return {"tenant": tenant, "user": user, "client": _client(user, tenant)}


@pytest.fixture
def beta(db):
    tenant = _tenant("Beta CC", "beta-cc")
    user = _user("doer@beta-cc.test")
    _member(tenant, user, Role.BuiltIn.DOER)
    return {"tenant": tenant, "user": user, "client": _client(user, tenant)}


@pytest.fixture
def guidance(db):
    BestPractice.objects.create(
        category="Q1/Q2 Formulation",
        sub_category="Sameness",
        guidance="Provide a side-by-side comparison of the qualitative composition.",
    )
    BestPractice.objects.create(
        category="Q1/Q2 Formulation",
        sub_category="Deviation",
        guidance="Justify any quantitative deviation beyond the permitted range.",
    )
    BestPractice.objects.create(
        category="Bioequivalence",
        sub_category="",
        guidance="State the proposed study design and the reference product.",
    )


def _make_draft(client, **overrides):
    payload = {"proposed_drug_product_name": "Metoprolol Succinate ER Tablets 50 mg"}
    payload.update(overrides)
    return client.post(DRAFTS, payload, format="json")


# --------------------------------------------------------------------------
# Best practices: published guidance, read-only
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_is_refused(guidance):
    assert APIClient().get(PRACTICES).status_code in (401, 403)


@pytest.mark.django_db
def test_guidance_is_the_same_for_every_tenant(guidance, alpha, beta):
    """It is published reference material, not tenant content."""
    assert alpha["client"].get(PRACTICES).json()["count"] == 3
    assert beta["client"].get(PRACTICES).json()["count"] == 3


@pytest.mark.django_db
def test_guidance_is_read_only(guidance, alpha):
    assert alpha["client"].post(PRACTICES, {}, format="json").status_code in (403, 405)


@pytest.mark.django_db
def test_guidance_filters(guidance, alpha):
    assert alpha["client"].get(PRACTICES + "?category=Bioequivalence").json()["count"] == 1
    assert alpha["client"].get(PRACTICES + "?search=deviation").json()["count"] == 1
    assert alpha["client"].get(PRACTICES + "?search=zzznotpresent").json()["count"] == 0


@pytest.mark.django_db
def test_categories_are_distinct_values_not_rows(guidance, alpha):
    """Regression: Meta.ordering leaks into SELECT DISTINCT, so an unguarded
    .distinct() returns one entry per row."""
    body = alpha["client"].get(CATEGORIES).json()
    assert body["categories"] == ["Bioequivalence", "Q1/Q2 Formulation"]


# --------------------------------------------------------------------------
# Drafts: tenant work product
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_draft_is_invisible_to_another_tenant(alpha, beta):
    _make_draft(alpha["client"])
    assert alpha["client"].get(DRAFTS).json()["count"] == 1
    assert beta["client"].get(DRAFTS).json()["count"] == 0


@pytest.mark.django_db
def test_another_tenants_draft_is_404_not_403(alpha, beta):
    created = _make_draft(alpha["client"]).json()
    assert beta["client"].get(f"{DRAFTS}{created['id']}/").status_code == 404


@pytest.mark.django_db
def test_draft_defaults_to_draft_status(alpha):
    assert _make_draft(alpha["client"]).json()["status"] == "draft"


@pytest.mark.django_db
def test_draft_can_be_updated_and_filtered_by_status(alpha):
    created = _make_draft(alpha["client"]).json()
    alpha["client"].patch(f"{DRAFTS}{created['id']}/", {"status": "submitted"}, format="json")
    assert alpha["client"].get(DRAFTS + "?status=submitted").json()["count"] == 1
    assert alpha["client"].get(DRAFTS + "?status=draft").json()["count"] == 0


@pytest.mark.django_db
def test_draft_can_be_deleted_by_its_own_tenant(alpha):
    created = _make_draft(alpha["client"]).json()
    assert alpha["client"].delete(f"{DRAFTS}{created['id']}/").status_code == 204
    assert not CorrespondenceDraft.objects.filter(public_id=created["id"]).exists()


@pytest.mark.django_db
def test_reviewer_can_read_drafts_but_not_create_them(alpha):
    reviewer = _user("reviewer@alpha-cc.test")
    _member(alpha["tenant"], reviewer, Role.BuiltIn.REVIEWER)
    client = _client(reviewer, alpha["tenant"])
    _make_draft(alpha["client"])
    assert client.get(DRAFTS).status_code == 200
    assert _make_draft(client).status_code == 403


def test_drafts_are_writable_by_the_tenant_guidance_is_not():
    assert PERM_MANAGE in ROLE_PERMISSIONS[Role.BuiltIn.DOER]
    assert PERM_MANAGE in ROLE_PERMISSIONS[Role.BuiltIn.TENANT_ADMIN]
    assert PERM_MANAGE not in ROLE_PERMISSIONS[Role.BuiltIn.REVIEWER]
    assert PERM_VIEW in ROLE_PERMISSIONS[Role.BuiltIn.VP]
