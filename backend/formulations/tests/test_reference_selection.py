"""Reference-product selection must name a real product in the ACTIVE Orange
Book release, and every identifier sent must agree with that product."""

import uuid

import pytest

from fda_data.models import (
    FDADataSourceRelease,
    FDAReleaseStatus,
    OrangeBookApplication,
    OrangeBookProduct,
)

BASE = "/api/regx/v1"


def _ob_product(status, checksum, appl_no="212379", product_no="001"):
    release = FDADataSourceRelease.objects.create(
        dataset_type="orange_book_products",
        source_name="Orange Book",
        official_source_reference="Test: real row from FDA EOBZIP_2026_08.zip",
        source_checksum_sha256=checksum * 64,
        status=status,
    )
    app = OrangeBookApplication.objects.create(
        release=release, application_type="N", application_number=appl_no
    )
    return OrangeBookProduct.objects.create(
        release=release,
        application=app,
        product_number=product_no,
        trade_name="AMZEEQ",
        active_ingredient_raw="MINOCYCLINE HYDROCHLORIDE",
        marketing_category="RX",
        rld_flag=True,
        reference_standard_flag=True,
    )


@pytest.fixture
def active_product(db):
    return _ob_product(FDAReleaseStatus.ACTIVE, "a")


@pytest.fixture
def formulation_product(api_client_a):
    resp = api_client_a.post(
        f"{BASE}/formulations/products/",
        data={
            "product_code": "PROD-REF",
            "proposed_product_name": "Name",
            "active_ingredient": "X",
        },
        format="json",
    )
    return resp.json()["public_id"]


def _select(client, formulation_public_id, **payload):
    return client.post(
        f"{BASE}/formulations/products/{formulation_public_id}/select-reference/",
        data=payload,
        format="json",
    )


def _payload(product, **overrides):
    data = {
        "application_number": product.application.application_number,
        "product_number": product.product_number,
        "product_public_id": str(product.public_id),
        "release_public_id": str(product.release.public_id),
        "justification": "Explicit selection.",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestReferenceSelectionValidation:
    def test_real_product_in_active_release_is_accepted_and_snapshotted(
        self, api_client_a, formulation_product, active_product
    ):
        resp = _select(api_client_a, formulation_product, **_payload(active_product))
        assert resp.status_code == 200
        body = resp.json()
        assert body["selected_ob_product_public_id"] == str(active_product.public_id)
        assert body["selected_ob_release_public_id"] == str(active_product.release.public_id)
        assert body["selected_ob_application_number"] == "212379"

    def test_unknown_product_is_refused(self, api_client_a, formulation_product, active_product):
        resp = _select(
            api_client_a,
            formulation_product,
            **_payload(active_product, product_public_id=str(uuid.uuid4())),
        )
        assert resp.status_code == 400
        assert "product_public_id" in str(resp.json())

    def test_product_in_a_non_active_release_is_refused(self, api_client_a, formulation_product):
        registered = _ob_product(FDAReleaseStatus.REGISTERED, "b")
        resp = _select(api_client_a, formulation_product, **_payload(registered))
        assert resp.status_code == 400
        assert "not in the active Orange Book release" in str(resp.json())

    def test_release_identifier_must_match(self, api_client_a, formulation_product, active_product):
        resp = _select(
            api_client_a,
            formulation_product,
            **_payload(active_product, release_public_id=str(uuid.uuid4())),
        )
        assert resp.status_code == 400
        assert "release_public_id" in str(resp.json())

    def test_application_and_product_numbers_must_match(
        self, api_client_a, formulation_product, active_product
    ):
        resp = _select(
            api_client_a,
            formulation_product,
            **_payload(active_product, application_number="099999", product_number="002"),
        )
        assert resp.status_code == 400
        body = str(resp.json())
        assert "application_number" in body and "product_number" in body

    def test_refused_selection_stores_nothing(self, api_client_a, formulation_product):
        _select(
            api_client_a,
            formulation_product,
            application_number="099999",
            product_number="001",
            product_public_id=str(uuid.uuid4()),
            release_public_id=str(uuid.uuid4()),
        )
        detail = api_client_a.get(f"{BASE}/formulations/products/{formulation_product}/")
        assert detail.json()["selected_ob_product_public_id"] is None
