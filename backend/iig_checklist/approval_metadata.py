"""Milestone 4D-4 -- governed ``approval_metadata`` generation (``4D4-DEC-008``).

Specification: ``MILESTONE_4D_4_DISCOVERY.md`` §AD (approved 2026-08-12).

``approval_metadata`` is an :class:`~iig_checklist.enums.AnswerType`, not an
execution column -- a per-question response whose payload lives in
``ChecklistResponse.raw_value``. Its compatibility floor is ``REVIEWER_CONFIRMED``
only, and it sits in ``response_validation._CLIENT_REJECTED_TYPES``, so a client
may never supply it.

**It is a projection, not a second approval system.** Every value below is derived
from governed state that already exists on ``ChecklistExecution`` -- ``approved_by``,
``approved_at`` -- or from the pinned checklist version. Nothing here introduces a
parallel record of who approved what, and no new column is added: ``4D4-DEC-008``
approves no new field, so this slice implies no migration.

Written once, inside the approve transition's own ``transaction.atomic()`` block,
so the metadata and the approval status commit together or not at all. After
approval the execution leaves ``EDITABLE_EXECUTION_STATUSES``, so no governed path
can rewrite it -- immutability comes from the lifecycle rather than from a second
guard invented here.
"""

from __future__ import annotations

__all__ = [
    "ALLOWED_APPROVAL_METADATA_FIELDS",
    "APPROVAL_DECISION_APPROVED",
    "ApprovalMetadataError",
    "build_approval_metadata",
    "populate_approval_metadata",
]

#: The only decision this payload records. ``4D4-DEC-008`` approves the approved
#: case only; rejection and return have their own governed columns and are not
#: projected here.
APPROVAL_DECISION_APPROVED = "approved"

#: ``4D4-DEC-008`` -- the exact approved key set. Positive-listed for the same
#: reason as the export provenance allow-lists: a key added later cannot reach a
#: regulatory artifact without a governed decision. No actor email or display
#: name, no database primary keys, no free-form extension, no approval comment.
ALLOWED_APPROVAL_METADATA_FIELDS: frozenset[str] = frozenset(
    {
        "approval_decision",
        "approved_by_public_id",
        "approved_at",
        "execution_public_id",
        "checklist_version_public_id",
        "checklist_version_number",
        "reviewer_conclusion_response_public_id",
    }
)


class ApprovalMetadataError(Exception):
    """A generated payload violated the approved contract."""


def _reviewer_conclusion_response(execution):
    """The governed reviewer-conclusion response for this execution, or ``None``.

    ``4D4-DEC-008`` makes the linkage **conditional**: the key is present only
    where a governed reviewer-conclusion response actually carries a value. An
    unanswered conclusion question is not a linkage, so it is omitted rather than
    exported as null.
    """
    from .enums import AnswerType

    return (
        execution.responses.select_related("question")
        .filter(question__answer_type=AnswerType.REVIEWER_CONCLUSION)
        .exclude(raw_value=None)
        .order_by("public_id")
        .first()
    )


def build_approval_metadata(*, execution, actor, approved_at, reviewer_conclusion_response=None):
    """Assemble the governed payload for one approved execution.

    ``approved_at`` is rendered through the same UTC/``Z`` convention
    ``4D4-DEC-006`` fixes for the controlled export, so an approval timestamp
    reads identically wherever it surfaces.
    """
    # The governed timestamp renderer. Reused rather than reimplemented -- a
    # second copy could drift from the canonical form DEC-006 fixes, which is
    # exactly the argument that promoted the CSV helper to `common`.
    from .controlled_export import _iso_utc

    version = execution.checklist_version
    payload = {
        "approval_decision": APPROVAL_DECISION_APPROVED,
        "approved_by_public_id": str(actor.public_id),
        "approved_at": _iso_utc(approved_at),
        "execution_public_id": str(execution.public_id),
        "checklist_version_public_id": str(version.public_id),
        "checklist_version_number": version.version_number,
    }
    if reviewer_conclusion_response is not None:
        payload["reviewer_conclusion_response_public_id"] = str(
            reviewer_conclusion_response.public_id
        )

    # Defence in depth: the literal above is the contract, and this makes a typo
    # or an unreviewed addition fail loudly rather than silently ship into a
    # regulatory artifact.
    unexpected = set(payload) - ALLOWED_APPROVAL_METADATA_FIELDS
    if unexpected:
        raise ApprovalMetadataError(
            f"approval_metadata fields not in the allow-list: {sorted(unexpected)}"
        )
    return payload


def populate_approval_metadata(*, execution, actor, approved_at) -> int:
    """Write the governed payload into every ``approval_metadata`` response.

    Returns the number of responses written. **Zero is a valid, normal result**:
    an execution whose checklist defines no ``approval_metadata`` question
    approves exactly as before. ``4D4-DEC-008`` does not make the question
    mandatory, and no normative source requires one.

    Must be called inside the approve transition's ``transaction.atomic()`` block
    -- the metadata and the approval status are one governed fact.
    """
    from .enums import AnswerType
    from .models import ChecklistResponse

    responses = list(
        ChecklistResponse.objects.select_for_update()
        .select_related("question")
        .filter(execution=execution, question__answer_type=AnswerType.APPROVAL_METADATA)
        .order_by("public_id")
    )
    if not responses:
        return 0

    payload = build_approval_metadata(
        execution=execution,
        actor=actor,
        approved_at=approved_at,
        reviewer_conclusion_response=_reviewer_conclusion_response(execution),
    )

    for response in responses:
        response.raw_value = payload
        response.entered_by = actor
        response.entered_at = approved_at
        # Same version discipline as every other governed server-derived write.
        response.version = response.version + 1
        response.save(
            update_fields=["raw_value", "entered_by", "entered_at", "version", "updated_at"]
        )
    return len(responses)
