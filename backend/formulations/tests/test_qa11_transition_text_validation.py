"""QA-11 (QA_CODEX_REPORT.md): a non-string note or reason on approve, return or reject gave HTTP 500.

The views passed request data straight to the service, which calls .strip(). The
note (approve) and reason (return, reject) are now validated by a serializer: a
value that is not text is refused with 400 and a field error, and nothing changes.
A text value behaves as before (a missing or blank one is still refused by the
service with its own message).
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent

from .test_version_approval import _draft, _post, _status, people  # noqa: F401

pytestmark = pytest.mark.django_db

NOT_TEXT = [123, 1.5, True, ["a note"], {"text": "a note"}, None]
ACTIONS = [
    ("approve", "note", "vp"),
    ("return", "reason", "reviewer"),
    ("reject", "reason", "reviewer"),
]


def _under_review(people, code):  # noqa: F811
    doer = people["doer"][1]
    _, vid = _draft(doer, code=code)
    assert _post(doer, vid, "submit-review").status_code == 200
    return vid


@pytest.mark.parametrize(("action", "field", "who"), ACTIONS)
@pytest.mark.parametrize("value", NOT_TEXT, ids=lambda v: type(v).__name__)
def test_a_value_that_is_not_text_is_refused_with_400(people, action, field, who, value):  # noqa: F811
    vid = _under_review(people, f"QA11-{action}-{type(value).__name__}")
    events_before = AuditEvent.objects.filter(resource_id=vid).count()
    resp = _post(people[who][1], vid, action, {field: value})
    assert resp.status_code == 400, (resp.status_code, resp.content[:200])
    detail = resp.json()["error"]["detail"]
    assert field in detail, detail
    assert _status(vid) == "under_review"
    assert AuditEvent.objects.filter(resource_id=vid).count() == events_before


@pytest.mark.parametrize(("action", "field", "who"), ACTIONS)
def test_text_still_works(people, action, field, who):  # noqa: F811
    vid = _under_review(people, f"QA11-OK-{action}")
    resp = _post(people[who][1], vid, action, {field: "Checked against the batch record."})
    assert resp.status_code == 200, resp.json()
    assert _status(vid) == {"approve": "approved", "return": "draft", "reject": "retired"}[action]


@pytest.mark.parametrize(("action", "field", "who"), ACTIONS)
def test_blank_or_missing_text_is_still_refused_by_the_service(people, action, field, who):  # noqa: F811
    vid = _under_review(people, f"QA11-BLANK-{action}")
    for body in ({}, {field: "   "}):
        resp = _post(people[who][1], vid, action, body)
        assert resp.status_code == 400, resp.json()
        assert resp.json()["error_code"] in ("note_required", "reason_required")
    assert _status(vid) == "under_review"
