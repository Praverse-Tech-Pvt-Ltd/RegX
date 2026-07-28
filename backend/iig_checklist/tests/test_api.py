"""API-level tests: UUID-only, tenant isolation, mass assignment,
deletion policy, sections/questions CRUD."""

import uuid

import pytest

BASE = "/api/regx/v1"


@pytest.mark.django_db
class TestDefinitionApi:
    def test_create_and_uuid_only_response(self, api_client_doer):
        resp = api_client_doer.post(
            f"{BASE}/iig-checklists/definitions/",
            data={"code": "NEW-DEF", "title": "New Definition", "scope_type": "tenant"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert "id" not in body
        assert "pk" not in body
        uuid.UUID(body["public_id"])  # does not raise

    def test_generic_404_for_nonexistent(self, api_client_doer):
        resp = api_client_doer.get(f"{BASE}/iig-checklists/definitions/{uuid.uuid4()}/")
        assert resp.status_code == 404

    def test_tenant_isolation(self, api_client_doer, tenant_b, user_a):
        from iig_checklist.models import ChecklistDefinition

        other = ChecklistDefinition.objects.create(
            code="OTHER-TENANT-DEF",
            title="t",
            scope_type="tenant",
            tenant=tenant_b,
            created_by=user_a,
        )
        resp = api_client_doer.get(f"{BASE}/iig-checklists/definitions/{other.public_id}/")
        assert resp.status_code == 404

    def test_platform_master_visible_to_any_tenant(self, api_client_doer, user_a):
        from iig_checklist.models import ChecklistDefinition

        platform_def = ChecklistDefinition.objects.create(
            code="PLATFORM-VISIBLE",
            title="t",
            scope_type="platform_master",
            created_by=user_a,
        )
        resp = api_client_doer.get(f"{BASE}/iig-checklists/definitions/{platform_def.public_id}/")
        assert resp.status_code == 200


@pytest.mark.django_db
class TestVersionApiMassAssignment:
    def test_status_cannot_be_patched_generically(self, draft_version, api_client_doer):
        resp = api_client_doer.patch(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/",
            data={"status": "approved"},
            format="json",
        )
        assert resp.status_code == 200
        draft_version.refresh_from_db()
        assert draft_version.status == "draft"

    def test_patch_blocked_once_under_review(self, draft_version, api_client_doer):
        api_client_doer.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/submit-review/", data={}
        )
        resp = api_client_doer.patch(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/",
            data={"regulatory_basis": "changed"},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["detail"].get("error_code") == "VERSION_NO_LONGER_EDITABLE"


@pytest.mark.django_db
class TestSectionQuestionApi:
    def test_create_section_and_question(self, draft_version, api_client_doer):
        section_resp = api_client_doer.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/sections/",
            data={
                "code": "SEC-API",
                "title": "Section via API",
                "display_order": 1,
                "criticality": "medium",
            },
            format="json",
        )
        assert section_resp.status_code == 201, section_resp.content
        section_pid = section_resp.json()["public_id"]

        question_resp = api_client_doer.post(
            f"{BASE}/iig-checklists/sections/{section_pid}/questions/",
            data={
                "code": "Q-API",
                "question_text": "Is this a synthetic question?",
                "display_order": 1,
                "answer_type": "yes_no",
                "data_source_classification": "user_required",
                "criticality": "low",
            },
            format="json",
        )
        assert question_resp.status_code == 201, question_resp.content

    def test_section_delete_blocked_once_not_editable(self, draft_version, api_client_doer):
        section_resp = api_client_doer.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/sections/",
            data={"code": "SEC-LOCK", "title": "s", "display_order": 1, "criticality": "low"},
            format="json",
        )
        section_pid = section_resp.json()["public_id"]
        api_client_doer.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/submit-review/", data={}
        )
        resp = api_client_doer.delete(f"{BASE}/iig-checklists/sections/{section_pid}/")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestDeletionPolicyApi:
    def test_empty_never_submitted_draft_can_be_deleted(self, draft_version, api_client_doer):
        definition_pid = draft_version.definition.public_id
        resp = api_client_doer.delete(f"{BASE}/iig-checklists/definitions/{definition_pid}/")
        assert resp.status_code == 204

    def test_submitted_definition_cannot_be_deleted(self, draft_version, api_client_doer):
        api_client_doer.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/submit-review/", data={}
        )
        resp = api_client_doer.delete(
            f"{BASE}/iig-checklists/definitions/{draft_version.definition.public_id}/"
        )
        assert resp.status_code == 400

    def test_multi_version_definition_cannot_be_deleted(
        self, tenant_definition, draft_version, user_a, api_client_doer
    ):
        from iig_checklist.services import create_next_version

        create_next_version(definition=tenant_definition, actor=user_a)
        resp = api_client_doer.delete(
            f"{BASE}/iig-checklists/definitions/{tenant_definition.public_id}/"
        )
        assert resp.status_code == 400

    def test_deletion_emits_audit_event(self, draft_version, api_client_doer):
        from audit.models import AuditEvent

        definition_pid = str(draft_version.definition.public_id)
        api_client_doer.delete(f"{BASE}/iig-checklists/definitions/{definition_pid}/")
        assert AuditEvent.objects.filter(
            resource_id=definition_pid, event_type="iig_checklist.definition.deleted"
        ).exists()
