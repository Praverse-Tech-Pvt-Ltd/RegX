"""QA-07: the IID preview applies the same 1 to 1,000 range to maximum dosage units/day.

The IID record (conftest `active_iid_setup`) is 50 mg per dosage unit.
"""

import pytest

from .test_amount_limits_preview import _preview

MIN_MESSAGE = "The maximum number of dosage units per day must be at least 1."


@pytest.mark.django_db
class TestPreviewUnitsPerDayRange:
    @pytest.mark.parametrize("value", ["0.5", "0.999"])
    def test_below_one_is_refused(self, api_client_doer, active_iid_setup, value):
        resp = _preview(
            api_client_doer, active_iid_setup, "10", "mg", maximum_dosage_units_per_day=value
        )
        assert resp.status_code == 400, resp.json()
        assert resp.json()["error"]["detail"]["maximum_dosage_units_per_day"] == [MIN_MESSAGE]

    @pytest.mark.parametrize("value", ["1", "1000"])
    def test_the_ends_of_the_range_are_accepted(self, api_client_doer, active_iid_setup, value):
        resp = _preview(
            api_client_doer, active_iid_setup, "10", "mg", maximum_dosage_units_per_day=value
        )
        assert resp.status_code == 200, resp.json()

    def test_just_above_1000_is_refused(self, api_client_doer, active_iid_setup):
        resp = _preview(
            api_client_doer, active_iid_setup, "10", "mg", maximum_dosage_units_per_day="1000.01"
        )
        assert resp.status_code == 400
