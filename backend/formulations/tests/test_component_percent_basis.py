# ruff: noqa: F811  (units_in_force is a pytest fixture imported by name)
"""A formulation component's typed percentage basis must agree with its meaning.

Found on the real stack (2026-11-19, after F-1): a component accepted unit
"%w/v" with the meaning %w/w and stored it as "percent" / %w/w; the typed basis
was dropped without a word. "% wt/vol", "% m/v" and "% foo" were read as plain
percent too. The rule is now one shared function,
fda_data.controlled_units.unit_meaning_problem, used by the component and the
IID preview alike.
"""

from __future__ import annotations

import pytest

from .test_input_validation_qa import (  # noqa: F401
    _add,
    _components_url,
    _err,
    _meaning,
    units_in_force,
)

pytestmark = pytest.mark.django_db


def w_w():
    return _meaning(family="percentage", basis="w_w")


def w_v():
    return _meaning(family="percentage", basis="w_v")


def v_v():
    return _meaning(family="percentage", basis="v_v")


class TestBasisDisagreesWithMeaning:
    """Each of these was saved on the old code as plain percent with the meaning."""

    @pytest.mark.parametrize("unit", ["%w/v", "% wt/vol", "% m/v", "%(w/v)", "% v/v", "%vol/vol"])
    def test_another_basis_with_a_w_w_meaning_is_refused(self, api_client_a, units_in_force, unit):
        url = _components_url(api_client_a, "PB-X")
        resp = _add(api_client_a, url, "10", unit, w_w())
        assert resp.status_code == 400, resp.json()
        msg = _err(resp)["quantity_expression_public_id"][0]
        assert "but the meaning chosen is %w/w" in msg

    @pytest.mark.parametrize("unit", ["% foo", "%w/x", "% weight per volume", "%(w)"])
    def test_an_unrecognised_basis_is_refused_not_read_as_percent(
        self,
        api_client_a,
        units_in_force,
        unit,
    ):
        url = _components_url(api_client_a, "PB-U")
        resp = _add(api_client_a, url, "10", unit, w_w())
        assert resp.status_code == 400, resp.json()
        assert "basis REGX does not recognise" in _err(resp)["quantity_unit"][0]

    def test_an_unrecognised_basis_is_refused_without_a_meaning_too(
        self,
        api_client_a,
        units_in_force,
    ):
        url = _components_url(api_client_a, "PB-N")
        resp = _add(api_client_a, url, "10", "% foo")
        assert resp.status_code == 400, resp.json()
        assert "basis REGX does not recognise" in _err(resp)["quantity_unit"][0]


class TestAgreeingSpellingsAreSaved:
    """A legitimate request still succeeds, stored as "percent" with the meaning."""

    @pytest.mark.parametrize(
        ("unit", "meaning"),
        [
            ("percent", "w_w"),
            ("%", "v_v"),
            ("%w/w", "w_w"),
            ("% W/W", "w_w"),
            ("%(w/w)", "w_w"),
            ("% wt/wt", "w_w"),
            ("% m/m", "w_w"),
            ("% w/v", "w_v"),
            ("% wt/vol", "w_v"),
            ("% wt/v", "w_v"),
            ("% m/v", "w_v"),
            ("%[w/v]", "w_v"),
            ("% v/v", "v_v"),
            ("% vol/vol", "v_v"),
            ("percent w/w", "w_w"),
        ],
    )
    def test_saved(self, api_client_a, units_in_force, unit, meaning):
        url = _components_url(api_client_a, "PB-OK")
        resp = _add(api_client_a, url, "10", unit, {"w_w": w_w, "w_v": w_v, "v_v": v_v}[meaning]())
        assert resp.status_code == 201, resp.json()
        assert resp.json()["quantity_unit"] == "percent"
        assert resp.json()["quantity_meaning"] == "%" + meaning.replace("_", "/")
