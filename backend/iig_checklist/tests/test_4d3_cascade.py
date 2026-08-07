"""Milestone 4D-3 -- governed cascade recalculation.

Real PostgreSQL-backed tests over the approved six-entry registry, which
already contains a genuine two-level cascade:

    Q_SUBJECT_COMPONENT  (user-required selector, no graph edge)
      |
      +-- recalculation_triggers --> percentage_w_w
      |                              daily_exposure          (Q_DAILY_EXPOSURE)
      |                              percentage_of_iid_potency
      |                              difference_from_iid_potency
      |
      +-- Q_DAILY_EXPOSURE, in turn, triggers and is a calculation_dependency of
              percentage_of_iid_mde
              difference_from_iid_mde

So one change to the subject-component selector must recalculate all six, in an
order that puts ``daily_exposure`` before the two MDE calculations that read its
outcome. That is the M4D3-RCL-001 point in one fixture: the selector creates no
graph edge at all, yet changing it must still cascade.

Synthetic registries are installed with ``monkeypatch`` only where the approved
six entries cannot express the case under test -- a cycle, an over-deep chain,
an over-wide fan-out. ``get_entry()`` resolves the module global on each call,
so the substitution is observed consistently and no committed definition is
mutated.
"""

from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal
from types import MappingProxyType

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from iid_assessment import calculations as engine
from iig_checklist import calculation_registry as registry_mod
from iig_checklist import cascade as cascade_mod
from iig_checklist.calculation_execution import StaleResponseVersion
from iig_checklist.cascade import (
    CascadeExecutionNotRecalculable,
    CascadeGraphInvalid,
    CascadeRecalculationResult,
    CascadeResponseNotInExecution,
    CascadeTarget,
    build_execution_graph,
    recalculate_dependents,
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

#: Every calculated question in the ``world`` fixture, by registry identifier.
ALL_KEYS = (
    "percentage_w_w",
    "daily_exposure",
    "percentage_of_iid_potency",
    "difference_from_iid_potency",
    "percentage_of_iid_mde",
    "difference_from_iid_mde",
)


# ---------------------------------------------------------------------------
# Persisted content
# ---------------------------------------------------------------------------


def _product(tenant, user, code="PROD-CAS-01"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant, product_code=code, proposed_product_name="Cascade Product",
        active_ingredient="Cascade Ingredient", dosage_form="tablet", route="oral",
        created_by=user,
    )


def _formulation(product, user, *, weight="1.000000", max_units="4.0000"):
    from formulations.models import FormulationVersion

    return FormulationVersion.objects.create(
        product=product, version_number=1, status="approved",
        total_dosage_unit_weight=Decimal(weight),
        total_dosage_unit_weight_unit="gram",
        maximum_dosage_units_per_day=Decimal(max_units), created_by=user,
    )


def _component(formulation, *, quantity="0.250000", order=1, ingredient=None,
               name="Cascade Excipient"):
    from formulations.models import FormulationComponent

    return FormulationComponent.objects.create(
        formulation_version=formulation, component_type="inactive",
        ingredient_name=name,
        resolved_ingredient_public_id=(
            ingredient.public_id if ingredient is not None else None
        ),
        quantity_per_dosage_unit=Decimal(quantity), quantity_unit="gram",
        display_order=order,
    )


def _iid_setup(*, potency="1.000000", mde="2.000000"):
    """One active FDA IID release with a CALCULABLE precedent for the excipient."""
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
        official_source_reference="ref", source_checksum_sha256="c" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )
    ingredient = IIDIngredient.objects.create(
        canonical_name="Cascade Excipient", normalized_name="CASCADE EXCIPIENT"
    )
    record = IIDPrecedentRecord.objects.create(
        release=release, ingredient=ingredient,
        ingredient_name_raw="Cascade Excipient",
        route_raw="ORAL", route_normalized=route,
        dosage_form_raw="TABLET", dosage_form_normalized=dosage_form,
        potency_amount=Decimal(potency), potency_unit_raw="G",
        potency_unit_normalized=gram,
        maximum_daily_exposure=Decimal(mde), mde_unit_raw="G",
        mde_unit_normalized=gram,
        raw_row_checksum="d" * 64,
        calculability_status=IIDCalculabilityStatus.CALCULABLE,
    )
    return {"release": release, "ingredient": ingredient, "record": record}


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


def _install(monkeypatch, mapping):
    monkeypatch.setattr(
        registry_mod, "CALCULATION_BINDING_REGISTRY", MappingProxyType(dict(mapping))
    )


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    """An execution carrying all six approved calculations and the selector."""
    from iig_checklist.models import (
        CalculationOutcome,
        ChecklistResponse,
        ChecklistVersion,
    )
    from iig_checklist.services import create_execution

    iid = _iid_setup()
    product = _product(tenant_a, user_a)
    formulation = _formulation(product, user_a)
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
    free_q = _question(
        section, "Q_FREE_TEXT", answer_type=AnswerType.SHORT_TEXT,
        classification=DataSourceClassification.USER_REQUIRED, order=8,
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
        "definition": tenant_definition, "execution": execution,
        "questions": questions, "responses": responses,
        "selector_q": selector_q, "selector_response": selector_response,
        "free_response": ChecklistResponse.objects.get(
            execution=execution, question=free_q
        ),
        "iid": iid,
        "outcomes": {
            key: CalculationOutcome.objects.get(response=r)
            for key, r in responses.items()
        },
    }


