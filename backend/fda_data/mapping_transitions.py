"""
Single authoritative source of truth for terminology-mapping lifecycle
transitions, across all four mapping types (route, dosage_form, unit,
substance).

No view, serializer, or service may mutate a mapping's status except by
going through validate_mapping_transition() first. This exists because a
prior implementation let any status transition succeed regardless of the
mapping's current status -- e.g. approving a still-PROPOSED or even
REJECTED mapping directly, defeating the mandatory-review-before-approval
design. See docs/HUMAN_REVIEW_PR5_REMEDIATION.md (HR-01).

Rules, identical in spirit across all four types (only the concrete status
values differ, since route/dosage_form/unit use MappingDecisionStatus and
substance uses the richer SubstanceMappingStatus):

- submit_review: only from PROPOSED or RETURNED (RETURNED only exists for
  substance mappings) -> the "under review" status for that type.
- approve: only from the "under review" status -> APPROVED. Never from
  PROPOSED, REJECTED, or RETURNED directly -- this is the fix for the
  segregation-of-duties bypass (HR-01).
- reject: from PROPOSED or "under review" -> REJECTED. Rejecting an
  obviously-wrong proposal without first forcing it through review is
  intentionally allowed (rejection is always the safe direction); this
  matches the pre-existing, tested route/dosage_form/unit behavior.
- return: only from "under review" -> RETURNED (substance only; the other
  three types have no RETURNED status and do not support this action).

APPROVED and REJECTED are terminal for every type: no action table entry
exists for them, so any action attempted against those the mapping is
currently in either status raises IllegalMappingTransition.
"""

from .models import MappingDecisionStatus, SubstanceMappingStatus


class MappingAction:
    SUBMIT_REVIEW = "submit_review"
    APPROVE = "approve"
    REJECT = "reject"
    RETURN = "return"


class IllegalMappingTransition(Exception):
    """Raised when a requested action is not legal from the mapping's
    current status. Callers must convert this to a structured 400 and
    must never mutate or save the mapping when this is raised."""

    def __init__(self, message: str, current_status: str):
        super().__init__(message)
        self.current_status = current_status


# {action: (frozenset of legal current statuses, resulting status)}
_LEGACY_TRANSITIONS = {
    MappingAction.SUBMIT_REVIEW: (
        frozenset({MappingDecisionStatus.PROPOSED}),
        MappingDecisionStatus.REVIEWED,
    ),
    MappingAction.APPROVE: (
        frozenset({MappingDecisionStatus.REVIEWED}),
        MappingDecisionStatus.APPROVED,
    ),
    MappingAction.REJECT: (
        frozenset({MappingDecisionStatus.PROPOSED, MappingDecisionStatus.REVIEWED}),
        MappingDecisionStatus.REJECTED,
    ),
}

_SUBSTANCE_TRANSITIONS = {
    MappingAction.SUBMIT_REVIEW: (
        frozenset({SubstanceMappingStatus.PROPOSED, SubstanceMappingStatus.RETURNED}),
        SubstanceMappingStatus.UNDER_REVIEW,
    ),
    MappingAction.APPROVE: (
        frozenset({SubstanceMappingStatus.UNDER_REVIEW}),
        SubstanceMappingStatus.APPROVED,
    ),
    MappingAction.REJECT: (
        frozenset({SubstanceMappingStatus.PROPOSED, SubstanceMappingStatus.UNDER_REVIEW}),
        SubstanceMappingStatus.REJECTED,
    ),
    MappingAction.RETURN: (
        frozenset({SubstanceMappingStatus.UNDER_REVIEW}),
        SubstanceMappingStatus.RETURNED,
    ),
}

_TRANSITIONS_BY_MAPPING_TYPE = {
    "route": _LEGACY_TRANSITIONS,
    "dosage_form": _LEGACY_TRANSITIONS,
    "unit": _LEGACY_TRANSITIONS,
    "substance": _SUBSTANCE_TRANSITIONS,
}


def validate_mapping_transition(mapping_type: str, current_status: str, action: str) -> str:
    """Returns the resulting status if (mapping_type, action) is a legal
    transition from current_status. Raises IllegalMappingTransition
    otherwise -- callers must not mutate or save the mapping in that case."""
    table = _TRANSITIONS_BY_MAPPING_TYPE.get(mapping_type)
    if table is None:
        raise IllegalMappingTransition(f"Unknown mapping type {mapping_type!r}.", current_status)
    entry = table.get(action)
    if entry is None:
        raise IllegalMappingTransition(
            f"{action!r} is not a supported action for {mapping_type!r} mappings.",
            current_status,
        )
    legal_from_statuses, resulting_status = entry
    if current_status not in legal_from_statuses:
        raise IllegalMappingTransition(
            f"Cannot {action} a {mapping_type!r} mapping while it is {current_status!r}.",
            current_status,
        )
    return resulting_status
