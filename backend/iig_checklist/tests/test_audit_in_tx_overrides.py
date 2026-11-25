"""Audit inside the transaction (QA-09 follow-up, owner decision 2026-11-23): answer overrides.

See test_audit_in_tx_calculation_and_execution.py for the rule. No on-commit capture here.
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from iig_checklist.overrides import OverrideStaleVersion

from .test_4d4_overrides import _apply, _response, world  # noqa: F401

EVENT = "iig_checklist.answer.overridden"


def _events(world_):
    return AuditEvent.objects.filter(event_type=EVENT, resource_id=str(_response(world_).public_id))


@pytest.mark.django_db
class TestTheEventIsWrittenWithTheChange:
    def test_an_override_writes_its_event_in_its_own_transaction(
        self,
        world,  # noqa: F811
        tenant_a,
        reviewer_user,
        reviewer_membership,
    ):
        _apply(world, reviewer_user, tenant_a)
        assert _events(world).count() == 1

    def test_a_stale_override_writes_no_event(
        self,
        world,  # noqa: F811
        tenant_a,
        reviewer_user,
        reviewer_membership,
    ):
        from iig_checklist.overrides import override_checklist_response

        response = _response(world)
        with pytest.raises(OverrideStaleVersion):
            override_checklist_response(
                tenant=tenant_a,
                execution_public_id=world["execution"].public_id,
                response_public_id=response.public_id,
                actor=reviewer_user,
                payload={
                    "raw_value": {"value": "x"},
                    "override_reason": "Governed deviation reason.",
                    "expected_version": response.version + 5,
                },
            )
        assert not _events(world).exists()


@pytest.mark.django_db(transaction=True)
def test_a_failed_audit_write_rolls_the_override_back(
    world,  # noqa: F811
    tenant_a,
    reviewer_user,
    reviewer_membership,
):
    before = _response(world).raw_value
    with audit_writes_fail():
        attempt(_apply, world, reviewer_user, tenant_a)
    assert _response(world).raw_value == before
