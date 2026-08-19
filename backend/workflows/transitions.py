"""Single authoritative WorkflowItem lifecycle transition table.

Structurally identical in shape to `iig_checklist/transitions.py` and
`fda_data/mapping_transitions.py`. This is the third instance of that shape and
deliberately not a generalisation of the other two -- see
docs/MILESTONE_6_WORKFLOW_ENGINE_DISCOVERY.md §B and §J.

This module is pure: it validates and returns, it never mutates or saves. The
caller holds the row lock and performs the write -- see `workflows/services.py`.
"""

from .models import WorkflowItem


class WorkflowAction:
    SUBMIT = "submit"
    BEGIN_REVIEW = "begin_review"
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    RETURN_TO_DRAFT = "return_to_draft"


class IllegalWorkflowTransition(Exception):
    def __init__(self, message: str, current_state: str):
        super().__init__(message)
        self.current_state = current_state


_S = WorkflowItem.State

#: {action: (frozenset of legal current states, resulting state)}
_TRANSITIONS = {
    WorkflowAction.SUBMIT: (
        frozenset({_S.DRAFT}),
        _S.SUBMITTED,
    ),
    WorkflowAction.BEGIN_REVIEW: (
        frozenset({_S.SUBMITTED}),
        _S.IN_REVIEW,
    ),
    WorkflowAction.APPROVE: (
        frozenset({_S.IN_REVIEW}),
        _S.APPROVED,
    ),
    WorkflowAction.REJECT: (
        frozenset({_S.IN_REVIEW}),
        _S.REJECTED,
    ),
    WorkflowAction.RETURN_TO_DRAFT: (
        frozenset({_S.REJECTED}),
        _S.DRAFT,
    ),
    WorkflowAction.CANCEL: (
        frozenset({_S.DRAFT, _S.SUBMITTED, _S.IN_REVIEW, _S.REJECTED}),
        _S.CANCELLED,
    ),
}

#: Terminal states. APPROVED stays terminal in this milestone: a
#: supersede/reopen pattern exists in the repository (ChecklistVersion,
#: TemplateVersion) but it is bound to versioned governed content, and importing
#: it here would give a generic work item versioning semantics it does not have.
TERMINAL_STATES = frozenset({_S.APPROVED, _S.CANCELLED})

#: Actions whose reason must be non-blank. A required reason is a required
#: reason -- it carries no electronic-signature meaning.
REASON_REQUIRED_ACTIONS = frozenset({WorkflowAction.REJECT, WorkflowAction.CANCEL})


def validate_workflow_transition(current_state: str, action: str) -> str:
    """Return the resulting state if `action` is legal from `current_state`.

    Raises IllegalWorkflowTransition otherwise -- callers must not mutate or
    save the item in that case.
    """
    entry = _TRANSITIONS.get(action)
    if entry is None:
        raise IllegalWorkflowTransition(f"Unknown action {action!r}.", current_state)
    legal_from_states, resulting_state = entry
    if current_state not in legal_from_states:
        raise IllegalWorkflowTransition(
            f"Cannot {action} a WorkflowItem while it is {current_state!r}.",
            current_state,
        )
    return resulting_state


def legal_actions_from(current_state: str) -> list[str]:
    """Actions structurally legal from this state, ignoring permissions.

    The API layer intersects this with the caller's permissions so the UI can
    render only actions the caller may actually perform. Structural legality
    alone is never sufficient authority -- see `workflows/permissions.py`.
    """
    return sorted(
        action for action, (legal_from, _to) in _TRANSITIONS.items() if current_state in legal_from
    )
