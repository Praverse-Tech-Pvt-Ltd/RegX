"""Supersede on an approved checklist execution needs a typed reason (owner, 2026-11-26).

Found by the browser regression of 2026-11-25 (QA-11): one click on Supersede superseded an
approved execution, with no confirmation and no reason. The server now refuses a supersede
without a non-blank reason, stores the reason on the execution, and writes it into the audit
event, which is written in the same transaction as the change (a failed audit write rolls the
supersede back).
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from iig_checklist.models import ChecklistExecution
from iig_checklist.services import transition_execution

from .test_execution_api import _make_active_cv, _make_execution, _make_fv, _make_product

SUPERSEDED = "iig_checklist.execution.superseded"


def _approved(tenant, definition, user, vp):
    cv = _make_active_cv(definition, user)
    fv = _make_fv(_make_product(tenant, user), user)
    ex = _make_execution(tenant, cv, fv, user)
    ChecklistExecution.objects.filter(pk=ex.pk).update(
        status="approved", submitted_by=user, approved_by=vp, reviewer_conclusion_note="Approved."
    )
    ex.refresh_from_db()
    return ex


def _url(ex):
    return reverse("iig_checklist:execution-supersede", kwargs={"public_id": ex.public_id})


def _events(ex):
    return AuditEvent.objects.filter(event_type=SUPERSEDED, resource_id=str(ex.public_id))


@pytest.mark.django_db
class TestSupersedeNeedsAReason:
    @pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}])
    def test_refused_without_a_reason(
        self,
        body,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex = _approved(tenant_a, tenant_definition, user_a, vp_user)
        resp = api_client_vp.post(_url(ex), body, format="json")
        assert resp.status_code == 400
        assert resp.data["error_code"] == "missing_supersede_reason"
        ex.refresh_from_db()
        assert ex.status == "approved"
        assert not _events(ex).exists()

    def test_with_a_reason_it_supersedes_stores_the_reason_and_audits_it(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex = _approved(tenant_a, tenant_definition, user_a, vp_user)
        reason = "Replaced: the formulation version was corrected (QA synthetic)."
        resp = api_client_vp.post(_url(ex), {"reason": reason}, format="json")
        assert resp.status_code == 200, resp.data
        assert resp.data["status"] == "superseded"
        assert resp.data["supersede_reason"] == reason
        ex.refresh_from_db()
        assert ex.status == "superseded"
        assert ex.supersede_reason == reason
        events = list(_events(ex))
        assert len(events) == 1
        assert events[0].payload["reason"] == reason
        assert events[0].payload["before_status"] == "approved"
        assert events[0].actor_email == vp_user.email

    def test_an_unknown_field_is_still_refused(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex = _approved(tenant_a, tenant_definition, user_a, vp_user)
        resp = api_client_vp.post(_url(ex), {"reason": "x", "superseded_by": "y"}, format="json")
        assert resp.status_code == 400
        ex.refresh_from_db()
        assert ex.status == "approved"

    def test_the_service_refuses_too(
        self, tenant_a, tenant_definition, user_a, vp_user, doer_membership, vp_membership
    ):
        from iig_checklist.services import MissingSupersedeReason

        ex = _approved(tenant_a, tenant_definition, user_a, vp_user)
        with pytest.raises(MissingSupersedeReason):
            transition_execution(execution=ex, action="supersede", actor=vp_user, tenant=tenant_a)
        ex.refresh_from_db()
        assert ex.status == "approved"


@pytest.mark.django_db(transaction=True)
def test_a_failed_audit_write_rolls_the_supersede_back(
    tenant_a, tenant_definition, user_a, vp_user, doer_membership, vp_membership
):
    ex = _approved(tenant_a, tenant_definition, user_a, vp_user)
    with audit_writes_fail():
        attempt(
            transition_execution,
            execution=ex,
            action="supersede",
            actor=vp_user,
            tenant=tenant_a,
            reason="QA synthetic reason",
        )
    ex.refresh_from_db()
    assert ex.status == "approved"
    assert ex.supersede_reason == ""
    assert not _events(ex).exists()
