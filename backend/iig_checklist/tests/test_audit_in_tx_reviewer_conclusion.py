"""Audit inside the transaction (QA-09 follow-up, owner decision 2026-11-23): the reviewer
conclusion. No on-commit capture here.
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail

from .test_4d4_reviewer_conclusion_completion import _body, _response, _url, world  # noqa: F401

PREFIX = "checklist_response.reviewer_conclusion_"


def _events(world_):
    return AuditEvent.objects.filter(
        event_type__startswith=PREFIX, resource_id=str(_response(world_).public_id)
    )


@pytest.mark.django_db
class TestTheEventIsWrittenWithTheChange:
    def test_a_conclusion_writes_its_event_in_its_own_transaction(
        self,
        world,  # noqa: F811
        api_client_reviewer,
        reviewer_membership,
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_body(response.version), format="json"
        )
        assert resp.status_code == 200
        assert _events(world).count() == 1

    def test_a_stale_conclusion_writes_no_event(
        self,
        world,  # noqa: F811
        api_client_reviewer,
        reviewer_membership,
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_body(response.version + 5), format="json"
        )
        assert resp.status_code == 409
        assert not _events(world).exists()


@pytest.mark.django_db(transaction=True)
def test_a_failed_audit_write_rolls_the_conclusion_back(
    world,  # noqa: F811
    api_client_reviewer,
    reviewer_membership,
):
    response = _response(world)
    before = (response.raw_value, response.version)
    with audit_writes_fail():
        attempt(
            api_client_reviewer.post,
            _url(world, response),
            data=_body(response.version),
            format="json",
        )
    after = _response(world)
    assert (after.raw_value, after.version) == before
