"""QA-07 (QA_CODEX_REPORT.md): maximum dosage units/day accepted 0.5.

The agreed range is 1 to 1,000. The shared rule
(iid_assessment.amount_limits.dosage_units_per_day_problem) refused only zero
and below, so 0.5 saved a draft version and could feed a daily-exposure
calculation. The rule is shared by formulation versions, dosing regimens and the
IID preview; all three are checked here through the real API.
"""

from __future__ import annotations

import pytest

from .test_input_validation_qa import BASE, _err, _product, _version

pytestmark = pytest.mark.django_db

MIN_MESSAGE = "The maximum number of dosage units per day must be at least 1."


class TestFormulationVersion:
    @pytest.mark.parametrize("value", ["0.5", "0.999"])
    def test_below_one_is_refused(self, api_client_a, value):
        resp = _version(
            api_client_a,
            _product(api_client_a, f"QA07-{value}"),
            maximum_dosage_units_per_day=value,
        )
        assert resp.status_code == 400, resp.json()
        assert _err(resp)["maximum_dosage_units_per_day"] == [MIN_MESSAGE]

    @pytest.mark.parametrize("value", ["1", "1000"])
    def test_the_ends_of_the_range_are_accepted(self, api_client_a, value):
        resp = _version(
            api_client_a,
            _product(api_client_a, f"QA07-OK-{value}"),
            maximum_dosage_units_per_day=value,
        )
        assert resp.status_code == 201, resp.json()

    def test_just_above_1000_is_refused(self, api_client_a):
        resp = _version(
            api_client_a, _product(api_client_a, "QA07-HI"), maximum_dosage_units_per_day="1000.01"
        )
        assert resp.status_code == 400
        assert "cannot be more than 1,000" in _err(resp)["maximum_dosage_units_per_day"][0]


class TestDosingRegimen:
    @pytest.mark.parametrize(
        ("value", "status"),
        [("0.5", 400), ("0.999", 400), ("1", 201), ("1000", 201), ("1000.01", 400)],
    )
    def test_same_range(self, api_client_a, value, status):
        version = _version(api_client_a, _product(api_client_a, f"QA07-REG-{value}")).json()
        resp = api_client_a.post(
            f"{BASE}/formulations/versions/{version['public_id']}/dosing-regimens/",
            data={
                "units_per_administration": "1",
                "administrations_per_day": "1",
                "maximum_units_per_day": value,
            },
            format="json",
        )
        assert resp.status_code == status, resp.json()
        if value in ("0.5", "0.999"):
            assert _err(resp)["maximum_units_per_day"] == [MIN_MESSAGE]
