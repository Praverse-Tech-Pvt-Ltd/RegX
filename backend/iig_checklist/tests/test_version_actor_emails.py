"""The checklist version API returns who submitted, approved and activated it (4c, 2026-11-26).

The version page reads submitted_by_email, approved_by_email and activated_by_email; the
serializer never returned them, so an active version showed "not yet submitted / approved /
activated" (browser regression 2026-11-25, N-4). They are read-only.
"""

from __future__ import annotations

import pytest

from iig_checklist.enums import AnswerType, DataSourceClassification

from .test_4d3_activation_validation import _question, _section

BASE = "/api/regx/v1/iig-checklists/versions"


@pytest.mark.django_db
def test_detail_names_the_submitter_approver_and_activator(
    draft_version, api_client_doer, api_client_vp, user_a, vp_user, vp_membership
):
    _question(
        _section(draft_version),
        "Q1",
        answer_type=AnswerType.YES_NO,
        classification=DataSourceClassification.USER_REQUIRED,
    )
    url = f"{BASE}/{draft_version.public_id}/"
    before = api_client_doer.get(url).json()
    assert before["submitted_by_email"] is None
    assert before["approved_by_email"] is None
    assert before["activated_by_email"] is None

    assert api_client_doer.post(f"{url}submit-review/", {}, format="json").status_code == 200
    assert api_client_vp.post(f"{url}approve/", {}, format="json").status_code == 200
    assert api_client_vp.post(f"{url}activate/", {}, format="json").status_code == 200

    after = api_client_doer.get(url).json()
    assert after["status"] == "active"
    assert after["submitted_by_email"] == user_a.email
    assert after["approved_by_email"] == vp_user.email
    assert after["activated_by_email"] == vp_user.email


@pytest.mark.django_db
def test_the_emails_are_read_only(draft_version, api_client_doer):
    resp = api_client_doer.patch(
        f"{BASE}/{draft_version.public_id}/",
        {"submitted_by_email": "forged@example.com"},
        format="json",
    )
    draft_version.refresh_from_db()
    assert draft_version.submitted_by_id is None
    assert resp.status_code in (200, 400)
