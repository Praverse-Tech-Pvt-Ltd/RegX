"""Single authoritative ChecklistVersion lifecycle transition table --
structurally identical in shape to fda_data/mapping_transitions.py.

The RETURNED/REJECTED refinement here is a disclosed, approved deviation
from the earlier Milestone 4D design's leaner table -- see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §6a and
docs/MILESTONE_4D_1_SPEC_REMEDIATION.md (SR-01).
"""

from .enums import ChecklistVersionStatus


class VersionAction:
    SUBMIT_REVIEW = "submit_review"
    APPROVE = "approve"
    RETURN = "return"
    REJECT = "reject"
    ACTIVATE = "activate"
    SUPERSEDE = "supersede"
    RETIRE = "retire"


class IllegalVersionTransition(Exception):
    def __init__(self, message: str, current_status: str):
        super().__init__(message)
        self.current_status = current_status


# {action: (frozenset of legal current statuses, resulting status)}
_TRANSITIONS = {
    VersionAction.SUBMIT_REVIEW: (
        frozenset({ChecklistVersionStatus.DRAFT, ChecklistVersionStatus.RETURNED}),
        ChecklistVersionStatus.UNDER_REVIEW,
    ),
    VersionAction.APPROVE: (
        frozenset({ChecklistVersionStatus.UNDER_REVIEW}),
        ChecklistVersionStatus.APPROVED,
    ),
    VersionAction.RETURN: (
        frozenset({ChecklistVersionStatus.UNDER_REVIEW}),
        ChecklistVersionStatus.RETURNED,
    ),
    VersionAction.REJECT: (
        frozenset({ChecklistVersionStatus.DRAFT, ChecklistVersionStatus.UNDER_REVIEW}),
        ChecklistVersionStatus.REJECTED,
    ),
    VersionAction.ACTIVATE: (
        frozenset({ChecklistVersionStatus.APPROVED}),
        ChecklistVersionStatus.ACTIVE,
    ),
    VersionAction.SUPERSEDE: (
        frozenset({ChecklistVersionStatus.ACTIVE}),
        ChecklistVersionStatus.SUPERSEDED,
    ),
    VersionAction.RETIRE: (
        frozenset(
            {
                ChecklistVersionStatus.DRAFT,
                ChecklistVersionStatus.APPROVED,
                ChecklistVersionStatus.ACTIVE,
                ChecklistVersionStatus.RETURNED,
            }
        ),
        ChecklistVersionStatus.RETIRED,
    ),
}


def validate_version_transition(current_status: str, action: str) -> str:
    """Returns the resulting status if `action` is legal from
    `current_status`. Raises IllegalVersionTransition otherwise -- callers
    must not mutate or save the version in that case."""
    entry = _TRANSITIONS.get(action)
    if entry is None:
        raise IllegalVersionTransition(f"Unknown action {action!r}.", current_status)
    legal_from_statuses, resulting_status = entry
    if current_status not in legal_from_statuses:
        raise IllegalVersionTransition(
            f"Cannot {action} a ChecklistVersion while it is {current_status!r}.",
            current_status,
        )
    return resulting_status
