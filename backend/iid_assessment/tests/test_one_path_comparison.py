"""Controlled units, increment 3: one comparison path, and the like-for-like comparison.

IID records come from two fixtures copied byte-for-byte from the FDA file
iig_july_2026.zip (member IIR_OCOMM.csv, SHA-256 4f3a8e37...436d302): the
existing `iir_ocomm_sample.csv` and `iir_ocomm_units_sample.csv` (one real row
per potency unit string). Unit meanings come from the committed reviewed list
`fda_data/reference/controlled_units_v1.json`, taken through the real
load -> approve -> activate path; unit mappings through `propose_unit_mappings`
plus test approvals; records get their meaning through re-resolve.
"""

from __future__ import annotations

import csv
import io
import pathlib
from decimal import Decimal

import pytest

from fda_data import controlled_units as cu
from fda_data import lifecycle
from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDCalculabilityStatus,
    IIDIngredient,
    IIDPrecedentRecord,
    UnitMapping,
)
from fda_data.reresolve import reresolve
from iid_assessment import comparison as cmp
from iid_assessment.assess import run_preview
from iid_assessment.matching import MatchStatus, find_iid_candidates

FDA = pathlib.Path(__file__).resolve().parents[2] / "fda_data"
FIXTURES = FDA / "tests" / "fixtures" / "iid"


def _rows(name):
    raw = (FIXTURES / name).read_bytes().decode("latin-1")
    return list(csv.DictReader(io.StringIO(raw, newline="")))


ROWS = _rows("iir_ocomm_units_sample.csv") + [
    r for r in _rows("iir_ocomm_sample.csv") if r["POTENCY_UNIT"] in ("NA", "ADJ PH")
]


def _row(**match):
    return next(r for r in ROWS if all(r[k] == v for k, v in match.items()))


@pytest.fixture
def world(db, django_user_model):
    """Real rows in a not-yet-reviewed IID release; route/form mapped (except one
    deliberately unmapped form); the reviewed unit list in force; the 20 unit
    mappings proposed and test-approved; re-resolve run. Then the IID release is
    activated so the assessment layer can match against it."""
    vp = django_user_model.objects.create_user(email="vp@units3.test", password="x")
    units, _ = cu.load_snapshot(
        raw=(FDA / "reference" / "controlled_units_v1.json").read_bytes(),
        filename="controlled_units_v1.json",
        source_reference="test",
        actor=None,
    )
    units = lifecycle.activate(lifecycle.approve(lifecycle.submit_for_review(units, vp), vp), vp)

    iid = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="iig_july_2026.zip (fixture rows)",
        source_checksum_sha256="c" * 64,
        status=FDAReleaseStatus.REGISTERED,
    )
    records = {}
    for n, r in enumerate(ROWS, start=1):
        route, _ = ControlledRoute.objects.get_or_create(
            code=f"R-{r['ROUTE']}", defaults={"canonical_label": r["ROUTE"], "lifecycle": "active"}
        )
        form = None
        if r["DOSAGE_FORM"] != "SUSPENSION/ DROPS":  # DROPS stays unmapped (out of scope)
            form, _ = ControlledDosageForm.objects.get_or_create(
                code=f"F-{r['DOSAGE_FORM']}",
                defaults={"canonical_label": r["DOSAGE_FORM"], "lifecycle": "active"},
            )
        ingredient, _ = IIDIngredient.objects.get_or_create(
            normalized_name=r["INGREDIENT_NAME"], defaults={"canonical_name": r["INGREDIENT_NAME"]}
        )
        records[(r["INGREDIENT_NAME"], r["ROUTE"], r["DOSAGE_FORM"])] = (
            IIDPrecedentRecord.objects.create(
                release=iid,
                ingredient=ingredient,
                ingredient_name_raw=r["INGREDIENT_NAME"],
                route_raw=r["ROUTE"],
                route_normalized=route,
                dosage_form_raw=r["DOSAGE_FORM"],
                dosage_form_normalized=form,
                potency_amount=Decimal(r["POTENCY_AMOUNT"]) if r["POTENCY_AMOUNT"] else None,
                potency_amount_raw=r["POTENCY_AMOUNT"],
                potency_unit_raw=r["POTENCY_UNIT"],
                maximum_daily_exposure=Decimal(r["MAXIMUM_DAILY_EXPOSURE"])
                if r["MAXIMUM_DAILY_EXPOSURE"]
                else None,
                mde_amount_raw=r["MAXIMUM_DAILY_EXPOSURE"],
                mde_unit_raw=r["MAXIMUM_DAILY_EXPOSURE_UNIT"],
                source_row_locator=f"IIR_OCOMM.csv:{n}",
                raw_row_checksum=f"{n:064x}",
                calculability_status=IIDCalculabilityStatus.POTENCY_UNIT_MISSING,
            )
        )
    cu.propose_unit_mappings(iid, actor=None)
    UnitMapping.objects.filter(status="proposed").update(status="approved")  # test approvals
    reresolve(iid)
    for record in records.values():
        record.refresh_from_db()
    iid = lifecycle.activate(lifecycle.approve(lifecycle.submit_for_review(iid, vp), vp), vp)
    return {"iid": iid, "units": units, "records": records}


