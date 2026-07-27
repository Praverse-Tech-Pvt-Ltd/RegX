"""
Direct runtime tests that calculation-facing serializers and services never
introduce a binary-float artifact, and that malformed/non-numeric input is
rejected with a structured error rather than silently coerced.
"""

from decimal import Decimal

from iid_assessment import unit_conversion
from iid_assessment.calculations import calculate_percentage_of_potency
from iid_assessment.serializers import MatchPreviewRequestSerializer

BASE = "/api/regx/v1"


class TestSerializerDecimalSafety:
    def test_json_float_becomes_exact_decimal_not_binary_artifact(self):
        # JSON transport turns "0.1" into a Python float (0.1) before it
        # ever reaches the serializer -- DRF's DecimalField must convert
        # via str(data), never Decimal(data) directly on the float, or the
        # binary-float artifact (0.1000000000000000055511151231257827...)
        # would leak into a max_digits=20 field.
        serializer = MatchPreviewRequestSerializer(
            data={
                "ingredient_public_id": "11111111-1111-1111-1111-111111111111",
                "route_code": "oral",
                "dosage_form_code": "tablet",
                "active_release_public_id": "22222222-2222-2222-2222-222222222222",
                "proposed_quantity_per_unit": 0.1,
                "proposed_quantity_unit": "milligram",
                "total_dosage_unit_weight": 0.2,
                "total_dosage_unit_weight_unit": "milligram",
            }
        )
        assert serializer.is_valid(), serializer.errors
        value = serializer.validated_data["proposed_quantity_per_unit"]
        total = serializer.validated_data["total_dosage_unit_weight"]
        assert isinstance(value, Decimal)
        assert value == Decimal("0.1")
        assert total == Decimal("0.2")
        assert value + total == Decimal("0.3")
        # No 17-significant-digit binary-float tail leaked into the string.
        assert len(str(value).split(".")[-1]) <= 6

    def test_string_decimal_input_also_exact(self):
        serializer = MatchPreviewRequestSerializer(
            data={
                "ingredient_public_id": "11111111-1111-1111-1111-111111111111",
                "route_code": "oral",
                "dosage_form_code": "tablet",
                "active_release_public_id": "22222222-2222-2222-2222-222222222222",
                "proposed_quantity_per_unit": "0.3",
                "proposed_quantity_unit": "milligram",
                "total_dosage_unit_weight": "500",
                "total_dosage_unit_weight_unit": "milligram",
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["proposed_quantity_per_unit"] == Decimal("0.3")

    def test_non_numeric_string_rejected_structured(self):
        serializer = MatchPreviewRequestSerializer(
            data={
                "ingredient_public_id": "11111111-1111-1111-1111-111111111111",
                "route_code": "oral",
                "dosage_form_code": "tablet",
                "active_release_public_id": "22222222-2222-2222-2222-222222222222",
                "proposed_quantity_per_unit": "not-a-number",
                "proposed_quantity_unit": "milligram",
                "total_dosage_unit_weight": "500",
                "total_dosage_unit_weight_unit": "milligram",
            }
        )
        assert not serializer.is_valid()
        assert "proposed_quantity_per_unit" in serializer.errors

    def test_nan_and_infinity_rejected(self):
        for bad_value in ("nan", "inf", "-inf", float("nan"), float("inf")):
            serializer = MatchPreviewRequestSerializer(
                data={
                    "ingredient_public_id": "11111111-1111-1111-1111-111111111111",
                    "route_code": "oral",
                    "dosage_form_code": "tablet",
                    "active_release_public_id": "22222222-2222-2222-2222-222222222222",
                    "proposed_quantity_per_unit": bad_value,
                    "proposed_quantity_unit": "milligram",
                    "total_dosage_unit_weight": "500",
                    "total_dosage_unit_weight_unit": "milligram",
                }
            )
            assert not serializer.is_valid(), f"{bad_value!r} should not validate"


class TestEngineDecimalSafety:
    def test_unit_conversion_rejects_raw_python_object_cleanly(self):
        # Something that can't become a Decimal at all (e.g. a dict) must
        # fail closed with INVALID_VALUE, never raise an uncaught TypeError.
        result = unit_conversion.convert({"not": "a number"}, "milligram", "gram")
        assert not result.ok
        assert result.reason_code == unit_conversion.ConversionReasonCode.INVALID_VALUE

    def test_calculation_engine_deterministic_decimal_formatting(self):
        result = calculate_percentage_of_potency(
            converted_proposed_quantity=Decimal("0.1") + Decimal("0.2"),
            selected_iid_potency_amount=Decimal("1"),
        )
        assert result.ok
        assert isinstance(result.value, Decimal)
        # Deterministic: repeated calls with identical Decimal inputs
        # produce byte-identical output every time (no nondeterministic
        # float rounding across runs/platforms).
        result2 = calculate_percentage_of_potency(
            converted_proposed_quantity=Decimal("0.1") + Decimal("0.2"),
            selected_iid_potency_amount=Decimal("1"),
        )
        assert result.value == result2.value == Decimal("30")
