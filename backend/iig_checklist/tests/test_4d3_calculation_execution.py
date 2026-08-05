"""Milestone 4D-3 ORM Phase 3 -- governed calculation execution.

Real PostgreSQL-backed tests driving the whole governed path: persisted
checklist content, the real ORM resolver, one approved registry function, the
approved translators, and the single placeholder row updated in place.

Fixture values are scientifically meaningful -- a 250 mg excipient in a 1 g
tablet taken four times a day, against an FDA precedent of 1 g potency and 2 g
maximum daily exposure -- so every expected Decimal is checkable by hand.

The engine's difference convention is **reference minus proposed**: a positive
difference means the proposal sits below the precedent.
"""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

import pytest

from iid_assessment import calculations as engine
from iig_checklist import calculation_registry as registry_mod
from iig_checklist.calculation_execution import (
    BindingNotApproved,
    CalculationEngineFailure,
    PlaceholderAmbiguous,
    PlaceholderMissing,
    ResponseNotInExecution,
    StaleResponseVersion,
    TargetNotCalculated,
    execute_calculation_response,
)
from iig_checklist.calculation_inputs import ResolutionContext
from iig_checklist.calculation_translation import (
    REGISTRY_BINDING_VERSION_PROVENANCE_KEY as BINDING_VERSION_KEY,
)
from iig_checklist.calculation_translation import (
    SUBJECT_COMPONENT_PROVENANCE_KEY as COMPONENT_KEY,
)
from iig_checklist.enums import (
    AnswerType,
    CalculationStatus,
    Criticality,
    DataSourceClassification,
    ExecutionStatus,
)

pytestmark = pytest.mark.django_db

CALCULATED_EVENT = "iig_checklist.response.calculated"


# ---------------------------------------------------------------------------
# Persisted content
# ---------------------------------------------------------------------------


def _product(tenant, user, code="PROD-EX-01"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant, product_code=code, proposed_product_name="Synthetic Product",
        active_ingredient="Synthetic Ingredient", dosage_form="tablet", route="oral",
        created_by=user,
    )


def _formulation(product, user, *, weight="1.000000", max_units=None):
    from formulations.models import FormulationVersion

    return FormulationVersion.objects.create(
        product=product, version_number=1, status="approved",
        total_dosage_unit_weight=Decimal(weight),
        total_dosage_unit_weight_unit="gram",
        maximum_dosage_units_per_day=max_units, created_by=user,
    )


def _component(formulation, *, quantity="0.250000", order=1, ctype="inactive"):
    from formulations.models import FormulationComponent

    return FormulationComponent.objects.create(
        formulation_version=formulation, component_type=ctype,
        ingredient_name="Synthetic Excipient",
        quantity_per_dosage_unit=Decimal(quantity), quantity_unit="gram",
        display_order=order,
    )


def _section(version, code="S1", order=1):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=version, code=code, title=f"Section {code}",
        display_order=order, criticality=Criticality.MEDIUM,
    )


def _question(section, code, *, answer_type, classification, binding="", order=1):
    from iig_checklist.models import ChecklistQuestion

    return ChecklistQuestion.objects.create(
        section=section, code=code, question_text=f"Q {code}", display_order=order,
        answer_type=answer_type, data_source_classification=classification,
        calculation_binding_identifier=binding, criticality=Criticality.LOW,
    )


def _calculated(section, code, identifier, *, order=1):
    return _question(
        section, code, answer_type=AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding=identifier, order=order,
    )


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


def _percentage_w_w_with(function):
    """The approved percentage_w_w entry with its function swapped.

    Keeps the real resolver declarations so input resolution is unchanged and
    only the engine call under test differs.
    """
    approved = registry_mod.CALCULATION_BINDING_REGISTRY["percentage_w_w"]
    return _entry(
        input_resolvers=approved.input_resolvers,
        recalculation_triggers=approved.recalculation_triggers,
        required_units=approved.required_units,
        output_unit=approved.output_unit,
        function=function,
    )


def _install(monkeypatch, mapping):
    monkeypatch.setattr(
        registry_mod, "CALCULATION_BINDING_REGISTRY", MappingProxyType(dict(mapping))
    )


