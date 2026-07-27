"""Orange Book search API filter tests."""

import pytest

from fda_data.models import (
    FDADataSourceRelease,
    FDAReleaseStatus,
    OrangeBookApplication,
    OrangeBookProduct,
)

BASE = "/api/regx/v1"


@pytest.fixture
def active_release(db):
    return FDADataSourceRelease.objects.create(
        dataset_type="orange_book_products",
        source_name="Synthetic Orange Book",
        official_source_reference="ref",
        source_checksum_sha256="a" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )


@pytest.fixture
def products(db, active_release):
    app_a = OrangeBookApplication.objects.create(
        release=active_release,
        application_type="A",
        application_number="099999",
        applicant_short_name="Synthetic Pharma",
    )
    rld = OrangeBookProduct.objects.create(
        release=active_release,
        application=app_a,
        product_number="001",
        trade_name="Synthacet",
        active_ingredient_raw="SYNTHETIC-ACETAMINOPHEN",
        dosage_form_raw="TABLET",
        route_raw="ORAL",
        strength_raw="500MG",
        rld_flag=True,
        reference_standard_flag=True,
        discontinued=False,
    )
    non_rld = OrangeBookProduct.objects.create(
        release=active_release,
        application=app_a,
        product_number="002",
        trade_name="Synthacet Forte",
        active_ingredient_raw="SYNTHETIC-ACETAMINOPHEN",
        dosage_form_raw="TABLET",
        route_raw="ORAL",
        strength_raw="650MG",
        rld_flag=False,
        reference_standard_flag=False,
        discontinued=True,
    )
    return {"rld": rld, "non_rld": non_rld}


@pytest.mark.django_db
class TestOrangeBookFilters:
    def test_filter_by_rld(self, api_client_doer, products):
        resp = api_client_doer.get(f"{BASE}/fda-data/orange-book/products/?rld=true")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["trade_name"] == "Synthacet"

    def test_filter_by_reference_standard(self, api_client_doer, products):
        resp = api_client_doer.get(f"{BASE}/fda-data/orange-book/products/?reference_standard=true")
        assert len(resp.json()["results"]) == 1

    def test_filter_by_discontinued(self, api_client_doer, products):
        resp = api_client_doer.get(f"{BASE}/fda-data/orange-book/products/?discontinued=true")
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["trade_name"] == "Synthacet Forte"

    def test_filter_by_application_type(self, api_client_doer, products):
        resp = api_client_doer.get(f"{BASE}/fda-data/orange-book/products/?application_type=A")
        assert len(resp.json()["results"]) == 2

    def test_filter_by_strength(self, api_client_doer, products):
        resp = api_client_doer.get(f"{BASE}/fda-data/orange-book/products/?strength=650")
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["trade_name"] == "Synthacet Forte"

    def test_no_reference_standard_never_auto_flagged(self, api_client_doer, products):
        # PLANTED VIOLATION (detected): a non-RLD/non-reference-standard
        # product must never appear when filtering for RLD=true, even
        # though it shares the same active ingredient/application.
        resp = api_client_doer.get(f"{BASE}/fda-data/orange-book/products/?rld=true")
        names = {r["trade_name"] for r in resp.json()["results"]}
        assert "Synthacet Forte" not in names
