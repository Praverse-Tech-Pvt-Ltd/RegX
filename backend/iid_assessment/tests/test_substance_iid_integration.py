"""
Integration between the substance/UNII synonym-mapping service and the
IID matching/assessment engine: an approved synonym permits an exact
match; proposed/rejected/ambiguous synonyms never do; the selected
mapping is snapshotted; a later mapping change never mutates an existing
snapshot. Synthetic data only.
"""

from decimal import Decimal

import pytest

from fda_data.models import SubstanceMappingMethod, SubstanceMappingStatus, SubstanceSynonymMapping
from iid_assessment.assess import run_preview
from iid_assessment.decisions import PrecedentDecisionStatus
from iid_assessment.matching import MatchStatus


@pytest.mark.django_db
class TestSubstanceIdentityInIidAssessment:
    def test_approved_synonym_permits_exact_match(self, active_iid_setup):
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-STARCH-RAW",
            normalized_ingredient_name="SYNTHETIC STARCH",
            proposed_ingredient=active_iid_setup["ingredient"],
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        preview = run_preview(
            substance_name="SYNTHETIC STARCH",
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
        assert preview.substance_mapping_public_id is not None

    def test_proposed_synonym_produces_review_required(self, active_iid_setup):
        # PLANTED VIOLATION (detected): a merely-proposed synonym mapping
        # must never allow the assessment to proceed to a real comparison.
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-STARCH-RAW",
            normalized_ingredient_name="SYNTHETIC STARCH",
            proposed_ingredient=active_iid_setup["ingredient"],
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.PROPOSED,
        )
        preview = run_preview(
            substance_name="SYNTHETIC STARCH",
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.match_status == MatchStatus.REVIEW_REQUIRED
        assert preview.decision_status == PrecedentDecisionStatus.REVIEW_REQUIRED
        assert preview.selected_record is None
        assert preview.substance_mapping_public_id is None

    def test_rejected_synonym_produces_ingredient_ambiguous(self, active_iid_setup):
        # PLANTED VIOLATION (detected): a rejected mapping must never
        # produce a usable match -- and must resolve to
        # INGREDIENT_AMBIGUOUS, not silently fall back to NO_MATCH.
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-STARCH-RAW",
            normalized_ingredient_name="SYNTHETIC STARCH",
            proposed_ingredient=active_iid_setup["ingredient"],
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.REJECTED,
        )
        preview = run_preview(
            substance_name="SYNTHETIC STARCH",
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.match_status == MatchStatus.INGREDIENT_AMBIGUOUS
        assert preview.selected_record is None
        assert preview.substance_mapping_public_id is None

    def test_no_mapping_at_all_is_review_required_not_silently_matched(self, active_iid_setup):
        preview = run_preview(
            substance_name="COMPLETELY-UNSEEN-INGREDIENT",
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.match_status == MatchStatus.REVIEW_REQUIRED
        assert preview.selected_record is None

    def test_multiple_conflicting_approved_mappings_produce_review_required(self, active_iid_setup):
        from fda_data.models import IIDIngredient

        other_ingredient = IIDIngredient.objects.create(
            canonical_name="Other Starch", normalized_name="OTHER STARCH"
        )
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="AMBIG-A",
            normalized_ingredient_name="AMBIGUOUS STARCH",
            proposed_ingredient=active_iid_setup["ingredient"],
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="AMBIG-B",
            normalized_ingredient_name="AMBIGUOUS STARCH",
            proposed_ingredient=other_ingredient,
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.APPROVED,
        )
        preview = run_preview(
            substance_name="AMBIGUOUS STARCH",
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.match_status == MatchStatus.REVIEW_REQUIRED
        assert preview.selected_record is None

    def test_string_equality_alone_never_overrides_unresolved_identity(self, active_iid_setup):
        # PLANTED VIOLATION (detected): the raw substance name is byte-for-
        # byte identical to the ingredient's normalized_name, but with no
        # approved mapping, string equality alone must never be treated as
        # a confirmed exact canonical match here -- only an approved
        # SubstanceSynonymMapping or the direct IIDIngredient table lookup
        # (already exact) counts. Since resolve_substance_identity DOES
        # fall back to a direct IIDIngredient normalized_name match when no
        # mapping exists at all, this exercises that this fallback still
        # requires the exact stored canonical name -- a near-variant must
        # not match.
        preview = run_preview(
            substance_name="SYNTHETIC STARCH VARIANT",
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.match_status != MatchStatus.EXACT_MATCH

    def test_selected_mapping_is_snapshotted_and_survives_later_mapping_change(
        self, active_iid_setup, tenant_a
    ):
        from iid_assessment.models import AssessmentSnapshot

        mapping = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-STARCH-RAW",
            normalized_ingredient_name="SYNTHETIC STARCH",
            proposed_ingredient=active_iid_setup["ingredient"],
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        preview = run_preview(
            substance_name="SYNTHETIC STARCH",
            route_code="oral",
            dosage_form_code="tablet",
            active_release_public_id=active_iid_setup["release"].public_id,
            proposed_quantity_per_unit=Decimal("30"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
            maximum_dosage_units_per_day=Decimal("4"),
        )
        assert preview.substance_mapping_public_id == str(mapping.public_id)

        snapshot = AssessmentSnapshot.objects.create(
            tenant=tenant_a,
            formulation_component_public_id="11111111-1111-1111-1111-111111111111",
            formulation_version_public_id="22222222-2222-2222-2222-222222222222",
            iid_release_public_id=active_iid_setup["release"].public_id,
            iid_substance_mapping_public_id=preview.substance_mapping_public_id,
            match_status=preview.match_status,
            decision_status=preview.decision_status,
            decision_note=preview.decision_note,
        )

        # PLANTED VIOLATION (detected): retiring/superseding the mapping
        # after the fact must never retroactively alter the snapshot's
        # frozen reference to the mapping version it actually used.
        mapping.is_current = False
        mapping.full_clean()
        mapping.save(update_fields=["is_current", "updated_at"])

        replacement = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-STARCH-RAW",
            normalized_ingredient_name="SYNTHETIC STARCH",
            proposed_ingredient=active_iid_setup["ingredient"],
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.APPROVED,
        )

        snapshot.refresh_from_db()
        assert snapshot.iid_substance_mapping_public_id == mapping.public_id
        assert snapshot.iid_substance_mapping_public_id != replacement.public_id
