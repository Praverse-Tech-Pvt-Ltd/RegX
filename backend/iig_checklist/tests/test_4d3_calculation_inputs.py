"""Milestone 4D-3 ORM Phase 2 -- governed calculation input resolution.

Real PostgreSQL-backed tests.  The resolver is never exercised through mocked
QuerySets or managers: every case builds actual persisted rows.

Synthetic immutable registry entries are installed with ``monkeypatch`` for one
test at a time to reach resolver forms the approved six-entry registry does not
declare (form A and form F).  ``get_entry()`` resolves the module global on each
call, so the substitution is observed consistently and the real registry is
restored automatically.  No committed registry definition is mutated.
"""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

import pytest

from iid_assessment import calculations as engine
from iig_checklist import calculation_registry as registry_mod
from iig_checklist.calculation_inputs import (
    REVIEW_REQUIRED_MARKER,
    SUBJECT_COMPONENT_PROVENANCE_KEY,
    CalculationInputContractError,
    ResolutionContext,
    resolve_calculation_inputs,
)
from iig_checklist.calculation_translation import ALLOWED_INPUT_FAILURE_CODES
from iig_checklist.enums import (
    AnswerType,
    CalculationStatus,
    Criticality,
    DataSourceClassification,
    ExecutionStatus,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Persisted content helpers
# ---------------------------------------------------------------------------


def _product(tenant, user, code="PROD-CI-01"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code=code,
        proposed_product_name="Synthetic Product",
        active_ingredient="Synthetic Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )


def _formulation(product, user, *, weight="1.000000", unit="gram", max_units=None):
    from formulations.models import FormulationVersion

    return FormulationVersion.objects.create(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight=Decimal(weight),
        total_dosage_unit_weight_unit=unit,
        maximum_dosage_units_per_day=max_units,
        created_by=user,
    )


def _component(formulation, *, quantity="0.250000", unit="gram", ctype="inactive", order=1):
    from formulations.models import FormulationComponent

    return FormulationComponent.objects.create(
        formulation_version=formulation,
        component_type=ctype,
        ingredient_name="Synthetic Excipient",
        quantity_per_dosage_unit=Decimal(quantity),
        quantity_unit=unit,
        display_order=order,
    )


def _regimen(formulation, *, maximum="4.0000", population=""):
    from formulations.models import DosingRegimen

    return DosingRegimen.objects.create(
        formulation_version=formulation,
        units_per_administration=Decimal("1.0000"),
        administrations_per_day=Decimal("4.0000"),
        maximum_units_per_day=Decimal(maximum),
        patient_population=population,
    )


def _active_version(definition, user, number=1):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=definition, version_number=number, status="active", created_by=user
    )


def _draft_version(definition, user, number):
    """A sibling version. Only one ACTIVE version may exist per definition, so
    isolation fixtures that merely need *another* version use a draft."""
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=definition, version_number=number, status="draft", created_by=user
    )


def _section(version, code="S1", order=1):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=version, code=code, title=f"Section {code}",
        display_order=order, criticality=Criticality.MEDIUM,
    )


def _question(
    section, code, *, answer_type, classification, binding="", order=1, allowed_units=None
):
    from iig_checklist.models import ChecklistQuestion

    return ChecklistQuestion.objects.create(
        section=section, code=code, question_text=f"Q {code}", display_order=order,
        answer_type=answer_type, data_source_classification=classification,
        calculation_binding_identifier=binding, criticality=Criticality.LOW,
        allowed_units=allowed_units or [],
    )


def _execution(tenant, version, formulation, user):
    from iig_checklist.models import ChecklistExecution

    return ChecklistExecution.objects.create(
        tenant=tenant, checklist_version=version, formulation_version=formulation,
        status=ExecutionStatus.DRAFT, created_by=user,
    )


def _response(execution, question, *, raw=None, na=False, reason=None):
    from iig_checklist.models import ChecklistResponse

    return ChecklistResponse.objects.create(
        execution=execution, question=question,
        data_source_type_snapshot=question.data_source_classification,
        raw_value=raw, is_not_applicable=na, not_applicable_reason=reason,
    )


def _outcome(
    response, *, name="calculate_daily_exposure", status=CalculationStatus.COMPLETE,
    value="0.750000", unit="gram", component_public_id=None,
):
    from iig_checklist.models import CalculationOutcome

    provenance = {}
    if component_public_id is not None:
        provenance[SUBJECT_COMPONENT_PROVENANCE_KEY] = str(component_public_id)
    return CalculationOutcome.objects.create(
        response=response, calculation_name=name, status=status,
        value=Decimal(value) if value is not None else None, unit=unit,
        input_provenance=provenance,
    )


def _snapshot(tenant, component, formulation, *, potency="1.000000", potency_unit="gram",
              mde="2.000000", mde_unit="gram", release=None):
    from iid_assessment.models import AssessmentSnapshot

    return AssessmentSnapshot.objects.create(
        tenant=tenant,
        formulation_component_public_id=component.public_id,
        formulation_version_public_id=formulation.public_id,
        iid_release_public_id=release,
        iid_potency_amount=Decimal(potency) if potency is not None else None,
        iid_potency_unit=potency_unit,
        iid_mde=Decimal(mde) if mde is not None else None,
        iid_mde_unit=mde_unit,
    )


# ---------------------------------------------------------------------------
# Synthetic registry seam
# ---------------------------------------------------------------------------


