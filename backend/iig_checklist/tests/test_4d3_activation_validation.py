"""Milestone 4D-3 -- ORM-backed registry activation validation.

Real PostgreSQL-backed tests.  The central validator is never exercised through
mocked QuerySets or managers: every case builds actual persisted checklist
content and drives the governed activation endpoint.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-REG-018/019  activation validation and structured rejection
  - M4D3-DEP-005/006  graph validation at activation; form E target rules
  - M4D3-DEP-011      upstream producer compatibility
  - M4D3-TRG-006/007  dependency and trigger agreement
  - M4D3-FCR-012      registry_component_code selector disabled

Some controls are unreachable while the approved six-entry registry is in force,
because ``_validate_registry()`` rejects those configurations at import time and
the registry is immutable.  Those defensive branches are exercised through a
**synthetic registry** installed with ``monkeypatch`` for the duration of one
test; production definitions are never mutated and immutability is never
weakened.
"""

from __future__ import annotations

import datetime
from types import MappingProxyType

import pytest

from iid_assessment import calculations as engine
from iig_checklist import calculation_registry as registry_mod
from iig_checklist.activation_validation import (
    CALCULATION_GRAPH_CYCLE,
    CASCADE_NODE_LIMIT_EXCEEDED,
    DEPENDENCY_DEPTH_EXCEEDED,
    DEPENDENCY_MISMATCH,
    DEPENDENCY_NOT_CALCULATED,
    DISABLED_SELECTOR_FORM,
    DUPLICATE_GRAPH_NODE,
    QUESTION_CODE_DUPLICATE,
    QUESTION_CODE_MISSING,
    SELECTOR_WRONG_ANSWER_TYPE,
    SYSTEM_CALCULATED_BINDING_MISSING,
    TRIGGER_MISMATCH,
    UNKNOWN_DEPENDENCY_CODE,
    UNKNOWN_REGISTRY_IDENTIFIER,
    UPSTREAM_ANSWER_TYPE_MISMATCH,
    UPSTREAM_BINDING_IDENTIFIER_MISSING,
    UPSTREAM_OUTPUT_UNIT_MISMATCH,
    UPSTREAM_REGISTRY_IDENTIFIER_UNKNOWN,
    UPSTREAM_SOURCE_CLASSIFICATION_MISMATCH,
    WRONG_ANSWER_TYPE,
    WRONG_SOURCE_CLASSIFICATION,
    validate_version_calculation_bindings,
)
from iig_checklist.enums import (
    AnswerType,
    ChecklistVersionStatus,
    Criticality,
    DataSourceClassification,
)

pytestmark = pytest.mark.django_db

#: Matches the existing lifecycle tests' base path.
BASE = "/api/regx/v1"

ACTIVATED_EVENT = "iig_checklist.version.activated"


# ---------------------------------------------------------------------------
# Persisted content helpers -- no mocks anywhere.
# ---------------------------------------------------------------------------


def _section(version, code="S1", order=1):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=version,
        code=code,
        title=f"Section {code}",
        display_order=order,
        criticality=Criticality.MEDIUM,
    )


def _question(
    section,
    code,
    *,
    answer_type,
    classification,
    binding="",
    order=1,
):
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


def _selector_question(section, code=None, *, answer_type=None, order=90):
    """The governed component-reference selector the registry binds to."""
    return _question(
        section,
        code or registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=answer_type or AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED,
        order=order,
    )


def _calculated_question(section, code, identifier, *, order=1, answer_type=None):
    return _question(
        section,
        code,
        answer_type=answer_type or AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding=identifier,
        order=order,
    )


def _valid_percentage_w_w_version(draft_version):
    """A version whose single binding resolves cleanly."""
    section = _section(draft_version)
    _calculated_question(section, "Q_PCT_WW", "percentage_w_w", order=1)
    _selector_question(section)
    return draft_version


def _prepare_for_activation(version):
    version.effective_date = datetime.date(2026, 1, 1)
    version.save(update_fields=["effective_date", "updated_at"])


def _approve_then_activate(version, api_client_doer, api_client_vp):
    """Drive the real governed lifecycle: submit -> approve -> activate."""
    pid = version.public_id
    submit = api_client_doer.post(
        f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={}
    )
    assert submit.status_code == 200, submit.data
    approve = api_client_vp.post(
        f"{BASE}/iig-checklists/versions/{pid}/approve/", data={}
    )
    assert approve.status_code == 200, approve.data
    return api_client_vp.post(
        f"{BASE}/iig-checklists/versions/{pid}/activate/", data={}
    )


def _codes(findings):
    return {finding.validation_code for finding in findings}


