"""Product comparison API tests.

Tenant isolation is the priority here: unlike the FDA reference corpora, a
comparison is a tenant's own work, so cross-tenant leakage is the failure that
matters most.
"""

import pytest
from rest_framework.test import APIClient

from authorization.models import Role
from product_comparison.models import ComparisonAttribute, ProductComparison
from product_comparison.permissions import PERM_MANAGE, PERM_VIEW, ROLE_PERMISSIONS

LIST = "/api/regx/v1/product-comparisons/"


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
    tenant = _tenant("Alpha Pharma", "alpha-pc")
    user = _user("doer@alpha.test")
    _member(tenant, user, Role.BuiltIn.DOER)
    return {"tenant": tenant, "user": user, "client": _client(user, tenant)}


@pytest.fixture
def beta(db):
    tenant = _tenant("Beta Pharma", "beta-pc")
    user = _user("doer@beta.test")
    _member(tenant, user, Role.BuiltIn.DOER)
    return {"tenant": tenant, "user": user, "client": _client(user, tenant)}


@pytest.fixture
def reviewer(db, alpha):
    user = _user("reviewer@alpha.test")
    _member(alpha["tenant"], user, Role.BuiltIn.REVIEWER)
    return _client(user, alpha["tenant"])


def _make(client, **overrides):
    payload = {
        "product_type": "tablet",
        "rld_product_name": "Toprol-XL 50 mg",
        "company_product_name": "Metoprolol ER 50 mg",
    }
    payload.update(overrides)
    return client.post(LIST, payload, format="json")


# --------------------------------------------------------------------------
# Tenant isolation
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_a_comparison_is_invisible_to_another_tenant(alpha, beta):
    _make(alpha["client"])
    assert alpha["client"].get(LIST).json()["count"] == 1
    assert beta["client"].get(LIST).json()["count"] == 0


@pytest.mark.django_db
def test_another_tenants_comparison_is_404_not_403(alpha, beta):
    """403 would confirm the record exists. It must be indistinguishable from
    one that does not."""
    created = _make(alpha["client"]).json()
    assert beta["client"].get(f"{LIST}{created['id']}/").status_code == 404


@pytest.mark.django_db
def test_another_tenant_cannot_delete(alpha, beta):
    created = _make(alpha["client"]).json()
    assert beta["client"].delete(f"{LIST}{created['id']}/").status_code == 404
    assert ProductComparison.objects.filter(public_id=created["id"]).exists()


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_anonymous_is_refused(db):
    assert APIClient().get(LIST).status_code in (401, 403)


@pytest.mark.django_db
def test_reviewer_can_read_but_not_write(alpha, reviewer):
    _make(alpha["client"])
    assert reviewer.get(LIST).status_code == 200
    assert _make(reviewer).status_code == 403


def test_write_is_a_tenant_capability_not_platform_only():
    """Unlike the FDA corpora, a comparison is the tenant's own work."""
    assert PERM_MANAGE in ROLE_PERMISSIONS[Role.BuiltIn.DOER]
    assert PERM_MANAGE in ROLE_PERMISSIONS[Role.BuiltIn.TENANT_ADMIN]
    assert PERM_MANAGE not in ROLE_PERMISSIONS[Role.BuiltIn.REVIEWER]
    assert PERM_VIEW in ROLE_PERMISSIONS[Role.BuiltIn.VP]


# --------------------------------------------------------------------------
# Attributes and the matrix
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_setting_an_attribute_twice_updates_rather_than_duplicating(alpha):
    """(attribute, source) is unique per comparison, so PUT is an upsert. A
    create-only endpoint would force the client to know whether a cell was
    already filled."""
    created = _make(alpha["client"]).json()
    url = f"{LIST}{created['id']}/attributes/"
    alpha["client"].put(url, {"attribute": "shape", "source": "rld", "value": "Round"}, format="json")
    alpha["client"].put(url, {"attribute": "shape", "source": "rld", "value": "Oval"}, format="json")
    stored = ComparisonAttribute.objects.filter(attribute="shape", source="rld")
    assert stored.count() == 1
    assert stored.first().value == "Oval"


@pytest.mark.django_db
def test_the_same_attribute_from_different_sources_coexists(alpha):
    created = _make(alpha["client"]).json()
    url = f"{LIST}{created['id']}/attributes/"
    for source in ("rld", "company", "difference", "fda_limit"):
        alpha["client"].put(
            url, {"attribute": "shape", "source": source, "value": source}, format="json"
        )
    assert ComparisonAttribute.objects.filter(attribute="shape").count() == 4


@pytest.mark.django_db
def test_matrix_lists_every_known_attribute_even_when_unset(alpha):
    """The UI renders a complete form, not only the cells that happen to be
    filled."""
    created = _make(alpha["client"]).json()
    body = alpha["client"].get(f"{LIST}{created['id']}/matrix/").json()
    assert len(body["rows"]) == 12  # tablet attributes
    assert body["sources"] == ["rld", "company", "difference", "fda_limit"]
    assert all(row["rld"]["value"] == "" for row in body["rows"])


@pytest.mark.django_db
def test_capsule_matrix_has_the_capsule_attribute_set(alpha):
    created = _make(alpha["client"], product_type="capsule").json()
    body = alpha["client"].get(f"{LIST}{created['id']}/matrix/").json()
    assert len(body["rows"]) == 8
    assert "external_diameter" in [r["attribute"] for r in body["rows"]]


@pytest.mark.django_db
def test_an_attribute_outside_the_known_list_still_appears(alpha):
    """The vocabulary is a default, not a whitelist -- a tenant may record
    something the list does not name."""
    created = _make(alpha["client"]).json()
    alpha["client"].put(
        f"{LIST}{created['id']}/attributes/",
        {"attribute": "embossing", "source": "rld", "value": "ME 50"},
        format="json",
    )
    body = alpha["client"].get(f"{LIST}{created['id']}/matrix/").json()
    assert [r["attribute"] for r in body["rows"]][-1] == "embossing"


@pytest.mark.django_db
def test_public_id_is_exposed_and_the_pk_is_not(alpha):
    created = _make(alpha["client"]).json()
    assert "public_id" not in created
    assert ProductComparison.objects.filter(public_id=created["id"]).exists()
