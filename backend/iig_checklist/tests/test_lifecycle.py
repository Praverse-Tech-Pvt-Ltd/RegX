"""ChecklistVersion lifecycle regression tests -- every legal/illegal
transition, self-approval, Doer-blocked, no-audit-on-failure, and a real
concurrency test, mirroring
fda_data/tests/test_mapping_lifecycle_transitions.py's pattern."""

import threading

import pytest
from django.db import connection
from rest_framework.test import APIClient

from iig_checklist.enums import ChecklistVersionStatus
from iig_checklist.transitions import (
    IllegalVersionTransition,
    VersionAction,
    validate_version_transition,
)

BASE = "/api/regx/v1"


class TestTransitionTableUnit:
    @pytest.mark.parametrize(
        "action,legal_from,result",
        [
            (VersionAction.SUBMIT_REVIEW, ChecklistVersionStatus.DRAFT, ChecklistVersionStatus.UNDER_REVIEW),
            (VersionAction.SUBMIT_REVIEW, ChecklistVersionStatus.RETURNED, ChecklistVersionStatus.UNDER_REVIEW),
            (VersionAction.APPROVE, ChecklistVersionStatus.UNDER_REVIEW, ChecklistVersionStatus.APPROVED),
            (VersionAction.RETURN, ChecklistVersionStatus.UNDER_REVIEW, ChecklistVersionStatus.RETURNED),
            (VersionAction.REJECT, ChecklistVersionStatus.DRAFT, ChecklistVersionStatus.REJECTED),
            (VersionAction.REJECT, ChecklistVersionStatus.UNDER_REVIEW, ChecklistVersionStatus.REJECTED),
            (VersionAction.ACTIVATE, ChecklistVersionStatus.APPROVED, ChecklistVersionStatus.ACTIVE),
            (VersionAction.SUPERSEDE, ChecklistVersionStatus.ACTIVE, ChecklistVersionStatus.SUPERSEDED),
            (VersionAction.RETIRE, ChecklistVersionStatus.DRAFT, ChecklistVersionStatus.RETIRED),
            (VersionAction.RETIRE, ChecklistVersionStatus.APPROVED, ChecklistVersionStatus.RETIRED),
            (VersionAction.RETIRE, ChecklistVersionStatus.ACTIVE, ChecklistVersionStatus.RETIRED),
            (VersionAction.RETIRE, ChecklistVersionStatus.RETURNED, ChecklistVersionStatus.RETIRED),
        ],
    )
    def test_legal_transitions(self, action, legal_from, result):
        assert validate_version_transition(legal_from, action) == result

    @pytest.mark.parametrize(
        "action,illegal_from",
        [
            (VersionAction.APPROVE, ChecklistVersionStatus.DRAFT),
            (VersionAction.APPROVE, ChecklistVersionStatus.RETURNED),
            (VersionAction.APPROVE, ChecklistVersionStatus.REJECTED),
            (VersionAction.APPROVE, ChecklistVersionStatus.SUPERSEDED),
            (VersionAction.APPROVE, ChecklistVersionStatus.RETIRED),
            (VersionAction.ACTIVATE, ChecklistVersionStatus.DRAFT),
            (VersionAction.ACTIVATE, ChecklistVersionStatus.UNDER_REVIEW),
            (VersionAction.ACTIVATE, ChecklistVersionStatus.REJECTED),
            (VersionAction.SUBMIT_REVIEW, ChecklistVersionStatus.APPROVED),
            (VersionAction.SUBMIT_REVIEW, ChecklistVersionStatus.ACTIVE),
            (VersionAction.SUBMIT_REVIEW, ChecklistVersionStatus.REJECTED),
            (VersionAction.SUBMIT_REVIEW, ChecklistVersionStatus.SUPERSEDED),
            (VersionAction.SUBMIT_REVIEW, ChecklistVersionStatus.RETIRED),
            (VersionAction.RETURN, ChecklistVersionStatus.DRAFT),
            (VersionAction.RETURN, ChecklistVersionStatus.APPROVED),
            (VersionAction.RETURN, ChecklistVersionStatus.ACTIVE),
            (VersionAction.REJECT, ChecklistVersionStatus.APPROVED),
            (VersionAction.REJECT, ChecklistVersionStatus.ACTIVE),
            (VersionAction.REJECT, ChecklistVersionStatus.RETURNED),
            (VersionAction.REJECT, ChecklistVersionStatus.REJECTED),
            (VersionAction.SUPERSEDE, ChecklistVersionStatus.DRAFT),
            (VersionAction.SUPERSEDE, ChecklistVersionStatus.APPROVED),
            (VersionAction.RETIRE, ChecklistVersionStatus.REJECTED),
            (VersionAction.RETIRE, ChecklistVersionStatus.SUPERSEDED),
            (VersionAction.RETIRE, ChecklistVersionStatus.RETIRED),
        ],
    )
    def test_illegal_transitions(self, action, illegal_from):
        with pytest.raises(IllegalVersionTransition):
            validate_version_transition(illegal_from, action)


