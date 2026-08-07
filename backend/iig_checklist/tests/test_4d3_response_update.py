"""Milestone 4D-3 -- the governed response-update service and its cascade trigger.

Part 4 (`update_checklist_response()`) and Part 5 (the `expected_version`
contract) of the approved specification, exercised end to end against real
PostgreSQL rows and the real cascade.

The world here is the one the cascade tests use -- the approved six-entry
registry behind a `Q_SUBJECT_COMPONENT` selector -- but reached through the
governed HTTP endpoint rather than by calling the service directly, because the
point of this module is the wiring:

    PATCH /executions/{id}/responses/{id}/
      -> update_checklist_response()          (Part 4)
        -> recalculate_dependents()           (M4D3-RCL-001)
          -> execute_calculation_response()   per target

Nothing here mocks the writer, the resolver or the engine.
"""

from __future__ import annotations

import inspect
import textwrap
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from iig_checklist import calculation_registry as registry_mod
from iig_checklist import cascade as cascade_mod
from iig_checklist.enums import (
    AnswerType,
    CalculationStatus,
    Criticality,
    DataSourceClassification,
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
# Persisted content -- the approved six-calculation world
# ---------------------------------------------------------------------------


def _iid_setup():
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
        official_source_reference="ref", source_checksum_sha256="e" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )
    ingredient = IIDIngredient.objects.create(
        canonical_name="Update Excipient", normalized_name="UPDATE EXCIPIENT"
    )
    IIDPrecedentRecord.objects.create(
        release=release, ingredient=ingredient,
        ingredient_name_raw="Update Excipient",
        route_raw="ORAL", route_normalized=route,
        dosage_form_raw="TABLET", dosage_form_normalized=dosage_form,
        potency_amount=Decimal("1.000000"), potency_unit_raw="G",
        potency_unit_normalized=gram,
        maximum_daily_exposure=Decimal("2.000000"), mde_unit_raw="G",
        mde_unit_normalized=gram,
        raw_row_checksum="f" * 64,
        calculability_status=IIDCalculabilityStatus.CALCULABLE,
    )
    return ingredient


def _question(section, code, *, answer_type, classification, binding="", order=1):
    from iig_checklist.models import ChecklistQuestion

    return ChecklistQuestion.objects.create(
        section=section, code=code, question_text=f"Q {code}", display_order=order,
        answer_type=answer_type, data_source_classification=classification,
        calculation_binding_identifier=binding, criticality=Criticality.LOW,
    )


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    """An execution carrying all six approved calculations behind the selector."""
    from formulations.models import (
        FormulationComponent,
        FormulationVersion,
        ProductDevelopmentRecord,
    )
    from iig_checklist.models import (
        CalculationOutcome,
        ChecklistResponse,
        ChecklistSection,
        ChecklistVersion,
    )
    from iig_checklist.services import create_execution

    ingredient = _iid_setup()
    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant_a, product_code="PROD-UPD-01",
        proposed_product_name="Update Product",
        active_ingredient="Update Ingredient", dosage_form="tablet", route="oral",
        created_by=user_a,
    )
    formulation = FormulationVersion.objects.create(
        product=product, version_number=1, status="approved",
        total_dosage_unit_weight=Decimal("1.000000"),
        total_dosage_unit_weight_unit="gram",
        maximum_dosage_units_per_day=Decimal("4.0000"), created_by=user_a,
    )
    component = FormulationComponent.objects.create(
        formulation_version=formulation, component_type="inactive",
        ingredient_name="Update Excipient",
        resolved_ingredient_public_id=ingredient.public_id,
        quantity_per_dosage_unit=Decimal("0.250000"), quantity_unit="gram",
        display_order=1,
    )
    version = ChecklistVersion.objects.create(
        definition=tenant_definition, version_number=1, status="active",
        created_by=user_a,
    )
    section = ChecklistSection.objects.create(
        checklist_version=version, code="S1", title="Section S1",
        display_order=1, criticality=Criticality.MEDIUM,
    )
    selector_q = _question(
        section, registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED, order=1,
    )
    free_q = _question(
        section, "Q_FREE_TEXT", answer_type=AnswerType.SHORT_TEXT,
        classification=DataSourceClassification.USER_REQUIRED, order=8,
    )
    calc_codes = {
        "percentage_w_w": "Q_PCT_WW",
        "daily_exposure": registry_mod.Q_DAILY_EXPOSURE,
        "percentage_of_iid_potency": "Q_PCT_POT",
        "difference_from_iid_potency": "Q_DIF_POT",
        "percentage_of_iid_mde": "Q_PCT_MDE",
        "difference_from_iid_mde": "Q_DIF_MDE",
    }
    questions = {
        key: _question(
            section, code, answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding=key, order=index + 2,
        )
        for index, (key, code) in enumerate(calc_codes.items())
    }
    execution = create_execution(
        tenant=tenant_a,
        checklist_version_public_id=str(version.public_id),
        formulation_version_public_id=str(formulation.public_id),
        actor=user_a,
    )
    responses = {
        key: ChecklistResponse.objects.get(execution=execution, question=q)
        for key, q in questions.items()
    }
    return {
        "tenant": tenant_a, "user": user_a, "execution": execution,
        "component": component, "formulation": formulation, "version": version,
        "questions": questions, "responses": responses,
        "selector_response": ChecklistResponse.objects.get(
            execution=execution, question=selector_q
        ),
        "free_response": ChecklistResponse.objects.get(
            execution=execution, question=free_q
        ),
        "outcomes": {
            key: CalculationOutcome.objects.get(response=r)
            for key, r in responses.items()
        },
    }