def _install_percentage_w_w(monkeypatch, function):
    _install(
        monkeypatch,
        {
            **dict(registry_mod.CALCULATION_BINDING_REGISTRY),
            "percentage_w_w": _percentage_w_w_with(function),
        },
    )


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    """An execution whose placeholders exist, created by the governed service."""
    from iig_checklist.models import (
        CalculationOutcome,
        ChecklistResponse,
        ChecklistVersion,
    )
    from iig_checklist.services import create_execution

    product = _product(tenant_a, user_a)
    formulation = _formulation(product, user_a, max_units="4.0000")
    component = _component(formulation)
    version = ChecklistVersion.objects.create(
        definition=tenant_definition, version_number=1, status="active",
        created_by=user_a,
    )
    section = _section(version)
    selector_q = _question(
        section, registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED, order=1,
    )
    questions = {
        "percentage_w_w": _calculated(section, "Q_PCT_WW", "percentage_w_w", order=2),
        "daily_exposure": _calculated(
            section, registry_mod.Q_DAILY_EXPOSURE, "daily_exposure", order=3
        ),
        "percentage_of_iid_potency": _calculated(
            section, "Q_PCT_POT", "percentage_of_iid_potency", order=4
        ),
        "difference_from_iid_potency": _calculated(
            section, "Q_DIF_POT", "difference_from_iid_potency", order=5
        ),
        "percentage_of_iid_mde": _calculated(
            section, "Q_PCT_MDE", "percentage_of_iid_mde", order=6
        ),
        "difference_from_iid_mde": _calculated(
            section, "Q_DIF_MDE", "difference_from_iid_mde", order=7
        ),
    }
    execution = create_execution(
        tenant=tenant_a,
        checklist_version_public_id=str(version.public_id),
        formulation_version_public_id=str(formulation.public_id),
        actor=user_a,
    )
    selector_response = ChecklistResponse.objects.get(
        execution=execution, question=selector_q
    )
    selector_response.raw_value = {"public_id": str(component.public_id)}
    selector_response.save(update_fields=["raw_value", "updated_at"])

    responses = {
        key: ChecklistResponse.objects.get(execution=execution, question=q)
        for key, q in questions.items()
    }
    return {
        "tenant": tenant_a, "user": user_a, "formulation": formulation,
        "component": component, "version": version, "section": section,
        "execution": execution, "questions": questions, "responses": responses,
        "selector_response": selector_response,
        "outcomes": {
            key: CalculationOutcome.objects.get(response=r)
            for key, r in responses.items()
        },
    }


def _snapshot(world, *, potency="1.000000", mde="2.000000", component=None,
              release=None):
    from iid_assessment.models import AssessmentSnapshot

    return AssessmentSnapshot.objects.create(
        tenant=world["tenant"],
        formulation_component_public_id=(component or world["component"]).public_id,
        formulation_version_public_id=world["formulation"].public_id,
        iid_release_public_id=release,
        iid_potency_amount=Decimal(potency), iid_potency_unit="gram",
        iid_mde=Decimal(mde), iid_mde_unit="gram",
    )


def _run(world, key, *, snapshot=None, expected_version=None, actor=None):
    response = world["responses"][key]
    return execute_calculation_response(
        tenant=world["tenant"],
        execution=world["execution"],
        response=response,
        actor=actor or world["user"],
        expected_version=(
            response.version if expected_version is None else expected_version
        ),
        snapshot_context=(
            ResolutionContext(assessment_snapshot=snapshot)
            if snapshot is not None
            else None
        ),
    )


def _complete_daily_exposure(world):
    """Execute the upstream daily-exposure calculation the MDE entries need."""
    result = _run(world, "daily_exposure")
    assert result.status == CalculationStatus.COMPLETE, result.reason_code
    return result


# ===========================================================================
# A. All six approved calculations
# ===========================================================================


