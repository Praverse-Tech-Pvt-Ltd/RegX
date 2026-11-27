"""Reinstate can never leave two approved or live executions for one scope (owner, 2026-11-27).

Two layers:
- The database: the partial unique constraints `unique_active_execution_per_version_formulation`
  and `unique_active_execution_per_formulation_component` allow at most one execution per scope
  (tenant, checklist version, formulation version, subject component) in any status other than
  rejected, cancelled or superseded. Approved is covered. A direct UPDATE that skips every
  Python check is refused.
- The service: reinstate locks the checklist version row and refuses while another execution
  for the scope is live; if a concurrent write still reached the save, the constraint refuses
  it and the reinstate is reported as `AnotherExecutionActive`, never as a server error.

The race tests use two real database connections (two threads), released together.
"""

from __future__ import annotations

import threading

import pytest
from django.db import IntegrityError, connection, connections, transaction

from iig_checklist.models import ChecklistExecution
from iig_checklist.services import AnotherExecutionActive, create_execution, transition_execution

from .test_execution_api import _make_active_cv, _make_execution, _make_fv, _make_product

LIVE_EXCLUDED = ("rejected", "cancelled", "superseded")
REASON = "Race test: reinstate (QA synthetic)."
CONSTRAINTS = (
    "unique_active_execution_per_version_formulation",
    "unique_active_execution_per_formulation_component",
)


def _approved(tenant, cv, fv, user, vp):
    ex = _make_execution(tenant, cv, fv, user)
    ChecklistExecution.objects.filter(pk=ex.pk).update(
        status="approved", submitted_by=user, approved_by=vp, reviewer_conclusion_note="Approved."
    )
    ex.refresh_from_db()
    return ex


def _supersede(ex, vp, tenant):
    transition_execution(
        execution=ex, action="supersede", actor=vp, tenant=tenant, reason="Superseded (QA)."
    )
    ex.refresh_from_db()
    assert ex.status == "superseded"
    return ex


def _two_superseded_for_one_scope(tenant, definition, user, vp):
    """E1 approved then superseded; E2 for the same scope approved then superseded."""
    cv = _make_active_cv(definition, user)
    fv = _make_fv(_make_product(tenant, user), user)
    e1 = _supersede(_approved(tenant, cv, fv, user, vp), vp, tenant)
    e2 = _supersede(_approved(tenant, cv, fv, user, vp), vp, tenant)
    return e1, e2, cv, fv


def _live(cv, fv):
    return ChecklistExecution.objects.filter(checklist_version=cv, formulation_version=fv).exclude(
        status__in=LIVE_EXCLUDED
    )


def _race(*calls):
    """Run each call on its own thread (own DB connection), released together."""
    barrier = threading.Barrier(len(calls))
    outcomes = [None] * len(calls)

    def run(i, fn):
        try:
            barrier.wait(timeout=10)
            outcomes[i] = ("ok", fn())
        except Exception as exc:  # recorded and asserted on below
            outcomes[i] = ("error", exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert all(not t.is_alive() for t in threads), "a racing thread did not finish"
    return outcomes


@pytest.mark.django_db
def test_the_database_itself_refuses_a_second_approved_execution_for_one_scope(
    tenant_a, tenant_definition, user_a, vp_user, doer_membership, vp_membership
):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(%s)",
            [list(CONSTRAINTS)],
        )
        found = dict(cur.fetchall())
    assert set(found) == set(CONSTRAINTS), found
    for indexdef in found.values():
        assert "UNIQUE" in indexdef
        assert "approved" not in indexdef  # approved is not among the excluded statuses
        for excluded in LIVE_EXCLUDED:
            assert excluded in indexdef

    e1, e2, _, _ = _two_superseded_for_one_scope(tenant_a, tenant_definition, user_a, vp_user)
    ChecklistExecution.objects.filter(pk=e1.pk).update(status="approved")
    # A raw UPDATE skips every Python check; the database still refuses.
    with pytest.raises(IntegrityError), transaction.atomic():
        ChecklistExecution.objects.filter(pk=e2.pk).update(status="approved")


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_reinstates_leave_exactly_one_approved(
    tenant_a, tenant_definition, user_a, vp_user, doer_membership, vp_membership
):
    e1, e2, cv, fv = _two_superseded_for_one_scope(tenant_a, tenant_definition, user_a, vp_user)

    def reinstate(ex):
        return lambda: transition_execution(
            execution=ex, action="reinstate", actor=vp_user, tenant=tenant_a, reason=REASON
        ).public_id

    outcomes = _race(reinstate(e1), reinstate(e2))

    assert _live(cv, fv).count() == 1, list(_live(cv, fv).values_list("public_id", "status"))
    assert _live(cv, fv).get().status == "approved"
    oks = [o for o in outcomes if o[0] == "ok"]
    errors = [o[1] for o in outcomes if o[0] == "error"]
    assert len(oks) == 1, outcomes
    assert len(errors) == 1 and isinstance(errors[0], AnotherExecutionActive), outcomes