def _url(world, response=None):
    target = response if response is not None else world["selector_response"]
    return reverse(
        "iig_checklist:execution-response-update",
        kwargs={
            "public_id": world["execution"].public_id,
            "response_public_id": target.public_id,
        },
    )


def _select_component(world, client, *, expected_version=None, response=None):
    """PATCH the subject-component selector -- the governed cascade trigger."""
    target = response if response is not None else world["selector_response"]
    target.refresh_from_db()
    body = {
        "raw_value": {"public_id": str(world["component"].public_id)},
        "expected_version": (
            target.version if expected_version is None else expected_version
        ),
    }
    return client.patch(_url(world, target), body, format="json")


def _error_code(resp):
    """The governed ``error_code``, whichever envelope carried it.

    ``common.exceptions.regx_exception_handler`` wraps every *raised* DRF error
    as ``{"error": {"status": ..., "detail": ...}}``, and a serializer error
    dict is normalised to ``{key: [value]}`` on the way through. A view that
    *returns* a ``Response`` directly is not an exception and keeps its flat
    shape. Both are governed contracts, so this reads either.
    """
    data = resp.data
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        data = data["error"].get("detail", {})
    code = data.get("error_code") if isinstance(data, dict) else None
    if isinstance(code, list):
        code = code[0] if code else None
    return code


def _outcome(world, key):
    from iig_checklist.models import CalculationOutcome

    return CalculationOutcome.objects.get(response=world["responses"][key])


def _fingerprint(world):
    """Everything a rejected update must leave untouched."""
    from audit.models import AuditEvent
    from iid_assessment.models import AssessmentSnapshot
    from iig_checklist.models import ChecklistResponse, ChecklistResponseHistory

    return {
        "outcomes": {
            key: (
                _outcome(world, key).status,
                _outcome(world, key).value,
                _outcome(world, key).updated_at,
            )
            for key in ALL_KEYS
        },
        "responses": dict(
            ChecklistResponse.objects.filter(
                execution=world["execution"]
            ).values_list("pk", "version")
        ),
        "raw_values": dict(
            ChecklistResponse.objects.filter(
                execution=world["execution"]
            ).values_list("pk", "raw_value")
        ),
        "history": ChecklistResponseHistory.objects.count(),
        "snapshots": AssessmentSnapshot.objects.count(),
        "audit": AuditEvent.objects.count(),
    }


# ===========================================================================
# A. Part 5 -- the expected_version contract
# ===========================================================================


