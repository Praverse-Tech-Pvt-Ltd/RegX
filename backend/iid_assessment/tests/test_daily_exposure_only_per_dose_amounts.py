"""Daily exposure is calculated only for a real per-dose-unit mass or volume.

Report-only finding of 2026-11-19 (PROJECT_OVERVIEW §11 item 37): the IID preview
showed a daily exposure for a percentage or an unrecognised unit, as if it were an
amount per dosage unit: 0.3 "%w/v" x 4 units/day = "1.2"; 2 "tablets" x 4 = "8".
The comparison was already refused; only the daily exposure was wrong. It is now
not calculated, with a short reason, and nothing else changes.

IID record (conftest `active_iid_setup`): 50 mg per dosage unit.
"""

from decimal import Decimal

import pytest

from .test_amount_limits_preview import _preview

REASON_CODE = "NOT_A_PER_DOSE_MASS_OR_VOLUME"


def _daily(resp):
    assert resp.status_code == 200, resp.json()
    return resp.json()["calculations"]["daily_exposure"]


@pytest.mark.django_db
class TestNotCalculated:
    @pytest.mark.parametrize(
        ("amount", "unit", "says"),
        [
            ("0.3", "%w/v", "is a percentage"),
            ("0.3", "% w/v", "is a percentage"),
            ("0.3", "percent", "is a percentage"),
            ("2", "tablets", "not a unit REGX can read"),
            ("2", "furlongs", "not a unit REGX can read"),
        ],
    )
    def test_no_value_and_a_short_reason(
        self, api_client_doer, active_iid_setup, amount, unit, says
    ):
        daily = _daily(_preview(api_client_doer, active_iid_setup, amount, unit))  # 4 units/day
        assert daily["status"] != "OK"
        assert daily["value"] is None
        assert daily["reason_code"] == REASON_CODE
        assert says in daily["reason"]
        assert "mg, g, µg, mL or L" in daily["reason"]


@pytest.mark.django_db
class TestStillCalculated:
    @pytest.mark.parametrize(
        ("amount", "unit", "per_day"),
        [
            ("10", "mg", "40"),
            ("0.01", "g", "0.04"),
            ("500", "µg", "2000"),
            ("0.5", "mL", "2"),
            ("10", "milligram", "40"),
        ],
    )
    def test_mass_and_volume_per_dose_unit(
        self, api_client_doer, active_iid_setup, amount, unit, per_day
    ):
        daily = _daily(_preview(api_client_doer, active_iid_setup, amount, unit))
        assert daily["status"] == "OK"
        assert Decimal(daily["value"]) == Decimal(per_day)

    def test_without_units_per_day_it_still_asks_for_data(self, api_client_doer, active_iid_setup):
        daily = _daily(
            _preview(
                api_client_doer, active_iid_setup, "10", "mg", maximum_dosage_units_per_day=None
            )
        )
        assert daily["status"] == "DATA_REQUIRED"