class TestApprovedCalculations:
    def test_percentage_w_w(self, world):
        """0.25 g excipient in a 1 g tablet = 25 % w/w."""
        result = _run(world, "percentage_w_w")
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        assert result.value == Decimal("25")
        assert result.unit == "percent_w_w"

        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.calculation_name == "calculate_percentage_w_w"
        assert outcome.formula_version == engine.FORMULA_VERSION
        assert outcome.value == Decimal("25")
        assert outcome.generated_at is not None
        outcome.full_clean()

    def test_daily_exposure(self, world):
        """0.25 g per unit x 4 units/day = 1 g/day."""
        result = _run(world, "daily_exposure")
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        assert result.value == Decimal("1")
        outcome = world["outcomes"]["daily_exposure"]
        outcome.refresh_from_db()
        assert outcome.value == Decimal("1")
        outcome.full_clean()

    def test_percentage_of_iid_potency(self, world):
        """0.25 g against a 1 g IID potency = 25 %."""
        result = _run(world, "percentage_of_iid_potency", snapshot=_snapshot(world))
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        assert result.value == Decimal("25")
        assert result.unit == "percent_of_potency"

    def test_difference_from_iid_potency(self, world):
        """1 g IID potency minus a 0.25 g proposal = 0.75 g of headroom.

        The engine's convention is reference minus proposed, so a positive
        result means the proposal sits below the precedent.
        """
        result = _run(world, "difference_from_iid_potency", snapshot=_snapshot(world))
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        assert result.value == Decimal("0.75")

    def test_percentage_of_iid_mde(self, world):
        """1 g/day against a 2 g IID MDE = 50 %."""
        _complete_daily_exposure(world)
        result = _run(world, "percentage_of_iid_mde", snapshot=_snapshot(world))
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        assert result.value == Decimal("50")
        assert result.unit == "percent_of_mde"

    def test_difference_from_iid_mde(self, world):
        """2 g IID MDE minus a 1 g/day exposure = 1 g/day of headroom."""
        _complete_daily_exposure(world)
        result = _run(world, "difference_from_iid_mde", snapshot=_snapshot(world))
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        assert result.value == Decimal("1")

    def test_exactly_one_function_invocation(self, world, monkeypatch):
        calls = []
        real = engine.calculate_percentage_w_w

        def _counting(**kwargs):
            calls.append(kwargs)
            return real(**kwargs)

        _install_percentage_w_w(monkeypatch, _counting)
        _run(world, "percentage_w_w")
        assert len(calls) == 1
        assert set(calls[0]) == {
            "quantity_per_unit_grams", "total_dosage_unit_weight_grams"
        }


# ===========================================================================
# B. Outcome persistence and provenance
# ===========================================================================


class TestOutcomePersistence:
    def test_no_second_outcome_row_is_created(self, world):
        from iig_checklist.models import CalculationOutcome

        before = CalculationOutcome.objects.count()
        _run(world, "percentage_w_w")
        assert CalculationOutcome.objects.count() == before
        assert (
            CalculationOutcome.objects.filter(
                response=world["responses"]["percentage_w_w"]
            ).count()
            == 1
        )

    def test_inputs_are_persisted_json_safe(self, world):
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert set(outcome.inputs) == {
            "quantity_per_unit_grams", "total_dosage_unit_weight_grams"
        }
        # Exact decimal strings, never floats.
        assert outcome.inputs["quantity_per_unit_grams"] == "0.250000"
        for value in outcome.inputs.values():
            assert isinstance(value, str)

    def test_provenance_carries_the_governed_keys(self, world):
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        provenance = outcome.input_provenance
        assert provenance[BINDING_VERSION_KEY] == "1.0.0"
        assert provenance["calculation_name"] == "calculate_percentage_w_w"
        assert provenance["formula_version"] == engine.FORMULA_VERSION
        assert provenance[COMPONENT_KEY] == str(world["component"].public_id)

    def test_per_input_descriptors_are_recorded(self, world):
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        descriptor = outcome.input_provenance["quantity_per_unit_grams"]
        assert descriptor["source_kind"] == "formulation_component"
        assert descriptor["source_public_id"] == str(world["component"].public_id)
        assert descriptor["value"] == "0.250000"

    def test_provenance_carries_no_database_ids(self, world):
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()

        def walk(node):
            if isinstance(node, dict):
                for key, item in node.items():
                    assert key not in {"pk", "id"}
                    assert not (key.endswith("_id") and not key.endswith("_public_id"))
                    walk(item)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, str):
                assert "object at" not in node

        walk(outcome.input_provenance)
        walk(outcome.inputs)

    def test_snapshot_public_id_recorded(self, world):
        snapshot = _snapshot(world)
        _run(world, "percentage_of_iid_potency", snapshot=snapshot)
        outcome = world["outcomes"]["percentage_of_iid_potency"]
        outcome.refresh_from_db()
        assert outcome.source_assessment_snapshot_public_id == snapshot.public_id
        assert outcome.input_provenance["assessment_snapshot_public_id"] == str(
            snapshot.public_id
        )

    def test_response_is_never_mutated(self, world):
        """M4D3-MDL-006 -- results live exclusively in the outcome."""
        response = world["responses"]["percentage_w_w"]
        before = (response.raw_value, response.version, response.system_derived_value,
                  response.is_not_applicable)
        _run(world, "percentage_w_w")
        response.refresh_from_db()
        assert (response.raw_value, response.version, response.system_derived_value,
                response.is_not_applicable) == before
        assert response.raw_value is None

    def test_no_history_row_is_written(self, world):
        """M4D3-HST-003 -- no response transition, so no history row is due."""
        from iig_checklist.models import ChecklistResponseHistory

        before = ChecklistResponseHistory.objects.count()
        _run(world, "percentage_w_w")
        assert ChecklistResponseHistory.objects.count() == before


