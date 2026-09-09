"""Gap analysis calculation tests.

The calculation is pure -- it takes an execution and returns a dict -- so these
exercise `analyse_execution` directly rather than through HTTP. What matters is
the arithmetic and, more importantly, the cases where a naive implementation
reports a reassuring number that is wrong.
"""

import pytest

from iig_checklist.gap_analysis import _normalised, _score


class TestNormalisation:
    """`raw_value` is a JSONField, so the same answer arrives in several shapes
    depending on which client wrote it. All of them must reduce to one token."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (True, "yes"),
            (False, "no"),
            ("yes", "yes"),
            ("Yes", "yes"),
            ("YES", "yes"),
            ("y", "yes"),
            ("true", "yes"),
            ("no", "no"),
            ("No", "no"),
            ("n", "no"),
            ("false", "no"),
            ({"value": "no"}, "no"),
            ({"value": True}, "yes"),
            ({"value": None}, None),
            (None, None),
            ("", None),
            ("   ", None),
        ],
    )
    def test_reduces_every_shape_to_one_token(self, raw, expected):
        assert _normalised(raw) == expected

    def test_a_free_text_answer_is_preserved_not_coerced(self):
        """A non-yes/no answer must not be forced into the yes/no vocabulary."""
        assert _normalised("Partially compliant") == "partially compliant"


class TestScore:
    def test_score_is_the_share_of_answered_questions_that_are_not_gaps(self):
        assert _score(answered=10, gaps=0) == 100.0
        assert _score(answered=10, gaps=5) == 50.0
        assert _score(answered=4, gaps=1) == 75.0

    def test_nothing_answered_scores_none_not_one_hundred(self):
        """The trap: (0 - 0) / 0 guarded to 100 makes an untouched checklist look
        complete. It has no score at all."""
        assert _score(answered=0, gaps=0) is None

    def test_every_answer_a_gap_scores_zero(self):
        assert _score(answered=3, gaps=3) == 0.0

    def test_rounds_to_two_places(self):
        assert _score(answered=3, gaps=1) == 66.67
