"""Calculation release gate: 15 cases whose expected answers were worked by hand.

The hand working for every case is in `docs/CALC_RELEASE_GATE.md` (same case numbers). The data is
synthetic: three made-up excipients in one made-up active IID release, ORAL / TABLET only, plus a
route (BUCCAL) and a dosage form (CAPSULE) that exist but have no record for these excipients.

What these tests prove: the IID preview (`iid_assessment.assess.run_preview`) gives the answers our
own rules say it should, including at the exact limit, just above it, across mass units, and where it
must refuse. What they do NOT prove: that the rules are regulatorily correct. That needs the
regulatory reviewer to sign off the expected answers in the doc.

Records (potency = per-unit IID value, MDE = maximum daily exposure):
  A  SYN EXCIPIENT A   potency 50 mg per dose unit, no MDE     (the common real-data shape, F-3)
  B  SYN EXCIPIENT B   no potency, MDE 200 mg per day           (the other real-data shape, F-3)
  C  SYN EXCIPIENT C   potency 50 mg per dose unit, MDE 200 mg  (both: not in the July 2026 file)
  D  SYN EXCIPIENT D   in the ingredient list, no record at all (not in the IID)
Every case uses a total dosage-unit weight of 250 mg.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fda_data.tests._meanings import per_day, per_dose_unit, put_in_force
from iid_assessment.assess import run_preview

WEIGHT_MG = Decimal("250")


@pytest.fixture
def gate(db):
    from fda_data.models import (
        ControlledDosageForm,
        ControlledRoute,
        ControlledUnit,
        FDADataSourceRelease,
        FDAReleaseStatus,
        IIDCalculabilityStatus,
        IIDIngredient,
        IIDPrecedentRecord,
        QuantityExpression,
    )

    oral = ControlledRoute.objects.create(
        code="gate-oral", canonical_label="ORAL", lifecycle="active"
    )
    buccal = ControlledRoute.objects.create(
        code="gate-buccal", canonical_label="BUCCAL", lifecycle="active"
    )
    tablet = ControlledDosageForm.objects.create(
        code="gate-tablet", canonical_label="TABLET", lifecycle="active"
    )
    capsule = ControlledDosageForm.objects.create(
        code="gate-capsule", canonical_label="CAPSULE", lifecycle="active"
    )
    mg = ControlledUnit.objects.create(code="milligram", symbol="MG", dimension="mass", active=True)
    ml = ControlledUnit.objects.create(
        code="millilitre", symbol="ML", dimension="volume", active=True
    )
    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID (synthetic, calculation release gate)",
        official_source_reference="synthetic",
        source_checksum_sha256="c" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )

    def ingredient(name):
        return IIDIngredient.objects.create(canonical_name=name, normalized_name=name)

    def record(ing, n, *, potency=None, mde=None):
        return IIDPrecedentRecord.objects.create(
            release=release,
            ingredient=ing,
            ingredient_name_raw=ing.normalized_name,
            route_raw="ORAL",
            route_normalized=oral,
            dosage_form_raw="TABLET",
            dosage_form_normalized=tablet,
            potency_amount=potency,
            potency_unit_raw="MG" if potency is not None else "",
            potency_expression=per_dose_unit(mg) if potency is not None else None,
            maximum_daily_exposure=mde,
            mde_unit_raw="MG" if mde is not None else "",
            mde_expression=per_day(mg) if mde is not None else None,
            raw_row_checksum=f"{n}" * 64,
            calculability_status=(
                IIDCalculabilityStatus.CALCULABLE
                if potency is not None
                else IIDCalculabilityStatus.POTENCY_MISSING
            ),
        )

    a, b, c, d = (ingredient(f"SYN EXCIPIENT {x}") for x in "ABCD")
    record(a, 1, potency=Decimal("50"))
    record(b, 2, mde=Decimal("200"))
    record(c, 3, potency=Decimal("50"), mde=Decimal("200"))

    # The two stated meanings a proposed amount can carry in the refusal cases, put in force
    # as after review (otherwise the comparison refuses with PROPOSED_UNIT_MISSING instead).
    pct_ww = QuantityExpression.objects.create(family="percentage", basis="w_w")
    mg_per_5ml = QuantityExpression.objects.create(
        family="mass",
        basis="per_volume",
        numerator_unit=mg,
        denominator_amount=Decimal("5"),
        denominator_unit=ml,
    )
    put_in_force(pct_ww, "%W/W")
    put_in_force(mg_per_5ml, "MG/5ML")

    return {
        "release": release,
        "ingredients": {"A": a, "B": b, "C": c, "D": d},
        "routes": {"ORAL": oral, "BUCCAL": buccal},
        "forms": {"TABLET": tablet, "CAPSULE": capsule},
        "meanings": {"%w/w": pct_ww, "mg/5mL": mg_per_5ml},
    }


def preview(
    gate,
    excipient,
    qty,
    unit="mg",
    *,
    route="ORAL",
    form="TABLET",
    per_day_units=None,
    meaning=None,
):
    return run_preview(
        ingredient_public_id=gate["ingredients"][excipient].public_id,
        route_code=gate["routes"][route].code,
        dosage_form_code=gate["forms"][form].code,
        active_release_public_id=gate["release"].public_id,
        proposed_quantity_per_unit=Decimal(qty),
        proposed_quantity_unit=unit,
        total_dosage_unit_weight=WEIGHT_MG,
        total_dosage_unit_weight_unit="milligram",
        maximum_dosage_units_per_day=Decimal(per_day_units) if per_day_units else None,
        proposed_quantity_expression=gate["meanings"][meaning] if meaning else None,
    )


def value(p, key):
    """A calculation's value as a Decimal (None when the calculation did not produce one)."""
    calc = p.calculations.get(key)
    if not calc or calc.get("value") is None:
        return None
    return Decimal(str(calc["value"]))


