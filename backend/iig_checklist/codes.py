"""One authoritative code-normalization function, applied to every
`code` field in this app (ChecklistDefinition, ChecklistSection,
ChecklistQuestion, ApplicabilityRule) -- see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §3f.

Normalization happens before storage, so uniqueness constraints are
plain column-level constraints against already-normalized values -- no
reliance on database collation.
"""

import re

CODE_MAX_LENGTH = 100
_CODE_GRAMMAR = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")
_WHITESPACE_RUN = re.compile(r"\s+")


class CodeValidationError(Exception):
    """Raised with a deterministic, machine-readable error_code."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def normalize_code(raw: str) -> str:
    """Trim -> collapse internal whitespace to '_' -> uppercase -> validate.

    Raises CodeValidationError with one of: CODE_BLANK,
    CODE_INVALID_CHARACTERS, CODE_TOO_LONG. Never silently rewrites an
    unrecognized character -- an invalid code is a hard rejection.
    """
    if raw is None:
        raw = ""
    stripped = raw.strip()
    collapsed = _WHITESPACE_RUN.sub("_", stripped)
    normalized = collapsed.upper()

    if not normalized:
        raise CodeValidationError("CODE_BLANK", "Code must not be blank.")
    if len(normalized) > CODE_MAX_LENGTH:
        raise CodeValidationError(
            "CODE_TOO_LONG", f"Code must be at most {CODE_MAX_LENGTH} characters."
        )
    if not _CODE_GRAMMAR.match(normalized):
        raise CodeValidationError(
            "CODE_INVALID_CHARACTERS",
            "Code may only contain A-Z, 0-9, '_' and '-', and must start "
            "with an alphanumeric character.",
        )
    return normalized
