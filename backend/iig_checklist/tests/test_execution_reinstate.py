"""Reinstate a superseded checklist execution (owner, 2026-11-27; follow-up to #167).

Rules:
- VP only (permission `iig_checklist.reinstate_execution`, held by the VP role alone).
- A typed, non-blank reason is required; the server refuses without one.
- The audit event is written in the same transaction as the change (a failed audit write
  rolls the reinstate back).
- History is never deleted or rewritten: the supersede reason and the original approval stay
  on the execution, and the superseded and reinstated audit events both stay on record.
- Refused while another execution for the same scope (tenant, checklist version, formulation
  version, subject component) is live, i.e. not rejected, cancelled or superseded.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from iig_checklist.execution_transitions import available_actions
from iig_checklist.models import ChecklistExecution
from iig_checklist.permissions import has_iig_checklist_permission
from iig_checklist.services import transition_execution

from .test_execution_api import _make_active_cv, _make_execution, _make_fv, _make_product

SUPERSEDED = "iig_checklist.execution.superseded"
REINSTATED = "iig_checklist.execution.reinstated"
SUPERSEDE_REASON = "Replaced while the formulation was corrected (QA synthetic)."
REINSTATE_REASON = "The correction was withdrawn; the earlier approval stands (QA synthetic)."


def _superseded(tenant, definition, user, vp):
    """An approved execution superseded through the real service (so its audit event exists)."""
    cv = _make_active_cv(definition, user)
    fv = _make_fv(_make_product(tenant, user), user)
    ex = _make_execution(tenant, cv, fv, user)
    ChecklistExecution.objects.filter(pk=ex.pk).update(
        status="approved", submitted_by=user, approved_by=vp, reviewer_conclusion_note="Approved."
    )
    ex.refresh_from_db()
    transition_execution(
        execution=ex, action="supersede", actor=vp, tenant=tenant, reason=SUPERSEDE_REASON
    )
    ex.refresh_from_db()
    assert ex.status == "superseded"
    return ex, cv, fv


def _url(ex):
    return reverse("iig_checklist:execution-reinstate", kwargs={"public_id": ex.public_id})


def _events(ex, event_type):
    return AuditEvent.objects.filter(event_type=event_type, resource_id=str(ex.public_id))


FIXTURES = (
    "tenant_a",
    "tenant_definition",
    "user_a",
    "vp_user",
    "doer_membership",
    "vp_membership",
)


@pytest.mark.django_db
class TestReinstate:
    def test_vp_with_a_reason_reinstates_and_keeps_the_history(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        approved_at = ex.approved_at

        resp = api_client_vp.post(_url(ex), {"reason": REINSTATE_REASON}, format="json")

        assert resp.status_code == 200, resp.data
        assert resp.data["status"] == "approved"
        assert resp.data["reinstate_reason"] == REINSTATE_REASON
        assert resp.data["reinstated_by_email"] == vp_user.email
        assert resp.data["supersede_reason"] == SUPERSEDE_REASON  # not cleared
        ex.refresh_from_db()
        assert ex.status == "approved"
        assert ex.reinstate_reason == REINSTATE_REASON
        assert ex.reinstated_by_id == vp_user.id
        assert ex.reinstated_at is not None
        # the original approval is not rewritten
        assert ex.approved_by_id == vp_user.id
        assert ex.approved_at == approved_at
        assert ex.supersede_reason == SUPERSEDE_REASON
        # both events stay on record
        assert _events(ex, SUPERSEDED).count() == 1
        reinstated = list(_events(ex, REINSTATED))
        assert len(reinstated) == 1
        payload = reinstated[0].payload
        assert payload["reason"] == REINSTATE_REASON
        assert payload["before_status"] == "superseded"
        assert payload["after_status"] == "approved"
        assert payload["supersede_reason"] == SUPERSEDE_REASON
        assert reinstated[0].actor_email == vp_user.email

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
        ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        resp = api_client_vp.post(_url(ex), body, format="json")
        assert resp.status_code == 400
        assert resp.data["error_code"] == "missing_reinstate_reason"
        ex.refresh_from_db()
        assert ex.status == "superseded"
        assert not _events(ex, REINSTATED).exists()

    def test_refused_while_another_execution_for_the_same_scope_is_live(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex, cv, fv = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        other = _make_execution(tenant_a, cv, fv, user_a)  # a new draft for the same scope

        resp = api_client_vp.post(_url(ex), {"reason": REINSTATE_REASON}, format="json")

        assert resp.status_code == 409
        assert resp.data["error_code"] == "another_execution_active"
        assert str(other.public_id) in resp.data["detail"]
        ex.refresh_from_db()
        assert ex.status == "superseded"
        assert not _events(ex, REINSTATED).exists()

    @pytest.mark.parametrize("closed", ["cancelled", "rejected", "superseded"])
    def test_allowed_when_the_other_execution_is_closed(
        self,
        closed,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex, cv, fv = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        other = _make_execution(tenant_a, cv, fv, user_a)
        ChecklistExecution.objects.filter(pk=other.pk).update(status=closed)
        resp = api_client_vp.post(_url(ex), {"reason": REINSTATE_REASON}, format="json")
        assert resp.status_code == 200, resp.data

    def test_only_a_superseded_execution_can_be_reinstated(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        ex = _make_execution(
            tenant_a, cv, _make_fv(_make_product(tenant_a, user_a), user_a), user_a
        )
        ChecklistExecution.objects.filter(pk=ex.pk).update(status="approved", approved_by=vp_user)
        resp = api_client_vp.post(_url(ex), {"reason": REINSTATE_REASON}, format="json")
        assert resp.status_code == 400
        assert resp.data["error_code"] == "illegal_execution_transition"

    def test_an_unknown_field_is_refused(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        resp = api_client_vp.post(_url(ex), {"reason": "x", "approved_by": "y"}, format="json")
        assert resp.status_code == 400
        ex.refresh_from_db()
        assert ex.status == "superseded"


@pytest.mark.django_db
class TestVpOnly:
    def test_reviewer_is_refused(
        self,
        api_client_reviewer,
        reviewer_membership,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        resp = api_client_reviewer.post(_url(ex), {"reason": REINSTATE_REASON}, format="json")
        assert resp.status_code == 403
        ex.refresh_from_db()
        assert ex.status == "superseded"

    def test_doer_is_refused(
        self,
        api_client_doer,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        resp = api_client_doer.post(_url(ex), {"reason": REINSTATE_REASON}, format="json")
        assert resp.status_code == 403

    def test_the_permission_is_held_by_the_vp_role_alone(self):
        from authorization.models import Role
        from iig_checklist.permissions import ROLE_PERMISSIONS

        holders = [
            r
            for r, perms in ROLE_PERMISSIONS.items()
            if "iig_checklist.reinstate_execution" in perms
        ]
        assert holders == [Role.BuiltIn.VP]

    def test_the_screen_offers_reinstate_to_the_vp_only(
        self,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        reviewer_user,
        doer_membership,
        vp_membership,
        reviewer_membership,
    ):
        ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        for user, expected in ((vp_user, True), (reviewer_user, False), (user_a, False)):
            actions = available_actions(
                ex, user, lambda c, u=user: has_iig_checklist_permission(u, tenant_a, c)
            )
            assert ("reinstate" in actions) is expected, (user.email, actions)

    def test_the_service_refuses_a_non_vp(
        self,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        reviewer_user,
        doer_membership,
        vp_membership,
        reviewer_membership,
    ):
        from rest_framework.exceptions import PermissionDenied

        ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
        with pytest.raises(PermissionDenied):
            transition_execution(
                execution=ex, action="reinstate", actor=reviewer_user, tenant=tenant_a, reason="x"
            )


@pytest.mark.django_db(transaction=True)
def test_a_failed_audit_write_rolls_the_reinstate_back(
    tenant_a, tenant_definition, user_a, vp_user, doer_membership, vp_membership
):
    ex, _, _ = _superseded(tenant_a, tenant_definition, user_a, vp_user)
    with audit_writes_fail():
        attempt(
            transition_execution,
            execution=ex,
            action="reinstate",
            actor=vp_user,
            tenant=tenant_a,
            reason=REINSTATE_REASON,
        )
    ex.refresh_from_db()
    assert ex.status == "superseded"
    assert ex.reinstate_reason == ""
    assert ex.reinstated_by_id is None
    assert not _events(ex, REINSTATED).exists()