def _assert_no_success_audit(version):
    from audit.models import AuditEvent

    assert not AuditEvent.objects.filter(
        event_type=ACTIVATED_EVENT, resource_id=str(version.public_id)
    ).exists()


# ---------------------------------------------------------------------------
# Synthetic registry seam.
#
# The approved registry is immutable and self-validating at import time, so a
# cycle, an over-deep chain or a mismatched trigger set simply cannot exist in
# it.  These helpers build throwaway RegistryEntry values and install them for
# the duration of one test.  ``get_entry()`` resolves the module global on every
# call, so both this module and calculation_graph observe the substitution, and
# monkeypatch restores the real registry afterwards.
# ---------------------------------------------------------------------------


def _entry(**overrides):
    """A structurally valid synthetic registry entry."""
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


def _outcome_resolver(question_code, *, unit_source="gram"):
    """A form E (prior calculation outcome) resolver declaration."""
    return MappingProxyType(
        {
            "source": registry_mod.SOURCE_CALCULATION_OUTCOME,
            "question_code": question_code,
            "field": "value",
            "required_status": "complete",
            "unit_source": unit_source,
            "expected_type": "decimal",
        }
    )


def _dependent_entry(upstream_code, *, unit_source="gram", **overrides):
    """An entry consuming ``upstream_code``'s outcome."""
    return _entry(
        input_resolvers=MappingProxyType(
            {"upstream": _outcome_resolver(upstream_code, unit_source=unit_source)}
        ),
        calculation_dependencies=(upstream_code,),
        recalculation_triggers=(upstream_code,),
        **overrides,
    )


def _install_registry(monkeypatch, mapping):
    monkeypatch.setattr(
        registry_mod, "CALCULATION_BINDING_REGISTRY", MappingProxyType(dict(mapping))
    )


def _chain(monkeypatch, version, length):
    """Persist a straight dependency chain of ``length`` calculated questions."""
    entries = {}
    for index in range(1, length + 1):
        if index == 1:
            entries[f"chain_{index}"] = _entry()
        else:
            entries[f"chain_{index}"] = _dependent_entry(f"Q_CHAIN_{index - 1}")
    _install_registry(monkeypatch, entries)

    section = _section(version)
    for index in range(1, length + 1):
        _calculated_question(
            section, f"Q_CHAIN_{index}", f"chain_{index}", order=index
        )
    return version


def _fan_out(monkeypatch, version, dependants):
    """One root plus ``dependants`` direct consumers -- depth 2, wide cascade."""
    entries = {"fan_root": _entry()}
    for index in range(1, dependants + 1):
        entries[f"fan_{index}"] = _dependent_entry("Q_FAN_ROOT")
    _install_registry(monkeypatch, entries)

    section = _section(version)
    _calculated_question(section, "Q_FAN_ROOT", "fan_root", order=1)
    for index in range(1, dependants + 1):
        _calculated_question(
            section, f"Q_FAN_{index}", f"fan_{index}", order=index + 1
        )
    return version


# ===========================================================================
# A. Valid activation
# ===========================================================================


class TestValidActivation:
    def test_valid_bindings_produce_no_findings(self, draft_version):
        _valid_percentage_w_w_version(draft_version)
        assert validate_version_calculation_bindings(draft_version) == ()

    def test_version_with_no_calculated_questions_is_unaffected(self, draft_version):
        section = _section(draft_version)
        _question(
            section,
            "Q_PLAIN",
            answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED,
        )
        assert validate_version_calculation_bindings(draft_version) == ()

    def test_unreferenced_invalid_entry_does_not_block(self, draft_version, monkeypatch):
        """A deliberately broken entry the version never references is ignored.

        Registry length proves nothing; this installs an entry that *would* fail
        activation outright and shows it is irrelevant while unreferenced.
        """
        _install_registry(
            monkeypatch,
            {
                **dict(registry_mod.CALCULATION_BINDING_REGISTRY),
                "never_referenced": _dependent_entry("Q_DOES_NOT_EXIST"),
            },
        )
        _valid_percentage_w_w_version(draft_version)
        assert validate_version_calculation_bindings(draft_version) == ()

    def test_activation_succeeds_end_to_end(
        self, draft_version, api_client_doer, api_client_vp
    ):
        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 200, response.data
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.ACTIVE
        assert draft_version.activated_at is not None

    def test_activation_emits_success_audit(
        self, draft_version, api_client_doer, api_client_vp
    ):
        from audit.models import AuditEvent

        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert AuditEvent.objects.filter(
            event_type=ACTIVATED_EVENT, resource_id=str(draft_version.public_id)
        ).exists()

    def test_valid_acyclic_graph_activates(
        self, draft_version, api_client_doer, api_client_vp
    ):
        """The real two-node daily-exposure -> MDE graph passes end to end."""
        section = _section(draft_version)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "daily_exposure", order=1
        )
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=2)
        _selector_question(section)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 200, response.data
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.ACTIVE


