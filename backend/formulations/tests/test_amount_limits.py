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

    @pytest.mark.parametrize(
        ("amount", "unit"), [("2000000", "µg"), ("2000", "mg"), ("1000000", "mg"), ("1000", "l")]
    )
    def test_accepted_up_to_one_million_in_the_base_unit(
        self, api_client_a, version_url, amount, unit
    ):
        assert _add(api_client_a, version_url, amount, unit).status_code == 201

    @pytest.mark.parametrize(
        ("amount", "unit", "message"),
        [
            ("1000001", "mg", "(you entered 1,000,001 mg)"),
            ("900000", "kg", "(you entered 900,000 kg = 900,000,000,000 mg)"),
            ("1000", "kg", "(you entered 1,000 kg = 1,000,000,000 mg)"),
        ],
    )
    def test_refused_above_one_million_mg(self, api_client_a, version_url, amount, unit, message):
        resp = _add(api_client_a, version_url, amount, unit)
        assert resp.status_code == 400
        assert "cannot be more than 1,000,000 mg" in _error(resp)
        assert message in _error(resp)

    def test_a_percentage_cannot_exceed_100(self, api_client_a, version_url):
        assert _add(api_client_a, version_url, "100", "percent").status_code == 201
        resp = _add(api_client_a, version_url, "120", "percent")
        assert resp.status_code == 400
        assert _error(resp) == "A percentage cannot be more than 100."

    # 0.5 kg = 500,000 mg, inside the limit (2 kg would be 2,000,000 mg and is refused).
    @pytest.mark.parametrize(
        ("amount", "unit"), [("0.5", "kg"), ("2", "µg"), ("2", "ug"), ("2", "mcg")]
    )
    def test_new_mass_spellings_are_accepted(self, api_client_a, version_url, amount, unit):
        assert _add(api_client_a, version_url, amount, unit).status_code == 201
