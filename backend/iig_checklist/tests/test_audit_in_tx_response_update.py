"""Audit inside the transaction (QA-09 follow-up, owner decision 2026-11-23): response
entry/update. No on-commit capture here.
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail

from .test_4d3_response_update import _select_component, world  # noqa: F401

EVENTS = ("iig_checklist.response.entered", "iig_checklist.response.updated")


def _events(world_):
    return AuditEvent.objects.filter(
        event_type__in=EVENTS, resource_id=str(world_["selector_response"].public_id)
    )


@pytest.mark.django_db
class TestTheEventIsWrittenWithTheChange:
    def test_an_update_writes_its_event_in_its_own_transaction(self, world, api_client_doer):  # noqa: F811
        assert _select_component(world, api_client_doer).status_code == 200
        assert _events(world).count() == 1

    def test_a_stale_update_writes_no_event(self, world, api_client_doer):  # noqa: F811
        assert _select_component(world, api_client_doer, expected_version=99).status_code == 409
        assert not _events(world).exists()


@pytest.mark.django_db(transaction=True)
def test_a_failed_audit_write_rolls_the_update_back(world, api_client_doer):  # noqa: F811
    selector = world["selector_response"]
    selector.refresh_from_db()
    before = (selector.raw_value, selector.version)
    with audit_writes_fail():
        attempt(_select_component, world, api_client_doer)
    selector.refresh_from_db()
    assert (selector.raw_value, selector.version) == before