@pytest.mark.django_db(transaction=True)
def test_a_reinstate_racing_a_new_execution_leaves_at_most_one_live(
    tenant_a, tenant_definition, user_a, vp_user, doer_membership, vp_membership
):
    cv = _make_active_cv(tenant_definition, user_a)
    fv = _make_fv(_make_product(tenant_a, user_a), user_a)
    e1 = _supersede(_approved(tenant_a, cv, fv, user_a, vp_user), vp_user, tenant_a)

    outcomes = _race(
        lambda: transition_execution(
            execution=e1, action="reinstate", actor=vp_user, tenant=tenant_a, reason=REASON
        ).public_id,
        lambda: create_execution(
            tenant=tenant_a,
            checklist_version_public_id=cv.public_id,
            formulation_version_public_id=fv.public_id,
            actor=user_a,
        ).public_id,
    )

    assert _live(cv, fv).count() == 1, list(_live(cv, fv).values_list("public_id", "status"))
    assert (
        ChecklistExecution.objects.filter(
            checklist_version=cv, formulation_version=fv, status="approved"
        ).count()
        <= 1
    )
    assert sum(1 for o in outcomes if o[0] == "ok") == 1, outcomes


@pytest.mark.django_db(transaction=True)
def test_a_reinstate_racing_a_new_approval_leaves_at_most_one_approved(
    tenant_a,
    tenant_definition,
    user_a,
    vp_user,
    reviewer_user,
    doer_membership,
    vp_membership,
    reviewer_membership,
):
    """E2 is waiting for review (so it is already live) when its approval and E1's reinstate
    are released together. Whichever order the database runs them in, at most one execution
    for the scope ends up approved."""
    e1, _, cv, fv = _two_superseded_for_one_scope(tenant_a, tenant_definition, user_a, vp_user)
    # A third execution for the same scope, submitted for review by the Doer.
    e3 = _make_execution(tenant_a, cv, fv, user_a)
    ChecklistExecution.objects.filter(pk=e3.pk).update(
        status="submitted_for_review", submitted_by=user_a
    )
    e3.refresh_from_db()

    outcomes = _race(
        lambda: transition_execution(
            execution=e1, action="reinstate", actor=vp_user, tenant=tenant_a, reason=REASON
        ).public_id,
        lambda: transition_execution(
            execution=e3,
            action="approve",
            actor=vp_user,
            tenant=tenant_a,
            reviewer_conclusion_note="Approved in the race test (QA).",
        ).public_id,
    )

    approved = ChecklistExecution.objects.filter(
        checklist_version=cv, formulation_version=fv, status="approved"
    )
    assert approved.count() <= 1, list(approved.values_list("public_id", flat=True))
    assert _live(cv, fv).count() == 1
    errors = [o[1] for o in outcomes if o[0] == "error"]
    assert all(isinstance(e, AnotherExecutionActive) for e in errors), outcomes
