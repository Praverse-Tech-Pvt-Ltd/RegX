"""API-level clone endpoint tests."""

import pytest

from .conftest import add_one_question

BASE = "/api/regx/v1"


@pytest.mark.django_db
class TestCloneEndpoint:
    def _approve_and_activate(self, version, api_client_doer, api_client_vp):
        pid = version.public_id
        api_client_doer.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        api_client_vp.post(f"{BASE}/iig-checklists/versions/{pid}/approve/", data={})
        version.refresh_from_db()

    def test_clone_via_api(self, draft_version, api_client_doer, api_client_vp):
        add_one_question(draft_version)  # N-2: a version needs a question
        self._approve_and_activate(draft_version, api_client_doer, api_client_vp)
        resp = api_client_doer.post(
            f"{BASE}/iig-checklists/definitions/{draft_version.definition.public_id}/clone/",
            data={
                "source_version_public_id": str(draft_version.public_id),
                "target_scope_type": "tenant",
                "target_tenant_public_id": str(draft_version.definition.tenant.public_id),
                "new_code": "cloned-via-api",
                "new_title": "Cloned via API",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["current_version"]["status"] == "draft"
        assert body["current_version"]["version_number"] == 1

    def test_clone_cross_tenant_blocked(
        self, draft_version, api_client_doer, api_client_vp, tenant_b
    ):
        self._approve_and_activate(draft_version, api_client_doer, api_client_vp)
        resp = api_client_doer.post(
            f"{BASE}/iig-checklists/definitions/{draft_version.definition.public_id}/clone/",
            data={
                "source_version_public_id": str(draft_version.public_id),
                "target_scope_type": "tenant",
                "target_tenant_public_id": str(tenant_b.public_id),
                "new_code": "cross-tenant-clone",
                "new_title": "Should be blocked",
            },
            format="json",
        )
        assert resp.status_code == 403

    def test_clone_still_draft_source_rejected(self, draft_version, api_client_doer):
        resp = api_client_doer.post(
            f"{BASE}/iig-checklists/definitions/{draft_version.definition.public_id}/clone/",
            data={
                "source_version_public_id": str(draft_version.public_id),
                "target_scope_type": "tenant",
                "target_tenant_public_id": str(draft_version.definition.tenant.public_id),
                "new_code": "should-fail",
                "new_title": "x",
            },
            format="json",
        )
        assert resp.status_code == 400
