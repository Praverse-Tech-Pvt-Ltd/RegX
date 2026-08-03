"""Unit tests for response_validation.validate_raw_value_shape() -- the
canonical raw_value shape for all 18 AnswerType DB values (DR-2-17,
spec §23/§24, Milestone 4D-2 remediation M4D2-F-2)."""

from types import SimpleNamespace

import pytest

from iig_checklist.response_validation import InvalidRawValueShape, validate_raw_value_shape


def _question(answer_type, allowed_units=None, validation_rule=None):
    return SimpleNamespace(
        answer_type=answer_type,
        allowed_units=allowed_units or [],
        validation_rule=validation_rule or {},
    )


def _rejects(answer_type, raw_value, **kwargs):
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(answer_type, raw_value, **kwargs)


def _accepts(answer_type, raw_value, **kwargs):
    validate_raw_value_shape(answer_type, raw_value, **kwargs)  # must not raise


# ---------------------------------------------------------------------------
# raw_value=None is always accepted (is_not_applicable path handled elsewhere)
# ---------------------------------------------------------------------------


def test_none_raw_value_always_accepted():
    for answer_type in (
        "short_text", "integer", "yes_no", "single_select", "calculated_value",
    ):
        _accepts(answer_type, None)


# ---------------------------------------------------------------------------
# short_text / long_narrative
# ---------------------------------------------------------------------------


def test_short_text_accepts_non_empty_string():
    _accepts("short_text", {"value": "hello"})


def test_short_text_rejects_empty_string():
    _rejects("short_text", {"value": ""})


def test_short_text_rejects_wrong_shape():
    _rejects("short_text", {"val": "hello"})
    _rejects("short_text", "hello")


def test_long_narrative_rejects_non_string():
    _rejects("long_narrative", {"value": 123})


# ---------------------------------------------------------------------------
# integer -- DR-2-24 bool/int subclass trap
# ---------------------------------------------------------------------------


def test_integer_accepts_zero_and_one():
    _accepts("integer", {"value": 0})
    _accepts("integer", {"value": 1})
    _accepts("integer", {"value": 42})


def test_integer_rejects_bool_true_and_false():
    _rejects("integer", {"value": True})
    _rejects("integer", {"value": False})


def test_integer_rejects_float_and_string():
    _rejects("integer", {"value": 1.0})
    _rejects("integer", {"value": "1"})


# ---------------------------------------------------------------------------
# decimal / percentage -- reject JSON float, require decimal string
# ---------------------------------------------------------------------------


def test_decimal_accepts_decimal_string():
    _accepts("decimal", {"value": "12.3400"})


def test_decimal_rejects_json_float():
    _rejects("decimal", {"value": 12.34})


def test_decimal_rejects_non_numeric_string():
    _rejects("decimal", {"value": "not-a-number"})


def test_percentage_accepts_boundary_values():
    _accepts("percentage", {"value": "0.0000"})
    _accepts("percentage", {"value": "100.0000"})


def test_percentage_rejects_out_of_range():
    _rejects("percentage", {"value": "100.0001"})
    _rejects("percentage", {"value": "-0.0001"})


def test_percentage_rejects_json_float():
    _rejects("percentage", {"value": 50.0})


# ---------------------------------------------------------------------------
# quantity_with_unit -- allowed_units enforcement (DR-2-25, DR-2-32)
# ---------------------------------------------------------------------------


def test_quantity_with_unit_accepts_allowed_unit():
    q = _question("quantity_with_unit", allowed_units=["mg", "mcg"])
    _accepts("quantity_with_unit", {"value": "12.3400", "unit": "mg"}, question=q)


def test_quantity_with_unit_rejects_unit_not_in_allowed_list():
    q = _question("quantity_with_unit", allowed_units=["mg"])
    _rejects("quantity_with_unit", {"value": "12.3400", "unit": "kg"}, question=q)


def test_quantity_with_unit_empty_allowed_units_rejects_any_unit():
    q = _question("quantity_with_unit", allowed_units=[])
    _rejects("quantity_with_unit", {"value": "12.3400", "unit": "mg"}, question=q)
    _rejects("quantity_with_unit", {"value": "12.3400", "unit": ""}, question=q)


def test_quantity_with_unit_rejects_json_float_value():
    q = _question("quantity_with_unit", allowed_units=["mg"])
    _rejects("quantity_with_unit", {"value": 12.34, "unit": "mg"}, question=q)


# ---------------------------------------------------------------------------
# date
# ---------------------------------------------------------------------------


def test_date_accepts_iso_date():
    _accepts("date", {"value": "2026-01-15"})


def test_date_rejects_non_iso_format():
    _rejects("date", {"value": "01/15/2026"})
    _rejects("date", {"value": "2026-13-99"})


# ---------------------------------------------------------------------------
# yes_no -- JSON boolean only
# ---------------------------------------------------------------------------


