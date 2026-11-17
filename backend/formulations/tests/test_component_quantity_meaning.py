"""Controlled units, increment 4: a formulation component can state what its
amount means, using only meanings the reviewed unit list puts in force."""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from fda_data import controlled_units as cu
from fda_data import lifecycle
from fda_data.models import ControlledUnit, QuantityExpression
from formulations.serializers import FormulationComponentSerializer

FDA = pathlib.Path(__file__).resolve().parents[2] / "fda_data"


@pytest.fixture
def units_in_force(db, django_user_model):
    vp = django_user_model.objects.create_user(email="vp@units4.test", password="x")
    release, _ = cu.load_snapshot(
        raw=(FDA / "reference" / "controlled_units_v1.json").read_bytes(),
        filename="controlled_units_v1.json",
        source_reference="test",
        actor=None,
    )
    lifecycle.activate(lifecycle.approve(lifecycle.submit_for_review(release, vp), vp), vp)


def _meaning(**kw):
    return QuantityExpression.objects.get(**kw)


def _data(**overrides):
    data = {
        "component_type": "inactive",
        "ingredient_name": "Synthetic Excipient",
        "quantity_per_dosage_unit": "40",
        "quantity_unit": "mg",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestStatingAMeaning:
    def test_no_meaning_is_per_dosage_unit_as_before(self, units_in_force):
        s = FormulationComponentSerializer(data=_data(quantity_unit="milligram"))
        assert s.is_valid(), s.errors
        assert s.validated_data.get("quantity_expression") is None

    def test_per_volume_meaning_in_its_numerator_unit(self, units_in_force):
        meaning = _meaning(family="mass", basis="per_volume", denominator_amount=Decimal("5"))
        s = FormulationComponentSerializer(
            data=_data(quantity_expression_public_id=str(meaning.public_id))
        )
        assert s.is_valid(), s.errors
        assert s.validated_data["quantity_expression"] == meaning

    def test_unit_spelled_out_is_accepted(self, units_in_force):
        meaning = _meaning(family="mass", basis="per_volume", denominator_amount=Decimal("5"))
        s = FormulationComponentSerializer(
            data=_data(
                quantity_unit="milligram", quantity_expression_public_id=str(meaning.public_id)
            )
        )
        assert s.is_valid(), s.errors

    def test_amount_in_another_unit_is_refused(self, units_in_force):
        meaning = _meaning(family="mass", basis="per_volume", denominator_amount=Decimal("5"))
        s = FormulationComponentSerializer(
            data=_data(quantity_unit="gram", quantity_expression_public_id=str(meaning.public_id))
        )
        assert not s.is_valid()
        assert "must be entered in 'mg'" in str(s.errors["quantity_expression_public_id"][0])

    def test_percentage_needs_unit_percent(self, units_in_force):
        meaning = _meaning(family="percentage", basis="w_w")
        bad = FormulationComponentSerializer(
            data=_data(quantity_unit="mg", quantity_expression_public_id=str(meaning.public_id))
        )
        assert not bad.is_valid()
        good = FormulationComponentSerializer(
            data=_data(
                quantity_unit="percent",
                quantity_per_dosage_unit="2",
                quantity_expression_public_id=str(meaning.public_id),
            )
        )
        assert good.is_valid(), good.errors

    def test_per_day_meaning_is_refused(self, units_in_force):
        mg = ControlledUnit.objects.get(code="mg")
        per_day, _ = QuantityExpression.objects.get_or_create(
            family="mass", basis="per_day", numerator_unit=mg
        )
        # Even if it were listed, a per-day meaning needs the Q8 rule.
        assert cu.stated_amount_problem(per_day, "mg").startswith("a per-day meaning")

    def test_meaning_not_in_force_is_refused(self, units_in_force):
        unlisted = QuantityExpression.objects.create(
            family="mass",
            basis="per_volume",
            numerator_unit=ControlledUnit.objects.get(code="mg"),
            denominator_amount=Decimal("3"),
            denominator_unit=ControlledUnit.objects.get(code="ml"),
        )
        s = FormulationComponentSerializer(
            data=_data(quantity_expression_public_id=str(unlisted.public_id))
        )
        assert not s.is_valid()
        assert "active controlled-units list" in str(s.errors["quantity_expression_public_id"][0])

    def test_nothing_is_in_force_without_an_active_unit_list(self, db):
        mg, _ = ControlledUnit.objects.get_or_create(
            code="mg", defaults={"symbol": "mg", "dimension": "mass", "active": False}
        )
        meaning, _ = QuantityExpression.objects.get_or_create(
            family="mass", basis="per_dose_unit", numerator_unit=mg
        )
        s = FormulationComponentSerializer(
            data=_data(quantity_expression_public_id=str(meaning.public_id))
        )
        assert not s.is_valid()


@pytest.mark.django_db
class TestShowingTheMeaning:
    def test_representation_shows_label_and_public_id(self, units_in_force):
        from types import SimpleNamespace

        meaning = _meaning(family="mass", basis="per_volume", denominator_amount=Decimal("5"))
        s = FormulationComponentSerializer()
        stated = SimpleNamespace(quantity_expression=meaning, quantity_unit="mg")
        plain = SimpleNamespace(quantity_expression=None, quantity_unit="milligram")
        assert s.get_quantity_meaning(stated) == "mg/5mL"
        assert s.get_quantity_meaning(plain) == "milligram per dosage unit"

    def test_partial_update_without_the_field_keeps_the_meaning(self, units_in_force):
        meaning = _meaning(family="mass", basis="per_volume", denominator_amount=Decimal("5"))
        s = FormulationComponentSerializer(partial=True, data={"grade": "NF"})
        assert s.is_valid(), s.errors
        assert "quantity_expression" not in s.validated_data
        s2 = FormulationComponentSerializer(
            partial=True, data={"quantity_expression_public_id": None}
        )
        assert s2.is_valid(), s2.errors
        assert s2.validated_data["quantity_expression"] is None
        assert meaning is not None