# ===========================================================================
# C. Component provenance, including inherited chains
# ===========================================================================


class TestComponentProvenance:
    def test_selector_component_is_written(self, world):
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.input_provenance[COMPONENT_KEY] == str(
            world["component"].public_id
        )
        assert "selector" in outcome.input_provenance["subject_component_sources"]

    def test_inherited_component_is_written_without_a_selector(self, world):
        """percentage_of_iid_mde declares no selector; it inherits.

        Writing the key here is what keeps component provenance alive through a
        dependency chain -- it is deliberately not limited to entries that
        declare a component_selector.
        """
        _complete_daily_exposure(world)
        _run(world, "percentage_of_iid_mde", snapshot=_snapshot(world))
        outcome = world["outcomes"]["percentage_of_iid_mde"]
        outcome.refresh_from_db()
        entry = registry_mod.get_entry("percentage_of_iid_mde")
        assert not any(
            d.get("component_selector") for d in entry.input_resolvers.values()
        )
        assert outcome.input_provenance[COMPONENT_KEY] == str(
            world["component"].public_id
        )
        assert "inherited" in outcome.input_provenance["subject_component_sources"]
        outcome.full_clean()

    def test_three_level_chain_preserves_the_component(self, world, monkeypatch):
        """A -> B -> C: the middle outcome's component reaches the third level.

        The approved registry is only two levels deep, so the third link is
        synthetic. Without writing the key on the inherited middle outcome, C
        would resolve no component and its snapshot check would be skipped.
        """
        from iig_checklist.models import CalculationOutcome, ChecklistResponse

        third = _calculated(world["section"], "Q_LEVEL3", "level_three", order=20)
        level_three = _entry(
            calculation_name="calculate_difference_from_mde",
            function=engine.calculate_difference_from_mde,
            input_resolvers=MappingProxyType(
                {
                    "converted_proposed_daily_exposure": MappingProxyType(
                        {
                            "source": registry_mod.SOURCE_CALCULATION_OUTCOME,
                            "question_code": "Q_PCT_MDE",
                            "field": "value",
                            "required_status": "complete",
                            "unit_source": "percent_of_mde",
                            "expected_type": "decimal",
                        }
                    ),
                    "selected_iid_mde": MappingProxyType(
                        {
                            "source": registry_mod.SOURCE_ASSESSMENT_SNAPSHOT,
                            "field": "iid_mde",
                            "unit_field": "iid_mde_unit",
                            "expected_type": "decimal",
                        }
                    ),
                }
            ),
            calculation_dependencies=("Q_PCT_MDE",),
            recalculation_triggers=("Q_PCT_MDE",),
            output_unit="",
        )
        _install(
            monkeypatch,
            {**dict(registry_mod.CALCULATION_BINDING_REGISTRY), "level_three": level_three},
        )

        snapshot = _snapshot(world)
        _complete_daily_exposure(world)
        _run(world, "percentage_of_iid_mde", snapshot=snapshot)

        middle = world["outcomes"]["percentage_of_iid_mde"]
        middle.refresh_from_db()
        assert middle.input_provenance[COMPONENT_KEY] == str(
            world["component"].public_id
        )

        third_response = ChecklistResponse.objects.create(
            execution=world["execution"], question=third,
            data_source_type_snapshot=third.data_source_classification,
        )
        CalculationOutcome.objects.create(
            response=third_response, calculation_name="calculate_difference_from_mde",
            status=CalculationStatus.DATA_REQUIRED,
        )
        result = execute_calculation_response(
            tenant=world["tenant"], execution=world["execution"],
            response=third_response, actor=world["user"],
            expected_version=third_response.version,
            snapshot_context=ResolutionContext(assessment_snapshot=snapshot),
        )
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        third_outcome = CalculationOutcome.objects.get(response=third_response)
        assert third_outcome.input_provenance[COMPONENT_KEY] == str(
            world["component"].public_id
        )

    def test_mismatched_component_fails_atomically(self, world):
        """A snapshot for another component is rejected with no value stored."""
        other = _component(world["formulation"], quantity="0.100000", order=9)
        outcome = world["outcomes"]["percentage_of_iid_potency"]
        result = _run(
            world, "percentage_of_iid_potency",
            snapshot=_snapshot(world, component=other),
        )
        assert not result.executed
        assert "ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH" in result.failure_codes
        outcome.refresh_from_db()
        assert outcome.value is None
        assert outcome.status == CalculationStatus.ERROR


