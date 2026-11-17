"""The everyday unit spellings ("mg", "g", "mcg", "ml") work in every preview calculation.

Found in the real-stack demo run (2026-11-17, Round 2 case C01): a component of
63 mg in a 250 mg unit was compared correctly (the comparison normalises "mg"),
but its % w/w came back "Blocked: DATA_REQUIRED". The % w/w and daily-exposure
conversions were given the unit exactly as typed, and the converter only knows
"milligram". Every earlier test typed "milligram", so none saw it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from iid_assessment.assess import run_preview

from .test_one_path_comparison import world  # noqa: F401  (pytest fixture)

TOCOPHEROL_BUCCAL = (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE")  # 0.07 mg per dose


def _preview(world, qty, unit, total, total_unit):  # noqa: F811
    record = world["records"][TOCOPHEROL_BUCCAL]
    return run_preview(
        ingredient_public_id=record.ingredient.public_id,
        route_code=record.route_normalized.code,
        dosage_form_code=record.dosage_form_normalized.code,
        active_release_public_id=world["iid"].public_id,
        proposed_quantity_per_unit=Decimal(qty),
        proposed_quantity_unit=unit,
        total_dosage_unit_weight=Decimal(total),
        total_dosage_unit_weight_unit=total_unit,
        maximum_dosage_units_per_day=Decimal("4"),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("qty", "unit", "total", "total_unit"),
    [
        ("0.05", "milligram", "100", "milligram"),  # the long spellings (always worked)
        ("0.05", "mg", "100", "mg"),  # the short spellings users type
        ("0.05", "MG", "0.1", "g"),
        ("50", "mcg", "100", "mg"),
        ("0.00005", "g", "100000", "mcg"),
    ],
)
def test_percentage_w_w_accepts_short_unit_spellings(world, qty, unit, total, total_unit):  # noqa: F811
    preview = _preview(world, qty, unit, total, total_unit)
    pct = preview.calculations["percentage_w_w"]
    assert pct["status"] == "OK", pct
    assert Decimal(pct["value"]) == Decimal("0.05")
    # The comparison was always fine; keep it in view.
    comparison = preview.calculations["potency_comparison"]
    assert comparison["comparable"] is True
    assert comparison["result"] == "at_or_below"


@pytest.mark.django_db
def test_daily_exposure_is_computed_with_short_spellings(world):  # noqa: F811
    preview = _preview(world, "0.05", "mg", "100", "mg")
    daily = preview.calculations["daily_exposure"]
    assert daily["status"] == "OK", daily
    assert Decimal(daily["value"]) == Decimal("0.20")


@pytest.mark.django_db
def test_an_unknown_unit_is_still_refused(world):  # noqa: F811
    preview = _preview(world, "0.05", "tablets", "100", "mg")
    assert preview.calculations["potency_comparison"]["reason_code"] == "PROPOSED_UNIT_MISSING"
    assert preview.calculations["percentage_w_w"]["status"] != "OK"
