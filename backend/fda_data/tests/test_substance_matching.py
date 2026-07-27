"""
resolve_substance_identity() candidate-generation tests: exact
canonical-name/UNII/CAS resolution, approved-synonym resolution, ambiguous
and multiple-candidate handling, rejected/proposed mappings never usable,
and fuzzy candidates never auto-approved. Synthetic data only.
"""

import pytest

from fda_data.models import (
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDIngredient,
    SubstanceMappingMethod,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)
from fda_data.substance_matching import SubstanceMatchStatus, resolve_substance_identity


def _make_release(checksum, status=FDAReleaseStatus.ACTIVE):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256=checksum,
        status=status,
    )


@pytest.mark.django_db
class TestResolveSubstanceIdentity:
    def test_no_identity_supplied_is_ambiguous(self):
        result = resolve_substance_identity()
        assert result.status == SubstanceMatchStatus.INGREDIENT_AMBIGUOUS

    def test_exact_canonical_ingredient_name_match(self):
        IIDIngredient.objects.create(
            canonical_name="Synthetic Starch", normalized_name="SYNTHETIC STARCH"
        )
        result = resolve_substance_identity(normalized_name="SYNTHETIC STARCH")
        assert result.status == SubstanceMatchStatus.EXACT_MATCH
        assert result.candidates[0].method == "EXACT_NAME"

    def test_exact_canonical_ingredient_unii_match(self):
        IIDIngredient.objects.create(
            canonical_name="Synthetic Starch", normalized_name="SYNTHETIC STARCH", unii="SYN0001"
        )
        result = resolve_substance_identity(unii="SYN0001")
        assert result.status == SubstanceMatchStatus.EXACT_MATCH
        assert result.candidates[0].method == "EXACT_UNII"

    def test_exact_canonical_ingredient_cas_match(self):
        IIDIngredient.objects.create(
            canonical_name="Synthetic Starch",
            normalized_name="SYNTHETIC STARCH",
            cas_number="9005-25-8",
        )
        result = resolve_substance_identity(cas_number="9005-25-8")
        assert result.status == SubstanceMatchStatus.EXACT_MATCH
        assert result.candidates[0].method == "EXACT_CAS"

    def test_approved_synonym_mapping_resolves(self):
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        result = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETIC")
        assert result.status == SubstanceMatchStatus.EXACT_MATCH
        assert result.candidates[0].ingredient_public_id == str(ingredient.public_id)

    def test_proposed_synonym_mapping_never_usable(self):
        # PLANTED VIOLATION (detected): a merely-proposed synonym mapping
        # must never be treated as a confirmed identity.
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.PROPOSED,
        )
        result = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETIC")
        assert result.status == SubstanceMatchStatus.REVIEW_REQUIRED
        assert result.reason_code == "MAPPING_PENDING_REVIEW"

    def test_rejected_synonym_mapping_never_usable(self):
        # PLANTED VIOLATION (detected): a rejected mapping must never
        # silently resolve, and must be distinguishable from "never
        # reviewed" -- it reports INGREDIENT_AMBIGUOUS, not REVIEW_REQUIRED.
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.REJECTED,
        )
        result = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETIC")
        assert result.status == SubstanceMatchStatus.INGREDIENT_AMBIGUOUS
        assert result.reason_code == "REJECTED_MAPPING"

    def test_multiple_conflicting_approved_mappings_never_auto_resolved(self):
        # PLANTED VIOLATION (detected): two approved mappings for the same
        # raw identity pointing at different ingredients must never be
        # auto-collapsed to one -- always MULTIPLE_CANDIDATES.
        ing_a = IIDIngredient.objects.create(canonical_name="Ingredient A", normalized_name="A")
        ing_b = IIDIngredient.objects.create(canonical_name="Ingredient B", normalized_name="B")
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="AMBIGUOUS-NAME",
            normalized_ingredient_name="AMBIGUOUS NAME",
            proposed_ingredient=ing_a,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="AMBIGUOUS-NAME-2",
            normalized_ingredient_name="AMBIGUOUS NAME",
            proposed_ingredient=ing_b,
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.APPROVED,
        )
        result = resolve_substance_identity(normalized_name="AMBIGUOUS NAME")
        assert result.status == SubstanceMatchStatus.MULTIPLE_CANDIDATES
        assert len(result.candidates) == 2

    def test_no_mapping_at_all_is_review_required(self):
        result = resolve_substance_identity(normalized_name="NEVER-SEEN-BEFORE")
        assert result.status == SubstanceMatchStatus.REVIEW_REQUIRED
        assert result.reason_code == "NO_APPROVED_MAPPING"

    def test_fuzzy_similarity_never_auto_approved(self):
        # This service performs exact matching only -- there is no fuzzy
        # matching code path at all, so a near-miss variant of an approved
        # mapping's raw identity simply does not resolve.
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        near_miss = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETC")
        assert near_miss.status != SubstanceMatchStatus.EXACT_MATCH

    def test_superseded_release_mapping_not_usable(self):
        # PLANTED VIOLATION (detected): an approved mapping scoped to a
        # release that has since been superseded must not silently keep
        # supplying identity resolutions.
        superseded_release = _make_release("a" * 64, status=FDAReleaseStatus.SUPERSEDED)
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        SubstanceSynonymMapping.objects.create(
            release=superseded_release,
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        result = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETIC")
        assert result.status != SubstanceMatchStatus.EXACT_MATCH

    def test_platform_master_mapping_always_usable(self):
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        SubstanceSynonymMapping.objects.create(
            release=None,
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        result = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETIC")
        assert result.status == SubstanceMatchStatus.EXACT_MATCH


@pytest.mark.django_db
class TestStaleReleaseNeverBlocksFallback:
    """Human-review remediation HR-04: a non-approved mapping scoped to a
    since-superseded release must never keep blocking a legitimate direct
    IIDIngredient exact match for a brand-new active release. It remains
    exactly as it was for any historical assessment snapshot that already
    referenced it (snapshots freeze their own data and never re-resolve),
    but it must not silently keep governing new resolutions."""

    def test_stale_proposed_mapping_on_superseded_release_does_not_block_fallback(self):
        superseded = _make_release("s4a" + "0" * 61, status=FDAReleaseStatus.SUPERSEDED)
        ingredient = IIDIngredient.objects.create(
            canonical_name="Stale Fallback Ingredient", normalized_name="STALE FALLBACK EXACT"
        )
        # A stale PROPOSED mapping left over on the now-superseded release.
        SubstanceSynonymMapping.objects.create(
            release=superseded,
            source_dataset="fda_iid",
            raw_ingredient_name="STALE-RAW",
            normalized_ingredient_name="STALE FALLBACK EXACT",
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.PROPOSED,
        )
        # DETECT: the direct canonical-ingredient fallback still resolves
        # -- the stale mapping on an unusable release does not block it.
        result = resolve_substance_identity(normalized_name="STALE FALLBACK EXACT")
        assert result.status == SubstanceMatchStatus.EXACT_MATCH
        assert result.candidates[0].ingredient_public_id == str(ingredient.public_id)

    def test_current_release_proposed_mapping_still_produces_review_required(self):
        active = _make_release("s4b" + "0" * 61, status=FDAReleaseStatus.ACTIVE)
        IIDIngredient.objects.create(
            canonical_name="Current Fallback Ingredient", normalized_name="CURRENT FALLBACK EXACT"
        )
        SubstanceSynonymMapping.objects.create(
            release=active,
            source_dataset="fda_iid",
            raw_ingredient_name="CURRENT-RAW",
            normalized_ingredient_name="CURRENT FALLBACK EXACT",
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.PROPOSED,
        )
        # A mapping on a genuinely usable (active) release still correctly
        # blocks the direct fallback and forces review.
        result = resolve_substance_identity(normalized_name="CURRENT FALLBACK EXACT")
        assert result.status == SubstanceMatchStatus.REVIEW_REQUIRED

    def test_current_release_rejected_mapping_still_produces_ambiguous(self):
        active = _make_release("s4c" + "0" * 61, status=FDAReleaseStatus.ACTIVE)
        IIDIngredient.objects.create(
            canonical_name="Rejected Fallback Ingredient",
            normalized_name="REJECTED FALLBACK EXACT",
        )
        SubstanceSynonymMapping.objects.create(
            release=active,
            source_dataset="fda_iid",
            raw_ingredient_name="REJECTED-RAW",
            normalized_ingredient_name="REJECTED FALLBACK EXACT",
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.REJECTED,
        )
        result = resolve_substance_identity(normalized_name="REJECTED FALLBACK EXACT")
        assert result.status == SubstanceMatchStatus.INGREDIENT_AMBIGUOUS

    def test_mapping_scoped_to_rejected_release_cannot_leak_into_resolution(self):
        # A mapping scoped to a release that was REJECTED outright (never
        # approved/activated at all, distinct from "superseded") must be
        # just as unusable as a superseded one -- _release_usable() only
        # ever honors APPROVED/ACTIVE.
        rejected_release = _make_release("s4d" + "0" * 61, status=FDAReleaseStatus.REJECTED)
        ingredient = IIDIngredient.objects.create(
            canonical_name="Rejected Release Ingredient",
            normalized_name="REJECTED RELEASE IDENTITY",
        )
        SubstanceSynonymMapping.objects.create(
            release=rejected_release,
            source_dataset="fda_iid",
            raw_ingredient_name="REJECTED-RELEASE-RAW",
            normalized_ingredient_name="REJECTED RELEASE IDENTITY",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.APPROVED,
        )
        result = resolve_substance_identity(normalized_name="REJECTED RELEASE IDENTITY")
        # The direct-IIDIngredient fallback still applies (no non-approved
        # mapping is blocking it), so this correctly still resolves via
        # the canonical ingredient table itself -- proving the approved
        # mapping on the rejected release was NOT what supplied the match.
        assert result.status == SubstanceMatchStatus.EXACT_MATCH
        assert result.candidates[0].mapping_public_id is None
