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
        tenant=tenant,
        product_code=code,
        proposed_product_name="Cascade Product",
        active_ingredient="Cascade Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )


def _formulation(product, user, *, weight="1.000000", max_units="4.0000"):
    from formulations.models import FormulationVersion

    return FormulationVersion.objects.create(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight=Decimal(weight),
        total_dosage_unit_weight_unit="gram",
        maximum_dosage_units_per_day=Decimal(max_units),
        created_by=user,
    )


def _component(
    formulation, *, quantity="0.250000", order=1, ingredient=None, name="Cascade Excipient"
):
    from formulations.models import FormulationComponent

    return FormulationComponent.objects.create(
        formulation_version=formulation,
        component_type="inactive",
        ingredient_name=name,
        resolved_ingredient_public_id=(ingredient.public_id if ingredient is not None else None),
        quantity_per_dosage_unit=Decimal(quantity),
        quantity_unit="gram",
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

    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    gram = ControlledUnit.objects.create(code="gram", symbol="G", dimension="mass", active=True)
    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="c" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )
    ingredient = IIDIngredient.objects.create(
        canonical_name="Cascade Excipient", normalized_name="CASCADE EXCIPIENT"
    )
    record = IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="Cascade Excipient",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal(potency),
        potency_unit_raw="G",
        potency_unit_normalized=gram,
        maximum_daily_exposure=Decimal(mde),
        mde_unit_raw="G",
        mde_unit_normalized=gram,
        raw_row_checksum="d" * 64,
        calculability_status=IIDCalculabilityStatus.CALCULABLE,
    )
    return {"release": release, "ingredient": ingredient, "record": record}


def _section(version, code="S1", order=1):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=version,
        code=code,
        title=f"Section {code}",
        display_order=order,
        criticality=Criticality.MEDIUM,
    )


def _question(section, code, *, answer_type, classification, binding="", order=1):
    from iig_checklist.models import ChecklistQuestion

    return ChecklistQuestion.objects.create(
        section=section,
        code=code,
        question_text=f"Q {code}",
        display_order=order,
        answer_type=answer_type,
        data_source_classification=classification,
        calculation_binding_identifier=binding,
        criticality=Criticality.LOW,
    )


