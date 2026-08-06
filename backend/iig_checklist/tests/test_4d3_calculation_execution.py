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

import dataclasses
import inspect
import re
import threading
from decimal import Decimal
from types import MappingProxyType

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from iid_assessment import calculations as engine
from iig_checklist import calculation_execution as execution_mod
from iig_checklist import calculation_registry as registry_mod
from iig_checklist.calculation_execution import (
    BindingNotApproved,
    CalculationEngineFailure,
    CalculationExecutionResult,
    InvalidExpectedVersion,
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
from iig_checklist.calculation_translation import format_decimal_plain
from iig_checklist.enums import (
    AnswerType,
    CalculationStatus,
    Criticality,
    DataSourceClassification,
    ExecutionStatus,
)

pytestmark = pytest.mark.django_db

CALCULATED_EVENT = "iig_checklist.response.calculated"

_EXPONENT = re.compile(r"\d[eE][+-]?\d")


def _is_scientific(text: str) -> bool:
    """True only for a *number* rendered in scientific form.

    A public UUID such as ``...aca7-474b30d178a7`` contains ``4e5c``, so a bare
    regex sweep over a whole provenance structure would flag identifiers as
    exponents. Requiring the string to parse as a Decimal keeps the check on
    numbers alone.
    """
    if not _EXPONENT.search(text):
        return False
    try:
        Decimal(text)
    except (ArithmeticError, ValueError):
        return False
    return True


def _exponent_values(node) -> list[str]:
    """Every persisted number in ``node`` that is stored in scientific form."""
    if isinstance(node, dict):
        return [found for item in node.values() for found in _exponent_values(item)]
    if isinstance(node, list | tuple):
        return [found for item in node for found in _exponent_values(item)]
    if isinstance(node, str):
        return [node] if _is_scientific(node) else []
    return []


def _has_exponent(value) -> bool:
    """True when any persisted number in ``value`` uses scientific form."""
    if isinstance(value, str):
        return _is_scientific(value)
    return bool(_exponent_values(value))


def _executable_source(source: str) -> str:
    """``source`` with docstrings and comments removed.

    A module that documents "no ``.first()``" would otherwise fail a search for
    ``.first()`` in its own prose.
    """
    import ast
    import io
    import tokenize

    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add((body[0].lineno, body[0].end_lineno))

    dropped = {n for start, end in docstrings for n in range(start, end + 1)}
    kept = [
        line
        for number, line in enumerate(source.splitlines(), start=1)
        if number not in dropped
    ]
    readline = io.StringIO("\n".join(kept)).readline
    out = []
    for token in tokenize.generate_tokens(readline):
        if token.type != tokenize.COMMENT:
            out.append(token.string)
    return "\n".join(out)


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


def _component(formulation, *, quantity="0.250000", order=1, ctype="inactive",
               ingredient=None):
    from formulations.models import FormulationComponent

    return FormulationComponent.objects.create(
        formulation_version=formulation, component_type=ctype,
        ingredient_name="Synthetic Excipient",
        resolved_ingredient_public_id=(
            ingredient.public_id if ingredient is not None else None
        ),
        quantity_per_dosage_unit=Decimal(quantity), quantity_unit="gram",
        display_order=order,
    )


def _iid_setup(*, potency="1.000000", mde="2.000000"):
    """One active FDA IID release with a CALCULABLE precedent for the excipient.

    The governed snapshot service resolves this release server-side
    (M4D3-SRC-001) and freezes its potency and MDE, so these are the values the
    approved calculations are checked against: a 1 g potency and a 2 g maximum
    daily exposure, matching the hand-checkable fixture in the module docstring.
    """
    from fda_data.models import (
        ControlledDosageForm,
        ControlledRoute,
        ControlledUnit,
        FDADataSourceRelease,
        FDAReleaseStatus,
        IIDCalculabilityStatus,
        IIDIngredient,
        IIDPrecedentRecord,
    )

    route = ControlledRoute.objects.create(
        code="oral", canonical_label="Oral", lifecycle="active"
    )
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    gram = ControlledUnit.objects.create(
        code="gram", symbol="G", dimension="mass", active=True
    )
    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid", source_name="FDA IID",
        official_source_reference="ref", source_checksum_sha256="a" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )
    ingredient = IIDIngredient.objects.create(
        canonical_name="Synthetic Excipient", normalized_name="SYNTHETIC EXCIPIENT"
    )
    record = IIDPrecedentRecord.objects.create(
        release=release, ingredient=ingredient,
        ingredient_name_raw="Synthetic Excipient",
        route_raw="ORAL", route_normalized=route,
        dosage_form_raw="TABLET", dosage_form_normalized=dosage_form,
        potency_amount=Decimal(potency), potency_unit_raw="G",
        potency_unit_normalized=gram,
        maximum_daily_exposure=Decimal(mde), mde_unit_raw="G",
        mde_unit_normalized=gram,
        raw_row_checksum="b" * 64,
        calculability_status=IIDCalculabilityStatus.CALCULABLE,
    )
    return {
        "route": route, "dosage_form": dosage_form, "unit": gram,
        "release": release, "ingredient": ingredient, "record": record,
    }


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

    iid = _iid_setup()
    product = _product(tenant_a, user_a)
    formulation = _formulation(product, user_a, max_units="4.0000")
    component = _component(formulation, ingredient=iid["ingredient"])
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
        "selector_response": selector_response, "iid": iid,
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


#: ``expected_version`` is mandatory, so the helper needs a sentinel distinct
#: from ``None`` -- ``None`` is now a value under test in its own right.
_AUTO = object()


