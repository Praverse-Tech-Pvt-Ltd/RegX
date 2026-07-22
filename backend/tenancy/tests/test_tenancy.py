"""Tests for tenancy domain."""

import pytest
from tenancy.models import Tenant, TenantMembership
from tenancy.context import set_current_tenant, current_tenant, clear_current_tenant
from common.exceptions import TenantScopeMissing


@pytest.mark.django_db
class TestTenantModel:
    def test_create_tenant(self):
        t = Tenant.objects.create(name="Pharma Corp", slug="pharma-corp")
        assert t.status == Tenant.Status.ACTIVE
        assert t.public_id is not None

    def test_slug_uniqueness(self):
        Tenant.objects.create(name="Alpha", slug="alpha")
        with pytest.raises(Exception):
            Tenant.objects.create(name="Alpha 2", slug="alpha")


@pytest.mark.django_db
class TestTenantMembership:
    def test_user_can_belong_to_multiple_tenants(self, user):
        t1 = Tenant.objects.create(name="T1", slug="t1")
        t2 = Tenant.objects.create(name="T2", slug="t2")
        TenantMembership.objects.create(tenant=t1, user=user)
        TenantMembership.objects.create(tenant=t2, user=user)
        assert TenantMembership.objects.filter(user=user).count() == 2


class TestTenantContext:
    def test_fail_closed_when_no_tenant_set(self):
        clear_current_tenant()
        with pytest.raises(TenantScopeMissing):
            current_tenant()

    def test_set_and_get_tenant(self, tenant):
        set_current_tenant(tenant)
        assert current_tenant() == tenant
        clear_current_tenant()

    def test_clear_resets_context(self, tenant):
        set_current_tenant(tenant)
        clear_current_tenant()
        with pytest.raises(TenantScopeMissing):
            current_tenant()


@pytest.mark.django_db
class TestTenantAPIViews:
    def test_list_tenants_for_authenticated_user(self, auth_client, membership):
        resp = auth_client.get("/api/regx/v1/tenants/")
        assert resp.status_code == 200
        assert len(resp.data) == 1

    def test_unauthenticated_rejected(self, api_client):
        resp = api_client.get("/api/regx/v1/tenants/")
        assert resp.status_code == 403
