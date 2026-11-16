"""
FDA data import pipeline and release lifecycle tests. Every test that
plants a violation is noted.
"""

import pytest
from django.db import IntegrityError, transaction

from fda_data import importer, lifecycle
from fda_data.adapters import fda_iid_adapter, orange_book_products_adapter
from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    DosageFormMapping,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDCalculabilityStatus,
    IIDPrecedentRecord,
    OrangeBookProduct,
    RouteMapping,
    StrengthParseStatus,
)

from .conftest import make_release_file


def _approve_route_and_dosage_form(dataset_type="fda_iid"):
    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    RouteMapping.objects.create(
        source_dataset=dataset_type,
        source_raw_value="ORAL",
        controlled_route=route,
        status="approved",
    )
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    DosageFormMapping.objects.create(
        source_dataset=dataset_type,
        source_raw_value="TABLET",
        controlled_dosage_form=dosage_form,
        status="approved",
    )
    return route, dosage_form


def _ensure_mg_unit():
    unit, _ = ControlledUnit.objects.get_or_create(
        code="milligram", defaults={"symbol": "MG", "dimension": "mass", "active": True}
    )
    return unit


@pytest.mark.django_db
class TestReleaseRegistration:
    def test_registration_is_idempotent_by_checksum(self, orange_book_rows, user_a):
        file_1 = make_release_file(orange_book_rows)
        file_2 = make_release_file(orange_book_rows)
        release_1 = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="https://www.fda.gov/ob",
            file_obj=file_1,
            original_filename="products.json",
            imported_by=user_a,
        )
        release_2 = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book (re-registered)",
            official_source_reference="https://www.fda.gov/ob",
            file_obj=file_2,
            original_filename="products.json",
            imported_by=user_a,
        )
        assert release_1.pk == release_2.pk
        assert FDADataSourceRelease.objects.filter(dataset_type="orange_book_products").count() == 1

    def test_different_dataset_types_never_collide(self, orange_book_rows, user_a):
        file_1 = make_release_file(orange_book_rows)
        file_2 = make_release_file(orange_book_rows)
        r1 = importer.register_release(
            dataset_type="orange_book_products",
            source_name="OB",
            official_source_reference="ref",
            file_obj=file_1,
            original_filename="a.json",
            imported_by=user_a,
        )
        r2 = importer.register_release(
            dataset_type="orange_book_discontinued",
            source_name="OB discontinued",
            official_source_reference="ref",
            file_obj=file_2,
            original_filename="b.json",
            imported_by=user_a,
        )
        assert r1.pk != r2.pk


@pytest.mark.django_db
class TestOrangeBookImport:
    def test_products_and_applications_imported(self, orange_book_rows, user_a):
        _approve_route_and_dosage_form("orange_book_products")
        release = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="ref",
            file_obj=make_release_file(orange_book_rows),
            original_filename="products.json",
            imported_by=user_a,
        )
        neutral = orange_book_products_adapter(orange_book_rows)
        importer.import_orange_book_rows(release, neutral, user_a)

        assert OrangeBookProduct.objects.filter(release=release).count() == 2
        release.refresh_from_db()
        assert release.record_count_imported == 2
        assert release.record_count_failed == 0

    def test_dosage_form_route_split_and_normalized(self, orange_book_rows, user_a):
        _approve_route_and_dosage_form("orange_book_products")
        release = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="ref",
            file_obj=make_release_file(orange_book_rows),
            original_filename="products.json",
            imported_by=user_a,
        )
        neutral = orange_book_products_adapter(orange_book_rows)
        importer.import_orange_book_rows(release, neutral, user_a)
        product = OrangeBookProduct.objects.filter(release=release).first()
        assert product.dosage_form_raw == "TABLET"
        assert product.route_raw == "ORAL"
        assert product.route_normalized is not None
        assert product.dosage_form_normalized is not None

    def test_non_date_approval_text_preserved_not_dropped(self, orange_book_rows, user_a):
        # PLANTED VIOLATION (detected): "Approved Prior to Jan 1, 1982"
        # must be preserved as text, never coerced into a fake date.
        release = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="ref",
            file_obj=make_release_file(orange_book_rows),
            original_filename="products.json",
            imported_by=user_a,
        )
        neutral = orange_book_products_adapter(orange_book_rows)
        importer.import_orange_book_rows(release, neutral, user_a)
        old_product = OrangeBookProduct.objects.get(release=release, product_number="002")
        assert old_product.approval_date is None
        assert old_product.approval_date_text == "Approved Prior to Jan 1, 1982"

    def test_strength_parsed_when_simple(self, orange_book_rows, user_a):
        _ensure_mg_unit()
        release = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="ref",
            file_obj=make_release_file(orange_book_rows),
            original_filename="products.json",
            imported_by=user_a,
        )
        neutral = orange_book_products_adapter(orange_book_rows)
        importer.import_orange_book_rows(release, neutral, user_a)
        product = OrangeBookProduct.objects.get(release=release, product_number="001")
        assert product.strength_amount is not None
        assert product.strength_parse_status == StrengthParseStatus.PARSED

    def test_unparseable_strength_marked_review_required_not_guessed(self, user_a):
        # PLANTED VIOLATION (detected): a combination-strength string like
        # "10MG/5ML" must never be silently parsed into a wrong number --
        # it must be marked REVIEW_REQUIRED with the raw string preserved.
        rows = [
            {
                "Ingredient": "SYNTHETIC-COMBO",
                "DF;Route": "SOLUTION;ORAL",
                "Trade_Name": "Synthcombo",
                "Applicant": "Synthetic Pharma",
                "Strength": "10MG/5ML",
                "Appl_Type": "N",
                "Appl_No": "199999",
                "Product_No": "001",
            }
        ]
        release = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="ref",
            file_obj=make_release_file(rows),
            original_filename="products.json",
            imported_by=user_a,
        )
        neutral = orange_book_products_adapter(rows)
        importer.import_orange_book_rows(release, neutral, user_a)
        product = OrangeBookProduct.objects.get(release=release)
        assert product.strength_amount is None
        assert product.strength_parse_status == StrengthParseStatus.REVIEW_REQUIRED
        assert product.strength_raw == "10MG/5ML"

    def test_rerun_is_idempotent_no_duplicate_products(self, orange_book_rows, user_a):
        # PLANTED VIOLATION (detected): rerunning the same import must
        # never create duplicate OrangeBookProduct rows.
        release = importer.register_release(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="ref",
            file_obj=make_release_file(orange_book_rows),
            original_filename="products.json",
            imported_by=user_a,
        )
        neutral = orange_book_products_adapter(orange_book_rows)
        importer.import_orange_book_rows(release, neutral, user_a)
        count_after_first = OrangeBookProduct.objects.filter(release=release).count()
        importer.import_orange_book_rows(release, neutral, user_a)
        assert OrangeBookProduct.objects.filter(release=release).count() == count_after_first


