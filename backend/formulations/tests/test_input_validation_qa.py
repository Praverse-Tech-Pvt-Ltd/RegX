"""QA-02 and QA-03 (docs/QA_BROWSER_TEST_2026-11-18.md), through the real API.

* A component's unit must be one REGX can convert or read (mass, volume or a
  percentage). "furlongs" and "tablets" were saved before.
* A percentage in ANY spelling ("% w/w", "%w/v", "percent") is capped at 100,
  and needs its basis. "150 % w/w" was saved before.
* A per-volume amount (mg/5mL, % w/v, % v/v) is refused on a clearly solid
  product (TABLET, CAPSULE, ...). It was saved before.
* Maximum dosage units per day: greater than zero and at most 1,000. -5 was
  saved before.
* Old rows are never changed: a component with an unknown unit is flagged
  `unit_recognised: false`.
"""

from __future__ import annotations

import pathlib

import pytest

from fda_data import controlled_units as cu
from fda_data import lifecycle
from fda_data.models import QuantityExpression

BASE = "/api/regx/v1"
FDA = pathlib.Path(__file__).resolve().parents[2] / "fda_data"
pytestmark = pytest.mark.django_db


@pytest.fixture
def units_in_force(db, django_user_model):
    vp = django_user_model.objects.create_user(email="vp@qa02.test", password="x")
    release, _ = cu.load_snapshot(
        raw=(FDA / "reference" / "controlled_units_v1.json").read_bytes(),
        filename="controlled_units_v1.json",
        source_reference="test",
        actor=None,
    )
    lifecycle.activate(lifecycle.approve(lifecycle.submit_for_review(release, vp), vp), vp)


def _err(resp) -> dict:
    """Field errors from the API error envelope."""
    return resp.json()["error"]["detail"]


def _meaning(**kw) -> str:
    return str(QuantityExpression.objects.get(**kw).public_id)


def _product(client, code, dosage_form=""):
    return client.post(
        f"{BASE}/formulations/products/",
        data={
            "product_code": code,
            "proposed_product_name": "Name",
            "active_ingredient": "X",
            "dosage_form": dosage_form,
        },
        format="json",
    ).json()


def _version(client, product, **extra):
    return client.post(
        f"{BASE}/formulations/products/{product['public_id']}/versions/",
        data={
            "total_dosage_unit_weight": "250",
            "total_dosage_unit_weight_unit": "mg",
            **extra,
        },
        format="json",
    )


def _components_url(client, code, dosage_form=""):
    version = _version(client, _product(client, code, dosage_form)).json()
    return f"{BASE}/formulations/versions/{version['public_id']}/components/"


def _add(client, url, amount, unit, meaning=None):
    data = {
        "component_type": "inactive",
        "ingredient_name": "Synthetic Starch",
        "quantity_per_dosage_unit": amount,
        "quantity_unit": unit,
    }
    if meaning:
        data["quantity_expression_public_id"] = meaning
    return client.post(url, data=data, format="json")


class TestUnitMustBeRecognised:
    @pytest.mark.parametrize("unit", ["furlongs", "tablets", "mg/5mL", "", "mgs"])
    def test_unknown_units_are_refused(self, api_client_a, unit):
        url = _components_url(api_client_a, "QA02-U")
        resp = _add(api_client_a, url, "5", unit)
        assert resp.status_code == 400
        if unit:
            assert "Choose a unit from the list" in str(_err(resp)["quantity_unit"])

    @pytest.mark.parametrize("unit", ["mg", "g", "kg", "µg", "mcg", "mL", "L", "milligram"])
    def test_mass_and_volume_units_are_accepted(self, api_client_a, unit):
        url = _components_url(api_client_a, "QA02-OK")
        assert _add(api_client_a, url, "0.5", unit).status_code == 201


class TestPercentageInAnySpelling:
    @pytest.mark.parametrize("unit", ["% w/w", "%w/w", "% w/v", "%v/v", "percent", "%", "Percent"])
    def test_over_100_is_refused(self, api_client_a, unit):
        url = _components_url(api_client_a, "QA02-P")
        resp = _add(api_client_a, url, "150", unit)
        assert resp.status_code == 400
        assert _err(resp)["quantity_per_dosage_unit"] == ["A percentage cannot be more than 100."]

    def test_a_percentage_needs_its_basis(self, api_client_a, units_in_force):
        url = _components_url(api_client_a, "QA02-B")
        resp = _add(api_client_a, url, "15", "% w/w")
        assert resp.status_code == 400
        assert "needs its basis" in str(_err(resp)["quantity_expression_public_id"])

    def test_with_its_basis_it_is_saved_as_percent(self, api_client_a, units_in_force):
        url = _components_url(api_client_a, "QA02-W")
        resp = _add(api_client_a, url, "15", "% w/w", _meaning(family="percentage", basis="w_w"))
        assert resp.status_code == 201, resp.json()
        assert resp.json()["quantity_unit"] == "percent"
        assert resp.json()["unit_recognised"] is True


