"""The person who submitted a checklist version for review cannot Reject or Return it
(owner, 2026-11-27). Approve was already refused (self-approval); the UI hides all three
from the submitter (#169). This is the server-side rule, so every caller is held to it.

Submit-review belongs to the Doer role and return/reject to Reviewer/VP, so the gap is
reached by a person who holds both (a Reviewer or VP who is also a Doer), as in
test_lifecycle.test_self_approval_blocked.
"""

import pytest

from audit.models import AuditEvent

BASE = "/api/regx/v1"
pytestmark = pytest.mark.django_db


def _url(version, action):
    return f"{BASE}/iig-checklists/versions/{version.public_id}/{action}/"


def _events(version):
    return list(
        AuditEvent.objects.filter(resource_id=str(version.public_id)).values_list(
            "event_type", flat=True
        )
    )


def _grant_doer(tenant, user):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    doer_role, _ = Role.objects.get_or_create(
        tenant=None, name="doer", defaults={"is_system": True}
    )
    MembershipRole.objects.get_or_create(membership=membership, role=doer_role)


def _submit(client, version):
    resp = client.post(_url(version, "submit-review"), data={})
    assert resp.status_code == 200, resp.content
    version.refresh_from_db()
    assert version.status == "under_review"


class TestSubmitterRefused:
    @pytest.mark.parametrize(
        "action,code",
        [("return", "submitter_cannot_return"), ("reject", "submitter_cannot_reject")],
    )
    def test_reviewer_cannot_act_on_their_own_submission(
        self, draft_version, api_client_reviewer, reviewer_user, tenant_a, action, code
    ):
        _grant_doer(tenant_a, reviewer_user)
        _submit(api_client_reviewer, draft_version)
        before = _events(draft_version)

        resp = api_client_reviewer.post(_url(draft_version, action), data={"reason": "own"})

        assert resp.status_code == 400, resp.content
        error = resp.json()["error"]
        assert error["code"] == code
        verb = code.rsplit("_", 1)[1]
        assert error["detail"] == {
            "detail": f"You submitted this version for review, so someone else must {verb} it."
        }
        draft_version.refresh_from_db()
        assert draft_version.status == "under_review"
        assert draft_version.returned_by_id is None
        assert draft_version.rejected_by_id is None
        assert _events(draft_version) == before  # nothing written for a refusal

    def test_vp_who_submitted_cannot_reject(self, draft_version, api_client_vp, vp_user, tenant_a):
        _grant_doer(tenant_a, vp_user)
        _submit(api_client_vp, draft_version)
        resp = api_client_vp.post(_url(draft_version, "reject"), data={})
        assert resp.status_code == 400
        assert "submitter_cannot_reject" in str(resp.content)
        draft_version.refresh_from_db()
        assert draft_version.status == "under_review"


class TestSomeoneElseStillCan:
    def test_reviewer_returns_a_doers_submission(
        self, draft_version, api_client_doer, api_client_reviewer, reviewer_user
    ):
        _submit(api_client_doer, draft_version)
        resp = api_client_reviewer.post(_url(draft_version, "return"), data={"reason": "fix it"})
        assert resp.status_code == 200, resp.content
        draft_version.refresh_from_db()
        assert draft_version.status == "returned"
        assert draft_version.returned_by_id == reviewer_user.id

    def test_reviewer_rejects_a_doers_submission(
        self, draft_version, api_client_doer, api_client_reviewer, reviewer_user
    ):
        _submit(api_client_doer, draft_version)
        resp = api_client_reviewer.post(_url(draft_version, "reject"), data={})
        assert resp.status_code == 200, resp.content
        draft_version.refresh_from_db()
        assert draft_version.status == "rejected"
        assert draft_version.rejected_by_id == reviewer_user.id

    def test_a_never_submitted_draft_can_still_be_rejected(
        self, draft_version, api_client_reviewer
    ):
        # Reject is legal from draft; nobody has submitted it, so there is no submitter to refuse.
        resp = api_client_reviewer.post(_url(draft_version, "reject"), data={})
        assert resp.status_code == 200, resp.content
