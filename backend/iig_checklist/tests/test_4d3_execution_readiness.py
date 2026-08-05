"""Milestone 4D-3 -- execution-readiness corrections.

Two blockers stood between the closed resolver gate and governed calculation
execution, and both are covered here against real PostgreSQL:

1. ``create_execution()`` wrote the registry *binding identifier* into
   ``CalculationOutcome.calculation_name``, which ``CalculationOutcome.clean()``
   rejects -- so no placeholder could be created for any SYSTEM_CALCULATED
   question and the governed path was unusable.
2. The resolver accepted non-canonical UUID spellings for
   ``_subject_component_public_id`` where M4D3-PRV-005 mandates the canonical
   lowercase hyphenated form.

Nothing here executes a calculation, completes an outcome or creates a
snapshot.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import MappingProxyType

import pytest

from iid_assessment import calculations as engine
from iig_checklist import calculation_registry as registry_mod
from iig_checklist.calculation_inputs import (
    ResolutionContext,
    resolve_calculation_inputs,
)
from iig_checklist.calculation_translation import SUBJECT_COMPONENT_PROVENANCE_KEY
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


def _product(tenant, user, code="PROD-XR-01"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant, product_code=code, proposed_product_name="Synthetic Product",
        active_ingredient="Synthetic Ingredient", dosage_form="tablet", route="oral",
        created_by=user,
    )


def _formulation(product, user):
    from formulations.models import FormulationVersion

    return FormulationVersion.objects.create(
        product=product, version_number=1, status="approved",
        total_dosage_unit_weight=Decimal("1.000000"),
        total_dosage_unit_weight_unit="gram", created_by=user,
    )


def _component(formulation, *, quantity="0.250000", order=1):
    from formulations.models import FormulationComponent

    return FormulationComponent.objects.create(
        formulation_version=formulation, component_type="inactive",
        ingredient_name="Synthetic Excipient",
        quantity_per_dosage_unit=Decimal(quantity), quantity_unit="gram",
        display_order=order,
    )


def _active_version(definition, user, number=1):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=definition, version_number=number, status="active", created_by=user
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


def _calculated(section, code, identifier, *, order=1, answer_type=None):
    return _question(
        section, code, answer_type=answer_type or AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding=identifier, order=order,
    )


def _grant_create_execution(tenant, user):
    """The Doer role already carries iig_checklist.create_execution."""
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(
        tenant=tenant, name="doer", defaults={"is_system": True}
    )
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


@pytest.fixture
def execution_world(db, tenant_a, tenant_definition, user_a, doer_membership):
    """An active version plus an approved formulation, ready for execution."""
    product = _product(tenant_a, user_a)
    formulation = _formulation(product, user_a)
    component = _component(formulation)
    version = _active_version(tenant_definition, user_a)
    section = _section(version)
    return {
        "tenant": tenant_a, "user": user_a, "product": product,
        "formulation": formulation, "component": component,
        "version": version, "section": section,
    }


def _create(world):
    from iig_checklist.services import create_execution

    return create_execution(
        tenant=world["tenant"],
        checklist_version_public_id=str(world["version"].public_id),
        formulation_version_public_id=str(world["formulation"].public_id),
        actor=world["user"],
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


# ===========================================================================
# A. create_execution() placeholder correction
# ===========================================================================


class TestPlaceholderCalculationName:
    def test_governed_path_creates_a_valid_placeholder(self, execution_world):
        """The governed path now creates a valid placeholder end to end.

        This replaces the tripwire that asserted the path was still blocked on
        ``{"inputs", "input_provenance"}``. Both defects are fixed: the binding
        identifier is no longer written into ``calculation_name``, and the two
        JSONFields accept their own ``{}`` defaults.
        """
        from iig_checklist.models import CalculationOutcome, ChecklistResponse

        _calculated(execution_world["section"], "Q_PCT_WW", "percentage_w_w")
        execution = _create(execution_world)

        response = ChecklistResponse.objects.get(execution=execution)
        outcomes = list(CalculationOutcome.objects.filter(response=response))
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.calculation_name == "calculate_percentage_w_w"
        assert outcome.calculation_name != "percentage_w_w"
        outcome.full_clean()  # the row the governed path just wrote is valid

    def test_placeholder_carries_no_result(self, execution_world):
        """A placeholder is a slot, not a result."""
        from iig_checklist.models import CalculationOutcome

        _calculated(execution_world["section"], "Q_PCT_WW", "percentage_w_w")
        _create(execution_world)
        outcome = CalculationOutcome.objects.get()
        assert outcome.status == CalculationStatus.DATA_REQUIRED
        assert outcome.value is None
        assert outcome.unit == ""
        assert outcome.inputs == {}
        assert outcome.input_provenance == {}
        assert outcome.generated_at is None
        assert outcome.reason_code == ""
        assert outcome.source_assessment_snapshot_public_id is None
        # Completed-outcome provenance belongs to the execution phase.
        assert SUBJECT_COMPONENT_PROVENANCE_KEY not in outcome.input_provenance
        assert "_registry_binding_version" not in outcome.input_provenance

    def test_two_calculated_questions_produce_two_valid_placeholders(
        self, execution_world
    ):
        from iig_checklist.models import CalculationOutcome

        _calculated(execution_world["section"], "Q_PCT_WW", "percentage_w_w", order=1)
        _calculated(execution_world["section"], "Q_DAILY", "daily_exposure", order=2)
        _create(execution_world)
        outcomes = list(CalculationOutcome.objects.all())
        assert len(outcomes) == 2
        assert sorted(o.calculation_name for o in outcomes) == [
            "calculate_daily_exposure",
            "calculate_percentage_w_w",
        ]
        for outcome in outcomes:
            outcome.full_clean()

    def test_one_placeholder_per_calculated_response(self, execution_world):
        from iig_checklist.models import CalculationOutcome, ChecklistResponse

        _calculated(execution_world["section"], "Q_PCT_WW", "percentage_w_w", order=1)
        _question(
            execution_world["section"], "Q_PLAIN", answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED, order=2,
        )
        execution = _create(execution_world)
        assert ChecklistResponse.objects.filter(execution=execution).count() == 2
        assert CalculationOutcome.objects.count() == 1

    def test_registry_lookup_yields_the_approved_function_name(self):
        """The value create_execution() now writes, verified at the source.

        Asserts the mapping the service performs -- identifier in, approved
        calculation function name out -- without depending on the row being
        persistable.
        """
        from iig_checklist.calculation_registry import get_entry

        assert get_entry("percentage_w_w").calculation_name == "calculate_percentage_w_w"
        assert get_entry("daily_exposure").calculation_name == "calculate_daily_exposure"
        for identifier, entry in registry_mod.CALCULATION_BINDING_REGISTRY.items():
            assert entry.calculation_name != identifier
            assert entry.calculation_name.startswith("calculate_")

    def test_approved_function_names_pass_model_validation(self):
        """The corrected value is accepted where the old one was rejected."""
        from django.core.exceptions import ValidationError as DjangoValidationError

        from iig_checklist.models import CalculationOutcome

        for identifier, entry in registry_mod.CALCULATION_BINDING_REGISTRY.items():
            CalculationOutcome(
                calculation_name=entry.calculation_name,
                status=CalculationStatus.DATA_REQUIRED,
            ).clean()  # the corrected value: accepted
            with pytest.raises(DjangoValidationError):
                CalculationOutcome(
                    calculation_name=identifier,
                    status=CalculationStatus.DATA_REQUIRED,
                ).clean()  # the old value: rejected

    def test_non_calculated_questions_still_create_executions(self, execution_world):
        """The uncalculated path is unaffected by the correction."""
        from iig_checklist.models import CalculationOutcome, ChecklistResponse

        _question(
            execution_world["section"], "Q_PLAIN", answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED,
        )
        execution = _create(execution_world)
        assert ChecklistResponse.objects.filter(execution=execution).count() == 1
        assert CalculationOutcome.objects.count() == 0


# ===========================================================================
# B. Fail-closed placeholder validation
# ===========================================================================


class TestPlaceholderFailsClosed:
    def _assert_nothing_persisted(self):
        from audit.models import AuditEvent
        from iig_checklist.models import (
            CalculationOutcome,
            ChecklistExecution,
            ChecklistResponse,
        )

        assert ChecklistExecution.objects.count() == 0
        assert ChecklistResponse.objects.count() == 0
        assert CalculationOutcome.objects.count() == 0
        assert not AuditEvent.objects.filter(
            event_type="iig_checklist.execution.created"
        ).exists()

    def test_unknown_identifier_rolls_everything_back(self, execution_world):
        from iig_checklist.services import InvalidCalculationBinding

        _calculated(execution_world["section"], "Q_BAD", "not_a_registry_key")
        with pytest.raises(InvalidCalculationBinding):
            _create(execution_world)
        self._assert_nothing_persisted()

    def test_blank_identifier_rolls_everything_back(self, execution_world):
        from iig_checklist.services import InvalidCalculationBinding

        _question(
            execution_world["section"], "Q_ORPHAN",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
        )
        with pytest.raises(InvalidCalculationBinding):
            _create(execution_world)
        self._assert_nothing_persisted()

    def test_wrong_answer_type_rolls_everything_back(self, execution_world):
        from iig_checklist.services import InvalidCalculationBinding

        _calculated(
            execution_world["section"], "Q_PCT_WW", "percentage_w_w",
            answer_type=AnswerType.CALCULATED_STATUS,
        )
        with pytest.raises(InvalidCalculationBinding):
            _create(execution_world)
        self._assert_nothing_persisted()

    def test_wrong_source_classification_rolls_everything_back(
        self, execution_world, monkeypatch
    ):
        """Only reachable with a synthetic entry: the approved registry's
        allowed_data_source is always system_calculated."""
        from iig_checklist.services import InvalidCalculationBinding

        _install(
            monkeypatch,
            {
                "fda_scoped": _entry(
                    allowed_data_source=(
                        DataSourceClassification.FDA_DERIVED_DEFAULT.value
                    )
                )
            },
        )
        _calculated(execution_world["section"], "Q_FDA", "fda_scoped")
        with pytest.raises(InvalidCalculationBinding):
            _create(execution_world)
        self._assert_nothing_persisted()

    def test_valid_question_beside_invalid_one_is_also_rolled_back(
        self, execution_world
    ):
        """No partial execution: a good question does not survive a bad one.

        The valid question is ordered first, so it reaches placeholder creation
        and currently trips the JSONField defect before the invalid binding is
        ever examined. Whichever failure fires, the whole transaction must roll
        back -- that is what this asserts.
        """
        from django.core.exceptions import ValidationError as DjangoValidationError

        from iig_checklist.services import InvalidCalculationBinding

        _calculated(execution_world["section"], "Q_GOOD", "percentage_w_w", order=1)
        _calculated(execution_world["section"], "Q_BAD", "not_a_registry_key", order=2)
        with pytest.raises((InvalidCalculationBinding, DjangoValidationError)):
            _create(execution_world)
        self._assert_nothing_persisted()


# ===========================================================================
# C. Execution creation still behaves
# ===========================================================================


class TestExecutionCreationUnchanged:
    """The uncalculated path must behave exactly as before the correction."""

    def _plain_question(self, world):
        return _question(
            world["section"], "Q_PLAIN", answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED,
        )

    def test_success_still_emits_the_created_audit(
        self, execution_world, django_capture_on_commit_callbacks
    ):
        """The audit is emitted on commit, so the callbacks must be captured."""
        from audit.models import AuditEvent

        self._plain_question(execution_world)
        with django_capture_on_commit_callbacks(execute=True):
            execution = _create(execution_world)
        assert AuditEvent.objects.filter(
            event_type="iig_checklist.execution.created",
            resource_id=str(execution.public_id),
        ).exists()

    def test_execution_is_scoped_to_its_tenant(self, execution_world, tenant_b):
        from iig_checklist.models import ChecklistExecution

        self._plain_question(execution_world)
        execution = _create(execution_world)
        assert execution.tenant_id == execution_world["tenant"].id
        assert not ChecklistExecution.objects.visible_to(tenant_b).exists()
        assert ChecklistExecution.objects.visible_to(execution_world["tenant"]).exists()

    def test_created_execution_starts_in_draft(self, execution_world):
        self._plain_question(execution_world)
        execution = _create(execution_world)
        assert execution.status == ExecutionStatus.DRAFT

    def test_no_calculation_function_is_invoked(self, execution_world, monkeypatch):
        """Placeholder creation must never run the calculation itself.

        A tripwire replaces the bound function, so any invocation would fail
        the test loudly. The placeholder is created successfully and the
        function stays untouched.
        """
        from iig_checklist.models import CalculationOutcome

        called = []

        def _tripwire(*args, **kwargs):
            called.append(True)
            raise AssertionError("calculation function invoked during placeholder creation")

        _install(
            monkeypatch,
            {
                "percentage_w_w": _entry(
                    calculation_name="calculate_percentage_w_w", function=_tripwire
                )
            },
        )
        _calculated(execution_world["section"], "Q_PCT_WW", "percentage_w_w")
        _create(execution_world)
        assert called == []
        assert CalculationOutcome.objects.get().value is None


# ===========================================================================
# D. Canonical subject-component UUID provenance (M4D3-PRV-005)
# ===========================================================================


@pytest.fixture
def resolver_world(execution_world):
    """An execution whose MDE consumer depends on a daily-exposure outcome.

    Rows are built directly rather than through ``create_execution()``: that
    path cannot yet create a calculated placeholder (see
    ``TestPlaceholderCalculationName``), and these tests are about the
    resolver's canonical-UUID rule, not about execution creation.
    """
    from iig_checklist.models import (
        CalculationOutcome,
        ChecklistExecution,
        ChecklistResponse,
    )

    section = execution_world["section"]
    selector_q = _question(
        section, registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED, order=1,
    )
    upstream_q = _calculated(
        section, registry_mod.Q_DAILY_EXPOSURE, "daily_exposure", order=2
    )
    target = _calculated(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=3)

    execution = ChecklistExecution.objects.create(
        tenant=execution_world["tenant"],
        checklist_version=execution_world["version"],
        formulation_version=execution_world["formulation"],
        status=ExecutionStatus.DRAFT,
        created_by=execution_world["user"],
    )
    ChecklistResponse.objects.create(
        execution=execution, question=selector_q,
        data_source_type_snapshot=selector_q.data_source_classification,
        raw_value={"public_id": str(execution_world["component"].public_id)},
    )
    upstream_response = ChecklistResponse.objects.create(
        execution=execution, question=upstream_q,
        data_source_type_snapshot=upstream_q.data_source_classification,
    )
    outcome = CalculationOutcome.objects.create(
        response=upstream_response, calculation_name="calculate_daily_exposure",
        status=CalculationStatus.DATA_REQUIRED,
    )
    execution_world.update(
        {
            "execution": execution,
            "target": target,
            "upstream_response": upstream_response,
            "outcome": outcome,
        }
    )
    return execution_world


def _snapshot(world, component=None):
    from iid_assessment.models import AssessmentSnapshot

    return AssessmentSnapshot.objects.create(
        tenant=world["tenant"],
        formulation_component_public_id=(component or world["component"]).public_id,
        formulation_version_public_id=world["formulation"].public_id,
        iid_mde=Decimal("2.000000"), iid_mde_unit="gram",
    )


def _complete_upstream(world, recorded_component):
    """Mark the upstream placeholder complete with a given provenance value.

    This is the only place these tests write an outcome value, and it exists
    solely to give the resolver something to read; no calculation is executed.
    """
    outcome = world["outcome"]
    outcome.status = CalculationStatus.COMPLETE
    outcome.value = Decimal("0.750000")
    outcome.unit = "gram"
    outcome.input_provenance = {SUBJECT_COMPONENT_PROVENANCE_KEY: recorded_component}
    outcome.save(
        update_fields=["status", "value", "unit", "input_provenance", "updated_at"]
    )
    return outcome


def _resolve(world):
    return resolve_calculation_inputs(
        execution=world["execution"], target_question=world["target"],
        registry_identifier="percentage_of_iid_mde", actor=world["user"],
        locked_context=ResolutionContext(assessment_snapshot=_snapshot(world)),
    )


def _codes(result):
    return set(result.failure_codes)


class TestCanonicalComponentProvenance:
    def test_canonical_uuid_is_accepted(self, resolver_world):
        canonical = str(resolver_world["component"].public_id)
        assert canonical == canonical.lower()
        assert len(canonical) == 36
        _complete_upstream(resolver_world, canonical)
        result = _resolve(resolver_world)
        assert result.resolved, result.failure_codes
        assert result.subject_component_public_id == canonical

    @pytest.mark.parametrize(
        "spelling",
        [
            pytest.param(lambda u: str(u).upper(), id="uppercase"),
            pytest.param(lambda u: "{" + str(u) + "}", id="braced"),
            pytest.param(lambda u: str(u).replace("-", ""), id="compact"),
            pytest.param(lambda u: f"urn:uuid:{u}", id="urn"),
            pytest.param(lambda u: f"  {u}  ", id="whitespace-padded"),
            pytest.param(lambda u: f"{u}\n", id="trailing-newline"),
        ],
    )
    def test_non_canonical_uuid_is_rejected(self, resolver_world, spelling):
        """M4D3-PRV-005 -- the canonical rendering is the stored form."""
        component_uuid = resolver_world["component"].public_id
        _complete_upstream(resolver_world, spelling(component_uuid))
        result = _resolve(resolver_world)
        assert not result.resolved
        assert "INPUT_VALUE_INVALID" in _codes(result)
        assert dict(result.kwargs) == {}

    def test_malformed_uuid_is_rejected(self, resolver_world):
        _complete_upstream(resolver_world, "not-a-uuid-at-all")
        result = _resolve(resolver_world)
        assert "INPUT_VALUE_INVALID" in _codes(result)

    def test_wrong_component_stays_a_component_mismatch(self, resolver_world):
        """A canonical UUID for the wrong component is a different failure."""
        other = _component(resolver_world["formulation"], quantity="0.100000", order=9)
        _complete_upstream(resolver_world, str(other.public_id))
        result = _resolve(resolver_world)
        assert not result.resolved
        # It resolves as the inherited component, then the snapshot disagrees.
        assert "INPUT_VALUE_INVALID" not in _codes(result)
        assert "ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH" in _codes(result)

    def test_foreign_component_uuid_is_not_leaked(self, resolver_world, user_a):
        """A component outside this formulation must not be echoed back."""
        foreign_product = _product(resolver_world["tenant"], user_a, code="PROD-XR-FOR")
        foreign_formulation = _formulation(foreign_product, user_a)
        foreign_component = _component(foreign_formulation)
        _complete_upstream(resolver_world, str(foreign_component.public_id))
        result = _resolve(resolver_world)
        assert "UPSTREAM_CALCULATION_COMPONENT_MISMATCH" in _codes(result)
        for failure in result.failures:
            assert str(foreign_component.public_id) not in failure.message

    def test_rejection_writes_nothing_and_emits_no_audit(self, resolver_world):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from audit.models import AuditEvent
        from iid_assessment.models import AssessmentSnapshot
        from iig_checklist.models import CalculationOutcome, ChecklistResponse

        _complete_upstream(
            resolver_world, str(resolver_world["component"].public_id).upper()
        )
        before = (
            ChecklistResponse.objects.count(),
            CalculationOutcome.objects.count(),
            AssessmentSnapshot.objects.count(),
            AuditEvent.objects.count(),
        )
        snapshot = _snapshot(resolver_world)
        with CaptureQueriesContext(connection) as captured:
            result = resolve_calculation_inputs(
                execution=resolver_world["execution"],
                target_question=resolver_world["target"],
                registry_identifier="percentage_of_iid_mde",
                actor=resolver_world["user"],
                locked_context=ResolutionContext(assessment_snapshot=snapshot),
            )
        assert not result.resolved
        verbs = [
            q["sql"].strip().split(None, 1)[0].upper() for q in captured.captured_queries
        ]
        assert not {"INSERT", "UPDATE", "DELETE"} & set(verbs), verbs
        after = (
            ChecklistResponse.objects.count(),
            CalculationOutcome.objects.count(),
            AssessmentSnapshot.objects.count() - 1,  # the snapshot built above
            AuditEvent.objects.count(),
        )
        assert before == after

    def test_uuid_module_would_have_accepted_the_rejected_forms(self, resolver_world):
        """Proves the control is the canonical check, not UUID parsing.

        Every spelling rejected above parses cleanly; only the canonical-form
        comparison distinguishes them.
        """
        component_uuid = resolver_world["component"].public_id
        for spelling in (
            str(component_uuid).upper(),
            "{" + str(component_uuid) + "}",
            str(component_uuid).replace("-", ""),
            f"urn:uuid:{component_uuid}",
        ):
            assert uuid.UUID(spelling) == component_uuid
            assert spelling != str(component_uuid)


# ===========================================================================
# E. Completed-outcome invariant (M4D3-PRV-002/005/007)
#
# blank=True lets a placeholder hold {}. On its own that would also let a
# COMPLETE row carrying a real regulated number be saved with no provenance at
# all, so clean() gains a status-dependent invariant. These tests validate the
# model directly; nothing here executes a calculation or completes an outcome
# through a service, because no such service exists yet.
# ===========================================================================

BINDING_VERSION_KEY = "_registry_binding_version"

#: percentage_w_w declares a component_selector -> component-scoped.
COMPONENT_SCOPED_NAME = "calculate_percentage_w_w"
#: percentage_of_iid_mde has no selector; it inherits from its form E upstream.
INHERITING_NAME = "calculate_percentage_of_mde"


def _outcome(**overrides):
    from iig_checklist.models import CalculationOutcome

    base = {
        "calculation_name": COMPONENT_SCOPED_NAME,
        "status": CalculationStatus.COMPLETE,
        "value": Decimal("12.5000000000"),
        "unit": "percent_w_w",
        "input_provenance": {
            BINDING_VERSION_KEY: "1.0.0",
            "quantity_per_unit_grams": {"source": "formulation_component"},
            SUBJECT_COMPONENT_PROVENANCE_KEY: str(uuid.uuid4()),
        },
    }
    base.update(overrides)
    return CalculationOutcome(**base)


def _clean_errors(outcome):
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        outcome.clean()
    except DjangoValidationError as exc:
        return set(exc.message_dict)
    return set()


class TestPlaceholderStatesRemainValid:
    """The invariant must not touch statuses that carry no result."""

    @pytest.mark.parametrize(
        "status",
        [
            CalculationStatus.DATA_REQUIRED,
            CalculationStatus.CALCULATING,
            CalculationStatus.ERROR,
        ],
    )
    def test_incomplete_statuses_accept_empty_provenance(self, status):
        outcome = _outcome(
            status=status, value=None, unit="", input_provenance={}, inputs={}
        )
        assert _clean_errors(outcome) == set()


class TestCompletedOutcomeInvariant:
    def test_valid_component_scoped_completed_outcome(self):
        assert _clean_errors(_outcome()) == set()

    def test_valid_inheriting_completed_outcome(self):
        """An MDE calculation has no selector but inherits its component."""
        outcome = _outcome(
            calculation_name=INHERITING_NAME,
            unit="percent_of_mde",
            input_provenance={
                BINDING_VERSION_KEY: "1.0.0",
                "converted_proposed_daily_exposure": {"source": "calculation_outcome"},
                SUBJECT_COMPONENT_PROVENANCE_KEY: str(uuid.uuid4()),
            },
        )
        assert _clean_errors(outcome) == set()

    def test_inheriting_outcome_may_omit_the_component(self):
        outcome = _outcome(
            calculation_name=INHERITING_NAME,
            input_provenance={
                BINDING_VERSION_KEY: "1.0.0",
                "converted_proposed_daily_exposure": {"source": "calculation_outcome"},
            },
        )
        assert _clean_errors(outcome) == set()

    def test_null_value_is_rejected(self):
        assert "value" in _clean_errors(_outcome(value=None))

    def test_empty_provenance_is_rejected(self):
        assert "input_provenance" in _clean_errors(_outcome(input_provenance={}))

    def test_missing_binding_version_is_rejected(self):
        outcome = _outcome(
            input_provenance={
                "quantity_per_unit_grams": {"source": "formulation_component"},
                SUBJECT_COMPONENT_PROVENANCE_KEY: str(uuid.uuid4()),
            }
        )
        assert "input_provenance" in _clean_errors(outcome)

    @pytest.mark.parametrize(
        "version", ["1.0", "1.0.0.0", "v1.0.0", "", "one.zero.zero", 100],
        ids=["two-part", "four-part", "prefixed", "empty", "words", "non-string"],
    )
    def test_malformed_binding_version_is_rejected(self, version):
        outcome = _outcome(
            input_provenance={
                BINDING_VERSION_KEY: version,
                "quantity_per_unit_grams": {"source": "formulation_component"},
                SUBJECT_COMPONENT_PROVENANCE_KEY: str(uuid.uuid4()),
            }
        )
        assert "input_provenance" in _clean_errors(outcome)

    def test_historical_binding_version_is_accepted(self):
        """Provenance is evidence: an older binding stays valid after a bump.

        The format is enforced; equality with today's registry deliberately is
        not, or every historical record would be invalidated by a version
        increment.
        """
        outcome = _outcome(
            input_provenance={
                BINDING_VERSION_KEY: "0.9.3",
                "quantity_per_unit_grams": {"source": "formulation_component"},
                SUBJECT_COMPONENT_PROVENANCE_KEY: str(uuid.uuid4()),
            }
        )
        assert _clean_errors(outcome) == set()

    def test_provenance_without_any_input_descriptor_is_rejected(self):
        """Reserved keys alone record no inputs (M4D3-PRV-002)."""
        outcome = _outcome(
            input_provenance={
                BINDING_VERSION_KEY: "1.0.0",
                SUBJECT_COMPONENT_PROVENANCE_KEY: str(uuid.uuid4()),
            }
        )
        assert "input_provenance" in _clean_errors(outcome)

    def test_component_scoped_outcome_requires_the_component(self):
        outcome = _outcome(
            input_provenance={
                BINDING_VERSION_KEY: "1.0.0",
                "quantity_per_unit_grams": {"source": "formulation_component"},
            }
        )
        assert SUBJECT_COMPONENT_PROVENANCE_KEY in _clean_errors(outcome)

    @pytest.mark.parametrize(
        "spelling",
        [
            pytest.param(lambda u: str(u).upper(), id="uppercase"),
            pytest.param(lambda u: "{" + str(u) + "}", id="braced"),
            pytest.param(lambda u: str(u).replace("-", ""), id="compact"),
            pytest.param(lambda u: f"urn:uuid:{u}", id="urn"),
            pytest.param(lambda u: "not-a-uuid", id="malformed"),
            pytest.param(lambda u: 12345, id="non-string"),
        ],
    )
    def test_non_canonical_component_uuid_is_rejected(self, spelling):
        value = uuid.uuid4()
        outcome = _outcome(
            input_provenance={
                BINDING_VERSION_KEY: "1.0.0",
                "quantity_per_unit_grams": {"source": "formulation_component"},
                SUBJECT_COMPONENT_PROVENANCE_KEY: spelling(value),
            }
        )
        assert SUBJECT_COMPONENT_PROVENANCE_KEY in _clean_errors(outcome)

    def test_component_key_prohibited_when_neither_selected_nor_inherited(
        self, monkeypatch
    ):
        """Only reachable with a synthetic entry: every approved entry either
        selects a component or inherits one."""
        _install(
            monkeypatch,
            {
                "standalone": _entry(
                    calculation_name=COMPONENT_SCOPED_NAME,
                    input_resolvers=MappingProxyType({}),
                    calculation_dependencies=(),
                )
            },
        )
        outcome = _outcome(
            input_provenance={
                BINDING_VERSION_KEY: "1.0.0",
                "some_input": {"source": "constant"},
                SUBJECT_COMPONENT_PROVENANCE_KEY: str(uuid.uuid4()),
            }
        )
        assert SUBJECT_COMPONENT_PROVENANCE_KEY in _clean_errors(outcome)

    def test_unknown_calculation_name_is_rejected(self):
        """The pre-existing non-field check still fires first, unchanged."""
        from django.core.exceptions import ValidationError as DjangoValidationError

        with pytest.raises(DjangoValidationError, match="not one of the six"):
            _outcome(calculation_name="calculate_something_else").clean()

    def test_approved_name_that_no_longer_resolves_is_rejected(self, monkeypatch):
        """An approved name absent from the registry fails on its own field.

        Only reachable with a synthetic registry: the six approved names and
        the six registry entries are the same set.
        """
        _install(monkeypatch, {"other": _entry(calculation_name="calculate_daily_exposure")})
        outcome = _outcome(calculation_name=COMPONENT_SCOPED_NAME)
        assert "calculation_name" in _clean_errors(outcome)

    def test_non_mapping_provenance_is_rejected(self):
        assert "input_provenance" in _clean_errors(_outcome(input_provenance=["a"]))

    def test_no_database_id_appears_in_error_messages(self):
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            _outcome(value=None, input_provenance={}).clean()
        except DjangoValidationError as exc:
            for messages in exc.message_dict.values():
                for message in messages:
                    lowered = message.lower()
                    assert "traceback" not in lowered
                    assert "select " not in lowered
                    assert "object at" not in lowered


class TestCompletedOutcomePersistence:
    """The invariant binds through full_clean(), not only a direct clean()."""

    def test_valid_completed_outcome_saves(self, resolver_world):
        from iig_checklist.models import CalculationOutcome

        outcome = resolver_world["outcome"]
        outcome.status = CalculationStatus.COMPLETE
        outcome.value = Decimal("0.7500000000")
        outcome.unit = "gram"
        outcome.input_provenance = {
            BINDING_VERSION_KEY: "1.0.0",
            "quantity_per_dosage_unit": {"source": "formulation_component"},
            SUBJECT_COMPONENT_PROVENANCE_KEY: str(
                resolver_world["component"].public_id
            ),
        }
        outcome.full_clean()
        outcome.save()
        assert CalculationOutcome.objects.get(pk=outcome.pk).value == Decimal(
            "0.7500000000"
        )

    def test_completed_outcome_without_provenance_cannot_be_saved(
        self, resolver_world
    ):
        from django.core.exceptions import ValidationError as DjangoValidationError

        outcome = resolver_world["outcome"]
        outcome.status = CalculationStatus.COMPLETE
        outcome.value = Decimal("0.7500000000")
        outcome.unit = "gram"
        with pytest.raises(DjangoValidationError) as raised:
            outcome.full_clean()
        assert "input_provenance" in raised.value.message_dict
