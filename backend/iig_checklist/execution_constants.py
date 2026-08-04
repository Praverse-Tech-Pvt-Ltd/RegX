"""Payload-limit constants for 4D-2 execution and response models.

Authoritative source for all length and size limits in the execution
domain. Serializers, model clean() methods, and service functions all
import from here -- never hardcode a limit elsewhere.
"""

MAX_RAW_VALUE_BYTES = 16_384
MAX_RETURN_REASON_CHARS = 2_000
MAX_REVIEWER_CONCLUSION_CHARS = 4_000  # Both ChecklistExecution.reviewer_conclusion_note
#                                        and reviewer_conclusion raw_value.value.
#                                        NOT MAX_FREE_TEXT_CHARS (DR-2-29).
MAX_FREE_TEXT_CHARS = 4_000  # short_text and long_narrative only.
MAX_NOT_APPLICABLE_REASON_CHARS = 200
MAX_SELECT_OPTIONS = 64

# Closed set of fda_record_reference record_type values (DR-2-17, §24) --
# each maps to a real fda_data model carrying a public_id.
FDA_RECORD_TYPES = frozenset(
    {
        "orange_book_application",
        "orange_book_product",
        "iid_ingredient",
        "iid_precedent_record",
    }
)