def _entry(**overrides):
    base = {
        "calculation_name": "calculate_percentage_w_w",
        "function": engine.calculate_percentage_w_w,
        "formula_version": engine.FORMULA_VERSION,
        "binding_version": "1.0.0",
        "input_resolvers": MappingProxyType({}),
        "calculation_dependencies": (),
        "recalculation_triggers": (),
        "required_units": MappingProxyType({}),
        "output_unit": "gram",
        "rounding_rule": "none (Decimal, unrounded)",
        "allowed_answer_type": AnswerType.CALCULATED_VALUE.value,
        "allowed_data_source": DataSourceClassification.SYSTEM_CALCULATED.value,
    }
    base.update(overrides)
    return registry_mod.RegistryEntry(**base)


def _install(monkeypatch, mapping):
    monkeypatch.setattr(
        registry_mod, "CALCULATION_BINDING_REGISTRY", MappingProxyType(dict(mapping))
    )


# ---------------------------------------------------------------------------
# A complete, resolvable percentage_w_w world
# ---------------------------------------------------------------------------


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a):
    """Persisted content that resolves ``percentage_w_w`` cleanly."""
    product = _product(tenant_a, user_a)
    formulation = _formulation(product, user_a, weight="1.000000", unit="gram")
    component = _component(formulation, quantity="0.250000", unit="gram")
    version = _active_version(tenant_definition, user_a)
    section = _section(version)
    target = _question(
        section, "Q_PCT_WW", answer_type=AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding="percentage_w_w", order=1,
    )
    selector = _question(
        section, registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED, order=2,
    )
    execution = _execution(tenant_a, version, formulation, user_a)
    selector_response = _response(
        execution, selector, raw={"public_id": str(component.public_id)}
    )
    return {
        "tenant": tenant_a, "user": user_a, "product": product,
        "formulation": formulation, "component": component, "version": version,
        "section": section, "target": target, "selector": selector,
        "execution": execution, "selector_response": selector_response,
    }


def _resolve(world, identifier="percentage_w_w", target=None, context=None):
    return resolve_calculation_inputs(
        execution=world["execution"],
        target_question=target or world["target"],
        registry_identifier=identifier,
        actor=world["user"],
        locked_context=context,
    )


def _codes(result):
    return set(result.failure_codes)


# ===========================================================================
# A. Service contract
# ===========================================================================


class TestServiceContract:
    def test_successful_resolution_produces_all_kwargs(self, world):
        result = _resolve(world)
        assert result.resolved, result.failure_codes
        assert set(result.kwargs) == {
            "quantity_per_unit_grams", "total_dosage_unit_weight_grams"
        }
        assert result.kwargs["quantity_per_unit_grams"] == Decimal("0.250000")
        assert result.kwargs["total_dosage_unit_weight_grams"] == Decimal("1.000000")
        assert result.calculation_name == "calculate_percentage_w_w"
        assert result.subject_component_public_id == str(world["component"].public_id)

    def test_unknown_registry_identifier_fails_closed(self, world):
        result = _resolve(world, identifier="not_a_registry_key")
        assert not result.resolved
        assert result.failure_codes == ("INPUT_RESOLVER_UNKNOWN",)
        assert dict(result.kwargs) == {}

    def test_no_partial_success(self, world):
        """One failed input empties the whole kwargs mapping."""
        world["selector_response"].raw_value = None
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert not result.resolved
        assert dict(result.kwargs) == {}
        # The version field still resolved, but is not offered as a kwarg.
        assert any(i.kwarg_name == "total_dosage_unit_weight_grams" for i in result.inputs)

    def test_target_question_from_another_version_is_a_contract_error(self, world, user_a):
        other_version = _draft_version(world["version"].definition, user_a, number=2)
        other_target = _question(
            _section(other_version, code="OTHER"), "Q_PCT_WW",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding="percentage_w_w",
        )
        with pytest.raises(CalculationInputContractError):
            _resolve(world, target=other_target)

    def test_non_calculated_target_is_a_contract_error(self, world):
        plain = _question(
            world["section"], "Q_PLAIN", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=50,
        )
        with pytest.raises(CalculationInputContractError):
            _resolve(world, target=plain)

    def test_target_answer_type_mismatch_is_a_contract_error(self, world):
        mismatched = _question(
            world["section"], "Q_WRONG_TYPE", answer_type=AnswerType.CALCULATED_STATUS,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding="percentage_w_w", order=60,
        )
        with pytest.raises(CalculationInputContractError):
            _resolve(world, target=mismatched)

    def test_every_failure_code_is_governed(self, world):
        world["selector_response"].raw_value = {"public_id": "not-a-uuid"}
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert not result.resolved
        assert set(result.failure_codes) <= ALLOWED_INPUT_FAILURE_CODES

    def test_resolution_performs_no_writes(self, world, django_assert_num_queries):
        from iig_checklist.models import CalculationOutcome, ChecklistResponse

        before_responses = ChecklistResponse.objects.count()
        before_outcomes = CalculationOutcome.objects.count()
        result = _resolve(world)
        assert result.resolved
        assert ChecklistResponse.objects.count() == before_responses
        assert CalculationOutcome.objects.count() == before_outcomes

    def test_repeated_resolution_is_byte_stable(self, world):
        runs = {
            tuple((i.kwarg_name, str(i.value)) for i in _resolve(world).inputs)
            for _ in range(5)
        }
        assert len(runs) == 1


# ===========================================================================
# B. Form A -- question_response
# ===========================================================================


