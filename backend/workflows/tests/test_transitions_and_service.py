"""Transition table, service layer, history immutability and audit emission.

Synthetic data only. No production regulatory content.
"""

import pytest

from workflows import services
from workflows.models import (
    WorkflowHistoryMutationForbidden,
    WorkflowItem,
    WorkflowTransition,
)
from workflows.transitions import (
    TERMINAL_STATES,
    IllegalWorkflowTransition,
    WorkflowAction,
    legal_actions_from,
    validate_workflow_transition,
)

S = WorkflowItem.State


class TestTransitionTable:
    """Pure table behaviour -- no database, no permissions."""

    @pytest.mark.parametrize(
        "current,action,expected",
        [
            (S.DRAFT, WorkflowAction.SUBMIT, S.SUBMITTED),
            (S.DRAFT, WorkflowAction.CANCEL, S.CANCELLED),
            (S.SUBMITTED, WorkflowAction.BEGIN_REVIEW, S.IN_REVIEW),
            (S.SUBMITTED, WorkflowAction.CANCEL, S.CANCELLED),
            (S.IN_REVIEW, WorkflowAction.APPROVE, S.APPROVED),
            (S.IN_REVIEW, WorkflowAction.REJECT, S.REJECTED),
            (S.IN_REVIEW, WorkflowAction.CANCEL, S.CANCELLED),
            (S.REJECTED, WorkflowAction.RETURN_TO_DRAFT, S.DRAFT),
            (S.REJECTED, WorkflowAction.CANCEL, S.CANCELLED),
        ],
    )
    def test_legal_transitions(self, current, action, expected):
        assert validate_workflow_transition(current, action) == expected

    @pytest.mark.parametrize(
        "current,action",
        [
            (S.DRAFT, WorkflowAction.APPROVE),
            (S.DRAFT, WorkflowAction.REJECT),
            (S.DRAFT, WorkflowAction.BEGIN_REVIEW),
            (S.SUBMITTED, WorkflowAction.APPROVE),
            (S.SUBMITTED, WorkflowAction.SUBMIT),
            (S.IN_REVIEW, WorkflowAction.SUBMIT),
            (S.APPROVED, WorkflowAction.REJECT),
            (S.APPROVED, WorkflowAction.CANCEL),
            (S.APPROVED, WorkflowAction.RETURN_TO_DRAFT),
            (S.CANCELLED, WorkflowAction.SUBMIT),
            (S.CANCELLED, WorkflowAction.APPROVE),
            (S.REJECTED, WorkflowAction.APPROVE),
        ],
    )
    def test_illegal_transitions_raise(self, current, action):
        with pytest.raises(IllegalWorkflowTransition):
            validate_workflow_transition(current, action)

    def test_unknown_action_raises(self):
        with pytest.raises(IllegalWorkflowTransition):
            validate_workflow_transition(S.DRAFT, "teleport")

    def test_terminal_states_have_no_outgoing_actions(self):
        for state in TERMINAL_STATES:
            assert legal_actions_from(state) == [], f"{state} should be terminal"

    def test_approved_is_terminal(self):
        """APPROVED stays terminal in this milestone -- see the discovery note
        on why the supersede pattern was not imported."""
        assert S.APPROVED in TERMINAL_STATES
        assert legal_actions_from(S.APPROVED) == []