# ===========================================================================
# D. Non-success engine and resolver results
# ===========================================================================


class TestNonSuccessResults:
    def test_input_failure_persists_a_governed_outcome(self, world):
        """A missing snapshot is DATA_REQUIRED, with a null value."""
        result = _run(world, "percentage_of_iid_potency")
        assert not result.executed
        assert "ASSESSMENT_SNAPSHOT_MISSING" in result.failure_codes
        outcome = world["outcomes"]["percentage_of_iid_potency"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.DATA_REQUIRED
        assert outcome.reason_code == "DATA_REQUIRED"
        assert outcome.value is None
        assert outcome.unit == ""
        assert outcome.input_provenance["input_failures"][0]["failure_code"] == (
            "ASSESSMENT_SNAPSHOT_MISSING"
        )
        outcome.full_clean()

    def test_tenant_failure_is_not_a_scientific_result(self, world, tenant_b):
        """M4D3-IFV-005 -- isolation faults never become NOT_COMPARABLE."""
        snapshot = _snapshot(world)
        snapshot.tenant = tenant_b
        snapshot.save(update_fields=["tenant"])
        result = _run(world, "percentage_of_iid_potency", snapshot=snapshot)
        outcome = world["outcomes"]["percentage_of_iid_potency"]
        outcome.refresh_from_db()
        assert "ASSESSMENT_SNAPSHOT_TENANT_MISMATCH" in result.failure_codes
        assert outcome.status == CalculationStatus.ERROR
        assert outcome.reason_code == "TENANT_ISOLATION_VIOLATION"
        assert outcome.reason_code != "NOT_COMPARABLE"
        assert outcome.value is None

    def test_engine_non_ok_status_yields_null_value(self, world, monkeypatch):
        """Every non-OK engine status stores a null value."""

        def _not_comparable(**kwargs):
            return engine.CalculationResult(
                formula_identifier="percentage_w_w",
                formula_version=engine.FORMULA_VERSION,
                status="UNIT_MISMATCH",
                value=Decimal("99"),
                unit="percent_w_w",
                generated_at="2026-01-01T00:00:00Z",
            )

        _install_percentage_w_w(monkeypatch, _not_comparable)
        result = _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.ERROR
        assert outcome.reason_code == "UNIT_MISMATCH"
        assert outcome.value is None
        assert outcome.unit == ""
        assert result.value is None

    def test_engine_data_required_maps_to_data_required(self, world, monkeypatch):
        def _data_required(**kwargs):
            return engine.CalculationResult(
                formula_identifier="percentage_w_w",
                formula_version=engine.FORMULA_VERSION,
                status="DATA_REQUIRED",
                generated_at="2026-01-01T00:00:00Z",
            )

        _install_percentage_w_w(monkeypatch, _data_required)
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.DATA_REQUIRED
        assert outcome.reason_code == "DATA_REQUIRED"
        assert outcome.value is None

    def test_unknown_engine_status_fails_closed(self, world, monkeypatch):
        def _unknown(**kwargs):
            return engine.CalculationResult(
                formula_identifier="percentage_w_w",
                formula_version=engine.FORMULA_VERSION,
                status="SOMETHING_NEW",
                value=Decimal("5"),
                generated_at="2026-01-01T00:00:00Z",
            )

        _install_percentage_w_w(monkeypatch, _unknown)
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.ERROR
        assert outcome.reason_code == "UNKNOWN_ENGINE_STATUS"
        assert outcome.value is None

    def test_invalid_generated_at_fails_closed(self, world, monkeypatch):
        def _naive(**kwargs):
            return engine.CalculationResult(
                formula_identifier="percentage_w_w",
                formula_version=engine.FORMULA_VERSION,
                status="OK", value=Decimal("25"), unit="percent_w_w",
                generated_at="2026-01-01T00:00:00",  # no timezone
            )

        _install_percentage_w_w(monkeypatch, _naive)
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.ERROR
        assert outcome.reason_code == "INVALID_GENERATED_AT"
        assert outcome.value is None


# ===========================================================================
# E. Concurrency and atomicity
# ===========================================================================


def _snapshot_state(world):
    from audit.models import AuditEvent
    from iid_assessment.models import AssessmentSnapshot
    from iig_checklist.models import (
        CalculationOutcome,
        ChecklistResponse,
        ChecklistResponseHistory,
    )

    outcomes = sorted(
        (str(o.public_id), o.status, str(o.value), o.unit,
         str(o.input_provenance), str(o.inputs))
        for o in CalculationOutcome.objects.all()
    )
    responses = sorted(
        (str(r.public_id), str(r.raw_value), r.version, r.is_not_applicable)
        for r in ChecklistResponse.objects.all()
    )
    return (
        outcomes, responses,
        AssessmentSnapshot.objects.count(),
        ChecklistResponseHistory.objects.count(),
        AuditEvent.objects.count(),
    )


class TestAtomicity:
    def test_stale_expected_version_changes_nothing(self, world):
        before = _snapshot_state(world)
        with pytest.raises(StaleResponseVersion):
            _run(world, "percentage_w_w", expected_version=999)
        assert _snapshot_state(world) == before

    def test_engine_exception_rolls_back(self, world, monkeypatch):
        def _explode(**kwargs):
            raise RuntimeError("engine imploded")

        _install_percentage_w_w(monkeypatch, _explode)
        before = _snapshot_state(world)
        with pytest.raises(CalculationEngineFailure) as raised:
            _run(world, "percentage_w_w")
        assert "engine imploded" not in str(raised.value)
        assert _snapshot_state(world) == before

    def test_missing_placeholder_fails_closed(self, world):
        from iig_checklist.models import CalculationOutcome

        CalculationOutcome.objects.filter(
            response=world["responses"]["percentage_w_w"]
        ).delete()
        before = _snapshot_state(world)
        with pytest.raises(PlaceholderMissing):
            _run(world, "percentage_w_w")
        assert _snapshot_state(world) == before

    def test_duplicate_placeholder_fails_closed(self, world):
        from iig_checklist.models import CalculationOutcome

        CalculationOutcome.objects.create(
            response=world["responses"]["percentage_w_w"],
            calculation_name="calculate_percentage_w_w",
            status=CalculationStatus.DATA_REQUIRED,
        )
        before = _snapshot_state(world)
        with pytest.raises(PlaceholderAmbiguous):
            _run(world, "percentage_w_w")
        assert _snapshot_state(world) == before

    def test_non_calculated_target_is_rejected(self, world):
        from iig_checklist.models import ChecklistResponse

        response = ChecklistResponse.objects.get(
            execution=world["execution"],
            question__code=registry_mod.Q_SUBJECT_COMPONENT,
        )
        with pytest.raises(TargetNotCalculated):
            execute_calculation_response(
                tenant=world["tenant"], execution=world["execution"],
                response=response, actor=world["user"],
                expected_version=response.version,
            )

    def test_response_from_another_execution_is_rejected(self, world, user_a):
        from iig_checklist.models import ChecklistExecution

        other = ChecklistExecution.objects.create(
            tenant=world["tenant"], checklist_version=world["version"],
            formulation_version=_formulation(
                _product(world["tenant"], user_a, code="PROD-EX-02"), user_a
            ),
            status=ExecutionStatus.DRAFT, created_by=user_a,
        )
        with pytest.raises(ResponseNotInExecution):
            execute_calculation_response(
                tenant=world["tenant"], execution=other,
                response=world["responses"]["percentage_w_w"], actor=world["user"],
                expected_version=1,
            )

    def test_unknown_binding_is_rejected(self, world):
        question = world["questions"]["percentage_w_w"]
        question.calculation_binding_identifier = "not_a_registry_key"
        question.save(update_fields=["calculation_binding_identifier", "updated_at"])
        response = world["responses"]["percentage_w_w"]
        response.refresh_from_db()
        before = _snapshot_state(world)
        with pytest.raises(BindingNotApproved):
            execute_calculation_response(
                tenant=world["tenant"], execution=world["execution"],
                response=response, actor=world["user"],
                expected_version=response.version,
            )
        assert _snapshot_state(world) == before


# ===========================================================================
# F. Audit
# ===========================================================================


class TestAudit:
    def test_success_emits_exactly_one_audit_event(
        self, world, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            _run(world, "percentage_w_w")
        events = list(
            AuditEvent.objects.filter(
                event_type=CALCULATED_EVENT,
                resource_id=str(world["responses"]["percentage_w_w"].public_id),
            )
        )
        assert len(events) == 1
        payload = events[0].payload
        assert payload["status"] == CalculationStatus.COMPLETE
        assert payload["calculation_name"] == "calculate_percentage_w_w"
        assert payload["question_code"] == "Q_PCT_WW"
        assert "value" not in payload  # no regulated result in the audit body

    def test_rollback_emits_no_audit(self, world, django_capture_on_commit_callbacks):
        from audit.models import AuditEvent

        before = AuditEvent.objects.count()
        with (
            pytest.raises(StaleResponseVersion),
            django_capture_on_commit_callbacks(execute=True),
        ):
            _run(world, "percentage_w_w", expected_version=999)
        assert AuditEvent.objects.count() == before

    def test_governed_failure_still_audits_its_status(
        self, world, django_capture_on_commit_callbacks
    ):
        """A DATA_REQUIRED outcome is a governed result, not a silent no-op."""
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            _run(world, "percentage_of_iid_potency")
        event = AuditEvent.objects.get(
            event_type=CALCULATED_EVENT,
            resource_id=str(world["responses"]["percentage_of_iid_potency"].public_id),
        )
        assert event.payload["status"] == CalculationStatus.DATA_REQUIRED


# ===========================================================================
# G. Recalculation of the same response
# ===========================================================================


class TestRecalculation:
    def test_recalculation_updates_the_same_row(self, world):
        from iig_checklist.models import CalculationOutcome

        first = _run(world, "percentage_w_w")
        outcome_id = first.outcome_public_id
        world["component"].quantity_per_dosage_unit = Decimal("0.500000")
        world["component"].save(
            update_fields=["quantity_per_dosage_unit", "updated_at"]
        )
        second = _run(world, "percentage_w_w")

        assert second.outcome_public_id == outcome_id
        assert second.value == Decimal("50")
        assert (
            CalculationOutcome.objects.filter(
                response=world["responses"]["percentage_w_w"]
            ).count()
            == 1
        )

    def test_recalculation_replaces_provenance_atomically(self, world):
        snapshot_one = _snapshot(world)
        _run(world, "percentage_of_iid_potency", snapshot=snapshot_one)
        snapshot_two = _snapshot(world, potency="2.000000")
        _run(world, "percentage_of_iid_potency", snapshot=snapshot_two)

        outcome = world["outcomes"]["percentage_of_iid_potency"]
        outcome.refresh_from_db()
        assert outcome.source_assessment_snapshot_public_id == snapshot_two.public_id
        assert outcome.input_provenance["assessment_snapshot_public_id"] == str(
            snapshot_two.public_id
        )
        assert str(snapshot_one.public_id) not in str(outcome.input_provenance)
