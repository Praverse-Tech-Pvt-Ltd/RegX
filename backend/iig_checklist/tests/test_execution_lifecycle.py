"""Lifecycle/transition tests for Milestone 4D-2 execution services."""

import pytest

from iig_checklist.execution_transitions import (
    IllegalExecutionTransition,
    TERMINAL_EXECUTION_STATUSES,
    validate_execution_transition,
)
from iig_checklist.services import (
    SelfApprovalForbidden,
    transition_execution,
)


# ---------------------------------------------------------------------------
# Pure transition table tests (no DB)
# ---------------------------------------------------------------------------


class TestTransitionTable:
    def test_submit_review_from_draft(self):
        assert validate_execution_transition("draft", "submit_review") == "submitted_for_review"

    def test_submit_review_from_returned(self):
        assert validate_execution_transition("returned", "submit_review") == "submitted_for_review"

    def test_approve_from_submitted(self):
        assert validate_execution_transition("submitted_for_review", "approve") == "approved"

    def test_return_from_submitted(self):
        assert validate_execution_transition("submitted_for_review", "return") == "returned"

    def test_reject_from_draft(self):
        assert validate_execution_transition("draft", "reject") == "rejected"

    def test_reject_from_submitted(self):
        assert validate_execution_transition("submitted_for_review", "reject") == "rejected"

    def test_cancel_from_draft(self):
        assert validate_execution_transition("draft", "cancel") == "cancelled"

    def test_cancel_from_returned(self):
        assert validate_execution_transition("returned", "cancel") == "cancelled"

    def test_supersede_from_approved(self):
        assert validate_execution_transition("approved", "supersede") == "superseded"

    def test_unknown_action_raises(self):
        with pytest.raises(IllegalExecutionTransition, match="Unknown action"):
            validate_execution_transition("draft", "nonexistent")

    def test_illegal_from_state_raises(self):
        with pytest.raises(IllegalExecutionTransition):
            validate_execution_transition("approved", "submit_review")

    def test_terminal_statuses_set(self):
        assert "rejected" in TERMINAL_EXECUTION_STATUSES
        assert "cancelled" in TERMINAL_EXECUTION_STATUSES
        assert "superseded" in TERMINAL_EXECUTION_STATUSES
        assert "approved" not in TERMINAL_EXECUTION_STATUSES


class TestTerminalStatuses:
    @pytest.mark.parametrize("status", ["rejected", "cancelled", "superseded"])
    def test_no_transition_from_terminal(self, status):
        for action in ("submit_review", "approve", "return", "cancel", "supersede"):
            with pytest.raises(IllegalExecutionTransition):
                validate_execution_transition(status, action)


# ---------------------------------------------------------------------------
# DB-backed lifecycle tests
# ---------------------------------------------------------------------------


def _make_product(tenant, user):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code="PROD-LC-01",
        name="LC Test Product",
        dosage_form="tablet",
        administration_route="oral",
        created_by=user,
    )


def _make_formulation_version(product, user):
    from formulations.models import FormulationVersion

    fv = FormulationVersion(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight="100.000000",
        total_dosage_unit_weight_unit="mg",
        created_by=user,
    )
    fv.save()
    return fv


def _make_active_cv(tenant_definition, user):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=1,
        status="active",
        created_by=user,
    )


def _make_execution(tenant, cv, fv, user):
    from iig_checklist.models import ChecklistExecution
    from iig_checklist.enums import ExecutionStatus

    ex = ChecklistExecution(
        tenant=tenant,
        checklist_version=cv,
        formulation_version=fv,
        status=ExecutionStatus.DRAFT,
        created_by=user,
    )
    ex.full_clean()
    ex.save()
    return ex


@pytest.mark.django_db
class TestSelfApprovalGuard:
    def test_self_approval_raises(
        self,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
        reviewer_membership,
    ):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_cv(tenant_definition, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)

        # user_a submits
        execution.status = "submitted_for_review"
        execution.submitted_by = user_a
        execution.save()

        # user_a tries to approve their own submission — must fail
        with pytest.raises(SelfApprovalForbidden):
            transition_execution(
                execution=execution,
                action="approve",
                actor=user_a,
                tenant=tenant_a,
                reviewer_conclusion_note="Some conclusion",
            )

    def test_different_user_can_approve(
        self,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
        reviewer_membership,
    ):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_cv(tenant_definition, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)

        execution.status = "submitted_for_review"
        execution.submitted_by = user_a
        execution.save()

        updated = transition_execution(
            execution=execution,
            action="approve",
            actor=vp_user,
            tenant=tenant_a,
            reviewer_conclusion_note="Reviewed and approved.",
        )
        assert updated.status == "approved"


@pytest.mark.django_db
class TestConcurrentApproval:
    def test_double_approval_is_idempotent_via_transition_guard(
        self,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        """After approving, re-approving must raise IllegalExecutionTransition."""
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_cv(tenant_definition, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)
        execution.status = "submitted_for_review"
        execution.submitted_by = user_a
        execution.save()

        updated = transition_execution(
            execution=execution,
            action="approve",
            actor=vp_user,
            tenant=tenant_a,
            reviewer_conclusion_note="First approval.",
        )
        with pytest.raises(IllegalExecutionTransition):
            transition_execution(
                execution=updated,
                action="approve",
                actor=vp_user,
                tenant=tenant_a,
                reviewer_conclusion_note="Second approval.",
            )