def _cascade(world, response=None, *, expected_version=None, actor=None,
             tenant=None, execution=None):
    """Run the governed cascade from the subject-component selector by default."""
    changed = response if response is not None else world["selector_response"]
    return recalculate_dependents(
        tenant=tenant if tenant is not None else world["tenant"],
        execution=execution if execution is not None else world["execution"],
        changed_response=changed,
        actor=actor or world["user"],
        expected_version=(
            changed.version if expected_version is None else expected_version
        ),
    )


def _sibling_execution(world, user, *, code="PROD-CAS-02"):
    """A second execution of the same checklist version.

    ``create_execution`` refuses a second active execution for one formulation
    version (``ExecutionAlreadyActive``), so this builds its own product and
    formulation carrying an equivalent component.
    """
    from iig_checklist.models import ChecklistResponse
    from iig_checklist.services import create_execution

    product = _product(world["tenant"], user, code=code)
    formulation = _formulation(product, user)
    component = _component(formulation, ingredient=world["iid"]["ingredient"])
    execution = create_execution(
        tenant=world["tenant"],
        checklist_version_public_id=str(world["version"].public_id),
        formulation_version_public_id=str(formulation.public_id),
        actor=user,
    )
    selector = ChecklistResponse.objects.get(
        execution=execution, question=world["selector_q"]
    )
    selector.raw_value = {"public_id": str(component.public_id)}
    selector.save(update_fields=["raw_value", "updated_at"])
    return execution, selector


def _outcome(world, key):
    from iig_checklist.models import CalculationOutcome

    return CalculationOutcome.objects.get(response=world["responses"][key])


def _code(world, key):
    return world["questions"][key].code


# ===========================================================================
# A. Dependency discovery
# ===========================================================================


class TestGraphDiscovery:
    def test_every_calculated_response_becomes_a_node(self, world):
        graph = build_execution_graph(world["execution"])
        assert len(graph.nodes) == len(ALL_KEYS)
        assert {node.question_code for node in graph.nodes.values()} == {
            _code(world, key) for key in ALL_KEYS
        }

    def test_node_identity_is_the_response_public_id(self, world):
        """M4D3-DEP-007 -- not the calculation function name."""
        graph = build_execution_graph(world["execution"])
        assert set(graph.nodes) == {
            str(world["responses"][key].public_id) for key in ALL_KEYS
        }

    def test_user_input_questions_are_not_nodes(self, world):
        """The selector drives the cascade but is not part of the graph."""
        graph = build_execution_graph(world["execution"])
        codes = {node.question_code for node in graph.nodes.values()}
        assert registry_mod.Q_SUBJECT_COMPONENT not in codes
        assert "Q_FREE_TEXT" not in codes

    def test_edges_come_only_from_calculation_dependencies(self, world):
        graph = build_execution_graph(world["execution"])
        by_code = {n.question_code: node_id for node_id, n in graph.nodes.items()}
        exposure = by_code[registry_mod.Q_DAILY_EXPOSURE]
        assert graph.edges[by_code["Q_PCT_MDE"]] == (exposure,)
        assert graph.edges[by_code["Q_DIF_MDE"]] == (exposure,)
        assert graph.edges[by_code["Q_PCT_WW"]] == ()

    def test_discovery_is_read_only(self, world):
        """No transaction, no lock, no write -- a graph read is free of side effects."""
        from audit.models import AuditEvent

        audit_before = AuditEvent.objects.count()
        with CaptureQueriesContext(connection) as ctx:
            build_execution_graph(world["execution"])
        verbs = {q["sql"].lstrip().split()[0].upper() for q in ctx.captured_queries}
        assert verbs == {"SELECT"}
        assert not any("FOR UPDATE" in q["sql"].upper() for q in ctx.captured_queries)
        assert AuditEvent.objects.count() == audit_before

    def test_another_executions_responses_never_enter_the_graph(self, world, user_a):
        """M4D3-DAG-009 -- the graph is scoped to one execution's responses."""
        other, _ = _sibling_execution(world, user_a)
        graph = build_execution_graph(world["execution"])
        other_graph = build_execution_graph(other)
        assert set(graph.nodes).isdisjoint(set(other_graph.nodes))
        assert len(other_graph.nodes) == len(ALL_KEYS)


# ===========================================================================
# B. Governed graph faults -- all rejected, none silently repaired
# ===========================================================================


def _synthetic_world(world, monkeypatch, entries, codes):
    """Rebind the execution's calculated questions onto a synthetic registry.

    ``entries`` is the replacement registry; ``codes`` maps each approved key in
    the fixture to the question code and identifier it should take on.
    """
    _install(monkeypatch, entries)
    for key, (code, identifier) in codes.items():
        question = world["questions"][key]
        question.code = code
        question.calculation_binding_identifier = identifier
        question.save(
            update_fields=[
                "code", "calculation_binding_identifier", "updated_at",
            ]
        )
    for key in set(world["questions"]) - set(codes):
        response = world["responses"][key]
        from iig_checklist.models import CalculationOutcome

        CalculationOutcome.objects.filter(response=response).delete()
        response.delete()