@pytest.mark.django_db
class TestIidImport:
    def test_valid_potency_calculable(self, iid_rows, user_a):
        # One comparison path: calculable needs the unit's MEANING (an approved
        # unit mapping whose meaning is in force), not the legacy unit link.
        from fda_data.tests._meanings import per_dose_unit, put_in_force

        _approve_route_and_dosage_form("fda_iid")
        put_in_force(per_dose_unit(_ensure_mg_unit()), "MG")
        release = importer.register_release(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            file_obj=make_release_file(iid_rows),
            original_filename="iid.json",
            imported_by=user_a,
        )
        neutral = fda_iid_adapter(iid_rows)
        importer.import_iid_rows(release, neutral, user_a)
        record = IIDPrecedentRecord.objects.get(
            release=release, ingredient_name_raw="SYNTHETIC-STARCH"
        )
        assert record.potency_amount is not None
        assert record.calculability_status == IIDCalculabilityStatus.CALCULABLE
        assert str(record.potency_expression) == "MG per dose unit"

    def test_the_legacy_unit_link_alone_never_makes_a_record_calculable(self, iid_rows, user_a):
        """The old path: an ACTIVE legacy ControlledUnit that `lookup_unit` finds.
        It is still recorded for history, but the record is not calculable."""
        _approve_route_and_dosage_form("fda_iid")
        unit = _ensure_mg_unit()
        assert unit.active is True
        release = importer.register_release(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            file_obj=make_release_file(iid_rows),
            original_filename="iid.json",
            imported_by=user_a,
        )
        importer.import_iid_rows(release, fda_iid_adapter(iid_rows), user_a)
        record = IIDPrecedentRecord.objects.get(
            release=release, ingredient_name_raw="SYNTHETIC-STARCH"
        )
        assert record.potency_unit_normalized == unit  # history only
        assert record.potency_expression is None
        assert record.calculability_status == IIDCalculabilityStatus.POTENCY_UNIT_MISSING

    def test_missing_potency_never_forced_to_zero(self, iid_rows, user_a):
        # PLANTED VIOLATION (detected): a blank potency must remain null,
        # never coerced to 0.
        _approve_route_and_dosage_form("fda_iid")
        release = importer.register_release(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            file_obj=make_release_file(iid_rows),
            original_filename="iid.json",
            imported_by=user_a,
        )
        neutral = fda_iid_adapter(iid_rows)
        importer.import_iid_rows(release, neutral, user_a)
        record = IIDPrecedentRecord.objects.get(
            release=release, ingredient_name_raw="SYNTHETIC-BLANK-POTENCY"
        )
        assert record.potency_amount is None
        assert record.calculability_status == IIDCalculabilityStatus.POTENCY_MISSING

    def test_unmapped_route_flags_review_required(self, user_a):
        rows = [
            {
                "Ingredient Name": "SYNTHETIC-X",
                "Route": "UNMAPPED-ROUTE",
                "Dosage Form": "TABLET",
                "Potency": "10",
                "Unit": "MG",
            }
        ]
        release = importer.register_release(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            file_obj=make_release_file(rows),
            original_filename="iid.json",
            imported_by=user_a,
        )
        neutral = fda_iid_adapter(rows)
        importer.import_iid_rows(release, neutral, user_a)
        record = IIDPrecedentRecord.objects.get(release=release)
        assert record.calculability_status == IIDCalculabilityStatus.ROUTE_UNMAPPED

    def test_duplicate_row_within_release_idempotent(self, iid_rows, user_a):
        release = importer.register_release(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            file_obj=make_release_file(iid_rows),
            original_filename="iid.json",
            imported_by=user_a,
        )
        neutral = fda_iid_adapter(iid_rows)
        importer.import_iid_rows(release, neutral, user_a)
        count_after_first = IIDPrecedentRecord.objects.filter(release=release).count()
        importer.import_iid_rows(release, neutral, user_a)
        assert IIDPrecedentRecord.objects.filter(release=release).count() == count_after_first


