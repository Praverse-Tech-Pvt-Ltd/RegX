"""Editing ?tenant= in the browser cannot reach another organisation.

Every REGX page sends its `?tenant=` value as the X-Tenant-Slug header. A
signed-in member of one organisation who edits the URL to another
organisation's slug must be refused by the backend (403) with no data from that
organisation in the response. The control case proves the same request
succeeds for the organisation the user belongs to, so the refusal is about
membership and not a broken endpoint.

Session login (force_login), not force_authenticate: the browser sends a
session cookie, and TenantMiddleware checks membership only once Django's
session auth has resolved the user.
"""

import pytest
from rest_framework.test import APIClient

PRODUCTS_URL = "/api/regx/v1/formulations/products/"


@pytest.fixture
def two_orgs(db, user):
    from authorization.models import MembershipRole, Role
    from formulations.models import ProductDevelopmentRecord
    from tenancy.models import Tenant, TenantMembership

    own = Tenant.objects.create(name="Own Org", slug="own-org")
    other = Tenant.objects.create(name="Other Org", slug="other-org")
    membership = TenantMembership.objects.create(tenant=own, user=user)
    role, _ = Role.objects.get_or_create(name="doer", tenant=None, defaults={"is_system": True})
    MembershipRole.objects.create(membership=membership, role=role)
    ProductDevelopmentRecord.objects.create(
        tenant=own,
        product_code="OWN-1",
        proposed_product_name="Own product",
        active_ingredient="Own API",
    )
    ProductDevelopmentRecord.objects.create(
        tenant=other,
        product_code="OTHER-SECRET-1",
        proposed_product_name="Other organisation's product",
        active_ingredient="Other API",
    )
    return own, other


def _session_client(user, slug):
    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_X_TENANT_SLUG=slug)
    return client


@pytest.mark.django_db
class TestEditingTenantInUrl:
    def test_own_organisation_succeeds_and_returns_own_data(self, user, two_orgs):
        resp = _session_client(user, "own-org").get(PRODUCTS_URL)
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "OWN-1" in body
        assert "OTHER-SECRET-1" not in body

    def test_other_organisation_is_refused_with_403_and_no_data(self, user, two_orgs):
        resp = _session_client(user, "other-org").get(PRODUCTS_URL)
        assert resp.status_code == 403
        assert resp.json() == {"detail": "User is not a member of this tenant."}
        body = resp.content.decode()
        assert "OTHER-SECRET-1" not in body
        assert "Other organisation" not in body

    def test_other_organisation_is_refused_for_writes_too(self, user, two_orgs):
        from formulations.models import ProductDevelopmentRecord

        resp = _session_client(user, "other-org").post(
            PRODUCTS_URL,
            {"product_code": "PLANTED-1", "proposed_product_name": "x", "active_ingredient": "y"},
            format="json",
        )
        assert resp.status_code == 403
        assert not ProductDevelopmentRecord.objects.filter(product_code="PLANTED-1").exists()
