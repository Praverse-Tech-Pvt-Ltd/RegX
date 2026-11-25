"""A checklist version with no questions can no longer be submitted, approved or activated.

Found by the browser regression of 2026-11-25 (N-2): a version with no sections went through
submit, approve and activate, and as the active version it would supersede a real one. The
check sits with the other activation prerequisites (effective date, bindings), so it runs before
any change, including superseding a prior active version, and the refusal carries a plain
reason the screen can show.
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from iig_checklist.enums import AnswerType, DataSourceClassification
from iig_checklist.models import ChecklistVersion

from .test_4d3_activation_validation import _question, _section

BASE = "/api/regx/v1/iig-checklists/versions"
REASON = "has no questions"


def _post(client, version, action):
    return client.post(f"{BASE}/{version.public_id}/{action}/", data={}, format="json")


def _set_status(version, status, user=None):
    fields = {"status": status}
    if user is not None:
        fields["submitted_by"] = user
    ChecklistVersion.objects.filter(pk=version.pk).update(**fields)
    version.refresh_from_db()


def _assert_refused(resp, version, status):
    assert resp.status_code == 400, resp.data
    body = resp.json()
    assert body["error"]["code"] == "version_has_no_questions", body
    assert REASON in body["error"]["detail"]["detail"], body
    version.refresh_from_db()
    assert version.status == status


@pytest.mark.django_db
class TestEmptyVersionIsRefused:
    def test_submit_with_no_sections(self, api_client_doer, draft_version):
        _assert_refused(
            _post(api_client_doer, draft_version, "submit-review"), draft_version, "draft"
        )
        assert not AuditEvent.objects.filter(
            resource_id=str(draft_version.public_id),
            event_type="iig_checklist.version.submitted_for_review",
        ).exists()

    def test_submit_with_sections_but_no_questions(self, api_client_doer, draft_version):
        _section(draft_version)
        _assert_refused(
            _post(api_client_doer, draft_version, "submit-review"), draft_version, "draft"
        )

    def test_approve_an_empty_version_already_under_review(
        self, api_client_vp, draft_version, user_a, vp_membership
    ):
        _set_status(draft_version, "under_review", user=user_a)
        _assert_refused(
            _post(api_client_vp, draft_version, "approve"), draft_version, "under_review"
        )

    def test_activate_an_empty_approved_version(
        self, api_client_vp, draft_version, user_a, vp_membership
    ):
        _set_status(draft_version, "approved", user=user_a)
        _assert_refused(_post(api_client_vp, draft_version, "activate"), draft_version, "approved")

    def test_a_version_with_one_question_still_submits(self, api_client_doer, draft_version):
        section = _section(draft_version)
        _question(
            section,
            "Q1",
            answer_type=AnswerType.YES_NO,
            classification=DataSourceClassification.USER_REQUIRED,
        )
        resp = _post(api_client_doer, draft_version, "submit-review")
        assert resp.status_code == 200, resp.data
        draft_version.refresh_from_db()
        assert draft_version.status == "under_review"
