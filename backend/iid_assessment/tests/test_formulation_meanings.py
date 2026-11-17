"""Controlled units, increment 4: formulation-side meanings (design section 3E).

A formulation amount can now state what it means: per dose unit, per stated
volume (e.g. mg/5mL) or a percentage (%w/w, %w/v, %v/v), using the meanings the
reviewed unit list puts in force. It is then compared with an IID limit of the
same family and basis -- and nothing else. Real IID rows, the real unit list and
the real load -> approve -> activate path come from the increment-3 `world`
fixture (see test_one_path_comparison).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fda_data.models import ControlledUnit, QuantityExpression
from iid_assessment import comparison as cmp
from iid_assessment.assess import run_preview

from .test_one_path_comparison import world  # noqa: F401  (pytest fixture)

LABEL = "technically comparable (not regulatorily approved)"


def _meaning(**kw):
    """An existing (in-force) meaning from the reviewed list."""
    return QuantityExpression.objects.select_related("numerator_unit", "denominator_unit").get(**kw)


def mg_per(volume):
    return _meaning(
        family="mass",
        basis="per_volume",
        numerator_unit__code="mg",
        denominator_amount=Decimal(volume),
        denominator_unit__code="ml",
    )


def ml_per(volume):
    return _meaning(
        family="volume",
        basis="per_volume",
        numerator_unit__code="ml",
        denominator_amount=Decimal(volume),
        denominator_unit__code="ml",
    )


def percent(basis):
    return _meaning(family="percentage", basis=basis)


def mg_per_dose():
    return _meaning(family="mass", basis="per_dose_unit", numerator_unit__code="mg")


def _preview(world, key, qty, unit, expression):  # noqa: F811
    record = world["records"][key]
    return run_preview(
        ingredient_public_id=record.ingredient.public_id,
        route_code=record.route_normalized.code,
        dosage_form_code=record.dosage_form_normalized.code,
        active_release_public_id=world["iid"].public_id,
        proposed_quantity_per_unit=Decimal(qty),
        proposed_quantity_unit=unit,
        total_dosage_unit_weight=Decimal("100"),
        total_dosage_unit_weight_unit="milligram",
        proposed_quantity_expression=expression,
    )


ACESULFAME = ("ACESULFAME POTASSIUM", "ORAL", "POWDER, FOR SUSPENSION")  # 45 mg/5ml
TERPINEOL = (".ALPHA.-TERPINEOL", "TOPICAL", "LOTION")  # 11 %w/w
ANISE = ("ANISE OIL", "ORAL", "ELIXIR")  # 0.15 ml/5ml
TOCOPHEROL_BUCCAL = (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE")  # 0.07 mg
TOCOPHEROL_IV = (".ALPHA.-TOCOPHEROL, DL-", "INTRAVENOUS", "SOLUTION, CONCENTRATE")  # 0.08 %w/v


@pytest.mark.django_db
class TestPerVolume:
    def test_same_stated_volume_is_compared_at_or_below(self, world):  # noqa: F811
        preview = _preview(world, ACESULFAME, "40", "mg", mg_per("5"))
        c = preview.calculations["potency_comparison"]
        assert c["comparable"] is True
        assert c["result"] == "at_or_below"
        assert (c["proposed_value"], c["iid_value"], c["unit"]) == ("40", "45", "mg/5mL")
        assert c["conversion"] == "none needed"
        assert c["label"] == LABEL
        assert c["proposed_meaning"] == "mg/5mL"

    def test_other_stated_volume_is_restated_exactly(self, world):  # noqa: F811
        # 10 mg/1 mL = 50 mg/5 mL, above the IID 45 mg/5 mL.
        preview = _preview(world, ACESULFAME, "10", "mg", mg_per("1"))
        c = preview.calculations["potency_comparison"]
        assert c["comparable"] is True
        assert (c["proposed_value"], c["result"]) == ("50", "above")
        assert "restated per 5" in c["conversion"]
        assert preview.decision_status == "EXCEEDS_IID_PRECEDENT"

    def test_volume_per_volume(self, world):  # noqa: F811
        preview = _preview(world, ANISE, "0.1", "ml", ml_per("5"))
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["result"], c["unit"]) == (True, "at_or_below", "mL/5mL")

    def test_per_volume_against_a_per_dose_limit_is_refused(self, world):  # noqa: F811
        preview = _preview(world, TOCOPHEROL_BUCCAL, "1", "mg", mg_per("5"))
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["reason_code"], c["label"]) == (False, "DIFFERENT_BASIS", None)
        assert preview.decision_status == "NOT_COMPARABLE"


@pytest.mark.django_db
class TestPercentage:
    def test_same_percentage_basis_is_compared(self, world):  # noqa: F811
        preview = _preview(world, TERPINEOL, "5", "percent", percent("w_w"))
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["result"], c["unit"]) == (True, "at_or_below", "%w/w")
        assert c["label"] == LABEL

    def test_above_a_percentage_limit(self, world):  # noqa: F811
        preview = _preview(world, TOCOPHEROL_IV, "0.1", "percent", percent("w_v"))
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["result"]) == (True, "above")

    def test_other_percentage_basis_is_refused(self, world):  # noqa: F811
        # %w/v vs %w/w needs a density: never converted.
        preview = _preview(world, TERPINEOL, "5", "percent", percent("w_v"))
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["reason_code"]) == (False, "DIFFERENT_BASIS")

    def test_percentage_against_a_mass_limit_is_refused(self, world):  # noqa: F811
        preview = _preview(world, TOCOPHEROL_BUCCAL, "1", "percent", percent("w_w"))
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["reason_code"]) == (False, "DIFFERENT_FAMILY")


@pytest.mark.django_db
class TestOnlyMeaningsInForce:
    def test_a_meaning_the_active_list_does_not_carry_is_never_used(self, world):  # noqa: F811
        # "mg per 3 mL" is not on the reviewed list (no IID string states it).
        unlisted = QuantityExpression.objects.create(
            family="mass",
            basis="per_volume",
            numerator_unit=ControlledUnit.objects.get(code="mg"),
            denominator_amount=Decimal("3"),
            denominator_unit=ControlledUnit.objects.get(code="ml"),
        )
        preview = _preview(world, ACESULFAME, "40", "mg", unlisted)
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["reason_code"]) == (False, "PROPOSED_UNIT_MISSING")
        assert c["proposed_meaning"] is None

    def test_stated_quantity_refuses_an_unlisted_meaning(self, world):  # noqa: F811
        q = cmp.stated_quantity(Decimal("1"), None)
        assert (q.family, q.basis) == ("", "")


@pytest.mark.django_db
class TestPerDoseOnlyCalculations:
    def test_not_computed_for_an_amount_per_volume(self, world):  # noqa: F811
        preview = _preview(world, ACESULFAME, "40", "mg", mg_per("5"))
        for name in ("percentage_w_w", "daily_exposure"):
            calc = preview.calculations[name]
            assert calc["status"] == "NOT_COMPARABLE"
            assert calc["reason_code"] == "NOT_PER_DOSE_UNIT"
            assert calc["value"] is None
        assert "percentage_of_iid_mde" not in preview.calculations

    def test_not_computed_for_a_percentage(self, world):  # noqa: F811
        preview = _preview(world, TERPINEOL, "5", "percent", percent("w_w"))
        assert preview.calculations["percentage_w_w"]["reason_code"] == "NOT_PER_DOSE_UNIT"

    def test_still_computed_for_a_stated_per_dose_meaning(self, world):  # noqa: F811
        preview = _preview(world, TOCOPHEROL_BUCCAL, "0.05", "mg", mg_per_dose())
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["result"], c["proposed_meaning"]) == (
            True,
            "at_or_below",
            "mg per dose unit",
        )
        assert preview.calculations["percentage_w_w"]["status"] == "OK"

    def test_no_meaning_keeps_the_old_per_dose_behaviour(self, world):  # noqa: F811
        preview = _preview(world, ACESULFAME, "40", "milligram", None)
        c = preview.calculations["potency_comparison"]
        assert (c["comparable"], c["reason_code"]) == (False, "DIFFERENT_BASIS")
        assert c["proposed_meaning"] == "mg per dose unit"
        assert preview.calculations["percentage_w_w"]["status"] == "OK"


@pytest.mark.django_db
class TestGovernedSnapshotUsesTheComponentMeaning:
    def test_preview_arguments_carry_the_components_meaning(self, world):  # noqa: F811
        from types import SimpleNamespace

        from iid_assessment.services import _preview_arguments

        meaning = mg_per("5")
        product = SimpleNamespace(route="Oral", dosage_form="Tablet")
        version = SimpleNamespace(
            product=product,
            total_dosage_unit_weight=Decimal("100"),
            total_dosage_unit_weight_unit="milligram",
        )
        component = SimpleNamespace(
            resolved_ingredient_public_id=None,
            ingredient_name="X",
            resolved_unii="",
            quantity_per_dosage_unit=Decimal("40"),
            quantity_unit="mg",
            quantity_expression=meaning,
        )
        args, _, _ = _preview_arguments(version, component, world["iid"], Decimal("4"))
        assert args["proposed_quantity_expression"] is meaning

    def test_snapshot_request_cannot_supply_a_meaning(self):
        from iid_assessment.serializers import SnapshotRequestSerializer

        assert "proposed_quantity_expression_public_id" not in SnapshotRequestSerializer().fields
