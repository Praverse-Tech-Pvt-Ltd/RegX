"""
Substance/UNII synonym-mapping planted-failure scenarios that specifically
touch the IID matching/assessment engine (scenarios 2 and 10 of the 10
named substance-mapping scenarios; the other 8 live in
fda_data/tests/test_substance_planted_failures.py and do not import
iid_assessment, keeping fda_data platform-level and decoupled from the
tenant-scoped iid_assessment app).

Each test PLANTS the exact violation described, DETECTS it via an
assertion that the real system's guard rejects/blocks it, RESTORES to a
clean state, and RERUNS to confirm the legitimate path still works. No
planted violation is left committed. Synthetic data only.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDIngredient,
    IIDPrecedentRecord,
    SubstanceMappingMethod,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)
from fda_data.tests._meanings import per_dose_unit
from iid_assessment.assess import run_preview
from iid_assessment.matching import MatchStatus
from iid_assessment.models import AssessmentSnapshot


def _make_release(checksum, status=FDAReleaseStatus.ACTIVE):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256=checksum,
        status=status,
    )


def _iid_setup():
    """A minimal calculable IID precedent for the substance-resolution
    scenarios that need to reach a real comparison."""
    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    unit = ControlledUnit.objects.create(
        code="milligram", symbol="MG", dimension="mass", active=True
    )
    release = _make_release("f1" + "0" * 62)
    ingredient = IIDIngredient.objects.create(
        canonical_name="Synthetic Starch", normalized_name="SYNTHETIC STARCH"
    )
    IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="Synthetic Starch",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("50"),
        potency_unit_raw="MG",
        potency_expression=per_dose_unit(unit),
        raw_row_checksum="9" * 64,
        calculability_status="calculable",
    )
    return {
        "release": release,
        "ingredient": ingredient,
        "route": route,
        "dosage_form": dosage_form,
    }


# ---------------------------------------------------------------------------
# 2. Proposed mapping used in IID exact match
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s2_proposed_mapping_never_used_in_exact_match():
    setup = _iid_setup()
    mapping = SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-STARCH-RAW",
        normalized_ingredient_name="SYNTHETIC STARCH",
        proposed_ingredient=setup["ingredient"],
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
        status=SubstanceMappingStatus.PROPOSED,
    )
    # PLANT: attempt to run a full assessment preview using only the
    # proposed (not-yet-approved) synonym mapping.
    preview = run_preview(
        substance_name="SYNTHETIC STARCH",
        route_code="oral",
        dosage_form_code="tablet",
        active_release_public_id=setup["release"].public_id,
        proposed_quantity_per_unit=Decimal("30"),
        proposed_quantity_unit="milligram",
        total_dosage_unit_weight=Decimal("500"),
        total_dosage_unit_weight_unit="milligram",
    )
    # DETECT: never an exact match while proposed.
    assert preview.match_status != MatchStatus.EXACT_MATCH
    assert preview.selected_record is None
    # RESTORE/RERUN: approving the mapping makes the exact match legitimate.
    mapping.status = SubstanceMappingStatus.APPROVED
    mapping.full_clean()
    mapping.save(update_fields=["status", "updated_at"])
    preview2 = run_preview(
        substance_name="SYNTHETIC STARCH",
        route_code="oral",
        dosage_form_code="tablet",
        active_release_public_id=setup["release"].public_id,
        proposed_quantity_per_unit=Decimal("30"),
        proposed_quantity_unit="milligram",
        total_dosage_unit_weight=Decimal("500"),
        total_dosage_unit_weight_unit="milligram",
    )
    assert preview2.match_status == MatchStatus.EXACT_MATCH


# ---------------------------------------------------------------------------
# 10. Completed assessment snapshot changes after mapping update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s10_snapshot_never_changes_after_mapping_update(tenant_a):
    setup = _iid_setup()
    mapping = SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-STARCH-RAW",
        normalized_ingredient_name="SYNTHETIC STARCH",
        proposed_ingredient=setup["ingredient"],
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
        status=SubstanceMappingStatus.APPROVED,
    )
    preview = run_preview(
        substance_name="SYNTHETIC STARCH",
        route_code="oral",
        dosage_form_code="tablet",
        active_release_public_id=setup["release"].public_id,
        proposed_quantity_per_unit=Decimal("30"),
        proposed_quantity_unit="milligram",
        total_dosage_unit_weight=Decimal("500"),
        total_dosage_unit_weight_unit="milligram",
        maximum_dosage_units_per_day=Decimal("4"),
    )
    snapshot = AssessmentSnapshot.objects.create(
        tenant=tenant_a,
        formulation_component_public_id="33333333-3333-3333-3333-333333333333",
        formulation_version_public_id="44444444-4444-4444-4444-444444444444",
        iid_release_public_id=setup["release"].public_id,
        iid_substance_mapping_public_id=preview.substance_mapping_public_id,
        match_status=preview.match_status,
        decision_status=preview.decision_status,
        decision_note=preview.decision_note,
    )
    frozen_mapping_id = snapshot.iid_substance_mapping_public_id
    frozen_decision = snapshot.decision_status

    # PLANT: the mapping is later retired and superseded by a corrected
    # version -- simulate a subsequent re-run that would produce a
    # different decision, then attempt to retroactively "sync" the old
    # snapshot to it.
    mapping.is_current = False
    mapping.full_clean()
    mapping.save(update_fields=["is_current", "updated_at"])
    SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-STARCH-RAW",
        normalized_ingredient_name="SYNTHETIC STARCH",
        proposed_ingredient=setup["ingredient"],
        mapping_method=SubstanceMappingMethod.MANUAL,
        status=SubstanceMappingStatus.REJECTED,
    )
    snapshot.decision_status = "REVIEW_REQUIRED"
    with pytest.raises(ValidationError):
        snapshot.full_clean()

    # DETECT: the persisted snapshot is untouched.
    snapshot.refresh_from_db()
    assert str(snapshot.iid_substance_mapping_public_id) == frozen_mapping_id
    assert snapshot.decision_status == frozen_decision

    # RESTORE/RERUN: a fresh preview against the now-rejected identity
    # correctly reports the new state, but only as a NEW snapshot.
    preview2 = run_preview(
        substance_name="SYNTHETIC STARCH",
        route_code="oral",
        dosage_form_code="tablet",
        active_release_public_id=setup["release"].public_id,
        proposed_quantity_per_unit=Decimal("30"),
        proposed_quantity_unit="milligram",
        total_dosage_unit_weight=Decimal("500"),
        total_dosage_unit_weight_unit="milligram",
    )
    assert preview2.match_status == MatchStatus.INGREDIENT_AMBIGUOUS