# ===========================================================================
# B. Missing bindings
# ===========================================================================


class TestMissingBindings:
    def test_missing_component_selector_question(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        findings = validate_version_calculation_bindings(draft_version)
        assert QUESTION_CODE_MISSING in _codes(findings)
        assert any(f.question_code == registry_mod.Q_SUBJECT_COMPONENT for f in findings)

    def test_missing_form_e_dependency_question(self, draft_version):
        """percentage_of_iid_mde depends on the daily-exposure response."""
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde")
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_MISSING
            and f.question_code == registry_mod.Q_DAILY_EXPOSURE
            for f in findings
        )

    def test_one_missing_code_produces_exactly_one_finding(self, draft_version):
        """Regression: the absent selector previously produced two findings.

        The resolver lookup and the trigger sweep both reported it with
        different wording, so one defect surfaced twice.  Identity is now the
        governed semantic key, and messages never determine uniqueness.
        """
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        findings = validate_version_calculation_bindings(draft_version)
        missing = [
            f
            for f in findings
            if f.validation_code == QUESTION_CODE_MISSING
            and f.question_code == registry_mod.Q_SUBJECT_COMPONENT
        ]
        assert len(missing) == 1, [f.message for f in missing]

    def test_missing_binding_blocks_activation_with_zero_mutation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        assert draft_version.activated_at is None

    def test_failed_activation_emits_no_success_audit(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _prepare_for_activation(draft_version)
        _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        _assert_no_success_audit(draft_version)

    def test_failed_activation_does_not_supersede_prior_active(
        self, draft_version, tenant_definition, user_a, api_client_doer, api_client_vp
    ):
        """The supersede step must never run when validation fails."""
        from iig_checklist.models import ChecklistVersion

        prior = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=99,
            created_by=user_a,
            status=ChecklistVersionStatus.ACTIVE,
            effective_date=datetime.date(2025, 1, 1),
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        prior.refresh_from_db()
        assert prior.status == ChecklistVersionStatus.ACTIVE

    def test_unbound_system_calculated_question_fails_activation(self, draft_version):
        """M4D3-REG-018 -- every SYSTEM_CALCULATED question is validated.

        Model.clean() couples classification and binding, but it is not a
        database constraint: objects.create() bypasses it, so activation must
        re-establish the invariant rather than assume it.
        """
        section = _section(draft_version)
        _question(
            section,
            "Q_ORPHAN",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == SYSTEM_CALCULATED_BINDING_MISSING
            and f.question_code == "Q_ORPHAN"
            for f in findings
        )

    def test_unbound_system_calculated_blocks_activation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _question(
            section,
            "Q_ORPHAN",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
        )
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        _assert_no_success_audit(draft_version)


# ===========================================================================
# C. Duplicate bindings
# ===========================================================================


class TestDuplicateBindings:
    def test_duplicate_question_code_across_sections_is_rejected(self, draft_version):
        """Codes are unique per SECTION, so a version may hold duplicates."""
        section_one = _section(draft_version, code="S1", order=1)
        section_two = _section(draft_version, code="S2", order=2)
        _calculated_question(section_one, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section_one)
        _selector_question(section_two)

        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_DUPLICATE
            and f.question_code == registry_mod.Q_SUBJECT_COMPONENT
            for f in findings
        )

    def test_duplicate_never_silently_selects_one(
        self, draft_version, tenant_definition, user_a, api_client_doer, api_client_vp
    ):
        """Ambiguity is reported, not resolved -- and nothing is mutated.

        One of the two matches is perfectly valid on its own, so a validator
        that picked either would activate successfully.  This asserts the exact
        code, the exact ambiguous question code, and full lifecycle inertia.
        """
        from iig_checklist.models import ChecklistVersion

        prior = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=98,
            created_by=user_a,
            status=ChecklistVersionStatus.ACTIVE,
            effective_date=datetime.date(2025, 1, 1),
        )
        section_one = _section(draft_version, code="S1", order=1)
        section_two = _section(draft_version, code="S2", order=2)
        _calculated_question(section_one, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section_one)
        _selector_question(section_two)

        duplicates = [
            f
            for f in validate_version_calculation_bindings(draft_version)
            if f.validation_code == QUESTION_CODE_DUPLICATE
        ]
        assert [f.question_code for f in duplicates] == [registry_mod.Q_SUBJECT_COMPONENT]

        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        prior.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        assert prior.status == ChecklistVersionStatus.ACTIVE
        _assert_no_success_audit(draft_version)

    def test_duplicate_blocks_activation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section_one = _section(draft_version, code="S1", order=1)
        section_two = _section(draft_version, code="S2", order=2)
        _calculated_question(section_one, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section_one)
        _selector_question(section_two)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED

    def test_duplicate_calculated_codes_are_an_ambiguous_graph(self, draft_version):
        """Two bound questions sharing one code cannot form distinct nodes."""
        section_one = _section(draft_version, code="S1", order=1)
        section_two = _section(draft_version, code="S2", order=2)
        _calculated_question(section_one, "Q_PCT_WW", "percentage_w_w")
        _calculated_question(section_two, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section_one)
        findings = validate_version_calculation_bindings(draft_version)
        assert DUPLICATE_GRAPH_NODE in _codes(findings)


