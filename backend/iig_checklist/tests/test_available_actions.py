# ruff: noqa: F811  (pytest fixtures imported from another test module)
"""QA-13 (docs/QA_BROWSER_TEST_2026-11-18.md): the execution detail lists only
the actions this user could take now, so the screen stops offering buttons the
server would refuse (the Doer saw Approve on their own submission).

Display only: every action endpoint keeps its own permission and
self-approval checks (tested elsewhere and again below).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iig_checklist.execution_transitions import available_actions

from .test_p2_audit_coverage import active_version, approved_formulation, execution  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/regx/v1/iig-checklists/executions/{}/"


def _submitted(execution, user):
    from iig_checklist.models import ChecklistExecution

    ChecklistExecution.objects.filter(pk=execution.pk).update(
        status="submitted_for_review", submitted_by=user
    )


class TestTheRule:
    def test_a_submitter_with_approve_permission_is_not_offered_approve(self):
        user = SimpleNamespace(id=7)
        ex = SimpleNamespace(status="submitted_for_review", submitted_by_id=7)
        assert available_actions(ex, user, lambda codename: True) == ["return", "reject"]

    def test_someone_else_is_offered_approve(self):
        ex = SimpleNamespace(status="submitted_for_review", submitted_by_id=7)
        assert "approve" in available_actions(ex, SimpleNamespace(id=8), lambda c: True)

    def test_no_permission_no_action(self):
        ex = SimpleNamespace(status="draft", submitted_by_id=None)
        assert available_actions(ex, SimpleNamespace(id=1), lambda c: False) == []


class TestThroughTheApi:
    def test_doer_on_a_draft(self, api_client_doer, execution):
        actions = api_client_doer.get(URL.format(execution.public_id)).json()["available_actions"]
        assert "submit_review" in actions
        assert "approve" not in actions

    def test_doer_on_their_own_submission_sees_no_approve(
        self,
        api_client_doer,
        execution,
        user_a,
    ):
        _submitted(execution, user_a)
        actions = api_client_doer.get(URL.format(execution.public_id)).json()["available_actions"]
        assert "approve" not in actions and "return" not in actions

    def test_vp_on_someone_elses_submission_sees_approve(
        self,
        api_client_vp,
        execution,
        user_a,
    ):
        _submitted(execution, user_a)
        actions = api_client_vp.get(URL.format(execution.public_id)).json()["available_actions"]
        assert "approve" in actions

    def test_the_server_still_refuses_the_doer(self, api_client_doer, execution, user_a):
        _submitted(execution, user_a)
        resp = api_client_doer.post(
            URL.format(execution.public_id) + "approve/",
            data={"reviewer_conclusion_note": "x"},
            format="json",
        )
        assert resp.status_code == 403
