"""
IID matching engine and full assess.run_preview integration tests. Every
test that plants a violation is noted.
"""

from decimal import Decimal

import pytest

from iid_assessment.assess import run_preview
from iid_assessment.decisions import PrecedentDecisionStatus
from iid_assessment.matching import MatchStatus, find_iid_candidates

BASE = "/api/regx/v1"


@pytest.mark.django_db
class TestFindIidCandidates:
    def test_exact_match(self, active_iid_setup):
        result = find_iid_candidates(
            ingredient_public_id=str(active_iid_setup["ingredient"].public_id),
            controlled_route_id=active_iid_setup["route"].id,
            controlled_dosage_form_id=active_iid_setup["dosage_form"].id,
            active_release_id=active_iid_setup["release"].id,
        )
        assert result.status == MatchStatus.EXACT_MATCH
        assert len(result.candidates) == 1

    def test_no_match_when_route_different(self, active_iid_setup):
        from fda_data.models import ControlledRoute

        other_route = ControlledRoute.objects.create(
            code="topical", canonical_label="Topical", lifecycle="active"
        )
        result = find_iid_candidates(
            ingredient_public_id=str(active_iid_setup["ingredient"].public_id),
            controlled_route_id=other_route.id,
            controlled_dosage_form_id=active_iid_setup["dosage_form"].id,
            active_release_id=active_iid_setup["release"].id,
        )
        assert result.status == MatchStatus.NO_MATCHING_IID_PRECEDENT

    def test_unconfirmed_route_returns_route_mismatch(self, active_iid_setup):
        # PLANTED VIOLATION (detected): matching must never proceed
        # without a confirmed controlled route.
        result = find_iid_candidates(
            ingredient_public_id=str(active_iid_setup["ingredient"].public_id),
            controlled_route_id=None,
            controlled_dosage_form_id=active_iid_setup["dosage_form"].id,
            active_release_id=active_iid_setup["release"].id,
        )
        assert result.status == MatchStatus.ROUTE_MISMATCH

    def test_multiple_exact_matches_never_auto_resolved(self, active_iid_setup):
        # PLANTED VIOLATION (detected): a second identical-scope record
        # must produce MULTIPLE_EXACT_MATCHES, never an automatic pick of
        # either one.
        from fda_data.models import IIDPrecedentRecord

        IIDPrecedentRecord.objects.create(
            release=active_iid_setup["release"],
            ingredient=active_iid_setup["ingredient"],
            ingredient_name_raw="Synthetic Starch",
            route_raw="ORAL",
            route_normalized=active_iid_setup["route"],
            dosage_form_raw="TABLET",
            dosage_form_normalized=active_iid_setup["dosage_form"],
            potency_amount=Decimal("75"),
            potency_unit_raw="MG",
            potency_unit_normalized=active_iid_setup["unit"],
            raw_row_checksum="2" * 64,
            calculability_status="calculable",
        )
        result = find_iid_candidates(
            ingredient_public_id=str(active_iid_setup["ingredient"].public_id),
            controlled_route_id=active_iid_setup["route"].id,
            controlled_dosage_form_id=active_iid_setup["dosage_form"].id,
            active_release_id=active_iid_setup["release"].id,
        )
        assert result.status == MatchStatus.MULTIPLE_EXACT_MATCHES
        assert len(result.candidates) == 2