@pytest.mark.django_db
class TestReleaseLifecycle:
    def _release(self, user_a):
        return FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            source_checksum_sha256="a" * 64,
            imported_by=user_a,
        )

    def test_imported_release_never_auto_active(self, user_a):
        release = self._release(user_a)
        assert release.status == FDAReleaseStatus.REGISTERED

    def test_cannot_activate_unapproved_release(self, user_a, vp_user):
        # PLANTED VIOLATION (detected): activation must require APPROVED
        # status first.
        release = self._release(user_a)
        with pytest.raises(lifecycle.InvalidTransition):
            lifecycle.activate(release, vp_user)

    def test_doer_cannot_approve_own_import_self_approval_blocked(self, user_a):
        from django.core.exceptions import PermissionDenied

        release = self._release(user_a)
        lifecycle.submit_for_review(release, user_a)
        with pytest.raises(PermissionDenied):
            lifecycle.approve(release, user_a)

    def test_full_walk_to_active(self, user_a, vp_user):
        release = self._release(user_a)
        release = lifecycle.submit_for_review(release, user_a)
        release = lifecycle.approve(release, vp_user)
        release = lifecycle.activate(release, vp_user)
        assert release.status == FDAReleaseStatus.ACTIVE

    def test_activation_supersedes_prior_active_release(self, user_a, vp_user):
        release_1 = self._release(user_a)
        release_1.source_checksum_sha256 = "b" * 64
        release_1.save()
        release_1 = lifecycle.submit_for_review(release_1, user_a)
        release_1 = lifecycle.approve(release_1, vp_user)
        release_1 = lifecycle.activate(release_1, vp_user)

        release_2 = FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="FDA IID v2",
            official_source_reference="ref",
            source_checksum_sha256="c" * 64,
            imported_by=user_a,
        )
        release_2 = lifecycle.submit_for_review(release_2, user_a)
        release_2 = lifecycle.approve(release_2, vp_user)
        release_2 = lifecycle.activate(release_2, vp_user)

        release_1.refresh_from_db()
        assert release_1.status == FDAReleaseStatus.SUPERSEDED
        assert release_2.status == FDAReleaseStatus.ACTIVE

    def test_second_simultaneous_active_release_blocked_at_db_level(self, user_a):
        # PLANTED VIOLATION (detected): the DB constraint must reject a
        # second ACTIVE release for the same dataset_type even if the
        # lifecycle service is bypassed entirely.
        release_1 = self._release(user_a)
        release_1.source_checksum_sha256 = "d" * 64
        release_1.status = FDAReleaseStatus.ACTIVE
        release_1.save()

        release_2 = FDADataSourceRelease(
            dataset_type="fda_iid",
            source_name="FDA IID v2",
            official_source_reference="ref",
            source_checksum_sha256="e" * 64,
            status=FDAReleaseStatus.ACTIVE,
            imported_by=user_a,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            release_2.save()

    def test_approved_release_is_immutable(self, user_a, vp_user):
        # PLANTED VIOLATION (detected): editing a field on an approved
        # release must be rejected by clean().
        from django.core.exceptions import ValidationError

        release = self._release(user_a)
        release = lifecycle.submit_for_review(release, user_a)
        release = lifecycle.approve(release, vp_user)
        release.source_name = "Tampered"
        with pytest.raises(ValidationError):
            release.full_clean()
