"""QA-06 (docs/qa/QA_CODEX_REPORT.md), part (a): creating a checklist version ignored effective_date.

POST iig-checklists/definitions/<id>/versions/ with {"effective_date": ...} answered 201 with
effective_date null (the view never reads the request body). It must either save the date or
refuse the field with 400; it must never drop it silently.
"""

import pytest

BASE = "/api/regx/v1"


@pytest.mark.django_db
def test_effective_date_on_create_is_saved_or_refused(api_client_doer, tenant_definition):
    resp = api_client_doer.post(
        f"{BASE}/iig-checklists/definitions/{tenant_definition.public_id}/versions/",
        {"effective_date": "2027-01-01"},
        format="json",
    )
    assert resp.status_code in (201, 400), resp.content[:300]
    if resp.status_code == 201:
        assert resp.json().get("effective_date") == "2027-01-01", resp.json()


# Part (b): prerequisites checked only at activation must also be checked at submit (and
# approve), so a version can never be approved and then fail to activate.
import datetime  # noqa: E402

from .test_4d3_activation_validation import (  # noqa: E402
    _calculated_question,
    _section,
    _selector_question,
)


def _submit(client, version):
    return client.post(
        f"{BASE}/iig-checklists/versions/{version.public_id}/submit-review/", data={}
    )


def _status(version):
    version.refresh_from_db()
    return version.status


@pytest.mark.django_db
class TestPrerequisitesAtSubmit:
    def test_submit_without_effective_date_is_refused(self, api_client_doer, draft_version):
        draft_version.effective_date = None
        draft_version.save(update_fields=["effective_date", "updated_at"])
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w", order=1)
        _selector_question(section)
        resp = _submit(api_client_doer, draft_version)
        assert resp.status_code == 400, resp.data
        assert "effective_date" in str(resp.data)
        assert _status(draft_version) == "draft"

    def test_submit_with_a_binding_missing_its_selector_is_refused(
        self, api_client_doer, draft_version
    ):
        draft_version.effective_date = datetime.date(2027, 1, 1)
        draft_version.save(update_fields=["effective_date", "updated_at"])
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w", order=1)  # no selector question
        resp = _submit(api_client_doer, draft_version)
        assert resp.status_code == 400, resp.data
        assert "REGISTRY_VALIDATION_FAILED" in str(resp.data)
        assert _status(draft_version) == "draft"

    def test_a_complete_version_still_submits(self, api_client_doer, draft_version):
        draft_version.effective_date = datetime.date(2027, 1, 1)
        draft_version.save(update_fields=["effective_date", "updated_at"])
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w", order=1)
        _selector_question(section)
        resp = _submit(api_client_doer, draft_version)
        assert resp.status_code == 200, resp.data
        assert _status(draft_version) == "under_review"