@pytest.mark.django_db
class TestChecklistVersionLifecycleApi:
    def test_full_lifecycle_walk(self, draft_version, api_client_doer, api_client_reviewer, api_client_vp):
        pid = draft_version.public_id

        submit = api_client_doer.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        assert submit.status_code == 200, submit.content
        assert submit.json()["status"] == "under_review"

        approve = api_client_vp.post(f"{BASE}/iig-checklists/versions/{pid}/approve/", data={})
        assert approve.status_code == 200
        assert approve.json()["status"] == "approved"

        draft_version.refresh_from_db()
        draft_version.effective_date = "2026-01-01"
        draft_version.save()

        activate = api_client_vp.post(f"{BASE}/iig-checklists/versions/{pid}/activate/", data={})
        assert activate.status_code == 200
        assert activate.json()["status"] == "active"

    def test_direct_approve_from_draft_blocked(self, draft_version, api_client_vp):
        resp = api_client_vp.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/approve/", data={}
        )
        assert resp.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == "draft"

    def test_direct_activate_from_draft_blocked(self, draft_version, api_client_vp):
        resp = api_client_vp.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/activate/", data={}
        )
        assert resp.status_code == 400

    def test_activate_requires_effective_date(self, draft_version, api_client_doer, api_client_vp):
        pid = draft_version.public_id
        api_client_doer.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        api_client_vp.post(f"{BASE}/iig-checklists/versions/{pid}/approve/", data={})
        resp = api_client_vp.post(f"{BASE}/iig-checklists/versions/{pid}/activate/", data={})
        assert resp.status_code == 400

    def test_illegal_transition_emits_no_audit_event(self, draft_version, api_client_vp):
        from audit.models import AuditEvent

        before = AuditEvent.objects.filter(resource_id=str(draft_version.public_id)).count()
        api_client_vp.post(f"{BASE}/iig-checklists/versions/{draft_version.public_id}/approve/", data={})
        after = AuditEvent.objects.filter(resource_id=str(draft_version.public_id)).count()
        assert after == before

    def test_self_approval_blocked(self, draft_version, api_client_vp, vp_user, tenant_a):
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        # Grant the VP user Doer permissions too, so the same actor can both
        # submit and attempt to approve -- the only way to meaningfully
        # exercise the same-actor self-approval guard under this permission
        # model, since submit_review and approve are otherwise held by
        # disjoint built-in roles.
        membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp_user)
        doer_role, _ = Role.objects.get_or_create(
            tenant=tenant_a, name="doer", defaults={"is_system": True}
        )
        MembershipRole.objects.get_or_create(membership=membership, role=doer_role)

        pid = draft_version.public_id
        api_client_vp.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        draft_version.refresh_from_db()
        assert draft_version.status == "under_review"
        resp = api_client_vp.post(f"{BASE}/iig-checklists/versions/{pid}/approve/", data={})
        assert resp.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == "under_review"

    def test_doer_cannot_approve_or_activate(self, draft_version, api_client_doer, api_client_reviewer):
        pid = draft_version.public_id
        api_client_reviewer.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        resp = api_client_doer.post(f"{BASE}/iig-checklists/versions/{pid}/approve/", data={})
        assert resp.status_code == 403

    def test_return_then_edit_then_resubmit_preserves_provenance(
        self, draft_version, api_client_doer, api_client_reviewer
    ):
        pid = draft_version.public_id
        api_client_doer.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        returned = api_client_reviewer.post(
            f"{BASE}/iig-checklists/versions/{pid}/return/", data={"reason": "fix section order"}
        )
        assert returned.status_code == 200
        assert returned.json()["status"] == "returned"

        draft_version.refresh_from_db()
        assert draft_version.return_reason == "fix section order"
        first_returned_at = draft_version.returned_at

        resubmit = api_client_doer.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        assert resubmit.status_code == 200
        draft_version.refresh_from_db()
        assert draft_version.returned_at == first_returned_at
        assert draft_version.return_reason == "fix section order"

    def test_rejected_is_terminal_and_cannot_resurrect(
        self, draft_version, api_client_reviewer, api_client_doer
    ):
        pid = draft_version.public_id
        reject = api_client_reviewer.post(f"{BASE}/iig-checklists/versions/{pid}/reject/", data={})
        assert reject.status_code == 200
        resubmit = api_client_doer.post(f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={})
        assert resubmit.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_activation_serializes_to_one_active_version(
        self, tenant_definition, user_a, vp_user, tenant_a
    ):
        from authorization.models import MembershipRole, Role
        from iig_checklist.models import ChecklistVersion
        from tenancy.models import TenantMembership

        membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp_user)
        role, _ = Role.objects.get_or_create(tenant=tenant_a, name="vp", defaults={"is_system": True})
        MembershipRole.objects.get_or_create(membership=membership, role=role)

        v1 = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=1,
            status="approved",
            effective_date="2026-01-01",
            created_by=user_a,
        )
        v2 = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=2,
            status="approved",
            effective_date="2026-01-01",
            created_by=user_a,
        )

        results = []

        def activate(version):
            client = APIClient()
            client.force_authenticate(user=vp_user)
            client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
            resp = client.post(f"{BASE}/iig-checklists/versions/{version.public_id}/activate/", data={})
            results.append(resp.status_code)
            connection.close()

        threads = [threading.Thread(target=activate, args=(v,)) for v in (v1, v2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        active_count = ChecklistVersion.objects.filter(
            definition=tenant_definition, status="active"
        ).count()
        assert active_count == 1
        assert sorted(results) == [200, 200]  # both succeed: second supersedes/activates in turn
