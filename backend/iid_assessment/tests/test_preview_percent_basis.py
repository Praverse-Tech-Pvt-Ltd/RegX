"""The IID preview reads a percentage basis spelling with the shared rule
(fda_data.controlled_units.unit_meaning_problem), the same as a formulation component.

After F-1 (#138) the preview still read "% wt/vol", "% m/v" and "% foo" with a
%w/w meaning as plain percent, because only "w/w", "w/v" and "v/v" were looked
for. Now every spelling is either recognised or refused.

IID rows (fixture `world`): .ALPHA.-TERPINEOL, TOPICAL, LOTION 11 %w/w;
.ALPHA.-TOCOPHEROL, DL-, INTRAVENOUS, SOLUTION, CONCENTRATE 0.08 %w/v.
"""

from decimal import Decimal

import pytest

from .test_formulation_meanings import TERPINEOL, TOCOPHEROL_IV, percent
from .test_one_path_comparison import world  # noqa: F401  (pytest fixture)
from .test_preview_unit_matches_meaning import _comparison, _preview, _unit_error


@pytest.mark.django_db
class TestPercentBasisSpellingsInThePreview:
    @pytest.mark.parametrize("unit", ["% wt/vol", "% m/v", "% vol/vol"])
    def test_another_basis_in_another_spelling_is_refused(self, api_client_doer, world, unit):  # noqa: F811
        resp = _preview(api_client_doer, world, TERPINEOL, "10", unit, percent("w_w"))
        assert "but the meaning chosen is %w/w" in _unit_error(resp)

    @pytest.mark.parametrize("unit", ["% foo", "%w/x", "%(w)"])
    def test_an_unrecognised_basis_is_refused(self, api_client_doer, world, unit):  # noqa: F811
        resp = _preview(api_client_doer, world, TERPINEOL, "10", unit, percent("w_w"))
        assert "basis REGX does not recognise" in _unit_error(resp)

    @pytest.mark.parametrize("unit", ["%(w/w)", "% wt/wt", "% m/m"])
    def test_same_basis_in_another_spelling_is_compared(self, api_client_doer, world, unit):  # noqa: F811
        c = _comparison(_preview(api_client_doer, world, TERPINEOL, "10", unit, percent("w_w")))
        assert (c["result"], Decimal(c["proposed_value"])) == ("at_or_below", Decimal("10"))

    @pytest.mark.parametrize("unit", ["% wt/vol", "% m/v", "%(w/v)"])
    def test_w_v_spellings_with_a_w_v_meaning(self, api_client_doer, world, unit):  # noqa: F811
        c = _comparison(
            _preview(api_client_doer, world, TOCOPHEROL_IV, "0.09", unit, percent("w_v"))
        )
        assert (c["result"], Decimal(c["proposed_value"])) == ("above", Decimal("0.09"))

    def test_an_unrecognised_basis_is_refused_without_a_meaning_too(self, api_client_doer, world):  # noqa: F811
        # Old code: "% foo" with no meaning was accepted (and only "cannot compare" later).
        resp = _preview(api_client_doer, world, TERPINEOL, "10", "% foo")
        assert "basis REGX does not recognise" in _unit_error(resp)