class TestGraphFaults:
    def test_a_cycle_is_rejected(self, world, monkeypatch):
        """M4D3-DAG-005 -- a cycle is a governed configuration error."""
        _synthetic_world(
            world, monkeypatch,
            {
                "cyc_a": _entry(calculation_dependencies=("Q_CYC_B",)),
                "cyc_b": _entry(calculation_dependencies=("Q_CYC_A",)),
            },
            {
                "percentage_w_w": ("Q_CYC_A", "cyc_a"),
                "daily_exposure": ("Q_CYC_B", "cyc_b"),
            },
        )
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        assert caught.value.error_code == "DEPENDENCY_CYCLE"
        assert set(caught.value.question_codes) == {"Q_CYC_A", "Q_CYC_B"}

    def test_a_self_dependency_is_a_cycle(self, world, monkeypatch):
        _synthetic_world(
            world, monkeypatch,
            {"self_dep": _entry(calculation_dependencies=("Q_SELF",))},
            {"percentage_w_w": ("Q_SELF", "self_dep")},
        )
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        assert caught.value.error_code == "DEPENDENCY_CYCLE"

    def test_a_dependency_outside_the_version_is_rejected(self, world, monkeypatch):
        """M4D3-DAG-009 -- an edge may not point at a code this version lacks."""
        _synthetic_world(
            world, monkeypatch,
            {"needs_absent": _entry(calculation_dependencies=("Q_NOT_HERE",))},
            {"percentage_w_w": ("Q_PRESENT", "needs_absent")},
        )
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        assert caught.value.error_code == "UNKNOWN_DEPENDENCY_CODE"

    def test_depth_beyond_the_limit_is_rejected(self, world, monkeypatch):
        """M4D3-DAG-003 -- six chained nodes exceed the depth limit of five."""
        assert registry_mod.CALCULATION_MAX_DEPENDENCY_DEPTH == 5
        chain = list(ALL_KEYS)
        entries = {}
        codes = {}
        previous = None
        for index, key in enumerate(chain):
            identifier = f"chain_{index}"
            entries[identifier] = _entry(
                calculation_dependencies=() if previous is None else (previous,)
            )
            code = f"Q_CHAIN_{index}"
            codes[key] = (code, identifier)
            previous = code
        _synthetic_world(world, monkeypatch, entries, codes)
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        assert caught.value.error_code == "DEPENDENCY_DEPTH_EXCEEDED"

    def test_an_unapproved_binding_is_rejected_not_skipped(self, world):
        """Dropping the node would leave the rest of the graph silently stale."""
        question = world["questions"]["percentage_w_w"]
        question.calculation_binding_identifier = "not_a_registered_calculation"
        question.save(
            update_fields=["calculation_binding_identifier", "updated_at"]
        )
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        assert caught.value.error_code == "UNKNOWN_REGISTRY_IDENTIFIER"

    def test_a_graph_fault_aborts_the_cascade_before_any_write(self, world):
        """M4D3-RBD-008 -- rejected, and nothing partially recalculated."""
        from audit.models import AuditEvent

        question = world["questions"]["percentage_of_iid_mde"]
        question.calculation_binding_identifier = "not_a_registered_calculation"
        question.save(
            update_fields=["calculation_binding_identifier", "updated_at"]
        )
        audit_before = AuditEvent.objects.count()
        with pytest.raises(CascadeGraphInvalid):
            _cascade(world)
        for key in ALL_KEYS:
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED
            assert _outcome(world, key).value is None
        assert AuditEvent.objects.count() == audit_before

    def test_the_error_carries_no_database_id(self, world):
        question = world["questions"]["percentage_w_w"]
        question.calculation_binding_identifier = "not_a_registered_calculation"
        question.save(
            update_fields=["calculation_binding_identifier", "updated_at"]
        )
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        text = str(caught.value) + repr(caught.value.question_codes)
        assert str(world["responses"]["percentage_w_w"].pk) not in text
        assert "SELECT" not in text


# ===========================================================================
# C. Trigger identification -- M4D3-RCL-001 / M4D3-RCL-007
# ===========================================================================


