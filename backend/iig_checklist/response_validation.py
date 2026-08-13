"""Canonical raw_value shape validation for all 18 AnswerType values.

Authoritative source: docs/MILESTONE_4D_2_IMPLEMENTATION_SPEC.md §23/§24
(DR-2-17). Every answer_type has an exact accepted shape; anything else
raises InvalidRawValueShape, which the caller (ChecklistResponseUpdateSerializer)
turns into a structured 400 with error_code="invalid_raw_value_shape" before
any DB write.

isinstance(val, bool) is checked before isinstance(val, int) everywhere a
JSON integer is expected -- Python's bool is an int subclass (DR-2-24).
"""

import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from .enums import AnswerType
from .execution_constants import FDA_RECORD_TYPES, MAX_FREE_TEXT_CHARS, MAX_SELECT_OPTIONS

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DECIMAL_STRING_RE_CHARS = frozenset("0123456789.-")


class InvalidRawValueShape(Exception):
    """Raised when raw_value does not match its answer_type's canonical shape."""


def _fail(detail):
    raise InvalidRawValueShape(detail)


def _require_exact_keys(value, keys, detail):
    if not isinstance(value, dict) or set(value.keys()) != set(keys):
        _fail(detail)


def _require_non_empty_string(value, detail):
    if not isinstance(value, str) or not value.strip():
        _fail(detail)


def _require_decimal_string(value, detail):
    if not isinstance(value, str) or not value or set(value) - _DECIMAL_STRING_RE_CHARS:
        _fail(detail)
    try:
        Decimal(value)
    except InvalidOperation:
        _fail(detail)


def _require_uuid_string(value, detail):
    if not isinstance(value, str):
        _fail(detail)
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        _fail(detail)


def _validate_short_text(value):
    _require_exact_keys(value, {"value"}, "short_text requires {'value': <string>}.")
    _require_non_empty_string(value["value"], "short_text value must be a non-empty string.")
    if len(value["value"]) > MAX_FREE_TEXT_CHARS:
        _fail("short_text value exceeds MAX_FREE_TEXT_CHARS.")


def _validate_long_narrative(value):
    _require_exact_keys(value, {"value"}, "long_narrative requires {'value': <string>}.")
    _require_non_empty_string(value["value"], "long_narrative value must be a non-empty string.")
    if len(value["value"]) > MAX_FREE_TEXT_CHARS:
        _fail("long_narrative value exceeds MAX_FREE_TEXT_CHARS.")


def _validate_integer(value):
    _require_exact_keys(value, {"value"}, "integer requires {'value': <int>}.")
    v = value["value"]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail("integer value must be a JSON integer (bool is not accepted).")


def _validate_decimal(value):
    _require_exact_keys(value, {"value"}, "decimal requires {'value': <decimal string>}.")
    _require_decimal_string(value["value"], "decimal value must be a decimal string.")


def _validate_quantity_with_unit(value, *, question):
    _require_exact_keys(value, {"value", "unit"}, "quantity_with_unit requires {'value', 'unit'}.")
    _require_decimal_string(value["value"], "quantity_with_unit value must be a decimal string.")
    unit = value["unit"]
    allowed = list(question.allowed_units) if question is not None else []
    if not isinstance(unit, str) or not unit or unit not in allowed:
        _fail("quantity_with_unit unit is not in the question's allowed_units.")


def _validate_percentage(value):
    _require_exact_keys(value, {"value"}, "percentage requires {'value': <decimal string>}.")
    _require_decimal_string(value["value"], "percentage value must be a decimal string.")
    if not (Decimal("0") <= Decimal(value["value"]) <= Decimal("100")):
        _fail("percentage value must be between 0 and 100 inclusive.")