def _form_a_registry(monkeypatch, *, expected_type="decimal", required_unit=None,
                     unit_source=None):
    declaration = {
        "source": registry_mod.SOURCE_QUESTION_RESPONSE,
        "question_code": "Q_INPUT_A",
        "value_field": "raw_value",
        "expected_type": expected_type,
    }
    if required_unit is not None:
        declaration["required_unit"] = required_unit
    if unit_source is not None:
        declaration["unit_source"] = unit_source
    _install(
        monkeypatch,
        {
            "form_a": _entry(
                input_resolvers=MappingProxyType({"x": MappingProxyType(declaration)}),
                recalculation_triggers=("Q_INPUT_A",),
            )
        },
    )


class TestFormAQuestionResponse:
    def test_valid_decimal_response(self, world, monkeypatch):
        _form_a_registry(monkeypatch)
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "12.5"})
        result = _resolve(world, identifier="form_a")
        assert result.resolved, result.failure_codes
        assert result.kwargs["x"] == Decimal("12.5")

    def test_missing_question(self, world, monkeypatch):
        _form_a_registry(monkeypatch)
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_RESPONSE_MISSING"}

    def test_missing_response_row(self, world, monkeypatch):
        _form_a_registry(monkeypatch)
        _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_RESPONSE_MISSING"}

    def test_duplicate_question_code_across_sections(self, world, monkeypatch):
        """Codes are unique per section, so one version may hold two."""
        _form_a_registry(monkeypatch)
        second = _section(world["version"], code="S2", order=2)
        for section in (world["section"], second):
            question = _question(
                section, "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
                classification=DataSourceClassification.USER_REQUIRED, order=10,
            )
            _response(world["execution"], question, raw={"value": "1.0"})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_VALUE_INVALID"}
        assert not result.resolved

    def test_not_applicable_response(self, world, monkeypatch):
        _form_a_registry(monkeypatch)
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, na=True, reason="Not required here")
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_RESPONSE_NOT_APPLICABLE"}

    def test_review_required_marker(self, world, monkeypatch):
        """M4D3-PST-002 -- the reserved marker blocks resolution."""
        _form_a_registry(monkeypatch)
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(
            world["execution"], question, raw={"value": "3.0"},
            reason=f"{REVIEW_REQUIRED_MARKER}route_unconfirmed",
        )
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_REVIEW_REQUIRED"}

    def test_malformed_payload(self, world, monkeypatch):
        _form_a_registry(monkeypatch)
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "not-a-number"})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_VALUE_INVALID"}

    def test_system_calculated_response_cannot_be_read_as_form_a(self, world, monkeypatch):
        """M4D3-INP-003 -- raw_value is permanently null for calculated rows."""
        _form_a_registry(monkeypatch)
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding="percentage_w_w", order=10,
        )
        _response(world["execution"], question)
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_RESOLVER_UNKNOWN"}

    def test_string_expected_type(self, world, monkeypatch):
        _form_a_registry(monkeypatch, expected_type="string")
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "oral"})
        result = _resolve(world, identifier="form_a")
        assert result.resolved, result.failure_codes
        assert result.kwargs["x"] == "oral"

    def test_blank_string_is_invalid(self, world, monkeypatch):
        _form_a_registry(monkeypatch, expected_type="string")
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "   "})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_VALUE_INVALID"}

    def test_unsupported_expected_type(self, world, monkeypatch):
        _form_a_registry(monkeypatch, expected_type="uuid")
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "oral"})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_RESOLVER_UNKNOWN"}

    def test_quantity_with_unit_is_converted(self, world, monkeypatch):
        _form_a_registry(monkeypatch, required_unit="gram")
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.QUANTITY_WITH_UNIT,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
            allowed_units=["milligram"],
        )
        _response(world["execution"], question, raw={"value": "500", "unit": "milligram"})
        result = _resolve(world, identifier="form_a")
        assert result.resolved, result.failure_codes
        assert result.kwargs["x"] == Decimal("0.5")

    def test_missing_source_unit_fails_closed(self, world, monkeypatch):
        """Carried forward from the activation review: absent unit != mismatch."""
        _form_a_registry(monkeypatch, required_unit="gram")
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "5"})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_UNIT_MISSING"}

    def test_unsupported_unit(self, world, monkeypatch):
        _form_a_registry(monkeypatch, required_unit="gram", unit_source="furlong")
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "5"})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_UNIT_UNSUPPORTED"}

    def test_dimension_mismatch(self, world, monkeypatch):
        _form_a_registry(monkeypatch, required_unit="gram", unit_source="millilitre")
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        _response(world["execution"], question, raw={"value": "5"})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) <= {"INPUT_UNIT_DIMENSION_MISMATCH", "INPUT_DENSITY_REQUIRED"}
        assert result.failure_codes


# ===========================================================================
# C. Form B -- formulation_field
# ===========================================================================


