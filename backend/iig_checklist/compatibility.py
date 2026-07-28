"""Single central registry for answer-type x data-source-classification
compatibility (see docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §3d-i).

Consulted by both the serializer and ChecklistQuestion.clean() -- never
scattered ad hoc checks. Any (answer_type, data_source_classification)
pair not present in ALLOWED_MATRIX is PROHIBITED; the matrix is
exhaustive and closed.
"""

from .enums import AnswerType as AT
from .enums import DataSourceClassification as DSC

# {answer_type: {allowed classifications}}
ALLOWED_MATRIX: dict[str, frozenset[str]] = {
    AT.SHORT_TEXT: frozenset(
        {DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.REVIEWER_CONFIRMED, DSC.EVIDENCE_DERIVED}
    ),
    AT.LONG_NARRATIVE: frozenset(
        {DSC.USER_REQUIRED, DSC.REVIEWER_CONFIRMED, DSC.EVIDENCE_DERIVED}
    ),
    AT.INTEGER: frozenset({DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.EVIDENCE_DERIVED}),
    AT.DECIMAL: frozenset({DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.EVIDENCE_DERIVED}),
    AT.QUANTITY_WITH_UNIT: frozenset(
        {DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.EVIDENCE_DERIVED}
    ),
    AT.PERCENTAGE: frozenset({DSC.SYSTEM_CALCULATED}),
    AT.DATE: frozenset({DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.EVIDENCE_DERIVED}),
    AT.YES_NO: frozenset({DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.REVIEWER_CONFIRMED}),
    AT.YES_NO_NOT_APPLICABLE: frozenset(
        {DSC.FDA_DERIVED_DEFAULT, DSC.SYSTEM_CALCULATED, DSC.REVIEWER_CONFIRMED}
    ),
    AT.SINGLE_SELECT: frozenset(
        {DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.REVIEWER_CONFIRMED}
    ),
    AT.MULTI_SELECT: frozenset(
        {DSC.FDA_DERIVED_DEFAULT, DSC.USER_REQUIRED, DSC.REVIEWER_CONFIRMED}
    ),
    AT.FDA_RECORD_REFERENCE: frozenset({DSC.FDA_DERIVED_DEFAULT, DSC.REVIEWER_CONFIRMED}),
    AT.FORMULATION_COMPONENT_REFERENCE: frozenset(
        {DSC.USER_REQUIRED, DSC.REVIEWER_CONFIRMED}
    ),
    AT.EVIDENCE_ATTACHMENT_REFERENCE: frozenset({DSC.USER_REQUIRED, DSC.EVIDENCE_DERIVED}),
    AT.CALCULATED_VALUE: frozenset({DSC.SYSTEM_CALCULATED}),
    AT.CALCULATED_STATUS: frozenset({DSC.SYSTEM_CALCULATED}),
    AT.REVIEWER_CONCLUSION: frozenset({DSC.REVIEWER_CONFIRMED}),
    AT.APPROVAL_METADATA: frozenset({DSC.REVIEWER_CONFIRMED}),
}


def is_allowed(answer_type: str, data_source_classification: str) -> bool:
    return data_source_classification in ALLOWED_MATRIX.get(answer_type, frozenset())
