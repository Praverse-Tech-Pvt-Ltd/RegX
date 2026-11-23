"""Audit inside the transaction (QA-09 follow-up; owner decision 2026-11-23): calculations
and execution creation.

The audit event used to be written by `transaction.on_commit()`, i.e. AFTER the change
committed, so a failed audit write left the change with no record. It is now written
inside the change's transaction. The spec's goal still holds: a refused change (here a
stale version) writes no event, because the rollback removes it with the change.

No `django_capture_on_commit_callbacks` anywhere in this file: the event must exist
without any post-commit callback running.
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from iig_checklist.models import CalculationOutcome, ChecklistExecution
from iig_checklist.services import create_execution

from .test_4d3_calculation_execution import _run, world  # noqa: F401

CALCULATED = "iig_checklist.response.calculated"
CREATED = "iig_checklist.execution.created"


def _free_the_slot(world_):
    """The fixture already holds the active execution for this version and formulation;
    a cancelled one does not block a new one (ExecutionAlreadyActive)."""
    ChecklistExecution.objects.filter(pk=world_["execution"].pk).update(status="cancelled")


def _calculated_events(world_):
    return AuditEvent.objects.filter(
        event_type=CALCULATED, resource_id=str(world_["responses"]["percentage_w_w"].public_id)
    )


@pytest.mark.django_db
class TestTheEventIsWrittenWithTheChange:
    def test_a_calculation_writes_its_event_in_its_own_transaction(self, world):  # noqa: F811
        _run(world, "percentage_w_w")
        assert _calculated_events(world).count() == 1

    def test_a_stale_calculation_writes_no_event(self, world):  # noqa: F811
        from iig_checklist.calculation_execution import StaleResponseVersion

        with pytest.raises(StaleResponseVersion):
            _run(world, "percentage_w_w", expected_version=999)
        assert not _calculated_events(world).exists()

    def test_creating_an_execution_writes_its_event_in_its_own_transaction(self, world):  # noqa: F811
        _free_the_slot(world)
        execution = create_execution(
            tenant=world["tenant"],
            checklist_version_public_id=str(world["version"].public_id),
            formulation_version_public_id=str(world["formulation"].public_id),
            actor=world["user"],
        )
        assert AuditEvent.objects.filter(
            event_type=CREATED, resource_id=str(execution.public_id)
        ).exists()


@pytest.mark.django_db(transaction=True)
class TestAFailedAuditWriteRollsTheChangeBack:
    def test_calculation(self, world):  # noqa: F811
        outcome = world["outcomes"]["percentage_w_w"]
        before = CalculationOutcome.objects.get(pk=outcome.pk).status
        with audit_writes_fail():
            attempt(_run, world, "percentage_w_w")
        assert CalculationOutcome.objects.get(pk=outcome.pk).status == before

    def test_execution_creation(self, world):  # noqa: F811
        _free_the_slot(world)
        before = ChecklistExecution.objects.count()
        with audit_writes_fail():
            attempt(
                create_execution,
                tenant=world["tenant"],
                checklist_version_public_id=str(world["version"].public_id),
                formulation_version_public_id=str(world["formulation"].public_id),
                actor=world["user"],
            )
        assert ChecklistExecution.objects.count() == before