def _run(world, key, *, snapshot=None, expected_version=_AUTO, actor=None):
    """Execute one calculated response.

    ``snapshot`` is only for the tests that must pin a *specific* -- usually
    deliberately wrong -- snapshot through the private hook. Left unset, the
    service creates its own governed snapshot, which is the production path.
    """
    response = world["responses"][key]
    return execute_calculation_response(
        tenant=world["tenant"],
        execution=world["execution"],
        response=response,
        actor=actor or world["user"],
        expected_version=(
            response.version if expected_version is _AUTO else expected_version
        ),
        _internal_snapshot_context=(
            ResolutionContext(assessment_snapshot=snapshot)
            if snapshot is not None
            else None
        ),
    )


def _created_snapshot(world):
    """The single snapshot the governed service created for this execution."""
    from iid_assessment.models import AssessmentSnapshot

    snapshots = list(AssessmentSnapshot.objects.filter(tenant=world["tenant"]))
    assert len(snapshots) == 1, snapshots
    return snapshots[0]


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
            _internal_snapshot_context=ResolutionContext(assessment_snapshot=snapshot),
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
        """A snapshot that froze no IID potency is DATA_REQUIRED, value null.

        The service now always creates a snapshot, so the governed failure is no
        longer an absent snapshot but an empty one: with no matching precedent
        record the snapshot is still frozen -- that is the reproducible record of
        "no precedent existed" -- and Form D reports the missing field.
        """
        world["iid"]["record"].delete()
        result = _run(world, "percentage_of_iid_potency")
        assert not result.executed
        # An empty snapshot fails both snapshot-derived kwargs: the potency
        # value is absent, and so is the unit the proposed quantity would have
        # been converted into. Both are governed missing-data codes.
        assert set(result.failure_codes) == {
            "ASSESSMENT_FIELD_MISSING", "INPUT_UNIT_MISSING",
        }
        outcome = world["outcomes"]["percentage_of_iid_potency"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.DATA_REQUIRED
        assert outcome.reason_code == "DATA_REQUIRED"
        assert outcome.value is None
        assert outcome.unit == ""
        recorded = {
            failure["failure_code"]
            for failure in outcome.input_provenance["input_failures"]
        }
        assert recorded == set(result.failure_codes)
        outcome.full_clean()
        # The snapshot still exists: a governed event always leaves one behind.
        snapshot = _created_snapshot(world)
        assert snapshot.iid_potency_amount is None
        assert snapshot.match_status == "NO_MATCHING_IID_PRECEDENT"

    def test_a_snapshot_is_created_even_when_no_precedent_matches(self, world):
        """M4D3-SNO-006 -- the event is recorded whatever the outcome."""
        from iid_assessment.models import AssessmentSnapshot

        world["iid"]["record"].delete()
        assert AssessmentSnapshot.objects.count() == 0
        _run(world, "percentage_of_iid_potency")
        assert AssessmentSnapshot.objects.count() == 1

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

    def test_engine_unit_mismatch_yields_null_value(self, world, monkeypatch):
        """A UNIT_MISMATCH engine status stores UNIT_MISMATCH and a null value.

        Deliberately distinct from the NOT_COMPARABLE test below: a unit fault is
        a configuration condition and must never be recorded as scientific
        non-comparability (M4D3-IFV-004/005).
        """

        def _unit_mismatch(**kwargs):
            return engine.CalculationResult(
                formula_identifier="percentage_w_w",
                formula_version=engine.FORMULA_VERSION,
                status="UNIT_MISMATCH",
                value=Decimal("99"),
                unit="percent_w_w",
                generated_at="2026-01-01T00:00:00Z",
            )

        _install_percentage_w_w(monkeypatch, _unit_mismatch)
        result = _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.ERROR
        assert outcome.reason_code == "UNIT_MISMATCH"
        assert outcome.reason_code != "NOT_COMPARABLE"
        assert outcome.value is None
        assert outcome.unit == ""
        assert result.value is None

    def test_engine_emits_not_comparable_for_an_unclear_basis(self):
        """The engine really does produce NOT_COMPARABLE (M4D3-TRL-002).

        ``BASIS_UNCLEAR`` resolves to the string ``NOT_COMPARABLE``, and a zero
        dosage-unit weight is the governed condition that reaches it. Proven
        against the pure engine so the persistence test below is exercising a
        real engine status rather than a hand-written one.
        """
        assert engine.CalculationStatus.BASIS_UNCLEAR == "NOT_COMPARABLE"
        result = engine.calculate_percentage_w_w(
            quantity_per_unit_grams=Decimal("0.25"),
            total_dosage_unit_weight_grams=Decimal("0"),
        )
        assert result.status == "NOT_COMPARABLE"
        assert result.value is None

    def test_genuine_not_comparable_is_persisted(self, world, monkeypatch):
        """A real engine NOT_COMPARABLE persists as NOT_COMPARABLE.

        The formulation table forbids a zero ``total_dosage_unit_weight``
        (``formulation_total_weight_positive``), so the governed basis-unclear
        condition is reached by handing the approved function the zero basis
        directly; the status returned is the engine's own, unmodified.
        """

        def _basis_unclear(**kwargs):
            return engine.calculate_percentage_w_w(
                quantity_per_unit_grams=kwargs["quantity_per_unit_grams"],
                total_dosage_unit_weight_grams=Decimal("0"),
            )

        _install_percentage_w_w(monkeypatch, _basis_unclear)
        result = _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.ERROR
        assert outcome.reason_code == "NOT_COMPARABLE"
        assert outcome.reason_code != "UNIT_MISMATCH"
        assert outcome.value is None
        assert outcome.unit == ""
        assert result.value is None

    def test_resolver_unit_fault_is_not_scientific_non_comparability(self, world):
        """An unknown source unit is UNIT_MISMATCH, never NOT_COMPARABLE."""
        world["component"].quantity_unit = "furlong"
        world["component"].save(update_fields=["quantity_unit", "updated_at"])
        result = _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert not result.executed
        assert "INPUT_UNIT_UNSUPPORTED" in result.failure_codes
        assert outcome.status == CalculationStatus.ERROR
        assert outcome.reason_code == "UNIT_MISMATCH"
        assert outcome.reason_code != "NOT_COMPARABLE"
        assert outcome.value is None

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

        world["iid"]["record"].delete()
        with django_capture_on_commit_callbacks(execute=True):
            _run(world, "percentage_of_iid_potency")
        event = AuditEvent.objects.get(
            event_type=CALCULATED_EVENT,
            resource_id=str(world["responses"]["percentage_of_iid_potency"].public_id),
        )
        assert event.payload["status"] == CalculationStatus.DATA_REQUIRED
        # The snapshot the event was calculated against is named in the audit.
        assert event.payload["assessment_snapshot_public_id"] == str(
            _created_snapshot(world).public_id
        )


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


# ===========================================================================
# H. Lock order, verified against the SQL PostgreSQL actually receives
# ===========================================================================

_LOCK_TABLES = (
    "iig_checklist_checklistexecution",
    "iig_checklist_checklistresponse",
    "iig_checklist_calculationoutcome",
    "iid_assessment_assessmentsnapshot",
)


def _table_of(sql: str) -> str:
    """The locked table, read from the quoted identifier rather than a guess."""
    lowered = sql.lower()
    for candidate in _LOCK_TABLES:
        if f'"{candidate}"' in lowered:
            return candidate
    return "?"


def _order_column(sql: str) -> str | None:
    """The bare column name an ``ORDER BY`` uses, alias-insensitive.

    Only the column matters here, so any table qualifier is discarded; the
    assertion stays strict about *which* column orders the lock.
    """
    lowered = sql.lower()
    marker = " order by "
    if marker not in lowered:
        return None
    clause = lowered.split(marker, 1)[1].split(" for update")[0]
    first = clause.split(",")[0].strip()
    column = first.replace(" asc", "").replace(" desc", "").strip()
    return column.split(".")[-1].strip('"')


def _capture_locks(fn):
    """Every ``FOR UPDATE`` statement ``fn`` issues, in execution order."""
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return [
        (_table_of(q["sql"]), _order_column(q["sql"]), q["sql"])
        for q in ctx.captured_queries
        if "for update" in q["sql"].lower()
    ]


@pytest.fixture
def snapshot_backed_locks(world):
    """Locks taken by a snapshot-backed calculation with a Form E dependency.

    ``percentage_of_iid_mde`` is the richest path: it locks the execution, its
    own response, the upstream daily-exposure response, both outcome rows and
    the snapshot.
    """
    snapshot = _snapshot(world)
    _complete_daily_exposure(world)
    return _capture_locks(
        lambda: _run(world, "percentage_of_iid_mde", snapshot=snapshot)
    )


class TestLockOrder:
    """M4D3-TXN-001 / M4D3-OUT-004 -- ascending primary key, never public_id."""

    def test_related_responses_are_locked_by_primary_key(self, snapshot_backed_locks):
        ordered = [
            (table, column)
            for table, column, _ in snapshot_backed_locks
            if table == "iig_checklist_checklistresponse" and column is not None
        ]
        assert ordered, "no ordered response lock was issued"
        assert all(column == "id" for _, column in ordered), ordered

    def test_outcomes_are_locked_by_primary_key(self, snapshot_backed_locks):
        ordered = [
            (table, column)
            for table, column, _ in snapshot_backed_locks
            if table == "iig_checklist_calculationoutcome"
        ]
        assert ordered, "no outcome lock was issued"
        assert all(column == "id" for _, column in ordered), ordered

    def test_all_outcomes_are_locked_by_one_statement(self, snapshot_backed_locks):
        """Upstream rows and the target placeholder share one ordered set."""
        outcome_locks = [
            sql
            for table, _, sql in snapshot_backed_locks
            if table == "iig_checklist_calculationoutcome"
        ]
        assert len(outcome_locks) == 1, outcome_locks
        assert "response_id" in outcome_locks[0].lower()

    def test_no_for_update_query_orders_by_public_id(self, snapshot_backed_locks):
        offenders = [
            sql
            for _, column, sql in snapshot_backed_locks
            if column is not None
            and (
                column == "public_id"
                or "public_id" in sql.lower().split(" order by ", 1)[1]
            )
        ]
        assert offenders == [], offenders

    def test_execution_is_locked_first(self, snapshot_backed_locks):
        assert snapshot_backed_locks[0][0] == "iig_checklist_checklistexecution"

    def test_target_response_precedes_related_responses(self, snapshot_backed_locks):
        responses = [
            (index, column)
            for index, (table, column, _) in enumerate(snapshot_backed_locks)
            if table == "iig_checklist_checklistresponse"
        ]
        assert len(responses) >= 2, responses
        target_index, target_order = responses[0]
        related_index, related_order = responses[1]
        # The target is a single-row lock, so it carries no ORDER BY; the
        # related set that follows it is pk-ordered.
        assert target_order is None
        assert related_order == "id"
        assert target_index < related_index

    def test_target_outcome_is_locked_before_the_snapshot(self, snapshot_backed_locks):
        tables = [table for table, _, _ in snapshot_backed_locks]
        assert tables.index("iig_checklist_calculationoutcome") < tables.index(
            "iid_assessment_assessmentsnapshot"
        ), tables

    def test_snapshot_is_locked_last(self, snapshot_backed_locks):
        assert snapshot_backed_locks[-1][0] == "iid_assessment_assessmentsnapshot"

    def test_documented_order_matches_the_issued_statements(
        self, snapshot_backed_locks
    ):
        assert [table for table, _, _ in snapshot_backed_locks] == [
            "iig_checklist_checklistexecution",
            "iig_checklist_checklistresponse",   # target
            "iig_checklist_checklistresponse",   # related, pk order
            "iig_checklist_calculationoutcome",  # upstream + target, pk order
            "iid_assessment_assessmentsnapshot",
        ]

    def test_lock_helpers_normalise_caller_supplied_order(self, world):
        """The helpers order by pk whatever order the caller hands them.

        This is what lets a future cascade or rebinding service reuse them and
        arrive at the same acquisition order as direct execution.
        """
        from iig_checklist.models import ChecklistResponse

        ids = list(
            ChecklistResponse.objects.filter(execution=world["execution"])
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        assert len(ids) >= 3

        for supplied in (ids, list(reversed(ids)), [ids[1], ids[0], *ids[2:]]):
            locks = _capture_locks(
                lambda batch=supplied: (
                    execution_mod._lock_responses(batch),
                    execution_mod._lock_outcomes(batch),
                )
            )
            assert [column for _, column, _ in locks] == ["id", "id"], supplied


class TestLockHelperEdges:
    """The guards the six approved entries never reach, but a cascade would."""

    def test_an_entry_declaring_no_question_codes_locks_no_related_rows(self, world):
        """A registry entry reading only formulation fields has nothing to lock."""
        entry = _entry(input_resolvers=MappingProxyType({}))
        assert execution_mod._declared_question_codes(entry) == set()
        assert (
            execution_mod._related_response_ids(
                world["execution"], entry, world["responses"]["percentage_w_w"].pk
            )
            == []
        )

    def test_empty_batches_issue_no_lock_at_all(self, world):
        """An empty id list must never become an unbounded FOR UPDATE."""
        locks = _capture_locks(lambda: execution_mod._lock_responses([]))
        assert locks == []
        outcomes = None

        def _lock_none():
            nonlocal outcomes
            outcomes = execution_mod._lock_outcomes([])

        assert _capture_locks(_lock_none) == []
        assert outcomes == []


class TestLockOrderConcurrency:
    """A real overlap between two differently-ordered row sets."""

    @pytest.mark.django_db(transaction=True)
    def test_overlapping_transactions_do_not_deadlock(self, world):
        """Two transactions, opposite logical starting points, same pk order.

        One holds the row set an execution touches; the other holds the wider
        set a cascade or rebinding pass would touch, supplied in reverse. Both
        go through the governed helpers, so both acquire ascending pk and one
        simply waits. Ordering by ``public_id`` on either side would have made
        this a deadlock.
        """
        from django.db import connections, transaction

        from iig_checklist.models import ChecklistResponse

        ids = list(
            ChecklistResponse.objects.filter(execution=world["execution"])
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        assert len(ids) >= 3

        start = threading.Barrier(2, timeout=30)
        errors: list[BaseException] = []
        orders: dict[str, list[str | None]] = {}

        def acquire(name, supplied):
            try:
                with transaction.atomic():
                    # 5 s is far longer than this contention needs and far
                    # shorter than the test timeout, so a genuine inversion
                    # surfaces as a failure instead of a hang.
                    with connections["default"].cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                    start.wait()
                    locks = _capture_locks(
                        lambda: (
                            execution_mod._lock_responses(supplied),
                            execution_mod._lock_outcomes(supplied),
                        )
                    )
                    orders[name] = [column for _, column, _ in locks]
            except BaseException as exc:
                # Reported through ``errors``, never swallowed -- a deadlock or
                # lock timeout must fail the test, not disappear in a thread.
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=acquire, args=("execution", list(ids))),
            threading.Thread(target=acquire, args=("cascade", list(reversed(ids)))),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not any(thread.is_alive() for thread in threads), "a transaction hung"
        assert errors == [], errors
        assert orders == {"execution": ["id", "id"], "cascade": ["id", "id"]}

    @pytest.mark.django_db(transaction=True)
    def test_execution_lock_serialises_concurrent_calculations(self, world):
        """M4D3-TXN-006 -- the execution row is the serialization barrier."""
        from django.db import connections, transaction

        from iig_checklist.models import ChecklistExecution

        order: list[str] = []
        locked = threading.Event()
        release = threading.Event()

        def holder():
            try:
                with transaction.atomic():
                    list(
                        ChecklistExecution.objects.filter(pk=world["execution"].pk)
                        .select_for_update()
                    )
                    order.append("holder-locked")
                    locked.set()
                    release.wait(timeout=30)
                    order.append("holder-releasing")
            finally:
                connections.close_all()

        thread = threading.Thread(target=holder)
        thread.start()
        assert locked.wait(timeout=30)

        def run_service():
            order.append("service-start")
            release.set()
            result = _run(world, "percentage_w_w")
            order.append("service-done")
            return result

        result = run_service()
        thread.join(timeout=30)

        assert result.status == CalculationStatus.COMPLETE, result.failure_codes
        assert order.index("holder-releasing") < order.index("service-done"), order


# ===========================================================================
# I. Mandatory optimistic concurrency
# ===========================================================================


class TestExpectedVersionIsMandatory:
    """M4D3-TXN-003 -- there is no value that disables the check."""

    @pytest.mark.parametrize(
        "supplied",
        [None, True, False, 0, -1, "1", 1.0, Decimal("1")],
        ids=["none", "true", "false", "zero", "negative", "str", "float", "decimal"],
    )
    def test_unusable_expected_version_is_rejected(self, world, supplied):
        before = _snapshot_state(world)
        with pytest.raises(InvalidExpectedVersion):
            _run(world, "percentage_w_w", expected_version=supplied)
        assert _snapshot_state(world) == before

    def test_rejection_precedes_any_calculation_or_audit(self, world, monkeypatch):
        from audit.models import AuditEvent

        calls = []

        def _counting(**kwargs):
            calls.append(kwargs)
            return engine.calculate_percentage_w_w(**kwargs)

        _install_percentage_w_w(monkeypatch, _counting)
        audit_before = AuditEvent.objects.count()
        with pytest.raises(InvalidExpectedVersion):
            _run(world, "percentage_w_w", expected_version=None)
        assert calls == []
        assert AuditEvent.objects.count() == audit_before

    def test_the_correct_version_still_executes(self, world):
        response = world["responses"]["percentage_w_w"]
        assert response.version == 1
        result = _run(world, "percentage_w_w", expected_version=1)
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes

    def test_stale_version_invokes_no_calculation(self, world, monkeypatch):
        calls = []

        def _counting(**kwargs):
            calls.append(kwargs)
            return engine.calculate_percentage_w_w(**kwargs)

        _install_percentage_w_w(monkeypatch, _counting)
        before = _snapshot_state(world)
        with pytest.raises(StaleResponseVersion):
            _run(world, "percentage_w_w", expected_version=999)
        assert calls == []
        assert _snapshot_state(world) == before


# ===========================================================================
# J. Tenant isolation
# ===========================================================================


class TestTenantIsolation:
    def test_execution_from_another_tenant_is_rejected(
        self, world, tenant_b, monkeypatch
    ):
        """The guard fires before any lock, calculation, write or audit."""
        from audit.models import AuditEvent

        calls = []

        def _counting(**kwargs):
            calls.append(kwargs)
            return engine.calculate_percentage_w_w(**kwargs)

        _install_percentage_w_w(monkeypatch, _counting)
        before = _snapshot_state(world)
        audit_before = AuditEvent.objects.count()
        response = world["responses"]["percentage_w_w"]

        with pytest.raises(ResponseNotInExecution) as raised:
            execute_calculation_response(
                tenant=tenant_b,
                execution=world["execution"],
                response=response,
                actor=world["user"],
                expected_version=response.version,
            )

        assert calls == []
        assert _snapshot_state(world) == before
        assert AuditEvent.objects.count() == audit_before
        # No identifier of the foreign execution, response or tenant leaks.
        message = str(raised.value)
        for leaked in (
            str(world["execution"].public_id),
            str(response.public_id),
            str(tenant_b.id),
        ):
            assert leaked not in message

    def test_response_belonging_to_another_tenants_execution_is_rejected(
        self, world, tenant_b, user_a
    ):
        """Another tenant's response cannot be executed through this tenant."""
        from authorization.models import MembershipRole, Role
        from iig_checklist.models import ChecklistDefinition, ChecklistVersion
        from iig_checklist.services import create_execution
        from tenancy.models import TenantMembership

        # The foreign execution is built through the governed service, so the
        # actor needs a doer role in that tenant. This grants only what tenant B
        # needs; tenant A's guard is what the assertion is about.
        membership, _ = TenantMembership.objects.get_or_create(
            tenant=tenant_b, user=user_a
        )
        role, _ = Role.objects.get_or_create(
            tenant=tenant_b, name="doer", defaults={"is_system": True}
        )
        MembershipRole.objects.get_or_create(membership=membership, role=role)

        other_definition = ChecklistDefinition.objects.create(
            code="IIG-OTHER-TENANT", title="Other tenant (synthetic)",
            scope_type="tenant", tenant=tenant_b, created_by=user_a,
        )
        other_version = ChecklistVersion.objects.create(
            definition=other_definition, version_number=1, status="active",
            created_by=user_a,
        )
        other_section = _section(other_version, code="S9")
        _question(
            other_section, registry_mod.Q_SUBJECT_COMPONENT,
            answer_type=AnswerType.FORMULATION_COMPONENT_REFERENCE,
            classification=DataSourceClassification.USER_REQUIRED, order=1,
        )
        other_calculated = _calculated(
            other_section, "Q_PCT_WW", "percentage_w_w", order=2
        )
        other_product = _product(tenant_b, user_a, code="PROD-EX-TB")
        other_formulation = _formulation(other_product, user_a)
        _component(other_formulation)
        other_execution = create_execution(
            tenant=tenant_b,
            checklist_version_public_id=str(other_version.public_id),
            formulation_version_public_id=str(other_formulation.public_id),
            actor=user_a,
        )
        from iig_checklist.models import ChecklistResponse

        foreign_response = ChecklistResponse.objects.get(
            execution=other_execution, question=other_calculated
        )
        before = _snapshot_state(world)

        with pytest.raises(ResponseNotInExecution):
            execute_calculation_response(
                tenant=world["tenant"],
                execution=other_execution,
                response=foreign_response,
                actor=world["user"],
                expected_version=foreign_response.version,
            )
        assert _snapshot_state(world) == before


# ===========================================================================
# K. Model-validation rollback
# ===========================================================================


class TestFullCleanRollback:
    def test_planted_completion_invariant_failure_rolls_back(
        self, world, monkeypatch, django_capture_on_commit_callbacks
    ):
        """A completed outcome the model rejects must leave nothing behind.

        ``_registry_binding_version`` is planted as a two-part version, which
        ``CalculationOutcome._validate_completed_outcome()`` rejects. The
        calculation is invoked -- that is expected, the failure happens at
        persistence -- but no result survives.
        """
        from audit.models import AuditEvent

        calls = []

        def _counting(**kwargs):
            calls.append(kwargs)
            return engine.calculate_percentage_w_w(**kwargs)

        approved = registry_mod.CALCULATION_BINDING_REGISTRY["percentage_w_w"]
        planted = _entry(
            input_resolvers=approved.input_resolvers,
            recalculation_triggers=approved.recalculation_triggers,
            required_units=approved.required_units,
            output_unit=approved.output_unit,
            function=_counting,
            binding_version="1.0",  # not the governed three-part form
        )
        _install(
            monkeypatch,
            {**dict(registry_mod.CALCULATION_BINDING_REGISTRY), "percentage_w_w": planted},
        )

        before = _snapshot_state(world)
        audit_before = AuditEvent.objects.count()
        with (
            pytest.raises(ValidationError) as raised,
            django_capture_on_commit_callbacks(execute=True),
        ):
            _run(world, "percentage_w_w")

        assert BINDING_VERSION_KEY in str(raised.value)
        assert len(calls) == 1
        assert _snapshot_state(world) == before
        assert AuditEvent.objects.count() == audit_before

    def test_the_registry_is_restored_after_the_planted_failure(self, world):
        """The monkeypatch above is undone, so the approved entry still runs."""
        entry = registry_mod.get_entry("percentage_w_w")
        assert entry.binding_version == "1.0.0"
        result = _run(world, "percentage_w_w")
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes


# ===========================================================================
# L. Immutable result
# ===========================================================================


class TestImmutableResult:
    def test_result_fields_cannot_be_reassigned(self, world):
        result = _run(world, "percentage_w_w")
        for field in dataclasses.fields(result):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(result, field.name, None)

    def test_result_accepts_no_new_attribute_and_has_no_dict(self, world):
        result = _run(world, "percentage_w_w")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.injected = "x"
        assert not hasattr(result, "__dict__")
        assert CalculationExecutionResult.__dataclass_params__.frozen

    def test_nested_result_metadata_is_immutable(self, world):
        result = _run(world, "percentage_of_iid_potency")
        assert isinstance(result.failure_codes, tuple)
        with pytest.raises(AttributeError):
            result.failure_codes.append("INJECTED")
        with pytest.raises(TypeError):
            result.failure_codes[0] = "INJECTED"

    def test_complete_property_tracks_the_stored_status(self, world):
        """The result's own convenience accessor, part of its public contract."""
        assert _run(world, "percentage_w_w").complete is True
        # A resolver failure is a governed outcome, not a completion.
        world["iid"]["record"].delete()
        failed = _run(world, "percentage_of_iid_potency")
        assert failed.status == CalculationStatus.DATA_REQUIRED
        assert failed.complete is False

    def test_result_exposes_no_model_instance_or_queryset(self, world):
        from django.db.models import Model, QuerySet

        result = _run(world, "percentage_w_w")
        for field in dataclasses.fields(result):
            value = getattr(result, field.name)
            assert not isinstance(value, Model | QuerySet), field.name
            assert isinstance(value, str | bool | Decimal | tuple), field.name
        # Identity is the public UUID string, never a database id.
        assert result.outcome_public_id == str(
            world["outcomes"]["percentage_w_w"].public_id
        )


# ===========================================================================
# M. Persisted numeric formatting
# ===========================================================================


def _use_milligram_component(world):
    """Make the subject component 0.000001 mg, i.e. exactly 1E-9 g once converted."""
    world["component"].quantity_per_dosage_unit = Decimal("0.000001")
    world["component"].quantity_unit = "milligram"
    world["component"].save(
        update_fields=["quantity_per_dosage_unit", "quantity_unit", "updated_at"]
    )


class TestPlainNotationPersistence:
    """Regulated numbers are stored in plain notation, exactly."""

    def test_the_json_boundary_renders_every_governed_type(self):
        """`_json_safe` is the whole persistence boundary; each branch matters.

        Provenance can legitimately carry a UUID or a timestamp, and anything
        unforeseen must degrade to a string rather than break a governed write.
        """
        import uuid as uuid_module
        from datetime import UTC, datetime

        identifier = uuid_module.uuid4()
        moment = datetime(2026, 1, 1, tzinfo=UTC)

        assert execution_mod._json_safe(identifier) == str(identifier)
        assert execution_mod._json_safe(moment) == moment.isoformat()
        assert execution_mod._json_safe(Decimal("1E-7")) == "0.0000001"
        assert execution_mod._json_safe({"a": Decimal("1E-7")}) == {"a": "0.0000001"}
        assert execution_mod._json_safe(
            MappingProxyType({"a": (Decimal("1E-7"),)})
        ) == {"a": ["0.0000001"]}
        assert execution_mod._json_safe(["x", 1, True, None]) == ["x", 1, True, None]
        # Anything else is stringified rather than allowed to break the write.
        assert execution_mod._json_safe({1, 2}) in ("{1, 2}", "{2, 1}")

    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [
            ("1E-7", "0.0000001"),
            ("-1E-7", "-0.0000001"),
            ("1E-12", "0.000000000001"),
            ("1E+3", "1000"),
            ("0", "0"),
            ("0.250000", "0.250000"),
            ("-0.500000", "-0.500000"),
        ],
    )
    def test_formatter_never_emits_an_exponent(self, supplied, expected):
        rendered = format_decimal_plain(Decimal(supplied))
        assert rendered == expected
        assert "E" not in rendered.upper()
        assert Decimal(rendered) == Decimal(supplied)

    def test_tiny_converted_input_is_persisted_in_plain_notation(self, world):
        """A milligram quantity converts to 1E-9 g and must not persist as that.

        ``str(Decimal("1E-9"))`` really is ``'1E-9'``, so this is the exact
        condition the shared formatter exists for.
        """
        _use_milligram_component(world)
        result = _run(world, "percentage_w_w")
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes

        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        stored = outcome.inputs["quantity_per_unit_grams"]
        assert str(Decimal("1E-9")) == "1E-9"  # what a bare str() would have stored
        assert stored == "0.000000001"
        assert Decimal(stored) == Decimal("1E-9")
        descriptor = outcome.input_provenance["quantity_per_unit_grams"]
        assert descriptor["value"] == "0.000000001"
        assert not _has_exponent(outcome.inputs)
        assert not _has_exponent(outcome.input_provenance)

    def test_negative_input_is_persisted_in_plain_notation(self, world):
        """A negative reference keeps its sign and stays exponent-free.

        A negative IID potency is not a scientific scenario; it is the shortest
        governed path that puts a negative Decimal through the persistence
        boundary, and ``calculate_difference_from_potency`` applies no sign
        guard, so the difference completes normally.
        """
        snapshot = _snapshot(world, potency="-0.000001")
        result = _run(world, "difference_from_iid_potency", snapshot=snapshot)
        assert result.status == CalculationStatus.COMPLETE, result.failure_codes

        outcome = world["outcomes"]["difference_from_iid_potency"]
        outcome.refresh_from_db()
        stored = outcome.inputs["selected_iid_potency_amount"]
        assert stored == "-0.000001"
        assert Decimal(stored) == Decimal("-0.000001")
        assert stored.startswith("-")
        assert not _has_exponent(outcome.inputs)
        assert not _has_exponent(outcome.input_provenance)

    def test_repeated_execution_persists_an_identical_rendering(self, world):
        _use_milligram_component(world)
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        first = dict(outcome.inputs)
        _run(world, "percentage_w_w")
        outcome.refresh_from_db()
        assert dict(outcome.inputs) == first

    def test_conversion_provenance_is_also_plain(self, world):
        """The adapter and the writer share one formatter, so both stay plain."""
        _use_milligram_component(world)
        _run(world, "percentage_w_w")
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        provenance = outcome.input_provenance["quantity_per_unit_grams"]
        resolver = provenance["resolver_provenance"]
        assert resolver["original_value"] == "0.000001"
        assert resolver["converted_value"] == "0.000000001"
        assert not _has_exponent(resolver["conversion_factor"])
        assert _exponent_values(outcome.input_provenance) == []


# ===========================================================================
# N. Result unit for the difference calculations -- specification gap
# ===========================================================================


class TestDifferenceResultUnit:
    """M4D3-MAP-004/006 prescribe no result unit; this records that honestly.

    M4D3-MAP-007 explicitly tells the service to store ``gram`` for
    ``daily_exposure``, whose engine result also carries no unit. No equivalent
    clause exists for either difference calculation, and the registry contract
    states ``output_unit`` "may be empty", so the governed value today is the
    empty string. Inventing ``iid_potency_unit`` here would be a new rule, not an
    implementation of an approved one, so the gap is asserted rather than
    papered over. Recorded as a deferred specification requirement in
    docs/MILESTONE_4D_3_IMPLEMENTATION_EVIDENCE.md.
    """

    def test_registry_declares_no_output_unit_for_the_differences(self):
        for identifier in ("difference_from_iid_potency", "difference_from_iid_mde"):
            assert registry_mod.get_entry(identifier).output_unit == ""

    def test_daily_exposure_by_contrast_has_a_governed_unit(self, world):
        """M4D3-MAP-007 -- the clause that exists, and is honoured."""
        assert registry_mod.get_entry("daily_exposure").output_unit == "gram"
        result = _run(world, "daily_exposure")
        assert result.unit == "gram"

    def test_difference_outcomes_complete_with_an_empty_unit(self, world):
        """Documents the gap: a regulated Decimal with no stored unit."""
        snapshot = _snapshot(world)
        _complete_daily_exposure(world)
        for key in ("difference_from_iid_potency", "difference_from_iid_mde"):
            result = _run(world, key, snapshot=snapshot)
            assert result.status == CalculationStatus.COMPLETE, result.failure_codes
            assert result.value is not None
            assert result.unit == "", key
            outcome = world["outcomes"][key]
            outcome.refresh_from_db()
            assert outcome.unit == ""
            outcome.full_clean()

    def test_the_unit_remains_reconstructible_from_provenance(self, world):
        """The gap is bounded: both operands record their units."""
        snapshot = _snapshot(world)
        _run(world, "difference_from_iid_potency", snapshot=snapshot)
        outcome = world["outcomes"]["difference_from_iid_potency"]
        outcome.refresh_from_db()
        for kwarg in ("selected_iid_potency_amount", "converted_proposed_quantity"):
            descriptor = outcome.input_provenance[kwarg]
            assert descriptor.get("target_unit") == "gram" or (
                descriptor.get("source_unit") == "gram"
            ), (kwarg, descriptor)


# ===========================================================================
# O. Audit-callback failure and the deferred boundaries
# ===========================================================================


class TestAuditCallbackFailure:
    def test_a_failing_audit_callback_does_not_undo_the_commit(
        self, world, monkeypatch, django_capture_on_commit_callbacks
    ):
        """Established behaviour, not a new guarantee.

        The audit is dispatched through ``transaction.on_commit()``, so by the
        time it runs the outcome is already durable. The project has no durable
        outbox, so a failing callback propagates to the caller, writes no audit
        row and is not retried; the calculation result stays committed. That
        limitation is recorded in the evidence rather than hidden behind a
        swallowed exception.
        """
        from audit.models import AuditEvent

        def _exploding(**kwargs):
            raise RuntimeError("audit sink unavailable")

        monkeypatch.setattr(execution_mod_audit(), "emit", _exploding)

        audit_before = AuditEvent.objects.count()
        with pytest.raises(RuntimeError):
            with django_capture_on_commit_callbacks(execute=True):
                result = _run(world, "percentage_w_w")
                assert result.status == CalculationStatus.COMPLETE

        # The regulated result survived; only the audit row is missing.
        outcome = world["outcomes"]["percentage_w_w"]
        outcome.refresh_from_db()
        assert outcome.status == CalculationStatus.COMPLETE
        assert outcome.value == Decimal("25")
        assert AuditEvent.objects.count() == audit_before

    def test_a_successful_callback_writes_exactly_one_row(
        self, world, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            _run(world, "percentage_w_w")
        assert len(callbacks) == 1
        assert (
            AuditEvent.objects.filter(
                event_type=CALCULATED_EVENT,
                resource_id=str(world["responses"]["percentage_w_w"].public_id),
            ).count()
            == 1
        )


def execution_mod_audit():
    """The audit module the execution service resolves ``emit`` from."""
    from iig_checklist import audit as audit_mod

    return audit_mod


class TestDeferredBoundaries:
    """The stop conditions this run deliberately keeps."""

    def test_the_execution_module_never_writes_a_snapshot_itself(self):
        """Creation belongs to the governed service, never to this module."""
        source = inspect.getsource(execution_mod)
        for forbidden in (
            "AssessmentSnapshot.objects.create",
            "AssessmentSnapshot.objects.get",
            "AssessmentSnapshot.objects.all",
            ".first()",
            ".last()",
            ".latest(",
            ".earliest(",
        ):
            assert forbidden not in source, forbidden
        # The only snapshot query is the pk-scoped lock of a supplied row; the
        # created one is obtained from the service, never queried back.
        assert source.count("AssessmentSnapshot.objects") == 1
        assert "create_assessment_snapshot" in source

    def test_the_governed_snapshot_service_is_the_single_creation_path(self):
        """The stop condition of §6H is lifted, and asserted rather than assumed."""
        import inspect as _inspect

        from iid_assessment import services as snapshot_services
        from iid_assessment import views as assessment_views

        assert callable(snapshot_services.create_assessment_snapshot)
        # The API is an adapter over the same service -- no second path.
        view_source = _inspect.getsource(assessment_views)
        assert "create_assessment_snapshot" in view_source
        assert "AssessmentSnapshot.objects.create" not in view_source
        # And the service itself creates without any lookup or reuse. Prose is
        # stripped first: the module docstring *names* the prohibited calls to
        # record that they are prohibited, which is not a use of them.
        code = _executable_source(_inspect.getsource(snapshot_services))
        for forbidden in (".first()", ".last()", ".latest(", ".earliest("):
            assert forbidden not in code, forbidden
        # The row is constructed in memory, never fetched back.
        assert "AssessmentSnapshot.objects" not in code

    def test_snapshot_backed_execution_is_reachable_from_no_view_or_task(self):
        """Nothing but tests and future services calls the execution service."""
        from iig_checklist import serializers, urls, views

        for module in (views, serializers, urls):
            assert "calculation_execution" not in inspect.getsource(module), module

    def test_a_client_supplied_snapshot_identifier_is_never_accepted(self, world):
        """Only an exact server-held object is honoured (M4D3-SNO-011)."""
        snapshot = _snapshot(world)
        with pytest.raises((AttributeError, TypeError, ValueError)):
            execute_calculation_response(
                tenant=world["tenant"],
                execution=world["execution"],
                response=world["responses"]["percentage_of_iid_potency"],
                actor=world["user"],
                expected_version=1,
                snapshot_context=ResolutionContext(
                    assessment_snapshot=str(snapshot.public_id)
                ),
            )

    def test_duplicate_outcome_stays_an_internal_fail_closed_exception(self, world):
        """M4D3-OUT-005's ``duplicate_calculation_outcome`` belongs to the API layer.

        This service raises a typed internal exception and writes nothing; the
        governed external error code is mapped by the deferred serializer layer,
        which must never serialize the raw exception.
        """
        from iig_checklist.models import CalculationOutcome

        CalculationOutcome.objects.create(
            response=world["responses"]["percentage_w_w"],
            calculation_name="calculate_percentage_w_w",
            status=CalculationStatus.DATA_REQUIRED,
        )
        before = _snapshot_state(world)
        with pytest.raises(PlaceholderAmbiguous) as raised:
            _run(world, "percentage_w_w")
        assert "duplicate_calculation_outcome" not in str(raised.value)
        assert _snapshot_state(world) == before
