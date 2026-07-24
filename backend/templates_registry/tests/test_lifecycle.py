"""
Lifecycle state-machine tests: the full governance walk, segregation of
duties, activation transactionally superseding a prior active version,
and invalid-transition guards.

Every test that plants a violation is noted.
"""

import pytest
from django.core.exceptions import PermissionDenied

from templates_registry import lifecycle
from templates_registry.models import (
    ApprovalDecision,
    RegulatoryTemplate,
    TemplateApproval,
    TemplateLifecycleStatus,
    TemplateVersion,
)


def _draft_version(tenant, canonical_code="TPL-1", created_by=None):
    template = RegulatoryTemplate.objects.create(
        tenant=tenant, canonical_code=canonical_code, title="Test Template", created_by=created_by
    )
    return TemplateVersion.objects.create(
        template=template,
        version_number=1,
        status=TemplateLifecycleStatus.IMPORTED,
        created_by=created_by,
    )


@pytest.mark.django_db
class TestFullLifecycleWalk:
    def test_draft_to_active_walk(self, tenant_a, user_a, vp_user):
        version = _draft_version(tenant_a, created_by=user_a)

        version = lifecycle.submit_for_review(version, user_a)
        assert version.status == TemplateLifecycleStatus.UNDER_REVIEW

        version = lifecycle.approve(version, vp_user, "Looks good", "vp")
        assert version.status == TemplateLifecycleStatus.APPROVED
        assert version.approved_by_id == vp_user.id

        version = lifecycle.activate(version, vp_user)
        assert version.status == TemplateLifecycleStatus.ACTIVE
        assert version.effective_date is not None

        version.template.refresh_from_db()
        assert version.template.current_approved_version_id == version.pk
        assert version.template.lifecycle_status == TemplateLifecycleStatus.ACTIVE

        approval = TemplateApproval.objects.get(template_version=version)
        assert approval.decision == ApprovalDecision.APPROVED
        assert approval.approval_sequence == 1

    def test_return_for_correction_then_resubmit(self, tenant_a, user_a, vp_user):
        version = _draft_version(tenant_a, created_by=user_a)
        version = lifecycle.submit_for_review(version, user_a)
        version = lifecycle.return_for_correction(version, vp_user, "Fix category", "vp")
        assert version.status == TemplateLifecycleStatus.RETURNED

        version = lifecycle.submit_for_review(version, user_a)
        assert version.status == TemplateLifecycleStatus.UNDER_REVIEW

    def test_reject_is_terminal_for_that_version(self, tenant_a, user_a, vp_user):
        version = _draft_version(tenant_a, created_by=user_a)
        version = lifecycle.submit_for_review(version, user_a)
        version = lifecycle.reject(version, vp_user, "Not eligible", "vp")
        assert version.status == TemplateLifecycleStatus.REJECTED

    def test_activation_supersedes_prior_active_version(self, tenant_a, user_a, vp_user):
        template = RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="TPL-SUP", title="Superseded Template"
        )
        v1 = TemplateVersion.objects.create(
            template=template, version_number=1, status=TemplateLifecycleStatus.APPROVED
        )
        v1 = lifecycle.activate(v1, vp_user)
        assert v1.status == TemplateLifecycleStatus.ACTIVE

        v2 = TemplateVersion.objects.create(
            template=template, version_number=2, status=TemplateLifecycleStatus.APPROVED
        )
        v2 = lifecycle.activate(v2, vp_user)
        assert v2.status == TemplateLifecycleStatus.ACTIVE

        v1.refresh_from_db()
        assert v1.status == TemplateLifecycleStatus.SUPERSEDED
        assert v1.superseded_date is not None

        template.refresh_from_db()
        assert template.current_approved_version_id == v2.pk

    def test_supersede_and_retire(self, tenant_a, vp_user):
        template = RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="TPL-RETIRE", title="Retiring Template"
        )
        version = TemplateVersion.objects.create(
            template=template, version_number=1, status=TemplateLifecycleStatus.APPROVED
        )
        version = lifecycle.activate(version, vp_user)
        version = lifecycle.supersede(version, vp_user, "Manual supersession")
        assert version.status == TemplateLifecycleStatus.SUPERSEDED

        template.refresh_from_db()
        assert template.current_approved_version_id is None

        version = lifecycle.retire(version, vp_user, "End of life")
        assert version.status == TemplateLifecycleStatus.RETIRED


@pytest.mark.django_db
class TestSegregationOfDuties:
    def test_reviewer_cannot_approve_their_own_version(self, tenant_a, user_a):
        version = _draft_version(tenant_a, created_by=user_a)
        version = lifecycle.submit_for_review(version, user_a)
        # PLANTED VIOLATION (detected): the creator attempts to approve
        # their own version.
        with pytest.raises(PermissionDenied):
            lifecycle.approve(version, user_a, "Self-approving", "vp")
        version.refresh_from_db()
        assert version.status == TemplateLifecycleStatus.UNDER_REVIEW

    def test_different_approver_succeeds(self, tenant_a, user_a, vp_user):
        version = _draft_version(tenant_a, created_by=user_a)
        version = lifecycle.submit_for_review(version, user_a)
        version = lifecycle.approve(version, vp_user, "Fine", "vp")
        assert version.status == TemplateLifecycleStatus.APPROVED


@pytest.mark.django_db
class TestInvalidTransitions:
    def test_cannot_activate_a_draft_version(self, tenant_a, vp_user):
        version = _draft_version(tenant_a)
        # PLANTED VIOLATION (detected): activating a version that was
        # never approved.
        with pytest.raises(lifecycle.InvalidTransition):
            lifecycle.activate(version, vp_user)
        version.refresh_from_db()
        assert version.status == TemplateLifecycleStatus.IMPORTED

    def test_cannot_approve_a_draft_version_directly(self, tenant_a, vp_user):
        version = _draft_version(tenant_a)
        # PLANTED VIOLATION (detected): approving without submit_for_review.
        with pytest.raises(lifecycle.InvalidTransition):
            lifecycle.approve(version, vp_user, "", "vp")

    def test_cannot_submit_an_active_version_for_review(self, tenant_a, vp_user):
        template = RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="TPL-ACTIVE", title="Active Template"
        )
        version = TemplateVersion.objects.create(
            template=template, version_number=1, status=TemplateLifecycleStatus.APPROVED
        )
        version = lifecycle.activate(version, vp_user)
        with pytest.raises(lifecycle.InvalidTransition):
            lifecycle.submit_for_review(version, vp_user)

    def test_cannot_retire_a_draft_version(self, tenant_a, vp_user):
        version = _draft_version(tenant_a)
        with pytest.raises(lifecycle.InvalidTransition):
            lifecycle.retire(version, vp_user)


@pytest.mark.django_db
class TestApprovalAuditTrail:
    def test_multiple_approval_events_get_sequential_numbers(self, tenant_a, user_a, vp_user):
        version = _draft_version(tenant_a, created_by=user_a)
        version = lifecycle.submit_for_review(version, user_a)
        version = lifecycle.return_for_correction(version, vp_user, "fix", "vp")
        version = lifecycle.submit_for_review(version, user_a)
        version = lifecycle.approve(version, vp_user, "ok", "vp")

        sequences = list(
            TemplateApproval.objects.filter(template_version=version)
            .order_by("approval_sequence")
            .values_list("approval_sequence", "decision")
        )
        assert sequences == [(1, ApprovalDecision.RETURNED), (2, ApprovalDecision.APPROVED)]
