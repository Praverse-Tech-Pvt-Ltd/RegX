"""Cross-language pin for the checklist response `raw_value` wire contract.

The frontend response editor serialises answers in
`frontend/src/app/iig-checklists/executions/[executionPublicId]/ChecklistResponses.tsx`
(`toPayloadValue`). Nothing in either suite previously compared the two: the
frontend tests mocked past the wire and asserted only that the API helper had
been *called*, and the backend tests used shapes written by hand in Python. The
result was a merged editor that emitted bare scalars for every answer type and
could not save at all against a real backend.

This module is the missing half. Every payload below is exactly what the
frontend now puts on the wire, asserted against the real
`validate_raw_value_shape()`. If either side drifts, this fails.

Database-free for the eight types the editor supports -- none of them touches a
model. Reference types are covered by the existing response-validation suite.
"""

from __future__ import annotations

import pytest

from iig_checklist.enums import AnswerType
from iig_checklist.response_validation import InvalidRawValueShape, validate_raw_value_shape

# (answer_type, payload emitted by the frontend for a representative edit)
#
# Kept literal rather than generated: the point is to state the agreed wire
# shape in one readable place, so a reviewer can compare it to the TypeScript
# without running anything.
FRONTEND_PAYLOADS = [
    (AnswerType.SHORT_TEXT, {"value": "abc"}),
    (AnswerType.LONG_NARRATIVE, {"value": "a longer answer"}),
    (AnswerType.INTEGER, {"value": 12}),
    (AnswerType.DECIMAL, {"value": "12.5000000000"}),
    (AnswerType.PERCENTAGE, {"value": "99.9"}),
    (AnswerType.DATE, {"value": "2026-08-11"}),
    (AnswerType.YES_NO, {"value": True}),
    (AnswerType.YES_NO, {"value": False}),
    (AnswerType.YES_NO_NOT_APPLICABLE, {"value": "yes"}),
    (AnswerType.YES_NO_NOT_APPLICABLE, {"value": "no"}),
    (AnswerType.YES_NO_NOT_APPLICABLE, {"value": "not_applicable"}),
]


@pytest.mark.parametrize(("answer_type", "payload"), FRONTEND_PAYLOADS)
def test_frontend_payload_is_accepted_by_backend_validation(answer_type, payload):
    """Every shape the editor emits must pass the governed validator."""
    validate_raw_value_shape(answer_type, payload)


def test_an_empty_edit_clears_the_answer():
    """The editor sends a bare null, not an envelope, to clear an answer."""
    validate_raw_value_shape(AnswerType.SHORT_TEXT, None)


# ---------------------------------------------------------------------------
# The shapes the editor used to emit, pinned as rejected.
#
# These are the regression: each is what the merged editor actually sent before
# the fix. Asserting they fail is what stops a future refactor quietly
# reintroducing bare scalars.
# ---------------------------------------------------------------------------

PRE_FIX_PAYLOADS = [
    (AnswerType.SHORT_TEXT, "abc"),
    (AnswerType.LONG_NARRATIVE, "a longer answer"),
    (AnswerType.INTEGER, 12),
    (AnswerType.DECIMAL, "12.5000000000"),
    (AnswerType.PERCENTAGE, "99.9"),
    (AnswerType.DATE, "2026-08-11"),
    (AnswerType.YES_NO, True),
    # The old helper mapped yes_no_na through booleans, which is doubly wrong:
    # unenveloped, and the wrong inner type for a closed string vocabulary.
    (AnswerType.YES_NO_NOT_APPLICABLE, True),
    (AnswerType.YES_NO_NOT_APPLICABLE, False),
]


@pytest.mark.parametrize(("answer_type", "payload"), PRE_FIX_PAYLOADS)
def test_bare_scalar_payloads_are_rejected(answer_type, payload):
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(answer_type, payload)


def test_yes_no_na_does_not_accept_a_boolean_even_when_enveloped():
    """The vocabulary is a string set; a boolean is refused explicitly."""
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(AnswerType.YES_NO_NOT_APPLICABLE, {"value": True})


def test_yes_no_does_not_accept_the_string_vocabulary():
    """The mirror case: yes_no is a boolean, not 'yes'/'no'.

    Worth pinning because the two types read as near-synonyms but take different
    inner types, which is exactly the kind of detail a client gets wrong.
    """
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(AnswerType.YES_NO, {"value": "yes"})


def test_integer_does_not_accept_a_boolean():
    """bool is an int subclass in Python; the validator refuses it explicitly."""
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(AnswerType.INTEGER, {"value": True})


def test_decimal_does_not_accept_a_json_number():
    """Regulated figures travel as strings so no precision is lost to a float."""
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(AnswerType.DECIMAL, {"value": 12.5})