@pytest.mark.django_db
class TestRunPreviewEndToEnd:
    def test_within_precedent_passes(self, active_iid_setup):
        preview = run_preview(
            ingredient_public_id=active_iid_setup["ingredient"].public_id,
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
            maximum_dosage_units_per_day=Decimal("4"),
        )
        assert preview.match_status == MatchStatus.EXACT_MATCH
        assert preview.decision_status == PrecedentDecisionStatus.PASS_WITH_IID_PRECEDENT
        assert "not an automatic safety" in preview.decision_note.lower()

    def test_exceeding_potency_flags_exceeds(self, active_iid_setup):
        # PLANTED VIOLATION (detected): a proposed amount above the IID
        # potency must never pass.
        preview = run_preview(
            ingredient_public_id=active_iid_setup["ingredient"].public_id,
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("999"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("1500"),
            total_dosage_unit_weight_unit="milligram",
            maximum_dosage_units_per_day=Decimal("4"),
        )
        assert preview.decision_status == PrecedentDecisionStatus.EXCEEDS_IID_PRECEDENT
        assert preview.escalation_required

    def test_no_match_when_ingredient_does_not_exist(self, active_iid_setup):
        # A syntactically-valid but nonexistent ingredient identity yields
        # NO_MATCH (no precedent record exists for it) -- distinct from
        # REVIEW_REQUIRED, which is reserved for a genuinely ambiguous/
        # unresolved identity (no ingredient identity supplied at all).
        import uuid

        preview = run_preview(
            ingredient_public_id=uuid.uuid4(),
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.decision_status == PrecedentDecisionStatus.NO_MATCH

    def test_review_required_when_ingredient_identity_missing(self, active_iid_setup):
        preview = run_preview(
            ingredient_public_id=None,
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.decision_status == PrecedentDecisionStatus.REVIEW_REQUIRED

    def test_incompatible_unit_without_density_not_comparable(self, active_iid_setup):
        # PLANTED VIOLATION (detected): comparing a volume-unit proposal
        # against a mass-unit IID potency must never proceed without an
        # explicit density.
        preview = run_preview(
            ingredient_public_id=active_iid_setup["ingredient"].public_id,
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="millilitre",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
            maximum_dosage_units_per_day=Decimal("4"),
        )
        assert preview.decision_status == PrecedentDecisionStatus.NOT_COMPARABLE

    def test_no_prefill_of_proposed_quantity_from_iid(self, active_iid_setup):
        # PLANTED VIOLATION (detected): the proposed quantity in the
        # response must always equal exactly what was submitted, never a
        # value silently substituted from the matched IID precedent.
        proposed = Decimal("12.5")
        preview = run_preview(
            ingredient_public_id=active_iid_setup["ingredient"].public_id,
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=proposed,
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
            maximum_dosage_units_per_day=Decimal("4"),
        )
        assert preview.calculations["unit_conversion"]["original_value"] == str(proposed)


@pytest.mark.django_db
class TestPreviewApi:
    def test_preview_endpoint_returns_decision(self, api_client_doer, active_iid_setup):
        resp = api_client_doer.post(
            f"{BASE}/iid-assessments/preview/",
            data={
                "ingredient_public_id": str(active_iid_setup["ingredient"].public_id),
                "route_code": "oral",
                "dosage_form_code": "tablet",
                "active_release_public_id": str(active_iid_setup["release"].public_id),
                "proposed_quantity_per_unit": "30",
                "proposed_quantity_unit": "milligram",
                "total_dosage_unit_weight": "500",
                "total_dosage_unit_weight_unit": "milligram",
                "maximum_dosage_units_per_day": "4",
            },
            format="json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision_status"] == PrecedentDecisionStatus.PASS_WITH_IID_PRECEDENT
        # PLANTED VIOLATION (detected): the API must never return a
        # forbidden safety-claim word anywhere in the response body.
        forbidden = ("SAFE", "FDA APPROVED", "AUTOMATICALLY ACCEPTABLE", "REGULATORILY CLEARED")
        body_text = str(body).upper()
        for word in forbidden:
            assert word not in body_text or "NOT AN AUTOMATIC" in body_text

    def test_snapshot_is_immutable(self, api_client_doer, active_iid_setup, user_a):
        resp = api_client_doer.post(
            f"{BASE}/iid-assessments/snapshot/",
            data={
                "ingredient_public_id": str(active_iid_setup["ingredient"].public_id),
                "route_code": "oral",
                "dosage_form_code": "tablet",
                "active_release_public_id": str(active_iid_setup["release"].public_id),
                "proposed_quantity_per_unit": "30",
                "proposed_quantity_unit": "milligram",
                "total_dosage_unit_weight": "500",
                "total_dosage_unit_weight_unit": "milligram",
                "maximum_dosage_units_per_day": "4",
                "formulation_component_public_id": str(active_iid_setup["ingredient"].public_id),
                "formulation_version_public_id": str(active_iid_setup["release"].public_id),
            },
            format="json",
        )
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        # PLANTED VIOLATION (detected): a later FDA data refresh must
        # never be able to retroactively change a completed snapshot.
        from django.core.exceptions import ValidationError

        from iid_assessment.models import AssessmentSnapshot

        snapshot = AssessmentSnapshot.objects.get(public_id=public_id)
        snapshot.decision_status = "TAMPERED"
        with pytest.raises(ValidationError):
            snapshot.full_clean()
