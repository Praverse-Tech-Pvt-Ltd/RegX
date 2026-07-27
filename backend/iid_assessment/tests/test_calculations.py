"""
Calculation engine tests. Every test that plants a violation is noted.
"""

from decimal import Decimal

from iid_assessment.calculations import (
    CalculationStatus,
    calculate_daily_exposure,
    calculate_difference_from_mde,
    calculate_difference_from_potency,
    calculate_percentage_of_mde,
    calculate_percentage_of_potency,
    calculate_percentage_w_w,
)


class TestPercentageWW:
    def test_basic(self):
        result = calculate_percentage_w_w(
            quantity_per_unit_grams=Decimal("50"), total_dosage_unit_weight_grams=Decimal("500")
        )
        assert result.ok
        assert result.value == Decimal("10")
        assert isinstance(result.value, Decimal)

    def test_missing_daily_dose_style_missing_value_blocks(self):
        result = calculate_percentage_w_w(
            quantity_per_unit_grams=None, total_dosage_unit_weight_grams=Decimal("500")
        )
        assert not result.ok
        assert result.status == CalculationStatus.PROPOSED_VALUE_MISSING

    def test_zero_denominator_blocks(self):
        # PLANTED VIOLATION (detected): division by zero must never raise
        # or silently return zero -- it must return a blocked status.
        result = calculate_percentage_w_w(
            quantity_per_unit_grams=Decimal("50"), total_dosage_unit_weight_grams=Decimal("0")
        )
        assert not result.ok
        assert result.status == CalculationStatus.BASIS_UNCLEAR


class TestDailyExposure:
    def test_basic(self):
        result = calculate_daily_exposure(
            quantity_per_dosage_unit=Decimal("10"), maximum_dosage_units_per_day=Decimal("4")
        )
        assert result.ok
        assert result.value == Decimal("40")

    def test_missing_max_daily_dose_blocks(self):
        # PLANTED VIOLATION (detected): calculation must not proceed
        # without maximum_dosage_units_per_day.
        result = calculate_daily_exposure(
            quantity_per_dosage_unit=Decimal("10"), maximum_dosage_units_per_day=None
        )
        assert not result.ok
        assert result.status == CalculationStatus.MAX_DAILY_UNITS_MISSING


class TestPercentageOfPotency:
    def test_basic(self):
        result = calculate_percentage_of_potency(
            converted_proposed_quantity=Decimal("5"), selected_iid_potency_amount=Decimal("10")
        )
        assert result.ok
        assert result.value == Decimal("50")

    def test_missing_fda_value_blocks(self):
        # PLANTED VIOLATION (detected): a missing IID potency value must
        # never be treated as zero.
        result = calculate_percentage_of_potency(
            converted_proposed_quantity=Decimal("5"), selected_iid_potency_amount=None
        )
        assert not result.ok
        assert result.status == CalculationStatus.IID_VALUE_MISSING

    def test_invalid_zero_potency_blocks(self):
        result = calculate_percentage_of_potency(
            converted_proposed_quantity=Decimal("5"), selected_iid_potency_amount=Decimal("0")
        )
        assert not result.ok
        assert result.status == CalculationStatus.IID_VALUE_INVALID


class TestDifferenceFromPotency:
    def test_basic(self):
        result = calculate_difference_from_potency(
            selected_iid_potency_amount=Decimal("10"), converted_proposed_quantity=Decimal("4")
        )
        assert result.ok
        assert result.value == Decimal("6")


class TestPercentageOfMde:
    def test_basic(self):
        result = calculate_percentage_of_mde(
            converted_proposed_daily_exposure=Decimal("20"), selected_iid_mde=Decimal("40")
        )
        assert result.ok
        assert result.value == Decimal("50")

    def test_missing_mde_blocks_not_zero(self):
        # PLANTED VIOLATION (detected): missing MDE must return
        # IID_VALUE_MISSING, never a silently computed 0% or 100%.
        result = calculate_percentage_of_mde(
            converted_proposed_daily_exposure=Decimal("20"), selected_iid_mde=None
        )
        assert not result.ok
        assert result.status == CalculationStatus.IID_VALUE_MISSING


class TestDifferenceFromMde:
    def test_basic(self):
        result = calculate_difference_from_mde(
            selected_iid_mde=Decimal("40"), converted_proposed_daily_exposure=Decimal("20")
        )
        assert result.ok
        assert result.value == Decimal("20")


class TestStructuredResultShape:
    def test_every_result_carries_formula_identity_and_provenance(self):
        result = calculate_percentage_w_w(
            quantity_per_unit_grams=Decimal("1"), total_dosage_unit_weight_grams=Decimal("2")
        )
        assert result.formula_identifier == "percentage_w_w"
        assert result.formula_version
        assert result.generated_at
        assert "quantity_per_unit_grams" in result.inputs

    def test_blocked_result_still_carries_reason_code(self):
        result = calculate_daily_exposure(
            quantity_per_dosage_unit=None, maximum_dosage_units_per_day=Decimal("4")
        )
        assert result.reason_code is not None