class TestPerVolumeOnASolid:
    def _mg_per_5ml(self):
        return _meaning(
            family="mass",
            basis="per_volume",
            denominator_amount="5.000000",
            numerator_unit__code__iexact="mg",
        )

    @pytest.mark.parametrize("form", ["TABLET", "TABLET, FILM COATED", "CAPSULE", "Lozenge"])
    def test_refused_on_a_solid(self, api_client_a, units_in_force, form):
        url = _components_url(api_client_a, f"QA02-S-{form[:6]}", form)
        resp = _add(api_client_a, url, "100", "mg", self._mg_per_5ml())
        assert resp.status_code == 400
        assert "a solid" in str(_err(resp)["quantity_expression_public_id"])

    def test_w_v_percentage_refused_on_a_capsule(self, api_client_a, units_in_force):
        url = _components_url(api_client_a, "QA02-WV", "CAPSULE")
        resp = _add(api_client_a, url, "5", "percent", _meaning(family="percentage", basis="w_v"))
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "form", ["SUSPENSION", "POWDER, FOR SUSPENSION", "TABLET, FOR SUSPENSION", ""]
    )
    def test_accepted_when_not_clearly_solid(self, api_client_a, units_in_force, form):
        url = _components_url(api_client_a, f"QA02-L-{form[:8]}", form)
        resp = _add(api_client_a, url, "100", "mg", self._mg_per_5ml())
        assert resp.status_code == 201, resp.json()


class TestMaximumDosageUnitsPerDay:
    @pytest.mark.parametrize("value", ["-5", "0", "1001", "10000"])
    def test_out_of_range_is_refused(self, api_client_a, value):
        resp = _version(
            api_client_a,
            _product(api_client_a, f"QA03-{value}"),
            maximum_dosage_units_per_day=value,
        )
        assert resp.status_code == 400
        assert "maximum_dosage_units_per_day" in _err(resp)

    @pytest.mark.parametrize("value", ["1", "6", "1000", None])
    def test_in_range_or_absent_is_accepted(self, api_client_a, value):
        resp = _version(
            api_client_a,
            _product(api_client_a, f"QA03-OK-{value}"),
            maximum_dosage_units_per_day=value,
        )
        assert resp.status_code == 201, resp.json()

    def test_dosing_regimen_has_the_same_upper_limit(self, api_client_a):
        version = _version(api_client_a, _product(api_client_a, "QA03-REG")).json()
        url = f"{BASE}/formulations/versions/{version['public_id']}/dosing-regimens/"
        data = {"units_per_administration": "1", "administrations_per_day": "3"}
        assert (
            api_client_a.post(
                url, data={**data, "maximum_units_per_day": "1001"}, format="json"
            ).status_code
            == 400
        )
        assert (
            api_client_a.post(
                url, data={**data, "maximum_units_per_day": "6"}, format="json"
            ).status_code
            == 201
        )


class TestOldRowsAreFlaggedNotChanged:
    def test_an_unknown_unit_saved_before_is_flagged(self, api_client_a):
        from formulations.models import FormulationComponent, FormulationVersion

        url = _components_url(api_client_a, "QA02-OLD")
        version_id = url.rstrip("/").split("/")[-2]
        version = FormulationVersion.objects.get(public_id=version_id)
        FormulationComponent.objects.create(  # as it could be saved before QA-02
            formulation_version=version,
            component_type="inactive",
            ingredient_name="Old Row",
            quantity_per_dosage_unit="150",
            quantity_unit="furlongs",
        )
        rows = api_client_a.get(url).json()
        assert [(r["quantity_unit"], r["unit_recognised"]) for r in rows] == [("furlongs", False)]
        assert (
            FormulationComponent.objects.get(ingredient_name="Old Row").quantity_unit == "furlongs"
        )


class TestCreateButtonFlag:
    def test_list_says_whether_this_user_may_create(self, api_client_a):
        assert api_client_a.get(f"{BASE}/formulations/products/").json()["can_create"] is True
