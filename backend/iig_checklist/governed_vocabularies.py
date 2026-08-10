"""Milestone 4D-3 -- governed history and service-level vocabularies.

Database-free by construction: immutable frozensets plus import-time validation.

These two vocabularies are deliberately kept out of ``calculation_translation``
so the four categories can never blur (M4D3-RSN-011):

  ALLOWED_HISTORY_REASON_CODES  -> ChecklistResponseHistory.correction_reason
  ALLOWED_SERVICE_DETAIL_CODES  -> pre-calculation service rejections that never
                                   reach a CalculationOutcome at all

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-HST-005      history reason vocabulary
  - M4D3-RSN-011/012  four-vocabulary separation and service detail codes
"""

from __future__ import annotations

from .calculation_translation import (
    ALLOWED_INPUT_FAILURE_CODES,
    ALLOWED_REASON_CODES,
    ALLOWED_RESOLVER_DETAIL_CODES,
    VocabularyConfigurationError,
)

# ---------------------------------------------------------------------------
# M4D3-HST-005 -- history correction_reason vocabulary.
#
# Each code describes exactly one governed persisted-state transition and is
# never applied to the other (M4D3-HST-014/015).
# ---------------------------------------------------------------------------

HISTORY_REASON_APPLICABILITY_REEVALUATED = "APPLICABILITY_REEVALUATED"
HISTORY_REASON_COMPONENT_REBOUND = "COMPONENT_REBOUND"

ALLOWED_HISTORY_REASON_CODES: frozenset[str] = frozenset(
    {
        HISTORY_REASON_APPLICABILITY_REEVALUATED,
        HISTORY_REASON_COMPONENT_REBOUND,
    }
)


# ---------------------------------------------------------------------------
# M4D3-RSN-012 -- service-level rejection codes.
#
# These occur before any calculation begins, so they never produce a
# CalculationOutcome row and are surfaced only in the structured API error.
# ---------------------------------------------------------------------------

SERVICE_DETAIL_COMPONENT_REBINDING_NOT_ALLOWED = (
    "COMPONENT_REBINDING_NOT_ALLOWED_WHILE_NOT_APPLICABLE"
)

ALLOWED_SERVICE_DETAIL_CODES: frozenset[str] = frozenset(
    {SERVICE_DETAIL_COMPONENT_REBINDING_NOT_ALLOWED}
)


# ---------------------------------------------------------------------------
# M4D3-PST-002 -- the reserved server-owned marker prefix.
#
# A REVIEW_REQUIRED applicability outcome is persisted as
# ``REVIEW_REQUIRED:<ApplicabilityRule.reason_code>`` in
# ``ChecklistResponse.not_applicable_reason``. The marker is written only by a
# governed server-side service, so M4D3-APP-011 requires the governed
# response-update service to reject any client-supplied
# ``not_applicable_reason`` beginning with it -- for any response, rule-governed
# or not -- so client data can never impersonate a server determination.
#
# This is a persisted **value prefix**, deliberately not a member of any of the
# four closed code vocabularies above: it names a marker, not a reason code, and
# ``_validate()`` below is intentionally not extended to cover it.
# ---------------------------------------------------------------------------

RESERVED_REASON_PREFIX = "REVIEW_REQUIRED:"


def _validate() -> None:
    """Import-time separation guard across all four closed vocabularies."""
    named = (
        ("ALLOWED_REASON_CODES", ALLOWED_REASON_CODES),
        ("ALLOWED_RESOLVER_DETAIL_CODES", ALLOWED_RESOLVER_DETAIL_CODES),
        ("ALLOWED_HISTORY_REASON_CODES", ALLOWED_HISTORY_REASON_CODES),
        ("ALLOWED_SERVICE_DETAIL_CODES", ALLOWED_SERVICE_DETAIL_CODES),
        ("ALLOWED_INPUT_FAILURE_CODES", ALLOWED_INPUT_FAILURE_CODES),
    )

    for name, vocab in named:
        for code in vocab:
            if not isinstance(code, str) or not code:
                raise VocabularyConfigurationError(f"{name} contains an empty code")
            if code != code.upper() or not code.replace("_", "").isalnum():
                raise VocabularyConfigurationError(
                    f"{name} contains a non-canonical code: {code!r}"
                )

    # M4D3-RSN-011 -- history and service codes must not leak into the
    # CalculationOutcome reason vocabulary, in either direction.
    for name, vocab in named:
        if name in {"ALLOWED_HISTORY_REASON_CODES", "ALLOWED_SERVICE_DETAIL_CODES"}:
            leaked = vocab & ALLOWED_REASON_CODES
            if leaked:
                raise VocabularyConfigurationError(
                    f"{name} leaks into ALLOWED_REASON_CODES: {sorted(leaked)}"
                )
            leaked = vocab & ALLOWED_RESOLVER_DETAIL_CODES
            if leaked:
                raise VocabularyConfigurationError(
                    f"{name} leaks into ALLOWED_RESOLVER_DETAIL_CODES: {sorted(leaked)}"
                )
            leaked = vocab & ALLOWED_INPUT_FAILURE_CODES
            if leaked:
                raise VocabularyConfigurationError(
                    f"{name} leaks into ALLOWED_INPUT_FAILURE_CODES: {sorted(leaked)}"
                )

    if ALLOWED_HISTORY_REASON_CODES & ALLOWED_SERVICE_DETAIL_CODES:
        raise VocabularyConfigurationError("history and service-detail vocabularies overlap")


_validate()
