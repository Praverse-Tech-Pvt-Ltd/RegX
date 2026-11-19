"""The one rule for "does this typed unit agree with this meaning?"
(fda_data.controlled_units.unit_meaning_problem), used by formulation components
and the IID preview. Exactly these percentage spellings are recognised; any other
text after the percent sign is refused, never read as plain percent.
"""

from __future__ import annotations

import pytest

from fda_data.controlled_units import PERCENTAGE_BASIS_SPELLINGS, parse_percentage_unit


class TestRecognisedSpellings:
    def test_the_documented_list_is_exactly_this(self):
        assert PERCENTAGE_BASIS_SPELLINGS == {
            "w/w": "w_w",
            "wt/wt": "w_w",
            "m/m": "w_w",
            "w/v": "w_v",
            "wt/vol": "w_v",
            "wt/v": "w_v",
            "m/v": "w_v",
            "v/v": "v_v",
            "vol/vol": "v_v",
        }

    @pytest.mark.parametrize(
        ("unit", "basis"),
        [
            ("%", None),
            ("percent", None),
            ("Percentage", None),
            ("pct", None),
            ("% w/w", "w_w"),
            ("%W/W", "w_w"),
            ("%(w/w)", "w_w"),
            ("% [wt/wt]", "w_w"),
            ("% m/m", "w_w"),
            ("% wt/vol", "w_v"),
            ("%(w/v)", "w_v"),
            ("% m/v", "w_v"),
            ("% wt/v", "w_v"),
            ("% v/v", "v_v"),
            ("% vol/vol", "v_v"),
            ("percent w/v", "w_v"),
        ],
    )
    def test_recognised(self, unit, basis):
        assert parse_percentage_unit(unit) == (True, basis, True)

    @pytest.mark.parametrize(
        "unit", ["% foo", "%w/x", "% weight per volume", "%(w)", "%w/w/v", "% mg/mL"]
    )
    def test_percentage_with_an_unrecognised_basis(self, unit):
        assert parse_percentage_unit(unit) == (True, None, False)

    @pytest.mark.parametrize("unit", ["mg", "mL", "w/v %", "", "furlongs"])
    def test_not_a_percentage(self, unit):
        assert parse_percentage_unit(unit)[0] is False
