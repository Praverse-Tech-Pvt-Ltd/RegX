"""Execution lifecycle transition table -- structurally identical in shape
to iig_checklist/transitions.py (ChecklistVersion transitions).
"""

TERMINAL_EXECUTION_STATUSES = frozenset({"rejected", "cancelled", "superseded"})

_EXECUTION_TRANSITIONS: dict[str, tuple[frozenset, str]] = {
    "submit_review": (frozenset({"draft", "returned"}), "submitted_for_review"),
    "approve": (frozenset({"submitted_for_review"}), "approved"),
    "return": (frozenset({"submitted_for_review"}), "returned"),
    "reject": (frozenset({"draft", "submitted_for_review"}), "rejected"),
    "cancel": (frozenset({"draft", "returned"}), "cancelled"),
    "supersede": (frozenset({"approved"}), "superseded"),
}


class IllegalExecutionTransition(ValueError):
    pass


def validate_execution_transition(current_status: str, action: str) -> str:
    """Returns the resulting status. Raises IllegalExecutionTransition on illegal path."""
    if action not in _EXECUTION_TRANSITIONS:
        raise IllegalExecutionTransition(f"Unknown action: {action!r}")
    legal_from, resulting_status = _EXECUTION_TRANSITIONS[action]
    if current_status not in legal_from:
        raise IllegalExecutionTransition(
            f"Action {action!r} is not legal from status {current_status!r}."
        )
    return resulting_status
