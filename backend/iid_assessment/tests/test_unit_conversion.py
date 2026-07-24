"""
Unit-conversion engine tests. Every test that plants a violation is noted.
"""

from decimal import Decimal

import pytest

from iid_assessment.unit_conversion import (
    ConversionReasonCode,
    calculate_percentage_w_w,
    convert,
    convert_mass_or_volume,
    convert_with_density,
)


class TestMassConversions:
    def test_microgram_to_milligram(self):
        result = convert_mass_or_volume(Decimal("1000"), "microgram", "milligram")
        assert result.ok
        assert result.converted_value == Decimal("1")

    def test_milligram_to_gram(self):
        result = convert_mass_or_volume(Decimal("1000"), "milligram", "gram")
        assert result.ok
        assert result.converted_value == Decimal("1")

    def test_gram_to_kilogram(self):
        result = convert_mass_or_volume(Decimal("1000"), "gram", "kilogram")
        assert result.ok
        assert result.converted_value == Decimal("1")

    def test_result_is_decimal_not_float(self):
        # PLANTED VIOLATION (detected): the conversion must never produce a
        # Python float anywhere in the result.
        result = convert_mass_or_volume(Decimal("500"), "milligram", "gram")
        assert isinstance(result.converted_value, Decimal)
        assert not isinstance(result.converted_value, float)


class TestVolumeConversions:
    def test_microlitre_to_millilitre(self):
        result = convert_mass_or_volume(Decimal("1000"), "microlitre", "millilitre")
        assert result.ok
        assert result.converted_value == Decimal("1")

    def test_millilitre_to_litre(self):
        result = convert_mass_or_volume(Decimal("1000"), "millilitre", "litre")
        assert result.ok
        assert result.converted_value == Decimal("1")


class TestCountConversions:
    def test_same_count_unit_passes_through(self):
        result = convert(Decimal("5"), "tablet", "tablet")
        assert result.ok
        assert result.converted_value == Decimal("5")

    def test_different_count_units_not_supported(self):
        # PLANTED VIOLATION (detected): "tablet" and "capsule" must never
        # be silently treated as interchangeable.
        result = convert(Decimal("5"), "tablet", "capsule")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.CONVERSION_NOT_SUPPORTED


class TestDimensionMismatch:
    def test_mass_to_volume_without_convert_helper_fails(self):
        result = convert_mass_or_volume(Decimal("10"), "milligram", "millilitre")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.DIMENSION_MISMATCH

    def test_mass_to_count_fails(self):
        result = convert(Decimal("10"), "milligram", "tablet")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.DIMENSION_MISMATCH


class TestDensityRequired:
    def test_mass_to_volume_without_density_fails_closed(self):
        # PLANTED VIOLATION (detected): mass<->volume must never proceed
        # without an explicit density.
        result = convert(Decimal("10"), "gram", "millilitre")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.DENSITY_REQUIRED

    def test_mass_to_volume_with_density_succeeds(self):
        # 10 g at density 1 g/mL -> 10 mL
        result = convert_with_density(Decimal("10"), "gram", "millilitre", Decimal("1"))
        assert result.ok
        assert result.converted_value == Decimal("10")

    def test_volume_to_mass_with_density(self):
        result = convert_with_density(Decimal("10"), "millilitre", "gram", Decimal("2"))
        assert result.ok
        assert result.converted_value == Decimal("20")

    def test_zero_or_negative_density_rejected(self):
        result = convert_with_density(Decimal("10"), "gram", "millilitre", Decimal("0"))
        assert result.failed
        assert result.reason_code == ConversionReasonCode.INVALID_VALUE


class TestUnknownUnitAndMissingValues:
    def test_unknown_unit_fails_closed(self):
        # PLANTED VIOLATION (detected): a completely unrecognized unit
        # string must never be silently guessed.
        result = convert(Decimal("10"), "furlong", "gram")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.UNIT_UNKNOWN

    def test_missing_value_fails_closed(self):
        result = convert_mass_or_volume(None, "milligram", "gram")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.VALUE_MISSING

    def test_invalid_value_fails_closed(self):
        result = convert_mass_or_volume("not-a-number", "milligram", "gram")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.INVALID_VALUE


class TestPercentageWW:
    def test_percentage_w_w_basic(self):
        # 50 mg excipient in a 500 mg tablet -> 10% w/w
        result = calculate_percentage_w_w(Decimal("50"), "milligram", Decimal("500"), "milligram")
        assert result.ok
        assert result.converted_value == Decimal("10")

    def test_percentage_w_w_requires_mass_basis(self):
        # PLANTED VIOLATION (detected): % w/w must never be computed
        # against a non-mass unit without an explicit basis.
        result = calculate_percentage_w_w(Decimal("50"), "millilitre", Decimal("500"), "milligram")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.BASIS_REQUIRED

    def test_percentage_w_w_zero_total_fails_closed(self):
        result = calculate_percentage_w_w(Decimal("50"), "milligram", Decimal("0"), "milligram")
        assert result.failed
        assert result.reason_code == ConversionReasonCode.INVALID_VALUE


@pytest.mark.parametrize(
    "value",
    [Decimal("1"), Decimal("0.001"), Decimal("123456.789")],
)
def test_decimal_precision_preserved_across_conversion(value):
    result = convert_mass_or_volume(value, "gram", "milligram")
    assert result.ok
    assert isinstance(result.converted_value, Decimal)