def comparison(p):
    return p.calculations.get("potency_comparison", {})


@pytest.mark.django_db
class TestCalcReleaseGate:
    # ---- at the limit, just above, and the same amounts in other mass units (record A) ----

    def test_01_exactly_at_the_per_unit_limit(self, gate):
        p = preview(gate, "A", "50")
        assert p.match_status == "EXACT_MATCH"
        assert comparison(p)["result"] == "at_or_below"
        assert value(p, "percentage_of_iid_potency") == Decimal("100")
        assert value(p, "difference_from_iid_potency") == Decimal("0")
        assert value(p, "percentage_w_w") == Decimal("20")
        # within the per-unit value, but A has no MDE: never a pass (F-3)
        assert p.decision_status == "REVIEW_REQUIRED"

    def test_02_just_above_the_per_unit_limit(self, gate):
        p = preview(gate, "A", "50.001")
        assert comparison(p)["result"] == "above"
        assert value(p, "difference_from_iid_potency") == Decimal("-0.001")
        assert p.decision_status == "EXCEEDS_IID_PRECEDENT"

    def test_03_grams_exactly_at_the_limit(self, gate):
        p = preview(gate, "A", "0.05", "g")
        assert comparison(p)["result"] == "at_or_below"
        assert Decimal(comparison(p)["proposed_value"]) == Decimal("50")
        assert value(p, "percentage_w_w") == Decimal("20")
        assert p.decision_status == "REVIEW_REQUIRED"

    def test_04_grams_just_above_the_limit(self, gate):
        p = preview(gate, "A", "0.050001", "g")
        assert Decimal(comparison(p)["proposed_value"]) == Decimal("50.001")
        assert comparison(p)["result"] == "above"
        assert p.decision_status == "EXCEEDS_IID_PRECEDENT"

    def test_05_micrograms_exactly_at_the_limit(self, gate):
        p = preview(gate, "A", "50000", "µg")
        assert Decimal(comparison(p)["proposed_value"]) == Decimal("50")
        assert comparison(p)["result"] == "at_or_below"
        assert p.decision_status == "REVIEW_REQUIRED"

    def test_06_micrograms_just_above_the_limit(self, gate):
        p = preview(gate, "A", "50001", "mcg")
        assert Decimal(comparison(p)["proposed_value"]) == Decimal("50.001")
        assert comparison(p)["result"] == "above"
        assert p.decision_status == "EXCEEDS_IID_PRECEDENT"

    # ---- amounts that must not be compared with a per-unit mass limit ----

    def test_07_percent_w_w_is_a_different_family(self, gate):
        p = preview(gate, "A", "20", "%", meaning="%w/w")
        assert comparison(p)["reason_code"] == "DIFFERENT_FAMILY"
        assert p.decision_status == "NOT_COMPARABLE"
        assert value(p, "percentage_of_iid_potency") is None

    def test_08_mg_per_ml_on_a_solid_is_a_different_basis(self, gate):
        p = preview(gate, "A", "10", "mg", meaning="mg/5mL")
        assert comparison(p)["reason_code"] == "DIFFERENT_BASIS"
        assert p.decision_status == "NOT_COMPARABLE"
        assert value(p, "percentage_of_iid_potency") is None

    # ---- no record to compare against ----

    def test_09_excipient_not_in_the_iid(self, gate):
        p = preview(gate, "D", "10")
        assert p.match_status == "NO_MATCHING_IID_PRECEDENT"
        assert p.decision_status == "NO_MATCH"

    def test_10_wrong_route(self, gate):
        p = preview(gate, "A", "10", route="BUCCAL")
        assert p.match_status == "NO_MATCHING_IID_PRECEDENT"
        assert p.decision_status == "NO_MATCH"

    def test_11_wrong_dosage_form(self, gate):
        p = preview(gate, "A", "10", form="CAPSULE")
        assert p.match_status == "NO_MATCHING_IID_PRECEDENT"
        assert p.decision_status == "NO_MATCH"

    # ---- the daily maximum (records B and C) ----

    def test_12_daily_maximum_only_is_not_compared(self, gate):
        p = preview(gate, "B", "10", per_day_units="1")
        assert p.match_status == "POTENCY_UNAVAILABLE"
        assert comparison(p)["reason_code"] == "DAILY_EXPOSURE_ONLY_NEEDS_Q8"
        assert p.decision_status == "NOT_COMPARABLE"
        assert value(p, "percentage_w_w") == Decimal("4")
        assert value(p, "daily_exposure") == Decimal("10")
        assert value(p, "percentage_of_iid_mde") is None

    def test_13_exactly_at_the_daily_maximum(self, gate):
        p = preview(gate, "C", "50", per_day_units="4")
        assert value(p, "daily_exposure") == Decimal("200")
        assert value(p, "percentage_of_iid_mde") == Decimal("100")
        assert value(p, "difference_from_iid_mde") == Decimal("0")
        assert p.decision_status == "PASS_WITH_IID_PRECEDENT"

    def test_14_above_the_daily_maximum(self, gate):
        p = preview(gate, "C", "50", per_day_units="5")
        assert value(p, "daily_exposure") == Decimal("250")
        assert value(p, "percentage_of_iid_mde") == Decimal("125")
        assert value(p, "difference_from_iid_mde") == Decimal("-50")
        assert p.decision_status == "EXCEEDS_IID_PRECEDENT"

    def test_15_within_the_per_unit_limit_with_no_daily_maximum(self, gate):
        p = preview(gate, "A", "25", per_day_units="2")
        assert comparison(p)["result"] == "at_or_below"
        assert value(p, "percentage_of_iid_potency") == Decimal("50")
        assert value(p, "difference_from_iid_potency") == Decimal("25")
        assert value(p, "percentage_of_iid_mde") is None
        assert p.decision_status == "REVIEW_REQUIRED"
        assert "maximum daily exposure precedent is unavailable" in p.decision_note
