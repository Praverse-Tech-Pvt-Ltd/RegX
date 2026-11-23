"""QA-18 (docs/qa/QA_CODEX_REPORT.md; reproduced in #154): review stamps were changeable under review.

While a version was under review the trigger excluded the review stamps from its "nothing
changed" check and allowed a same-status update, and the approval branch compared the
approver with NEW.submitted_by_id. So SQL could change the submitter, and one UPDATE could
rewrite the submitter and approve as the original submitter.

Migration formulations.0005 freezes the submitter and every review stamp under review: staying
under review changes nothing; returning, rejecting or approving may set only that step's own
stamps; the self-approval check reads the stored (OLD) creator and submitter.

The first two tests are #154's reproductions with their xfail removed; the SQL is unchanged.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, InternalError, ProgrammingError, connection, transaction

from formulations.models import FormulationVersion

from .test_version_approval import _draft, _post, people  # noqa: F401

DB_REFUSED = (ProgrammingError, InternalError, IntegrityError)
pytestmark = pytest.mark.django_db


def _under_review_by(people, code):  # noqa: F811
    """Created by the Doer, submitted by another user (Doer+VP), so creator != submitter."""
    creator, submitter_client = people["doer"][1], people["doer_vp"][1]
    _, vid = _draft(creator, code=code)
    assert _post(submitter_client, vid, "submit-review").status_code == 200
    v = FormulationVersion.objects.get(public_id=vid)
    assert v.submitted_by_id == people["doer_vp"][0].id
    return v


def _sql(statement, params):
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(statement, params)


def test_qa18_submitter_stamp_is_frozen_under_review(people):  # noqa: F811
    v = _under_review_by(people, "INV-QA18A")
    with pytest.raises(DB_REFUSED):
        _sql(
            "UPDATE formulations_formulationversion SET submitted_by_id = %s WHERE id = %s",
            [people["reviewer"][0].id, v.id],
        )


def test_qa18_submitter_cannot_self_approve_by_rewriting_the_stamp(people):  # noqa: F811
    v = _under_review_by(people, "INV-QA18B")
    submitter = people["doer_vp"][0]
    with pytest.raises(DB_REFUSED):
        _sql(
            "UPDATE formulations_formulationversion SET submitted_by_id = %s, status = 'approved', "
            "approved_by_id = %s, approved_at = now(), approval_note = 'maintenance' WHERE id = %s",
            [people["reviewer"][0].id, submitter.id, v.id],
        )


@pytest.mark.parametrize(
    "assignment",
    [
        "submitted_at = now() - interval '1 day'",
        "approved_by_id = {other}, approved_at = now(), approval_note = 'x'",  # stamps without approving
        "returned_by_id = {other}, returned_at = now(), return_reason = 'x'",
        "rejected_by_id = {other}, rejected_at = now(), reject_reason = 'x'",
    ],
)
def test_no_review_stamp_changes_while_staying_under_review(people, assignment):  # noqa: F811
    v = _under_review_by(people, "QA18-STAY-" + str(abs(hash(assignment)) % 1000))
    with pytest.raises(DB_REFUSED):
        _sql(
            f"UPDATE formulations_formulationversion SET {assignment.format(other=people['reviewer'][0].id)} WHERE id = %s",
            [v.id],
        )


def test_approving_cannot_rewrite_another_steps_stamps(people):  # noqa: F811
    v = _under_review_by(people, "QA18-APPROVE-EXTRA")
    vp = people["vp"][0]
    with pytest.raises(DB_REFUSED):
        _sql(
            "UPDATE formulations_formulationversion SET status = 'approved', approved_by_id = %s, "
            "approved_at = now(), approval_note = 'ok', return_reason = 'rewritten' WHERE id = %s",
            [vp.id, v.id],
        )


class TestTheNormalFlowStillWorks:
    def test_return_reject_approve_through_the_api(self, people):  # noqa: F811
        reviewer, vp = people["reviewer"][1], people["vp"][1]
        v = _under_review_by(people, "QA18-OK-RET")
        assert (
            _post(reviewer, v.public_id, "return", {"reason": "Fix the grade."}).status_code == 200
        )
        v2 = _under_review_by(people, "QA18-OK-REJ")
        assert (
            _post(reviewer, v2.public_id, "reject", {"reason": "Wrong product."}).status_code == 200
        )
        v3 = _under_review_by(people, "QA18-OK-APP")
        assert (
            _post(vp, v3.public_id, "approve", {"note": "Reviewed (internal)."}).status_code == 200
        )
        v3.refresh_from_db()
        assert v3.status == "approved"