class TestTriggerIdentification:
    def test_the_selector_cascades_to_every_calculation(self, world):
        """M4D3-RCL-001 -- the selector has no graph edge, yet drives all six."""
        graph = build_execution_graph(world["execution"])
        selector = registry_mod.Q_SUBJECT_COMPONENT
        assert selector not in {n.question_code for n in graph.nodes.values()}

        result = _cascade(world)
        assert result.triggered is True
        assert set(result.question_codes) == {_code(world, key) for key in ALL_KEYS}

    def test_a_non_trigger_response_recalculates_nothing(self, world):
        """M4D3-RCL-007 -- no recalculation, no version change, no audit."""
        from audit.models import AuditEvent

        free = world["free_response"]
        audit_before = AuditEvent.objects.count()
        versions_before = {
            key: world["responses"][key].version for key in ALL_KEYS
        }

        result = _cascade(world, free)
        assert result.triggered is False
        assert result.targets == ()
        assert result.recalculated_count == 0
        assert result.origin_question_code == "Q_FREE_TEXT"

        for key in ALL_KEYS:
            response = world["responses"][key]
            response.refresh_from_db()
            assert response.version == versions_before[key]
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED
        assert AuditEvent.objects.count() == audit_before

    def test_a_non_trigger_response_writes_nothing_at_all(self, world):
        with CaptureQueriesContext(connection) as ctx:
            _cascade(world, world["free_response"])
        verbs = {q["sql"].lstrip().split()[0].upper() for q in ctx.captured_queries}
        assert verbs <= {"SELECT", "SAVEPOINT", "RELEASE", "BEGIN", "COMMIT"}
        assert "UPDATE" not in verbs
        assert "INSERT" not in verbs

    def test_a_trigger_only_reaches_its_declared_consumers(self, world):
        """Changing the daily-exposure response reaches the MDE pair, not all six."""
        result = _cascade(world, world["responses"]["daily_exposure"])
        assert result.triggered is True
        assert set(result.question_codes) == {"Q_PCT_MDE", "Q_DIF_MDE"}

    def test_downstream_expansion_follows_calculation_dependencies(self, world):
        """The two MDE nodes are reached through the graph, not the trigger set."""
        mde = registry_mod.CALCULATION_BINDING_REGISTRY["percentage_of_iid_mde"]
        assert mde.calculation_dependencies == (registry_mod.Q_DAILY_EXPOSURE,)
        assert registry_mod.Q_SUBJECT_COMPONENT not in mde.recalculation_triggers

        result = _cascade(world)
        assert "Q_PCT_MDE" in result.question_codes


# ===========================================================================
# D. Ordering -- M4D3-RCL-002 / M4D3-DAG-006
# ===========================================================================


class TestOrdering:
    def test_upstream_runs_before_its_dependants(self, world):
        result = _cascade(world)
        codes = list(result.question_codes)
        assert codes.index(registry_mod.Q_DAILY_EXPOSURE) < codes.index("Q_PCT_MDE")
        assert codes.index(registry_mod.Q_DAILY_EXPOSURE) < codes.index("Q_DIF_MDE")

    def test_independent_nodes_are_ordered_by_question_code(self, world):
        """M4D3-DAG-006 -- the tie-break is the governed code, ascending."""
        result = _cascade(world)
        independent = [
            code
            for code in result.question_codes
            if code not in {"Q_PCT_MDE", "Q_DIF_MDE"}
        ]
        assert independent == sorted(independent)

    def test_the_order_is_stable_across_runs(self, world):
        first = _cascade(world).question_codes
        second = _cascade(world).question_codes
        assert first == second

    def test_the_order_does_not_depend_on_response_public_ids(self, world, user_a):
        """M4D3-DAG-006 -- the tie-break is the question code, not the node id.

        A second execution of the same checklist version carries the same six
        question codes on six different response UUIDs. If the order keyed on
        node identity it would differ between the two; keyed on the governed
        code it cannot.
        """
        other, selector = _sibling_execution(world, user_a)
        assert {str(r.public_id) for r in world["responses"].values()}.isdisjoint(
            set(build_execution_graph(other).nodes)
        )

        first = _cascade(world).question_codes
        second = _cascade(world, selector, execution=other).question_codes
        assert first == second

    def test_a_dependant_sees_the_upstream_value_written_this_cascade(self, world):
        """The point of ordering: Q_PCT_MDE consumes the fresh daily exposure."""
        result = _cascade(world)
        assert result.triggered
        exposure = _outcome(world, "daily_exposure")
        assert exposure.status == CalculationStatus.COMPLETE
        assert exposure.value == Decimal("1.000000")

        mde = _outcome(world, "percentage_of_iid_mde")
        assert mde.status == CalculationStatus.COMPLETE
        # 1 g of a 2 g precedent maximum daily exposure.
        assert mde.value == Decimal("50")
        assert mde.input_provenance["upstream_outcome_public_ids"] == [
            str(exposure.public_id)
        ]


# ===========================================================================
# E. The governed writer stays the only writer -- M4D3-SVC
# ===========================================================================