class TestFormBFormulationField:
    def test_valid_version_scalar(self, world):
        result = _resolve(world)
        version_input = next(
            i for i in result.inputs if i.kwarg_name == "total_dosage_unit_weight_grams"
        )
        assert version_input.value == Decimal("1.000000")
        assert version_input.source_public_uuid == str(world["formulation"].public_id)

    def test_missing_field_value(self, world, monkeypatch):
        _install(
            monkeypatch,
            {
                "needs_batch": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "x": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                                    "object": "formulation_version",
                                    "field": "batch_size",
                                    "expected_type": "decimal",
                                }
                            )
                        }
                    )
                )
            },
        )
        result = _resolve(world, identifier="needs_batch")
        assert _codes(result) == {"FORMULATION_FIELD_MISSING"}

    def test_disallowed_field_is_rejected(self, world, monkeypatch):
        _install(
            monkeypatch,
            {
                "bad_field": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "x": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                                    "object": "formulation_version",
                                    "field": "rationale",
                                    "expected_type": "string",
                                }
                            )
                        }
                    )
                )
            },
        )
        result = _resolve(world, identifier="bad_field")
        assert _codes(result) == {"INPUT_RESOLVER_UNKNOWN"}

    def test_disallowed_unit_field_is_rejected(self, world, monkeypatch):
        _install(
            monkeypatch,
            {
                "bad_unit_field": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "x": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                                    "object": "formulation_version",
                                    "field": "total_dosage_unit_weight",
                                    "unit_field": "dosing_basis",
                                    "required_unit": "gram",
                                    "expected_type": "decimal",
                                }
                            )
                        }
                    )
                )
            },
        )
        result = _resolve(world, identifier="bad_unit_field")
        assert _codes(result) == {"INPUT_RESOLVER_UNKNOWN"}

    def test_component_from_another_formulation_is_rejected(self, world, user_a):
        other_product = _product(world["tenant"], user_a, code="PROD-CI-02")
        other_formulation = _formulation(other_product, user_a)
        foreign = _component(other_formulation)
        world["selector_response"].raw_value = {"public_id": str(foreign.public_id)}
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert "FORMULATION_COMPONENT_WRONG_FORMULATION" in _codes(result)

    def test_component_from_another_tenant_is_rejected(self, world, tenant_b, user_a):
        """A component in another tenant can never satisfy the selector."""
        foreign_product = _product(tenant_b, user_a, code="PROD-CI-B")
        foreign_formulation = _formulation(foreign_product, user_a)
        foreign = _component(foreign_formulation)
        world["selector_response"].raw_value = {"public_id": str(foreign.public_id)}
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert _codes(result) & {
            "FORMULATION_COMPONENT_WRONG_FORMULATION",
            "FORMULATION_COMPONENT_TENANT_MISMATCH",
        }
        assert not result.resolved

    def test_wrong_component_type_is_rejected(self, world):
        world["component"].component_type = "active"
        world["component"].save(update_fields=["component_type", "updated_at"])
        result = _resolve(world)
        assert "FORMULATION_COMPONENT_TYPE_MISMATCH" in _codes(result)


# ===========================================================================
# D. Form C -- maximum_daily_units
# ===========================================================================


def _mdu_registry(monkeypatch):
    _install(
        monkeypatch,
        {
            "mdu": _entry(
                input_resolvers=MappingProxyType(
                    {
                        "x": MappingProxyType(
                            {
                                "source": registry_mod.SOURCE_MAXIMUM_DAILY_UNITS,
                                "resolver_version": "1.0",
                                "expected_type": "decimal",
                            }
                        )
                    }
                )
            )
        },
    )


class TestFormCMaximumDailyUnits:
    def test_no_candidates_fails_closed(self, world, monkeypatch):
        _mdu_registry(monkeypatch)
        result = _resolve(world, identifier="mdu")
        assert _codes(result) == {"FORMULATION_FIELD_MISSING"}

    def test_scalar_only(self, world, monkeypatch):
        _mdu_registry(monkeypatch)
        world["formulation"].maximum_dosage_units_per_day = Decimal("6.0000")
        world["formulation"].save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        result = _resolve(world, identifier="mdu")
        assert result.resolved
        assert result.kwargs["x"] == Decimal("6.0000")

    def test_regimen_only(self, world, monkeypatch):
        _mdu_registry(monkeypatch)
        _regimen(world["formulation"], maximum="8.0000")
        result = _resolve(world, identifier="mdu")
        assert result.resolved
        assert result.kwargs["x"] == Decimal("8.0000")

    def test_scalar_higher_wins(self, world, monkeypatch):
        _mdu_registry(monkeypatch)
        world["formulation"].maximum_dosage_units_per_day = Decimal("10.0000")
        world["formulation"].save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        _regimen(world["formulation"], maximum="4.0000")
        result = _resolve(world, identifier="mdu")
        assert result.kwargs["x"] == Decimal("10.0000")

    def test_regimen_higher_wins(self, world, monkeypatch):
        _mdu_registry(monkeypatch)
        world["formulation"].maximum_dosage_units_per_day = Decimal("4.0000")
        world["formulation"].save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        _regimen(world["formulation"], maximum="12.0000")
        result = _resolve(world, identifier="mdu")
        assert result.kwargs["x"] == Decimal("12.0000")

    def test_all_regimens_are_collected_never_first(self, world, monkeypatch):
        """The highest regimen wins regardless of insertion order."""
        _mdu_registry(monkeypatch)
        _regimen(world["formulation"], maximum="2.0000")
        _regimen(world["formulation"], maximum="9.0000")
        _regimen(world["formulation"], maximum="5.0000")
        result = _resolve(world, identifier="mdu")
        assert result.kwargs["x"] == Decimal("9.0000")

    def test_equal_candidates_record_agreement(self, world, monkeypatch):
        _mdu_registry(monkeypatch)
        world["formulation"].maximum_dosage_units_per_day = Decimal("4.0000")
        world["formulation"].save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        _regimen(world["formulation"], maximum="4.0000")
        result = _resolve(world, identifier="mdu")
        assert result.kwargs["x"] == Decimal("4.0000")
        selected = next(i for i in result.inputs if i.kwarg_name == "x")
        assert selected.provenance

    def test_patient_population_is_provenance_only(self, world, monkeypatch):
        _mdu_registry(monkeypatch)
        _regimen(world["formulation"], maximum="7.0000", population="paediatric")
        result = _resolve(world, identifier="mdu")
        assert result.kwargs["x"] == Decimal("7.0000")


