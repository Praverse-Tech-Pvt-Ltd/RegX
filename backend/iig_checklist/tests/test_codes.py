import pytest

from iig_checklist.codes import CodeValidationError, normalize_code


class TestNormalizeCode:
    @pytest.mark.parametrize(
        "raw",
        ["iig oral", "IIG_ORAL", " iig_oral ", "iig_oral", "  iig   oral  "],
    )
    def test_equivalent_variants_normalize_identically(self, raw):
        assert normalize_code(raw) == "IIG_ORAL"

    def test_blank_rejected(self):
        with pytest.raises(CodeValidationError) as exc_info:
            normalize_code("   ")
        assert exc_info.value.error_code == "CODE_BLANK"

    def test_invalid_characters_rejected(self):
        with pytest.raises(CodeValidationError) as exc_info:
            normalize_code("iig.oral#1")
        assert exc_info.value.error_code == "CODE_INVALID_CHARACTERS"

    def test_leading_separator_rejected(self):
        with pytest.raises(CodeValidationError) as exc_info:
            normalize_code("_iig")
        assert exc_info.value.error_code == "CODE_INVALID_CHARACTERS"

    def test_too_long_rejected(self):
        with pytest.raises(CodeValidationError) as exc_info:
            normalize_code("A" * 101)
        assert exc_info.value.error_code == "CODE_TOO_LONG"

    def test_max_length_accepted(self):
        assert normalize_code("A" * 100) == "A" * 100
