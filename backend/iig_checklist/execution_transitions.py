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
    # Owner, 2026-11-27: a superseded execution can be reinstated to approved (VP, with a reason).
    "reinstate": (frozenset({"superseded"}), "approved"),
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


#: action -> the permission codename its endpoint checks (iig_checklist/views.py).
ACTION_PERMISSIONS = {
    "submit_review": "iig_checklist.submit_execution",
    "approve": "iig_checklist.approve_execution",
    "return": "iig_checklist.review_execution",
    "reject": "iig_checklist.approve_execution",
    "cancel": "iig_checklist.cancel_execution",
    "supersede": "iig_checklist.supersede_execution",
    "reinstate": "iig_checklist.reinstate_execution",
}


def available_actions(execution, user, has_permission) -> list[str]:
    """The actions this user could take on this execution now, for the screen.

    Display only: every action endpoint still checks its permission, the legal
    transition and (for approve) that the approver is not the submitter. This
    list just stops the screen offering buttons that would be refused.
    `has_permission(codename) -> bool` is the caller's tenant-scoped check.
    """
    actions = []
    for action, (legal_from, _resulting) in _EXECUTION_TRANSITIONS.items():
        if execution.status not in legal_from:
            continue
        if not has_permission(ACTION_PERMISSIONS[action]):
            continue
        if action == "approve" and execution.submitted_by_id == getattr(user, "id", None):
            continue  # SelfApprovalForbidden
        actions.append(action)
    return actions