class TestExpectedVersionContract:
    def test_an_omitted_expected_version_is_rejected(self, world, api_client_doer):
        """M4D3-VER-004 -- 400, a governed code, and no write."""
        before = _fingerprint(world)
        resp = api_client_doer.patch(
            _url(world),
            {"raw_value": {"public_id": str(world["component"].public_id)}},
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "expected_version_required"
        assert _fingerprint(world) == before

    def test_a_stale_expected_version_is_rejected(self, world, api_client_doer):
        """M4D3-VER-005 -- 409, no write, no history, no increment, no audit."""
        before = _fingerprint(world)
        resp = _select_component(world, api_client_doer, expected_version=99)
        assert resp.status_code == 409
        assert _error_code(resp) == "stale_version"
        assert _fingerprint(world) == before

    def test_a_successful_update_increments_the_version_by_exactly_one(
        self, world, api_client_doer
    ):
        """M4D3-VER-006."""
        selector = world["selector_response"]
        prior = selector.version
        resp = _select_component(world, api_client_doer)
        assert resp.status_code == 200
        selector.refresh_from_db()
        assert selector.version == prior + 1
        assert resp.data["version"] == prior + 1

    def test_the_second_identical_request_is_now_stale(self, world, api_client_doer):
        """The contract is real: a replayed version no longer matches."""
        first = _select_component(world, api_client_doer, expected_version=1)
        assert first.status_code == 200
        replay = _select_component(world, api_client_doer, expected_version=1)
        assert replay.status_code == 409
        assert _error_code(replay) == "stale_version"

    @pytest.mark.parametrize(
        "bad",
        [None, True, False, 1.0, 1.5, "1", "1.0", "abc", 0, -1, [], {}],
        ids=[
            "none", "true", "false", "float_one", "float_frac", "str_one",
            "str_float_one", "str_abc", "zero", "negative", "list", "dict",
        ],
    )
    def test_a_malformed_expected_version_is_rejected(
        self, world, api_client_doer, bad
    ):
        """M4D3-TXN-003 through the transport layer, with no coercion.

        ``1.0``, ``"1"`` and ``"1.0"`` are the values a DRF ``IntegerField``
        would have silently turned into version 1. The serializer no longer
        coerces, so the governed validator sees what the client sent.
        """
        before = _fingerprint(world)
        resp = api_client_doer.patch(
            _url(world),
            {
                "raw_value": {"public_id": str(world["component"].public_id)},
                "expected_version": bad,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "invalid_expected_version"
        assert _fingerprint(world) == before

    def test_the_endpoint_and_the_domain_validator_now_agree(self, world):
        """One structural rule, not two.

        Every value the governed validator refuses is refused by the update
        service too -- the divergence the independent review measured, where
        ``1.0``/``"1"``/``"1.0"`` passed the endpoint but failed the validator.
        """
        from iig_checklist.calculation_execution import (
            InvalidExpectedVersion,
            validate_expected_version,
        )
        from iig_checklist.services import (
            ResponseUpdateInvalidExpectedVersion,
            update_checklist_response,
        )

        for bad in (None, True, False, 1.0, 1.5, "1", "1.0", 0, -1, [], {}):
            with pytest.raises(InvalidExpectedVersion):
                validate_expected_version(bad)
            with pytest.raises(ResponseUpdateInvalidExpectedVersion):
                update_checklist_response(
                    tenant=world["tenant"],
                    execution_public_id=world["execution"].public_id,
                    response_public_id=world["selector_response"].public_id,
                    actor=world["user"],
                    payload={"expected_version": bad},
                )

    def test_the_service_uses_the_governed_validator(self):
        """Not a second implementation -- the same callable, by identity."""
        import ast
        import textwrap

        from iig_checklist import calculation_execution as exec_mod
        from iig_checklist import services as services_mod

        src = textwrap.dedent(
            inspect.getsource(services_mod.update_checklist_response)
        )
        called = {
            node.func.id
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "validate_expected_version" in called
        assert exec_mod.validate_expected_version is not None

    def test_the_serializer_does_not_coerce_the_submitted_value(self):
        """The transport layer enforces presence, never structure."""
        from iig_checklist.serializers import ChecklistResponseUpdateSerializer

        for value in (1.0, "1", "1.0", True, None, []):
            serializer = ChecklistResponseUpdateSerializer(
                data={"expected_version": value}, context={}
            )
            assert serializer.is_valid(), serializer.errors
            assert serializer.validated_data["expected_version"] == value
            assert type(serializer.validated_data["expected_version"]) is type(value)

    def test_true_is_not_accepted_as_version_one(self, world, api_client_doer):
        """The bool/int trap, defended at the API edge as well as in the domain."""
        world["selector_response"].refresh_from_db()
        assert world["selector_response"].version == 1
        before = _fingerprint(world)
        resp = api_client_doer.patch(
            _url(world),
            {
                "raw_value": {"public_id": str(world["component"].public_id)},
                "expected_version": True,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert _fingerprint(world) == before

    def test_version_is_still_not_client_writable(self, world, api_client_doer):
        resp = api_client_doer.patch(
            _url(world), {"version": 99, "expected_version": 1}, format="json"
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "unknown_field"


# ===========================================================================
# B. M4D3-SVC-005 -- server-controlled values are not client-writable
# ===========================================================================


class TestServerControlledValues:
    def test_a_calculated_response_cannot_be_written(self, world, api_client_doer):
        """A ``system_calculated`` value is owned by the calculation writer."""
        target = world["responses"]["daily_exposure"]
        before = _fingerprint(world)
        resp = api_client_doer.patch(
            _url(world, target),
            {"raw_value": {"value": "1.0"}, "expected_version": target.version},
            format="json",
        )
        assert resp.status_code == 403
        assert _error_code(resp) == "server_controlled_value"
        assert _fingerprint(world) == before

    def test_an_fda_derived_default_cannot_be_written(self, world, api_client_doer):
        from iig_checklist.models import ChecklistResponse

        target = world["free_response"]
        ChecklistResponse.objects.filter(pk=target.pk).update(
            data_source_type_snapshot=DataSourceClassification.FDA_DERIVED_DEFAULT
        )
        target.refresh_from_db()
        resp = api_client_doer.patch(
            _url(world, target),
            {"raw_value": {"value": "x"}, "expected_version": target.version},
            format="json",
        )
        assert resp.status_code == 403
        assert _error_code(resp) == "server_controlled_value"

    def test_the_check_lives_in_the_service_not_only_the_serializer(self, world):
        """M4D3-SVC-005 says so explicitly."""
        from iig_checklist.services import (
            ResponseUpdateServerControlledValue,
            update_checklist_response,
        )

        with pytest.raises(ResponseUpdateServerControlledValue):
            update_checklist_response(
                tenant=world["tenant"],
                execution_public_id=world["execution"].public_id,
                response_public_id=world["responses"]["daily_exposure"].public_id,
                actor=world["user"],
                payload={"raw_value": None, "expected_version": 1},
            )


# ===========================================================================
# C. M4D3-RCL-001 -- the update triggers the cascade
# ===========================================================================


class TestCascadeTrigger:
    def test_updating_the_selector_recalculates_every_calculation(
        self, world, api_client_doer
    ):
        for key in ALL_KEYS:
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED

        resp = _select_component(world, api_client_doer)
        assert resp.status_code == 200

        for key in ALL_KEYS:
            assert _outcome(world, key).status == CalculationStatus.COMPLETE
        assert _outcome(world, "daily_exposure").value == Decimal("1.000000")
        # 1 g against the precedent's 2 g maximum daily exposure.
        assert _outcome(world, "percentage_of_iid_mde").value == Decimal("50")

    def test_the_downstream_link_reads_the_upstream_written_by_this_request(
        self, world, api_client_doer
    ):
        """One HTTP request drives the whole two-level chain."""
        _select_component(world, api_client_doer)
        upstream = _outcome(world, "daily_exposure")
        downstream = _outcome(world, "percentage_of_iid_mde")
        assert downstream.input_provenance["upstream_outcome_public_ids"] == [
            str(upstream.public_id)
        ]

    def test_a_non_trigger_update_recalculates_nothing(self, world, api_client_doer):
        """M4D3-RCL-007 -- no recalculation, no calculated version change, no audit."""
        from audit.models import AuditEvent

        target = world["free_response"]
        calc_versions = {
            key: world["responses"][key].version for key in ALL_KEYS
        }
        audit_before = AuditEvent.objects.filter(event_type=CALCULATED_EVENT).count()

        resp = api_client_doer.patch(
            _url(world, target),
            {"raw_value": {"value": "no cascade"}, "expected_version": target.version},
            format="json",
        )
        assert resp.status_code == 200

        for key in ALL_KEYS:
            response = world["responses"][key]
            response.refresh_from_db()
            assert response.version == calc_versions[key]
            assert _outcome(world, key).status == CalculationStatus.DATA_REQUIRED
        assert (
            AuditEvent.objects.filter(event_type=CALCULATED_EVENT).count()
            == audit_before
        )

    def test_the_trigger_decision_is_not_duplicated_in_the_service(self):
        """The registry owns the trigger rules; the service must not restate them.

        Read from the parsed AST so the service's prose about triggers is not
        mistaken for a second implementation of them.
        """
        import ast

        from iig_checklist import services as services_mod

        tree = ast.parse(inspect.getsource(services_mod.update_checklist_response))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
        assert "recalculation_triggers" not in names
        assert "calculation_dependencies" not in names
        assert "build_execution_graph" not in names


# ===========================================================================
# D. M4D3-TXN-002 / M4D3-TXN-004 -- one transaction, all or nothing
# ===========================================================================


class TestAtomicity:
    def test_a_cascade_failure_rolls_back_the_response_write(
        self, world, api_client_doer, monkeypatch
    ):
        """M4D3-TXN-004 -- an exception after the response write rolls it back too."""
        import dataclasses
        from types import MappingProxyType

        from iid_assessment import calculations as engine

        def exploding(**kwargs):
            raise RuntimeError("engine fault")

        monkeypatch.setattr(engine, "calculate_daily_exposure", exploding)
        monkeypatch.setattr(
            registry_mod,
            "CALCULATION_BINDING_REGISTRY",
            MappingProxyType(
                {
                    **dict(registry_mod.CALCULATION_BINDING_REGISTRY),
                    "daily_exposure": dataclasses.replace(
                        registry_mod.CALCULATION_BINDING_REGISTRY["daily_exposure"],
                        function=exploding,
                    ),
                }
            ),
        )

        from iig_checklist.calculation_execution import CalculationEngineFailure

        before = _fingerprint(world)
        # The governed writer translates the engine fault; the cascade lets it
        # out, so the whole request -- response write included -- rolls back.
        with pytest.raises(CalculationEngineFailure):
            _select_component(world, api_client_doer)

        # The selector write happened before the cascade and must not survive.
        assert _fingerprint(world) == before

    def test_no_success_audit_survives_a_rolled_back_update(
        self, world, api_client_doer, monkeypatch, django_capture_on_commit_callbacks
    ):
        """M4D3-TXN-005 -- nothing is announced that did not commit."""
        import dataclasses
        from types import MappingProxyType

        from audit.models import AuditEvent
        from iid_assessment import calculations as engine
        from iig_checklist.calculation_execution import CalculationEngineFailure

        def exploding(**kwargs):
            raise RuntimeError("engine fault")

        monkeypatch.setattr(engine, "calculate_daily_exposure", exploding)
        monkeypatch.setattr(
            registry_mod,
            "CALCULATION_BINDING_REGISTRY",
            MappingProxyType(
                {
                    **dict(registry_mod.CALCULATION_BINDING_REGISTRY),
                    "daily_exposure": dataclasses.replace(
                        registry_mod.CALCULATION_BINDING_REGISTRY["daily_exposure"],
                        function=exploding,
                    ),
                }
            ),
        )

        before = AuditEvent.objects.count()
        with (
            pytest.raises(CalculationEngineFailure),
            django_capture_on_commit_callbacks(execute=True),
        ):
            _select_component(world, api_client_doer)
        assert AuditEvent.objects.count() == before


# ===========================================================================
# E. Audit -- M4D3-TXN-005
# ===========================================================================


class TestAudit:
    def test_a_successful_update_audits_after_commit(
        self, world, api_client_doer, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            resp = _select_component(world, api_client_doer)
        assert resp.status_code == 200

        events = AuditEvent.objects.filter(
            resource_id=str(world["selector_response"].public_id)
        )
        assert events.count() == 1
        payload = events.first().payload
        assert payload["prior_response_version"] == 1
        assert payload["new_response_version"] == 2
        assert payload["recalculated_count"] == len(ALL_KEYS)

    def test_each_recalculated_target_audits_once(
        self, world, api_client_doer, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            _select_component(world, api_client_doer)

        events = AuditEvent.objects.filter(event_type=CALCULATED_EVENT)
        assert events.count() == len(ALL_KEYS)
        assert {e.resource_id for e in events} == {
            str(world["responses"][key].public_id) for key in ALL_KEYS
        }


# ===========================================================================
# F. M4D3-SVC-004 -- the view is a thin adapter
# ===========================================================================


class TestViewIsThin:
    def test_the_view_holds_no_business_logic(self):
        """No model mutation, no audit emission, no transaction management.

        Checked against the parsed AST rather than the raw text, so the view's
        own comments about the governed contract are not mistaken for code.
        """
        import ast

        from iig_checklist.views import ChecklistResponseUpdateView

        source = textwrap.dedent(inspect.getsource(ChecklistResponseUpdateView.patch))
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)

        forbidden = {
            "emit", "on_commit", "atomic", "select_for_update",
            "full_clean", "save", "objects", "IigChecklistEvent",
            "ChecklistResponseUpdateSerializer", "has_iig_checklist_permission",
        }
        assert names.isdisjoint(forbidden), sorted(names & forbidden)

    def test_the_view_delegates_to_the_governed_service(self):
        import ast

        from iig_checklist.views import ChecklistResponseUpdateView

        source = textwrap.dedent(inspect.getsource(ChecklistResponseUpdateView.patch))
        tree = ast.parse(source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "update_checklist_response" in called


# ===========================================================================
# G. Authorization and isolation
# ===========================================================================


class TestAuthorization:
    def test_a_reader_without_edit_permission_is_refused(
        self, world, api_client_reviewer
    ):
        before = _fingerprint(world)
        resp = _select_component(world, api_client_reviewer)
        assert resp.status_code == 403
        assert _fingerprint(world) == before

    def test_a_foreign_tenant_gets_404_not_403(self, world, tenant_b, user_a):
        """Existence is never disclosed across a tenant boundary."""
        from rest_framework.exceptions import NotFound

        from iig_checklist.services import update_checklist_response

        with pytest.raises(NotFound):
            update_checklist_response(
                tenant=tenant_b,
                execution_public_id=world["execution"].public_id,
                response_public_id=world["selector_response"].public_id,
                actor=user_a,
                payload={"expected_version": 1},
            )

    def test_a_submitted_execution_refuses_updates(self, world, api_client_doer):
        """M4D3-RCL-005 -- and the response itself is immutable there too."""
        execution = world["execution"]
        execution.status = "submitted_for_review"
        execution.save(update_fields=["status"])

        before = _fingerprint(world)
        resp = _select_component(world, api_client_doer)
        assert resp.status_code == 400
        assert _error_code(resp) == "response_immutable"
        assert _fingerprint(world) == before


    def test_an_unknown_response_is_a_404(self, world, api_client_doer):
        import uuid

        url = reverse(
            "iig_checklist:execution-response-update",
            kwargs={
                "public_id": world["execution"].public_id,
                "response_public_id": uuid.uuid4(),
            },
        )
        resp = api_client_doer.patch(url, {"expected_version": 1}, format="json")
        assert resp.status_code == 404


# ===========================================================================
# H. The remaining governed rejection paths
# ===========================================================================


class TestModelLevelRejection:
    def test_a_model_validation_failure_is_a_structured_400(
        self, world, api_client_doer
    ):
        """``is_not_applicable`` without a reason passes the serializer and fails
        ``ChecklistResponse.clean()`` -- the service must surface that as the
        governed payload error, not as a 500.
        """
        target = world["free_response"]
        before = _fingerprint(world)
        resp = api_client_doer.patch(
            _url(world, target),
            {
                "is_not_applicable": True,
                "not_applicable_reason": "   ",
                "expected_version": target.version,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "invalid_raw_value_shape"
        assert _fingerprint(world) == before


class TestUnderLockStateRecheck:
    def test_a_status_change_committed_after_phase_a_is_caught_under_the_lock(
        self, world, monkeypatch
    ):
        """The Phase B re-read exists for exactly this race.

        Phase A sees ``draft`` and proceeds. Before Phase B takes the execution
        lock, a concurrent transaction commits ``submitted_for_review``. The
        governed service must observe the committed state, not the state its
        own earlier scan happened to see.

        The race is simulated at the last point before Phase B -- payload
        deserialization -- so the flip lands in the window the re-read guards.
        """
        from iig_checklist.models import ChecklistExecution
        from iig_checklist.serializers import ChecklistResponseUpdateSerializer
        from iig_checklist.services import (
            ResponseUpdateInvalidState,
            update_checklist_response,
        )

        original = ChecklistResponseUpdateSerializer.is_valid

        def flipping(self, *args, **kwargs):
            valid = original(self, *args, **kwargs)
            ChecklistExecution.objects.filter(pk=world["execution"].pk).update(
                status="submitted_for_review"
            )
            return valid

        monkeypatch.setattr(ChecklistResponseUpdateSerializer, "is_valid", flipping)

        before = _fingerprint(world)
        with pytest.raises(ResponseUpdateInvalidState):
            update_checklist_response(
                tenant=world["tenant"],
                execution_public_id=world["execution"].public_id,
                response_public_id=world["selector_response"].public_id,
                actor=world["user"],
                payload={
                    "raw_value": {"public_id": str(world["component"].public_id)},
                    "expected_version": world["selector_response"].version,
                },
            )
        assert _fingerprint(world) == before


# ===========================================================================
# I. M4D3-APP-011 -- the reserved server-owned marker is never client-supplied
# ===========================================================================
#
# M4D3-PST-002 stores a REVIEW_REQUIRED applicability outcome as
# ``REVIEW_REQUIRED:<ApplicabilityRule.reason_code>`` in
# ``not_applicable_reason``. M4D3-APP-011 requires the governed service to
# reject any client-supplied value beginning with that prefix, **for any
# response, rule-governed or not**, with ``error_code = "reserved_reason_prefix"``.
#
# The independent review measured the gap directly: the endpoint returned
# HTTP 200 and stored ``REVIEW_REQUIRED: injected by client`` verbatim.

RESERVED = "REVIEW_REQUIRED:"


class TestReservedReasonPrefixAtTheDomainBoundary:
    """The guard lives in the service, so a direct call is bound by it too."""

    def test_a_direct_service_call_is_rejected(self, world):
        from iig_checklist.services import (
            ResponseUpdateReservedReasonPrefix,
            update_checklist_response,
        )

        target = world["free_response"]
        before = _fingerprint(world)
        with pytest.raises(ResponseUpdateReservedReasonPrefix):
            update_checklist_response(
                tenant=world["tenant"],
                execution_public_id=world["execution"].public_id,
                response_public_id=target.public_id,
                actor=world["user"],
                payload={
                    "is_not_applicable": True,
                    "not_applicable_reason": f"{RESERVED} injected by client",
                    "expected_version": target.version,
                },
            )
        assert _fingerprint(world) == before

    def test_the_guard_is_not_only_a_serializer_rule(self):
        """M4D3-APP-011 binds the governed service, as M4D3-SVC-005 does."""
        import ast
        import textwrap

        from iig_checklist import services as services_mod

        src = textwrap.dedent(
            inspect.getsource(services_mod.update_checklist_response)
        )
        names = {
            n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)
        }
        assert "RESERVED_REASON_PREFIX" in names

    def test_the_prefix_constant_matches_the_persisted_marker_form(self):
        """M4D3-PST-002 -- ``REVIEW_REQUIRED:<reason_code>``."""
        from iig_checklist.governed_vocabularies import RESERVED_REASON_PREFIX

        assert RESERVED_REASON_PREFIX == "REVIEW_REQUIRED:"


class TestReservedReasonPrefixOverHttp:
    def test_the_endpoint_rejects_the_reserved_marker(self, world, api_client_doer):
        target = world["free_response"]
        before = _fingerprint(world)
        resp = api_client_doer.patch(
            _url(world, target),
            {
                "is_not_applicable": True,
                "not_applicable_reason": f"{RESERVED} injected by client",
                "expected_version": target.version,
            },
            format="json",
        )
        assert resp.status_code == 403
        assert _error_code(resp) == "reserved_reason_prefix"

        target.refresh_from_db()
        assert target.not_applicable_reason != f"{RESERVED} injected by client"
        assert target.is_not_applicable is False
        assert _fingerprint(world) == before

    def test_a_rejected_marker_drives_no_cascade_and_no_audit(
        self, world, api_client_doer, monkeypatch, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        calls = []
        monkeypatch.setattr(
            cascade_mod,
            "execute_calculation_response",
            lambda **kwargs: calls.append(kwargs),
        )
        audit_before = AuditEvent.objects.count()

        # The selector is the cascade trigger, so a rejected write here would
        # be the one most likely to leak a recalculation.
        selector = world["selector_response"]
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            resp = api_client_doer.patch(
                _url(world, selector),
                {
                    "is_not_applicable": True,
                    "not_applicable_reason": f"{RESERVED}NOT_APPLICABLE_BY_RULE",
                    "expected_version": selector.version,
                },
                format="json",
            )
        assert resp.status_code == 403
        assert calls == []
        assert callbacks == []
        assert AuditEvent.objects.count() == audit_before

    def test_the_rejection_precedes_any_lock(self, world, api_client_doer):
        """Phase A, before the transaction opens."""
        target = world["free_response"]
        with CaptureQueriesContext(connection) as ctx:
            resp = api_client_doer.patch(
                _url(world, target),
                {
                    "is_not_applicable": True,
                    "not_applicable_reason": f"{RESERVED}X",
                    "expected_version": target.version,
                },
                format="json",
            )
        assert resp.status_code == 403
        assert not any(
            "FOR UPDATE" in q["sql"].upper() for q in ctx.captured_queries
        )
        verbs = {q["sql"].lstrip().split()[0].upper() for q in ctx.captured_queries}
        assert "UPDATE" not in verbs
        assert "INSERT" not in verbs

    def test_a_calculated_response_is_still_refused_first(
        self, world, api_client_doer
    ):
        """Ordering is unchanged: server-controlled classification wins."""
        target = world["responses"]["daily_exposure"]
        resp = api_client_doer.patch(
            _url(world, target),
            {
                "is_not_applicable": True,
                "not_applicable_reason": f"{RESERVED}X",
                "expected_version": target.version,
            },
            format="json",
        )
        assert resp.status_code == 403
        assert _error_code(resp) == "server_controlled_value"


class TestReservedPrefixBoundary:
    """Exactly the normative prefix -- no trimming, folding or normalisation.

    M4D3-APP-011 says "beginning with the reserved prefix ``REVIEW_REQUIRED:``"
    and defines no canonicalisation, so none is applied. These cases pin that
    reading so a later change cannot quietly widen or narrow it.
    """

    @pytest.mark.parametrize(
        "reason",
        [
            "REVIEW_REQUIRED:",
            "REVIEW_REQUIRED:test",
            "REVIEW_REQUIRED: test",
            "REVIEW_REQUIRED:NOT_APPLICABLE_BY_RULE",
            "REVIEW_REQUIRED:anything at all",
            # DRF's CharField trims surrounding whitespace, so this reaches the
            # guard -- and the database -- as the bare reserved marker. The
            # guard deliberately runs on the deserialized value for exactly this
            # reason: it must judge what would be *stored*, not the wire form.
            " REVIEW_REQUIRED:leading space",
        ],
    )
    def test_values_that_must_be_rejected(self, world, api_client_doer, reason):
        target = world["free_response"]
        before = _fingerprint(world)
        resp = api_client_doer.patch(
            _url(world, target),
            {
                "is_not_applicable": True,
                "not_applicable_reason": reason,
                "expected_version": target.version,
            },
            format="json",
        )
        assert resp.status_code == 403
        assert _error_code(resp) == "reserved_reason_prefix"
        assert _fingerprint(world) == before

    @pytest.mark.parametrize(
        "reason",
        [
            # Case differs -- the clause names an exact prefix and defines no
            # case folding, so this is a permitted ordinary reason.
            "review_required:lower",
            "Review_Required:mixed",
            # The marker does not begin the string.
            "note REVIEW_REQUIRED:embedded",
            # The colon is part of the prefix.
            "REVIEW_REQUIRED",
            "REVIEW_REQUIRED_NO_COLON",
            # Ordinary text.
            "Not relevant to this product",
        ],
    )
    def test_values_that_must_be_accepted(self, world, api_client_doer, reason):
        target = world["free_response"]
        target.refresh_from_db()
        resp = api_client_doer.patch(
            _url(world, target),
            {
                "is_not_applicable": True,
                "not_applicable_reason": reason,
                "expected_version": target.version,
            },
            format="json",
        )
        assert resp.status_code == 200, resp.data
        target.refresh_from_db()
        assert target.not_applicable_reason == reason

    def test_a_null_reason_is_unaffected(self, world, api_client_doer):
        target = world["free_response"]
        resp = api_client_doer.patch(
            _url(world, target),
            {"raw_value": {"value": "ok"}, "expected_version": target.version},
            format="json",
        )
        assert resp.status_code == 200, resp.data