@pytest.mark.django_db
class TestServiceTransitions:
    def test_full_happy_path_records_history(self, item_a, tenant_a, doer_a, reviewer_a):
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        final = services.perform_transition(
            item=item_a, action="approve", actor=reviewer_a, tenant=tenant_a
        )

        assert final.state == S.APPROVED
        rows = list(WorkflowTransition.objects.filter(workflow_item=item_a))
        assert [(r.from_state, r.to_state) for r in rows] == [
            (S.DRAFT, S.SUBMITTED),
            (S.SUBMITTED, S.IN_REVIEW),
            (S.IN_REVIEW, S.APPROVED),
        ]
        assert rows[0].actor_id == doer_a.pk
        assert rows[2].actor_id == reviewer_a.pk

    def test_rejected_returns_to_draft(self, item_a, tenant_a, doer_a, reviewer_a):
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        services.perform_transition(
            item=item_a, action="reject", actor=reviewer_a, tenant=tenant_a, reason="Needs work"
        )
        back = services.perform_transition(
            item=item_a, action="return_to_draft", actor=doer_a, tenant=tenant_a
        )
        assert back.state == S.DRAFT

    def test_reject_requires_reason(self, item_a, tenant_a, doer_a, reviewer_a):
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        with pytest.raises(services.ReasonRequired):
            services.perform_transition(
                item=item_a, action="reject", actor=reviewer_a, tenant=tenant_a, reason="   "
            )
        item_a.refresh_from_db()
        assert item_a.state == S.IN_REVIEW, "a rejected attempt must not move the item"

    def test_cancel_requires_reason(self, item_a, tenant_a, doer_a):
        with pytest.raises(services.ReasonRequired):
            services.perform_transition(
                item=item_a, action="cancel", actor=doer_a, tenant=tenant_a, reason=""
            )

    def test_approve_reason_optional(self, item_a, tenant_a, doer_a, reviewer_a):
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        out = services.perform_transition(
            item=item_a, action="approve", actor=reviewer_a, tenant=tenant_a
        )
        assert out.state == S.APPROVED

    def test_permission_denied_for_wrong_role(self, item_a, tenant_a, doer_a, reviewer_a):
        """A doer may submit but not approve; a reviewer the reverse."""
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        with pytest.raises(services.WorkflowPermissionDenied):
            services.perform_transition(
                item=item_a, action="approve", actor=doer_a, tenant=tenant_a
            )

    def test_outsider_denied(self, item_a, tenant_a, outsider):
        """Authenticated but not a member: fail closed."""
        with pytest.raises(services.WorkflowPermissionDenied):
            services.perform_transition(
                item=item_a, action="submit", actor=outsider, tenant=tenant_a
            )

    def test_failed_transition_writes_no_history(self, item_a, tenant_a, doer_a):
        with pytest.raises(IllegalWorkflowTransition):
            services.perform_transition(
                item=item_a, action="approve", actor=doer_a, tenant=tenant_a
            )
        assert WorkflowTransition.objects.filter(workflow_item=item_a).count() == 0

    def test_cross_tenant_transition_refused(self, item_b, tenant_a, doer_a):
        with pytest.raises(services.TenantMismatch):
            services.perform_transition(item=item_b, action="submit", actor=doer_a, tenant=tenant_a)


@pytest.mark.django_db
class TestAssignment:
    def test_assign_and_unassign(self, item_a, tenant_a, reviewer_a, doer_a):
        assigned = services.assign(item=item_a, assignee=doer_a, actor=reviewer_a, tenant=tenant_a)
        assert assigned.assigned_to_id == doer_a.pk
        assert assigned.assigned_at is not None

        cleared = services.assign(item=item_a, assignee=None, actor=reviewer_a, tenant=tenant_a)
        assert cleared.assigned_to_id is None
        assert cleared.assigned_at is None

    def test_cross_tenant_assignee_refused(self, item_a, tenant_a, reviewer_a, doer_b):
        """The release-blocking rule: a user from another tenant is never a
        valid assignee, even for a caller with workflows.assign."""
        with pytest.raises(services.InvalidAssignee):
            services.assign(item=item_a, assignee=doer_b, actor=reviewer_a, tenant=tenant_a)

    def test_assignment_refused_on_terminal_item(self, item_a, tenant_a, doer_a, reviewer_a):
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        services.perform_transition(
            item=item_a, action="approve", actor=reviewer_a, tenant=tenant_a
        )
        with pytest.raises(IllegalWorkflowTransition):
            services.assign(item=item_a, assignee=doer_a, actor=reviewer_a, tenant=tenant_a)

    def test_assignment_is_audited(self, item_a, tenant_a, reviewer_a, doer_a):
        from audit.models import AuditEvent

        services.assign(item=item_a, assignee=doer_a, actor=reviewer_a, tenant=tenant_a)
        event = AuditEvent.objects.filter(event_type="workflow.assigned").latest("created_at")
        assert event.resource_id == str(item_a.public_id)
        assert event.payload["assigned_to_public_id"] == str(doer_a.public_id)


