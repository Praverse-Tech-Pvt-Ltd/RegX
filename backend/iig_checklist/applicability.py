"""Structured, allow-listed applicability-rule JSON validator (see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §5). No eval/exec, no
dynamic attribute access, no arbitrary executable expression -- a fixed
dispatch table keyed by `op`, plus a fixed set of composite operators.

4D-1 validated and canonicalized only. Milestone 5A-P1 adds the runtime
evaluator required by `5A-DEC-004`: persisting a rule without ever evaluating it
is not sufficient for production, because a question would then be presented as
applicable to every product regardless of what the approved rule says.

The evaluator implements the already-approved semantics exactly (M4D3-APP-001
through M4D3-APP-007) and invents no new vocabulary: same operators, same six
registry fields, same three outcomes. It is a pure function -- no database
access, no side effects, no `eval`, no `exec`, no dynamic attribute access --
so an approved rule evaluates identically wherever and whenever it is run.
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


# ---------------------------------------------------------------------------
# Runtime evaluator -- `5A-DEC-004`, implementing M4D3-APP-001..007.
#
# Deliberately a mirror of the validator above rather than a second grammar:
# the same operator sets drive both, so a tree that validates is a tree this
# can evaluate. A node reaching the evaluator that matches neither shape is a
# validator contract breach, not bad input, and raises RuntimeError to say so.
# ---------------------------------------------------------------------------

#: Sentinel for "this field is not in the context at all". Distinct from a
#: context value of ``None``, which is a real answer meaning "known absent".
_ABSENT = object()


class ApplicabilityEvaluationError(RuntimeError):
    """The validator's contract was broken -- a node shape reached the
    evaluator that `validate_condition_json()` should already have refused.

    A ``RuntimeError`` subclass on purpose (M4D3-APP-003): this is an internal
    invariant failure, not a user-input validation error, and conflating the two
    would let a genuine bug be reported to a client as if they had sent
    something wrong.
    """


def _leaf_value(context, field: str):
    """Read one field. Missing and explicitly-null are both absent."""
    value = context.get(field, _ABSENT)
    return _ABSENT if value is None else value


def _evaluate_leaf(node, context) -> bool:
    field = node["field"]
    op = node["op"]
    actual = _leaf_value(context, field)

    # M4D3-APP-005 -- absence is decided first, for every operator. An absent
    # field can only satisfy `not_exists`; every comparison against it is False
    # rather than an error, so a rule never fails closed by accident on a
    # product that simply has no value for that field.
    if op == "exists":
        return actual is not _ABSENT
    if op == "not_exists":
        return actual is _ABSENT
    if actual is _ABSENT:
        return False

    expected = node.get("value")

    if op == "eq":
        return _scalar_equal(actual, expected)
    if op == "neq":
        return not _scalar_equal(actual, expected)
    if op == "in":
        return any(_scalar_equal(actual, candidate) for candidate in expected)
    if op == "not_in":
        return not any(_scalar_equal(actual, candidate) for candidate in expected)

    # Numeric comparisons. A non-numeric actual value is False rather than a
    # TypeError: the validator guarantees the *rule* side is numeric, but the
    # context side comes from product data and may legitimately be a string.
    if isinstance(actual, bool) or not isinstance(actual, int | float):
        return False
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected

    raise ApplicabilityEvaluationError(f"Unknown leaf operator reached evaluator: {op!r}")


def _scalar_equal(actual, expected) -> bool:
    """Equality that refuses Python's bool/int conflation.

    Without this, ``True == 1`` would make a rule comparing `iid.has_mde` to 1
    match a boolean context value. Regulated branching must not turn on that.
    """
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    return actual == expected


def _evaluate_node(node, context, depth: int) -> bool:
    if depth > MAX_RECURSION_DEPTH:
        # Unreachable for a validated tree; a guard, not a limit, so a
        # hand-built tree can never spin the interpreter.
        raise ApplicabilityEvaluationError(
            f"Condition tree exceeds max depth {MAX_RECURSION_DEPTH} at evaluation."
        )
    if not isinstance(node, dict):
        raise ApplicabilityEvaluationError("Every condition node must be a JSON object.")

    if "operator" in node and "conditions" in node:
        op = node["operator"]
        children = node["conditions"]
        if op not in COMPOSITE_OPERATORS or not isinstance(children, list) or not children:
            raise ApplicabilityEvaluationError(f"Malformed composite node: {op!r}")
        # Evaluated in full rather than short-circuited: every child is a pure
        # function of the same context, so there is nothing to save, and
        # evaluating all of them means a malformed sibling is always detected
        # instead of being hidden by an early exit.
        results = [_evaluate_node(child, context, depth + 1) for child in children]
        return all(results) if op == "all" else any(results)

    if "field" in node and "op" in node:
        return _evaluate_leaf(node, context)

    # M4D3-APP-003.
    raise ApplicabilityEvaluationError(
        "Node must be either a composite ({operator, conditions}) or a leaf ({field, op, value?})."
    )


def evaluate_condition(condition_json, context) -> bool:
    """Evaluate a validated condition tree against a context dict."""
    if not isinstance(context, dict):
        raise ApplicabilityEvaluationError("context must be a dict.")
    return _evaluate_node(condition_json, context, depth=1)


def evaluate_applicability(rule, context) -> str:
    """M4D3-APP-001/004 -- the governed outcome for one rule and one context.

    Returns the rule's own ``outcome_if_true`` / ``outcome_if_false``, never a
    bare boolean: which branch means "not applicable" is the rule author's
    decision, and hard-coding it here would silently override approved content.
    """
    matched = evaluate_condition(rule.condition_json, context)
    return rule.outcome_if_true if matched else rule.outcome_if_false
