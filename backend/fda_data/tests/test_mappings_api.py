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
    MappingDecisionStatus,
    RouteMapping,
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
            f"{BASE}/fda-data/mappings/route/{route_mapping.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 403
        route_mapping.refresh_from_db()
        assert route_mapping.status == MappingDecisionStatus.PROPOSED

    def test_vp_approves_mapping(self, api_client_vp, route_mapping):
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/route/{route_mapping.public_id}/approve/",
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
            f"{BASE}/fda-data/mappings/dosage_form/{dosage_form_mapping.public_id}/reject/",
            data={"reason": "Ambiguous source value."},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        dosage_form_mapping.refresh_from_db()
        assert dosage_form_mapping.status == MappingDecisionStatus.REJECTED

    def test_approved_mapping_is_immutable(self, api_client_vp, route_mapping):
        first = api_client_vp.post(
            f"{BASE}/fda-data/mappings/route/{route_mapping.public_id}/approve/",
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
            f"{BASE}/fda-data/mappings/route/{uuid.uuid4()}/approve/", data={}, format="json"
        )
        assert resp.status_code == 404

    def test_unknown_mapping_type_returns_404(self, api_client_vp, route_mapping):
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/bogus_type/{route_mapping.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 404
