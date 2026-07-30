import pytest

from iig_checklist.applicability import (
    ApplicabilityRuleValidationError,
    canonicalize,
    validate_condition_json,
)
from iig_checklist.field_registry import FIELD_REGISTRY_VERSION


def _leaf(field="product.route", op="eq", value="ORAL"):
    node = {"field": field, "op": op}
    if value is not None:
        node["value"] = value
    return node


class TestApplicabilityValidation:
    def test_valid_composite_rule_accepted(self):
        rule = {
            "operator": "all",
            "conditions": [
                _leaf("product.route", "eq", "ORAL"),
                _leaf("iid.has_mde", "exists", None),
            ],
        }
        validate_condition_json(rule, FIELD_REGISTRY_VERSION)

    def test_unknown_operator_rejected(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(_leaf(op="regex"), FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "UNKNOWN_OPERATOR"

    def test_unknown_field_rejected(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(_leaf(field="arbitrary.python.attr"), FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "UNKNOWN_FIELD"

    def test_type_mismatch_rejected(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(_leaf(op="gt", value="not-a-number"), FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "TYPE_MISMATCH"

    def test_in_operator_requires_array(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(_leaf(op="in", value="ORAL"), FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "TYPE_MISMATCH"

    def test_exists_operator_rejects_value(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(
                {"field": "iid.has_mde", "op": "exists", "value": True}, FIELD_REGISTRY_VERSION
            )
        assert exc_info.value.error_code == "TYPE_MISMATCH"

    def test_missing_value_rejected(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json({"field": "product.route", "op": "eq"}, FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "MISSING_VALUE"

    def test_unknown_key_rejected(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(
                {"field": "product.route", "op": "eq", "value": "ORAL", "extra": 1},
                FIELD_REGISTRY_VERSION,
            )
        assert exc_info.value.error_code == "UNKNOWN_KEY"

    def test_empty_conditions_rejected(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json({"operator": "all", "conditions": []}, FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "EMPTY_CONDITIONS"

    def test_malformed_node_rejected(self):
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json({"nonsense": True}, FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "MALFORMED_JSON"

    def test_recursion_depth_exceeded(self):
        rule = _leaf()
        for _ in range(10):
            rule = {"operator": "all", "conditions": [rule]}
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(rule, FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "RECURSION_DEPTH_EXCEEDED"

    def test_condition_count_exceeded(self):
        rule = {
            "operator": "all",
            "conditions": [_leaf(value=str(i)) for i in range(60)],
        }
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(rule, FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "CONDITION_COUNT_EXCEEDED"

    def test_payload_size_exceeded(self):
        huge_value = "x" * 9000
        rule = _leaf(value=huge_value)
        with pytest.raises(ApplicabilityRuleValidationError) as exc_info:
            validate_condition_json(rule, FIELD_REGISTRY_VERSION)
        assert exc_info.value.error_code == "PAYLOAD_SIZE_EXCEEDED"

    def test_no_eval_of_python_syntax_in_value(self):
        """Planted-failure style: a condition value containing Python
        syntax must be treated as an inert string, never executed."""
        rule = _leaf(op="eq", value="__import__('os').system('echo pwned')")
        # This is a syntactically valid leaf (scalar string value) --
        # it must validate cleanly as an inert string, never execute.
        validate_condition_json(rule, FIELD_REGISTRY_VERSION)

    def test_canonical_serialization_is_order_independent(self):
        a = {"field": "product.route", "op": "eq", "value": "ORAL"}
        b = {"value": "ORAL", "op": "eq", "field": "product.route"}
        assert canonicalize(a) == canonicalize(b)