class TestCascadeIsNotASecondWriter:
    def test_every_target_goes_through_the_execution_service(self, world,
                                                             monkeypatch):
        from iig_checklist import calculation_execution as exec_mod

        seen = []
        original = exec_mod.execute_calculation_response

        def recording(**kwargs):
            seen.append(str(kwargs["response"].public_id))
            return original(**kwargs)

        monkeypatch.setattr(cascade_mod, "execute_calculation_response", recording)
        result = _cascade(world)
        assert seen == list(result.recalculated_response_public_ids)

    def test_the_module_never_touches_the_engine_or_the_outcome_fields(self):
        """It must not compute, translate, build provenance or emit audit.

        Checked against the parsed AST rather than the raw text: the module
        documents at length what it does not do, and a substring sweep over its
        own prose would flag the documentation instead of the code.
        """
        import ast

        tree = ast.parse(inspect.getsource(cascade_mod))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.alias):
                names.add(node.name.rsplit(".", 1)[-1])
                if node.asname:
                    names.add(node.asname)

        forbidden = {
            # the engine and its translation layer
            "calculate_percentage_w_w", "calculate_daily_exposure",
            "calculate_percentage_of_potency", "calculate_difference_from_potency",
            "calculate_percentage_of_mde", "calculate_difference_from_mde",
            "translate_result", "engine",
            # outcome persistence and provenance
            "full_clean", "input_provenance", "inputs", "generated_at",
            "rounding_rule", "formula_version", "calculation_name",
            # snapshot creation and audit dispatch
            "create_assessment_snapshot", "AssessmentSnapshot",
            "on_commit", "emit", "IigChecklistEvent",
        }
        assert names.isdisjoint(forbidden), sorted(names & forbidden)

    def test_the_result_leaks_no_orm_object(self, world):
        result = _cascade(world)
        assert isinstance(result, CascadeRecalculationResult)
        for target in result.targets:
            assert isinstance(target, CascadeTarget)
            for field in dataclasses.fields(target):
                value = getattr(target, field.name)
                assert isinstance(value, str | bool), field.name

    def test_the_result_is_immutable(self, world):
        result = _cascade(world)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.triggered = False
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.targets[0].status = "tampered"
        assert isinstance(result.targets, tuple)


# ===========================================================================
# F. Outcome persistence -- M4D3-RCL-003
# ===========================================================================


class TestOutcomePersistence:
    def test_outcome_rows_are_updated_in_place(self, world):
        """M4D3-RCL-003 -- no new row, no delete-and-recreate."""
        from iig_checklist.models import CalculationOutcome

        before = {
            key: (world["outcomes"][key].pk, world["outcomes"][key].public_id)
            for key in ALL_KEYS
        }
        total_before = CalculationOutcome.objects.count()

        _cascade(world)

        assert CalculationOutcome.objects.count() == total_before
        for key in ALL_KEYS:
            outcome = _outcome(world, key)
            assert (outcome.pk, outcome.public_id) == before[key]

    def test_a_second_cascade_reuses_the_same_rows(self, world):
        _cascade(world)
        first = {key: _outcome(world, key).public_id for key in ALL_KEYS}
        _cascade(world)
        second = {key: _outcome(world, key).public_id for key in ALL_KEYS}
        assert first == second

    def test_recalculated_responses_do_not_change_version(self, world):
        """M4D3-MDL-006 -- recalculation writes outcomes, never response versions."""
        before = {}
        for key in ALL_KEYS:
            world["responses"][key].refresh_from_db()
            before[key] = world["responses"][key].version

        _cascade(world)

        for key in ALL_KEYS:
            world["responses"][key].refresh_from_db()
            assert world["responses"][key].version == before[key]

    def test_a_changed_input_changes_the_downstream_value(self, world):
        """The end-to-end point of the cascade, as a value assertion."""
        _cascade(world)
        assert _outcome(world, "percentage_w_w").value == Decimal("25")

        component = world["component"]
        component.quantity_per_dosage_unit = Decimal("0.500000")
        component.save(update_fields=["quantity_per_dosage_unit", "updated_at"])

        _cascade(world)
        assert _outcome(world, "percentage_w_w").value == Decimal("50")
        assert _outcome(world, "daily_exposure").value == Decimal("2.000000")
        assert _outcome(world, "percentage_of_iid_mde").value == Decimal("100")


# ===========================================================================
# G. Audit -- M4D3-RCL-004 and post-commit dispatch
# ===========================================================================


