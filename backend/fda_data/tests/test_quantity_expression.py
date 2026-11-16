"""Controlled units, increment 1: the QuantityExpression model and its migration.

Fixture `fixtures/iid/iir_ocomm_units_sample.csv` is copied byte-for-byte from the
FDA file iig_july_2026.zip, member IIR_OCOMM.csv (SHA-256 4f3a8e37...436d302): the
header plus the first row for each potency unit string in the file (the 20
that state an exact meaning, and `mg/mg`) and the first maximum-daily-exposure row. Public
FDA data. File line numbers: 2, 3, 5, 6, 19, 72, 172, 485, 566, 587, 648, 1062,
1387, 1453, 1498, 1527, 1660, 2186, 2643, 3397, 4280, 8275.

Increment 1 only proves the model can state each real string's meaning exactly,
refuses meanings that do not exist, and migrates forward and back. It contains no
parser (increment 2) and no comparison (increment 3); there is no conversion
between families or bases anywhere.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError

from fda_data.models import (
    ControlledUnit,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDPrecedentRecord,
    QuantityBasis,
    QuantityExpression,
    QuantityFamily,
    UnitMapping,
)

FIXTURE = Path(__file__).parent / "fixtures" / "iid" / "iir_ocomm_units_sample.csv"
ROWS = list(csv.DictReader(io.StringIO(FIXTURE.read_bytes().decode("latin-1"), newline="")))

M, V, P = QuantityFamily.MASS, QuantityFamily.VOLUME, QuantityFamily.PERCENTAGE
B = QuantityBasis

#: The meaning of each real unit string (docs/CONTROLLED_UNITS_DESIGN.md section 2):
#: (family, basis, numerator unit code, denominator amount, denominator unit code).
#: Hand-written on purpose: increment 1 has no parser.
MEANING = {
    "mg": (M, B.PER_DOSE_UNIT, "mg", None, None),
    "ml": (V, B.PER_DOSE_UNIT, "ml", None, None),
    "%w/w": (P, B.W_W, None, None, None),
    "%w/v": (P, B.W_V, None, None, None),
    "%v/v": (P, B.V_V, None, None, None),
    "ml/1ml": (V, B.PER_VOLUME, "ml", "1", "ml"),
    "ml/5ml": (V, B.PER_VOLUME, "ml", "5", "ml"),
    "ml/15ml": (V, B.PER_VOLUME, "ml", "15", "ml"),
    **{
        f"mg/{n}ml": (M, B.PER_VOLUME, "mg", n, "ml")
        for n in ("0.1", "0.2", "1", "2.5", "5", "10", "15", "20", "100", "120", "140", "1000")
    },
}
MDE_MEANING = (M, B.PER_DAY, "mg", None, None)


@pytest.fixture
def units(db):
    """Test units only: the real unit list is loaded as proposals in increment 2."""
    return {
        "mg": ControlledUnit.objects.create(code="mg", symbol="mg", dimension="mass"),
        "ml": ControlledUnit.objects.create(code="ml", symbol="mL", dimension="volume"),
    }


def _expression(units, family, basis, num, den_amount, den_unit, save=True):
    expr = QuantityExpression(
        family=family,
        basis=basis,
        numerator_unit=units[num] if num else None,
        denominator_amount=Decimal(den_amount) if den_amount else None,
        denominator_unit=units[den_unit] if den_unit else None,
    )
    expr.full_clean()
    if save:
        expr.save()
    return expr


def test_fixture_is_the_expected_real_sample():
    potency_units = sorted(r["POTENCY_UNIT"] for r in ROWS if r["POTENCY_AMOUNT"])
    assert len(ROWS) == 22
    assert set(potency_units) == set(MEANING) | {"mg/mg"}
    assert len(potency_units) == 21  # every potency string once
    mde = [r for r in ROWS if r["MAXIMUM_DAILY_EXPOSURE"]]
    assert [(r["INGREDIENT_NAME"], r["MAXIMUM_DAILY_EXPOSURE_UNIT"]) for r in mde] == [
        (".ALPHA.-TOCOPHEROL", "mg")
    ]


@pytest.mark.django_db
class TestEveryRealUnitStringHasAnExactMeaning:
    @pytest.mark.parametrize(
        "row", [r for r in ROWS if r["POTENCY_UNIT"] in MEANING], ids=lambda r: r["POTENCY_UNIT"]
    )
    def test_potency_unit(self, units, row):
        family, basis, num, den_amount, den_unit = MEANING[row["POTENCY_UNIT"]]
        expr = _expression(units, family, basis, num, den_amount, den_unit)
        assert (expr.family, expr.basis) == (family, basis)
        if basis == B.PER_VOLUME:
            assert expr.denominator_amount == Decimal(den_amount)
        if basis == B.PER_VOLUME or family == P:
            assert str(expr) == row["POTENCY_UNIT"].replace("ml", "mL")

    def test_maximum_daily_exposure(self, units):
        expr = _expression(units, *MDE_MEANING)
        assert (expr.family, expr.basis) == (M, B.PER_DAY)
        assert expr.denominator_amount is None

    def test_mg_per_mg_has_no_meaning_the_model_can_state(self, units):
        """`mg/mg` (16 records): per mg of what? Mass is not a basis; refused."""
        with pytest.raises(ValidationError, match="not a volume"):
            _expression(units, M, B.PER_VOLUME, "mg", "1", "mg", save=False)
        with pytest.raises(ValidationError, match="not allowed"):
            _expression(units, M, B.W_W, "mg", None, None, save=False)

    def test_one_row_per_meaning(self, units):
        _expression(units, *MEANING["mg/5ml"])
        with pytest.raises(IntegrityError), transaction.atomic():
            QuantityExpression.objects.create(
                family=M,
                basis=B.PER_VOLUME,
                numerator_unit=units["mg"],
                denominator_amount=Decimal("5"),
                denominator_unit=units["ml"],
            )
        _expression(units, *MEANING["%w/v"])
        with pytest.raises(IntegrityError), transaction.atomic():
            QuantityExpression.objects.create(family=P, basis=B.W_V)  # nulls are not distinct

    def test_mg_per_5ml_and_mg_per_1ml_are_different_rows(self, units):
        """Same family and basis (comparable later, after exact division), different meaning."""
        a = _expression(units, *MEANING["mg/5ml"])
        b = _expression(units, *MEANING["mg/1ml"])
        assert a.pk != b.pk and (a.family, a.basis) == (b.family, b.basis)


@pytest.mark.django_db
class TestImpossibleMeaningsAreRefused:
    @pytest.mark.parametrize(
        "family,basis",
        [
            (V, B.PER_DAY),
            (M, B.W_W),
            (M, B.W_V),
            (V, B.V_V),
            (P, B.PER_DOSE_UNIT),
            (P, B.PER_VOLUME),
            (P, B.PER_DAY),
        ],
    )
    def test_family_basis_pair_refused_in_python_and_in_postgres(self, units, family, basis):
        num = None if family == P else ("mg" if family == M else "ml")
        den = ("1", "ml") if basis == B.PER_VOLUME else (None, None)
        with pytest.raises(ValidationError):
            _expression(units, family, basis, num, *den, save=False)
        with pytest.raises(IntegrityError), transaction.atomic():
            QuantityExpression.objects.create(
                family=family,
                basis=basis,
                numerator_unit=units[num] if num else None,
                denominator_amount=Decimal(den[0]) if den[0] else None,
                denominator_unit=units[den[1]] if den[1] else None,
            )

    def test_numerator_unit_must_match_the_family(self, units):
        with pytest.raises(ValidationError, match="is volume, not mass"):
            _expression(units, M, B.PER_DOSE_UNIT, "ml", None, None, save=False)

    def test_mass_without_unit_refused_in_postgres(self, units):
        with pytest.raises(IntegrityError), transaction.atomic():
            QuantityExpression.objects.create(family=M, basis=B.PER_DOSE_UNIT)

    def test_percentage_with_a_unit_refused_in_postgres(self, units):
        with pytest.raises(IntegrityError), transaction.atomic():
            QuantityExpression.objects.create(family=P, basis=B.W_W, numerator_unit=units["mg"])

    @pytest.mark.parametrize("amount", [None, "0", "-5"])
    def test_per_volume_needs_a_positive_stated_volume(self, units, amount):
        with pytest.raises(ValidationError):
            _expression(units, M, B.PER_VOLUME, "mg", amount, "ml", save=False)
        with pytest.raises(IntegrityError), transaction.atomic():
            QuantityExpression.objects.create(
                family=M,
                basis=B.PER_VOLUME,
                numerator_unit=units["mg"],
                denominator_amount=Decimal(amount) if amount else None,
                denominator_unit=units["ml"],
            )

    def test_only_per_volume_has_a_denominator(self, units):
        with pytest.raises(ValidationError, match="Only a per-volume"):
            _expression(units, M, B.PER_DOSE_UNIT, "mg", "5", "ml", save=False)
        with pytest.raises(IntegrityError), transaction.atomic():
            QuantityExpression.objects.create(
                family=M,
                basis=B.PER_DOSE_UNIT,
                numerator_unit=units["mg"],
                denominator_amount=Decimal("5"),
                denominator_unit=units["ml"],
            )

    def test_a_saved_meaning_cannot_be_edited(self, units):
        expr = _expression(units, *MEANING["mg/5ml"])
        expr.denominator_amount = Decimal("1")
        with pytest.raises(ValidationError, match="immutable"):
            expr.full_clean()


@pytest.mark.django_db
class TestLinks:
    def _record(self, row, n):
        release = FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="iig_july_2026.zip",
            source_checksum_sha256=f"{n:064x}",
            status=FDAReleaseStatus.ACTIVE,
        )
        return IIDPrecedentRecord.objects.create(
            release=release,
            ingredient_name_raw=row["INGREDIENT_NAME"],
            route_raw=row["ROUTE"],
            dosage_form_raw=row["DOSAGE_FORM"],
            potency_amount=Decimal(row["POTENCY_AMOUNT"]) if row["POTENCY_AMOUNT"] else None,
            potency_amount_raw=row["POTENCY_AMOUNT"],
            potency_unit_raw=row["POTENCY_UNIT"],
            mde_amount_raw=row["MAXIMUM_DAILY_EXPOSURE"],
            mde_unit_raw=row["MAXIMUM_DAILY_EXPOSURE_UNIT"],
            raw_row_checksum=f"{n:064x}",
        )

    def test_existing_records_and_mappings_start_without_a_meaning(self, units):
        row = next(r for r in ROWS if r["POTENCY_UNIT"] == "mg/5ml")
        record = self._record(row, 1)
        mapping = UnitMapping.objects.create(source_dataset="fda_iid", source_raw_value="mg/5ml")
        assert record.potency_expression is None and record.mde_expression is None
        assert mapping.quantity_expression is None

    def test_record_and_mapping_point_to_the_shared_meaning(self, units):
        expr = _expression(units, *MEANING["mg/5ml"])
        row = next(r for r in ROWS if r["POTENCY_UNIT"] == "mg/5ml")
        record = self._record(row, 2)
        record.potency_expression = expr
        record.save()
        mapping = UnitMapping.objects.create(
            source_dataset="fda_iid", source_raw_value="mg/5ml", quantity_expression=expr
        )
        record.refresh_from_db()
        assert record.potency_expression == expr == mapping.quantity_expression
        assert record.potency_amount == Decimal("45")  # the amount stays on the record

    def test_a_meaning_used_by_a_mapping_cannot_be_deleted(self, units):
        expr = _expression(units, *MEANING["%w/w"])
        UnitMapping.objects.create(
            source_dataset="fda_iid", source_raw_value="%w/w", quantity_expression=expr
        )
        with pytest.raises(ProtectedError):
            expr.delete()

    def test_a_unit_used_by_a_meaning_cannot_be_deleted(self, units):
        _expression(units, *MEANING["mg"])
        with pytest.raises(ProtectedError):
            units["mg"].delete()


BEFORE = [("fda_data", "0006_iidprecedentrecord_mde_amount_raw_and_more")]
AFTER = [("fda_data", "0007_quantity_expression")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


@pytest.mark.django_db(transaction=True)
def test_migration_is_add_only_and_reversible():
    assert "fda_data_quantityexpression" in connection.introspection.table_names()
    assert {"potency_expression_id", "mde_expression_id"} <= _columns("fda_data_iidprecedentrecord")
    try:
        _migrate(BEFORE)
        assert "fda_data_quantityexpression" not in connection.introspection.table_names()
        assert not {"potency_expression_id", "mde_expression_id"} & _columns(
            "fda_data_iidprecedentrecord"
        )
        assert "quantity_expression_id" not in _columns("fda_data_unitmapping")
    finally:
        _migrate(AFTER)
    assert "fda_data_quantityexpression" in connection.introspection.table_names()
    assert "quantity_expression_id" in _columns("fda_data_unitmapping")