# ===========================================================================
# D. Type and classification
# ===========================================================================


class TestTypeAndClassification:
    def test_wrong_answer_type_on_calculated_target(self, draft_version):
        section = _section(draft_version)
        # CALCULATED_STATUS is also SYSTEM_CALCULATED-compatible, but the
        # registry entry declares calculated_value.
        _calculated_question(
            section,
            "Q_PCT_WW",
            "percentage_w_w",
            answer_type=AnswerType.CALCULATED_STATUS,
        )
        _selector_question(section)
        findings = validate_version_calculation_bindings(draft_version)
        assert WRONG_ANSWER_TYPE in _codes(findings)

    def test_wrong_source_classification_on_bound_question(self, draft_version):
        """A binding on a non-SYSTEM_CALCULATED question fails closed.

        Model.clean() forbids this combination on the authoring path, but rows
        created without full_clean() can hold it, so activation checks it too.
        """
        section = _section(draft_version)
        _question(
            section,
            "Q_MISCLASSIFIED",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.USER_REQUIRED,
            binding="percentage_w_w",
        )
        _selector_question(section)
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == WRONG_SOURCE_CLASSIFICATION
            and f.question_code == "Q_MISCLASSIFIED"
            for f in findings
        )

    def test_wrong_source_classification_blocks_activation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _question(
            section,
            "Q_MISCLASSIFIED",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.USER_REQUIRED,
            binding="percentage_w_w",
        )
        _selector_question(section)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        assert WRONG_SOURCE_CLASSIFICATION in str(response.data)
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        assert draft_version.activated_at is None
        _assert_no_success_audit(draft_version)

    def test_selector_with_wrong_answer_type(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section, answer_type=AnswerType.SHORT_TEXT)
        findings = validate_version_calculation_bindings(draft_version)
        assert SELECTOR_WRONG_ANSWER_TYPE in _codes(findings)

    def test_form_e_dependency_must_be_system_calculated(self, draft_version):
        """A non-calculated question cannot satisfy a prior-outcome dependency."""
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde")
        _question(
            section,
            registry_mod.Q_DAILY_EXPOSURE,
            answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED,
            order=2,
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert DEPENDENCY_NOT_CALCULATED in _codes(findings)


# ===========================================================================
# E. Registry integrity
# ===========================================================================


class TestRegistryIntegrity:
    def test_unknown_calculation_binding_identifier(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == UNKNOWN_REGISTRY_IDENTIFIER
            and f.registry_identifier == "not_a_registry_key"
            for f in findings
        )

    def test_unknown_identifier_blocks_activation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED

    def test_full_mde_chain_validates(self, draft_version):
        """daily_exposure -> percentage_of_iid_mde resolves end to end."""
        section = _section(draft_version)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "daily_exposure", order=1
        )
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=2)
        _selector_question(section)
        assert validate_version_calculation_bindings(draft_version) == ()


# ===========================================================================
# F. Calculation graph (M4D3-DEP-005)
# ===========================================================================