def _rec(world, name, route, form):
    return IIDPrecedentRecord.objects.select_related(
        "release", "potency_expression__numerator_unit", "potency_expression__denominator_unit"
    ).get(pk=world["records"][(name, route, form)].pk)


def mg(amount):
    return cmp.Quantity(
        Decimal(amount) if amount is not None else None, "mass", "per_dose_unit", "milligram"
    )


def per_ml(amount, ml="1", unit="milligram", family="mass"):
    return cmp.Quantity(Decimal(amount), family, "per_volume", unit, Decimal(ml), "millilitre")


def pct(amount, basis):
    return cmp.Quantity(Decimal(amount), "percentage", basis)


# --- Step 1: one comparison path ---------------------------------------------------


@pytest.mark.django_db
class TestTheOldPathDecidesNothing:
    def _legacy_only_record(self, world):
        """A record made 'calculable' the old way: an ACTIVE legacy unit on
        potency_unit_normalized and a stored CALCULABLE flag, but no meaning."""
        legacy = ControlledUnit.objects.create(
            code="milligram", symbol="MG", dimension="mass", active=True
        )
        base = world["records"][(".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE")]
        record = IIDPrecedentRecord.objects.get(pk=base.pk)
        record.potency_expression = None
        record.potency_unit_normalized = legacy
        record.calculability_status = IIDCalculabilityStatus.CALCULABLE
        record.save()
        return record

    def test_matching_reports_the_unit_missing_despite_the_legacy_link(self, world):
        record = self._legacy_only_record(world)
        result = find_iid_candidates(
            ingredient_public_id=str(record.ingredient.public_id),
            controlled_route_id=record.route_normalized_id,
            controlled_dosage_form_id=record.dosage_form_normalized_id,
            active_release_id=world["iid"].id,
        )
        assert result.status == MatchStatus.POTENCY_UNAVAILABLE
        assert result.reason_code == "IID_UNIT_MISSING"
        assert result.candidates[0].potency_unit == ""  # the legacy "milligram" is not used

    def test_comparison_refuses_despite_the_legacy_link(self, world):
        record = self._legacy_only_record(world)
        result = cmp.compare(mg("0.01"), IIDPrecedentRecord.objects.get(pk=record.pk))
        assert (result.comparable, result.reason_code) == (False, "IID_UNIT_MISSING")

    def test_preview_is_not_comparable_despite_the_legacy_link(self, world):
        record = self._legacy_only_record(world)
        preview = run_preview(
            ingredient_public_id=record.ingredient.public_id,
            route_code=record.route_normalized.code,
            dosage_form_code=record.dosage_form_normalized.code,
            active_release_public_id=world["iid"].public_id,
            proposed_quantity_per_unit=Decimal("0.01"),
            proposed_quantity_unit="milligram",
            total_dosage_unit_weight=Decimal("100"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert preview.decision_status == "NOT_COMPARABLE"
        assert preview.calculations["potency_comparison"]["reason_code"] == "IID_UNIT_MISSING"
        assert "percentage_of_iid_potency" not in preview.calculations

    def test_reresolve_recomputes_calculability_from_the_meaning(self, world):
        record = world["records"][("ANISE OIL", "ORAL", "ELIXIR")]
        assert record.potency_expression is not None
        assert record.calculability_status == IIDCalculabilityStatus.CALCULABLE
        mgmg = world["records"][("BENTONITE", "DENTAL", "POWDER, DENTIFRICE")]
        assert mgmg.potency_expression is None
        assert mgmg.calculability_status == IIDCalculabilityStatus.POTENCY_UNIT_MISSING


# --- Step 2: the comparison service --------------------------------------------------


@pytest.mark.django_db
class TestSameFamilyAndBasis:
    def test_per_dose_mass_at_or_below_and_above(self, world):
        record = _rec(world, ".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE")  # 0.07 mg
        below = cmp.compare(mg("0.07"), record, unit_list_release_public_id="u")
        above = cmp.compare(mg("0.08"), record)
        assert (below.result, below.proposed_value, below.iid_value, below.unit) == (
            "at_or_below",
            "0.07",
            "0.07",
            "mg per dose unit",
        )
        assert above.result == "above"
        assert below.label == "technically comparable (not regulatorily approved)"
        assert below.iid_source_row["potency_unit"] == "mg"
        assert below.iid_release_public_id == str(world["iid"].public_id)
        assert below.unit_list_release_public_id == "u"

    def test_a_different_mass_unit_converts_by_an_exact_factor(self, world):
        record = _rec(world, ".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE")
        result = cmp.compare(
            cmp.Quantity(Decimal("0.00007"), "mass", "per_dose_unit", "gram"), record
        )
        assert (result.result, result.proposed_value) == ("at_or_below", "0.07")
        assert "exact factor 1000" in result.conversion

    def test_per_volume_restated_per_the_iid_stated_volume(self, world):
        record = _rec(world, "ACESULFAME POTASSIUM", "ORAL", "POWDER, FOR SUSPENSION")  # 45 mg/5mL
        equal = cmp.compare(per_ml("9"), record)  # 9 mg/mL = 45 mg/5mL
        assert (equal.result, equal.proposed_value, equal.unit) == ("at_or_below", "45", "mg/5mL")
        assert "exact rational arithmetic" in equal.conversion
        assert cmp.compare(per_ml("9.2"), record).result == "above"

    def test_a_non_terminating_restatement_is_compared_exactly(self, world):
        record = _rec(world, ".ALPHA.-TOCOPHEROL", "ORAL", "SOLUTION")  # 1.05 mg/1mL
        result = cmp.compare(per_ml("3.15", ml="3"), record)  # = 1.05 per mL exactly
        assert (result.result, result.proposed_value, result.rounded_for_display) == (
            "at_or_below",
            "1.05",
            False,
        )
        third = cmp.compare(per_ml("1", ml="3"), record)  # 0.333... per mL
        assert third.rounded_for_display is True and third.result == "at_or_below"
        assert third.proposed_value == "0.333333"

    def test_volume_per_volume(self, world):
        record = _rec(world, "ANISE OIL", "ORAL", "ELIXIR")  # 0.15 mL/5mL
        result = cmp.compare(per_ml("0.03", unit="millilitre", family="volume"), record)
        assert (result.result, result.proposed_value, result.unit) == (
            "at_or_below",
            "0.15",
            "mL/5mL",
        )

    def test_percentages_of_the_same_basis(self, world):
        record = _rec(world, ".ALPHA.-TERPINEOL", "TOPICAL", "LOTION")  # 11 %w/w
        assert cmp.compare(pct("11", "w_w"), record).result == "at_or_below"
        assert cmp.compare(pct("11.01", "w_w"), record).result == "above"


@pytest.mark.django_db
class TestCannotCompare:
    @pytest.mark.parametrize(
        "proposed,key,code",
        [
            (pct("11", "w_v"), (".ALPHA.-TERPINEOL", "TOPICAL", "LOTION"), "DIFFERENT_BASIS"),
            (
                mg("1"),
                ("ACESULFAME POTASSIUM", "ORAL", "POWDER, FOR SUSPENSION"),
                "DIFFERENT_BASIS",
            ),
            (per_ml("1"), (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE"), "DIFFERENT_BASIS"),
            (
                cmp.Quantity(Decimal("1"), "volume", "per_dose_unit", "millilitre"),
                (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE"),
                "DIFFERENT_FAMILY",
            ),
            (
                pct("1", "w_w"),
                (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE"),
                "DIFFERENT_FAMILY",
            ),
            (mg("1"), ("BENTONITE", "DENTAL", "POWDER, DENTIFRICE"), "IID_UNIT_MISSING"),
            (mg("1"), (".ALPHA.-TOCOPHEROL", "ORAL", "CAPSULE"), "DAILY_EXPOSURE_ONLY_NEEDS_Q8"),
            (mg("1"), (".ALPHA.-TOCOPHEROL", "TOPICAL", "OINTMENT"), "NO_NUMERIC_LIMIT"),
            (
                mg("1"),
                ("CARBOXYMETHYLCELLULOSE SODIUM", "ORAL", "SUSPENSION/ DROPS"),
                "ROUTE_OR_FORM_UNMAPPED",
            ),
            (mg(None), (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE"), "PROPOSED_VALUE_MISSING"),
            (
                cmp.per_dose_unit_quantity(Decimal("1"), "tablet"),
                (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE"),
                "PROPOSED_UNIT_MISSING",
            ),
        ],
    )
    def test_reason_codes(self, world, proposed, key, code):
        result = cmp.compare(proposed, _rec(world, *key))
        assert (result.comparable, result.reason_code, result.result, result.label) == (
            False,
            code,
            None,
            None,
        )
        assert result.reason.startswith("cannot compare: ")
        assert result.iid_source_row["ingredient_name"] == key[0]

    def test_daily_exposure_only_names_the_per_day_rule(self, world):
        result = cmp.compare(mg("1"), _rec(world, ".ALPHA.-TOCOPHEROL", "ORAL", "CAPSULE"))
        assert "per-day rule (Q8)" in result.reason


def test_no_verdict_words_outside_the_required_label():
    text = (
        (pathlib.Path(cmp.__file__))
        .read_text(encoding="utf-8")
        .lower()
        .replace(cmp.LABEL.lower(), "")
    )
    for word in ("acceptable", "compliant", "approved", "safe "):
        assert word not in text, word


# --- Step 3: wired into matching and the assessment preview --------------------------


@pytest.mark.django_db
class TestWiredIntoTheAssessment:
    def _preview(self, world, key, qty, unit="milligram"):
        record = world["records"][key]
        return run_preview(
            ingredient_public_id=record.ingredient.public_id,
            route_code=record.route_normalized.code,
            dosage_form_code=record.dosage_form_normalized.code
            if record.dosage_form_normalized
            else "",
            active_release_public_id=world["iid"].public_id,
            proposed_quantity_per_unit=Decimal(qty),
            proposed_quantity_unit=unit,
            total_dosage_unit_weight=Decimal("100"),
            total_dosage_unit_weight_unit="milligram",
        )

    def test_per_dose_record_is_compared_and_labelled(self, world):
        preview = self._preview(world, (".ALPHA.-TOCOPHEROL", "BUCCAL", "FILM, SOLUBLE"), "0.08")
        comparison = preview.calculations["potency_comparison"]
        assert preview.match_status == MatchStatus.EXACT_MATCH
        assert preview.decision_status == "EXCEEDS_IID_PRECEDENT"
        assert (comparison["result"], comparison["label"]) == ("above", cmp.LABEL)
        assert comparison["unit_list_release_public_id"] == str(world["units"].public_id)
        assert preview.selected_record["potency_unit"] == "milligram"
        assert preview.selected_record["potency_meaning"] == "mg per dose unit"

    def test_per_volume_record_cannot_be_compared_with_a_per_dose_formulation(self, world):
        preview = self._preview(
            world, ("ACESULFAME POTASSIUM", "ORAL", "POWDER, FOR SUSPENSION"), "1"
        )
        assert preview.decision_status == "NOT_COMPARABLE"
        assert preview.calculations["potency_comparison"]["reason_code"] == "DIFFERENT_BASIS"
        # The calculation engines never see a per-dose unit for a per-volume limit.
        assert preview.selected_record["potency_unit"] == "mg/5mL"

    def test_daily_exposure_only_record(self, world):
        key = (".ALPHA.-TOCOPHEROL", "ORAL", "CAPSULE")
        record = world["records"][key]
        match = find_iid_candidates(
            ingredient_public_id=str(record.ingredient.public_id),
            controlled_route_id=record.route_normalized_id,
            controlled_dosage_form_id=record.dosage_form_normalized_id,
            active_release_id=world["iid"].id,
        )
        assert (match.status, match.reason_code) == (
            MatchStatus.POTENCY_UNAVAILABLE,
            "DAILY_EXPOSURE_ONLY_NEEDS_Q8",
        )
        preview = self._preview(world, key, "1")
        assert preview.decision_status == "NOT_COMPARABLE"
        assert "per-day rule (Q8)" in preview.decision_note