# ===========================================================================
# E. Form D -- assessment_snapshot
# ===========================================================================


class TestFormDAssessmentSnapshot:
    def test_valid_exact_object(self, world):
        snapshot = _snapshot(world["tenant"], world["component"], world["formulation"])
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(assessment_snapshot=snapshot),
        )
        assert result.resolved, result.failure_codes
        assert result.assessment_snapshot_public_id == str(snapshot.public_id)
        assert result.kwargs["selected_iid_potency_amount"] == Decimal("1.000000")

    def test_absent_snapshot_fails_closed(self, world):
        result = _resolve(world, identifier="percentage_of_iid_potency")
        assert "ASSESSMENT_SNAPSHOT_MISSING" in _codes(result)

    def test_wrong_tenant_snapshot(self, world, tenant_b):
        snapshot = _snapshot(tenant_b, world["component"], world["formulation"])
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(assessment_snapshot=snapshot),
        )
        assert "ASSESSMENT_SNAPSHOT_TENANT_MISMATCH" in _codes(result)

    def test_wrong_component_snapshot(self, world):
        other = _component(world["formulation"], quantity="0.100000", order=2)
        snapshot = _snapshot(world["tenant"], other, world["formulation"])
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(assessment_snapshot=snapshot),
        )
        assert "ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH" in _codes(result)

    def test_missing_snapshot_field(self, world):
        snapshot = _snapshot(world["tenant"], world["component"], world["formulation"],
                             potency=None)
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(assessment_snapshot=snapshot),
        )
        assert "ASSESSMENT_FIELD_MISSING" in _codes(result)

    def test_missing_snapshot_unit_field(self, world):
        """A reference unit that is empty is missing data, not a mismatch."""
        snapshot = _snapshot(world["tenant"], world["component"], world["formulation"],
                             potency_unit="")
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(assessment_snapshot=snapshot),
        )
        assert "INPUT_UNIT_MISSING" in _codes(result)

    def test_snapshot_reference_unit_drives_conversion(self, world):
        """SnapshotUnitRef is resolved explicitly, not compared as a string."""
        snapshot = _snapshot(
            world["tenant"], world["component"], world["formulation"],
            potency="500.000000", potency_unit="milligram",
        )
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(assessment_snapshot=snapshot),
        )
        assert result.resolved, result.failure_codes
        # The component quantity is converted into the snapshot's own unit.
        assert result.kwargs["converted_proposed_quantity"] == Decimal("250")

    def test_wrong_release_snapshot(self, world):
        """The caller states the release it selected; the snapshot must match."""
        import uuid as uuid_module

        chosen_release = uuid_module.uuid4()
        snapshot = _snapshot(
            world["tenant"], world["component"], world["formulation"],
            release=uuid_module.uuid4(),
        )
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(
                assessment_snapshot=snapshot,
                expected_iid_release_public_id=chosen_release,
            ),
        )
        assert "ASSESSMENT_SNAPSHOT_RELEASE_MISMATCH" in _codes(result)

    def test_matching_release_snapshot(self, world):
        import uuid as uuid_module

        release = uuid_module.uuid4()
        snapshot = _snapshot(
            world["tenant"], world["component"], world["formulation"], release=release,
        )
        result = _resolve(
            world, identifier="percentage_of_iid_potency",
            context=ResolutionContext(
                assessment_snapshot=snapshot, expected_iid_release_public_id=release
            ),
        )
        assert result.resolved, result.failure_codes

    def test_service_never_looks_a_snapshot_up(self, world):
        """A persisted matching snapshot is ignored unless supplied explicitly."""
        _snapshot(world["tenant"], world["component"], world["formulation"])
        result = _resolve(world, identifier="percentage_of_iid_potency")
        assert "ASSESSMENT_SNAPSHOT_MISSING" in _codes(result)
        assert result.assessment_snapshot_public_id is None


# ===========================================================================
# F. Form E -- calculation_outcome
# ===========================================================================


@pytest.fixture
def mde_world(world):
    """Adds the upstream daily-exposure question and response."""
    upstream = _question(
        world["section"], registry_mod.Q_DAILY_EXPOSURE,
        answer_type=AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding="daily_exposure", order=20,
    )
    target = _question(
        world["section"], "Q_MDE_PCT", answer_type=AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding="percentage_of_iid_mde", order=21,
    )
    upstream_response = _response(world["execution"], upstream)
    world["upstream"] = upstream
    world["upstream_response"] = upstream_response
    world["mde_target"] = target
    return world


def _resolve_mde(world, context=None):
    return resolve_calculation_inputs(
        execution=world["execution"], target_question=world["mde_target"],
        registry_identifier="percentage_of_iid_mde", actor=world["user"],
        locked_context=context,
    )


