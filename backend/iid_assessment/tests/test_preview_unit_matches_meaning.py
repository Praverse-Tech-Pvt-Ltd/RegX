"""F-1 (validation report 2026-11-19): the typed unit must agree with the chosen meaning.

Found on the real stack: with the meaning "mg per dose unit", the preview read a
typed "0.03 g" as 0.03 mg and showed "at or below" against an IID limit of
0.03 mg (the real amount, 30 mg, is 1000 times that). "20 mcg" was read as
20 mg. The amount was read in the meaning's own unit and the typed unit was
dropped without a word. A formulation component already refuses such a pair
(fda_data.controlled_units.stated_amount_problem); the preview now applies the
same rule, through the real endpoint.

IID rows (fixture `world`, real IID July 2026 rows):
  .ALPHA.-TOCOPHEROL, BUCCAL, FILM, SOLUBLE   0.07 mg per dose unit
  ACESULFAME POTASSIUM, ORAL, POWDER, FOR SUSPENSION   45 mg/5ml
  ANISE OIL, ORAL, ELIXIR   0.15 ml/5ml
  .ALPHA.-TERPINEOL, TOPICAL, LOTION   11 %w/w
"""

from decimal import Decimal

import pytest

from .test_formulation_meanings import (
    ACESULFAME,
    ANISE,
    TERPINEOL,
    TOCOPHEROL_BUCCAL,
    mg_per,
    mg_per_dose,
    ml_per,
    percent,
)
from .test_one_path_comparison import world  # noqa: F401  (pytest fixture)

BASE = "/api/regx/v1"


def _preview(client, world, key, qty, unit, expression=None):  # noqa: F811
    record = world["records"][key]
    body = {
        "ingredient_public_id": str(record.ingredient.public_id),
        "route_code": record.route_normalized.code,
        "dosage_form_code": record.dosage_form_normalized.code,
        "active_release_public_id": str(world["iid"].public_id),
        "proposed_quantity_per_unit": qty,
        "proposed_quantity_unit": unit,
        "total_dosage_unit_weight": "100",
        "total_dosage_unit_weight_unit": "mg",
    }
    if expression is not None:
        body["proposed_quantity_expression_public_id"] = str(expression.public_id)
    return client.post(f"{BASE}/iid-assessments/preview/", data=body, format="json")


def _comparison(resp):
    assert resp.status_code == 200, resp.json()
    return resp.json()["calculations"]["potency_comparison"]


def _unit_error(resp):
    assert resp.status_code == 400, resp.json()
    return resp.json()["error"]["detail"]["proposed_quantity_unit"][0]


@pytest.mark.django_db
class TestTypedUnitDisagreesWithMeaning:
    """Refused, with the unit the meaning needs. Each of these was compared on the
    old code with the wrong amount."""

    def test_grams_with_mg_per_dose_is_refused_not_read_as_mg(self, api_client_doer, world):  # noqa: F811
        # Old code: 0.03 read as 0.03 mg -> "at or below" 0.07 mg. Really 30 mg.
        resp = _preview(api_client_doer, world, TOCOPHEROL_BUCCAL, "0.03", "g", mg_per_dose())
        assert _unit_error(resp) == (
            "the amount must be entered in 'mg', the unit this meaning states (got 'g')"
        )

    def test_micrograms_with_mg_per_dose_is_refused(self, api_client_doer, world):  # noqa: F811
        # Old code: 20 mcg read as 20 mg -> "above". Really 0.02 mg, at or below.
        resp = _preview(api_client_doer, world, TOCOPHEROL_BUCCAL, "20", "mcg", mg_per_dose())
        assert "must be entered in 'mg'" in _unit_error(resp)

    def test_grams_with_mg_per_volume_is_refused(self, api_client_doer, world):  # noqa: F811
        resp = _preview(api_client_doer, world, ACESULFAME, "0.009", "g", mg_per("1"))
        assert "must be entered in 'mg'" in _unit_error(resp)

    def test_mass_unit_with_a_percentage_meaning_is_refused(self, api_client_doer, world):  # noqa: F811
        # Old code: "10 mg" with %w/w was compared as 10 %w/w.
        resp = _preview(api_client_doer, world, TERPINEOL, "10", "mg", percent("w_w"))
        assert "percentage meaning needs the amount entered with unit 'percent'" in _unit_error(
            resp
        )

    def test_percentage_unit_with_another_basis_is_refused(self, api_client_doer, world):  # noqa: F811
        # Old code: "%w/v" typed with the %w/w meaning was compared as %w/w.
        resp = _preview(api_client_doer, world, TERPINEOL, "10", "%w/v", percent("w_w"))
        assert _unit_error(resp) == (
            "the unit says %w/v but the meaning chosen is %w/w; choose the meaning that "
            "matches, or type the unit as 'percent'"
        )


@pytest.mark.django_db
class TestAgreeingPairsStillCompare:
    """A legitimate request still succeeds and gives the right answer."""

    @pytest.mark.parametrize("unit", ["mg", "milligram", "MG"])
    def test_mg_spellings_with_mg_per_dose(self, api_client_doer, world, unit):  # noqa: F811
        c = _comparison(
            _preview(api_client_doer, world, TOCOPHEROL_BUCCAL, "0.05", unit, mg_per_dose())
        )
        assert (c["result"], Decimal(c["proposed_value"])) == ("at_or_below", Decimal("0.05"))

    def test_mg_per_volume_restated(self, api_client_doer, world):  # noqa: F811
        c = _comparison(_preview(api_client_doer, world, ACESULFAME, "9", "mg", mg_per("1")))
        assert (c["result"], Decimal(c["proposed_value"])) == ("at_or_below", Decimal("45"))

    @pytest.mark.parametrize("unit", ["mL", "ml", "millilitre"])
    def test_ml_per_volume(self, api_client_doer, world, unit):  # noqa: F811
        c = _comparison(_preview(api_client_doer, world, ANISE, "0.15", unit, ml_per("5")))
        assert (c["result"], Decimal(c["proposed_value"])) == ("at_or_below", Decimal("0.15"))

    @pytest.mark.parametrize("unit", ["percent", "%", "%w/w", "% w/w", "% W/W"])
    def test_percentage_spellings_with_the_same_basis(self, api_client_doer, world, unit):  # noqa: F811
        c = _comparison(_preview(api_client_doer, world, TERPINEOL, "10", unit, percent("w_w")))
        assert (c["result"], Decimal(c["proposed_value"])) == ("at_or_below", Decimal("10"))

    def test_no_meaning_still_converts_the_typed_unit(self, api_client_doer, world):  # noqa: F811
        # Unchanged: without a meaning the typed unit is used and converted.
        c = _comparison(_preview(api_client_doer, world, TOCOPHEROL_BUCCAL, "0.03", "g"))
        assert (c["result"], Decimal(c["proposed_value"])) == ("above", Decimal("30"))
