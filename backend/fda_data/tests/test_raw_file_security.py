"""
Direct runtime tests for raw FDA source-file access control.

There is no HTTP endpoint anywhere in fda_data that serves file bytes or a
storage_key -- retrieve_fda_source_file() in storage.py is a service-level
function only, never wired to a view. These tests verify that boundary
holds: storage_key never appears in any serializer output regardless of
role, Platform Support has no fda_data access at all, an unauthenticated/
under-permissioned write attempt is rejected, and nonexistent resources
return a generic 404 rather than disclosing existence via a 403/500.
"""

import pytest
from rest_framework.test import APIClient

from fda_data.models import FDADataSourceRelease, FDAReleaseStatus

BASE = "/api/regx/v1"


def _client_for(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
    return client


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
def active_release(db):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="f" * 64,
        status=FDAReleaseStatus.ACTIVE,
        original_filename="/var/secret/fda-iid-export.txt",
        storage_key="platform/0/abc123def456.json",
    )


@pytest.mark.django_db
class TestStorageKeyNeverSerialized:
    def test_storage_key_absent_for_doer(self, tenant_a, user_a, active_release):
        _membership_with_role(tenant_a, user_a, "doer")
        client = _client_for(user_a, tenant_a)
        resp = client.get(f"{BASE}/fda-data/releases/{active_release.public_id}/")
        assert resp.status_code == 200
        assert "storage_key" not in resp.json()
        assert "abc123def456" not in str(resp.json())

    def test_storage_key_absent_even_for_view_raw_holder(self, tenant_a, vp_user, active_release):
        _membership_with_role(tenant_a, vp_user, "vp")
        client = _client_for(vp_user, tenant_a)
        resp = client.get(f"{BASE}/fda-data/releases/{active_release.public_id}/")
        assert resp.status_code == 200
        data = resp.json()
        # A VP does see original_filename/checksum (view_raw), but never
        # the internal storage_key -- there is no legitimate reason for
        # any HTTP client, however privileged, to receive it.
        assert "original_filename" in data
        assert "storage_key" not in data

    def test_storage_key_absent_in_release_list(self, tenant_a, user_a, active_release):
        _membership_with_role(tenant_a, user_a, "doer")
        client = _client_for(user_a, tenant_a)
        resp = client.get(f"{BASE}/fda-data/releases/")
        assert resp.status_code == 200
        assert "storage_key" not in str(resp.json())


@pytest.mark.django_db
class TestPlatformSupportIsMetadataOnly:
    def test_platform_support_cannot_view_releases(self, tenant_a, user_a, active_release):
        _membership_with_role(tenant_a, user_a, "platform_support")
        client = _client_for(user_a, tenant_a)
        resp = client.get(f"{BASE}/fda-data/releases/")
        assert resp.status_code == 403

    def test_platform_support_cannot_export_reconciliation(self, tenant_a, user_a, active_release):
        _membership_with_role(tenant_a, user_a, "platform_support")
        client = _client_for(user_a, tenant_a)
        resp = client.get(f"{BASE}/fda-data/releases/{active_release.public_id}/reconciliation.csv")
        assert resp.status_code == 403

    def test_platform_support_cannot_import(self, tenant_a, user_a):
        _membership_with_role(tenant_a, user_a, "platform_support")
        client = _client_for(user_a, tenant_a)
        resp = client.post(
            f"{BASE}/fda-data/releases/",
            data={
                "dataset_type": "fda_iid",
                "source_name": "x",
                "official_source_reference": "x",
                "rows": [],
            },
            format="json",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestWriteAttemptsAndGenericNotFound:
    def test_reviewer_cannot_write_new_release(self, tenant_a, user_a):
        # Reviewer has review/approve/export permissions but not
        # register/import -- an under-permissioned write attempt must be
        # rejected, never silently accepted.
        _membership_with_role(tenant_a, user_a, "reviewer")
        client = _client_for(user_a, tenant_a)
        resp = client.post(
            f"{BASE}/fda-data/releases/",
            data={
                "dataset_type": "fda_iid",
                "source_name": "x",
                "official_source_reference": "x",
                "rows": [],
            },
            format="json",
        )
        assert resp.status_code == 403

    def test_nonexistent_release_returns_generic_404(self, tenant_a, user_a):
        _membership_with_role(tenant_a, user_a, "vp")
        client = _client_for(user_a, tenant_a)
        import uuid

        resp = client.get(f"{BASE}/fda-data/releases/{uuid.uuid4()}/")
        assert resp.status_code == 404
        # Generic message, no internal detail (e.g. no stack trace, no
        # mention of the table/model name beyond the documented resource).
        assert "traceback" not in str(resp.json()).lower()

    def test_unauthenticated_request_rejected_not_404(self, tenant_a, active_release):
        client = APIClient()
        client.credentials(**{"HTTP_X_TENANT_SLUG": tenant_a.slug})
        resp = client.get(f"{BASE}/fda-data/releases/{active_release.public_id}/")
        assert resp.status_code in (401, 403)
