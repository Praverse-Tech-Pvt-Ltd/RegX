"""Model/constraint tests for Milestone 4D-2 execution models."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from iig_checklist.enums import CalculationStatus, ExecutionStatus
from iig_checklist.models import (
    CalculationOutcome,
    ChecklistExecution,
    ChecklistResponse,
    ChecklistResponseHistory,
    GovernedHistoryMutationForbidden,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(tenant, user):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code="PROD-TEST-01",
        proposed_product_name="Test Product",
        active_ingredient="Synthetic Test Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )


def _make_formulation_version(product, user, status="approved"):
    from formulations.models import FormulationVersion

    fv = FormulationVersion(
        product=product,
        version_number=1,
        status=status,
        total_dosage_unit_weight="100.000000",
        total_dosage_unit_weight_unit="mg",
        created_by=user,
    )
    fv.save()
    return fv


def _make_active_checklist_version(tenant_definition, user):
    from iig_checklist.models import ChecklistVersion

    cv = ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=1,
        status="active",
        created_by=user,
    )
    return cv


def _make_execution(tenant, checklist_version, formulation_version, user):
    execution = ChecklistExecution(
        tenant=tenant,
        checklist_version=checklist_version,
        formulation_version=formulation_version,
        status=ExecutionStatus.DRAFT,
        created_by=user,
    )
    execution.full_clean()
    execution.save()
    return execution


def _make_yes_no_question(draft_version, user):
    from iig_checklist.models import ChecklistQuestion, ChecklistSection

    section = ChecklistSection.objects.create(
        checklist_version=draft_version,
        code="SEC-1",
        title="Section 1",
        display_order=1,
        criticality="low",
    )
    return ChecklistQuestion.objects.create(
        section=section,
        code="Q-YN-1",
        question_text="Yes/No question?",
        display_order=1,
        answer_type="yes_no",
        data_source_classification="user_required",
        criticality="low",
    )


# ---------------------------------------------------------------------------
# ChecklistExecution constraints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChecklistExecutionUniqueConstraint:
    def test_unique_active_execution_rejected(self, tenant_a, tenant_definition, user_a):
        """Two active executions for same (tenant, cv, fv) must fail."""
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)

        _make_execution(tenant_a, cv, fv, user_a)

        with pytest.raises((IntegrityError, ValidationError)):
            with transaction.atomic():
                _make_execution(tenant_a, cv, fv, user_a)

    def test_second_execution_allowed_after_rejected(self, tenant_a, tenant_definition, user_a):
        """A rejected execution unlocks the unique constraint so a new one can be created."""
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)

        e1 = _make_execution(tenant_a, cv, fv, user_a)
        e1.status = "rejected"
        e1.save()

        e2 = _make_execution(tenant_a, cv, fv, user_a)
        assert e2.pk != e1.pk

    def test_second_execution_allowed_after_cancelled(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)

        e1 = _make_execution(tenant_a, cv, fv, user_a)
        e1.status = "cancelled"
        e1.save()

        e2 = _make_execution(tenant_a, cv, fv, user_a)
        assert e2.pk != e1.pk

    def test_second_execution_allowed_after_superseded(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)

        e1 = _make_execution(tenant_a, cv, fv, user_a)
        e1.status = "superseded"
        e1.save()

        e2 = _make_execution(tenant_a, cv, fv, user_a)
        assert e2.pk != e1.pk


@pytest.mark.django_db
class TestChecklistExecutionVisibleTo:
    def test_visible_to_filters_by_tenant(self, tenant_a, tenant_b, tenant_definition, user_a):
        product_a = _make_product(tenant_a, user_a)
        fv_a = _make_formulation_version(product_a, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        _make_execution(tenant_a, cv, fv_a, user_a)

        assert ChecklistExecution.objects.visible_to(tenant_a).count() == 1
        assert ChecklistExecution.objects.visible_to(tenant_b).count() == 0


# ---------------------------------------------------------------------------
# ChecklistResponse.clean()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChecklistResponseClean:
    def _setup(self, tenant, tenant_definition, user):
        product = _make_product(tenant, user)
        fv = _make_formulation_version(product, user)
        cv = _make_active_checklist_version(tenant_definition, user)
        question = _make_yes_no_question(
            ChecklistExecution.objects.model._meta.get_field("checklist_version")
            .related_model.objects.get(pk=cv.pk)
            .sections.first()
            .checklist_version
            if False
            else cv,
            user,
        )
        execution = _make_execution(tenant, cv, fv, user)
        return execution, question

    def test_not_applicable_requires_reason(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)

        response = ChecklistResponse(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
            is_not_applicable=True,
            not_applicable_reason="",
        )
        with pytest.raises(ValidationError, match="not_applicable_requires_reason"):
            response.full_clean()

    def test_not_applicable_with_raw_value_rejected(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)

        response = ChecklistResponse(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
            is_not_applicable=True,
            not_applicable_reason="reason",
            raw_value={"value": True},
        )
        with pytest.raises(ValidationError):
            response.full_clean()

    def test_payload_too_large_rejected(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)

        oversized = {"value": "x" * 20_000}
        response = ChecklistResponse(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
            raw_value=oversized,
        )
        with pytest.raises(ValidationError, match="payload_too_large"):
            response.full_clean()

    def test_immutability_when_execution_not_mutable(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)

        response = ChecklistResponse.objects.create(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
        )

        execution.status = "submitted_for_review"
        execution.save()

        response.raw_value = {"value": True}
        with pytest.raises(ValidationError, match="response_immutable"):
            response.full_clean()


# ---------------------------------------------------------------------------
# ChecklistResponseHistory immutability
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChecklistResponseHistoryImmutability:
    def test_history_save_on_existing_row_raises(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)

        response = ChecklistResponse.objects.create(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
        )

        history = ChecklistResponseHistory(
            response=response,
            prior_raw_value=None,
            new_raw_value={"value": True},
            prior_is_not_applicable=False,
            new_is_not_applicable=False,
            prior_not_applicable_reason=None,
            new_not_applicable_reason=None,
            prior_entered_by=None,
            prior_entered_at=None,
            prior_version=1,
            new_version=2,
            correction_reason="test",
            amended_by=user_a,
            source_classification_snapshot="user_required",
        )
        history.save()  # First save is legal (new row)

        with pytest.raises(GovernedHistoryMutationForbidden):
            history.save()

    def test_history_delete_raises(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)
        response = ChecklistResponse.objects.create(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
        )
        history = ChecklistResponseHistory(
            response=response,
            prior_raw_value=None,
            new_raw_value={"value": True},
            prior_is_not_applicable=False,
            new_is_not_applicable=False,
            prior_not_applicable_reason=None,
            new_not_applicable_reason=None,
            prior_entered_by=None,
            prior_entered_at=None,
            prior_version=1,
            new_version=2,
            correction_reason="test",
            amended_by=user_a,
            source_classification_snapshot="user_required",
        )
        history.save()
        with pytest.raises(GovernedHistoryMutationForbidden):
            history.delete()

    def test_queryset_update_raises(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)
        response = ChecklistResponse.objects.create(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
        )
        ChecklistResponseHistory(
            response=response,
            prior_raw_value=None,
            new_raw_value={"value": True},
            prior_is_not_applicable=False,
            new_is_not_applicable=False,
            prior_not_applicable_reason=None,
            new_not_applicable_reason=None,
            prior_entered_by=None,
            prior_entered_at=None,
            prior_version=1,
            new_version=2,
            correction_reason="test",
            amended_by=user_a,
            source_classification_snapshot="user_required",
        ).save()

        with pytest.raises(GovernedHistoryMutationForbidden):
            ChecklistResponseHistory.objects.all().update(correction_reason="bad")

    def test_queryset_delete_raises(self, tenant_a, tenant_definition, user_a):
        with pytest.raises(GovernedHistoryMutationForbidden):
            ChecklistResponseHistory.objects.all().delete()


# ---------------------------------------------------------------------------
# CalculationOutcome.clean()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCalculationOutcomeClean:
    def test_invalid_calculation_name_rejected(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)
        response = ChecklistResponse.objects.create(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
        )
        outcome = CalculationOutcome(
            response=response,
            calculation_name="invalid_name",
            status=CalculationStatus.DATA_REQUIRED,
            inputs={"placeholder": True},
            input_provenance={"placeholder": "pre_calculation"},
        )
        with pytest.raises(ValidationError):
            outcome.full_clean()

    def test_valid_calculation_name_accepted(self, tenant_a, tenant_definition, user_a):
        product = _make_product(tenant_a, user_a)
        fv = _make_formulation_version(product, user_a)
        cv = _make_active_checklist_version(tenant_definition, user_a)
        q = _make_yes_no_question(cv, user_a)
        execution = _make_execution(tenant_a, cv, fv, user_a)
        response = ChecklistResponse.objects.create(
            execution=execution,
            question=q,
            data_source_type_snapshot="user_required",
        )
        # inputs and input_provenance require non-empty dicts (JSONField
        # blank=False treats {} as empty via Django's EMPTY_VALUES).
        outcome = CalculationOutcome(
            response=response,
            calculation_name="calculate_percentage_w_w",
            status=CalculationStatus.DATA_REQUIRED,
            inputs={"placeholder": True},
            input_provenance={"placeholder": "pre_calculation"},
        )
        outcome.full_clean()  # must not raise
        outcome.save()
        assert outcome.pk is not None
        assert outcome.status == CalculationStatus.DATA_REQUIRED
