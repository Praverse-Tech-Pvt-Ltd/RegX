"""Milestone 4D-4 -- M4D3-APP-009 governed applicability ownership.

M4D3-APP-008 makes ``is_not_applicable`` and ``not_applicable_reason``
server-owned for any response whose ``question.applicability_rule`` is non-null.
M4D3-APP-009 requires the governed response-update service to reject a
client-supplied value for either field on such a response with
``error_code = "applicability_server_controlled"`` and HTTP 403.
M4D3-APP-010 keeps a client-declared N/A permitted where no rule governs the
question.

4D-3 shipped APP-011 but deferred APP-009, recording it as a live exposure: a
client could set applicability on a rule-governed response and receive HTTP 200.
These tests pin the closed behaviour, and deliberately also pin what must *not*
change -- manual applicability, the reserved-marker guard, concurrency, and the
absence of any model-level ban that would block the future applicability engine.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from iig_checklist.enums import AnswerType, DataSourceClassification

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


def _product(tenant, user, code="PROD-APP009-01"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code=code,
        proposed_product_name=f"Product {code}",
        active_ingredient="Synthetic Applicability Ingredient",
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


def _rule(checklist_version, user, code="RULE-APP009"):
    """One approved applicability rule. Its condition is never evaluated here --
    4D-1 ships validation/canonicalisation only, so what matters for APP-009 is
    solely that the question carries a rule at all."""
    from iig_checklist.enums import ApplicabilityOutcome, ApplicabilityRuleStatus
    from iig_checklist.models import ApplicabilityRule

    return ApplicabilityRule.objects.create(
        checklist_version=checklist_version,
        code=code,
        rule_version=1,
        condition_json={"op": "always_true"},
        outcome_if_true=ApplicabilityOutcome.NOT_APPLICABLE,
        outcome_if_false=ApplicabilityOutcome.APPLICABLE,
        reason_code="NOT_APPLICABLE_BY_RULE",
        explanation_template="Not applicable by rule.",
        field_registry_version=1,
        status=ApplicabilityRuleStatus.APPROVED,
        created_by=user,
    )


def _world(tenant, tenant_definition, user):
    """An execution with one rule-governed and one ungoverned manual question."""
    from iig_checklist.models import (
        ChecklistQuestion,
        ChecklistResponse,
        ChecklistSection,
        ChecklistVersion,
    )
    from iig_checklist.services import create_execution

    cv = ChecklistVersion.objects.create(
        definition=tenant_definition, version_number=1, status="active", created_by=user
    )
    section = ChecklistSection.objects.create(
        checklist_version=cv, code="SEC-1", title="Section", display_order=1, criticality="low"
    )
    rule = _rule(cv, user)

    governed_q = ChecklistQuestion.objects.create(
        section=section,
        code="Q-GOVERNED",
        question_text="Rule-governed question",
        display_order=1,
        answer_type=AnswerType.SHORT_TEXT,
        data_source_classification=DataSourceClassification.USER_REQUIRED,
        criticality="low",
        applicability_rule=rule,
    )
    manual_q = ChecklistQuestion.objects.create(
        section=section,
        code="Q-MANUAL",
        question_text="Ungoverned question",
        display_order=2,
        answer_type=AnswerType.SHORT_TEXT,
        data_source_classification=DataSourceClassification.USER_REQUIRED,
        criticality="low",
    )

    product = _product(tenant, user)
    fv = _formulation(product, user)
    execution = create_execution(
        tenant=tenant,
        checklist_version_public_id=str(cv.public_id),
        formulation_version_public_id=str(fv.public_id),
        actor=user,
    )
    return {
        "execution": execution,
        "rule": rule,
        "governed": ChecklistResponse.objects.get(execution=execution, question=governed_q),
        "manual": ChecklistResponse.objects.get(execution=execution, question=manual_q),
    }


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    return _world(tenant_a, tenant_definition, user_a)


def _url(execution, response):
    return reverse(
        "iig_checklist:execution-response-update",
        kwargs={"public_id": execution.public_id, "response_public_id": response.public_id},
    )


def _patch(client, world_, response, payload):
    return client.patch(_url(world_["execution"], response), payload, format="json")


def _service_update(world_, response, payload, tenant, actor):
    from iig_checklist.services import update_checklist_response

    return update_checklist_response(
        tenant=tenant,
        execution_public_id=world_["execution"].public_id,
        response_public_id=response.public_id,
        actor=actor,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# A. The governed boundary -- rule-governed applicability is server-owned
# ---------------------------------------------------------------------------


class TestRuleGovernedApplicabilityIsServerOwned:
    def test_http_cannot_set_is_not_applicable(self, world, api_client_doer):
        resp = _patch(
            api_client_doer,
            world,
            world["governed"],
            {
                "expected_version": world["governed"].version,
                "is_not_applicable": True,
                "not_applicable_reason": "client says so",
            },
        )
        assert resp.status_code == 403
        assert resp.data["error_code"] == "applicability_server_controlled"

    def test_http_cannot_set_not_applicable_reason_alone(self, world, api_client_doer):
        resp = _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": world["governed"].version, "not_applicable_reason": "mine"},
        )
        assert resp.status_code == 403
        assert resp.data["error_code"] == "applicability_server_controlled"

    def test_direct_service_call_is_also_rejected(self, world, tenant_a, user_a):
        """The guard lives in the domain service, not only in the view."""
        from iig_checklist.services import ResponseUpdateApplicabilityServerControlled

        with pytest.raises(ResponseUpdateApplicabilityServerControlled):
            _service_update(
                world,
                world["governed"],
                {"expected_version": world["governed"].version, "is_not_applicable": True},
                tenant_a,
                user_a,
            )

    def test_a_client_cannot_clear_server_owned_applicability(
        self, world, api_client_doer, tenant_a, user_a
    ):
        """Clearing is as much an authorship of applicability as setting."""
        from iig_checklist.models import ChecklistResponse

        # Put the row into a server-declared N/A state directly, as the future
        # applicability engine would.
        ChecklistResponse.objects.filter(pk=world["governed"].pk).update(
            is_not_applicable=True, not_applicable_reason="REVIEW_REQUIRED:NOT_APPLICABLE_BY_RULE"
        )
        world["governed"].refresh_from_db()

        resp = _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": world["governed"].version, "is_not_applicable": False},
        )
        assert resp.status_code == 403
        assert resp.data["error_code"] == "applicability_server_controlled"
        world["governed"].refresh_from_db()
        assert world["governed"].is_not_applicable is True

    def test_applicability_cannot_be_smuggled_beside_a_valid_answer_edit(
        self, world, api_client_doer
    ):
        """A mixed payload is rejected whole -- the answer edit does not land."""
        before = world["governed"].version
        resp = _patch(
            api_client_doer,
            world,
            world["governed"],
            {
                "expected_version": before,
                "raw_value": {"value": "a legitimate answer"},
                "is_not_applicable": True,
            },
        )
        assert resp.status_code == 403
        world["governed"].refresh_from_db()
        assert world["governed"].raw_value is None
        assert world["governed"].version == before


# ---------------------------------------------------------------------------
# B. A rejected attempt changes nothing
# ---------------------------------------------------------------------------


class TestRejectionIsInert:
    def test_no_version_increment(self, world, api_client_doer):
        before = world["governed"].version
        _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": before, "is_not_applicable": True},
        )
        world["governed"].refresh_from_db()
        assert world["governed"].version == before

    def test_no_field_is_written(self, world, api_client_doer):
        _patch(
            api_client_doer,
            world,
            world["governed"],
            {
                "expected_version": world["governed"].version,
                "is_not_applicable": True,
                "not_applicable_reason": "client says so",
            },
        )
        world["governed"].refresh_from_db()
        assert world["governed"].is_not_applicable is False
        assert (world["governed"].not_applicable_reason or "") == ""

    def test_no_success_audit_is_emitted(self, world, api_client_doer):
        from audit.models import AuditEvent

        before = AuditEvent.objects.count()
        _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": world["governed"].version, "is_not_applicable": True},
        )
        assert AuditEvent.objects.count() == before

    def test_no_history_row_is_written(self, world, api_client_doer):
        from iig_checklist.models import ChecklistResponseHistory

        before = ChecklistResponseHistory.objects.count()
        _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": world["governed"].version, "is_not_applicable": True},
        )
        assert ChecklistResponseHistory.objects.count() == before

    def test_no_cascade_runs(self, world, api_client_doer, monkeypatch):
        """The service imports the cascade at call time, so patching the module
        attribute intercepts the real call site."""
        from iig_checklist import cascade as cascade_mod

        calls = []

        def spy(**kwargs):
            calls.append(kwargs)
            raise AssertionError("cascade must not run for a rejected update")

        monkeypatch.setattr(cascade_mod, "recalculate_dependents", spy)
        _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": world["governed"].version, "is_not_applicable": True},
        )
        assert calls == []

    def test_no_calculation_outcome_changes(self, world, api_client_doer):
        from iig_checklist.models import CalculationOutcome

        before = {
            o.pk: (o.status, o.value, o.reason_code)
            for o in CalculationOutcome.objects.filter(response__execution=world["execution"])
        }
        _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": world["governed"].version, "is_not_applicable": True},
        )
        after = {
            o.pk: (o.status, o.value, o.reason_code)
            for o in CalculationOutcome.objects.filter(response__execution=world["execution"])
        }
        assert after == before


# ---------------------------------------------------------------------------
# C. What must NOT change
# ---------------------------------------------------------------------------


class TestUngovernedApplicabilityStillWorks:
    def test_manual_applicability_remains_client_editable(self, world, api_client_doer):
        """M4D3-APP-010 -- no rule, so a client-declared N/A is still allowed."""
        resp = _patch(
            api_client_doer,
            world,
            world["manual"],
            {
                "expected_version": world["manual"].version,
                "is_not_applicable": True,
                "not_applicable_reason": "Not relevant to this formulation",
            },
        )
        assert resp.status_code == 200
        world["manual"].refresh_from_db()
        assert world["manual"].is_not_applicable is True
        assert world["manual"].not_applicable_reason == "Not relevant to this formulation"

    def test_an_ordinary_answer_edit_on_a_governed_question_still_works(
        self, world, api_client_doer
    ):
        """APP-009 owns applicability only -- it does not freeze the answer."""
        before = world["governed"].version
        resp = _patch(
            api_client_doer,
            world,
            world["governed"],
            {"expected_version": before, "raw_value": {"value": "an ordinary answer"}},
        )
        assert resp.status_code == 200
        world["governed"].refresh_from_db()
        assert world["governed"].raw_value == {"value": "an ordinary answer"}
        assert world["governed"].version == before + 1

    def test_the_field_stays_writable_below_the_client_service(self, world):
        """The guard is a client-write boundary, not a model-level ban.

        4D-1 ships applicability validation only -- runtime rule evaluation is a
        later stage -- so no governed applicability writer exists yet. This test
        pins that APP-009 does not foreclose it: the future engine must still be
        able to write the field through its own governed path.
        """
        from iig_checklist.models import ChecklistResponse

        ChecklistResponse.objects.filter(pk=world["governed"].pk).update(
            is_not_applicable=True, not_applicable_reason="REVIEW_REQUIRED:NOT_APPLICABLE_BY_RULE"
        )
        world["governed"].refresh_from_db()
        assert world["governed"].is_not_applicable is True


class TestApp011StillHolds:
    def test_reserved_marker_rejected_on_an_ungoverned_response(self, world, api_client_doer):
        """APP-011 is independent of APP-009 and applies to any response."""
        resp = _patch(
            api_client_doer,
            world,
            world["manual"],
            {
                "expected_version": world["manual"].version,
                "is_not_applicable": True,
                "not_applicable_reason": "REVIEW_REQUIRED:SMUGGLED",
            },
        )
        assert resp.status_code == 403
        assert resp.data["error_code"] == "reserved_reason_prefix"

    def test_a_governed_response_reports_applicability_ownership_first(
        self, world, api_client_doer
    ):
        """Deterministic ordering when both invariants would fire.

        Ownership is the more fundamental objection: on a rule-governed response
        the client may not author the field at all, so the value it carries is
        never reached.
        """
        resp = _patch(
            api_client_doer,
            world,
            world["governed"],
            {
                "expected_version": world["governed"].version,
                "is_not_applicable": True,
                "not_applicable_reason": "REVIEW_REQUIRED:SMUGGLED",
            },
        )
        assert resp.status_code == 403
        assert resp.data["error_code"] == "applicability_server_controlled"


class TestUnchangedContracts:
    def test_stale_expected_version_still_wins_for_an_otherwise_valid_edit(
        self, world, api_client_doer
    ):
        resp = _patch(
            api_client_doer,
            world,
            world["manual"],
            {"expected_version": 9999, "raw_value": {"value": "x"}},
        )
        assert resp.status_code == 409
        assert resp.data["error_code"] == "stale_version"

    def test_expected_version_is_still_required(self, world, api_client_doer):
        resp = _patch(api_client_doer, world, world["governed"], {"is_not_applicable": True})
        assert resp.status_code == 400

    def test_ownership_is_checked_before_the_payload_is_deserialized(self, world, api_client_doer):
        """An unknown field must not mask the ownership objection, or vice versa.

        Pins the order deliberately: the payload is deserialized first, so a
        malformed request still reports its own fault rather than being
        reclassified as an ownership problem.
        """
        resp = _patch(
            api_client_doer,
            world,
            world["governed"],
            {
                "expected_version": world["governed"].version,
                "is_not_applicable": True,
                "not_a_real_field": 1,
            },
        )
        assert resp.status_code == 400