def _validate_date(value):
    _require_exact_keys(value, {"value"}, "date requires {'value': <ISO 8601 date string>}.")
    v = value["value"]
    if not isinstance(v, str):
        _fail("date value must be a string.")
    if not _DATE_RE.match(v):
        _fail("date value must be an ISO 8601 date string in YYYY-MM-DD format.")
    try:
        date.fromisoformat(v)
    except ValueError:
        _fail("date value must be a valid calendar date in YYYY-MM-DD format.")


def _validate_yes_no(value):
    _require_exact_keys(value, {"value"}, "yes_no requires {'value': <boolean>}.")
    if not isinstance(value["value"], bool):
        _fail("yes_no value must be a JSON boolean.")


def _validate_yes_no_na(value):
    _require_exact_keys(
        value, {"value"}, "yes_no_na requires {'value': 'yes'|'no'|'not_applicable'}."
    )
    v = value["value"]
    if isinstance(v, bool) or v not in {"yes", "no", "not_applicable"}:
        _fail("yes_no_na value must be one of 'yes', 'no', 'not_applicable'.")


def _question_option_codes(question):
    """Returns the set of valid option *machine values*, or None if the question
    declares no closed option list.

    `5A-DEC-002` moved the vocabulary from a bare code list to governed
    value/label objects, so the shape is read through the single shared parser
    in `question_options` rather than unpacked here. Answer validation stays
    deliberately label-blind: a response is checked against the stable value,
    never the wording, so re-labelling an option can never invalidate an answer
    already recorded against it.
    """
    if question is None:
        return None
    from .question_options import option_values

    return option_values(question.validation_rule or {})


def _validate_single_select(value, *, question):
    _require_exact_keys(value, {"option"}, "single_select requires {'option': <code>}.")
    code = value["option"]
    _require_non_empty_string(code, "single_select option must be a non-empty string.")
    allowed = _question_option_codes(question)
    if allowed is not None and code not in allowed:
        _fail("single_select option is not a valid option code for this question.")


def _validate_multi_select(value, *, question):
    _require_exact_keys(value, {"options"}, "multi_select requires {'options': [<codes>]}.")
    codes = value["options"]
    if not isinstance(codes, list) or not codes:
        _fail("multi_select options must be a non-empty list.")
    if len(codes) > MAX_SELECT_OPTIONS:
        _fail("multi_select options exceeds MAX_SELECT_OPTIONS.")
    if not all(isinstance(c, str) and c for c in codes):
        _fail("multi_select options must all be non-empty strings.")
    if len(set(codes)) != len(codes):
        _fail("multi_select options must not contain duplicates.")
    if codes != sorted(codes):
        _fail("multi_select options must be sorted ascending.")
    allowed = _question_option_codes(question)
    if allowed is not None and not set(codes) <= allowed:
        _fail("multi_select options contain codes not valid for this question.")


_FDA_RECORD_MODEL_LOOKUP = {
    "orange_book_application": "OrangeBookApplication",
    "orange_book_product": "OrangeBookProduct",
    "iid_ingredient": "IIDIngredient",
    "iid_precedent_record": "IIDPrecedentRecord",
}


def _validate_fda_record_reference(value):
    _require_exact_keys(
        value,
        {"public_id", "record_type"},
        "fda_record_reference requires {'public_id', 'record_type'}.",
    )
    record_type = value["record_type"]
    if record_type not in FDA_RECORD_TYPES:
        _fail(f"fda_record_reference record_type must be one of {sorted(FDA_RECORD_TYPES)}.")
    _require_uuid_string(value["public_id"], "fda_record_reference public_id must be a valid UUID.")

    from fda_data import models as fda_models

    model = getattr(fda_models, _FDA_RECORD_MODEL_LOOKUP[record_type])
    if not model.objects.filter(public_id=value["public_id"]).exists():
        _fail("fda_record_reference public_id does not match a record of the given record_type.")