class TestFormECalculationOutcome:
    def test_valid_complete_outcome(self, mde_world):
        _outcome(
            mde_world["upstream_response"],
            component_public_id=mde_world["component"].public_id,
        )
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert result.resolved, result.failure_codes
        assert result.kwargs["converted_proposed_daily_exposure"] == Decimal("0.750000")
        assert len(result.upstream_outcome_public_ids) == 1

    def test_missing_outcome(self, mde_world):
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert "UPSTREAM_CALCULATION_MISSING" in _codes(result)

    def test_duplicate_outcomes(self, mde_world):
        for _ in range(2):
            _outcome(
                mde_world["upstream_response"],
                component_public_id=mde_world["component"].public_id,
            )
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert "UPSTREAM_CALCULATION_DUPLICATE" in _codes(result)

    def test_incomplete_status(self, mde_world):
        _outcome(
            mde_world["upstream_response"], status=CalculationStatus.DATA_REQUIRED,
            component_public_id=mde_world["component"].public_id,
        )
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert "UPSTREAM_CALCULATION_INCOMPLETE" in _codes(result)

    def test_null_value(self, mde_world):
        _outcome(
            mde_world["upstream_response"], value=None,
            component_public_id=mde_world["component"].public_id,
        )
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert "UPSTREAM_CALCULATION_INCOMPLETE" in _codes(result)

    def test_outcome_without_recorded_component_is_rejected(self, mde_world):
        """A component-scoped producer must prove which component it described."""
        _outcome(mde_world["upstream_response"])
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert "UPSTREAM_CALCULATION_COMPONENT_MISMATCH" in _codes(result)

    def test_outcome_for_another_component_is_rejected(self, mde_world):
        other = _component(mde_world["formulation"], quantity="0.100000", order=3)
        _outcome(mde_world["upstream_response"], component_public_id=other.public_id)
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        # The MDE entry has no component input of its own; it inherits from the
        # upstream outcome, and the snapshot must then describe that component.
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert not result.resolved

    def test_outcome_from_another_execution_cannot_satisfy(self, mde_world, user_a):
        """An identical outcome in a sibling execution is invisible."""
        other_product = _product(mde_world["tenant"], user_a, code="PROD-CI-OTHEX")
        other_formulation = _formulation(other_product, user_a)
        other_execution = _execution(
            mde_world["tenant"], mde_world["version"], other_formulation, user_a
        )
        other_response = _response(other_execution, mde_world["upstream"])
        _outcome(other_response, component_public_id=mde_world["component"].public_id)
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert "UPSTREAM_CALCULATION_MISSING" in _codes(result)

    def test_incompatible_upstream_unit(self, mde_world):
        _outcome(
            mde_world["upstream_response"], unit="millilitre",
            component_public_id=mde_world["component"].public_id,
        )
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert _codes(result) & {
            "INPUT_UNIT_DIMENSION_MISMATCH", "INPUT_DENSITY_REQUIRED"
        }

    def test_upstream_unit_is_converted_to_the_snapshot_unit(self, mde_world):
        _outcome(
            mde_world["upstream_response"], value="1.000000", unit="gram",
            component_public_id=mde_world["component"].public_id,
        )
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"],
            mde="2000.000000", mde_unit="milligram",
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        assert result.resolved, result.failure_codes
        assert result.kwargs["converted_proposed_daily_exposure"] == Decimal("1000")

    def test_upstream_question_must_be_calculated(self, world, monkeypatch):
        _install(
            monkeypatch,
            {
                "consumes": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "x": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_CALCULATION_OUTCOME,
                                    "question_code": "Q_UPSTREAM",
                                    "field": "value",
                                    "required_status": "complete",
                                    "unit_source": "gram",
                                    "expected_type": "decimal",
                                }
                            )
                        }
                    ),
                    calculation_dependencies=("Q_UPSTREAM",),
                    recalculation_triggers=("Q_UPSTREAM",),
                )
            },
        )
        upstream = _question(
            world["section"], "Q_UPSTREAM", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=30,
        )
        _response(world["execution"], upstream, raw={"value": "1.0"})
        result = _resolve(world, identifier="consumes")
        assert "UPSTREAM_CALCULATION_MISSING" in _codes(result)

    def test_own_component_disagreeing_with_upstream_is_rejected(self, world, monkeypatch):
        """A component-scoped consumer must not read another component's result."""
        _install(
            monkeypatch,
            {
                "daily_exposure": registry_mod.CALCULATION_BINDING_REGISTRY[
                    "daily_exposure"
                ],
                "scoped_consumer": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "a_quantity": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                                    "object": "formulation_component",
                                    "field": "quantity_per_dosage_unit",
                                    "unit_field": "quantity_unit",
                                    "required_unit": "gram",
                                    "expected_type": "decimal",
                                    "component_selector": MappingProxyType(
                                        {
                                            "type": registry_mod.SELECTOR_RESPONSE_REFERENCE,
                                            "question_code": (
                                                registry_mod.Q_SUBJECT_COMPONENT
                                            ),
                                        }
                                    ),
                                    "required_component_type": "inactive",
                                }
                            ),
                            "b_upstream": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_CALCULATION_OUTCOME,
                                    "question_code": registry_mod.Q_DAILY_EXPOSURE,
                                    "field": "value",
                                    "required_status": "complete",
                                    "unit_source": "gram",
                                    "expected_type": "decimal",
                                }
                            ),
                        }
                    ),
                    calculation_dependencies=(registry_mod.Q_DAILY_EXPOSURE,),
                    recalculation_triggers=(
                        registry_mod.Q_SUBJECT_COMPONENT,
                        registry_mod.Q_DAILY_EXPOSURE,
                    ),
                ),
            },
        )
        upstream = _question(
            world["section"], registry_mod.Q_DAILY_EXPOSURE,
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding="daily_exposure", order=40,
        )
        upstream_response = _response(world["execution"], upstream)
        other = _component(world["formulation"], quantity="0.100000", order=7)
        _outcome(upstream_response, component_public_id=other.public_id)
        target = _question(
            world["section"], "Q_SCOPED", answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding="scoped_consumer", order=41,
        )
        result = _resolve(world, identifier="scoped_consumer", target=target)
        assert "UPSTREAM_CALCULATION_COMPONENT_MISMATCH" in _codes(result)

    def test_provenance_records_upstream_public_ids(self, mde_world):
        outcome = _outcome(
            mde_world["upstream_response"],
            component_public_id=mde_world["component"].public_id,
        )
        snapshot = _snapshot(
            mde_world["tenant"], mde_world["component"], mde_world["formulation"]
        )
        result = _resolve_mde(mde_world, ResolutionContext(assessment_snapshot=snapshot))
        resolved = next(
            i for i in result.inputs if i.kwarg_name == "converted_proposed_daily_exposure"
        )
        assert resolved.provenance["upstream_outcome_public_id"] == str(outcome.public_id)
        assert resolved.provenance["upstream_response_public_id"] == str(
            mde_world["upstream_response"].public_id
        )