@pytest.mark.django_db
class TestHistoryImmutability:
    def _one_row(self, item, tenant, actor):
        services.perform_transition(item=item, action="submit", actor=actor, tenant=tenant)
        return WorkflowTransition.objects.get(workflow_item=item)

    def test_save_on_existing_row_forbidden(self, item_a, tenant_a, doer_a):
        row = self._one_row(item_a, tenant_a, doer_a)
        row.reason = "tampered"
        with pytest.raises(WorkflowHistoryMutationForbidden):
            row.save()

    def test_instance_delete_forbidden(self, item_a, tenant_a, doer_a):
        row = self._one_row(item_a, tenant_a, doer_a)
        with pytest.raises(WorkflowHistoryMutationForbidden):
            row.delete()

    def test_queryset_update_forbidden(self, item_a, tenant_a, doer_a):
        self._one_row(item_a, tenant_a, doer_a)
        with pytest.raises(WorkflowHistoryMutationForbidden):
            WorkflowTransition.objects.filter(workflow_item=item_a).update(reason="tampered")

    def test_queryset_delete_forbidden(self, item_a, tenant_a, doer_a):
        self._one_row(item_a, tenant_a, doer_a)
        with pytest.raises(WorkflowHistoryMutationForbidden):
            WorkflowTransition.objects.filter(workflow_item=item_a).delete()

    def test_bulk_update_forbidden(self, item_a, tenant_a, doer_a):
        row = self._one_row(item_a, tenant_a, doer_a)
        row.reason = "tampered"
        with pytest.raises(WorkflowHistoryMutationForbidden):
            WorkflowTransition.objects.bulk_update([row], ["reason"])


@pytest.mark.django_db
class TestAuditEmission:
    @pytest.mark.parametrize(
        "action,event_type",
        [
            ("submit", "workflow.submitted"),
            ("begin_review", "workflow.review_started"),
            ("approve", "workflow.approved"),
        ],
    )
    def test_each_transition_emits(self, item_a, tenant_a, doer_a, reviewer_a, action, event_type):
        from audit.models import AuditEvent

        sequence = [("submit", doer_a), ("begin_review", reviewer_a), ("approve", reviewer_a)]
        for act, actor in sequence:
            services.perform_transition(item=item_a, action=act, actor=actor, tenant=tenant_a)
            if act == action:
                break

        assert AuditEvent.objects.filter(
            event_type=event_type, resource_id=str(item_a.public_id)
        ).exists()

    def test_reason_text_is_not_written_to_audit(self, item_a, tenant_a, doer_a, reviewer_a):
        """The audit payload records that a reason was given and its length --
        never the text. The text lives on the append-only transition row."""
        from audit.models import AuditEvent

        secret = "REASON_TEXT_SHOULD_NOT_REACH_AUDIT_PAYLOAD"
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        services.perform_transition(
            item=item_a, action="reject", actor=reviewer_a, tenant=tenant_a, reason=secret
        )

        event = AuditEvent.objects.filter(event_type="workflow.rejected").latest("created_at")
        assert secret not in str(event.payload)
        assert event.payload["reason_supplied"] is True
        assert event.payload["reason_length"] == len(secret)
        # ...but it is preserved where it belongs.
        assert WorkflowTransition.objects.get(action="reject").reason == secret

    def test_payload_is_allow_listed(self, item_a, tenant_a, doer_a):
        from audit.models import AuditEvent
        from workflows.audit_events import _ALLOWED_PAYLOAD_KEYS

        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        event = AuditEvent.objects.filter(event_type="workflow.submitted").latest("created_at")
        assert set(event.payload).issubset(_ALLOWED_PAYLOAD_KEYS)


@pytest.mark.django_db
class TestDraftEditing:
    def test_edit_draft(self, item_a, tenant_a, doer_a):
        out = services.update_draft(item=item_a, actor=doer_a, tenant=tenant_a, title="Renamed")
        assert out.title == "Renamed"

    def test_edit_refused_once_submitted(self, item_a, tenant_a, doer_a):
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        with pytest.raises(IllegalWorkflowTransition):
            services.update_draft(item=item_a, actor=doer_a, tenant=tenant_a, title="Sneaky")


@pytest.mark.django_db
class TestOverdue:
    def test_not_overdue_without_due_date(self, item_a):
        assert item_a.is_overdue is False

    def test_overdue_when_past_and_open(self, item_a):
        from datetime import timedelta

        from django.utils import timezone

        item_a.due_at = timezone.now() - timedelta(days=1)
        item_a.save(update_fields=["due_at"])
        assert item_a.is_overdue is True

    def test_terminal_item_is_never_overdue(self, item_a, tenant_a, doer_a, reviewer_a):
        from datetime import timedelta

        from django.utils import timezone

        item_a.due_at = timezone.now() - timedelta(days=1)
        item_a.save(update_fields=["due_at"])
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        approved = services.perform_transition(
            item=item_a, action="approve", actor=reviewer_a, tenant=tenant_a
        )
        assert approved.is_overdue is False