# ---------------------------------------------------------------------------
# Types the editor deliberately does not offer a control for.
#
# Each needs a shape a single value control cannot produce. The editor renders
# them read-only; these assertions record *why*, so the exclusion is a documented
# contract rather than an oversight.
# ---------------------------------------------------------------------------

UNSUPPORTED_SHAPES = [
    (AnswerType.QUANTITY_WITH_UNIT, {"value": "1.0"}),  # also requires "unit"
    (AnswerType.SINGLE_SELECT, {"value": "opt"}),  # requires {"option": ...}
    (AnswerType.MULTI_SELECT, {"value": ["a"]}),  # requires {"options": [...]}
    (AnswerType.FDA_RECORD_REFERENCE, {"value": "x"}),  # requires public_id + record_type
    (AnswerType.FORMULATION_COMPONENT_REFERENCE, {"value": "x"}),  # requires public_id
    (AnswerType.EVIDENCE_ATTACHMENT_REFERENCE, {"value": "x"}),  # requires doc version id
]


@pytest.mark.parametrize(("answer_type", "payload"), UNSUPPORTED_SHAPES)
def test_unsupported_types_would_reject_a_plain_value_envelope(answer_type, payload):
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(answer_type, payload)


@pytest.mark.parametrize(
    "answer_type",
    [AnswerType.CALCULATED_VALUE, AnswerType.CALCULATED_STATUS, AnswerType.APPROVAL_METADATA],
)
def test_server_owned_types_reject_any_client_raw_value(answer_type):
    with pytest.raises(InvalidRawValueShape):
        validate_raw_value_shape(answer_type, {"value": "anything"})


# ---------------------------------------------------------------------------
# The per-response reviewer-conclusion endpoint.
#
# A `reviewer_conclusion` answer never travels the ordinary PATCH -- the check
# above records that refusal -- so its wire contract is owned by
# `ReviewerConclusionSerializer`, not `validate_raw_value_shape()`. These pin the
# payload the frontend client emits
# (`iigChecklists.executions.responses.reviewerConclusion`) against that real
# serializer, the same cross-language guarantee the block above gives the editor.
#
# Database-free: the serializer decides shape before any model is touched.
# ---------------------------------------------------------------------------


def _conclusion_errors(payload):
    from iig_checklist.serializers import ReviewerConclusionSerializer

    serializer = ReviewerConclusionSerializer(data=payload)
    return {} if serializer.is_valid() else serializer.errors


def test_frontend_first_entry_payload_is_accepted():
    # Exactly what the client sends on first entry: no correction_reason, and
    # expected_version as a JSON integer taken from the loaded response.
    assert _conclusion_errors({"raw_value": {"value": "Reviewed; acceptable."},
                               "expected_version": 3}) == {}


def test_frontend_amendment_payload_is_accepted():
    assert _conclusion_errors(
        {
            "raw_value": {"value": "Revised conclusion."},
            "expected_version": 7,
            "correction_reason": "Cited the wrong section.",
        }
    ) == {}


def test_a_meaningful_one_character_conclusion_is_accepted():
    # Section 13 specifies no numeric minimum, so none exists. This is the guard
    # against a 3- or 10-character rule being invented later on either side.
    assert _conclusion_errors({"raw_value": {"value": "Y"}, "expected_version": 1}) == {}


@pytest.mark.parametrize("text", ["", "   ", "\t\n "])
def test_empty_and_whitespace_only_conclusions_are_refused(text):
    # Meaningful non-empty is the enforced requirement on both sides.
    errors = _conclusion_errors({"raw_value": {"value": text}, "expected_version": 1})
    assert errors, "whitespace-only must not be accepted as a conclusion"


def test_the_existing_maximum_is_still_enforced():
    from iig_checklist.execution_constants import MAX_REVIEWER_CONCLUSION_CHARS

    # The frontend control caps at exactly this number; the boundary is valid.
    at_limit = "x" * MAX_REVIEWER_CONCLUSION_CHARS
    assert _conclusion_errors({"raw_value": {"value": at_limit}, "expected_version": 1}) == {}
    over = "x" * (MAX_REVIEWER_CONCLUSION_CHARS + 1)
    assert _conclusion_errors({"raw_value": {"value": over}, "expected_version": 1})


@pytest.mark.parametrize(
    "field",
    [
        "entered_by",
        "entered_at",
        "confirmed_by",
        "confirmed_at",
        "reviewer",
        "version",
        "history",
        "data_source_type_snapshot",
        "override_reason",
    ],
)
def test_server_controlled_fields_are_refused_if_a_client_ever_sends_one(field):
    # The frontend sends none of these; this is what makes that a contract
    # rather than a convention. All of it is derived from the authenticated
    # actor server-side.
    errors = _conclusion_errors(
        {"raw_value": {"value": "ok"}, "expected_version": 1, field: "anything"}
    )
    assert errors, f"{field} must be refused as an unknown field"