# ===========================================================================
# G. Form F -- constant
# ===========================================================================


def _constant_registry(monkeypatch, *, value, declared_type="decimal"):
    _install(
        monkeypatch,
        {
            "konst": _entry(
                input_resolvers=MappingProxyType(
                    {
                        "x": MappingProxyType(
                            {
                                "source": registry_mod.SOURCE_CONSTANT,
                                "value": value,
                                "type": declared_type,
                                "binding_version": "1.0.0",
                            }
                        )
                    }
                )
            )
        },
    )


class TestFormFConstant:
    def test_valid_decimal_constant(self, world, monkeypatch):
        _constant_registry(monkeypatch, value="2.5")
        result = _resolve(world, identifier="konst")
        assert result.resolved
        assert result.kwargs["x"] == Decimal("2.5")

    def test_valid_string_constant(self, world, monkeypatch):
        _constant_registry(monkeypatch, value="oral", declared_type="string")
        result = _resolve(world, identifier="konst")
        assert result.kwargs["x"] == "oral"

    def test_wrong_type_constant(self, world, monkeypatch):
        _constant_registry(monkeypatch, value="not-a-number")
        result = _resolve(world, identifier="konst")
        assert _codes(result) == {"INPUT_VALUE_INVALID"}

    def test_mutable_constant_is_rejected(self, world, monkeypatch):
        _constant_registry(monkeypatch, value=["1", "2"])
        result = _resolve(world, identifier="konst")
        assert _codes(result) == {"INPUT_VALUE_INVALID"}

    def test_callable_constant_is_rejected(self, world, monkeypatch):
        _constant_registry(monkeypatch, value=lambda: Decimal("1"))
        result = _resolve(world, identifier="konst")
        assert _codes(result) == {"INPUT_VALUE_INVALID"}

    def test_decimal_instance_constant(self, world, monkeypatch):
        _constant_registry(monkeypatch, value=Decimal("3.25"))
        result = _resolve(world, identifier="konst")
        assert result.kwargs["x"] == Decimal("3.25")

    def test_non_string_constant_declared_as_string(self, world, monkeypatch):
        _constant_registry(monkeypatch, value=7, declared_type="string")
        result = _resolve(world, identifier="konst")
        assert _codes(result) == {"INPUT_VALUE_INVALID"}

    def test_constant_provenance_carries_no_internal_id(self, world, monkeypatch):
        _constant_registry(monkeypatch, value="2.5")
        result = _resolve(world, identifier="konst")
        resolved = next(i for i in result.inputs if i.kwarg_name == "x")
        assert resolved.provenance["binding_version"] == "1.0.0"
        assert resolved.source_public_uuid is None


# ===========================================================================
# H. Subject component selector
# ===========================================================================


