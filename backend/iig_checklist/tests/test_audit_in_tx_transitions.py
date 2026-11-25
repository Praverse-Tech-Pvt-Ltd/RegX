"""Audit inside the transaction (QA-09 follow-up, owner decision 2026-11-23): execution
transitions (the approval path). No on-commit capture here.
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from iig_checklist.models import ChecklistExecution
from iig_checklist.services import ReviewerConclusionRequired, transition_execution

from .test_4d4_approval_capabilities import _approve, world  # noqa: F401

APPROVED = "iig_checklist.execution.approved"


def _events(world_):
    return AuditEvent.objects.filter(
        event_type=APPROVED, resource_id=str(world_["execution"].public_id)
    )


@pytest.mark.django_db
class TestTheEventIsWrittenWithTheChange:
    def test_an_approval_writes_its_event_in_its_own_transaction(
        self,
        world,  # noqa: F811
        tenant_a,
        vp_user,
        vp_membership,
    ):
        _approve(world, vp_user, tenant_a)
        assert _events(world).count() == 1

    def test_a_refused_approval_writes_no_event(
        self,
        world,  # noqa: F811
        tenant_a,
        vp_user,
        vp_membership,
    ):
        execution = world["execution"]
        ChecklistExecution.objects.filter(pk=execution.pk).update(status="submitted_for_review")
        execution.refresh_from_db()
        with pytest.raises(ReviewerConclusionRequired):
            transition_execution(
                tenant=tenant_a,
                execution=execution,
                action="approve",
                actor=vp_user,
                reviewer_conclusion_note="",
            )
        assert not _events(world).exists()


@pytest.mark.django_db(transaction=True)
def test_a_failed_audit_write_rolls_the_approval_back(
    world,  # noqa: F811
    tenant_a,
    vp_user,
    vp_membership,
):
    with audit_writes_fail():
        attempt(_approve, world, vp_user, tenant_a)
    assert ChecklistExecution.objects.get(pk=world["execution"].pk).status == "submitted_for_review"