def _calculated(section, code, identifier, *, order=1):
    return _question(
        section,
        code,
        answer_type=AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding=identifier,
        order=order,
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
        definition=tenant_definition,
        version_number=1,
        status="active",
        created_by=user_a,
    )
    section = _section(version)
    selector_q = _question(
        section,
        registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED,
        order=1,
    )
    free_q = _question(
        section,
        "Q_FREE_TEXT",
        answer_type=AnswerType.SHORT_TEXT,
        classification=DataSourceClassification.USER_REQUIRED,
        order=8,
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
    selector_response = ChecklistResponse.objects.get(execution=execution, question=selector_q)
    selector_response.raw_value = {"public_id": str(component.public_id)}
    selector_response.save(update_fields=["raw_value", "updated_at"])

    responses = {
        key: ChecklistResponse.objects.get(execution=execution, question=q)
        for key, q in questions.items()
    }
    return {
        "tenant": tenant_a,
        "user": user_a,
        "formulation": formulation,
        "component": component,
        "version": version,
        "section": section,
        "definition": tenant_definition,
        "execution": execution,
        "questions": questions,
        "responses": responses,
        "selector_q": selector_q,
        "selector_response": selector_response,
        "free_response": ChecklistResponse.objects.get(execution=execution, question=free_q),
        "iid": iid,
        "outcomes": {
            key: CalculationOutcome.objects.get(response=r) for key, r in responses.items()
        },
    }


def _cascade(
    world, response=None, *, expected_version=None, actor=None, tenant=None, execution=None
):
    """Run the governed cascade from the subject-component selector by default."""
    changed = response if response is not None else world["selector_response"]
    return recalculate_dependents(
        tenant=tenant if tenant is not None else world["tenant"],
        execution=execution if execution is not None else world["execution"],
        changed_response=changed,
        actor=actor or world["user"],
        expected_version=(changed.version if expected_version is None else expected_version),
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
    selector = ChecklistResponse.objects.get(execution=execution, question=world["selector_q"])
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
        assert set(graph.nodes) == {str(world["responses"][key].public_id) for key in ALL_KEYS}

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

    def test_an_execution_with_no_calculations_yields_an_empty_graph(self, world):
        """A legitimate state: a checklist version that calculates nothing."""
        from iig_checklist.models import CalculationOutcome

        for key in ALL_KEYS:
            response = world["responses"][key]
            CalculationOutcome.objects.filter(response=response).delete()
            response.delete()

        graph = build_execution_graph(world["execution"])
        assert dict(graph.nodes) == {}
        assert graph.order == ()

        result = _cascade(world)
        assert result.triggered is False
        assert result.targets == ()

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
                "code",
                "calculation_binding_identifier",
                "updated_at",
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
            world,
            monkeypatch,
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
            world,
            monkeypatch,
            {"self_dep": _entry(calculation_dependencies=("Q_SELF",))},
            {"percentage_w_w": ("Q_SELF", "self_dep")},
        )
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        assert caught.value.error_code == "DEPENDENCY_CYCLE"

    def test_a_dependency_outside_the_version_is_rejected(self, world, monkeypatch):
        """M4D3-DAG-009 -- an edge may not point at a code this version lacks."""
        _synthetic_world(
            world,
            monkeypatch,
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
        question.save(update_fields=["calculation_binding_identifier", "updated_at"])
        with pytest.raises(CascadeGraphInvalid) as caught:
            build_execution_graph(world["execution"])
        assert caught.value.error_code == "UNKNOWN_REGISTRY_IDENTIFIER"

    def test_a_graph_fault_aborts_the_cascade_before_any_write(self, world):
        """M4D3-RBD-008 -- rejected, and nothing partially recalculated."""
        from audit.models import AuditEvent

        question = world["questions"]["percentage_of_iid_mde"]
        question.calculation_binding_identifier = "not_a_registered_calculation"
        question.save(update_fields=["calculation_binding_identifier", "updated_at"])
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
        question.save(update_fields=["calculation_binding_identifier", "updated_at"])
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
        versions_before = {key: world["responses"][key].version for key in ALL_KEYS}

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
            code for code in result.question_codes if code not in {"Q_PCT_MDE", "Q_DIF_MDE"}
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
        assert mde.input_provenance["upstream_outcome_public_ids"] == [str(exposure.public_id)]


# ===========================================================================
# E. The governed writer stays the only writer -- M4D3-SVC
# ===========================================================================


class TestCascadeIsNotASecondWriter:
    def test_every_target_goes_through_the_execution_service(self, world, monkeypatch):
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
            "calculate_percentage_w_w",
            "calculate_daily_exposure",
            "calculate_percentage_of_potency",
            "calculate_difference_from_potency",
            "calculate_percentage_of_mde",
            "calculate_difference_from_mde",
            "translate_result",
            "engine",
            # outcome persistence and provenance
            "full_clean",
            "input_provenance",
            "inputs",
            "generated_at",
            "rounding_rule",
            "formula_version",
            "calculation_name",
            # snapshot creation and audit dispatch
            "create_assessment_snapshot",
            "AssessmentSnapshot",
            "on_commit",
            "emit",
            "IigChecklistEvent",
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
            key: (world["outcomes"][key].pk, world["outcomes"][key].public_id) for key in ALL_KEYS
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
    def test_one_event_per_recalculated_target(self, world, django_capture_on_commit_callbacks):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            result = _cascade(world)

        events = AuditEvent.objects.filter(event_type=CALCULATED_EVENT)
        assert events.count() == result.recalculated_count == len(ALL_KEYS)
        assert {e.resource_id for e in events} == set(result.recalculated_response_public_ids)

    def test_no_cascade_summary_event_is_invented(self, world, django_capture_on_commit_callbacks):
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
        assert {e for e in emitted if e.startswith("iig_checklist.")} == {CALCULATED_EVENT}
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

    def test_a_changed_recalculation_still_audits(self, world, django_capture_on_commit_callbacks):
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
        assert AuditEvent.objects.filter(event_type=CALCULATED_EVENT).count() - baseline == len(
            changed
        )

    def test_direct_execution_always_audits(self, world, django_capture_on_commit_callbacks):
        """The M4D3-RCL-004 hook is opt-in; single-response behaviour is unchanged."""
        from audit.models import AuditEvent
        from iig_checklist.calculation_execution import execute_calculation_response

        world["iid"]["record"].delete()
        response = world["responses"]["percentage_of_iid_potency"]
        for _ in range(2):
            response.refresh_from_db()
            with django_capture_on_commit_callbacks(execute=True):
                result = execute_calculation_response(
                    tenant=world["tenant"],
                    execution=world["execution"],
                    response=response,
                    actor=world["user"],
                    expected_version=response.version,
                )
            assert result.audit_suppressed is False
        assert (
            AuditEvent.objects.filter(
                event_type=CALCULATED_EVENT, resource_id=str(response.public_id)
            ).count()
            == 2
        )

    def test_a_rolled_back_cascade_emits_no_audit(self, world, django_capture_on_commit_callbacks):
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
    def test_a_failure_part_way_through_discards_the_whole_cascade(self, world, monkeypatch):
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
                        registry_mod.CALCULATION_BINDING_REGISTRY["percentage_of_iid_potency"],
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
                        registry_mod.CALCULATION_BINDING_REGISTRY["difference_from_iid_mde"],
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
        ChecklistResponse.objects.filter(pk=selector.pk).update(version=stale_version + 1)
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
                for d in registry_mod.CALCULATION_BINDING_REGISTRY[key].input_resolvers.values()
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
            for public_id in AssessmentSnapshot.objects.values_list("public_id", flat=True)
        }
        _cascade(world)
        referenced = {
            _outcome(world, key).source_assessment_snapshot_public_id for key in ALL_KEYS
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

        ChecklistExecution.objects.filter(pk=world["execution"].pk).update(status=status)
        with pytest.raises(CascadeExecutionNotRecalculable):
            _cascade(world)
        for key in ALL_KEYS:
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED

    @pytest.mark.parametrize("status", [ExecutionStatus.DRAFT, ExecutionStatus.RETURNED])
    def test_recalculable_statuses_proceed(self, world, status):
        from iig_checklist.models import ChecklistExecution

        ChecklistExecution.objects.filter(pk=world["execution"].pk).update(status=status)
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
        ChecklistExecution.objects.filter(pk=stale.pk).update(status=ExecutionStatus.APPROVED)
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
        return [q["sql"] for q in ctx.captured_queries if "FOR UPDATE" in q["sql"].upper()]

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
            "checklistresponse"
            if "checklistresponse" in sql.lower()
            else "calculationoutcome"
            if "calculationoutcome" in sql.lower()
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
        response_pks = {world["responses"][key].pk for key in ALL_KEYS}

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
        assert before_first_target.index(response_locks[-1]) < before_first_target.index(
            outcome_locks[-1]
        )


# ===========================================================================
# M. Result contract
# ===========================================================================


class TestResultContract:
    def test_the_result_identifies_the_origin(self, world):
        result = _cascade(world)
        assert result.execution_public_id == str(world["execution"].public_id)
        assert result.origin_response_public_id == str(world["selector_response"].public_id)
        assert result.origin_question_code == registry_mod.Q_SUBJECT_COMPONENT

    def test_targets_carry_governed_identities_only(self, world):
        result = _cascade(world)
        for target in result.targets:
            assert target.registry_identifier in (registry_mod.CALCULATION_BINDING_REGISTRY)
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


# ===========================================================================
# N. expected_version -- M4D3-TXN-003, the same gate as the single writer
# ===========================================================================
#
# The cascade previously compared the caller's ``expected_version`` to the
# locked row directly. Under Python equality ``True == 1`` and ``1.0 == 1``, so
# a malformed value was accepted whenever the origin stood at version 1, and
# every other malformed value was reported as ``StaleResponseVersion`` rather
# than ``InvalidExpectedVersion``. The structural gate is now the shared
# ``validate_expected_version()`` the single-response writer already used.

#: Every value M4D3-TXN-003 rejects structurally, whatever the row holds.
INVALID_EXPECTED_VERSIONS = (
    None,
    True,
    False,
    1.0,
    "1",
    0,
    -1,
    1.5,
    [],
    {},
    [1],
    Decimal("1"),
)


def _raw_cascade(world, expected_version):
    """``recalculate_dependents`` with ``expected_version`` passed verbatim.

    ``_cascade`` treats ``None`` as "use the row's own version", so the invalid
    cases must not go through it.
    """
    return recalculate_dependents(
        tenant=world["tenant"],
        execution=world["execution"],
        changed_response=world["selector_response"],
        actor=world["user"],
        expected_version=expected_version,
    )


def _mutation_fingerprint(world):
    """Everything a cascade must leave untouched to have written nothing."""
    from audit.models import AuditEvent
    from iid_assessment.models import AssessmentSnapshot
    from iig_checklist.models import ChecklistResponse

    return {
        "outcomes": {
            key: (
                _outcome(world, key).status,
                _outcome(world, key).value,
                _outcome(world, key).reason_code,
                _outcome(world, key).generated_at,
                _outcome(world, key).updated_at,
            )
            for key in ALL_KEYS
        },
        "responses": dict(
            ChecklistResponse.objects.filter(execution=world["execution"]).values_list(
                "pk", "version"
            )
        ),
        "snapshots": AssessmentSnapshot.objects.count(),
        "audit": AuditEvent.objects.count(),
    }


class TestExpectedVersionStructuralGate:
    def test_the_cascade_uses_the_single_governed_validator(self):
        """No second implementation: cascade imports the writer's own gate."""
        from iig_checklist import calculation_execution as exec_mod

        assert cascade_mod.validate_expected_version is exec_mod.validate_expected_version

    def test_the_cascade_restates_none_of_the_validation_rules(self):
        """The rules live in one place; cascade must not re-derive them.

        Read from the parsed AST of ``recalculate_dependents`` so the module's
        prose about the contract is not mistaken for a duplicate check.
        """
        import ast

        tree = ast.parse(inspect.getsource(cascade_mod.recalculate_dependents))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                assert name != "isinstance", "cascade re-implements the type rule"

    @pytest.mark.parametrize("bad", INVALID_EXPECTED_VERSIONS)
    def test_a_malformed_expected_version_is_invalid_not_stale(self, world, bad):
        from iig_checklist.calculation_execution import InvalidExpectedVersion

        with pytest.raises(InvalidExpectedVersion):
            _raw_cascade(world, bad)

    @pytest.mark.parametrize("bad", INVALID_EXPECTED_VERSIONS)
    def test_a_malformed_expected_version_mutates_nothing(self, world, bad):
        """Zero outcome, response, snapshot, audit and history mutation."""
        from iig_checklist.calculation_execution import InvalidExpectedVersion

        before = _mutation_fingerprint(world)
        with pytest.raises(InvalidExpectedVersion):
            _raw_cascade(world, bad)
        assert _mutation_fingerprint(world) == before

    @pytest.mark.parametrize("bad", INVALID_EXPECTED_VERSIONS)
    def test_a_malformed_expected_version_invokes_no_calculation(self, world, bad, monkeypatch):
        from iig_checklist.calculation_execution import InvalidExpectedVersion

        calls = []
        monkeypatch.setattr(
            cascade_mod,
            "execute_calculation_response",
            lambda **kwargs: calls.append(kwargs),
        )
        with pytest.raises(InvalidExpectedVersion):
            _raw_cascade(world, bad)
        assert calls == []

    @pytest.mark.parametrize("bad", INVALID_EXPECTED_VERSIONS)
    def test_validation_precedes_locking(self, world, bad):
        """Phase A runs before the transaction, so nothing is ever locked."""
        from iig_checklist.calculation_execution import InvalidExpectedVersion

        with CaptureQueriesContext(connection) as ctx:
            with pytest.raises(InvalidExpectedVersion):
                _raw_cascade(world, bad)
        assert not any("FOR UPDATE" in query["sql"].upper() for query in ctx.captured_queries)
        verbs = {q["sql"].lstrip().split()[0].upper() for q in ctx.captured_queries}
        assert "UPDATE" not in verbs
        assert "INSERT" not in verbs

    def test_a_malformed_expected_version_emits_no_audit(
        self, world, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent
        from iig_checklist.calculation_execution import InvalidExpectedVersion

        before = AuditEvent.objects.count()
        with (
            pytest.raises(InvalidExpectedVersion),
            django_capture_on_commit_callbacks(execute=True),
        ):
            _raw_cascade(world, True)
        assert AuditEvent.objects.count() == before


class TestTrueAndFloatDoNotPassAsVersionOne:
    """The regression the independent review measured, stated directly.

    The fixture's selector response stands at version 1, which is precisely
    where ``True == 1`` and ``1.0 == 1`` made a direct comparison succeed.
    """

    def test_the_origin_really_is_at_version_one(self, world):
        world["selector_response"].refresh_from_db()
        assert world["selector_response"].version == 1

    def test_true_does_not_pass_as_version_one(self, world):
        from iig_checklist.calculation_execution import InvalidExpectedVersion

        world["selector_response"].refresh_from_db()
        assert world["selector_response"].version == 1
        # The exact Python equality a direct comparison would have accepted.
        assert True == 1

        before = _mutation_fingerprint(world)
        with pytest.raises(InvalidExpectedVersion):
            _raw_cascade(world, True)
        assert _mutation_fingerprint(world) == before

    def test_float_one_does_not_pass_as_version_one(self, world):
        from iig_checklist.calculation_execution import InvalidExpectedVersion

        world["selector_response"].refresh_from_db()
        assert world["selector_response"].version == 1
        assert 1.0 == 1

        before = _mutation_fingerprint(world)
        with pytest.raises(InvalidExpectedVersion):
            _raw_cascade(world, 1.0)
        assert _mutation_fingerprint(world) == before

    def test_the_valid_integer_one_still_passes(self, world):
        """The gate must reject the impostors without rejecting the real value."""
        world["selector_response"].refresh_from_db()
        assert world["selector_response"].version == 1
        result = _raw_cascade(world, 1)
        assert result.triggered is True
        assert result.recalculated_count == len(ALL_KEYS)


class TestGenuineStaleVersion:
    """A valid integer that differs from the locked row -- and nothing else."""

    def test_a_valid_integer_mismatch_is_stale(self, world):
        world["selector_response"].refresh_from_db()
        current = world["selector_response"].version
        with pytest.raises(StaleResponseVersion):
            _raw_cascade(world, current + 1)

    def test_a_genuine_stale_version_is_detected_under_the_lock(self, world):
        """The comparison reads the locked row, not the caller's copy."""
        with CaptureQueriesContext(connection) as ctx:
            with pytest.raises(StaleResponseVersion):
                _raw_cascade(world, 9999)
        locked = [q for q in ctx.captured_queries if "FOR UPDATE" in q["sql"].upper()]
        assert locked, "the origin must be locked before the mismatch is reported"

    def test_a_genuine_stale_version_mutates_nothing(self, world):
        before = _mutation_fingerprint(world)
        with pytest.raises(StaleResponseVersion):
            _raw_cascade(world, 9999)
        assert _mutation_fingerprint(world) == before

    def test_a_genuine_stale_version_runs_no_target(self, world, monkeypatch):
        from iig_checklist import calculation_execution as exec_mod

        calls = []
        original = exec_mod.execute_calculation_response

        def recording(**kwargs):
            # Deliberately never reached: that this recorder's body stays
            # uncovered is the assertion, restated below as an empty ``calls``.
            calls.append(str(kwargs["response"].public_id))
            return original(**kwargs)

        monkeypatch.setattr(cascade_mod, "execute_calculation_response", recording)
        with pytest.raises(StaleResponseVersion):
            _raw_cascade(world, 9999)
        assert calls == []


# ===========================================================================
# O. A stale downstream target -- M4D3-RBD-008 whole-cascade rollback
# ===========================================================================


class TestStaleDownstreamTarget:
    """The third target presents a stale version part-way through the cascade.

    The seam replaces only the ``expected_version`` the cascade hands the writer
    for that one target: the real ``execute_calculation_response()`` runs, takes
    its own locks and raises the governed ``StaleResponseVersion`` itself.
    """

    @staticmethod
    def _stale_at_third(monkeypatch, seen):
        from iig_checklist import calculation_execution as exec_mod

        original = exec_mod.execute_calculation_response

        def staling(**kwargs):
            seen.append(str(kwargs["response"].public_id))
            if len(seen) == 3:
                kwargs["expected_version"] = kwargs["expected_version"] + 500
            return original(**kwargs)

        monkeypatch.setattr(cascade_mod, "execute_calculation_response", staling)

    def test_the_cascade_has_at_least_three_calculated_targets(self, world):
        assert len(build_execution_graph(world["execution"]).nodes) >= 3

    def test_a_stale_target_raises_and_rolls_the_whole_cascade_back(self, world, monkeypatch):
        seen = []
        before = _mutation_fingerprint(world)
        self._stale_at_third(monkeypatch, seen)

        with pytest.raises(StaleResponseVersion):
            _cascade(world)

        # The first two targets did run and did write; none of it survived.
        assert len(seen) == 3
        assert _mutation_fingerprint(world) == before

    def test_no_snapshot_survives_a_stale_target(self, world, monkeypatch):
        from iid_assessment.models import AssessmentSnapshot

        before = AssessmentSnapshot.objects.count()
        self._stale_at_third(monkeypatch, [])
        with pytest.raises(StaleResponseVersion):
            _cascade(world)
        assert AssessmentSnapshot.objects.count() == before

    def test_no_audit_fires_for_a_stale_target(
        self, world, monkeypatch, django_capture_on_commit_callbacks
    ):
        """The rollback discards the transaction, so no on_commit callback runs."""
        from audit.models import AuditEvent

        before = AuditEvent.objects.count()
        self._stale_at_third(monkeypatch, [])
        with (
            pytest.raises(StaleResponseVersion),
            django_capture_on_commit_callbacks(execute=True) as callbacks,
        ):
            _cascade(world)
        assert callbacks == []
        assert AuditEvent.objects.count() == before

    def test_no_partial_cascade_survives(self, world, monkeypatch):
        """Every outcome is back at its pre-cascade state, not merely most."""
        self._stale_at_third(monkeypatch, [])
        with pytest.raises(StaleResponseVersion):
            _cascade(world)
        for key in ALL_KEYS:
            outcome = _outcome(world, key)
            assert outcome.status == CalculationStatus.DATA_REQUIRED
            assert outcome.value is None
            assert outcome.generated_at is None


# ===========================================================================
# P. A real multi-level chain -- manual A -> calculated B -> calculated C
# ===========================================================================


def _recording_writer(monkeypatch):
    """Count real writer invocations per response, without replacing it."""
    from iig_checklist import calculation_execution as exec_mod

    seen: list[str] = []
    original = exec_mod.execute_calculation_response

    def recording(**kwargs):
        seen.append(str(kwargs["response"].public_id))
        return original(**kwargs)

    monkeypatch.setattr(cascade_mod, "execute_calculation_response", recording)
    return seen


def _keep_only(world, keys):
    """Reduce the execution's calculated responses to ``keys``, leaving them real."""
    from iig_checklist.models import CalculationOutcome

    for key in set(world["responses"]) - set(keys):
        response = world["responses"][key]
        CalculationOutcome.objects.filter(response=response).delete()
        response.delete()


class TestRealChainCascade:
    """``Q_SUBJECT_COMPONENT`` -> ``daily_exposure`` -> ``percentage_of_iid_mde``.

    Entirely the approved registry: real ORM responses and outcomes, the real
    resolver and the real calculation writer. Nothing is mocked -- the recorder
    wraps the writer to count calls and delegates to it unchanged.
    """

    CHAIN = ("daily_exposure", "percentage_of_iid_mde")

    @pytest.fixture
    def chain(self, world):
        _keep_only(world, self.CHAIN)
        return world

    def test_the_topology_really_is_a_two_level_chain(self, chain):
        graph = build_execution_graph(chain["execution"])
        by_code = {n.question_code: node_id for node_id, n in graph.nodes.items()}
        assert set(by_code) == {registry_mod.Q_DAILY_EXPOSURE, "Q_PCT_MDE"}
        assert graph.edges[by_code["Q_PCT_MDE"]] == (by_code[registry_mod.Q_DAILY_EXPOSURE],)
        assert graph.edges[by_code[registry_mod.Q_DAILY_EXPOSURE]] == ()

    def test_each_link_runs_exactly_once_and_in_order(self, chain, monkeypatch):
        seen = _recording_writer(monkeypatch)
        result = _cascade(chain)

        b_id = str(chain["responses"]["daily_exposure"].public_id)
        c_id = str(chain["responses"]["percentage_of_iid_mde"].public_id)
        assert seen.count(b_id) == 1
        assert seen.count(c_id) == 1
        assert seen.index(b_id) < seen.index(c_id)
        assert list(result.recalculated_response_public_ids) == [b_id, c_id]

    def test_the_downstream_link_reads_the_upstream_outcome_written_this_cascade(self, chain):
        result = _cascade(chain)
        assert result.triggered is True

        upstream = _outcome(chain, "daily_exposure")
        downstream = _outcome(chain, "percentage_of_iid_mde")
        assert upstream.status == CalculationStatus.COMPLETE
        assert upstream.value == Decimal("1.000000")
        assert downstream.status == CalculationStatus.COMPLETE
        # 1 g against the precedent's 2 g maximum daily exposure.
        assert downstream.value == Decimal("50")

    def test_the_downstream_provenance_names_the_current_upstream_outcome(self, chain):
        _cascade(chain)
        upstream = _outcome(chain, "daily_exposure")
        downstream = _outcome(chain, "percentage_of_iid_mde")
        assert downstream.input_provenance["upstream_outcome_public_ids"] == [
            str(upstream.public_id)
        ]
        descriptor = downstream.input_provenance["converted_proposed_daily_exposure"]
        assert descriptor["source_public_id"] == str(upstream.public_id)
        assert descriptor["source_question_code"] == registry_mod.Q_DAILY_EXPOSURE
        assert descriptor["resolver_provenance"]["upstream_outcome_public_id"] == str(
            upstream.public_id
        )

    def test_a_changed_input_flows_the_whole_way_down_the_chain(self, chain):
        """The chain is live, not a fixture coincidence: move A, watch C move."""
        _cascade(chain)
        assert _outcome(chain, "percentage_of_iid_mde").value == Decimal("50")

        component = chain["component"]
        component.quantity_per_dosage_unit = Decimal("0.125000")
        component.save(update_fields=["quantity_per_dosage_unit", "updated_at"])

        _cascade(chain)
        assert _outcome(chain, "daily_exposure").value == Decimal("0.500000")
        assert _outcome(chain, "percentage_of_iid_mde").value == Decimal("25")


# ===========================================================================
# Q. A real diamond -- A -> B, A -> C, (B, C) -> D
# ===========================================================================
#
# The approved six entries contain no diamond, so the topology is expressed
# with a synthetic registry. Only the *shape* is synthetic: B and C are the
# approved ``daily_exposure`` entry itself, D is the approved
# ``difference_from_iid_mde`` entry with its two inputs pointed at B and C, and
# the real resolver, the real engine functions and the real calculation writer
# all run untouched.


class TestRealDiamondCascade:
    B_CODE = "Q_DIA_B"
    C_CODE = "Q_DIA_C"
    D_CODE = "Q_DIA_D"

    @pytest.fixture
    def diamond(self, world, monkeypatch):
        approved = registry_mod.CALCULATION_BINDING_REGISTRY
        parent = approved["daily_exposure"]
        sink = approved["difference_from_iid_mde"]

        def _from_outcome(question_code):
            return MappingProxyType(
                {
                    "source": registry_mod.SOURCE_CALCULATION_OUTCOME,
                    "question_code": question_code,
                    "field": "value",
                    "required_status": "complete",
                    # A literal target unit, not a ``SnapshotUnitRef``: the
                    # sink declares no snapshot-sourced input here, so there is
                    # no snapshot for a reference unit to be read from. Both
                    # parents emit grams, so no conversion is implied either.
                    "required_unit": "gram",
                    "unit_source": "gram",
                    "expected_type": "decimal",
                }
            )

        _synthetic_world(
            world,
            monkeypatch,
            {
                "dia_b": parent,
                "dia_c": parent,
                "dia_d": dataclasses.replace(
                    sink,
                    input_resolvers=MappingProxyType(
                        {
                            "converted_proposed_daily_exposure": _from_outcome(self.B_CODE),
                            "selected_iid_mde": _from_outcome(self.C_CODE),
                        }
                    ),
                    calculation_dependencies=(self.B_CODE, self.C_CODE),
                    recalculation_triggers=(self.B_CODE, self.C_CODE),
                    required_units=MappingProxyType(
                        {
                            "converted_proposed_daily_exposure": "gram",
                            "selected_iid_mde": "gram",
                        }
                    ),
                ),
            },
            {
                "daily_exposure": (self.B_CODE, "dia_b"),
                "percentage_w_w": (self.C_CODE, "dia_c"),
                "difference_from_iid_mde": (self.D_CODE, "dia_d"),
            },
        )
        return {
            "world": world,
            "b": world["responses"]["daily_exposure"],
            "c": world["responses"]["percentage_w_w"],
            "d": world["responses"]["difference_from_iid_mde"],
        }

    def test_the_topology_really_is_a_diamond(self, diamond):
        graph = build_execution_graph(diamond["world"]["execution"])
        by_code = {n.question_code: node_id for node_id, n in graph.nodes.items()}
        assert set(by_code) == {self.B_CODE, self.C_CODE, self.D_CODE}
        assert graph.edges[by_code[self.B_CODE]] == ()
        assert graph.edges[by_code[self.C_CODE]] == ()
        assert set(graph.edges[by_code[self.D_CODE]]) == {
            by_code[self.B_CODE],
            by_code[self.C_CODE],
        }

    def test_every_node_runs_exactly_once_with_the_sink_last(self, diamond, monkeypatch):
        seen = _recording_writer(monkeypatch)
        result = _cascade(diamond["world"])

        b_id = str(diamond["b"].public_id)
        c_id = str(diamond["c"].public_id)
        d_id = str(diamond["d"].public_id)
        assert seen.count(b_id) == 1
        assert seen.count(c_id) == 1
        assert seen.count(d_id) == 1
        assert len(seen) == 3
        assert seen[-1] == d_id
        assert list(result.recalculated_response_public_ids) == [b_id, c_id, d_id]
        assert list(result.question_codes) == [self.B_CODE, self.C_CODE, self.D_CODE]

    def test_the_sink_is_not_executed_twice_for_its_two_parents(self, diamond, monkeypatch):
        """M4D3-DAG-010 -- the visited set, on the topology that would expose it."""
        seen = _recording_writer(monkeypatch)
        _cascade(diamond["world"])
        assert seen.count(str(diamond["d"].public_id)) == 1

    def test_the_sink_reads_both_newly_recalculated_parents(self, diamond):
        world = diamond["world"]
        result = _cascade(world)
        assert result.triggered is True

        b_outcome = _outcome(world, "daily_exposure")
        c_outcome = _outcome(world, "percentage_w_w")
        d_outcome = _outcome(world, "difference_from_iid_mde")

        assert b_outcome.status == CalculationStatus.COMPLETE
        assert c_outcome.status == CalculationStatus.COMPLETE
        assert d_outcome.status == CalculationStatus.COMPLETE
        # D is ``selected_iid_mde - converted_proposed_daily_exposure``, wired
        # here to C - B, and both parents recalculated in this same cascade.
        assert d_outcome.value == c_outcome.value - b_outcome.value

    def test_the_sink_provenance_names_both_current_upstream_outcomes(self, diamond):
        world = diamond["world"]
        _cascade(world)

        b_outcome = _outcome(world, "daily_exposure")
        c_outcome = _outcome(world, "percentage_w_w")
        d_outcome = _outcome(world, "difference_from_iid_mde")

        assert set(d_outcome.input_provenance["upstream_outcome_public_ids"]) == {
            str(b_outcome.public_id),
            str(c_outcome.public_id),
        }
        for kwarg, parent in (
            ("converted_proposed_daily_exposure", b_outcome),
            ("selected_iid_mde", c_outcome),
        ):
            descriptor = d_outcome.input_provenance[kwarg]
            assert descriptor["source_public_id"] == str(parent.public_id)
            assert descriptor["resolver_provenance"]["upstream_outcome_public_id"] == str(
                parent.public_id
            )

    def test_a_changed_parent_moves_the_sink(self, diamond):
        """Both parents are live inputs, so the sink tracks them."""
        world = diamond["world"]
        _cascade(world)
        first = _outcome(world, "difference_from_iid_mde").value

        world["component"].quantity_per_dosage_unit = Decimal("0.125000")
        world["component"].save(update_fields=["quantity_per_dosage_unit", "updated_at"])
        _cascade(world)

        b_outcome = _outcome(world, "daily_exposure")
        c_outcome = _outcome(world, "percentage_w_w")
        assert b_outcome.value == Decimal("0.500000")
        assert _outcome(world, "difference_from_iid_mde").value == (
            c_outcome.value - b_outcome.value
        )
        assert first is not None
