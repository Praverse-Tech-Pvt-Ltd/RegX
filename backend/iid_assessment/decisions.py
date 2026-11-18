"""
Deterministic precedent decision service.

This module produces exactly one of a fixed, closed set of statuses. None
of them may ever be interpreted as an automatic safety determination or a
regulatory approval -- that phrase is enforced structurally: SAFE,
FDA APPROVED, AUTOMATICALLY ACCEPTABLE, and REGULATORILY CLEARED do not
exist anywhere in this module's vocabulary, and _ALLOWED_STATUSES is a
closed set checked by every caller/test.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from .matching import MatchStatus


class PrecedentDecisionStatus:
    PASS_WITH_IID_PRECEDENT = "PASS_WITH_IID_PRECEDENT"  # noqa: S105 -- status code, not a password
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EXCEEDS_IID_PRECEDENT = "EXCEEDS_IID_PRECEDENT"
    NO_MATCH = "NO_MATCH"
    NOT_COMPARABLE = "NOT_COMPARABLE"


_ALLOWED_STATUSES = frozenset(
    {
        PrecedentDecisionStatus.PASS_WITH_IID_PRECEDENT,
        PrecedentDecisionStatus.REVIEW_REQUIRED,
        PrecedentDecisionStatus.EXCEEDS_IID_PRECEDENT,
        PrecedentDecisionStatus.NO_MATCH,
        PrecedentDecisionStatus.NOT_COMPARABLE,
    }
)

_FORBIDDEN_STATUS_WORDS = (
    "SAFE",
    "FDA APPROVED",
    "AUTOMATICALLY ACCEPTABLE",
    "REGULATORILY CLEARED",
)

REQUIRED_PRECEDENT_NOTE = (
    "Within selected FDA IID precedent. This is not an automatic safety "
    "determination or regulatory approval."
)


#: Why the selected IID record has no usable potency, in plain words.
_POTENCY_NOTES = {
    "NO_NUMERIC_LIMIT": (
        "The selected IID record has no numeric limit (for example 'NA' or 'ADJ PH'), so "
        "there is nothing to compare against; a reviewer must decide."
    ),
    "IID_UNIT_MISSING": (
        "The selected IID record's unit (for example 'mg/mg') has no agreed meaning in REGX "
        "yet, so it cannot be compared; a reviewer must decide."
    ),
    "DAILY_EXPOSURE_ONLY_NEEDS_Q8": (
        "The selected IID record gives only a maximum daily exposure, not an amount per "
        "unit; comparing per day is not supported yet, so a reviewer must decide."
    ),
}


@dataclass(frozen=True)
class PrecedentDecision:
    status: str
    note: str
    escalation_required: bool = False
    reason_codes: list = field(default_factory=list)

    def __post_init__(self):
        if self.status not in _ALLOWED_STATUSES:
            raise ValueError(f"Illegal precedent decision status: {self.status!r}")
        upper_note = self.note.upper()
        for forbidden in _FORBIDDEN_STATUS_WORDS:
            if forbidden in upper_note and "NOT AN AUTOMATIC" not in upper_note:
                raise ValueError(
                    f"Precedent decision note must never assert '{forbidden}' as a conclusion."
                )


def decide(
    *,
    match_status: str,
    unit_conversion_ok: bool,
    proposed_amount_per_unit: Decimal | None,
    selected_potency_amount: Decimal | None,
    proposed_daily_exposure: Decimal | None,
    selected_mde: Decimal | None,
    mde_available: bool,
    multiple_candidates: bool = False,
    source_release_superseded: bool = False,
    density_or_basis_required: bool = False,
    cannot_compare_reason: str | None = None,
    explanation: str | None = None,
    potency_reason: str | None = None,
) -> PrecedentDecision:
    """Combines a matching-engine result and (if matched) the calculation
    results into a final precedent decision. This function never itself
    performs unit conversion or the underlying calculations -- callers
    must have already run those and pass in their outcomes.

    `explanation` (from `iid_assessment.reasons`) replaces the generic sentence
    when the match found nothing to compare against; the status is unchanged.
    `potency_reason` is the match engine's reason for an unusable IID value."""
    reason_codes: list[str] = []

    if match_status == MatchStatus.NO_MATCHING_IID_PRECEDENT:
        return PrecedentDecision(
            status=PrecedentDecisionStatus.NO_MATCH,
            note=explanation
            or "No exact ingredient/route/dosage-form IID precedent record exists.",
        )

    if match_status in (MatchStatus.ROUTE_MISMATCH, MatchStatus.DOSAGE_FORM_MISMATCH):
        return PrecedentDecision(
            status=PrecedentDecisionStatus.NOT_COMPARABLE,
            note=explanation
            or (
                "The route entered is not a recognised controlled route."
                if match_status == MatchStatus.ROUTE_MISMATCH
                else "The dosage form entered is not a recognised controlled dosage form."
            ),
            reason_codes=[match_status],
        )

    if cannot_compare_reason is not None:
        # From the like-for-like comparison service (iid_assessment.comparison):
        # one specific reason, e.g. different basis, or daily exposure only (Q8).
        from .comparison import REASON_TEXT

        return PrecedentDecision(
            status=PrecedentDecisionStatus.NOT_COMPARABLE,
            note=REASON_TEXT.get(cannot_compare_reason, "cannot compare"),
            reason_codes=[cannot_compare_reason],
        )

    if not unit_conversion_ok or density_or_basis_required:
        return PrecedentDecision(
            status=PrecedentDecisionStatus.NOT_COMPARABLE,
            note="Unit or basis could not be reconciled between the proposed formulation "
            "and the selected IID record.",
            reason_codes=["UNIT_OR_BASIS_UNRECONCILED"],
        )

    if match_status == MatchStatus.MULTIPLE_EXACT_MATCHES or multiple_candidates:
        return PrecedentDecision(
            status=PrecedentDecisionStatus.REVIEW_REQUIRED,
            note="Multiple exact IID records match; a reviewer must select the precedent "
            "record to use.",
            escalation_required=True,
            reason_codes=["MULTIPLE_EXACT_MATCHES"],
        )

    if match_status in (MatchStatus.INGREDIENT_AMBIGUOUS, MatchStatus.REVIEW_REQUIRED):
        return PrecedentDecision(
            status=PrecedentDecisionStatus.REVIEW_REQUIRED,
            note=explanation
            or "Ingredient identity/synonym mapping requires reviewer confirmation "
            "before this can be compared.",
            escalation_required=True,
            reason_codes=[match_status],
        )

    if match_status == MatchStatus.POTENCY_UNAVAILABLE or selected_potency_amount is None:
        return PrecedentDecision(
            status=PrecedentDecisionStatus.REVIEW_REQUIRED,
            note=_POTENCY_NOTES.get(
                potency_reason,
                "Selected IID record has no usable potency value; regulatory review required.",
            ),
            escalation_required=True,
            reason_codes=["POTENCY_UNAVAILABLE"],
        )

    if proposed_amount_per_unit is None:
        return PrecedentDecision(
            status=PrecedentDecisionStatus.NOT_COMPARABLE,
            note="Proposed formulation amount is not available for comparison.",
            reason_codes=["PROPOSED_VALUE_MISSING"],
        )

    if source_release_superseded:
        reason_codes.append("SOURCE_RELEASE_SUPERSEDED")

    exceeds_potency = proposed_amount_per_unit > selected_potency_amount
    exceeds_mde = False
    mde_review_only = False

    if exceeds_potency:
        return PrecedentDecision(
            status=PrecedentDecisionStatus.EXCEEDS_IID_PRECEDENT,
            note="Proposed amount per dosage unit exceeds the selected IID potency precedent. "
            "Justification and reviewer conclusion are mandatory; approval cannot be automatic.",
            escalation_required=True,
            reason_codes=["EXCEEDS_POTENCY"],
        )

    if mde_available and selected_mde is not None and proposed_daily_exposure is not None:
        exceeds_mde = proposed_daily_exposure > selected_mde
        if exceeds_mde:
            return PrecedentDecision(
                status=PrecedentDecisionStatus.EXCEEDS_IID_PRECEDENT,
                note="Proposed maximum daily exposure exceeds the selected IID MDE precedent. "
                "Justification and reviewer conclusion are mandatory; approval cannot be "
                "automatic.",
                escalation_required=True,
                reason_codes=["EXCEEDS_MDE"],
            )
    elif not mde_available:
        mde_review_only = True
        reason_codes.append("MDE_UNAVAILABLE")

    if source_release_superseded or mde_review_only:
        return PrecedentDecision(
            status=PrecedentDecisionStatus.REVIEW_REQUIRED,
            note=(
                "Within selected IID potency precedent, but "
                + (
                    "the source release is superseded."
                    if source_release_superseded
                    else "maximum daily exposure precedent is unavailable for comparison."
                )
            ),
            escalation_required=True,
            reason_codes=reason_codes,
        )

    return PrecedentDecision(
        status=PrecedentDecisionStatus.PASS_WITH_IID_PRECEDENT,
        note=REQUIRED_PRECEDENT_NOTE,
        reason_codes=reason_codes,
    )
