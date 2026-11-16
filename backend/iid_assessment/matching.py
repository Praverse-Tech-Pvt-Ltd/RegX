"""
Deterministic IID precedent-matching service.

No fuzzy ingredient match ever becomes final automatically. No substring
route matching. No dosage-form family substitution without an approved
mapping. No automatic selection of the "most favourable" IID value when
multiple exact matches exist -- that always returns MULTIPLE_EXACT_MATCHES
and requires a human to pick one.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from fda_data.models import FDAReleaseStatus, IIDCalculabilityStatus, IIDPrecedentRecord


class MatchStatus:
    EXACT_MATCH = "EXACT_MATCH"
    MULTIPLE_EXACT_MATCHES = "MULTIPLE_EXACT_MATCHES"
    INGREDIENT_AMBIGUOUS = "INGREDIENT_AMBIGUOUS"
    ROUTE_MISMATCH = "ROUTE_MISMATCH"
    DOSAGE_FORM_MISMATCH = "DOSAGE_FORM_MISMATCH"
    NO_MATCHING_IID_PRECEDENT = "NO_MATCHING_IID_PRECEDENT"
    POTENCY_UNAVAILABLE = "POTENCY_UNAVAILABLE"
    MDE_UNAVAILABLE = "MDE_UNAVAILABLE"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class MatchCandidate:
    precedent_record_public_id: str
    ingredient_name: str
    route: str
    dosage_form: str
    potency_amount: Decimal | None
    potency_unit: str | None
    maximum_daily_exposure: Decimal | None
    mde_unit: str | None
    calculability_status: str
    #: The potency unit's meaning (controlled units), e.g. "mg/5mL"; None when
    #: not established. `potency_unit` is derived from it (see below).
    potency_meaning: str | None = None


@dataclass(frozen=True)
class MatchResult:
    status: str
    candidates: list = field(default_factory=list)
    reason_code: str | None = None


def find_iid_candidates(
    *,
    ingredient_public_id,
    controlled_route_id,
    controlled_dosage_form_id,
    active_release_id: int,
) -> MatchResult:
    """Steps 1-4 of the match sequence: ingredient identity (exact,
    resolved), exact controlled route, exact controlled dosage form,
    restricted to the caller-selected active/approved IID release only."""
    if ingredient_public_id is None:
        return MatchResult(
            status=MatchStatus.INGREDIENT_AMBIGUOUS, reason_code="INGREDIENT_UNRESOLVED"
        )
    if controlled_route_id is None:
        return MatchResult(
            status=MatchStatus.ROUTE_MISMATCH, reason_code="ROUTE_UNMAPPED_OR_UNCONFIRMED"
        )
    if controlled_dosage_form_id is None:
        return MatchResult(
            status=MatchStatus.DOSAGE_FORM_MISMATCH,
            reason_code="DOSAGE_FORM_UNMAPPED_OR_UNCONFIRMED",
        )

    release = FDAReleaseStatus
    qs = IIDPrecedentRecord.objects.filter(
        ingredient__public_id=ingredient_public_id,
        route_normalized_id=controlled_route_id,
        dosage_form_normalized_id=controlled_dosage_form_id,
        release_id=active_release_id,
        release__status__in=[release.APPROVED, release.ACTIVE],
    ).select_related(
        "release",
        "route_normalized",
        "dosage_form_normalized",
        "potency_expression__numerator_unit",
        "potency_expression__denominator_unit",
        "mde_expression__numerator_unit",
    )

    records = list(qs)
    if not records:
        return MatchResult(status=MatchStatus.NO_MATCHING_IID_PRECEDENT)

    candidates = [
        MatchCandidate(
            precedent_record_public_id=str(r.public_id),
            ingredient_name=r.ingredient_name_raw,
            route=r.route_normalized.canonical_label if r.route_normalized else r.route_raw,
            dosage_form=(
                r.dosage_form_normalized.canonical_label
                if r.dosage_form_normalized
                else r.dosage_form_raw
            ),
            potency_amount=r.potency_amount,
            potency_unit=_potency_unit(r),
            maximum_daily_exposure=r.maximum_daily_exposure,
            mde_unit=_mde_unit(r),
            calculability_status=r.calculability_status,
            potency_meaning=str(r.potency_expression) if r.potency_expression_id else None,
        )
        for r in records
    ]

    if len(candidates) > 1:
        return MatchResult(status=MatchStatus.MULTIPLE_EXACT_MATCHES, candidates=candidates)

    single = records[0]
    # One comparison path: availability comes from the record's amount and the
    # MEANING of its unit, never from the legacy unit link or a stored flag.
    if single.potency_amount is None:
        reason = (
            "DAILY_EXPOSURE_ONLY_NEEDS_Q8"
            if single.maximum_daily_exposure is not None
            else "NO_NUMERIC_LIMIT"
        )
        return MatchResult(
            status=MatchStatus.POTENCY_UNAVAILABLE, candidates=candidates, reason_code=reason
        )
    if single.potency_expression_id is None:
        return MatchResult(
            status=MatchStatus.POTENCY_UNAVAILABLE,
            candidates=candidates,
            reason_code="IID_UNIT_MISSING",
        )
    if single.calculability_status in (
        IIDCalculabilityStatus.INGREDIENT_AMBIGUOUS,
        IIDCalculabilityStatus.REVIEW_REQUIRED,
    ):
        return MatchResult(status=MatchStatus.REVIEW_REQUIRED, candidates=candidates)

    return MatchResult(status=MatchStatus.EXACT_MATCH, candidates=candidates)


def _potency_unit(record) -> str:
    """The unit handed to the calculation engines, from the meaning only.

    Per dose unit: the exact-factor unit key (e.g. "milligram"), which
    `unit_conversion` and the IIG checklist registry understand. Any other
    basis (per volume, percentage): the meaning's text (e.g. "mg/5mL"), which
    no engine resolves, so a per-dose-only engine fails closed instead of
    comparing across bases. No meaning: "" (fails closed too)."""
    from .comparison import conversion_key

    expression = record.potency_expression
    if expression is None:
        return ""
    if expression.basis == "per_dose_unit" and expression.numerator_unit_id:
        return conversion_key(expression.numerator_unit.code) or str(expression)
    return str(expression)


def _mde_unit(record) -> str:
    """The maximum-daily-exposure unit, from the meaning only (mass per day).

    Nothing fills `mde_expression` on real data yet: the per-day rule (Q8) is
    out of scope, so the raw string is returned and every per-day calculation
    fails closed. The legacy `mde_unit_normalized` link is never read."""
    from .comparison import conversion_key

    expression = record.mde_expression
    if expression is not None and expression.basis == "per_day" and expression.numerator_unit_id:
        return conversion_key(expression.numerator_unit.code) or record.mde_unit_raw
    return record.mde_unit_raw
