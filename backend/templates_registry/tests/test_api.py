"""
Template registry API tests: tenant isolation, permission enforcement,
response shape (no internal IDs, no source paths for non-raw viewers),
generic 404s, and the reconciliation export permission fix (VP/tenant
admin only, not Doer).

Every test that plants a violation is noted.
"""

import pytest
from rest_framework.test import APIClient

BASE = "/api/regx/v1"


def _client_for(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
    return client


def _register_package(client, source_name="anda-export", source_type="anda_checklist"):
    return client.post(
        f"{BASE}/template-sources/",
        data={
            "source_name": source_name,
            "source_type": source_type,
            "source_path_or_reference": "synthetic://anda.json",
            "payload": {"rows": [{"id": 1, "question": "Q1"}]},
        },
        format="json",
    )


def _run_batch(client, source_package_public_id, rows=None):
    rows = rows or [
        {
            "identifier": "anda-1",
            "raw_text": "<p>1. Describe formulation.</p>",
            "raw_payload": {},
            "locator": "RATools_andareportquestions:1",
            "extraction_method": "controlled_export_json",
            "encoding": "utf-8",
            "fields": {
                "template_canonical_code": "ANDA-API-TEST",
                "template_title": "ANDA API Test",
                "template_category": "Formulation",
                "section_code": "general",
                "section_title": "General",
                "item_code": "item-1",
                "response_type": "narrative",
                "required": False,
            },
        }
    ]
    return client.post(
        f"{BASE}/migration-batches/",
        data={"source_package": source_package_public_id, "records": rows},
        format="json",
    )


@pytest.mark.django_db
class TestUnauthenticatedAccess:
    def test_unauthenticated_template_list_rejected(self):
        # PLANTED: no credentials at all.
        client = APIClient()
        resp = client.get(f"{BASE}/templates/")
        assert resp.status_code in (401, 403)


@pytest.mark.django_db
class TestSourcePackageRegistrationPermissions:
    def test_doer_can_register_source_package(self, user_a, tenant_a, doer_membership):
        client = _client_for(user_a, tenant_a)
        resp = _register_package(client)
        assert resp.status_code == 201
        data = resp.json()
        assert "public_id" in data
        assert "id" not in data
        # Doer lacks view_raw -- source_path_or_reference must not appear.
        assert "source_path_or_reference" not in data

    def test_reviewer_cannot_register_source_package(
        self, reviewer_user, tenant_a, reviewer_membership
    ):
        # PLANTED: reviewer role attempting an import-permission action.
        client = _client_for(reviewer_user, tenant_a)
        resp = _register_package(client)
        assert resp.status_code == 403

    def test_483_source_package_rejected_via_api(self, user_a, tenant_a, doer_membership):
        client = _client_for(user_a, tenant_a)
        resp = _register_package(client, source_name="warning-letter-export", source_type="form483")
        # PLANTED: 483-typed source submitted through the public API.
        assert resp.status_code == 400

    def test_view_raw_permission_controls_source_path_visibility(
        self, user_a, tenant_a, doer_membership, reviewer_user, reviewer_membership
    ):
        doer_client = _client_for(user_a, tenant_a)
        _register_package(doer_client, source_name="raw-visibility-src")

        doer_list = doer_client.get(f"{BASE}/template-sources/").json()["results"]
        assert "source_path_or_reference" not in doer_list[0]

        reviewer_client = _client_for(reviewer_user, tenant_a)
        reviewer_list = reviewer_client.get(f"{BASE}/template-sources/").json()["results"]
        # Reviewer holds templates.view_raw -- the raw source path is
        # intentionally visible to them, gated by permission, not role name.
        assert "source_path_or_reference" in reviewer_list[0]


@pytest.mark.django_db
class TestMigrationBatchAndReconciliationPermissions:
    def test_doer_can_run_batch_but_not_export_reconciliation(
        self, user_a, tenant_a, doer_membership
    ):
        client = _client_for(user_a, tenant_a)
        pkg_resp = _register_package(client, source_name="anda-batch-src")
        package_id = pkg_resp.json()["public_id"]
        batch_resp = _run_batch(client, package_id)
        assert batch_resp.status_code == 201
        batch_id = batch_resp.json()["public_id"]

        # Doer can inspect their own batch and its per-record results.
        assert client.get(f"{BASE}/migration-batches/{batch_id}/").status_code == 200
        assert client.get(f"{BASE}/migration-batches/{batch_id}/results/").status_code == 200

        # PLANTED (detected, and this is the exact bug that was found and
        # fixed this milestone): a Doer must NOT be able to export the
        # reconciliation report -- that requires templates.export_reconciliation,
        # held only by VP/Tenant Admin, not Doer.
        assert (
            client.get(f"{BASE}/migration-batches/{batch_id}/reconciliation.json").status_code
            == 403
        )
        assert (
            client.get(f"{BASE}/migration-batches/{batch_id}/reconciliation.csv").status_code == 403
        )

    def test_reviewer_can_view_but_not_export_reconciliation(
        self, user_a, tenant_a, doer_membership, reviewer_user, reviewer_membership
    ):
        doer_client = _client_for(user_a, tenant_a)
        pkg_resp = _register_package(doer_client, source_name="anda-reviewer-src")
        package_id = pkg_resp.json()["public_id"]
        batch_resp = _run_batch(doer_client, package_id)
        batch_id = batch_resp.json()["public_id"]

        reviewer_client = _client_for(reviewer_user, tenant_a)
        # Reviewer may view the reconciliation data (needed to make
        # duplicate/normalization review decisions)...
        assert (
            reviewer_client.get(
                f"{BASE}/migration-batches/{batch_id}/reconciliation.json"
            ).status_code
            == 200
        )
        # ...but formally exporting/downloading it as a file is reserved
        # for VP/Tenant Admin.
        # PLANTED (detected): reviewer attempting the CSV export.
        assert (
            reviewer_client.get(
                f"{BASE}/migration-batches/{batch_id}/reconciliation.csv"
            ).status_code
            == 403
        )

    def test_vp_can_export_reconciliation(
        self, user_a, tenant_a, doer_membership, vp_user, vp_membership
    ):
        doer_client = _client_for(user_a, tenant_a)
        pkg_resp = _register_package(doer_client, source_name="anda-vp-src")
        package_id = pkg_resp.json()["public_id"]
        batch_resp = _run_batch(doer_client, package_id)
        batch_id = batch_resp.json()["public_id"]

        vp_client = _client_for(vp_user, tenant_a)
        json_resp = vp_client.get(f"{BASE}/migration-batches/{batch_id}/reconciliation.json")
        assert json_resp.status_code == 200
        report = json_resp.json()
        assert "counts" in report
        assert report["counts"]["imported"] == 1

        csv_resp = vp_client.get(f"{BASE}/migration-batches/{batch_id}/reconciliation.csv")
        assert csv_resp.status_code == 200
        assert csv_resp["Content-Type"] == "text/csv"


@pytest.mark.django_db
class TestTenantIsolation:
    def test_tenant_b_cannot_see_tenant_a_source_package(
        self, user_a, tenant_a, doer_membership, user_b, tenant_b
    ):
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        # Give user_b a doer role in tenant_b so permission checks pass;
        # only tenant scoping should be what blocks visibility.
        membership = TenantMembership.objects.create(tenant=tenant_b, user=user_b)
        role, _ = Role.objects.get_or_create(
            tenant=tenant_b, name="doer", defaults={"is_system": True}
        )
        MembershipRole.objects.create(membership=membership, role=role)

        client_a = _client_for(user_a, tenant_a)
        pkg_resp = _register_package(client_a, source_name="tenant-a-only-src")
        package_id = pkg_resp.json()["public_id"]

        client_b = _client_for(user_b, tenant_b)
        # PLANTED: tenant B attempting to read tenant A's private source
        # package list must not surface it, and direct access to tenant A
        # data through any tenant-B-scoped call must be impossible.
        list_resp = client_b.get(f"{BASE}/template-sources/")
        assert list_resp.status_code == 200
        returned_ids = [row["public_id"] for row in list_resp.json()["results"]]
        assert package_id not in returned_ids

    def test_cross_tenant_template_detail_returns_generic_404(
        self, user_a, tenant_a, doer_membership, vp_user, vp_membership, user_b, tenant_b
    ):
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        membership = TenantMembership.objects.create(tenant=tenant_b, user=user_b)
        role, _ = Role.objects.get_or_create(
            tenant=tenant_b, name="doer", defaults={"is_system": True}
        )
        MembershipRole.objects.create(membership=membership, role=role)

        client_a = _client_for(user_a, tenant_a)
        pkg_resp = _register_package(client_a, source_name="tenant-a-template-src")
        package_id = pkg_resp.json()["public_id"]
        _run_batch(client_a, package_id)
        template_list = client_a.get(f"{BASE}/templates/")
        template_id = template_list.json()["results"][0]["public_id"]

        client_b = _client_for(user_b, tenant_b)
        # PLANTED: cross-tenant read of another tenant's template.
        resp = client_b.get(f"{BASE}/templates/{template_id}/")
        assert resp.status_code == 404

        nonexistent_resp = client_b.get(f"{BASE}/templates/00000000-0000-0000-0000-000000000000/")
        # Same generic 404 whether the row exists in another tenant or
        # doesn't exist at all -- never distinguishable to the caller.
        assert nonexistent_resp.status_code == 404
        assert resp.json() == nonexistent_resp.json()


@pytest.mark.django_db
class TestNoInternalIdentifiersExposed:
    def test_template_and_version_responses_expose_no_numeric_id(
        self, user_a, tenant_a, doer_membership, vp_user, vp_membership
    ):
        client = _client_for(user_a, tenant_a)
        pkg_resp = _register_package(client, source_name="anda-shape-src")
        package_id = pkg_resp.json()["public_id"]
        _run_batch(client, package_id)

        vp_client = _client_for(vp_user, tenant_a)
        templates_resp = vp_client.get(f"{BASE}/templates/")
        assert templates_resp.status_code == 200
        for row in templates_resp.json()["results"]:
            # PLANTED: internal BigAutoField PK leaking into an API response.
            assert "id" not in row
            assert "pk" not in row

        template_id = templates_resp.json()["results"][0]["public_id"]
        versions_resp = vp_client.get(f"{BASE}/templates/{template_id}/versions/")
        for row in versions_resp.json()["results"]:
            assert "id" not in row


@pytest.mark.django_db
class TestLifecycleActionsThroughAPI:
    def _full_walk_to_under_review(self, doer_client, package_source_name):
        pkg_resp = _register_package(doer_client, source_name=package_source_name)
        package_id = pkg_resp.json()["public_id"]
        _run_batch(doer_client, package_id)
        template_id = doer_client.get(f"{BASE}/templates/").json()["results"][0]["public_id"]
        version_id = doer_client.get(f"{BASE}/templates/{template_id}/versions/").json()["results"][
            0
        ]["public_id"]
        return template_id, version_id

    def test_doer_cannot_approve_or_activate(
        self, user_a, tenant_a, doer_membership, reviewer_user, reviewer_membership
    ):
        doer_client = _client_for(user_a, tenant_a)
        template_id, version_id = self._full_walk_to_under_review(doer_client, "anda-lifecycle-src")

        submit_resp = doer_client.post(
            f"{BASE}/templates/{template_id}/versions/{version_id}/submit-review/", data={}
        )
        assert submit_resp.status_code == 200

        # PLANTED: doer attempting to approve directly through the API.
        approve_resp = doer_client.post(
            f"{BASE}/templates/{template_id}/versions/{version_id}/approve/", data={}
        )
        assert approve_resp.status_code == 403

        activate_resp = doer_client.post(
            f"{BASE}/templates/{template_id}/versions/{version_id}/activate/", data={}
        )
        assert activate_resp.status_code == 403

    def test_vp_can_approve_and_activate(
        self, user_a, tenant_a, doer_membership, vp_user, vp_membership
    ):
        doer_client = _client_for(user_a, tenant_a)
        template_id, version_id = self._full_walk_to_under_review(
            doer_client, "anda-vp-lifecycle-src"
        )
        doer_client.post(
            f"{BASE}/templates/{template_id}/versions/{version_id}/submit-review/", data={}
        )

        vp_client = _client_for(vp_user, tenant_a)
        approve_resp = vp_client.post(
            f"{BASE}/templates/{template_id}/versions/{version_id}/approve/", data={}
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        activate_resp = vp_client.post(
            f"{BASE}/templates/{template_id}/versions/{version_id}/activate/", data={}
        )
        assert activate_resp.status_code == 200
        assert activate_resp.json()["status"] == "active"
