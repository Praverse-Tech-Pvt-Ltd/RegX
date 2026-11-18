"""Amount limits, through the real IID preview endpoint.

From the real-stack demo run (2026-11-17, Round 2): the preview compared a zero
amount while a formulation component refused it; a 14-digit amount was accepted
and gave a % w/w of 39,999,999,999,999.6 %; "kg" and "µg" were refused as unknown
units. The preview and the component now share one rule (common/amount_limits.py).

The IID record (conftest `active_iid_setup`) is 50 mg per dosage unit.
"""

import pytest

BASE = "/api/regx/v1"


def _preview(client, setup, amount, unit, **extra):
    body = {
        "ingredient_public_id": str(setup["ingredient"].public_id),
        "route_code": "oral",
        "dosage_form_code": "tablet",
        "active_release_public_id": str(setup["release"].public_id),
        "proposed_quantity_per_unit": amount,
        "proposed_quantity_unit": unit,
        "total_dosage_unit_weight": "500",
        "total_dosage_unit_weight_unit": "mg",
        "maximum_dosage_units_per_day": "4",
    }
    body.update(extra)
    return client.post(f"{BASE}/iid-assessments/preview/", data=body, format="json")


def _field_error(resp):
    return resp.json()["error"]["detail"]["proposed_quantity_per_unit"][0]


@pytest.mark.django_db
class TestAmountLimits:
    @pytest.mark.parametrize("amount", ["0", "-1"])
    def test_zero_or_negative_is_refused_like_a_component(
        self, api_client_doer, active_iid_setup, amount
    ):
        resp = _preview(api_client_doer, active_iid_setup, amount, "mg")
        assert resp.status_code == 400
        assert _field_error(resp) == "The amount must be greater than zero."

    def test_the_smallest_positive_amount_is_accepted(self, api_client_doer, active_iid_setup):
        assert _preview(api_client_doer, active_iid_setup, "0.000001", "mg").status_code == 200

    def test_one_million_is_the_upper_limit(self, api_client_doer, active_iid_setup):
        ok = _preview(api_client_doer, active_iid_setup, "1000000", "mg")
        assert ok.status_code == 200
        assert ok.json()["calculations"]["potency_comparison"]["result"] == "above"
        too_big = _preview(api_client_doer, active_iid_setup, "1000000.000001", "mg")
        assert too_big.status_code == 400
        assert "cannot be more than 1,000,000" in _field_error(too_big)
        assert "239,360" in _field_error(too_big)

    def test_the_old_fourteen_digit_case_is_refused(self, api_client_doer, active_iid_setup):
        resp = _preview(api_client_doer, active_iid_setup, "99999999999999", "mg")
        assert resp.status_code == 400

    def test_a_percentage_cannot_exceed_100(self, api_client_doer, active_iid_setup):
        assert _preview(api_client_doer, active_iid_setup, "100", "percent").status_code == 200
        resp = _preview(api_client_doer, active_iid_setup, "100.5", "percent")
        assert resp.status_code == 400
        assert _field_error(resp) == "A percentage cannot be more than 100."

    def test_101_is_fine_when_it_is_not_a_percentage(self, api_client_doer, active_iid_setup):
        assert _preview(api_client_doer, active_iid_setup, "101", "mg").status_code == 200