class TestCalculationGraph:
    def test_self_cycle_is_rejected(self, draft_version):
        """A question that is its own upstream dependency has no execution order.

        Q_DAILY_EXPOSURE bound to percentage_of_iid_mde, whose form E dependency
        is Q_DAILY_EXPOSURE, is a self-edge.  This uses the real registry -- no
        patching needed to reach it.
        """
        section = _section(draft_version)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "percentage_of_iid_mde"
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert CALCULATION_GRAPH_CYCLE in _codes(findings)

    def test_self_cycle_blocks_activation_with_zero_mutation(
        self, draft_version, tenant_definition, user_a, api_client_doer, api_client_vp
    ):
        from iig_checklist.models import ChecklistVersion

        prior = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=97,
            created_by=user_a,
            status=ChecklistVersionStatus.ACTIVE,
            effective_date=datetime.date(2025, 1, 1),
        )
        section = _section(draft_version)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "percentage_of_iid_mde"
        )
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        assert CALCULATION_GRAPH_CYCLE in str(response.data)
        draft_version.refresh_from_db()
        prior.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        assert draft_version.activated_at is None
        assert prior.status == ChecklistVersionStatus.ACTIVE
        _assert_no_success_audit(draft_version)

    def test_two_node_cycle_is_rejected(self, draft_version, monkeypatch):
        """A depends on B and B depends on A."""
        _install_registry(
            monkeypatch,
            {
                "cyc_a": _dependent_entry("Q_CYC_B"),
                "cyc_b": _dependent_entry("Q_CYC_A"),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_CYC_A", "cyc_a", order=1)
        _calculated_question(section, "Q_CYC_B", "cyc_b", order=2)
        findings = validate_version_calculation_bindings(draft_version)
        assert CALCULATION_GRAPH_CYCLE in _codes(findings)

    def test_two_node_cycle_blocks_activation(
        self, draft_version, monkeypatch, api_client_doer, api_client_vp
    ):
        _install_registry(
            monkeypatch,
            {
                "cyc_a": _dependent_entry("Q_CYC_B"),
                "cyc_b": _dependent_entry("Q_CYC_A"),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_CYC_A", "cyc_a", order=1)
        _calculated_question(section, "Q_CYC_B", "cyc_b", order=2)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        _assert_no_success_audit(draft_version)

    def test_depth_five_is_accepted(
        self, draft_version, monkeypatch, api_client_doer, api_client_vp
    ):
        assert registry_mod.CALCULATION_MAX_DEPENDENCY_DEPTH == 5
        _chain(monkeypatch, draft_version, 5)
        assert validate_version_calculation_bindings(draft_version) == ()
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 200, response.data
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.ACTIVE

    def test_depth_six_is_rejected(
        self, draft_version, monkeypatch, api_client_doer, api_client_vp
    ):
        _chain(monkeypatch, draft_version, 6)
        findings = validate_version_calculation_bindings(draft_version)
        assert DEPENDENCY_DEPTH_EXCEEDED in _codes(findings)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        _assert_no_success_audit(draft_version)

    def test_cascade_of_ten_is_accepted(
        self, draft_version, monkeypatch, api_client_doer, api_client_vp
    ):
        assert registry_mod.CALCULATION_MAX_CASCADE_NODES == 10
        # Root plus nine consumers -- ten nodes reachable from the root.
        _fan_out(monkeypatch, draft_version, 9)
        assert validate_version_calculation_bindings(draft_version) == ()
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 200, response.data
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.ACTIVE

    def test_cascade_of_eleven_is_rejected(
        self, draft_version, monkeypatch, api_client_doer, api_client_vp
    ):
        _fan_out(monkeypatch, draft_version, 10)
        findings = validate_version_calculation_bindings(draft_version)
        assert CASCADE_NODE_LIMIT_EXCEEDED in _codes(findings)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        _assert_no_success_audit(draft_version)

    def test_unknown_dependency_node(self, draft_version, monkeypatch):
        """The dependency question exists but is not a calculated graph node."""
        _install_registry(monkeypatch, {"needs_upstream": _dependent_entry("Q_PLAIN")})
        section = _section(draft_version)
        _calculated_question(section, "Q_CONSUMER", "needs_upstream", order=1)
        _question(
            section,
            "Q_PLAIN",
            answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED,
            order=2,
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert UNKNOWN_DEPENDENCY_CODE in _codes(findings)

    def test_graph_findings_carry_no_raw_exception_text(self, draft_version):
        section = _section(draft_version)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "percentage_of_iid_mde"
        )
        graph_findings = [
            f
            for f in validate_version_calculation_bindings(draft_version)
            if f.validation_code == CALCULATION_GRAPH_CYCLE
        ]
        assert len(graph_findings) == 1
        message = graph_findings[0].message
        assert "GraphConfigurationError" not in message
        assert "Traceback" not in message
        assert "node_id" not in message


# ===========================================================================
# G. Upstream producer compatibility (M4D3-DEP-011)
# ===========================================================================


class TestUpstreamProducer:
    def test_upstream_without_binding_cannot_satisfy_dependency(self, draft_version):
        """A calculated-but-unbound question produces no outcome to consume."""
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=1)
        _question(
            section,
            registry_mod.Q_DAILY_EXPOSURE,
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            order=2,
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert UPSTREAM_BINDING_IDENTIFIER_MISSING in _codes(findings)

    def test_upstream_with_unknown_registry_identifier(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=1)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "no_such_entry", order=2
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert UPSTREAM_REGISTRY_IDENTIFIER_UNKNOWN in _codes(findings)

    def test_upstream_bound_to_wrong_producer_output_unit(self, draft_version):
        """The exact defect the independent review found.

        Q_DAILY_EXPOSURE is SYSTEM_CALCULATED and resolves uniquely, but it is
        bound to percentage_w_w, which produces percent_w_w -- not the gram/day
        quantity the MDE resolver declares it will consume.  Being calculated is
        not enough; the producer must be the right producer.
        """
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=1)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "percentage_w_w", order=2
        )
        _selector_question(section)
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == UPSTREAM_OUTPUT_UNIT_MISMATCH
            and f.question_code == registry_mod.Q_DAILY_EXPOSURE
            for f in findings
        )

    def test_wrong_producer_blocks_activation_with_zero_mutation(
        self, draft_version, tenant_definition, user_a, api_client_doer, api_client_vp
    ):
        from iig_checklist.models import ChecklistVersion

        prior = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=96,
            created_by=user_a,
            status=ChecklistVersionStatus.ACTIVE,
            effective_date=datetime.date(2025, 1, 1),
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=1)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "percentage_w_w", order=2
        )
        _selector_question(section)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        assert UPSTREAM_OUTPUT_UNIT_MISMATCH in str(response.data)
        draft_version.refresh_from_db()
        prior.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        assert prior.status == ChecklistVersionStatus.ACTIVE
        _assert_no_success_audit(draft_version)

    def test_upstream_answer_type_mismatch(self, draft_version, monkeypatch):
        """The upstream question's answer type must match what its entry emits."""
        _install_registry(
            monkeypatch,
            {
                "producer": _entry(allowed_answer_type=AnswerType.CALCULATED_VALUE.value),
                "consumer": _dependent_entry("Q_PRODUCER"),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_CONSUMER", "consumer", order=1)
        _calculated_question(
            section,
            "Q_PRODUCER",
            "producer",
            order=2,
            answer_type=AnswerType.CALCULATED_STATUS,
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert UPSTREAM_ANSWER_TYPE_MISMATCH in _codes(findings)

    def test_upstream_producer_must_emit_a_calculated_source(
        self, draft_version, monkeypatch
    ):
        """The producing entry itself must declare a system_calculated output.

        An entry that emits an FDA-derived or user-entered value can never
        satisfy a prior-calculation-outcome dependency, however the consuming
        question is classified.
        """
        _install_registry(
            monkeypatch,
            {
                "fda_producer": _entry(
                    allowed_data_source=DataSourceClassification.FDA_DERIVED_DEFAULT.value
                ),
                "consumer": _dependent_entry("Q_PRODUCER"),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_CONSUMER", "consumer", order=1)
        _calculated_question(section, "Q_PRODUCER", "fda_producer", order=2)
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == UPSTREAM_SOURCE_CLASSIFICATION_MISMATCH
            and f.question_code == "Q_PRODUCER"
            for f in findings
        )

    def test_incompatible_dimension_is_rejected(self, draft_version, monkeypatch):
        """A millilitre producer cannot satisfy a gram consumer."""
        _install_registry(
            monkeypatch,
            {
                "volume_producer": _entry(output_unit="millilitre"),
                "mass_consumer": _dependent_entry("Q_VOLUME", unit_source="gram"),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_MASS", "mass_consumer", order=1)
        _calculated_question(section, "Q_VOLUME", "volume_producer", order=2)
        findings = validate_version_calculation_bindings(draft_version)
        assert UPSTREAM_OUTPUT_UNIT_MISMATCH in _codes(findings)

    def test_matching_producer_unit_is_accepted(self, draft_version, monkeypatch):
        _install_registry(
            monkeypatch,
            {
                "producer": _entry(output_unit="gram"),
                "consumer": _dependent_entry("Q_PRODUCER", unit_source="gram"),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_CONSUMER", "consumer", order=1)
        _calculated_question(section, "Q_PRODUCER", "producer", order=2)
        assert validate_version_calculation_bindings(draft_version) == ()


# ===========================================================================
# H. Defensive registry-integrity branches
#
# Unreachable while the immutable approved registry is in force, because
# _validate_registry() rejects these shapes at import time.  Exercised through
# the synthetic-registry seam so the branches are proven, not merely asserted.
# ===========================================================================


class TestDefensiveRegistryBranches:
    def test_disabled_component_selector_form_is_rejected(self, draft_version, monkeypatch):
        """M4D3-FCR-012 -- registry_component_code stays disabled."""
        disabled = MappingProxyType(
            {
                "source": registry_mod.SOURCE_FORMULATION_FIELD,
                "object": "formulation_component",
                "field": "quantity_per_dosage_unit",
                "expected_type": "decimal",
                "component_selector": MappingProxyType(
                    {
                        "type": registry_mod.SELECTOR_REGISTRY_COMPONENT_CODE,
                        "question_code": "Q_ANY",
                    }
                ),
            }
        )
        _install_registry(
            monkeypatch,
            {"disabled_selector": _entry(input_resolvers=MappingProxyType({"q": disabled}))},
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_DISABLED", "disabled_selector")
        findings = validate_version_calculation_bindings(draft_version)
        assert DISABLED_SELECTOR_FORM in _codes(findings)

    def test_dependency_set_mismatch_is_rejected(self, draft_version, monkeypatch):
        """calculation_dependencies must match the form E resolvers."""
        _install_registry(
            monkeypatch,
            {"bad_deps": _entry(calculation_dependencies=("Q_UNDECLARED",))},
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD_DEPS", "bad_deps")
        findings = validate_version_calculation_bindings(draft_version)
        assert DEPENDENCY_MISMATCH in _codes(findings)

    def test_trigger_set_mismatch_is_rejected(self, draft_version, monkeypatch):
        """recalculation_triggers must match the resolver declarations."""
        _install_registry(
            monkeypatch,
            {"bad_triggers": _entry(recalculation_triggers=("Q_UNDECLARED",))},
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD_TRIGGERS", "bad_triggers")
        findings = validate_version_calculation_bindings(draft_version)
        assert TRIGGER_MISMATCH in _codes(findings)

    def test_form_a_question_response_binding_is_validated(self, draft_version, monkeypatch):
        """Form A (question_response) support is generic, defensive code.

        No approved production entry declares a question_response resolver, so
        this branch is unexercised by the real registry.  It is retained because
        the resolver form is approved (M4D3-INP-003), and proven here with a
        synthetic entry rather than left untested.
        """
        form_a = MappingProxyType(
            {
                "source": registry_mod.SOURCE_QUESTION_RESPONSE,
                "question_code": "Q_FORM_A",
                "value_field": "raw_value",
                "expected_type": "decimal",
            }
        )
        _install_registry(
            monkeypatch,
            {
                "form_a": _entry(
                    input_resolvers=MappingProxyType({"x": form_a}),
                    recalculation_triggers=("Q_FORM_A",),
                )
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_USES_FORM_A", "form_a")
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_MISSING and f.question_code == "Q_FORM_A"
            for f in findings
        )

    def test_form_a_binding_resolves_when_present(self, draft_version, monkeypatch):
        form_a = MappingProxyType(
            {
                "source": registry_mod.SOURCE_QUESTION_RESPONSE,
                "question_code": "Q_FORM_A",
                "value_field": "raw_value",
                "expected_type": "decimal",
            }
        )
        _install_registry(
            monkeypatch,
            {
                "form_a": _entry(
                    input_resolvers=MappingProxyType({"x": form_a}),
                    recalculation_triggers=("Q_FORM_A",),
                )
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_USES_FORM_A", "form_a", order=1)
        _question(
            section,
            "Q_FORM_A",
            answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED,
            order=2,
        )
        assert validate_version_calculation_bindings(draft_version) == ()


# ===========================================================================
# I. Isolation, lifecycle and determinism
# ===========================================================================


class TestIsolationAndLifecycle:
    def test_same_code_in_another_version_cannot_satisfy_binding(
        self, draft_version, tenant_definition, user_a
    ):
        from iig_checklist.models import ChecklistVersion

        other = ChecklistVersion.objects.create(
            definition=tenant_definition, version_number=7, created_by=user_a
        )
        other_section = _section(other, code="OTHER", order=1)
        _selector_question(other_section)  # correct code, wrong version

        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")

        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_MISSING
            and f.question_code == registry_mod.Q_SUBJECT_COMPONENT
            for f in findings
        )

    def test_another_tenants_question_cannot_satisfy_binding(
        self, draft_version, tenant_b, user_a
    ):
        """Build real second-tenant content holding the required code.

        Tenant B's checklist contains a perfectly valid Q_SUBJECT_COMPONENT.
        Tenant A's version does not, so the binding must still fail -- the
        lookup is scoped through the persisted ownership chain, not merely
        blocked at the endpoint.
        """
        from iig_checklist.models import ChecklistDefinition, ChecklistVersion

        other_definition = ChecklistDefinition.objects.create(
            code="IIG-TENANT-B",
            title="Tenant B checklist (synthetic)",
            scope_type="tenant",
            tenant=tenant_b,
            created_by=user_a,
        )
        other_version = ChecklistVersion.objects.create(
            definition=other_definition, version_number=1, created_by=user_a
        )
        _selector_question(_section(other_version, code="B1", order=1))

        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")

        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_MISSING
            and f.question_code == registry_mod.Q_SUBJECT_COMPONENT
            for f in findings
        )

    def test_cross_tenant_activation_returns_404(
        self, draft_version, tenant_b, api_client_vp
    ):
        """A caller who *has* the permission still cannot see another tenant.

        The actor is a VP who can legitimately activate in their own tenant, so
        a 404 here proves tenant scoping rather than a permission denial -- and
        avoids leaking whether the version exists.
        """
        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        draft_version.definition.tenant = tenant_b
        draft_version.definition.save(update_fields=["tenant"])
        response = api_client_vp.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/activate/",
            data={},
        )
        assert response.status_code == 404
        draft_version.refresh_from_db()
        assert draft_version.status != ChecklistVersionStatus.ACTIVE

    def test_doer_cannot_activate(self, draft_version, api_client_doer):
        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        response = api_client_doer.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/activate/"
        )
        assert response.status_code == 403

    def test_validation_ordering_is_deterministic(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde")
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w", order=2)
        runs = [
            tuple(
                (f.question_code, f.registry_identifier, f.validation_code)
                for f in validate_version_calculation_bindings(draft_version)
            )
            for _ in range(5)
        ]
        assert len(set(runs)) == 1
        assert runs[0] != ()

    def test_mixed_graph_and_binding_error_ordering_is_stable(
        self, draft_version, monkeypatch
    ):
        """Several simultaneous failures of different categories stay ordered.

        Ordering is keyed on governed fields -- question code, registry
        identifier, validation code, public UUID -- never on insertion order or
        primary key, so repeated runs are byte-equivalent.
        """
        _install_registry(
            monkeypatch,
            {
                "cyc_a": _dependent_entry("Q_CYC_B"),
                "cyc_b": _dependent_entry("Q_CYC_A"),
                "bad_triggers": _entry(recalculation_triggers=("Q_UNDECLARED",)),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_CYC_A", "cyc_a", order=1)
        _calculated_question(section, "Q_CYC_B", "cyc_b", order=2)
        _calculated_question(section, "Q_BAD_TRIGGERS", "bad_triggers", order=3)
        _question(
            section,
            "Q_ORPHAN",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            order=4,
        )

        runs = [
            tuple(f.semantic_key for f in validate_version_calculation_bindings(draft_version))
            for _ in range(5)
        ]
        assert len(set(runs)) == 1
        categories = {key[2] for key in runs[0]}
        assert CALCULATION_GRAPH_CYCLE in categories
        assert TRIGGER_MISMATCH in categories
        assert SYSTEM_CALCULATED_BINDING_MISSING in categories
        assert list(runs[0]) == sorted(runs[0])


# ===========================================================================
# J. Result integrity
# ===========================================================================


class TestResultIntegrity:
    def test_findings_expose_no_internal_ids(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        findings = validate_version_calculation_bindings(draft_version)
        assert findings
        for finding in findings:
            assert "pk" not in finding.message.lower()
            assert "select " not in finding.message.lower()
            assert "traceback" not in finding.message.lower()
            if finding.question_public_id is not None:
                # A public UUID, never a bare integer primary key.
                assert "-" in finding.question_public_id

    def test_error_body_is_structured_and_sanitized(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        body = str(response.data)
        assert "REGISTRY_VALIDATION_FAILED" in body
        assert "not_a_registry_key" in body
        assert "Traceback" not in body

    def test_findings_are_immutable(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        finding = validate_version_calculation_bindings(draft_version)[0]
        with pytest.raises(AttributeError):
            finding.validation_code = "TAMPERED"

    def test_every_emitted_code_is_governed(self, draft_version, monkeypatch):
        """No finding may carry a code outside the approved vocabulary."""
        from iig_checklist.activation_validation import ALLOWED_VALIDATION_CODES

        _install_registry(
            monkeypatch,
            {
                "cyc_a": _dependent_entry("Q_CYC_B"),
                "cyc_b": _dependent_entry("Q_CYC_A"),
            },
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_CYC_A", "cyc_a", order=1)
        _calculated_question(section, "Q_CYC_B", "cyc_b", order=2)
        findings = validate_version_calculation_bindings(draft_version)
        assert findings
        assert _codes(findings) <= ALLOWED_VALIDATION_CODES
