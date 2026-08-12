"""Milestone 4D-4 -- governed response overrides (deviations).

Specification: MILESTONE_4D_DISCOVERY.md section 12; MILESTONE_4D_4_DISCOVERY.md
section AC -- 4D4-DEC-004 (ANSWER_OVERRIDDEN), 4D4-DEC-010 (overridability by
classification), 4D4-DEC-011 (PERM_OVERRIDE_EXECUTION), with 4D4-DEC-002
(shared expected_version), 4D4-DEC-003 (editable states) and 4D4-DEC-007
(dedicated action endpoint).

Fixtures are synthetic. No production regulatory content exists or is invented
here -- the content-approval gate is open at 0 of 20.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from iig_checklist.enums import AnswerType, CalculationStatus, DataSourceClassification
from iig_checklist.overrides import (
    OverrideClearNotSupported,
    OverrideNotOverridable,
    OverridePermissionDenied,
    override_checklist_response,
)

pytestmark = pytest.mark.django_db

FIXED_GENERATED_AT = datetime(2026, 3, 4, 5, 6, 7, 890123, tzinfo=UTC)

#: One question per governed classification, so the 4D4-DEC-010 matrix is
#: exercised against real rows rather than asserted about in the abstract.
CLASSIFICATION_QUESTIONS = {
    DataSourceClassification.FDA_DERIVED_DEFAULT: ("Q-FDA", AnswerType.SHORT_TEXT),
    DataSourceClassification.USER_REQUIRED: ("Q-USER", AnswerType.SHORT_TEXT),
    DataSourceClassification.SYSTEM_CALCULATED: ("Q-CALC", AnswerType.CALCULATED_VALUE),
    DataSourceClassification.EVIDENCE_DERIVED: ("Q-EVID", AnswerType.SHORT_TEXT),
    DataSourceClassification.REVIEWER_CONFIRMED: ("Q-REVC", AnswerType.SHORT_TEXT),
}


def _world(tenant, tenant_definition, user, *, status="draft"):
    from formulations.models import FormulationVersion, ProductDevelopmentRecord
    from iig_checklist.models import (
        CalculationOutcome,
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
    order = 0
    for classification, (code, answer_type) in CLASSIFICATION_QUESTIONS.items():
        order += 1
        kwargs = {}
        if answer_type == AnswerType.CALCULATED_VALUE:
            kwargs["calculation_binding_identifier"] = "percentage_w_w"
        ChecklistQuestion.objects.create(
            section=section,
            code=code,
            question_text=f"Synthetic {code}",
            display_order=order,
            answer_type=answer_type,
            data_source_classification=classification,
            criticality="low",
            **kwargs,
        )

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code="PROD-OVR-01",
        proposed_product_name="Synthetic Override Product",
        active_ingredient="Synthetic Override Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )
    fv = FormulationVersion(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight="100.000000",
        total_dosage_unit_weight_unit="mg",
        created_by=user,
    )
    fv.save()

    execution = create_execution(
        tenant=tenant,
        checklist_version_public_id=str(cv.public_id),
        formulation_version_public_id=str(fv.public_id),
        actor=user,
    )

    # Give the FDA-derived response a populated default, so the first override
    # has a real original value to preserve.
    ChecklistResponse.objects.filter(execution=execution, question__code="Q-FDA").update(
        raw_value={"value": "fda-original"}
    )
    CalculationOutcome.objects.filter(response__execution=execution).update(
        status=CalculationStatus.COMPLETE,
        value=Decimal("12.5000000000"),
        unit="gram",
        reason_code="",
        input_provenance={
            "calculation_name": "calculate_percentage_w_w",
            "formula_version": "1.0.0",
        },
    )

    if status != "draft":
        type(execution).objects.filter(pk=execution.pk).update(status=status)
        execution.refresh_from_db()
    return {"execution": execution, "version": cv, "formulation": fv}


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    return _world(tenant_a, tenant_definition, user_a)


def _response(world_, code="Q-FDA"):
    from iig_checklist.models import ChecklistResponse

    return ChecklistResponse.objects.get(execution=world_["execution"], question__code=code)


def _url(world_, response):
    return reverse(
        "iig_checklist:execution-response-override",
        kwargs={
            "public_id": world_["execution"].public_id,
            "response_public_id": response.public_id,
        },
    )


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


def _payload(value="overridden", reason="Governed deviation reason.", version=None):
    body = {"raw_value": {"value": value}, "override_reason": reason}
    if version is not None:
        body["expected_version"] = version
    return body


def _apply(world_, actor, tenant, code="Q-FDA", **kw):
    """Direct governed service call."""
    response = _response(world_, code)
    payload = _payload(version=response.version, **kw)
    return override_checklist_response(
        tenant=tenant,
        execution_public_id=world_["execution"].public_id,
        response_public_id=response.public_id,
        actor=actor,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# A. Permission -- 4D4-DEC-011
# ---------------------------------------------------------------------------


class TestOverridePermission:
    def test_reviewer_may_override(self, world, api_client_reviewer, reviewer_membership):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_payload(version=response.version), format="json"
        )
        assert resp.status_code == 200

    def test_vp_may_override(self, world, api_client_vp, vp_membership):
        response = _response(world)
        resp = api_client_vp.post(
            _url(world, response), data=_payload(version=response.version), format="json"
        )
        assert resp.status_code == 200

    def test_doer_may_not_override(self, world, api_client_doer):
        response = _response(world)
        resp = api_client_doer.post(
            _url(world, response), data=_payload(version=response.version), format="json"
        )
        assert resp.status_code == 403
        assert _error_code(resp) == "override_permission_denied"

    def test_edit_permission_alone_does_not_grant_override(self):
        """4D4-DEC-011 -- override authority is never implicit."""
        from authorization.models import Role
        from iig_checklist.permissions import (
            PERM_EDIT_EXECUTION,
            PERM_OVERRIDE_EXECUTION,
            PERM_REVIEW_EXECUTION,
            PERM_VIEW_EXECUTION,
            ROLE_PERMISSIONS,
        )

        doer = ROLE_PERMISSIONS[Role.BuiltIn.DOER]
        assert PERM_EDIT_EXECUTION in doer
        assert PERM_VIEW_EXECUTION in doer
        assert PERM_OVERRIDE_EXECUTION not in doer

        # Reviewer and VP hold it; Tenant Admin holds view but not override.
        assert PERM_OVERRIDE_EXECUTION in ROLE_PERMISSIONS[Role.BuiltIn.REVIEWER]
        assert PERM_OVERRIDE_EXECUTION in ROLE_PERMISSIONS[Role.BuiltIn.VP]
        admin = ROLE_PERMISSIONS[Role.BuiltIn.TENANT_ADMIN]
        assert PERM_VIEW_EXECUTION in admin
        assert PERM_OVERRIDE_EXECUTION not in admin
        # The permission is distinct from review authority, not an alias of it.
        assert PERM_OVERRIDE_EXECUTION != PERM_REVIEW_EXECUTION

    def test_permission_codename_matches_the_approved_decision(self):
        from iig_checklist.permissions import PERM_OVERRIDE_EXECUTION

        assert PERM_OVERRIDE_EXECUTION == "iig_checklist.override_execution"

    def test_direct_service_call_enforces_permission(self, world, tenant_a, user_a):
        with pytest.raises(OverridePermissionDenied):
            _apply(world, user_a, tenant_a)

    def test_cross_tenant_is_404_not_403(self, world, tenant_b, reviewer_user):
        """Fail closed, and without disclosing existence."""
        from rest_framework.exceptions import NotFound

        with pytest.raises(NotFound):
            _apply(world, reviewer_user, tenant_b)


# ---------------------------------------------------------------------------
# B. Classification matrix -- 4D4-DEC-010
# ---------------------------------------------------------------------------


class TestClassificationMatrix:
    def test_fda_derived_default_is_overridable(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        result = _apply(world, reviewer_user, tenant_a, code="Q-FDA")
        assert result.response.raw_value == {"value": "overridden"}

    @pytest.mark.parametrize(
        "code",
        ["Q-USER", "Q-CALC", "Q-EVID", "Q-REVC"],
        ids=["user_required", "system_calculated", "evidence_derived", "reviewer_confirmed"],
    )
    def test_every_other_classification_is_refused(
        self, world, tenant_a, reviewer_user, reviewer_membership, code
    ):
        with pytest.raises(OverrideNotOverridable):
            _apply(world, reviewer_user, tenant_a, code=code)

    def test_refusal_is_enforced_in_the_service_not_only_the_view(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        """Frontend controls are not protection; the boundary is authoritative."""
        with pytest.raises(OverrideNotOverridable):
            _apply(world, reviewer_user, tenant_a, code="Q-CALC")

    def test_http_refusal_uses_the_governed_code(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world, "Q-USER")
        resp = api_client_reviewer.post(
            _url(world, response), data=_payload(version=response.version), format="json"
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "response_not_overridable"

    def test_classification_read_from_snapshot_not_live_question(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        """A later question re-classification must not retroactively unlock."""
        from iig_checklist.models import ChecklistQuestion, ChecklistResponse

        response = _response(world, "Q-USER")
        ChecklistQuestion.objects.filter(pk=response.question.pk).update(
            data_source_classification=DataSourceClassification.FDA_DERIVED_DEFAULT
        )
        assert (
            ChecklistResponse.objects.get(pk=response.pk).data_source_type_snapshot
            == DataSourceClassification.USER_REQUIRED
        )
        with pytest.raises(OverrideNotOverridable):
            _apply(world, reviewer_user, tenant_a, code="Q-USER")


# ---------------------------------------------------------------------------
# C. Lifecycle -- 4D4-DEC-003
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.parametrize("state", ["draft", "returned"])
    def test_editable_states_allow_override(
        self,
        db,
        tenant_a,
        tenant_definition,
        user_a,
        doer_membership,
        reviewer_user,
        reviewer_membership,
        state,
    ):
        world_ = _world(tenant_a, tenant_definition, user_a, status=state)
        result = _apply(world_, reviewer_user, tenant_a)
        assert result.response.override_reason

    @pytest.mark.parametrize("state", ["submitted_for_review", "under_review", "approved"])
    def test_non_editable_states_refuse_override(
        self,
        db,
        tenant_a,
        tenant_definition,
        user_a,
        doer_membership,
        reviewer_user,
        reviewer_membership,
        state,
    ):
        from iig_checklist.overrides import OverrideInvalidState

        world_ = _world(tenant_a, tenant_definition, user_a, status=state)
        with pytest.raises(OverrideInvalidState):
            _apply(world_, reviewer_user, tenant_a)

    def test_lifecycle_states_match_the_shared_constant(self):
        from iig_checklist.services import EDITABLE_EXECUTION_STATUSES

        assert set(EDITABLE_EXECUTION_STATUSES) == {"draft", "returned"}


# ---------------------------------------------------------------------------
# D. Storage semantics -- section AC.5
# ---------------------------------------------------------------------------


class TestStorageSemantics:
    def test_first_override_preserves_the_original_derived_value(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        result = _apply(world, reviewer_user, tenant_a)
        assert result.created is True
        assert result.response.system_derived_value == {"value": "fda-original"}
        assert result.response.raw_value == {"value": "overridden"}

    def test_override_reason_is_stored(self, world, tenant_a, reviewer_user, reviewer_membership):
        result = _apply(world, reviewer_user, tenant_a, reason="Because the default is wrong.")
        assert result.response.override_reason == "Because the default is wrong."

    def test_version_increments(self, world, tenant_a, reviewer_user, reviewer_membership):
        before = _response(world).version
        result = _apply(world, reviewer_user, tenant_a)
        assert result.response.version == before + 1

    def test_second_override_keeps_the_original_not_the_previous_override(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        """The corruption section AC.5 exists to prevent."""
        _apply(world, reviewer_user, tenant_a, value="first", reason="first reason")
        result = _apply(world, reviewer_user, tenant_a, value="second", reason="second reason")

        assert result.created is False
        assert result.response.system_derived_value == {"value": "fda-original"}
        assert result.response.raw_value == {"value": "second"}
        assert result.response.override_reason == "second reason"

    def test_a_null_original_default_does_not_confuse_apply_with_update(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        """override_reason is the marker, deliberately not system_derived_value.

        An FDA-derived response whose default was never populated has
        raw_value None, so the first override preserves None. Keying "already
        overridden?" off that column would read the second override as a first
        one and overwrite the preserved original with the previous override.
        """
        from iig_checklist.models import ChecklistResponse

        ChecklistResponse.objects.filter(
            execution=world["execution"], question__code="Q-FDA"
        ).update(raw_value=None)

        first = _apply(world, reviewer_user, tenant_a, value="first", reason="first reason")
        assert first.created is True
        assert first.response.system_derived_value is None

        second = _apply(world, reviewer_user, tenant_a, value="second", reason="second reason")
        assert second.created is False
        assert second.response.system_derived_value is None
        assert second.response.raw_value == {"value": "second"}

    def test_blank_reason_is_refused(self, world, api_client_reviewer, reviewer_membership):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data=_payload(version=response.version, reason=""),
            format="json",
        )
        assert resp.status_code == 400

    def test_whitespace_only_reason_is_refused(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data=_payload(version=response.version, reason="   "),
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "override_reason_required"

    def test_missing_reason_is_refused(self, world, api_client_reviewer, reviewer_membership):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data={"raw_value": {"value": "x"}, "expected_version": response.version},
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "override_reason_required"

    def test_no_write_survives_a_refused_override(self, world, api_client_doer):
        """A denied attempt writes nothing and increments no version."""
        response = _response(world)
        before_version = response.version
        before_value = response.raw_value
        api_client_doer.post(
            _url(world, response), data=_payload(version=response.version), format="json"
        )
        response.refresh_from_db()
        assert response.version == before_version
        assert response.raw_value == before_value
        assert response.override_reason == ""
        assert response.system_derived_value is None


# ---------------------------------------------------------------------------
# E. Clearing is not implemented -- section AC.4
# ---------------------------------------------------------------------------


class TestClearingRefused:
    def test_null_value_is_refused_with_a_governed_code(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data={
                "raw_value": None,
                "override_reason": "clearing",
                "expected_version": response.version,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "override_clear_not_supported"

    def test_direct_service_call_refuses_a_null_clear(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        response = _response(world)
        with pytest.raises(OverrideClearNotSupported):
            override_checklist_response(
                tenant=tenant_a,
                execution_public_id=world["execution"].public_id,
                response_public_id=response.public_id,
                actor=reviewer_user,
                payload={
                    "raw_value": None,
                    "override_reason": "clearing",
                    "expected_version": response.version,
                },
            )

    def test_client_may_not_null_the_preserved_original(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data={
                "raw_value": {"value": "x"},
                "override_reason": "r",
                "system_derived_value": None,
                "expected_version": response.version,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "unknown_field"

    def test_no_clear_code_exists_in_the_governed_vocabulary(self):
        from iig_checklist.governed_vocabularies import ALLOWED_HISTORY_REASON_CODES

        assert not [c for c in ALLOWED_HISTORY_REASON_CODES if "CLEAR" in c.upper()]

    def test_no_clear_route_exists(self):
        from django.urls import NoReverseMatch

        with pytest.raises(NoReverseMatch):
            reverse("iig_checklist:execution-response-override-clear")


# ---------------------------------------------------------------------------
# F. Optimistic concurrency -- 4D4-DEC-002
# ---------------------------------------------------------------------------


class TestExpectedVersion:
    def test_correct_expected_version_succeeds(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        assert _apply(world, reviewer_user, tenant_a).response.version == 2

    def test_stale_expected_version_is_refused(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_payload(version=response.version + 5), format="json"
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "stale_expected_version"

    @pytest.mark.parametrize("bad", [1.0, "1", "1.0", 0, -1, None])
    def test_malformed_expected_version_uses_the_shared_validator(
        self, world, api_client_reviewer, reviewer_membership, bad
    ):
        """The serializer does not coerce; one structural rule, in the domain."""
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_payload(version=bad), format="json"
        )
        assert resp.status_code == 400
        assert _error_code(resp) in {
            "invalid_expected_version",
            "expected_version_required",
        }

    def test_missing_expected_version_is_refused(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data={"raw_value": {"value": "x"}, "override_reason": "r"},
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "expected_version_required"


# ---------------------------------------------------------------------------
# G. History -- 4D4-DEC-004
# ---------------------------------------------------------------------------


class TestOverrideHistory:
    def _rows(self, world_, code="Q-FDA"):
        from iig_checklist.models import ChecklistResponseHistory

        return list(
            ChecklistResponseHistory.objects.filter(
                response__execution=world_["execution"], response__question__code=code
            ).order_by("new_version")
        )

    def test_governed_code_is_registered(self):
        from iig_checklist.governed_vocabularies import (
            ALLOWED_HISTORY_REASON_CODES,
            HISTORY_REASON_ANSWER_OVERRIDDEN,
        )

        assert HISTORY_REASON_ANSWER_OVERRIDDEN == "ANSWER_OVERRIDDEN"
        assert HISTORY_REASON_ANSWER_OVERRIDDEN in ALLOWED_HISTORY_REASON_CODES

    def test_no_speculative_apply_update_codes_were_minted(self):
        from iig_checklist.governed_vocabularies import ALLOWED_HISTORY_REASON_CODES

        assert "ANSWER_OVERRIDE_APPLIED" not in ALLOWED_HISTORY_REASON_CODES
        assert "ANSWER_OVERRIDE_UPDATED" not in ALLOWED_HISTORY_REASON_CODES
        assert ALLOWED_HISTORY_REASON_CODES == {
            "APPLICABILITY_REEVALUATED",
            "COMPONENT_REBOUND",
            "ANSWER_OVERRIDDEN",
        }

    def test_first_override_writes_one_history_row(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        _apply(world, reviewer_user, tenant_a)
        rows = self._rows(world)
        assert len(rows) == 1
        assert rows[0].correction_reason == "ANSWER_OVERRIDDEN"

    def test_apply_and_update_are_reconstructable_from_one_code(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        """4D4-DEC-004 -- ordering plus prior/new state distinguishes them."""
        _apply(world, reviewer_user, tenant_a, value="first", reason="first reason")
        _apply(world, reviewer_user, tenant_a, value="second", reason="second reason")

        rows = self._rows(world)
        assert [r.correction_reason for r in rows] == ["ANSWER_OVERRIDDEN"] * 2

        apply_row, update_row = rows
        # The apply displaced the original default...
        assert apply_row.prior_raw_value == {"value": "fda-original"}
        assert apply_row.new_raw_value == {"value": "first"}
        # ...and the update displaced the previous override.
        assert update_row.prior_raw_value == {"value": "first"}
        assert update_row.new_raw_value == {"value": "second"}
        # Versions chain without gaps, so replay order is unambiguous.
        assert apply_row.new_version == update_row.prior_version

    def test_history_records_the_overriding_actor(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        _apply(world, reviewer_user, tenant_a)
        assert self._rows(world)[0].amended_by_id == reviewer_user.id

    def test_refused_override_writes_no_history(self, world, api_client_doer):
        response = _response(world)
        api_client_doer.post(
            _url(world, response), data=_payload(version=response.version), format="json"
        )
        assert self._rows(world) == []


# ---------------------------------------------------------------------------
# H. Audit
# ---------------------------------------------------------------------------


class TestOverrideAudit:
    def _events(self):
        from audit.models import AuditEvent

        return AuditEvent.objects.filter(event_type="iig_checklist.answer.overridden")

    def test_success_emits_the_governed_event(
        self, world, api_client_reviewer, reviewer_membership, django_capture_on_commit_callbacks
    ):
        response = _response(world)
        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client_reviewer.post(
                _url(world, response), data=_payload(version=response.version), format="json"
            )
        assert resp.status_code == 200

        event = self._events().latest("id")
        payload = event.payload
        assert payload["response_public_id"] == str(response.public_id)
        assert payload["prior_response_version"] == 1
        assert payload["new_response_version"] == 2
        assert payload["override_reason"] == "Governed deviation reason."
        assert payload["prior_value"] == {"value": "fda-original"}
        assert payload["new_value"] == {"value": "overridden"}
        assert payload["system_derived_value"] == {"value": "fda-original"}
        assert payload["override_created"] is True

    def test_audit_carries_public_identifiers_only(
        self, world, api_client_reviewer, reviewer_membership, django_capture_on_commit_callbacks
    ):
        response = _response(world)
        with django_capture_on_commit_callbacks(execute=True):
            api_client_reviewer.post(
                _url(world, response), data=_payload(version=response.version), format="json"
            )
        payload = self._events().latest("id").payload
        blob = json.dumps(payload)
        assert "response_id" not in blob
        assert f'"{response.pk}"' not in blob
        assert payload["actor_public_id"]

    def test_denied_attempt_emits_no_success_audit(
        self, world, api_client_doer, django_capture_on_commit_callbacks
    ):
        response = _response(world)
        before = self._events().count()
        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client_doer.post(
                _url(world, response), data=_payload(version=response.version), format="json"
            )
        assert resp.status_code == 403
        assert self._events().count() == before

    def test_non_overridable_attempt_emits_no_success_audit(
        self, world, api_client_reviewer, reviewer_membership, django_capture_on_commit_callbacks
    ):
        response = _response(world, "Q-CALC")
        before = self._events().count()
        with django_capture_on_commit_callbacks(execute=True):
            api_client_reviewer.post(
                _url(world, response), data=_payload(version=response.version), format="json"
            )
        assert self._events().count() == before


# ---------------------------------------------------------------------------
# I. Ordinary API separation
# ---------------------------------------------------------------------------


class TestOrdinaryApiSeparation:
    def _patch_url(self, world_, response):
        return reverse(
            "iig_checklist:execution-response-update",
            kwargs={
                "public_id": world_["execution"].public_id,
                "response_public_id": response.public_id,
            },
        )

    def test_patch_cannot_set_override_reason(self, world, api_client_doer):
        response = _response(world, "Q-USER")
        resp = api_client_doer.patch(
            self._patch_url(world, response),
            data={
                "raw_value": {"value": "x"},
                "override_reason": "sneaky",
                "expected_version": response.version,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "unknown_field"
        response.refresh_from_db()
        assert response.override_reason == ""

    def test_patch_cannot_set_system_derived_value(self, world, api_client_doer):
        response = _response(world, "Q-USER")
        resp = api_client_doer.patch(
            self._patch_url(world, response),
            data={
                "raw_value": {"value": "x"},
                "system_derived_value": {"value": "forged"},
                "expected_version": response.version,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "unknown_field"
        response.refresh_from_db()
        assert response.system_derived_value is None

    def test_override_columns_are_not_client_updatable(self):
        from iig_checklist.services import _UPDATABLE_FIELDS

        assert "override_reason" not in _UPDATABLE_FIELDS
        assert "system_derived_value" not in _UPDATABLE_FIELDS


# ---------------------------------------------------------------------------
# J. Controlled-export integration -- section AC.5
# ---------------------------------------------------------------------------


def _artifact(world_):
    from iig_checklist.controlled_export import build_export_artifact

    execution = world_["execution"]
    # Export requires an approved execution; overrides require an editable one.
    # Flip for the read and restore, so a test can legitimately do both.
    original_status = execution.status
    type(execution).objects.filter(pk=execution.pk).update(status="approved")
    execution.refresh_from_db()
    try:
        return build_export_artifact(execution=execution, generated_at=FIXED_GENERATED_AT)
    finally:
        type(execution).objects.filter(pk=execution.pk).update(status=original_status)
        execution.refresh_from_db()


def _exported(artifact, code="Q-FDA"):
    for response in artifact["payload"]["responses"]:
        if response["question_code"] == code:
            return response
    raise AssertionError(f"no exported response for {code}")


class TestExportOverrideProvenance:
    def test_absent_when_no_override_exists(self, world):
        for response in _artifact(world)["payload"]["responses"]:
            assert "override" not in response
            assert "override_history" not in response

    def test_active_override_provenance_is_present(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        _apply(world, reviewer_user, tenant_a)
        override = _exported(_artifact(world))["override"]
        assert override["override_reason"] == "Governed deviation reason."
        assert override["response_version"] == 2
        assert override["data_source_type_snapshot"] == "fda_derived_default"

    def test_original_and_overridden_values_are_distinguishable(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        _apply(world, reviewer_user, tenant_a)
        override = _exported(_artifact(world))["override"]
        assert override["original_system_derived_value"] == {"value": "fda-original"}
        assert override["overridden_value"] == {"value": "overridden"}
        assert override["original_system_derived_value"] != override["overridden_value"]

    def test_actor_is_public_id_and_never_email(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        _apply(world, reviewer_user, tenant_a)
        artifact = _artifact(world)
        assert _exported(artifact)["override"]["overridden_by_public_id"] == str(
            reviewer_user.public_id
        )
        assert reviewer_user.email not in json.dumps(artifact, default=str)

    def test_override_projection_is_allow_listed(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        from iig_checklist.controlled_export import ALLOWED_OVERRIDE_FIELDS

        _apply(world, reviewer_user, tenant_a)
        assert set(_exported(_artifact(world))["override"]) <= ALLOWED_OVERRIDE_FIELDS

    def test_no_database_ids_reach_the_artifact(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        from iig_checklist.controlled_export import canonical_bytes

        _apply(world, reviewer_user, tenant_a)
        hashed = canonical_bytes(_artifact(world)["payload"]).decode("utf-8")
        for excluded in ("response_id", "entered_by_id", "amended_by_id", "created_at"):
            assert excluded not in hashed

    def test_answer_overridden_history_is_exported_separately(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        """Override rows must not be filed as reviewer amendments."""
        _apply(world, reviewer_user, tenant_a)
        exported = _exported(_artifact(world))
        assert len(exported["override_history"]) == 1
        assert "reviewer_amendments" not in exported

    def test_override_history_preserves_sequence(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        _apply(world, reviewer_user, tenant_a, value="first", reason="first reason")
        _apply(world, reviewer_user, tenant_a, value="second", reason="second reason")
        history = _exported(_artifact(world))["override_history"]
        assert [h["new_version"] for h in history] == [2, 3]

    def test_override_provenance_changes_the_checksum(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        before = _artifact(world)["checksum"]["value"]
        _apply(world, reviewer_user, tenant_a)
        assert _artifact(world)["checksum"]["value"] != before

    def test_changing_the_override_reason_changes_the_checksum(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        _apply(world, reviewer_user, tenant_a, value="v", reason="first reason")
        before = _artifact(world)["checksum"]["value"]
        _apply(world, reviewer_user, tenant_a, value="v", reason="second reason")
        assert _artifact(world)["checksum"]["value"] != before

    def test_an_artifact_without_overrides_is_unchanged_in_shape(self, world):
        """Backward compatibility: the conditional group adds nothing when absent."""
        artifact = _artifact(world)
        assert artifact["payload"]["export_schema_version"] == "1"
        assert "checksum" in artifact
        assert set(artifact) == {"checksum", "payload"}

    def test_override_reaches_the_csv_rendering(
        self, world, tenant_a, reviewer_user, reviewer_membership
    ):
        from iig_checklist.controlled_export import render_csv

        _apply(world, reviewer_user, tenant_a)
        rendered = render_csv(_artifact(world))
        assert "override" in rendered
        assert "Governed deviation reason." in rendered
