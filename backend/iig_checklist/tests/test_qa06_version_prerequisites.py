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
