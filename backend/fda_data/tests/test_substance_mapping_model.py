"""
SubstanceSynonymMapping model tests: raw-identity immutability,
approved-mapping immutability, uniqueness scoping, UUID identity, and
release relation integrity. Synthetic data only.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from fda_data.models import (
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDIngredient,
    SubstanceMappingMethod,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)


def _make_release(checksum):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256=checksum,
        status=FDAReleaseStatus.ACTIVE,
    )


@pytest.mark.django_db
class TestSubstanceSynonymMappingModel:
    def test_public_id_is_uuid_and_unique(self):
        m1 = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
        )
        m2 = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-IBUPROFEN",
            normalized_ingredient_name="IBUPROFEN SYNTHETIC",
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
        )
        assert m1.public_id != m2.public_id
        assert m1.public_id is not None

    def test_raw_source_identity_is_immutable(self):
        mapping = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
        )
        mapping.raw_ingredient_name = "TAMPERED"
        with pytest.raises(ValidationError):
            mapping.full_clean()

        # Non-identity fields (e.g. review_reason) remain freely editable
        # while the mapping is not yet approved.
        mapping.refresh_from_db()
        mapping.review_reason = "Looks correct to me."
        mapping.full_clean()
        mapping.save()

    def test_approved_mapping_is_fully_immutable(self):
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        mapping = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            proposed_ingredient=ingredient,
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            status=SubstanceMappingStatus.APPROVED,
        )
        mapping.review_reason = "Changed my mind."
        with pytest.raises(ValidationError):
            mapping.full_clean()

    def test_no_duplicate_current_mapping_for_same_release_raw_identity(self):
        release = _make_release("a" * 64)
        SubstanceSynonymMapping.objects.create(
            release=release,
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            is_current=True,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            SubstanceSynonymMapping.objects.create(
                release=release,
                source_dataset="fda_iid",
                raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
                normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC DUPLICATE",
                mapping_method=SubstanceMappingMethod.MANUAL,
                is_current=True,
            )

    def test_superseding_a_mapping_retires_is_current_not_edits_it(self):
        release = _make_release("b" * 64)
        original = SubstanceSynonymMapping.objects.create(
            release=release,
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
            is_current=True,
        )
        original.is_current = False
        original.full_clean()
        original.save(update_fields=["is_current", "updated_at"])

        replacement = SubstanceSynonymMapping.objects.create(
            release=release,
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC CORRECTED",
            mapping_method=SubstanceMappingMethod.MANUAL,
            is_current=True,
        )
        assert replacement.pk != original.pk
        original.refresh_from_db()
        assert original.is_current is False

    def test_release_relation_valid_and_protected_on_delete(self):
        release = _make_release("c" * 64)
        SubstanceSynonymMapping.objects.create(
            release=release,
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
        )
        # PLANTED VIOLATION (detected): a release with approved-mapping
        # history must never be silently deletable out from under it.
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            release.delete()

    def test_platform_master_mapping_has_no_release(self):
        mapping = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
            normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
            mapping_method=SubstanceMappingMethod.EXACT_NAME,
        )
        assert mapping.release_id is None
