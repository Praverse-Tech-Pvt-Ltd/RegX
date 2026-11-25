"""Audit inside the transaction (QA-09 follow-up, owner decision 2026-11-23): IID assessment
snapshots. The service opens no transaction of its own; its caller owns it (M4D3-SNO-012),
so the tests call it inside `transaction.atomic()` as every production caller does.
No on-commit capture here.
"""

from __future__ import annotations

import pytest
from django.db import transaction

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from iid_assessment.models import AssessmentSnapshot

from .test_snapshot_service import _create, world  # noqa: F401

EVENT = "iid_assessment.snapshot.created"


def _create_in_a_transaction(world_):
    with transaction.atomic():
        return _create(world_)


@pytest.mark.django_db
class TestTheEventIsWrittenWithTheChange:
    def test_a_snapshot_writes_its_event_in_its_own_transaction(self, world):  # noqa: F811
        result = _create_in_a_transaction(world)
        assert AuditEvent.objects.filter(
            event_type=EVENT, resource_id=result.snapshot_public_id
        ).exists()

    def test_a_rolled_back_snapshot_leaves_no_event(self, world):  # noqa: F811
        with pytest.raises(RuntimeError), transaction.atomic():
            _create(world)
            raise RuntimeError("the caller's later step fails")
        assert not AssessmentSnapshot.objects.exists()
        assert not AuditEvent.objects.filter(event_type=EVENT).exists()


@pytest.mark.django_db(transaction=True)
def test_a_failed_audit_write_rolls_the_snapshot_back(world):  # noqa: F811
    with audit_writes_fail():
        attempt(_create_in_a_transaction, world)
    assert not AssessmentSnapshot.objects.exists()
