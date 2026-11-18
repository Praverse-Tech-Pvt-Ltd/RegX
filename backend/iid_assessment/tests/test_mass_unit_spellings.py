"""Mass unit spellings ("kg", "µg"), through the real IID preview endpoint.

From the real-stack demo run (2026-11-17, Round 2): the preview compared a zero
amount while a formulation component refused it; a 14-digit amount was accepted
and gave a % w/w of 39,999,999,999,999.6 %; "kg" and "µg" were refused as unknown
units. The preview and the component now share one rule (common/amount_limits.py).

The IID record (conftest `active_iid_setup`) is 50 mg per dosage unit.
"""

from decimal import Decimal

import pytest

from iid_assessment.comparison import conversion_key
from iid_assessment.unit_conversion import dimension_of

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


@pytest.mark.django_db
class TestMassUnitSpellings:
    @pytest.mark.parametrize(
        ("amount", "unit", "expected_mg", "result"),
        [
            ("0.00004", "kg", "40", "at_or_below"),  # 40 mg
            ("0.00006", "KG", "60", "above"),
            ("60000", "µg", "60", "above"),  # micro sign
            ("40000", "μg", "40", "at_or_below"),  # Greek mu
            ("30000", "ug", "30", "at_or_below"),
            ("30000", "mcg", "30", "at_or_below"),
        ],
    )
    def test_kg_and_microgram_spellings_convert_exactly_to_mg(
        self, api_client_doer, active_iid_setup, amount, unit, expected_mg, result
    ):
        resp = _preview(api_client_doer, active_iid_setup, amount, unit)
        assert resp.status_code == 200, resp.json()
        comparison = resp.json()["calculations"]["potency_comparison"]
        assert comparison["comparable"] is True
        assert Decimal(comparison["proposed_value"]) == Decimal(expected_mg)
        assert comparison["result"] == result
        assert "exact factor" in comparison["conversion"]

    def test_kg_feeds_the_percentage_w_w_too(self, api_client_doer, active_iid_setup):
        resp = _preview(
            api_client_doer, active_iid_setup, "0.00005", "kg"
        )  # 50 mg in a 500 mg unit
        pct = resp.json()["calculations"]["percentage_w_w"]
        assert pct["status"] == "OK"
        assert Decimal(pct["value"]) == Decimal("10")

    def test_the_new_spellings_are_mass_only(self):
        for unit in ("kg", "µg", "μg", "ug", "mcg"):
            assert dimension_of(conversion_key(unit)) == "mass", unit

    def test_a_still_unknown_unit_is_refused(self, api_client_doer, active_iid_setup):
        resp = _preview(api_client_doer, active_iid_setup, "1", "tonnes")
        assert resp.status_code == 200
        assert (
            resp.json()["calculations"]["potency_comparison"]["reason_code"]
            == "PROPOSED_UNIT_MISSING"
        )
