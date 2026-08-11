"""Milestone 4D-3 -- the read-only CalculationOutcome projection.

A SYSTEM_CALCULATED response keeps ``raw_value`` null (M4D3-MDL-006) and the
writer may not touch ``system_derived_value`` (M4D3-SVC-006), so before this
projection existed a client had no way to render a calculated result at all.

These tests pin both halves of that contract: what the projection *shows*
(status, current value, unit, governed reason code) and what it must never leak
(database ids, inputs, input_provenance, snapshot references, engine detail).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from iig_checklist.enums import AnswerType, CalculationStatus, DataSourceClassification

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Content helpers -- deliberately the same shapes the 4D-2 response API tests
# already use, so this module does not invent a second way to build a world.
# ---------------------------------------------------------------------------


def _product(tenant, user, code="PROD-PROJ-01"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code=code,
        proposed_product_name=f"Product {code}",
        active_ingredient="Synthetic Projection Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )


def _formulation(product, user):
    from formulations.models import FormulationVersion

    fv = FormulationVersion(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight="100.000000",
        total_dosage_unit_weight_unit="mg",
        created_by=user,
    )
    fv.save()
    return fv


def _version(tenant_definition, user, version_number=1):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=version_number,
        status="active",
        created_by=user,
    )


def _section(cv, code="SEC-1", order=1):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=cv,
        code=code,
        title="Section",
        display_order=order,
        criticality="low",
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
        criticality="low",
    )


def _world(tenant, tenant_definition, user, *, calculated=1, seq=1):
    """An execution carrying one manual question and ``calculated`` calculated ones.

    ``seq`` keeps version numbers and product codes distinct so a single test can
    build more than one execution under the same definition.
    """
    from iig_checklist.services import create_execution

    cv = _version(tenant_definition, user, version_number=seq)
    section = _section(cv)
    _question(
        section,
        "Q-MANUAL",
        answer_type=AnswerType.SHORT_TEXT,
        classification=DataSourceClassification.USER_REQUIRED,
        order=1,
    )
    for i in range(calculated):
        _question(
            section,
            f"Q-CALC-{i}",
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding="percentage_w_w",
            order=2 + i,
        )

    product = _product(tenant, user, code=f"PROD-PROJ-{seq:02d}")
    fv = _formulation(product, user)
    return create_execution(
        tenant=tenant,
        checklist_version_public_id=str(cv.public_id),
        formulation_version_public_id=str(fv.public_id),
        actor=user,
    )


def _list(api_client, execution):
    url = reverse(
        "iig_checklist:execution-response-list", kwargs={"public_id": execution.public_id}
    )
    resp = api_client.get(url)
    assert resp.status_code == 200
    return resp.data["results"]


def _by_classification(rows, classification):
    return [r for r in rows if r["data_source_type_snapshot"] == classification]


def _calculated_row(rows):
    matches = _by_classification(rows, DataSourceClassification.SYSTEM_CALCULATED)
    assert len(matches) == 1
    return matches[0]


def _set_outcome(execution, **fields):
    """Drive the placeholder into a governed state.

    ``update()`` deliberately bypasses ``save()``/``clean()``: these tests are
    about how a persisted row is *projected*, and the completed-outcome
    provenance invariant is already covered by the model and writer suites.
    """
    from iig_checklist.models import CalculationOutcome

    updated = CalculationOutcome.objects.filter(response__execution=execution).update(**fields)
    assert updated >= 1
    return updated


# ---------------------------------------------------------------------------
# A. Shape -- present, null, and never inferred from the response row
# ---------------------------------------------------------------------------


class TestProjectionShape:
    def test_a_manual_response_carries_a_null_calculation(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        execution = _world(tenant_a, tenant_definition, user_a)
        rows = _list(api_client_doer, execution)

        manual = _by_classification(rows, DataSourceClassification.USER_REQUIRED)
        assert len(manual) == 1
        # Present and null -- not absent, and never a fabricated empty outcome.
        assert "calculation" in manual[0]
        assert manual[0]["calculation"] is None

    def test_a_calculated_response_carries_a_calculation_object(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        execution = _world(tenant_a, tenant_definition, user_a)
        row = _calculated_row(_list(api_client_doer, execution))

        assert row["calculation"] is not None
        assert set(row["calculation"]) == {
            "outcome_public_id",
            "status",
            "value",
            "unit",
            "reason_code",
        }

    def test_a_calculated_response_keeps_raw_value_and_system_derived_value_null(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        """M4D3-MDL-006 / M4D3-SVC-006 -- neither field carries the result."""
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.COMPLETE,
            value=Decimal("12.5000000000"),
            unit="gram",
        )
        row = _calculated_row(_list(api_client_doer, execution))

        # The result is readable only through the projection.
        assert row["raw_value"] is None
        assert row["system_derived_value"] is None
        assert row["calculation"]["value"] == "12.5000000000"


# ---------------------------------------------------------------------------
# B. Governed statuses -- exactly the stored vocabulary
# ---------------------------------------------------------------------------


class TestGovernedStatuses:
    def test_complete_exposes_the_current_value_and_unit(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.COMPLETE,
            value=Decimal("0.2500000000"),
            unit="gram",
            reason_code="",
        )
        calc = _calculated_row(_list(api_client_doer, execution))["calculation"]

        assert calc["status"] == "complete"
        # Plain notation, trailing zeros preserved -- the same rendering the
        # writer persists, never 2.5E-1.
        assert calc["value"] == "0.2500000000"
        assert calc["unit"] == "gram"
        assert calc["reason_code"] is None

    def test_data_required_shows_no_value(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.DATA_REQUIRED,
            value=None,
            unit="",
            reason_code="DATA_REQUIRED",
        )
        calc = _calculated_row(_list(api_client_doer, execution))["calculation"]

        assert calc["status"] == "data_required"
        assert calc["value"] is None
        assert calc["unit"] is None
        assert calc["reason_code"] == "DATA_REQUIRED"

    def test_not_comparable_is_an_error_status_with_a_governed_reason_code(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        """NOT_COMPARABLE is a reason code, not a status.

        ``CalculationStatus`` has only data_required/calculating/complete/error,
        and ENGINE_STATUS_MAPPING sends a not-comparable engine result to
        ``status=error`` with ``reason_code="NOT_COMPARABLE"``. The projection
        reports that pair as stored rather than inventing a fifth status.
        """
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.ERROR,
            value=None,
            unit="",
            reason_code="NOT_COMPARABLE",
        )
        calc = _calculated_row(_list(api_client_doer, execution))["calculation"]

        assert calc["status"] == "error"
        assert calc["reason_code"] == "NOT_COMPARABLE"
        assert calc["value"] is None

    def test_error_exposes_a_governed_code_and_no_engine_detail(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.ERROR,
            value=None,
            unit="",
            reason_code="INPUT_RESOLUTION_FAILED",
        )
        calc = _calculated_row(_list(api_client_doer, execution))["calculation"]

        assert calc["status"] == "error"
        # A closed-vocabulary code, never a traceback or exception message.
        from iig_checklist.calculation_translation import ALLOWED_REASON_CODES

        assert calc["reason_code"] in ALLOWED_REASON_CODES
        serialised = str(calc)
        for leak in ("Traceback", "Exception", "RuntimeError", "  File "):
            assert leak not in serialised

    def test_a_prior_complete_value_cannot_survive_into_a_later_state(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        """The core no-stale-value guarantee, exercised as a real transition."""
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.COMPLETE,
            value=Decimal("42.0000000000"),
            unit="gram",
            reason_code="",
        )
        first = _calculated_row(_list(api_client_doer, execution))["calculation"]
        assert first["value"] == "42.0000000000"

        # Upstream data disappeared; the writer moves the row to data_required.
        _set_outcome(
            execution,
            status=CalculationStatus.DATA_REQUIRED,
            value=None,
            unit="",
            reason_code="DATA_REQUIRED",
        )
        second = _calculated_row(_list(api_client_doer, execution))["calculation"]

        assert second["status"] == "data_required"
        assert second["value"] is None
        assert "42" not in str(second)


# ---------------------------------------------------------------------------
# C. Confidentiality -- what must never appear
# ---------------------------------------------------------------------------


class TestProjectionLeakage:
    def test_only_the_public_uuid_identifies_the_outcome(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        import uuid

        from iig_checklist.models import CalculationOutcome

        execution = _world(tenant_a, tenant_definition, user_a)
        calc = _calculated_row(_list(api_client_doer, execution))["calculation"]

        outcome = CalculationOutcome.objects.get(response__execution=execution)
        assert uuid.UUID(str(calc["outcome_public_id"])) == outcome.public_id

    def test_no_database_id_is_exposed(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        from iig_checklist.models import CalculationOutcome

        execution = _world(tenant_a, tenant_definition, user_a)
        row = _calculated_row(_list(api_client_doer, execution))
        outcome = CalculationOutcome.objects.get(response__execution=execution)

        assert "id" not in row["calculation"]
        assert "pk" not in row["calculation"]
        assert "response" not in row["calculation"]
        assert "response_id" not in row["calculation"]
        # No field *is* the integer primary key. Compared by value rather than
        # substring: the pk's digits can legitimately occur inside a UUID.
        assert outcome.pk not in row["calculation"].values()
        assert str(outcome.pk) not in [str(v) for v in row["calculation"].values()]

    def test_no_provenance_or_reproducibility_evidence_is_exposed(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.COMPLETE,
            value=Decimal("1.0000000000"),
            unit="gram",
            inputs={"secret_input": "must-not-appear"},
            input_provenance={"secret_provenance": "must-not-appear"},
            rounding_rule="none (Decimal, unrounded)",
            formula_version="9.9.9",
        )
        calc = _calculated_row(_list(api_client_doer, execution))["calculation"]

        for forbidden in (
            "inputs",
            "input_provenance",
            "rounding_rule",
            "formula_version",
            "calculation_name",
            "source_assessment_snapshot_public_id",
            "generated_at",
        ):
            assert forbidden not in calc
        assert "must-not-appear" not in str(calc)
        assert "9.9.9" not in str(calc)


# ---------------------------------------------------------------------------
# D. Read path and query cost
# ---------------------------------------------------------------------------


class TestReadPath:
    def test_the_list_reflects_the_current_outcome_on_every_read(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        """What the cascade writes is what the next refetch returns.

        The cascade's own correctness is covered by the 4D-3 cascade suite; what
        matters here is that the read path serves current committed state rather
        than anything cached, which is what makes the Option B refresh work.
        """
        execution = _world(tenant_a, tenant_definition, user_a)
        _set_outcome(
            execution,
            status=CalculationStatus.COMPLETE,
            value=Decimal("1.0000000000"),
            unit="gram",
        )
        assert _calculated_row(_list(api_client_doer, execution))["calculation"]["value"] == (
            "1.0000000000"
        )

        _set_outcome(
            execution,
            status=CalculationStatus.COMPLETE,
            value=Decimal("2.0000000000"),
            unit="gram",
        )
        assert _calculated_row(_list(api_client_doer, execution))["calculation"]["value"] == (
            "2.0000000000"
        )

    def test_serialising_outcomes_costs_exactly_one_query_for_the_whole_page(
        self,
        api_client_doer,
        tenant_a,
        tenant_definition,
        user_a,
        doer_membership,
    ):
        """N+1 guard.

        Counting *outcome* queries rather than total queries is the direct
        statement of the property: without ``prefetch_related`` the serializer
        would touch ``calculation_outcomes`` once per calculated response, so
        five of them would issue five reads. One read for the whole page is the
        thing that must not regress.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        execution = _world(tenant_a, tenant_definition, user_a, calculated=5)
        url = reverse(
            "iig_checklist:execution-response-list", kwargs={"public_id": execution.public_id}
        )
        api_client_doer.get(url)  # warm any per-request caching

        with CaptureQueriesContext(connection) as ctx:
            resp = api_client_doer.get(url)

        assert len(_by_classification(resp.data["results"], "system_calculated")) == 5
        outcome_reads = [
            q
            for q in ctx.captured_queries
            if "calculationoutcome" in q["sql"].lower()
            and q["sql"].lstrip().lower().startswith("select")
        ]
        assert len(outcome_reads) == 1, (
            f"expected one prefetched outcome read, got {len(outcome_reads)}"
        )


# ---------------------------------------------------------------------------
# E. The write contract is untouched
# ---------------------------------------------------------------------------


class TestWriteContractUnchanged:
    def test_the_update_serializer_still_refuses_a_calculation_key(self):
        """``calculation`` is read-only: it is not client-writable."""
        from iig_checklist.serializers import ChecklistResponseUpdateSerializer

        serializer = ChecklistResponseUpdateSerializer(
            data={"expected_version": 1, "calculation": {"status": "complete"}}
        )
        assert not serializer.is_valid()
        assert str(serializer.errors["error_code"][0]) == "unknown_field"

    def test_expected_version_is_still_required(self):
        from iig_checklist.serializers import ChecklistResponseUpdateSerializer

        serializer = ChecklistResponseUpdateSerializer(data={"raw_value": "x"})
        assert not serializer.is_valid()
        assert str(serializer.errors["error_code"][0]) == "expected_version_required"
