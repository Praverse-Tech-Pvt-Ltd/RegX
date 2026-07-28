import itertools

import pytest

from iig_checklist.compatibility import ALLOWED_MATRIX, is_allowed
from iig_checklist.enums import AnswerType, DataSourceClassification


class TestCompatibilityMatrix:
    @pytest.mark.parametrize(
        "answer_type,classification",
        list(itertools.product(list(AnswerType.values), list(DataSourceClassification.values))),
    )
    def test_every_pair_is_classified(self, answer_type, classification):
        # Every pair must return a definite boolean -- no KeyError, no
        # silent default.
        result = is_allowed(answer_type, classification)
        assert isinstance(result, bool)

    def test_approval_metadata_only_reviewer_confirmed(self):
        for classification in DataSourceClassification.values:
            expected = classification == DataSourceClassification.REVIEWER_CONFIRMED
            assert is_allowed(AnswerType.APPROVAL_METADATA, classification) is expected

    def test_reviewer_conclusion_only_reviewer_confirmed(self):
        for classification in DataSourceClassification.values:
            expected = classification == DataSourceClassification.REVIEWER_CONFIRMED
            assert is_allowed(AnswerType.REVIEWER_CONCLUSION, classification) is expected

    def test_calculated_value_only_system_calculated(self):
        for classification in DataSourceClassification.values:
            expected = classification == DataSourceClassification.SYSTEM_CALCULATED
            assert is_allowed(AnswerType.CALCULATED_VALUE, classification) is expected

    def test_calculated_status_only_system_calculated(self):
        for classification in DataSourceClassification.values:
            expected = classification == DataSourceClassification.SYSTEM_CALCULATED
            assert is_allowed(AnswerType.CALCULATED_STATUS, classification) is expected

    def test_user_required_cannot_be_approval_or_calculated(self):
        assert not is_allowed(AnswerType.APPROVAL_METADATA, DataSourceClassification.USER_REQUIRED)
        assert not is_allowed(AnswerType.CALCULATED_VALUE, DataSourceClassification.USER_REQUIRED)
        assert not is_allowed(AnswerType.CALCULATED_STATUS, DataSourceClassification.USER_REQUIRED)

    def test_matrix_is_exhaustive_no_missing_answer_type(self):
        assert set(ALLOWED_MATRIX.keys()) == set(AnswerType.values)
