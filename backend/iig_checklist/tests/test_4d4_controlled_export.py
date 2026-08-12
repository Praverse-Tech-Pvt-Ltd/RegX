"""Milestone 4D-4 -- governed controlled export.

Specification: MILESTONE_4D_DISCOVERY.md section 17/section 18; MILESTONE_4D_4_DISCOVERY.md
section I.1 (``4D4-DEC-005`` provenance contract) and ``4D4-DEC-006`` (canonical form).

Fixtures are synthetic. No production regulatory content exists or is invented
here -- the content-approval gate is open at 0 of 20.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from iig_checklist.controlled_export import (
    EXPORT_SCHEMA_VERSION,
    ExecutionNotExportable,
    ExportPermissionDenied,
    build_export_artifact,
    canonical_bytes,
    export_execution,
    render_csv,
)
from iig_checklist.enums import AnswerType, CalculationStatus, DataSourceClassification

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


def _world(tenant, tenant_definition, user, *, approve=True):
    from formulations.models import FormulationVersion, ProductDevelopmentRecord
    from iig_checklist.models import (
        CalculationOutcome,
        ChecklistQuestion,
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
    ChecklistQuestion.objects.create(
        section=section,
        code="Q-MANUAL",
        question_text="Synthetic manual question",
        display_order=1,
        answer_type=AnswerType.SHORT_TEXT,
        data_source_classification=DataSourceClassification.USER_REQUIRED,
        criticality="low",
    )
    ChecklistQuestion.objects.create(
        section=section,
        code="Q-CALC",
        question_text="Synthetic calculated question",
        display_order=2,
        answer_type=AnswerType.CALCULATED_VALUE,
        data_source_classification=DataSourceClassification.SYSTEM_CALCULATED,
        calculation_binding_identifier="percentage_w_w",
        criticality="low",
    )

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code="PROD-EXP-01",
        proposed_product_name="Synthetic Export Product",
        active_ingredient="Synthetic Export Ingredient",
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

    # A completed calculated outcome with realistic governed provenance.
    CalculationOutcome.objects.filter(response__execution=execution).update(
        status=CalculationStatus.COMPLETE,
        value=Decimal("12.5000000000"),
        unit="gram",
        reason_code="",
        input_provenance={
            "_registry_binding_version": "1.0.0",
            "calculation_name": "calculate_percentage_w_w",
            "formula_version": "1.0.0",
            "_subject_component_public_id": "11111111-1111-4111-8111-111111111111",
            "assessment_snapshot_public_id": "22222222-2222-4222-8222-222222222222",
            "upstream_outcome_public_ids": ["33333333-3333-4333-8333-333333333333"],
            "component_mass": {
                "source_kind": "formulation_component",
                "source_public_id": "44444444-4444-4444-8444-444444444444",
                "source_question_code": "Q-MANUAL",
                "value": "0.2500000000",
                "expected_type": "decimal",
                "source_unit": "gram",
                "target_unit": "gram",
                "conversion_factor": "1",
                "conversion_rule_version": "1",
                "detail_code": None,
            },
        },
    )

    if approve:
        # Export is offered for an approved execution only (section 17). Set the status
        # directly: the lifecycle path is covered by its own suite and is not
        # what this module is testing.
        type(execution).objects.filter(pk=execution.pk).update(status="approved")
        execution.refresh_from_db()

    return {"execution": execution, "version": cv, "formulation": fv}


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    return _world(tenant_a, tenant_definition, user_a)


#: generated_at participates in the hashed payload (4D4-DEC-005 "Checksum
#: coverage"), so any test comparing two checksums must pin it. The clock is
#: frozen only here, by passing an explicit value into the service -- the
#: service's own UTC normalisation is untouched and still exercised.
FIXED_GENERATED_AT = datetime(2026, 3, 4, 5, 6, 7, 890123, tzinfo=UTC)


def _artifact(world_, generated_at=FIXED_GENERATED_AT):
    return build_export_artifact(execution=world_["execution"], generated_at=generated_at)


def _url(execution):
    return reverse("iig_checklist:execution-export", kwargs={"public_id": execution.public_id})


# ---------------------------------------------------------------------------
# A. Permissions and tenancy
# ---------------------------------------------------------------------------


class TestPermissionsAndTenancy:
    def test_vp_can_export(self, world, api_client_vp, vp_membership):
        resp = api_client_vp.get(_url(world["execution"]))
        assert resp.status_code == 200

    def test_doer_cannot_export_despite_holding_view(self, world, api_client_doer):
        """section 17 -- export authority is never implicit from `view`."""
        from authorization.models import Role
        from iig_checklist.permissions import (
            PERM_VIEW_EXECUTION,
            ROLE_PERMISSIONS,
        )

        assert PERM_VIEW_EXECUTION in ROLE_PERMISSIONS[Role.BuiltIn.DOER]
        resp = api_client_doer.get(_url(world["execution"]))
        assert resp.status_code == 403
        assert resp.data["error_code"] == "export_permission_denied"

    def test_reviewer_cannot_export(self, world, api_client_reviewer, reviewer_membership):
        resp = api_client_reviewer.get(_url(world["execution"]))
        assert resp.status_code == 403

    def test_direct_service_call_enforces_permission(self, world, tenant_a, user_a):
        """The guard is in the service, not only the view."""
        with pytest.raises(ExportPermissionDenied):
            export_execution(
                tenant=tenant_a,
                execution_public_id=world["execution"].public_id,
                actor=user_a,
                fmt="json",
            )

    def test_unknown_execution_is_404_not_403(self, world, api_client_vp, vp_membership):
        import uuid

        url = reverse("iig_checklist:execution-export", kwargs={"public_id": uuid.uuid4()})
        assert api_client_vp.get(url).status_code == 404

    def test_a_non_approved_execution_cannot_be_exported(
        self, db, tenant_a, tenant_definition, user_a, doer_membership, api_client_vp, vp_membership
    ):
        draft = _world(tenant_a, tenant_definition, user_a, approve=False)
        resp = api_client_vp.get(_url(draft["execution"]))
        assert resp.status_code == 409
        assert resp.data["error_code"] == "execution_not_exportable"

    def test_the_service_refuses_a_non_approved_execution(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        draft = _world(tenant_a, tenant_definition, user_a, approve=False)
        from django.utils import timezone

        with pytest.raises(ExecutionNotExportable):
            build_export_artifact(execution=draft["execution"], generated_at=timezone.now())


# ---------------------------------------------------------------------------
# B. Schema and identifiers
# ---------------------------------------------------------------------------


class TestSchemaAndIdentifiers:
    def test_schema_version_is_present_and_centrally_defined(self, world):
        payload = _artifact(world)["payload"]
        assert payload["export_schema_version"] == EXPORT_SCHEMA_VERSION

    def test_no_database_ids_anywhere_in_the_artifact(self, world):
        artifact = _artifact(world)
        blob = json.dumps(artifact)
        for forbidden in ('"id"', '"pk"', '"response_id"', '"execution_id"', '"question_id"'):
            assert forbidden not in blob

    def test_identity_is_public_uuids_and_governed_codes(self, world):
        payload = _artifact(world)["payload"]
        execution = world["execution"]
        assert payload["execution"]["execution_public_id"] == str(execution.public_id)
        assert payload["checklist_definition"]["version_public_id"] == str(
            world["version"].public_id
        )
        assert payload["checklist_definition"]["version_number"] == 1

    def test_every_response_carries_the_governed_shape(self, world):
        payload = _artifact(world)["payload"]
        assert payload["responses"]
        for response in payload["responses"]:
            assert set(response) == {
                "question_public_id",
                "question_code",
                "answer_type",
                "response_public_id",
                "response_version",
                "raw_value",
                "is_not_applicable",
                "not_applicable_reason",
                "data_source_type_snapshot",
                "system_derived_value",
                "calculation",
            }

    def test_no_model_repr_leaks(self, world):
        blob = json.dumps(_artifact(world))
        for leak in ("<ChecklistResponse", "<CalculationOutcome", "object at 0x", "Traceback"):
            assert leak not in blob


# ---------------------------------------------------------------------------
# C. Provenance -- 4D4-DEC-005
# ---------------------------------------------------------------------------


def _calculated(payload):
    rows = [r for r in payload["responses"] if r["calculation"] is not None]
    assert rows, "expected a calculated response in the world"
    return rows[0]


class TestProvenanceContract:
    def test_response_and_version_provenance_present(self, world):
        payload = _artifact(world)["payload"]
        for response in payload["responses"]:
            assert isinstance(response["response_version"], int)
        assert payload["checklist_definition"]["version_number"] == 1

    def test_applicability_and_classification_present(self, world):
        payload = _artifact(world)["payload"]
        for response in payload["responses"]:
            assert "is_not_applicable" in response
            assert "not_applicable_reason" in response
            assert response["data_source_type_snapshot"]

    def test_calculation_identity_and_version_present(self, world):
        provenance = _calculated(_artifact(world)["payload"])["calculation"]["provenance"]
        assert provenance["calculation_name"] == "calculate_percentage_w_w"
        assert provenance["formula_version"] == "1.0.0"
        assert provenance["registry_binding_version"] == "1.0.0"

    def test_dependency_chain_provenance_present(self, world):
        provenance = _calculated(_artifact(world)["payload"])["calculation"]["provenance"]
        assert provenance["assessment_snapshot_public_id"]
        assert provenance["upstream_outcome_public_ids"] == ["33333333-3333-4333-8333-333333333333"]
        assert provenance["subject_component_public_id"]

    def test_normalized_input_descriptor_fields(self, world):
        inputs = _calculated(_artifact(world)["payload"])["calculation"]["provenance"]["inputs"]
        descriptor = inputs["component_mass"]
        assert descriptor["source_kind"] == "formulation_component"
        assert descriptor["source_public_id"]
        assert descriptor["source_question_code"] == "Q-MANUAL"
        assert descriptor["value"] == "0.2500000000"
        assert descriptor["source_unit"] == "gram"
        assert descriptor["conversion_factor"] == "1"
        assert descriptor["conversion_rule_version"] == "1"

    def test_calculated_value_is_a_plain_decimal_string(self, world):
        calculation = _calculated(_artifact(world)["payload"])["calculation"]
        assert calculation["value"] == "12.5000000000"
        assert isinstance(calculation["value"], str)

    def test_outcome_inputs_column_is_not_exported(self, world):
        """`4D4-DEC-005` section 6 -- redundant raw kwargs are excluded."""
        calculation = _calculated(_artifact(world)["payload"])["calculation"]
        assert "inputs" not in calculation
        assert set(calculation) == {
            "outcome_public_id",
            "status",
            "value",
            "unit",
            "reason_code",
            "provenance",
        }

    def test_an_unexpected_internal_provenance_key_is_dropped(self, world):
        """The allow-list is the point: a new stored key must not auto-export."""
        from iig_checklist.models import CalculationOutcome

        outcome = CalculationOutcome.objects.filter(response__execution=world["execution"]).first()
        stored = dict(outcome.input_provenance)
        stored["_internal_debug_note"] = "must-not-appear"
        stored["component_mass"] = dict(stored["component_mass"])
        stored["component_mass"]["internal_row_id"] = 4242
        CalculationOutcome.objects.filter(pk=outcome.pk).update(input_provenance=stored)

        provenance = _calculated(_artifact(world)["payload"])["calculation"]["provenance"]
        assert "_internal_debug_note" not in provenance
        assert "internal_row_id" not in provenance["inputs"]["component_mass"]
        assert "must-not-appear" not in json.dumps(provenance)
        assert "4242" not in json.dumps(provenance)


# ---------------------------------------------------------------------------
# D. The ordinary API must stay unchanged
# ---------------------------------------------------------------------------


class TestOrdinaryApiUnchanged:
    def test_response_api_still_excludes_input_provenance(self, world, api_client_doer):
        url = reverse(
            "iig_checklist:execution-response-list",
            kwargs={"public_id": world["execution"].public_id},
        )
        resp = api_client_doer.get(url)
        assert resp.status_code == 200
        blob = json.dumps(resp.data)
        assert "input_provenance" not in blob
        assert "registry_binding_version" not in blob
        for row in resp.data["results"]:
            if row["calculation"]:
                assert set(row["calculation"]) == {
                    "outcome_public_id",
                    "status",
                    "value",
                    "unit",
                    "reason_code",
                }


# ---------------------------------------------------------------------------
# E. Canonicalisation -- 4D4-DEC-006
# ---------------------------------------------------------------------------


class TestCanonicalisation:
    def test_key_order_does_not_affect_canonical_bytes(self):
        assert canonical_bytes({"b": 1, "a": 2}) == canonical_bytes({"a": 2, "b": 1})

    def test_nested_key_order_does_not_affect_canonical_bytes(self):
        left = {"outer": {"z": 1, "a": {"q": 2, "b": 3}}}
        right = {"outer": {"a": {"b": 3, "q": 2}, "z": 1}}
        assert canonical_bytes(left) == canonical_bytes(right)

    def test_decimals_render_in_plain_notation_without_float(self):
        rendered = canonical_bytes({"v": Decimal("0.2500000000")}).decode("utf-8")
        assert '"0.2500000000"' in rendered
        assert "E" not in rendered and "e-" not in rendered

    def test_a_float_is_refused_rather_than_silently_hashed(self):
        from iig_checklist.controlled_export import ControlledExportError

        with pytest.raises(ControlledExportError):
            canonical_bytes({"v": 1.5})

    def test_timestamps_render_as_utc_z(self):
        from datetime import datetime, timedelta, timezone

        moment = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        rendered = canonical_bytes({"t": moment}).decode("utf-8")
        assert rendered.endswith('Z"}')
        assert "07:00:00" in rendered

    def test_list_order_is_preserved_not_sorted(self):
        """Semantic ordering is governed by the producer, so it is never re-sorted."""
        assert canonical_bytes({"v": ["b", "a"]}) != canonical_bytes({"v": ["a", "b"]})

    def test_bytes_are_utf8_and_not_ascii_escaped(self):
        assert canonical_bytes({"v": "ug"}) == b'{"v":"ug"}'


# ---------------------------------------------------------------------------
# F. Checksum
# ---------------------------------------------------------------------------


class TestChecksum:
    def test_same_state_yields_the_same_checksum(self, world):
        assert _artifact(world)["checksum"]["value"] == _artifact(world)["checksum"]["value"]

    def test_checksum_is_lowercase_hex_sha256(self, world):
        value = _artifact(world)["checksum"]["value"]
        assert _artifact(world)["checksum"]["algorithm"] == "sha256"
        assert len(value) == 64
        assert value == value.lower()
        int(value, 16)

    def test_generated_at_lives_in_the_hashed_payload_not_the_envelope(self, world):
        """4D4-DEC-005: included artifact provenance participates in the hash.

        An earlier revision put generated_at in an unhashed envelope, which let
        an issued artifact's timestamp be rewritten without breaking its
        checksum -- defeating section 17's "verify a previously-issued export was
        not altered after the fact".
        """
        artifact = _artifact(world)
        assert "generated_at" in artifact["payload"]
        assert "generated_at" not in artifact
        assert artifact["payload"]["generated_at"] in canonical_bytes(artifact["payload"]).decode(
            "utf-8"
        )

    def test_a_different_generated_at_changes_the_checksum(self, world):
        """Two export runs at different times legitimately differ."""
        early = _artifact(world, FIXED_GENERATED_AT)
        later = _artifact(world, FIXED_GENERATED_AT + timedelta(days=1))
        assert early["payload"]["generated_at"] != later["payload"]["generated_at"]
        assert early["checksum"]["value"] != later["checksum"]["value"]

    def test_the_checksum_field_is_not_recursively_hashed(self, world):
        """A hash cannot cover itself; the envelope is what stays outside."""
        artifact = _artifact(world)
        hashed = canonical_bytes(artifact["payload"]).decode("utf-8")
        assert artifact["checksum"]["value"] not in hashed
        assert "checksum" not in artifact["payload"]

    def test_generated_at_is_canonical_utc_z(self, world):
        """DEC-006 timestamp contract, now actually load-bearing on the hash."""
        naive_looking = datetime(2026, 3, 4, 10, 6, 7, 890123, tzinfo=UTC)
        from datetime import timezone as _tz

        shifted = naive_looking.astimezone(_tz(timedelta(hours=5)))
        # Same instant, different tzinfo -- canonical form must collapse both.
        assert (
            _artifact(world, naive_looking)["checksum"]["value"]
            == (_artifact(world, shifted)["checksum"]["value"])
        )
        assert _artifact(world, naive_looking)["payload"]["generated_at"].endswith("Z")

    def test_a_governed_answer_change_changes_the_checksum(self, world):
        from iig_checklist.models import ChecklistResponse

        before = _artifact(world)["checksum"]["value"]
        ChecklistResponse.objects.filter(
            execution=world["execution"], question__code="Q-MANUAL"
        ).update(raw_value={"value": "changed"})
        assert _artifact(world)["checksum"]["value"] != before

    def test_an_applicability_change_changes_the_checksum(self, world):
        from iig_checklist.models import ChecklistResponse

        before = _artifact(world)["checksum"]["value"]
        ChecklistResponse.objects.filter(
            execution=world["execution"], question__code="Q-MANUAL"
        ).update(is_not_applicable=True, not_applicable_reason="synthetic reason")
        assert _artifact(world)["checksum"]["value"] != before

    def test_a_provenance_change_changes_the_checksum(self, world):
        from iig_checklist.models import CalculationOutcome

        before = _artifact(world)["checksum"]["value"]
        outcome = CalculationOutcome.objects.filter(response__execution=world["execution"]).first()
        stored = dict(outcome.input_provenance)
        stored["formula_version"] = "9.9.9"
        CalculationOutcome.objects.filter(pk=outcome.pk).update(input_provenance=stored)
        assert _artifact(world)["checksum"]["value"] != before

    def test_an_excluded_internal_field_does_not_move_the_checksum(self, world):
        """A field outside the export contract cannot alter the artifact."""
        from iig_checklist.models import CalculationOutcome

        before = _artifact(world)["checksum"]["value"]
        outcome = CalculationOutcome.objects.filter(response__execution=world["execution"]).first()
        stored = dict(outcome.input_provenance)
        stored["_not_in_the_contract"] = "irrelevant"
        CalculationOutcome.objects.filter(pk=outcome.pk).update(
            input_provenance=stored, rounding_rule="something else"
        )
        assert _artifact(world)["checksum"]["value"] == before


# ---------------------------------------------------------------------------
# G. CSV rendering and safety
# ---------------------------------------------------------------------------


class TestCsvRendering:
    @pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
    def test_formula_injection_is_neutralised(self, world, trigger):
        from iig_checklist.models import ChecklistResponse

        ChecklistResponse.objects.filter(
            execution=world["execution"], question__code="Q-MANUAL"
        ).update(not_applicable_reason=f"{trigger}cmd|'/c calc'!A0")

        rendered = render_csv(_artifact(world))
        assert f"'{trigger}cmd" in rendered

    def test_csv_carries_the_same_checksum_as_the_json_artifact(self, world):
        artifact = _artifact(world)
        rendered = render_csv(artifact)
        assert artifact["checksum"]["value"] in rendered
        assert EXPORT_SCHEMA_VERSION in rendered

    def test_csv_uses_the_shared_helper(self):
        """Not a second implementation -- section 17 forbids new CSV-safety code."""
        import iig_checklist.controlled_export as module
        from common.csv_safety import csv_safe_cell

        assert module.csv_safe_cell is csv_safe_cell

    def test_csv_contains_every_response(self, world):
        rendered = render_csv(_artifact(world))
        assert "Q-MANUAL" in rendered
        assert "Q-CALC" in rendered

    def test_http_csv_download(self, world, api_client_vp, vp_membership):
        resp = api_client_vp.get(_url(world["execution"]) + "?export_format=csv")
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        assert "attachment;" in resp["Content-Disposition"]
        assert resp["X-RegX-Export-Checksum"]

    def test_an_unsupported_format_is_refused(self, world, api_client_vp, vp_membership):
        """section 17 ships JSON and CSV only; PDF/Word are deferred beyond 4D."""
        resp = api_client_vp.get(_url(world["execution"]) + "?export_format=pdf")
        assert resp.status_code == 400
        assert resp.data["error_code"] == "unsupported_export_format"


# ---------------------------------------------------------------------------
# H. Audit, and the fields still gated on open decisions
# ---------------------------------------------------------------------------


class TestAuditAndDeferredFields:
    def test_export_emits_a_governed_audit_event_with_the_checksum(
        self, world, api_client_vp, vp_membership, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client_vp.get(_url(world["execution"]))
        assert resp.status_code == 200

        event = AuditEvent.objects.filter(event_type="iig_checklist.execution.exported").latest(
            "id"
        )
        assert event.payload["checksum"] == resp["X-RegX-Export-Checksum"]
        assert event.payload["export_schema_version"] == EXPORT_SCHEMA_VERSION
        assert event.payload["format"] == "json"

    def test_override_provenance_is_not_invented(self, world):
        """`4D4-DEC-004` is open -- schema 1 must not guess its vocabulary."""
        blob = json.dumps(_artifact(world))
        assert "override_reason" not in blob
        assert "override" not in blob

    def test_approval_metadata_is_not_invented(self, world):
        """`4D4-DEC-008` is open -- schema 1 must not guess its shape."""
        assert "approval_metadata" not in json.dumps(_artifact(world))


# ---------------------------------------------------------------------------
# I. Conditional reviewer-amendment provenance -- 4D4-DEC-005
# ---------------------------------------------------------------------------


def _amend(world_, user, *, prior_version, new_version, reason, new_value):
    """Append one governed reviewer-conclusion amendment row."""
    from iig_checklist.models import ChecklistResponse, ChecklistResponseHistory

    response = ChecklistResponse.objects.get(
        execution=world_["execution"], question__code="Q-MANUAL"
    )
    return ChecklistResponseHistory.objects.create(
        response=response,
        prior_raw_value={"value": "before"},
        new_raw_value={"value": new_value},
        prior_is_not_applicable=False,
        new_is_not_applicable=False,
        prior_not_applicable_reason=None,
        new_not_applicable_reason=None,
        prior_entered_by=user,
        prior_entered_at=FIXED_GENERATED_AT,
        prior_version=prior_version,
        new_version=new_version,
        correction_reason=reason,
        amended_by=user,
        source_classification_snapshot=DataSourceClassification.USER_REQUIRED,
    )


def _amendments_of(artifact, code="Q-MANUAL"):
    for response in artifact["payload"]["responses"]:
        if response["question_code"] == code:
            return response.get("reviewer_amendments")
    raise AssertionError(f"no response for {code}")


class TestReviewerAmendmentProvenance:
    def test_absent_when_no_governed_amendment_exists(self, world):
        """DEC-005 makes reviewer provenance conditional -- no empty placeholder."""
        for response in _artifact(world)["payload"]["responses"]:
            assert "reviewer_amendments" not in response

    def test_reviewer_conclusion_note_is_conditional(self, world):
        """MINOR-1: omitted rather than emitted as a meaningless null."""
        artifact = _artifact(world)
        assert "reviewer_conclusion_note" not in artifact["payload"]["execution"]

        world["execution"].reviewer_conclusion_note = "governed conclusion"
        world["execution"].save(update_fields=["reviewer_conclusion_note"])
        after = _artifact(world)
        assert after["payload"]["execution"]["reviewer_conclusion_note"] == "governed conclusion"
        assert after["checksum"]["value"] != artifact["checksum"]["value"]

    def test_included_when_a_governed_amendment_exists(self, world, user_a):
        _amend(world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x")
        amendments = _amendments_of(_artifact(world))
        assert len(amendments) == 1
        assert amendments[0]["correction_reason"] == "typo"
        assert amendments[0]["prior_version"] == 1
        assert amendments[0]["new_version"] == 2

    def test_projection_is_allow_listed_and_carries_no_db_ids(self, world, user_a):
        from iig_checklist.controlled_export import ALLOWED_AMENDMENT_FIELDS

        amendment = _amend(
            world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x"
        )
        projected = _amendments_of(_artifact(world))[0]
        assert set(projected) <= ALLOWED_AMENDMENT_FIELDS
        # Public identity only -- never the PK, never the actor's email.
        assert projected["amended_by_public_id"] == str(user_a.public_id)
        blob = json.dumps(_artifact(world), default=str)
        assert user_a.email not in blob
        assert f'"{amendment.pk}"' not in blob
        assert "response_id" not in blob

    def test_amendment_order_is_governed_sequence_not_alphabetical(self, world, user_a):
        _amend(world, user_a, prior_version=2, new_version=3, reason="zzz second", new_value="b")
        _amend(world, user_a, prior_version=1, new_version=2, reason="aaa first", new_value="a")
        amendments = _amendments_of(_artifact(world))
        assert [a["new_version"] for a in amendments] == [2, 3]
        # Alphabetical ordering would have put "aaa first" first regardless;
        # version order is what proves the sequence is governed, not sorted.
        assert [a["correction_reason"] for a in amendments] == ["aaa first", "zzz second"]

    def test_order_is_deterministic_across_exports(self, world, user_a):
        _amend(world, user_a, prior_version=2, new_version=3, reason="second", new_value="b")
        _amend(world, user_a, prior_version=1, new_version=2, reason="first", new_value="a")
        assert _artifact(world)["checksum"]["value"] == _artifact(world)["checksum"]["value"]

    def test_adding_an_amendment_changes_the_checksum(self, world, user_a):
        before = _artifact(world)["checksum"]["value"]
        _amend(world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x")
        assert _artifact(world)["checksum"]["value"] != before

    def test_changing_an_exported_amendment_field_changes_the_checksum(self, world, user_a):
        """Tamper evidence over amendment content.

        The ORM refuses both ``save()`` and ``update()`` on these rows, so the
        only way to alter one is behind the guard's back -- which is exactly the
        scenario section 17's checksum exists to expose. Raw SQL reproduces it.
        """
        from django.db import connection

        amendment = _amend(
            world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x"
        )
        before = _artifact(world)["checksum"]["value"]
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE iig_checklist_checklistresponsehistory "
                "SET correction_reason = %s WHERE id = %s",
                ["tampered", amendment.pk],
            )
        assert _artifact(world)["checksum"]["value"] != before

    def test_a_non_exported_history_field_does_not_move_the_checksum(self, world, user_a):
        from django.db import connection

        amendment = _amend(
            world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x"
        )
        before = _artifact(world)["checksum"]["value"]
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE iig_checklist_checklistresponsehistory SET updated_at = %s WHERE id = %s",
                [FIXED_GENERATED_AT + timedelta(days=9), amendment.pk],
            )
        assert _artifact(world)["checksum"]["value"] == before

    def test_db_ids_and_audit_columns_never_reach_the_hashed_bytes(self, world, user_a):
        amendment = _amend(
            world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x"
        )
        hashed = canonical_bytes(_artifact(world)["payload"]).decode("utf-8")
        for excluded in ("created_at", "updated_at", "response_id", "amended_by_id"):
            assert excluded not in hashed
        assert f":{amendment.pk}," not in hashed

    def test_amendments_reach_the_csv_rendering(self, world, user_a):
        _amend(world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x")
        rendered = render_csv(_artifact(world))
        assert "reviewer_amendments" in rendered
        assert "typo" in rendered

    def test_ordinary_response_api_does_not_expose_amendments(
        self, world, user_a, api_client_vp, vp_membership
    ):
        """DEC-005 projection boundary -- export-only, never the read model."""
        _amend(world, user_a, prior_version=1, new_version=2, reason="typo", new_value="x")
        url = reverse(
            "iig_checklist:execution-response-list",
            kwargs={"public_id": world["execution"].public_id},
        )
        resp = api_client_vp.get(url)
        assert resp.status_code == 200
        body = json.dumps(resp.json())
        assert "reviewer_amendments" not in body
        assert "correction_reason" not in body
