# ruff: noqa: F811  (pytest fixtures imported from another test module)
"""QA-06 and QA-07 (docs/QA_BROWSER_TEST_2026-11-18.md), through the real
preview and releases endpoints, on the real-rows `world` fixture.

QA-06: the preview's reason must be true for the case. Before:
* an ingredient not in the IID said "Ingredient identity/synonym mapping
  requires reviewer confirmation";
* a dosage form the IID lists but no reviewer has mapped (SUSPENSION/ DROPS)
  said "DOSAGE_FORM_MISMATCH: route and dosage form must match exactly";
* a route REGX does not know said "ROUTE_MISMATCH: ... must match exactly".
The match and decision STATUSES are unchanged; only the explanation is.

QA-07: the preview and the releases list say how many records of the IID
release have no route/dosage-form link, and what an operator should do.
"""

from __future__ import annotations

import pytest

from fda_data.models import FDADataSourceRelease, FDAReleaseStatus, IIDPrecedentRecord, RouteMapping

from .test_one_path_comparison import world  # noqa: F401  (pytest fixture)

BASE = "/api/regx/v1"
PREVIEW = f"{BASE}/iid-assessments/preview/"
pytestmark = pytest.mark.django_db

CMC = ("CARBOXYMETHYLCELLULOSE SODIUM", "ORAL", "SUSPENSION/ DROPS")  # form left unmapped
TOCO = (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE")


def _post(client, world, **fields):
    data = {
        "active_release_public_id": str(world["iid"].public_id),
        "proposed_quantity_per_unit": "1",
        "proposed_quantity_unit": "mg",
        "total_dosage_unit_weight": "100",
        "total_dosage_unit_weight_unit": "mg",
        **fields,
    }
    resp = client.post(PREVIEW, data=data, format="json")
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _ingredient(world, key):
    return str(world["records"][key].ingredient.public_id)


class TestIngredient:
    def test_not_in_the_iid_says_not_found(self, api_client_doer, world):
        body = _post(
            api_client_doer,
            world,
            substance_name="SYNTHETIC UNKNOWN EXCIPIENT 123",
            route_code="R-ORAL",
            dosage_form_code="F-CAPSULE",
        )
        assert body["decision_status"] == "REVIEW_REQUIRED"  # unchanged governance outcome
        assert body["match_reason_code"] == "INGREDIENT_NOT_FOUND"
        assert "was not found in the active IID release" in body["decision_note"]
        assert "synonym mapping requires reviewer confirmation" not in body["decision_note"]


class TestRouteAndDosageForm:
    def test_an_unmapped_dosage_form_says_not_yet_mapped(self, api_client_doer, world):
        body = _post(
            api_client_doer,
            world,
            ingredient_public_id=_ingredient(world, CMC),
            route_code="R-ORAL",
            dosage_form_code="SUSPENSION/ DROPS",
        )
        assert body["match_status"] == "DOSAGE_FORM_MISMATCH"  # unchanged
        assert body["match_reason_code"] == "DOSAGE_FORM_NOT_MAPPED"
        assert "no reviewer has mapped this dosage form" in body["decision_note"]
        assert "must match exactly" not in body["decision_note"]

    def test_an_unknown_dosage_form_says_not_recognised(self, api_client_doer, world):
        body = _post(
            api_client_doer,
            world,
            ingredient_public_id=_ingredient(world, TOCO),
            route_code="R-BUCCAL",
            dosage_form_code="BLOB",
        )
        assert body["match_reason_code"] == "DOSAGE_FORM_NOT_RECOGNISED"
        assert "'BLOB' is not a recognised dosage form" in body["decision_note"]

    def test_an_unknown_route_says_not_recognised(self, api_client_doer, world):
        body = _post(
            api_client_doer,
            world,
            ingredient_public_id=_ingredient(world, TOCO),
            route_code="PER OS",
            dosage_form_code="F-CAPSULE",
        )
        assert body["match_status"] == "ROUTE_MISMATCH"
        assert body["match_reason_code"] == "ROUTE_NOT_RECOGNISED"
        assert "'PER OS' is not a recognised route" in body["decision_note"]
        assert "must match exactly" not in body["decision_note"]


class TestNoRecordForTheCombination:
    def test_known_ingredient_other_route_and_form(self, api_client_doer, world):
        body = _post(
            api_client_doer,
            world,
            ingredient_public_id=_ingredient(world, TOCO),
            route_code="R-BUCCAL",
            dosage_form_code="F-CAPSULE",
        )
        assert body["decision_status"] == "NO_MATCH"
        assert body["match_reason_code"] == "NO_RECORD_FOR_ROUTE_AND_FORM"

    def test_unmapped_records_of_the_ingredient_are_named(self, api_client_doer, world):
        body = _post(
            api_client_doer,
            world,
            ingredient_public_id=_ingredient(world, CMC),
            route_code="R-ORAL",
            dosage_form_code="F-CAPSULE",
        )
        assert body["match_reason_code"] == "RECORDS_NOT_LINKED"
        assert "no reviewer has mapped yet" in body["decision_note"]


class TestReleaseHealth:
    def test_preview_reports_unlinked_records_and_what_to_do(self, api_client_doer, world):
        body = _post(
            api_client_doer,
            world,
            ingredient_public_id=_ingredient(world, TOCO),
            route_code="R-BUCCAL",
            dosage_form_code="F-FILM, SOLUBLE",
        )
        health = body["release_health"]
        unlinked = IIDPrecedentRecord.objects.filter(
            release=world["iid"], dosage_form_normalized__isnull=True
        ).count()
        assert unlinked >= 1
        assert health["unlinked_records"] == unlinked
        assert (
            health["total_records"]
            == IIDPrecedentRecord.objects.filter(release=world["iid"]).count()
        )
        assert {"raw_value": "SUSPENSION/ DROPS", "records": unlinked} in health[
            "unmapped_dosage_forms"
        ]
        assert "Terminology Mappings" in health["operator_action"]

    def test_releases_list_explains_the_counts(self, api_client_doer, world):
        rows = api_client_doer.get(f"{BASE}/fda-data/releases/?dataset_type=fda_iid").json()[
            "results"
        ]
        assert rows[0]["link_health"]["unlinked_records"] >= 1
        assert "can never match them" in rows[0]["link_health"]["message"]

    def _release_with_a_fillable_link(self, status):
        release = FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="later",
            official_source_reference="t",
            source_checksum_sha256="d" * 64,
            status=status,
        )
        IIDPrecedentRecord.objects.create(
            release=release,
            ingredient_name_raw="X",
            route_raw="SOMEWHERE",
            dosage_form_raw="TABLET",
            source_row_locator="r:1",
            raw_row_checksum="1" * 64,
            calculability_status="route_unmapped",
        )
        from fda_data.models import ControlledRoute

        route = ControlledRoute.objects.create(
            code="R-SOMEWHERE", canonical_label="SOMEWHERE", lifecycle="active"
        )
        RouteMapping.objects.create(
            source_dataset="fda_iid",
            source_raw_value="SOMEWHERE",
            controlled_route=route,
            status="approved",
            is_current=True,
        )
        return release

    def test_before_review_the_operator_is_told_to_reresolve(self):
        from fda_data.release_health import iid_link_health

        health = iid_link_health(self._release_with_a_fillable_link(FDAReleaseStatus.REGISTERED))
        assert health["fillable_by_approved_mappings"] == 1
        assert "reresolve_terminology" in health["operator_action"]

    def test_after_review_the_operator_is_told_it_is_fixed(self):
        from fda_data.release_health import iid_link_health

        health = iid_link_health(self._release_with_a_fillable_link(FDAReleaseStatus.ACTIVE))
        assert "fixed once it is submitted for review" in health["operator_action"]
        assert "reresolve_terminology" not in health["operator_action"]
