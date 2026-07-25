"""
Terminology mapping-review API tests: list, approve, reject. No fuzzy
mapping is ever auto-approved; approval/rejection always requires an
explicit fda_data.review-holding actor.
"""

import pytest

from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    DosageFormMapping,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDIngredient,
    MappingDecisionStatus,
    RouteMapping,
    SubstanceMappingMethod,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
    UnitMapping,
)

BASE = "/api/regx/v1"


@pytest.fixture
def route_mapping(db):
    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    return RouteMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value="ORAL",
        controlled_route=route,
        status=MappingDecisionStatus.PROPOSED,
    )


@pytest.fixture
def dosage_form_mapping(db):
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    return DosageFormMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value="TABLET",
        controlled_dosage_form=dosage_form,
        status=MappingDecisionStatus.PROPOSED,
    )


@pytest.fixture
def unit_mapping(db):
    unit = ControlledUnit.objects.create(
        code="milligram", symbol="MG", dimension="mass", active=True
    )
    return UnitMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value="MG",
        controlled_unit=unit,
        status=MappingDecisionStatus.PROPOSED,
    )


@pytest.mark.django_db
class TestMappingList:
    def test_doer_cannot_list_mappings(self, api_client_doer, route_mapping):
        # PLANTED VIOLATION (detected): only fda_data.review holders (VP/
        # Reviewer) may see mapping-review data -- a Doer must not.
        resp = api_client_doer.get(f"{BASE}/fda-data/mappings/")
        assert resp.status_code == 403

    def test_vp_lists_all_mapping_types(
        self, api_client_vp, route_mapping, dosage_form_mapping, unit_mapping
    ):
        resp = api_client_vp.get(f"{BASE}/fda-data/mappings/")
        assert resp.status_code == 200
        results = resp.json()["results"]
        types = {r["mapping_type"] for r in results}
        assert types == {"route", "dosage_form", "unit"}

    def test_filter_by_type(self, api_client_vp, route_mapping, dosage_form_mapping):
        resp = api_client_vp.get(f"{BASE}/fda-data/mappings/?type=route")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert all(r["mapping_type"] == "route" for r in results)
        assert len(results) == 1

    def test_filter_by_status(self, api_client_vp, route_mapping):
        route_mapping.status = MappingDecisionStatus.APPROVED
        route_mapping.reviewer = None
        route_mapping.save(update_fields=["status"])
        resp = api_client_vp.get(f"{BASE}/fda-data/mappings/?status=proposed")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_no_numeric_id_in_mapping_response(self, api_client_vp, route_mapping):
        resp = api_client_vp.get(f"{BASE}/fda-data/mappings/?type=route")
        result = resp.json()["results"][0]
        assert "id" not in result
        assert "pk" not in result
        assert result["public_id"] == str(route_mapping.public_id)