class TestSubjectComponent:
    def test_selector_response_missing(self, world):
        world["selector_response"].delete()
        result = _resolve(world)
        assert "INPUT_RESPONSE_MISSING" in _codes(result)

    def test_selector_not_applicable(self, world):
        world["selector_response"].raw_value = None
        world["selector_response"].is_not_applicable = True
        world["selector_response"].not_applicable_reason = "Not required"
        world["selector_response"].save()
        result = _resolve(world)
        assert "INPUT_RESPONSE_NOT_APPLICABLE" in _codes(result)

    def test_selector_review_required(self, world):
        world["selector_response"].not_applicable_reason = (
            f"{REVIEW_REQUIRED_MARKER}component_unconfirmed"
        )
        world["selector_response"].save(update_fields=["not_applicable_reason", "updated_at"])
        result = _resolve(world)
        assert "INPUT_REVIEW_REQUIRED" in _codes(result)

    def test_selector_payload_must_be_exact(self, world):
        world["selector_response"].raw_value = {
            "public_id": str(world["component"].public_id), "extra": "x"
        }
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert "FORMULATION_COMPONENT_REFERENCE_INVALID" in _codes(result)

    def test_selector_referencing_nothing(self, world):
        import uuid as uuid_module

        world["selector_response"].raw_value = {"public_id": str(uuid_module.uuid4())}
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert "FORMULATION_COMPONENT_MISSING" in _codes(result)

    def test_component_read_without_a_selector_is_rejected(self, world, monkeypatch):
        _install(
            monkeypatch,
            {
                "no_selector": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "x": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                                    "object": "formulation_component",
                                    "field": "quantity_per_dosage_unit",
                                    "expected_type": "decimal",
                                }
                            )
                        }
                    )
                )
            },
        )
        result = _resolve(world, identifier="no_selector")
        assert _codes(result) == {"FORMULATION_COMPONENT_MISSING"}

    def test_disabled_selector_form_is_rejected_at_runtime(self, world, monkeypatch):
        """M4D3-FCR-012 -- registry_component_code stays disabled at runtime too."""
        _install(
            monkeypatch,
            {
                "disabled": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "x": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                                    "object": "formulation_component",
                                    "field": "quantity_per_dosage_unit",
                                    "expected_type": "decimal",
                                    "component_selector": MappingProxyType(
                                        {
                                            "type": (
                                                registry_mod.SELECTOR_REGISTRY_COMPONENT_CODE
                                            ),
                                            "question_code": "Q_ANY",
                                        }
                                    ),
                                }
                            )
                        }
                    )
                )
            },
        )
        result = _resolve(world, identifier="disabled")
        assert "INPUT_RESOLVER_UNKNOWN" in _codes(result)

    def test_no_ingredient_name_fallback(self, world):
        """A same-named component is never matched by name."""
        twin = _component(world["formulation"], quantity="0.900000", order=9)
        assert twin.ingredient_name == world["component"].ingredient_name
        world["selector_response"].raw_value = {"public_id": str(twin.public_id)}
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert result.resolved, result.failure_codes
        assert result.subject_component_public_id == str(twin.public_id)
        assert result.kwargs["quantity_per_unit_grams"] == Decimal("0.900000")


# ===========================================================================
# I. Isolation and sanitization
# ===========================================================================


class TestIsolationAndSanitization:
    def test_another_executions_response_cannot_satisfy(self, world, user_a, monkeypatch):
        _form_a_registry(monkeypatch)
        question = _question(
            world["section"], "Q_INPUT_A", answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED, order=10,
        )
        sibling_product = _product(world["tenant"], user_a, code="PROD-CI-SIB")
        sibling_formulation = _formulation(sibling_product, user_a)
        sibling = _execution(
            world["tenant"], world["version"], sibling_formulation, user_a
        )
        _response(sibling, question, raw={"value": "42"})
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_RESPONSE_MISSING"}

    def test_another_versions_question_cannot_satisfy(self, world, user_a, monkeypatch):
        _form_a_registry(monkeypatch)
        other_version = _draft_version(world["version"].definition, user_a, number=3)
        other_question = _question(
            _section(other_version, code="OV"), "Q_INPUT_A",
            answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED,
        )
        assert other_question.code == "Q_INPUT_A"
        result = _resolve(world, identifier="form_a")
        assert _codes(result) == {"INPUT_RESPONSE_MISSING"}

    def test_execution_formulation_must_belong_to_the_tenant(self, world, tenant_b, user_a):
        """A cross-tenant formulation is a security fault, never missing data.

        Created through ``objects.create()`` so the row exists exactly as a
        corrupted or maliciously constructed record would.
        """
        foreign_product = _product(tenant_b, user_a, code="PROD-CI-XT")
        foreign_formulation = _formulation(foreign_product, user_a)
        world["execution"].formulation_version = foreign_formulation
        world["execution"].save(update_fields=["formulation_version", "updated_at"])
        result = _resolve(world)
        assert "INPUT_TENANT_MISMATCH" in _codes(result)
        assert "INPUT_RESPONSE_MISSING" not in _codes(result)

    def test_failures_expose_no_internal_ids(self, world):
        world["selector_response"].raw_value = {"public_id": "not-a-uuid"}
        world["selector_response"].save(update_fields=["raw_value", "updated_at"])
        result = _resolve(world)
        assert result.failures
        for failure in result.failures:
            text = failure.message.lower()
            assert "traceback" not in text
            assert "select " not in text
            assert "object at" not in text
            if failure.source_public_uuid is not None:
                assert "-" in failure.source_public_uuid

    def test_failure_ordering_is_stable(self, world, monkeypatch):
        _install(
            monkeypatch,
            {
                "many_failures": _entry(
                    input_resolvers=MappingProxyType(
                        {
                            "a": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                                    "object": "formulation_version",
                                    "field": "batch_size",
                                    "expected_type": "decimal",
                                }
                            ),
                            "b": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_CONSTANT,
                                    "value": ["mutable"],
                                    "type": "decimal",
                                    "binding_version": "1.0.0",
                                }
                            ),
                            "c": MappingProxyType(
                                {
                                    "source": registry_mod.SOURCE_ASSESSMENT_SNAPSHOT,
                                    "field": "iid_mde",
                                    "expected_type": "decimal",
                                }
                            ),
                        }
                    )
                )
            },
        )
        runs = {
            tuple(f.semantic_key for f in _resolve(world, identifier="many_failures").failures)
            for _ in range(5)
        }
        assert len(runs) == 1
        keys = next(iter(runs))
        assert list(keys) == sorted(keys)
        assert len(keys) == 3

    def test_provenance_contains_only_public_identifiers(self, world):
        result = _resolve(world)
        assert result.resolved
        for resolved in result.inputs:
            for key, value in resolved.provenance.items():
                assert "pk" != key
                assert not key.endswith("_id") or key.endswith("_public_id")
                if isinstance(value, str) and value:
                    assert "object at" not in value