class TestAudit:
    def test_one_event_per_recalculated_target(
        self, world, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            result = _cascade(world)

        events = AuditEvent.objects.filter(event_type=CALCULATED_EVENT)
        assert events.count() == result.recalculated_count == len(ALL_KEYS)
        assert {e.resource_id for e in events} == set(
            result.recalculated_response_public_ids
        )

    def test_no_cascade_summary_event_is_invented(
        self, world, django_capture_on_commit_callbacks
    ):
        """Only the per-calculation event the specification defines is emitted.

        The snapshot service's own ``iid_assessment.snapshot.created`` events are
        expected -- one governed snapshot per governed calculation event
        (M4D3-SNO-006). What must not appear is a cascade-level summary event,
        for which no approved clause or event constant exists.
        """
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            _cascade(world)
        emitted = set(AuditEvent.objects.values_list("event_type", flat=True))
        assert {e for e in emitted if e.startswith("iig_checklist.")} == {
            CALCULATED_EVENT
        }
        assert not any("cascade" in e or "recalc" in e for e in emitted)

    def test_an_unchanged_recalculation_emits_no_audit(
        self, world, django_capture_on_commit_callbacks
    ):
        """M4D3-RCL-004 -- status, value, reason_code and generated_at unchanged."""
        from audit.models import AuditEvent

        # No FDA precedent: the potency and MDE calculations settle on a stable
        # DATA_REQUIRED outcome whose generated_at stays None, so a second run
        # genuinely changes none of the four governed fields.
        world["iid"]["record"].delete()

        with django_capture_on_commit_callbacks(execute=True):
            first = _cascade(world)
        assert first.audited_count == first.recalculated_count
        after_first = AuditEvent.objects.filter(event_type=CALCULATED_EVENT).count()

        with django_capture_on_commit_callbacks(execute=True):
            second = _cascade(world)

        suppressed = [t for t in second.targets if t.audit_suppressed]
        assert suppressed, second.targets
        emitted = AuditEvent.objects.filter(event_type=CALCULATED_EVENT).count()
        assert emitted - after_first == second.audited_count
        assert emitted - after_first < second.recalculated_count

    def test_a_changed_recalculation_still_audits(
        self, world, django_capture_on_commit_callbacks
    ):
        """The suppression must be conditional, not a blanket cascade silence."""
        from audit.models import AuditEvent

        world["iid"]["record"].delete()
        with django_capture_on_commit_callbacks(execute=True):
            _cascade(world)
        baseline = AuditEvent.objects.filter(event_type=CALCULATED_EVENT).count()

        component = world["component"]
        component.quantity_per_dosage_unit = Decimal("0.500000")
        component.save(update_fields=["quantity_per_dosage_unit", "updated_at"])

        with django_capture_on_commit_callbacks(execute=True):
            result = _cascade(world)

        changed = [t for t in result.targets if not t.audit_suppressed]
        assert changed
        assert (
            AuditEvent.objects.filter(event_type=CALCULATED_EVENT).count() - baseline
            == len(changed)
        )

    def test_direct_execution_always_audits(
        self, world, django_capture_on_commit_callbacks
    ):
        """The M4D3-RCL-004 hook is opt-in; single-response behaviour is unchanged."""
        from audit.models import AuditEvent
        from iig_checklist.calculation_execution import execute_calculation_response

        world["iid"]["record"].delete()
        response = world["responses"]["percentage_of_iid_potency"]
        for _ in range(2):
            response.refresh_from_db()
            with django_capture_on_commit_callbacks(execute=True):
                result = execute_calculation_response(
                    tenant=world["tenant"], execution=world["execution"],
                    response=response, actor=world["user"],
                    expected_version=response.version,
                )
            assert result.audit_suppressed is False
        assert (
            AuditEvent.objects.filter(
                event_type=CALCULATED_EVENT, resource_id=str(response.public_id)
            ).count()
            == 2
        )

    def test_a_rolled_back_cascade_emits_no_audit(
        self, world, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        before = AuditEvent.objects.count()
        with (
            pytest.raises(StaleResponseVersion),
            django_capture_on_commit_callbacks(execute=True),
        ):
            _cascade(world, expected_version=9999)
        assert AuditEvent.objects.count() == before


# ===========================================================================
# H. Atomicity -- M4D3-RCL-006 / M4D3-RBD-008
# ===========================================================================


class TestAtomicity:
    def test_a_failure_part_way_through_discards_the_whole_cascade(
        self, world, monkeypatch
    ):
        """One transaction: an outcome written before the failure must not survive."""
        from iig_checklist.calculation_execution import CalculationEngineFailure

        calls = {"n": 0}
        original = engine.calculate_percentage_of_potency

        def exploding(**kwargs):
            calls["n"] += 1
            raise RuntimeError("engine fault")

        monkeypatch.setattr(engine, "calculate_percentage_of_potency", exploding)
        monkeypatch.setattr(
            registry_mod,
            "CALCULATION_BINDING_REGISTRY",
            MappingProxyType(
                {
                    **dict(registry_mod.CALCULATION_BINDING_REGISTRY),
                    "percentage_of_iid_potency": dataclasses.replace(
                        registry_mod.CALCULATION_BINDING_REGISTRY[
                            "percentage_of_iid_potency"
                        ],
                        function=exploding,
                    ),
                }
            ),
        )

        with pytest.raises(CalculationEngineFailure):
            _cascade(world)

        assert calls["n"] >= 1
        # percentage_w_w sorts before Q_PCT_POT and would have been written first.
        for key in ALL_KEYS:
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED
            assert _outcome(world, key).value is None
        assert original is not exploding

    def test_a_rolled_back_cascade_leaves_no_snapshot(self, world, monkeypatch):
        from iid_assessment.models import AssessmentSnapshot
        from iig_checklist.calculation_execution import CalculationEngineFailure

        def exploding(**kwargs):
            raise RuntimeError("engine fault")

        monkeypatch.setattr(
            registry_mod,
            "CALCULATION_BINDING_REGISTRY",
            MappingProxyType(
                {
                    **dict(registry_mod.CALCULATION_BINDING_REGISTRY),
                    "difference_from_iid_mde": dataclasses.replace(
                        registry_mod.CALCULATION_BINDING_REGISTRY[
                            "difference_from_iid_mde"
                        ],
                        function=exploding,
                    ),
                }
            ),
        )
        before = AssessmentSnapshot.objects.count()
        with pytest.raises(CalculationEngineFailure):
            _cascade(world)
        assert AssessmentSnapshot.objects.count() == before

    def test_a_stale_expected_version_writes_nothing(self, world):
        """M4D3-RBD-008 names a stale expected_version as a full-rollback failure."""
        with pytest.raises(StaleResponseVersion):
            _cascade(world, expected_version=9999)
        for key in ALL_KEYS:
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED

    def test_the_expected_version_is_checked_against_the_committed_row(self, world):
        from iig_checklist.models import ChecklistResponse

        selector = world["selector_response"]
        stale_version = selector.version
        ChecklistResponse.objects.filter(pk=selector.pk).update(
            version=stale_version + 1
        )
        with pytest.raises(StaleResponseVersion):
            _cascade(world, expected_version=stale_version)


# ===========================================================================
# I. Snapshots -- M4D3-SNO-006
# ===========================================================================


class TestSnapshots:
    def test_each_snapshot_backed_target_gets_its_own_new_snapshot(self, world):
        """M4D3-SNO-006 -- one governed snapshot per governed calculation event."""
        from iid_assessment.models import AssessmentSnapshot

        result = _cascade(world)
        snapshot_backed = [
            key
            for key in ALL_KEYS
            if registry_mod.CALCULATION_BINDING_REGISTRY[key].input_resolvers
            and any(
                d.get("source") == registry_mod.SOURCE_ASSESSMENT_SNAPSHOT
                for d in registry_mod.CALCULATION_BINDING_REGISTRY[
                    key
                ].input_resolvers.values()
            )
        ]
        assert snapshot_backed
        assert result.triggered
        assert AssessmentSnapshot.objects.count() == len(snapshot_backed)

    def test_a_second_cascade_creates_a_second_generation_of_snapshots(self, world):
        from iid_assessment.models import AssessmentSnapshot

        _cascade(world)
        first = set(AssessmentSnapshot.objects.values_list("public_id", flat=True))
        _cascade(world)
        second = set(AssessmentSnapshot.objects.values_list("public_id", flat=True))
        assert first < second
        assert len(second) == 2 * len(first)

    def test_outcomes_reference_the_snapshot_created_in_their_own_cascade(self, world):
        from iid_assessment.models import AssessmentSnapshot

        _cascade(world)
        first = {
            str(public_id)
            for public_id in AssessmentSnapshot.objects.values_list(
                "public_id", flat=True
            )
        }
        _cascade(world)
        referenced = {
            _outcome(world, key).source_assessment_snapshot_public_id
            for key in ALL_KEYS
        } - {None, ""}
        assert referenced
        assert referenced.isdisjoint(first)


# ===========================================================================
# J. Execution state -- M4D3-RCL-005
# ===========================================================================


class TestExecutionState:
    @pytest.mark.parametrize(
        "status",
        [
            ExecutionStatus.SUBMITTED_FOR_REVIEW,
            ExecutionStatus.APPROVED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.SUPERSEDED,
        ],
    )
    def test_non_recalculable_statuses_are_refused(self, world, status):
        from iig_checklist.models import ChecklistExecution

        ChecklistExecution.objects.filter(pk=world["execution"].pk).update(
            status=status
        )
        with pytest.raises(CascadeExecutionNotRecalculable):
            _cascade(world)
        for key in ALL_KEYS:
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED

    @pytest.mark.parametrize(
        "status", [ExecutionStatus.DRAFT, ExecutionStatus.RETURNED]
    )
    def test_recalculable_statuses_proceed(self, world, status):
        from iig_checklist.models import ChecklistExecution

        ChecklistExecution.objects.filter(pk=world["execution"].pk).update(
            status=status
        )
        result = _cascade(world)
        assert result.triggered is True

    def test_the_allow_list_covers_every_declared_status(self):
        """A status added later is excluded until it is deliberately considered."""
        from iig_checklist.enums import TERMINAL_EXECUTION_STATUSES

        allowed = cascade_mod.RECALCULABLE_EXECUTION_STATUSES
        assert allowed.isdisjoint(TERMINAL_EXECUTION_STATUSES)
        assert ExecutionStatus.SUBMITTED_FOR_REVIEW not in allowed
        assert allowed <= set(ExecutionStatus.values)

    def test_the_status_is_read_under_the_lock(self, world):
        """Checked against the committed row, not the caller's in-memory copy."""
        from iig_checklist.models import ChecklistExecution

        stale = world["execution"]
        assert stale.status == ExecutionStatus.DRAFT
        ChecklistExecution.objects.filter(pk=stale.pk).update(
            status=ExecutionStatus.APPROVED
        )
        assert stale.status == ExecutionStatus.DRAFT  # the copy is genuinely stale
        with pytest.raises(CascadeExecutionNotRecalculable):
            _cascade(world)


# ===========================================================================
# K. Isolation
# ===========================================================================


class TestIsolation:
    def test_a_foreign_tenant_is_refused(self, world, tenant_b):
        with pytest.raises(CascadeResponseNotInExecution):
            _cascade(world, tenant=tenant_b)

    def test_a_response_from_another_execution_is_refused(self, world, user_a):
        _, foreign = _sibling_execution(world, user_a)
        with pytest.raises(CascadeResponseNotInExecution):
            _cascade(world, foreign)

    def test_a_cascade_never_touches_another_execution(self, world, user_a):
        from iig_checklist.models import CalculationOutcome, ChecklistResponse

        other, _ = _sibling_execution(world, user_a)
        other_outcomes = {
            o.pk: (o.status, o.value, o.updated_at)
            for o in CalculationOutcome.objects.filter(
                response__in=ChecklistResponse.objects.filter(execution=other)
            )
        }
        assert other_outcomes

        _cascade(world)

        for pk, before in other_outcomes.items():
            after = CalculationOutcome.objects.get(pk=pk)
            assert (after.status, after.value, after.updated_at) == before


# ===========================================================================
# L. Lock order -- M4D3-TXN-001 / Part 17
# ===========================================================================


class TestLockOrder:
    @staticmethod
    def _locking(ctx):
        return [
            q["sql"] for q in ctx.captured_queries if "FOR UPDATE" in q["sql"].upper()
        ]

    def test_the_execution_is_locked_first(self, world):
        with CaptureQueriesContext(connection) as ctx:
            _cascade(world)
        first = self._locking(ctx)[0].lower()
        assert "checklistexecution" in first

    def test_every_multi_row_lock_orders_by_ascending_primary_key(self, world):
        with CaptureQueriesContext(connection) as ctx:
            _cascade(world)
        for sql in self._locking(ctx):
            if " in (" in sql.lower():
                assert '."id" asc' in sql.lower(), sql
                assert " desc" not in sql.lower(), sql

    def test_responses_are_locked_before_outcomes(self, world):
        with CaptureQueriesContext(connection) as ctx:
            _cascade(world)
        tables = [
            "checklistresponse" if "checklistresponse" in sql.lower()
            else "calculationoutcome" if "calculationoutcome" in sql.lower()
            else "other"
            for sql in self._locking(ctx)
        ]
        first_outcome = tables.index("calculationoutcome")
        assert "checklistresponse" in tables[:first_outcome]

    def test_the_whole_affected_set_is_locked_before_the_first_recalculation(
        self, world, monkeypatch
    ):
        """No target is written before every affected row is already held.

        ``execute_calculation_response`` takes its own batched locks per target,
        so this looks only at the queries issued *before* the first target call
        and requires the cascade's own two batched locks -- responses, then
        outcomes -- to cover the full affected set by then.
        """
        marks: list[int] = []
        original = cascade_mod.execute_calculation_response
        holder = {}

        def recording(**kwargs):
            marks.append(len(connection.queries_log) - holder["initial"])
            return original(**kwargs)

        monkeypatch.setattr(cascade_mod, "execute_calculation_response", recording)
        with CaptureQueriesContext(connection) as ctx:
            holder["initial"] = ctx.initial_queries
            result = _cascade(world)

        assert marks and result.recalculated_count == len(ALL_KEYS)
        before_first_target = [q["sql"] for q in ctx.captured_queries[: marks[0]]]
        response_pks = {
            world["responses"][key].pk for key in ALL_KEYS
        }

        response_locks = [
            sql
            for sql in before_first_target
            if "FOR UPDATE" in sql.upper()
            and "checklistresponse" in sql.lower()
            and " IN (" in sql.upper()
        ]
        outcome_locks = [
            sql
            for sql in before_first_target
            if "FOR UPDATE" in sql.upper() and "calculationoutcome" in sql.lower()
        ]
        assert response_locks, before_first_target
        assert outcome_locks, before_first_target
        # Every affected response id appears in the batched lock, and the
        # outcome lock follows it.
        assert all(str(pk) in response_locks[-1] for pk in response_pks)
        assert before_first_target.index(
            response_locks[-1]
        ) < before_first_target.index(outcome_locks[-1])


# ===========================================================================
# M. Result contract
# ===========================================================================


class TestResultContract:
    def test_the_result_identifies_the_origin(self, world):
        result = _cascade(world)
        assert result.execution_public_id == str(world["execution"].public_id)
        assert result.origin_response_public_id == str(
            world["selector_response"].public_id
        )
        assert result.origin_question_code == registry_mod.Q_SUBJECT_COMPONENT

    def test_targets_carry_governed_identities_only(self, world):
        result = _cascade(world)
        for target in result.targets:
            assert target.registry_identifier in (
                registry_mod.CALCULATION_BINDING_REGISTRY
            )
            assert target.status in set(CalculationStatus.values)
            assert len(target.response_public_id) == 36
            assert len(target.outcome_public_id) == 36

    def test_the_counts_agree_with_the_targets(self, world):
        result = _cascade(world)
        assert result.recalculated_count == len(result.targets)
        assert len(result.recalculated_response_public_ids) == len(result.targets)
        assert result.audited_count <= result.recalculated_count

    def test_target_order_matches_the_recalculation_order(self, world):
        result = _cascade(world)
        graph = build_execution_graph(world["execution"])
        expected = [
            node_id
            for node_id in graph.order
            if node_id in set(result.recalculated_response_public_ids)
        ]
        assert list(result.recalculated_response_public_ids) == expected