@pytest.mark.django_db
class TestMappingApproveReject:
    def test_doer_cannot_approve_mapping(self, api_client_doer, route_mapping):
        # PLANTED VIOLATION (detected): a Doer must never approve a mapping.
        resp = api_client_doer.post(
            f"{BASE}/fda-data/mappings/{route_mapping.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 403
        route_mapping.refresh_from_db()
        assert route_mapping.status == MappingDecisionStatus.PROPOSED

    def test_reviewer_cannot_approve_mapping(self, api_client_reviewer, route_mapping):
        # PLANTED VIOLATION (detected): approval requires fda_data.approve
        # (VP only) -- a Reviewer holding only fda_data.review must not be
        # able to approve, only submit-review/reject/return.
        resp = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{route_mapping.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 403

    def test_vp_approves_mapping(self, api_client_vp, route_mapping):
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{route_mapping.public_id}/approve/",
            data={"reason": "Exact match confirmed."},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        route_mapping.refresh_from_db()
        assert route_mapping.status == MappingDecisionStatus.APPROVED
        assert route_mapping.reviewer is not None

    def test_vp_rejects_mapping(self, api_client_vp, dosage_form_mapping):
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{dosage_form_mapping.public_id}/reject/",
            data={"reason": "Ambiguous source value."},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        dosage_form_mapping.refresh_from_db()
        assert dosage_form_mapping.status == MappingDecisionStatus.REJECTED

    def test_self_approval_blocked(self, api_client_vp, route_mapping, vp_user):
        route_mapping.reviewer = vp_user
        route_mapping.save(update_fields=["reviewer"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{route_mapping.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        route_mapping.refresh_from_db()
        assert route_mapping.status == MappingDecisionStatus.PROPOSED

    def test_approved_mapping_is_immutable(self, api_client_vp, route_mapping):
        first = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{route_mapping.public_id}/approve/",
            data={},
            format="json",
        )
        assert first.status_code == 200
        # PLANTED VIOLATION (detected): attempting to re-approve/mutate an
        # already-approved mapping's source value must fail at the model
        # layer (clean()) -- verified directly since the API only exposes
        # status/reason, not source_raw_value, as mutable.
        route_mapping.refresh_from_db()
        route_mapping.source_raw_value = "TAMPERED"
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            route_mapping.full_clean()

    def test_nonexistent_mapping_returns_generic_404(self, api_client_vp):
        import uuid

        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{uuid.uuid4()}/approve/", data={}, format="json"
        )
        assert resp.status_code == 404

    def test_mapping_detail_view(self, api_client_vp, route_mapping):
        resp = api_client_vp.get(f"{BASE}/fda-data/mappings/{route_mapping.public_id}/")
        assert resp.status_code == 200
        assert resp.json()["public_id"] == str(route_mapping.public_id)

    def test_affected_records_endpoint_paginated(self, api_client_vp, route_mapping):
        resp = api_client_vp.get(
            f"{BASE}/fda-data/mappings/{route_mapping.public_id}/affected-records/"
        )
        assert resp.status_code == 200
        assert "results" in resp.json()


@pytest.fixture
def substance_mapping(db):
    return SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
        normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
        proposed_unii="SYN0001",
        proposed_cas_number="9005-25-8",
        mapping_method=SubstanceMappingMethod.EXACT_UNII,
        status=SubstanceMappingStatus.PROPOSED,
    )


@pytest.mark.django_db
class TestSubstanceMappingLifecycle:
    def test_list_filters_to_substance_type_with_extra_fields(
        self, api_client_vp, substance_mapping
    ):
        resp = api_client_vp.get(f"{BASE}/fda-data/mappings/?type=substance")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["mapping_type"] == "substance"
        assert results[0]["proposed_unii"] == "SYN0001"
        assert results[0]["proposed_cas_number"] == "9005-25-8"
        assert results[0]["mapping_method"] == SubstanceMappingMethod.EXACT_UNII

    def test_submit_for_review_moves_to_under_review(self, api_client_reviewer, substance_mapping):
        resp = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping.public_id}/submit-review/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "under_review"
        substance_mapping.refresh_from_db()
        assert substance_mapping.status == SubstanceMappingStatus.UNDER_REVIEW

    def test_return_for_correction(self, api_client_reviewer, substance_mapping):
        substance_mapping.status = SubstanceMappingStatus.UNDER_REVIEW
        substance_mapping.save(update_fields=["status"])
        resp = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping.public_id}/return/",
            data={"reason": "UNII does not match ingredient name."},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "returned"
        substance_mapping.refresh_from_db()
        assert substance_mapping.status == SubstanceMappingStatus.RETURNED
        assert substance_mapping.review_reason == "UNII does not match ingredient name."

    def test_submit_review_not_valid_for_route_mapping(self, api_client_reviewer, route_mapping):
        # A route mapping's status field has no "under_review" choice --
        # attempting the substance-only lifecycle action on it must fail
        # closed with a structured 400, never a raw 500.
        resp = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{route_mapping.public_id}/submit-review/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        route_mapping.refresh_from_db()
        assert route_mapping.status == MappingDecisionStatus.PROPOSED

    def test_doer_cannot_submit_review_or_return(self, api_client_doer, substance_mapping):
        resp1 = api_client_doer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping.public_id}/submit-review/",
            data={},
            format="json",
        )
        assert resp1.status_code == 403
        resp2 = api_client_doer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping.public_id}/return/",
            data={},
            format="json",
        )
        assert resp2.status_code == 403

    def test_affected_records_safe_fields_only(self, api_client_vp, substance_mapping):
        release = FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            source_checksum_sha256="9" * 64,
            status=FDAReleaseStatus.ACTIVE,
            storage_key="platform/0/secret.json",
            original_filename="/var/secret/fda-iid.txt",
        )
        route = ControlledRoute.objects.create(
            code="oral", canonical_label="Oral", lifecycle="active"
        )
        dosage_form = ControlledDosageForm.objects.create(
            code="tablet", canonical_label="Tablet", lifecycle="active"
        )
        ingredient = IIDIngredient.objects.create(
            canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
        )
        from fda_data.models import IIDPrecedentRecord

        record = IIDPrecedentRecord.objects.create(
            release=release,
            ingredient=ingredient,
            ingredient_name_raw="SYNTHETIC-ACETAMINOPHEN",
            route_raw="ORAL",
            route_normalized=route,
            dosage_form_raw="TABLET",
            dosage_form_normalized=dosage_form,
            potency_amount=50,
            potency_unit_raw="MG",
            raw_row_checksum="8" * 64,
            calculability_status="calculable",
        )
        resp = api_client_vp.get(
            f"{BASE}/fda-data/mappings/{substance_mapping.public_id}/affected-records/"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        row = results[0]
        assert row["record_public_id"] == str(record.public_id)
        # DETECT: no numeric internal ID, no filesystem/storage path.
        assert "id" not in row
        assert "pk" not in row
        assert "storage_key" not in row
        assert "/var/secret" not in str(row)
        assert row["raw_value"] == "SYNTHETIC-ACETAMINOPHEN"

    def test_nonexistent_mapping_still_generic_404(self, api_client_vp):
        import uuid

        resp = api_client_vp.get(f"{BASE}/fda-data/mappings/{uuid.uuid4()}/affected-records/")
        assert resp.status_code == 404
