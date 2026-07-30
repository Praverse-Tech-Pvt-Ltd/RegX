"""Structured, allow-listed applicability-rule JSON validator (see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §5). No eval/exec, no
dynamic attribute access, no arbitrary executable expression -- a fixed
dispatch table keyed by `op`, plus a fixed set of composite operators.

4D-1 validates and canonicalizes only. Runtime evaluation of a
condition tree against a real execution context is a later Milestone
4D stage.
"""

import json

from .field_registry import allowed_fields_for_version

MAX_RECURSION_DEPTH = 5
MAX_CONDITION_COUNT = 50
MAX_PAYLOAD_BYTES = 8 * 1024

LEAF_OPERATORS = frozenset(
    {"eq", "neq", "in", "not_in", "exists", "not_exists", "gt", "gte", "lt", "lte"}
)
COMPOSITE_OPERATORS = frozenset({"all", "any"})
_NO_VALUE_OPERATORS = frozenset({"exists", "not_exists"})
_ARRAY_VALUE_OPERATORS = frozenset({"in", "not_in"})
_NUMERIC_VALUE_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})


class ApplicabilityRuleValidationError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def _err(code: str, message: str):
    raise ApplicabilityRuleValidationError(code, message)


def _validate_node(node, allowed_fields: frozenset[str], depth: int, counter: list[int]) -> None:
    if depth > MAX_RECURSION_DEPTH:
        _err("RECURSION_DEPTH_EXCEEDED", f"Condition tree exceeds max depth {MAX_RECURSION_DEPTH}.")
    if not isinstance(node, dict):
        _err("MALFORMED_JSON", "Every condition node must be a JSON object.")

    keys = set(node.keys())

    if "operator" in node and "conditions" in node:
        # Composite node.
        if keys - {"operator", "conditions"}:
            extra = keys - {"operator", "conditions"}
            _err("UNKNOWN_KEY", f"Unexpected keys on composite node: {extra}")
        op = node["operator"]
        if op not in COMPOSITE_OPERATORS:
            _err("UNKNOWN_OPERATOR", f"Unknown composite operator: {op!r}")
        conditions = node["conditions"]
        if not isinstance(conditions, list) or not conditions:
            _err("EMPTY_CONDITIONS", "Composite 'conditions' must be a non-empty array.")
        for child in conditions:
            counter[0] += 1
            if counter[0] > MAX_CONDITION_COUNT:
                _err(
                    "CONDITION_COUNT_EXCEEDED",
                    f"Condition tree exceeds max leaf count {MAX_CONDITION_COUNT}.",
                )
            _validate_node(child, allowed_fields, depth + 1, counter)
        return

    if "field" in node and "op" in node:
        # Leaf node.
        allowed_leaf_keys = {"field", "op", "value"}
        if keys - allowed_leaf_keys:
            _err("UNKNOWN_KEY", f"Unexpected keys on leaf node: {keys - allowed_leaf_keys}")
        field = node["field"]
        op = node["op"]
        if op not in LEAF_OPERATORS:
            _err("UNKNOWN_OPERATOR", f"Unknown leaf operator: {op!r}")
        if field not in allowed_fields:
            _err("UNKNOWN_FIELD", f"Field not in allow-list: {field!r}")

        has_value = "value" in node
        if op in _NO_VALUE_OPERATORS:
            if has_value:
                _err("TYPE_MISMATCH", f"Operator {op!r} must not include a 'value'.")
            return
        if not has_value:
            _err("MISSING_VALUE", f"Operator {op!r} requires a 'value'.")
        value = node["value"]
        if op in _ARRAY_VALUE_OPERATORS:
            if not isinstance(value, list):
                _err("TYPE_MISMATCH", f"Operator {op!r} requires an array 'value'.")
        elif op in _NUMERIC_VALUE_OPERATORS:
            if isinstance(value, bool) or not isinstance(value, int | float):
                _err("TYPE_MISMATCH", f"Operator {op!r} requires a numeric 'value'.")
        else:  # eq / neq
            if not isinstance(value, str | int | float | bool):
                _err("TYPE_MISMATCH", f"Operator {op!r} requires a scalar 'value'.")
        return

    _err(
        "MALFORMED_JSON",
        "Node must be either a composite ({operator, conditions}) or a leaf ({field, op, value?}).",
    )


def validate_condition_json(condition_json, field_registry_version: int) -> None:
    """Raises ApplicabilityRuleValidationError on any violation."""
    serialized = json.dumps(condition_json)
    if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        _err("PAYLOAD_SIZE_EXCEEDED", f"Payload exceeds {MAX_PAYLOAD_BYTES} bytes.")

    allowed_fields = allowed_fields_for_version(field_registry_version)
    counter = [0]
    _validate_node(condition_json, allowed_fields, depth=1, counter=counter)


def canonicalize(condition_json) -> str:
    """Canonical serialization for checksums -- sorted keys, no
    insignificant whitespace, so semantically-identical rules
    serialized differently never produce different checksums."""
    return json.dumps(condition_json, sort_keys=True, separators=(",", ":"))
