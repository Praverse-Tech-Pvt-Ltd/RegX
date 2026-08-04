"""API tests for reviewer-conclusion endpoint -- Milestone 4D-2."""

import pytest
from django.urls import reverse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(tenant, user, code="PROD-RC-API"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code=code,
        proposed_product_name=f"Product {code}",
        active_ingredient="Synthetic RC Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )


def _make_fv(product, user):
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


def _make_reviewer_conclusion_question(cv, user):
    from iig_checklist.models import ChecklistQuestion, ChecklistSection

    section, _ = ChecklistSection.objects.get_or_create(
        checklist_version=cv,
        code="SEC-RC-1",
        defaults={"title": "RC Section", "display_order": 1, "criticality": "medium"},
    )
    return ChecklistQuestion.objects.create(
        section=section,
        code="Q-RC-1",
        question_text="Reviewer conclusion?",
        display_order=1,
        answer_type="reviewer_conclusion",
        data_source_classification="reviewer_confirmed",
        criticality="high",
        reviewer_confirmation_required=True,
    )


def _create_execution_submitted(tenant, tenant_definition, user, submitter):
    """Create and submit an execution, return (execution, rc_response)."""

    cv = _make_active_cv(tenant_definition, user)
    _make_reviewer_conclusion_question(cv, user)
    product = _make_product(tenant, user)
    fv = _make_fv(product, user)

    # Use service so responses are pre-created.
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=submitter)
    role, _ = Role.objects.get_or_create(tenant=tenant, name="doer", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

    from iig_checklist.services import create_execution

    ex = create_execution(
        tenant=tenant,
        checklist_version_public_id=str(cv.public_id),
        formulation_version_public_id=str(fv.public_id),
        actor=submitter,
    )
    ex.status = "submitted_for_review"
    ex.submitted_by = submitter
    ex.save()

    rc_response = ex.responses.filter(question__answer_type="reviewer_conclusion").first()
    return ex, rc_response


# ---------------------------------------------------------------------------
# First entry
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReviewerConclusionFirstEntry:
    def test_post_creates_entry_returns_200(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_user,
        reviewer_membership,
        doer_membership,
    ):
        ex, rc_response = _create_execution_submitted(tenant_a, tenant_definition, user_a, user_a)

        url = reverse(
            "iig_checklist:execution-reviewer-conclusion",
            kwargs={
                "public_id": ex.public_id,
                "response_public_id": rc_response.public_id,
            },
        )
        resp = api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "Initial conclusion text."},
                "expected_version": rc_response.version,
            },
            format="json",
        )
        assert resp.status_code == 200
        rc_response.refresh_from_db()
        assert rc_response.raw_value == {"value": "Initial conclusion text."}
        assert rc_response.version == 2

    def test_empty_value_rejected(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_user,
        reviewer_membership,
        doer_membership,
    ):
        ex, rc_response = _create_execution_submitted(tenant_a, tenant_definition, user_a, user_a)
        url = reverse(
            "iig_checklist:execution-reviewer-conclusion",
            kwargs={
                "public_id": ex.public_id,
                "response_public_id": rc_response.public_id,
            },
        )
        resp = api_client_reviewer.post(
            url,
            {"raw_value": {"value": "   "}, "expected_version": rc_response.version},
            format="json",
        )
        assert resp.status_code in (400, 422)

    def test_too_long_value_rejected(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_membership,
        doer_membership,
    ):
        ex, rc_response = _create_execution_submitted(tenant_a, tenant_definition, user_a, user_a)
        url = reverse(
            "iig_checklist:execution-reviewer-conclusion",
            kwargs={
                "public_id": ex.public_id,
                "response_public_id": rc_response.public_id,
            },
        )
        resp = api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "x" * 5000},
                "expected_version": rc_response.version,
            },
            format="json",
        )
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Amendment (second entry)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReviewerConclusionAmendment:
    def test_amendment_creates_history_row(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_user,
        reviewer_membership,
        doer_membership,
    ):
        from iig_checklist.models import ChecklistResponseHistory

        ex, rc_response = _create_execution_submitted(tenant_a, tenant_definition, user_a, user_a)
        url = reverse(
            "iig_checklist:execution-reviewer-conclusion",
            kwargs={
                "public_id": ex.public_id,
                "response_public_id": rc_response.public_id,
            },
        )

        # First entry
        api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "First conclusion."},
                "expected_version": rc_response.version,
            },
            format="json",
        )

        rc_response.refresh_from_db()

        # Second entry (amendment) -- correction_reason required
        resp = api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "Amended conclusion."},
                "expected_version": rc_response.version,
                "correction_reason": "Typo corrected.",
            },
            format="json",
        )
        assert resp.status_code == 200
        assert ChecklistResponseHistory.objects.filter(response=rc_response).count() == 1

    def test_amendment_without_correction_reason_rejected(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_membership,
        doer_membership,
    ):
        ex, rc_response = _create_execution_submitted(tenant_a, tenant_definition, user_a, user_a)
        url = reverse(
            "iig_checklist:execution-reviewer-conclusion",
            kwargs={
                "public_id": ex.public_id,
                "response_public_id": rc_response.public_id,
            },
        )

        # First entry
        api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "First conclusion."},
                "expected_version": rc_response.version,
            },
            format="json",
        )
        rc_response.refresh_from_db()

        # Second entry without correction_reason
        resp = api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "Amended without reason."},
                "expected_version": rc_response.version,
            },
            format="json",
        )
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Stale version
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReviewerConclusionStaleVersion:
    def test_stale_expected_version_rejected(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_membership,
        doer_membership,
    ):
        ex, rc_response = _create_execution_submitted(tenant_a, tenant_definition, user_a, user_a)
        url = reverse(
            "iig_checklist:execution-reviewer-conclusion",
            kwargs={
                "public_id": ex.public_id,
                "response_public_id": rc_response.public_id,
            },
        )

        # Pass wrong expected_version
        resp = api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "Some conclusion."},
                "expected_version": rc_response.version + 99,
            },
            format="json",
        )
        assert resp.status_code in (400, 409, 422)


# ---------------------------------------------------------------------------
# Wrong execution state
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReviewerConclusionWrongState:
    def test_entry_not_allowed_on_draft_execution(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_membership,
        doer_membership,
    ):
        from iig_checklist.services import create_execution

        cv = _make_active_cv(tenant_definition, user_a)
        _make_reviewer_conclusion_question(cv, user_a)
        product = _make_product(tenant_a, user_a, code="PROD-DRAFT-RC")
        fv = _make_fv(product, user_a)

        ex = create_execution(
            tenant=tenant_a,
            checklist_version_public_id=str(cv.public_id),
            formulation_version_public_id=str(fv.public_id),
            actor=user_a,
        )
        rc_response = ex.responses.filter(question__answer_type="reviewer_conclusion").first()

        url = reverse(
            "iig_checklist:execution-reviewer-conclusion",
            kwargs={
                "public_id": ex.public_id,
                "response_public_id": rc_response.public_id,
            },
        )
        resp = api_client_reviewer.post(
            url,
            {
                "raw_value": {"value": "Conclusion on draft."},
                "expected_version": rc_response.version,
            },
            format="json",
        )
        assert resp.status_code in (400, 409, 422)