def _validate_formulation_component_reference(value, *, execution):
    _require_exact_keys(
        value, {"public_id"}, "formulation_component_reference requires {'public_id'}."
    )
    _require_uuid_string(
        value["public_id"], "formulation_component_reference public_id must be a valid UUID."
    )

    from formulations.models import FormulationComponent

    exists = FormulationComponent.objects.filter(
        formulation_version=execution.formulation_version if execution else None,
        public_id=value["public_id"],
    ).exists()
    if not exists:
        _fail(
            "formulation_component_reference public_id does not belong to "
            "this execution's FormulationVersion."
        )


def _validate_attachment_reference(value, *, tenant):
    _require_exact_keys(
        value,
        {"document_version_public_id"},
        "attachment_reference requires {'document_version_public_id'}.",
    )
    _require_uuid_string(
        value["document_version_public_id"],
        "attachment_reference document_version_public_id must be a valid UUID.",
    )

    from documents.models import DocumentVersion

    exists = DocumentVersion.objects.filter(
        document__tenant=tenant,
        public_id=value["document_version_public_id"],
    ).exists()
    if not exists:
        _fail("attachment_reference document_version_public_id not found for this tenant.")


# answer_type values whose raw_value is never accepted from a client.
_CLIENT_REJECTED_TYPES = frozenset(
    {
        AnswerType.CALCULATED_VALUE,
        AnswerType.CALCULATED_STATUS,
        AnswerType.APPROVAL_METADATA,
    }
)

_SIMPLE_VALIDATORS = {
    AnswerType.SHORT_TEXT: lambda v, **_: _validate_short_text(v),
    AnswerType.LONG_NARRATIVE: lambda v, **_: _validate_long_narrative(v),
    AnswerType.INTEGER: lambda v, **_: _validate_integer(v),
    AnswerType.DECIMAL: lambda v, **_: _validate_decimal(v),
    AnswerType.QUANTITY_WITH_UNIT: lambda v, *, question=None, **_: _validate_quantity_with_unit(
        v, question=question
    ),
    AnswerType.PERCENTAGE: lambda v, **_: _validate_percentage(v),
    AnswerType.DATE: lambda v, **_: _validate_date(v),
    AnswerType.YES_NO: lambda v, **_: _validate_yes_no(v),
    AnswerType.YES_NO_NOT_APPLICABLE: lambda v, **_: _validate_yes_no_na(v),
    AnswerType.SINGLE_SELECT: lambda v, *, question=None, **_: _validate_single_select(
        v, question=question
    ),
    AnswerType.MULTI_SELECT: lambda v, *, question=None, **_: _validate_multi_select(
        v, question=question
    ),
    AnswerType.FDA_RECORD_REFERENCE: lambda v, **_: _validate_fda_record_reference(v),
    AnswerType.FORMULATION_COMPONENT_REFERENCE: (
        lambda v, *, execution=None, **_: _validate_formulation_component_reference(
            v, execution=execution
        )
    ),
    AnswerType.EVIDENCE_ATTACHMENT_REFERENCE: (
        lambda v, *, tenant=None, **_: _validate_attachment_reference(v, tenant=tenant)
    ),
}


def validate_raw_value_shape(answer_type, raw_value, *, question=None, execution=None, tenant=None):
    """Validates raw_value against the canonical shape for answer_type.

    raw_value=None is always accepted here -- the null/is_not_applicable
    combination is enforced separately by ChecklistResponse.clean().
    reviewer_conclusion is out of scope: it is only ever submitted through
    ReviewerConclusionSerializer / the dedicated endpoint, never through
    this path.
    """
    if raw_value is None:
        return

    if answer_type in _CLIENT_REJECTED_TYPES:
        _fail(f"{answer_type} does not accept a client-supplied raw_value.")

    if answer_type == AnswerType.REVIEWER_CONCLUSION:
        _fail(
            "reviewer_conclusion raw_value must be submitted via the reviewer-conclusion endpoint."
        )

    validator = _SIMPLE_VALIDATORS.get(answer_type)
    if validator is None:
        _fail(f"Unknown answer_type: {answer_type!r}")
    validator(raw_value, question=question, execution=execution, tenant=tenant)
