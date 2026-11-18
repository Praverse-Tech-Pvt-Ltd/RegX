"""The API error envelope says WHY a request was refused.

Found on the real stack (2026-11-17): a signed-in Doer who opened Terminology
Mappings was sent to the sign-in page. The list endpoint correctly refuses a
Doer with 403, but session authentication also answers a signed-out caller with
403, and the page could not tell the two apart. `error.code` can.
"""

import pytest
from rest_framework.test import APIClient

MAPPINGS = "/api/regx/v1/fda-data/mappings/"


@pytest.fixture
def doer(db):
    from django.contrib.auth import get_user_model

    from authorization.models import MembershipRole, Role
    from tenancy.models import Tenant, TenantMembership

    tenant = Tenant.objects.create(name="Codes Tenant", slug="codes-tenant")
    user = get_user_model().objects.create_user(
        email="codes-doer@example.test", password="Synthetic-Pass-123!", full_name="Codes Doer"
    )
    membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
    role, _ = Role.objects.get_or_create(name=Role.BuiltIn.DOER, defaults={"description": "doer"})
    MembershipRole.objects.create(membership=membership, role=role)
    return user, tenant


@pytest.mark.django_db
class TestRefusalCodes:
    def test_signed_out_is_not_authenticated(self, doer):
        _, tenant = doer
        response = APIClient().get(MAPPINGS, HTTP_X_TENANT_SLUG=tenant.slug)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "not_authenticated"

    def test_signed_in_without_permission_is_permission_denied(self, doer):
        user, tenant = doer
        client = APIClient()
        client.force_login(user)
        response = client.get(MAPPINGS, HTTP_X_TENANT_SLUG=tenant.slug)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "permission_denied"

    def test_a_real_session_login_gets_the_same_answer(self, doer):
        user, tenant = doer
        client = APIClient()
        assert client.login(email=user.email, password="Synthetic-Pass-123!")
        response = client.get(MAPPINGS, HTTP_X_TENANT_SLUG=tenant.slug)
        assert response.json()["error"]["code"] == "permission_denied"

    def test_field_validation_errors_carry_no_single_code(self, doer):
        user, tenant = doer
        client = APIClient()
        client.force_login(user)
        response = client.post(
            "/api/regx/v1/formulations/products/",
            {},
            format="json",
            HTTP_X_TENANT_SLUG=tenant.slug,
        )
        assert response.status_code == 400
        assert "code" not in response.json()["error"]