def test_yes_no_accepts_boolean():
    _accepts("yes_no", {"value": True})
    _accepts("yes_no", {"value": False})


def test_yes_no_rejects_string():
    _rejects("yes_no", {"value": "true"})
    _rejects("yes_no", {"value": "false"})


# ---------------------------------------------------------------------------
# yes_no_na -- controlled string enum, boolean rejected
# ---------------------------------------------------------------------------


def test_yes_no_na_accepts_controlled_values():
    _accepts("yes_no_na", {"value": "yes"})
    _accepts("yes_no_na", {"value": "no"})
    _accepts("yes_no_na", {"value": "not_applicable"})


def test_yes_no_na_rejects_boolean():
    _rejects("yes_no_na", {"value": True})
    _rejects("yes_no_na", {"value": False})


def test_yes_no_na_rejects_out_of_set_string():
    _rejects("yes_no_na", {"value": "maybe"})


# ---------------------------------------------------------------------------
# single_select / multi_select
# ---------------------------------------------------------------------------


def test_single_select_requires_option_key():
    _accepts("single_select", {"option": "OPTION_A"})
    _rejects("single_select", {"value": "OPTION_A"})


def test_single_select_validates_against_question_options_when_defined():
    q = _question("single_select", validation_rule={"options": ["A", "B"]})
    _accepts("single_select", {"option": "A"}, question=q)
    _rejects("single_select", {"option": "C"}, question=q)


def test_multi_select_accepts_sorted_unique_codes():
    _accepts("multi_select", {"options": ["CODE_A", "CODE_B"]})


def test_multi_select_rejects_duplicates():
    _rejects("multi_select", {"options": ["CODE_A", "CODE_A"]})


def test_multi_select_rejects_unsorted():
    _rejects("multi_select", {"options": ["CODE_B", "CODE_A"]})


def test_multi_select_rejects_empty_list():
    _rejects("multi_select", {"options": []})


def test_multi_select_validates_against_question_options_when_defined():
    q = _question("multi_select", validation_rule={"options": ["A", "B", "C"]})
    _accepts("multi_select", {"options": ["A", "B"]}, question=q)
    _rejects("multi_select", {"options": ["A", "Z"]}, question=q)


# ---------------------------------------------------------------------------
# calculated_value / calculated_status / approval_metadata -- client-rejected
# ---------------------------------------------------------------------------


def test_calculated_value_rejects_any_client_raw_value():
    _rejects("calculated_value", {"value": 1})


def test_calculated_status_rejects_any_client_raw_value():
    _rejects("calculated_status", {"status": "complete"})


def test_approval_metadata_rejects_any_client_raw_value():
    _rejects("approval_metadata", {"anything": "x"})


# ---------------------------------------------------------------------------
# reviewer_conclusion -- out of scope for this path
# ---------------------------------------------------------------------------


def test_reviewer_conclusion_rejected_via_this_path():
    _rejects("reviewer_conclusion", {"value": "conclusion text"})


# ---------------------------------------------------------------------------
# fda_record_reference / formulation_component_reference / attachment_reference
# -- require DB-backed existence checks.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReferenceAnswerTypes:
    def test_fda_record_reference_rejects_unknown_record_type(self):
        _rejects(
            "fda_record_reference",
            {"public_id": "11111111-1111-1111-1111-111111111111", "record_type": "not_a_type"},
        )

    def test_fda_record_reference_rejects_nonexistent_public_id(self):
        _rejects(
            "fda_record_reference",
            {
                "public_id": "11111111-1111-1111-1111-111111111111",
                "record_type": "orange_book_product",
            },
        )

    def test_fda_record_reference_rejects_wrong_shape(self):
        _rejects("fda_record_reference", {"public_id": "11111111-1111-1111-1111-111111111111"})

    def test_formulation_component_reference_rejects_nonexistent_component(self, tenant_a, user_a):
        from formulations.models import FormulationVersion, ProductDevelopmentRecord

        product = ProductDevelopmentRecord.objects.create(
            tenant=tenant_a,
            product_code="PROD-VAL-1",
            proposed_product_name="Product",
            active_ingredient="Synthetic Val Ingredient",
            dosage_form="tablet",
            route="oral",
            created_by=user_a,
        )
        fv = FormulationVersion(
            product=product,
            version_number=1,
            status="approved",
            total_dosage_unit_weight="100.000000",
            total_dosage_unit_weight_unit="mg",
            created_by=user_a,
        )
        fv.save()
        execution = SimpleNamespace(formulation_version=fv)
        _rejects(
            "formulation_component_reference",
            {"public_id": "11111111-1111-1111-1111-111111111111"},
            execution=execution,
        )

    def test_attachment_reference_rejects_nonexistent_document_version(self, tenant_a):
        _rejects(
            "attachment_reference",
            {"document_version_public_id": "11111111-1111-1111-1111-111111111111"},
            tenant=tenant_a,
        )
