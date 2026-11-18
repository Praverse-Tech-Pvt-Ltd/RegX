"""A formulation component takes exactly the amounts the IID preview takes
(common/amount_limits.py), through the real components endpoint."""

import pytest

BASE = "/api/regx/v1"


@pytest.fixture
def version_url(api_client_a):
    product = api_client_a.post(
        f"{BASE}/formulations/products/",
        data={
            "product_code": "PROD-LIMITS-1",
            "proposed_product_name": "Name",
            "active_ingredient": "X",
        },
        format="json",
    ).json()
    version = api_client_a.post(
        f"{BASE}/formulations/products/{product['public_id']}/versions/",
        data={"total_dosage_unit_weight": "500", "total_dosage_unit_weight_unit": "mg"},
        format="json",
    ).json()
    return f"{BASE}/formulations/versions/{version['public_id']}/components/"


def _add(client, url, amount, unit):
    return client.post(
        url,
        data={
            "component_type": "inactive",
            "ingredient_name": "Synthetic Starch",
            "quantity_per_dosage_unit": amount,
            "quantity_unit": unit,
        },
        format="json",
    )


def _error(resp):
    return resp.json()["error"]["detail"]["quantity_per_dosage_unit"][0]


@pytest.mark.django_db
class TestComponentAmountLimits:
    def test_zero_is_still_refused(self, api_client_a, version_url):
        assert _add(api_client_a, version_url, "0", "mg").status_code == 400

    def test_one_million_is_the_upper_limit(self, api_client_a, version_url):
        assert _add(api_client_a, version_url, "1000000", "mg").status_code == 201
        resp = _add(api_client_a, version_url, "1000001", "mg")
        assert resp.status_code == 400
        assert "cannot be more than 1,000,000" in _error(resp)

    def test_a_percentage_cannot_exceed_100(self, api_client_a, version_url):
        assert _add(api_client_a, version_url, "100", "percent").status_code == 201
        resp = _add(api_client_a, version_url, "120", "percent")
        assert resp.status_code == 400
        assert _error(resp) == "A percentage cannot be more than 100."

    @pytest.mark.parametrize("unit", ["kg", "µg", "ug", "mcg"])
    def test_new_mass_spellings_are_accepted(self, api_client_a, version_url, unit):
        assert _add(api_client_a, version_url, "2", unit).status_code == 201
