"""Milestone 4D-3 -- database-free foundation coverage.

Every test here is provably database-free: no ``django_db`` marker, no ORM
manager call, no model factory, no network and no Docker.  The modules under
test import without Django configured, except where the enum cross-check is
explicitly exercised.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
Approved test strategy:  docs/MILESTONE_4D_3_TEST_STRATEGY.md
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from types import MappingProxyType

import pytest

from iid_assessment import calculations as engine
from iig_checklist import calculation_graph as graph_mod
from iig_checklist import calculation_registry as registry_mod
from iig_checklist import calculation_translation as translation
from iig_checklist import governed_vocabularies as vocab
from iig_checklist import max_daily_units as mdu
from iig_checklist import unit_adapter
from iig_checklist.calculation_graph import CalculationNode, GraphConfigurationError
from iig_checklist.calculation_registry import RegistryConfigurationError

# ===========================================================================
# Closed vocabularies (M4D3-RSN-001..012, M4D3-IFV-001)
# ===========================================================================


class TestVocabularies:
    def test_exact_counts(self):
        """Counts are asserted here and nowhere else in the codebase."""
        assert len(translation.ALLOWED_REASON_CODES) == 19
        assert len(translation.ALLOWED_RESOLVER_DETAIL_CODES) == 6
        assert len(vocab.ALLOWED_HISTORY_REASON_CODES) == 2
        assert len(vocab.ALLOWED_SERVICE_DETAIL_CODES) == 1
        assert len(translation.ALLOWED_INPUT_FAILURE_CODES) == 30

    def test_all_vocabularies_immutable(self):
        for vocabulary in (
            translation.ALLOWED_REASON_CODES,
            translation.ALLOWED_RESOLVER_DETAIL_CODES,
            translation.ALLOWED_INPUT_FAILURE_CODES,
            vocab.ALLOWED_HISTORY_REASON_CODES,
            vocab.ALLOWED_SERVICE_DETAIL_CODES,
        ):
            assert isinstance(vocabulary, frozenset)

    def test_codes_are_canonical_uppercase(self):
        for vocabulary in (
            translation.ALLOWED_REASON_CODES,
            translation.ALLOWED_RESOLVER_DETAIL_CODES,
            translation.ALLOWED_INPUT_FAILURE_CODES,
            vocab.ALLOWED_HISTORY_REASON_CODES,
            vocab.ALLOWED_SERVICE_DETAIL_CODES,
        ):
            for code in vocabulary:
                assert code == code.upper()
                assert code.replace("_", "").isalnum()
                assert len(code) <= 100

    def test_history_codes_only_in_history_vocabulary(self):
        """M4D3-RSN-011 -- history codes never reach CalculationOutcome."""
        for code in ("APPLICABILITY_REEVALUATED", "COMPONENT_REBOUND"):
            assert code in vocab.ALLOWED_HISTORY_REASON_CODES
            assert code not in translation.ALLOWED_REASON_CODES
            assert code not in translation.ALLOWED_RESOLVER_DETAIL_CODES
            assert code not in translation.ALLOWED_INPUT_FAILURE_CODES

    def test_service_detail_code_only_in_service_vocabulary(self):
        """M4D3-RSN-012 -- pre-calculation rejection never becomes an outcome."""
        code = "COMPONENT_REBINDING_NOT_ALLOWED_WHILE_NOT_APPLICABLE"
        assert code in vocab.ALLOWED_SERVICE_DETAIL_CODES
        assert code not in translation.ALLOWED_REASON_CODES
        assert code not in translation.ALLOWED_RESOLVER_DETAIL_CODES
        assert code not in translation.ALLOWED_INPUT_FAILURE_CODES
        assert code not in vocab.ALLOWED_HISTORY_REASON_CODES

    def test_no_cross_vocabulary_overlap(self):
        assert not (translation.ALLOWED_REASON_CODES & translation.ALLOWED_RESOLVER_DETAIL_CODES)
        assert not (vocab.ALLOWED_HISTORY_REASON_CODES & vocab.ALLOWED_SERVICE_DETAIL_CODES)


# ===========================================================================
# Deterministic failure mapping (M4D3-IFV-003..008)
# ===========================================================================


class TestFailureMapping:
    def test_mapping_has_one_row_per_code(self):
        assert len(translation.INPUT_FAILURE_MAPPING) == 30
        assert set(translation.INPUT_FAILURE_MAPPING) == (translation.ALLOWED_INPUT_FAILURE_CODES)

    @pytest.mark.parametrize("code", sorted(translation.ALLOWED_INPUT_FAILURE_CODES))
    def test_every_code_maps_deterministically(self, code):
        """One status, one canonical reason, one value rule -- never complete."""
        mapping = translation.INPUT_FAILURE_MAPPING[code]
        assert mapping.status in {"data_required", "error"}
        assert mapping.status != "complete"
        assert mapping.reason_code in translation.ALLOWED_REASON_CODES
        assert mapping.value_rule == translation.VALUE_RULE_NULL

    def test_upstream_component_mismatch_mapping(self):
        """The 29th row: distinct from both adjacent codes."""
        mapping = translation.INPUT_FAILURE_MAPPING["UPSTREAM_CALCULATION_COMPONENT_MISMATCH"]
        assert mapping.status == "error"
        assert mapping.reason_code == "INPUT_RESOLUTION_FAILED"
        assert mapping.value_rule == translation.VALUE_RULE_NULL
        assert mapping.reason_code != (
            translation.INPUT_FAILURE_MAPPING["ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH"].reason_code
        )
        assert mapping.status != (
            translation.INPUT_FAILURE_MAPPING["UPSTREAM_CALCULATION_MISSING"].status
        )

    @pytest.mark.parametrize(
        "code",
        [
            "INPUT_TENANT_MISMATCH",
            "FORMULATION_COMPONENT_TENANT_MISMATCH",
            "ASSESSMENT_SNAPSHOT_TENANT_MISMATCH",
        ],
    )
    def test_tenant_failures_never_scientific(self, code):
        """M4D3-IFV-005 -- security is never reported as non-comparability."""
        mapping = translation.INPUT_FAILURE_MAPPING[code]
        assert mapping.reason_code == "TENANT_ISOLATION_VIOLATION"
        assert mapping.reason_code != "NOT_COMPARABLE"
        assert mapping.reason_code != "DATA_REQUIRED"

    def test_duplicate_never_maps_to_missing_data(self):
        mapping = translation.INPUT_FAILURE_MAPPING["UPSTREAM_CALCULATION_DUPLICATE"]
        assert mapping.reason_code == "DUPLICATE_UPSTREAM_OUTCOME"
        assert mapping.status == "error"

    def test_malformed_input_distinct_from_non_comparability(self):
        """M4D3-IFV-004."""
        invalid = translation.INPUT_FAILURE_MAPPING["INPUT_VALUE_INVALID"]
        scientific = translation.INPUT_FAILURE_MAPPING["INPUT_VALUE_NOT_COMPARABLE"]
        assert invalid.reason_code == "INPUT_RESOLUTION_FAILED"
        assert scientific.reason_code == "NOT_COMPARABLE"
        assert invalid.reason_code != scientific.reason_code

    def test_unknown_detail_code_fails_closed(self):
        mapping = translation.translate_input_failure("NOT_A_REAL_CODE")
        assert mapping.status == "error"
        assert mapping.reason_code == "INPUT_RESOLUTION_FAILED"


# ===========================================================================
# Engine status translation (M4D3-TRL-001..006)
# ===========================================================================


def _result(status: str, value=None, generated_at: str | None = None):
    return engine.CalculationResult(
        formula_identifier="percentage_w_w",
        formula_version=engine.FORMULA_VERSION,
        status=status,
        value=value,
        generated_at=(generated_at if generated_at is not None else "2026-01-01T00:00:00+00:00"),
    )


class TestStatusTranslation:
    @pytest.mark.parametrize(
        "engine_status,expected_status,expected_reason",
        [
            ("OK", "complete", ""),
            ("DATA_REQUIRED", "data_required", "DATA_REQUIRED"),
            ("INGREDIENT_UNRESOLVED", "error", "INGREDIENT_UNRESOLVED"),
            ("ROUTE_MISMATCH", "error", "ROUTE_MISMATCH"),
            ("DOSAGE_FORM_MISMATCH", "error", "DOSAGE_FORM_MISMATCH"),
            ("UNIT_MISMATCH", "error", "UNIT_MISMATCH"),
            ("FDA_VALUE_UNAVAILABLE", "error", "FDA_VALUE_UNAVAILABLE"),
            ("NOT_COMPARABLE", "error", "NOT_COMPARABLE"),
            ("REGULATORY_REVIEW_REQUIRED", "error", "REGULATORY_REVIEW_REQUIRED"),
        ],
    )
    def test_every_engine_status(self, engine_status, expected_status, expected_reason):
        out = translation.translate_engine_status(_result(engine_status, value=Decimal("1.5")))
        assert out.status == expected_status
        assert out.reason_code == expected_reason
        if expected_status != "complete":
            assert out.value is None

    def test_only_ok_carries_a_value(self):
        out = translation.translate_engine_status(_result("OK", value=Decimal("42.5")))
        assert out.status == "complete"
        assert out.value == Decimal("42.5")

    def test_unknown_status_fails_closed(self):
        out = translation.translate_engine_status(_result("SOMETHING_NEW", value=Decimal("1")))
        assert out.status == "error"
        assert out.reason_code == "UNKNOWN_ENGINE_STATUS"
        assert out.value is None

    def test_calculating_never_produced(self):
        for status in [*translation.ENGINE_STATUS_MAPPING, "BOGUS"]:
            out = translation.translate_engine_status(_result(status))
            assert out.status != "calculating"

    @pytest.mark.parametrize(
        "alias_attr,resolved",
        [
            ("UNIT_CONVERSION_FAILED", "UNIT_MISMATCH"),
            ("IID_VALUE_MISSING", "FDA_VALUE_UNAVAILABLE"),
            ("IID_VALUE_INVALID", "FDA_VALUE_UNAVAILABLE"),
            ("PROPOSED_VALUE_MISSING", "DATA_REQUIRED"),
            ("MAX_DAILY_UNITS_MISSING", "DATA_REQUIRED"),
            ("BASIS_UNCLEAR", "NOT_COMPARABLE"),
            ("RELEASE_NOT_ACTIVE", "REGULATORY_REVIEW_REQUIRED"),
            ("RECORD_SUPERSEDED", "REGULATORY_REVIEW_REQUIRED"),
        ],
    )
    def test_engine_aliases_canonicalise_by_value(self, alias_attr, resolved):
        """M4D3-TRL-003 -- aliases resolve to strings already in the table."""
        assert getattr(engine.CalculationStatus, alias_attr) == resolved
        assert resolved in translation.ENGINE_STATUS_MAPPING

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", "not-a-date", "2026-01-01T00:00:00", "2026-13-01T00:00:00+00:00"],
    )
    def test_malformed_or_naive_generated_at_fails_closed(self, raw):
        """M4D3-TRL-005 -- naive timestamps are never assumed to be UTC."""
        out = translation.translate_engine_status(_result("OK", Decimal("1"), raw))
        assert out.status == "error"
        assert out.reason_code == "INVALID_GENERATED_AT"
        assert out.value is None
        assert out.generated_at is None

    @pytest.mark.parametrize(
        "raw", ["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00+05:30"]
    )
    def test_valid_offsets_accepted(self, raw):
        out = translation.translate_engine_status(_result("OK", Decimal("1"), raw))
        assert out.status == "complete"
        assert out.generated_at is not None
        assert out.generated_at.tzinfo is not None

    def test_engine_produces_parseable_timestamps(self):
        """The real engine always emits a tz-aware ISO-8601 string."""
        result = engine.calculate_percentage_w_w(
            quantity_per_unit_grams=Decimal("1"),
            total_dosage_unit_weight_grams=Decimal("10"),
        )
        assert translation.parse_generated_at(result.generated_at) is not None


# ===========================================================================
# Registry (M4D3-REG-001..020, M4D3-MAP-001..010)
# ===========================================================================


class TestRegistry:
    def test_six_approved_mappings(self):
        assert len(registry_mod.CALCULATION_BINDING_REGISTRY) == 6

    @pytest.mark.parametrize(
        "identifier,calculation_name",
        [
            ("percentage_w_w", "calculate_percentage_w_w"),
            ("daily_exposure", "calculate_daily_exposure"),
            ("percentage_of_iid_potency", "calculate_percentage_of_potency"),
            ("difference_from_iid_potency", "calculate_difference_from_potency"),
            ("percentage_of_iid_mde", "calculate_percentage_of_mde"),
            ("difference_from_iid_mde", "calculate_difference_from_mde"),
        ],
    )
    def test_identifier_to_calculation_name(self, identifier, calculation_name):
        """M4D3-REG-003/007 -- the key is never copied into calculation_name."""
        entry = registry_mod.CALCULATION_BINDING_REGISTRY[identifier]
        assert entry.calculation_name == calculation_name
        assert entry.calculation_name != identifier
        assert entry.function.__name__ == calculation_name

    def test_no_nested_identifier_key(self):
        """M4D3-REG-005/020 -- the mapping key is the sole identifier."""
        for entry in registry_mod.CALCULATION_BINDING_REGISTRY.values():
            assert not hasattr(entry, "identifier")

    def test_registry_is_immutable(self):
        with pytest.raises(TypeError):
            # Deliberately invalid: a read-only mapping must reject assignment.
            registry_mod.CALCULATION_BINDING_REGISTRY["x"] = None

    def test_unknown_key_returns_none(self):
        assert registry_mod.get_entry("does_not_exist") is None

    def test_every_kwarg_has_a_resolver(self):
        """M4D3-INP-002 -- resolvers cover the real function signature."""
        import inspect

        for entry in registry_mod.CALCULATION_BINDING_REGISTRY.values():
            expected = set(inspect.signature(entry.function).parameters)
            assert set(entry.input_resolvers) == expected

    def test_formula_version_matches_engine(self):
        for entry in registry_mod.CALCULATION_BINDING_REGISTRY.values():
            assert entry.formula_version == engine.FORMULA_VERSION

    def test_dependencies_match_form_e_only(self):
        """M4D3-TRG-001 -- only prior-outcome resolvers create edges."""
        for entry in registry_mod.CALCULATION_BINDING_REGISTRY.values():
            form_e = {
                d["question_code"]
                for d in entry.input_resolvers.values()
                if d.get("source") == registry_mod.SOURCE_CALCULATION_OUTCOME
            }
            assert set(entry.calculation_dependencies) == form_e

    def test_triggers_include_component_selectors(self):
        """M4D3-TRG-002 -- selector responses are triggers, not graph edges."""
        entry = registry_mod.CALCULATION_BINDING_REGISTRY["percentage_w_w"]
        assert registry_mod.Q_SUBJECT_COMPONENT in entry.recalculation_triggers
        assert registry_mod.Q_SUBJECT_COMPONENT not in entry.calculation_dependencies

    def test_canonical_units_are_full_words(self):
        """M4D3-UNC-003 -- 'gram', never 'g'."""
        entry = registry_mod.CALCULATION_BINDING_REGISTRY["percentage_w_w"]
        assert entry.required_units["quantity_per_unit_grams"] == "gram"
        assert entry.required_units["total_dosage_unit_weight_grams"] == "gram"


# ===========================================================================
# Resolver declaration validation (M4D3-INP-003..009, M4D3-FCR-012)
# ===========================================================================


class TestResolverDeclarations:
    def test_all_registry_declarations_valid(self):
        for entry in registry_mod.CALCULATION_BINDING_REGISTRY.values():
            for kwarg, decl in entry.input_resolvers.items():
                registry_mod.validate_resolver_declaration(kwarg, decl)

    def test_unknown_source_rejected(self):
        with pytest.raises(RegistryConfigurationError, match="unknown resolver source"):
            registry_mod.validate_resolver_declaration("x", {"source": "magic"})

    def test_missing_required_key_rejected(self):
        with pytest.raises(RegistryConfigurationError, match="missing keys"):
            registry_mod.validate_resolver_declaration(
                "x", {"source": registry_mod.SOURCE_ASSESSMENT_SNAPSHOT}
            )

    def test_forbidden_extra_key_rejected(self):
        with pytest.raises(RegistryConfigurationError, match="forbidden keys"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_ASSESSMENT_SNAPSHOT,
                    "field": "iid_mde",
                    "expected_type": "decimal",
                    "sneaky": 1,
                },
            )

    def test_registry_component_code_selector_disabled(self):
        """M4D3-FCR-012 -- form B is rejected with the approved detail."""
        with pytest.raises(RegistryConfigurationError, match="component_selector_form_disabled"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                    "object": "formulation_component",
                    "field": "quantity_per_dosage_unit",
                    "expected_type": "decimal",
                    "component_selector": {
                        "type": registry_mod.SELECTOR_REGISTRY_COMPONENT_CODE,
                        "question_code": "ANY",
                    },
                    "required_component_type": "inactive",
                },
            )

    def test_component_object_requires_selector(self):
        with pytest.raises(RegistryConfigurationError, match="component_selector is mandatory"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                    "object": "formulation_component",
                    "field": "quantity_per_dosage_unit",
                    "expected_type": "decimal",
                },
            )

    def test_shorthand_unit_rejected(self):
        """M4D3-UNC-003 -- 'g' is not a canonical unit."""
        with pytest.raises(RegistryConfigurationError, match="not a canonical unit"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_FORMULATION_FIELD,
                    "object": "formulation_version",
                    "field": "total_dosage_unit_weight",
                    "required_unit": "g",
                    "expected_type": "decimal",
                },
            )

    def test_snapshot_field_allow_list(self):
        with pytest.raises(RegistryConfigurationError, match="not a permitted snapshot field"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_ASSESSMENT_SNAPSHOT,
                    "field": "selected_iid_mde",  # a kwarg name, not a model field
                    "expected_type": "decimal",
                },
            )

    def test_calculation_outcome_requires_complete_status(self):
        with pytest.raises(RegistryConfigurationError, match="required_status"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_CALCULATION_OUTCOME,
                    "question_code": "Q",
                    "field": "value",
                    "required_status": "data_required",
                    "expected_type": "decimal",
                },
            )

    def test_question_response_only_reads_raw_value(self):
        with pytest.raises(RegistryConfigurationError, match="raw_value"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_QUESTION_RESPONSE,
                    "question_code": "Q",
                    "value_field": "system_derived_value",
                    "expected_type": "decimal",
                },
            )

    def test_callable_in_declaration_rejected(self):
        with pytest.raises(RegistryConfigurationError, match="callables are not permitted"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_CONSTANT,
                    "value": len,
                    "type": "decimal",
                    "binding_version": "1.0.0",
                },
            )

    def test_mutable_constant_rejected(self):
        with pytest.raises(RegistryConfigurationError, match="constant must be immutable"):
            registry_mod.validate_resolver_declaration(
                "x",
                {
                    "source": registry_mod.SOURCE_CONSTANT,
                    "value": [1, 2],
                    "type": "decimal",
                    "binding_version": "1.0.0",
                },
            )

    def test_constant_form_accepts_valid_declaration(self):
        registry_mod.validate_resolver_declaration(
            "x",
            {
                "source": registry_mod.SOURCE_CONSTANT,
                "value": Decimal("1"),
                "type": "decimal",
                "binding_version": "1.0.0",
            },
        )


# ===========================================================================
# Pure graph (M4D3-DEP-001..012, M4D3-DAG-003..010)
# ===========================================================================


def _node(node_id: str, code: str, identifier: str) -> CalculationNode:
    return CalculationNode(node_id=node_id, question_code=code, registry_identifier=identifier)


class TestCalculationGraph:
    def test_linear_graph_order(self):
        nodes = (
            _node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),
            _node("n-mde", "Q_MDE_PCT", "percentage_of_iid_mde"),
        )
        graph = graph_mod.build_graph(nodes)
        assert graph.order == ("n-exposure", "n-mde")
        assert graph.depth == 2

    def test_branching_siblings_do_not_depend_on_each_other(self):
        nodes = (
            _node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),
            _node("n-pct", "Q_MDE_PCT", "percentage_of_iid_mde"),
            _node("n-diff", "Q_MDE_DIFF", "difference_from_iid_mde"),
        )
        graph = graph_mod.build_graph(nodes)
        assert graph.edges["n-pct"] == ("n-exposure",)
        assert graph.edges["n-diff"] == ("n-exposure",)
        assert "n-diff" not in graph.edges["n-pct"]
        assert graph.depth == 2
        assert set(graph.downstream_closure("n-exposure")) == {"n-pct", "n-diff"}

    def test_same_function_two_components_stay_distinct(self):
        """M4D3-DEP-007 -- node identity is governed, not the function name."""
        nodes = (
            _node("n-a", "Q_PCT_A", "percentage_w_w"),
            _node("n-b", "Q_PCT_B", "percentage_w_w"),
        )
        graph = graph_mod.build_graph(nodes)
        assert len(graph.nodes) == 2
        assert graph.order == ("n-a", "n-b")

    def test_stable_repeated_order(self):
        nodes = (
            _node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),
            _node("n-diff", "Q_MDE_DIFF", "difference_from_iid_mde"),
            _node("n-pct", "Q_MDE_PCT", "percentage_of_iid_mde"),
        )
        orders = {graph_mod.build_graph(nodes).order for _ in range(10)}
        assert len(orders) == 1

    def test_an_empty_node_set_is_a_valid_empty_graph(self):
        """A checklist version with no calculations is legitimate, not a fault."""
        graph = graph_mod.build_graph(())
        assert graph.order == ()
        assert graph.depth == 0
        assert dict(graph.nodes) == {}
        assert graph_mod.affected_nodes_for_trigger(graph, "Q_ANYTHING") == ()

    def test_tie_break_is_the_question_code_not_the_node_id(self):
        """M4D3-DAG-006 -- ordered by ascending ``ChecklistQuestion.code``.

        The two orderings are deliberately opposed here: sorting by ``node_id``
        would put ``zzz`` last, sorting by ``question_code`` puts ``Q_AAA``
        first. Every other test in this class uses node ids that happen to sort
        the same way as their codes, so only this one can tell them apart.

        It matters because in production a node id is the response public UUID,
        which is effectively random: keyed on it, two executions carrying the
        same questions would recalculate in different orders.
        """
        nodes = (
            _node("zzz", "Q_AAA", "percentage_w_w"),
            _node("aaa", "Q_ZZZ", "percentage_w_w"),
        )
        graph = graph_mod.build_graph(nodes)
        assert graph.order == ("zzz", "aaa")
        assert [graph.nodes[n].question_code for n in graph.order] == [
            "Q_AAA",
            "Q_ZZZ",
        ]

    def test_the_tie_break_applies_to_nodes_released_mid_sort(self):
        """Nodes that become ready later are ordered by code too, not append order."""
        nodes = (
            _node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),
            _node("zz-pct", "Q_MDE_A_PCT", "percentage_of_iid_mde"),
            _node("aa-diff", "Q_MDE_B_DIFF", "difference_from_iid_mde"),
        )
        graph = graph_mod.build_graph(nodes)
        assert graph.order == ("n-exposure", "zz-pct", "aa-diff")

    def test_unknown_dependency_rejected(self):
        nodes = (_node("n-pct", "Q_MDE_PCT", "percentage_of_iid_mde"),)
        with pytest.raises(GraphConfigurationError) as exc:
            graph_mod.build_graph(nodes)
        assert exc.value.error_code == graph_mod.ERROR_UNKNOWN_DEPENDENCY_CODE

    def test_unknown_registry_identifier_rejected(self):
        nodes = (_node("n-x", "Q_X", "not_a_real_identifier"),)
        with pytest.raises(GraphConfigurationError) as exc:
            graph_mod.build_graph(nodes)
        assert exc.value.error_code == graph_mod.ERROR_UNKNOWN_REGISTRY_IDENTIFIER

    def test_duplicate_node_id_rejected(self):
        nodes = (
            _node("dup", "Q_A", "percentage_w_w"),
            _node("dup", "Q_B", "percentage_w_w"),
        )
        with pytest.raises(GraphConfigurationError) as exc:
            graph_mod.build_graph(nodes)
        assert exc.value.error_code == graph_mod.ERROR_DUPLICATE_NODE

    def test_duplicate_question_code_rejected(self):
        nodes = (
            _node("n-1", "Q_SAME", "percentage_w_w"),
            _node("n-2", "Q_SAME", "percentage_w_w"),
        )
        with pytest.raises(GraphConfigurationError) as exc:
            graph_mod.build_graph(nodes)
        assert exc.value.error_code == graph_mod.ERROR_DUPLICATE_NODE

    def test_external_trigger_is_not_a_graph_node(self):
        """M4D3-DEP-002 -- the component selector never enters the graph."""
        nodes = (_node("n-pct", "Q_PCT", "percentage_w_w"),)
        graph = graph_mod.build_graph(nodes)
        assert registry_mod.Q_SUBJECT_COMPONENT not in {
            n.question_code for n in graph.nodes.values()
        }
        assert graph.edges["n-pct"] == ()

    def test_trigger_expansion_reaches_downstream(self):
        """M4D3-RCL-006 -- a Form A/selector change still cascades."""
        nodes = (
            _node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),
            _node("n-pct", "Q_MDE_PCT", "percentage_of_iid_mde"),
        )
        graph = graph_mod.build_graph(nodes)
        affected = graph_mod.affected_nodes_for_trigger(graph, registry_mod.Q_SUBJECT_COMPONENT)
        assert affected == ("n-exposure", "n-pct")

    def test_unrelated_trigger_affects_nothing(self):
        """M4D3-RCL-007."""
        nodes = (_node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),)
        graph = graph_mod.build_graph(nodes)
        assert graph_mod.affected_nodes_for_trigger(graph, "Q_UNRELATED") == ()

    def test_cycle_detected(self):
        """A planted cycle is rejected rather than looping."""
        original = registry_mod.CALCULATION_BINDING_REGISTRY["daily_exposure"]
        cyclic = registry_mod.RegistryEntry(
            calculation_name=original.calculation_name,
            function=original.function,
            formula_version=original.formula_version,
            binding_version=original.binding_version,
            input_resolvers=original.input_resolvers,
            calculation_dependencies=("Q_MDE_PCT",),  # back-edge
            recalculation_triggers=original.recalculation_triggers,
            required_units=original.required_units,
            output_unit=original.output_unit,
            rounding_rule=original.rounding_rule,
            allowed_answer_type=original.allowed_answer_type,
        )
        patched = dict(registry_mod.CALCULATION_BINDING_REGISTRY)
        patched["daily_exposure"] = cyclic
        import types as _types

        saved = registry_mod.CALCULATION_BINDING_REGISTRY
        registry_mod.CALCULATION_BINDING_REGISTRY = _types.MappingProxyType(patched)
        try:
            nodes = (
                _node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),
                _node("n-pct", "Q_MDE_PCT", "percentage_of_iid_mde"),
            )
            with pytest.raises(GraphConfigurationError) as exc:
                graph_mod.build_graph(nodes)
            assert exc.value.error_code == graph_mod.ERROR_DEPENDENCY_CYCLE
        finally:
            registry_mod.CALCULATION_BINDING_REGISTRY = saved

    def test_limits_are_the_approved_values(self):
        assert registry_mod.CALCULATION_MAX_DEPENDENCY_DEPTH == 5
        assert registry_mod.CALCULATION_MAX_CASCADE_NODES == 10

    def test_approved_graph_is_within_limits(self):
        """M4D3-DEP-004 -- real depth 2, real cascade 3."""
        nodes = (
            _node("n-exposure", registry_mod.Q_DAILY_EXPOSURE, "daily_exposure"),
            _node("n-pct", "Q_MDE_PCT", "percentage_of_iid_mde"),
            _node("n-diff", "Q_MDE_DIFF", "difference_from_iid_mde"),
        )
        graph = graph_mod.build_graph(nodes)
        assert graph.depth == 2
        assert graph.depth <= registry_mod.CALCULATION_MAX_DEPENDENCY_DEPTH
        assert len(graph.downstream_closure("n-exposure")) + 1 == 3


# ===========================================================================
# Graph boundary limits (M4D3-DAG-003/004, M4D3-DEP-004)
#
# The six-entry production registry has a maximum chain depth of 2 and cannot
# express these graphs, so the boundaries are exercised with synthetic entries
# built from an approved entry.  Only the public graph API is used.
# ===========================================================================


def _synthetic_registry(*, chain: int = 0, fanout: int = 0):
    """Build synthetic registry entries: a linear chain and/or a fan-out star."""
    base = registry_mod.CALCULATION_BINDING_REGISTRY["percentage_w_w"]
    entries: dict[str, registry_mod.RegistryEntry] = {}

    def _add(identifier: str, dependencies: tuple[str, ...]) -> None:
        entries[identifier] = registry_mod.RegistryEntry(
            calculation_name=base.calculation_name,
            function=base.function,
            formula_version=base.formula_version,
            binding_version=base.binding_version,
            input_resolvers=base.input_resolvers,
            calculation_dependencies=dependencies,
            recalculation_triggers=base.recalculation_triggers,
            required_units=base.required_units,
            output_unit=base.output_unit,
            rounding_rule=base.rounding_rule,
            allowed_answer_type=base.allowed_answer_type,
        )

    for index in range(chain):
        _add(f"chain_{index}", () if index == 0 else (f"QC_{index - 1}",))
    if fanout:
        _add("root", ())
        for index in range(fanout):
            _add(f"leaf_{index}", ("QC_ROOT",))
    return MappingProxyType(entries)


def _chain_nodes(length: int) -> tuple[CalculationNode, ...]:
    return tuple(CalculationNode(f"n{i}", f"QC_{i}", f"chain_{i}") for i in range(length))


def _star_nodes(leaves: int) -> tuple[CalculationNode, ...]:
    nodes = [CalculationNode("nroot", "QC_ROOT", "root")]
    nodes += [CalculationNode(f"nl{i}", f"QC_L{i}", f"leaf_{i}") for i in range(leaves)]
    return tuple(nodes)


@contextmanager
def _using_registry(registry):
    """Swap the registry for the duration of one synthetic graph assertion."""
    saved = registry_mod.CALCULATION_BINDING_REGISTRY
    registry_mod.CALCULATION_BINDING_REGISTRY = registry
    try:
        yield
    finally:
        registry_mod.CALCULATION_BINDING_REGISTRY = saved


class TestGraphDepthBoundary:
    def test_isolated_node_has_depth_one(self):
        with _using_registry(_synthetic_registry(chain=1)):
            graph = graph_mod.build_graph(_chain_nodes(1))
        assert graph.depth == 1

    def test_depth_five_accepted(self):
        """M4D3-DAG-003 -- the approved maximum is permitted, not rejected."""
        with _using_registry(_synthetic_registry(chain=5)):
            graph = graph_mod.build_graph(_chain_nodes(5))
        assert graph.depth == registry_mod.CALCULATION_MAX_DEPENDENCY_DEPTH == 5
        assert len(graph.order) == 5

    def test_depth_six_rejected(self):
        """M4D3-DAG-003 -- one beyond the limit fails closed."""
        with _using_registry(_synthetic_registry(chain=6)):
            with pytest.raises(GraphConfigurationError) as exc:
                graph_mod.build_graph(_chain_nodes(6))
        assert exc.value.error_code == graph_mod.ERROR_DEPENDENCY_DEPTH_EXCEEDED

    def test_depth_rejection_is_deterministic(self):
        with _using_registry(_synthetic_registry(chain=6)):
            codes = set()
            for _ in range(5):
                with pytest.raises(GraphConfigurationError) as exc:
                    graph_mod.build_graph(_chain_nodes(6))
                codes.add(exc.value.error_code)
        assert codes == {graph_mod.ERROR_DEPENDENCY_DEPTH_EXCEEDED}

    def test_no_partial_graph_returned_on_depth_rejection(self):
        with _using_registry(_synthetic_registry(chain=6)):
            result = None
            try:
                result = graph_mod.build_graph(_chain_nodes(6))
            except GraphConfigurationError:
                pass
        assert result is None


class TestGraphCascadeBoundary:
    def test_ten_reachable_nodes_accepted(self):
        """M4D3-DAG-004 -- root plus nine leaves is exactly the limit."""
        with _using_registry(_synthetic_registry(fanout=9)):
            graph = graph_mod.build_graph(_star_nodes(9))
        reachable = len(graph.downstream_closure("nroot")) + 1
        assert reachable == registry_mod.CALCULATION_MAX_CASCADE_NODES == 10

    def test_eleven_reachable_nodes_rejected(self):
        with _using_registry(_synthetic_registry(fanout=10)):
            with pytest.raises(GraphConfigurationError) as exc:
                graph_mod.build_graph(_star_nodes(10))
        assert exc.value.error_code == graph_mod.ERROR_CASCADE_NODE_LIMIT_EXCEEDED

    def test_no_partial_cascade_returned_on_rejection(self):
        with _using_registry(_synthetic_registry(fanout=10)):
            result = None
            try:
                result = graph_mod.build_graph(_star_nodes(10))
            except GraphConfigurationError:
                pass
        assert result is None

    def test_external_triggers_are_not_counted_as_nodes(self):
        """A ten-node graph stays within the limit despite trigger codes."""
        with _using_registry(_synthetic_registry(fanout=9)):
            graph = graph_mod.build_graph(_star_nodes(9))
        codes = {node.question_code for node in graph.nodes.values()}
        assert registry_mod.Q_SUBJECT_COMPONENT not in codes
        assert len(graph.nodes) == 10

    def test_duplicate_nodes_rejected_independently_of_size(self):
        """Duplicate identity fails as a duplicate, not as a size violation."""
        with _using_registry(_synthetic_registry(fanout=2)):
            nodes = (
                CalculationNode("nroot", "QC_ROOT", "root"),
                CalculationNode("dup", "QC_L0", "leaf_0"),
                CalculationNode("dup", "QC_L1", "leaf_1"),
            )
            with pytest.raises(GraphConfigurationError) as exc:
                graph_mod.build_graph(nodes)
        assert exc.value.error_code == graph_mod.ERROR_DUPLICATE_NODE


# ===========================================================================
# Foundation immutability (M4D3-REG-004)
# ===========================================================================


class TestResolverKeyImmutability:
    def test_outer_mapping_is_read_only(self):
        with pytest.raises(TypeError):
            registry_mod._RESOLVER_KEYS["new_form"] = (frozenset(), frozenset())

    def test_existing_form_cannot_be_replaced(self):
        with pytest.raises(TypeError):
            registry_mod._RESOLVER_KEYS[registry_mod.SOURCE_CONSTANT] = (
                frozenset(),
                frozenset(),
            )

    def test_nested_key_sets_are_frozen(self):
        required, optional = registry_mod._RESOLVER_KEYS[registry_mod.SOURCE_QUESTION_RESPONSE]
        assert isinstance(required, frozenset)
        assert isinstance(optional, frozenset)
        with pytest.raises(AttributeError):
            # Deliberately invalid: a frozenset exposes no mutating method.
            required.add("smuggled")

    def test_form_count_unchanged(self):
        assert set(registry_mod._RESOLVER_KEYS) == (registry_mod.ALLOWED_RESOLVER_SOURCES)


class TestCanonicalCodePredicate:
    """The named predicate replacing the former lambda -- identical behaviour."""

    @pytest.mark.parametrize("value", ["DATA_REQUIRED", "A", "A1", "COMPONENT_REBOUND", "X_9_Y"])
    def test_accepts_canonical_codes(self, value):
        assert translation.is_canonical_code(value) is True

    @pytest.mark.parametrize(
        "value", ["", "lower", "Mixed_Case", "HAS SPACE", "HAS-DASH", None, 5, b"X"]
    )
    def test_rejects_non_canonical(self, value):
        assert translation.is_canonical_code(value) is False

    def test_every_vocabulary_member_is_canonical(self):
        for vocabulary in (
            translation.ALLOWED_REASON_CODES,
            translation.ALLOWED_RESOLVER_DETAIL_CODES,
            translation.ALLOWED_INPUT_FAILURE_CODES,
            vocab.ALLOWED_HISTORY_REASON_CODES,
            vocab.ALLOWED_SERVICE_DETAIL_CODES,
        ):
            assert all(translation.is_canonical_code(c) for c in vocabulary)

    def test_import_time_validation_still_passes(self):
        """Re-running the guard must not raise after the refactor."""
        translation._validate_vocabularies()


# ===========================================================================
# Maximum daily units (M4D3-MDU-001..024)
# ===========================================================================


def _regimen(pid: str, units: str, population: str = "") -> mdu.DosingRegimenCandidate:
    return mdu.DosingRegimenCandidate(
        public_id=pid, maximum_units_per_day=Decimal(units), patient_population=population
    )


class TestMaximumDailyUnits:
    def test_scalar_only(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1", version_scalar=Decimal("4")
        )
        assert out.resolved and out.value == Decimal("4")
        assert out.source_type == mdu.SOURCE_FORMULATION_VERSION
        assert out.source_disagreement is False

    def test_single_regimen_only(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            regimen_candidates=(_regimen("r-1", "6"),),
        )
        assert out.value == Decimal("6")
        assert out.source_type == mdu.SOURCE_DOSING_REGIMEN

    def test_highest_of_many_regimens(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            regimen_candidates=(
                _regimen("r-1", "10", "adult"),
                _regimen("r-2", "25", "paediatric"),
                _regimen("r-3", "15", "elderly"),
            ),
        )
        assert out.value == Decimal("25")
        assert out.provenance["selected_regimen_public_id"] == "r-2"

    def test_equal_values_use_uuid_tie_break(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            regimen_candidates=(_regimen("r-zzz", "9"), _regimen("r-aaa", "9")),
        )
        assert out.provenance["selected_regimen_public_id"] == "r-aaa"
        assert out.provenance["tie_break_applied"] is True

    def test_equal_scalar_and_regimen_records_both(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            version_scalar=Decimal("8"),
            regimen_candidates=(_regimen("r-1", "8"),),
        )
        assert out.value == Decimal("8")
        assert out.source_type == mdu.SOURCE_COMBINED_CONSERVATIVE
        assert out.source_disagreement is False

    def test_regimen_higher_than_scalar_wins(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            version_scalar=Decimal("10"),
            regimen_candidates=(_regimen("r-1", "25"),),
        )
        assert out.value == Decimal("25")
        assert out.source_disagreement is True
        assert out.detail_code == mdu.DETAIL_SOURCE_DISAGREEMENT

    def test_scalar_higher_than_regimen_wins(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            version_scalar=Decimal("25"),
            regimen_candidates=(_regimen("r-1", "10"),),
        )
        assert out.value == Decimal("25")
        assert out.source_disagreement is True

    def test_never_averages_or_prefers_lower(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            version_scalar=Decimal("10"),
            regimen_candidates=(_regimen("r-1", "20"),),
        )
        assert out.value not in (Decimal("15"), Decimal("10"))

    def test_no_source_fails_closed(self):
        out = mdu.select_maximum_daily_units(formulation_version_public_id="fv-1")
        assert out.resolved is False
        assert out.value is None
        assert out.detail_code == mdu.DETAIL_REQUIRED

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
    def test_non_positive_excluded(self, bad):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            regimen_candidates=(
                mdu.DosingRegimenCandidate("r-bad", bad),
                _regimen("r-ok", "3"),
            ),
        )
        assert out.value == Decimal("3")
        assert "r-bad" in out.provenance["invalid_candidates"]

    @pytest.mark.parametrize("bad", [1.5, True, "5", None, Decimal("NaN")])
    def test_non_decimal_rejected(self, bad):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            regimen_candidates=(mdu.DosingRegimenCandidate("r-bad", bad),),
        )
        assert out.resolved is False
        assert out.detail_code == mdu.DETAIL_SOURCE_INVALID

    def test_all_invalid_fails_closed(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            version_scalar=Decimal("-5"),
            regimen_candidates=(mdu.DosingRegimenCandidate("r-bad", Decimal("0")),),
        )
        assert out.resolved is False
        assert out.detail_code == mdu.DETAIL_SOURCE_INVALID

    def test_patient_population_is_provenance_not_filter(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            regimen_candidates=(
                _regimen("r-1", "5", "adult"),
                _regimen("r-2", "30", "paediatric"),
            ),
        )
        assert out.value == Decimal("30")
        populations = {c["patient_population"] for c in out.provenance["considered_regimens"]}
        assert populations == {"adult", "paediatric"}

    def test_repeated_runs_are_deterministic(self):
        candidates = (_regimen("r-b", "9"), _regimen("r-a", "9"), _regimen("r-c", "4"))
        results = [
            mdu.select_maximum_daily_units(
                formulation_version_public_id="fv-1", regimen_candidates=candidates
            )
            for _ in range(10)
        ]
        assert len({r.value for r in results}) == 1
        assert len({r.provenance["selected_regimen_public_id"] for r in results}) == 1

    def test_provenance_has_no_internal_ids(self):
        out = mdu.select_maximum_daily_units(
            formulation_version_public_id="fv-1",
            regimen_candidates=(_regimen("r-1", "5"),),
        )
        assert "pk" not in out.provenance
        assert "id" not in out.provenance
        assert out.provenance["resolver_version"] == mdu.RESOLVER_VERSION


# ===========================================================================
# Unit-conversion adapter (M4D3-UNC-001..011)
# ===========================================================================


class TestUnitAdapter:
    def test_gram_to_milligram(self):
        out = unit_adapter.convert_for_calculation(
            value=Decimal("2"), from_unit="gram", to_unit="milligram"
        )
        assert out.ok and out.value == Decimal("2000")

    def test_milligram_to_gram(self):
        out = unit_adapter.convert_for_calculation(
            value=Decimal("500"), from_unit="milligram", to_unit="gram"
        )
        assert out.ok and out.value == Decimal("0.5")

    def test_same_unit_passthrough(self):
        out = unit_adapter.convert_for_calculation(
            value=Decimal("7.25"), from_unit="gram", to_unit="gram"
        )
        assert out.ok and out.value == Decimal("7.25")
        assert isinstance(out.value, Decimal)

    def test_unknown_unit_maps_to_unsupported(self):
        out = unit_adapter.convert_for_calculation(
            value=Decimal("1"), from_unit="furlong", to_unit="gram"
        )
        assert not out.ok
        assert out.failure_code == "INPUT_UNIT_UNSUPPORTED"
        assert translation.INPUT_FAILURE_MAPPING[out.failure_code].reason_code == ("UNIT_MISMATCH")

    def test_mass_to_volume_without_density(self):
        out = unit_adapter.convert_for_calculation(
            value=Decimal("1"), from_unit="gram", to_unit="litre"
        )
        assert not out.ok
        assert out.failure_code in {"INPUT_DENSITY_REQUIRED", "INPUT_UNIT_DIMENSION_MISMATCH"}
        assert translation.INPUT_FAILURE_MAPPING[out.failure_code].status == "error"

    def test_missing_unit_is_data_required(self):
        out = unit_adapter.convert_for_calculation(value=Decimal("1"), from_unit="", to_unit="gram")
        assert not out.ok
        assert out.failure_code == "INPUT_UNIT_MISSING"
        assert translation.INPUT_FAILURE_MAPPING[out.failure_code].status == ("data_required")

    @pytest.mark.parametrize("bad", [1.5, True, "2", None])
    def test_non_decimal_value_rejected(self, bad):
        out = unit_adapter.convert_for_calculation(value=bad, from_unit="gram", to_unit="milligram")
        assert not out.ok
        assert out.failure_code == "INPUT_VALUE_INVALID"

    def test_failure_never_returns_a_value(self):
        out = unit_adapter.convert_for_calculation(
            value=Decimal("1"), from_unit="furlong", to_unit="gram"
        )
        assert out.value is None

    def test_provenance_records_conversion(self):
        out = unit_adapter.convert_for_calculation(
            value=Decimal("2"), from_unit="gram", to_unit="milligram"
        )
        assert out.provenance["original_unit"] == "gram"
        assert out.provenance["converted_unit"] == "milligram"
        assert out.provenance["conversion_factor"] == "1000"
        assert out.provenance["conversion_rule_version"] == (unit_adapter.CONVERSION_RULE_VERSION)

    def test_every_failure_code_is_in_the_vocabulary(self):
        for code in unit_adapter._REASON_TO_FAILURE.values():
            assert code in translation.ALLOWED_INPUT_FAILURE_CODES


# ===========================================================================
# Approved calculation functions reused unchanged (M4D3-INP-001)
# ===========================================================================


class TestApprovedCalculations:
    def test_percentage_w_w(self):
        result = engine.calculate_percentage_w_w(
            quantity_per_unit_grams=Decimal("5"),
            total_dosage_unit_weight_grams=Decimal("50"),
        )
        assert result.status == "OK"
        assert result.value == Decimal("10")

    def test_daily_exposure_is_monotonic_in_max_units(self):
        """Evidence for the M4D3-MDU-022 conservative-policy rationale."""
        low = engine.calculate_daily_exposure(
            quantity_per_dosage_unit=Decimal("2"), maximum_dosage_units_per_day=Decimal("3")
        )
        high = engine.calculate_daily_exposure(
            quantity_per_dosage_unit=Decimal("2"), maximum_dosage_units_per_day=Decimal("9")
        )
        assert high.value > low.value

    def test_percentage_of_mde_rises_with_exposure(self):
        low = engine.calculate_percentage_of_mde(
            converted_proposed_daily_exposure=Decimal("5"), selected_iid_mde=Decimal("100")
        )
        high = engine.calculate_percentage_of_mde(
            converted_proposed_daily_exposure=Decimal("50"), selected_iid_mde=Decimal("100")
        )
        assert high.value > low.value

    def test_difference_from_mde_falls_with_exposure(self):
        low = engine.calculate_difference_from_mde(
            selected_iid_mde=Decimal("100"), converted_proposed_daily_exposure=Decimal("5")
        )
        high = engine.calculate_difference_from_mde(
            selected_iid_mde=Decimal("100"), converted_proposed_daily_exposure=Decimal("50")
        )
        assert high.value < low.value

    def test_blocked_results_translate_without_a_value(self):
        result = engine.calculate_daily_exposure(
            quantity_per_dosage_unit=Decimal("1"), maximum_dosage_units_per_day=None
        )
        out = translation.translate_engine_status(result)
        assert out.status == "data_required"
        assert out.reason_code == "DATA_REQUIRED"
        assert out.value is None

    def test_zero_basis_is_not_comparable(self):
        result = engine.calculate_percentage_w_w(
            quantity_per_unit_grams=Decimal("1"),
            total_dosage_unit_weight_grams=Decimal("0"),
        )
        out = translation.translate_engine_status(result)
        assert out.status == "error"
        assert out.reason_code == "NOT_COMPARABLE"
        assert out.value is None
