"""
Deterministic substance/UNII/CAS identity resolution, shared by IID import
normalization, the IID matching engine, the terminology-review API, and
the affected-record drill-down. No fuzzy candidate is ever auto-approved
or auto-selected here -- this module only ever returns a status plus a
list of candidates; a human reviewer is the only path to APPROVED.
"""

from dataclasses import dataclass, field

from .models import (
    FDAReleaseStatus,
    IIDIngredient,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)


class SubstanceMatchStatus:
    EXACT_MATCH = "EXACT_MATCH"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    INGREDIENT_AMBIGUOUS = "INGREDIENT_AMBIGUOUS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class SubstanceCandidate:
    mapping_public_id: str | None
    ingredient_public_id: str | None
    ingredient_name: str | None
    unii: str | None
    method: str


@dataclass(frozen=True)
class SubstanceMatchResult:
    status: str
    candidates: list = field(default_factory=list)
    reason_code: str | None = None


def _release_usable(mapping: SubstanceSynonymMapping) -> bool:
    """A mapping scoped to a specific release can only be honored while
    that release is approved/active -- a superseded or rejected release
    can never silently keep supplying identity resolutions."""
    if mapping.release_id is None:
        return True
    return mapping.release.status in (FDAReleaseStatus.APPROVED, FDAReleaseStatus.ACTIVE)


def _approved_mappings_for(normalized_name: str, unii: str, cas_number: str):
    qs = SubstanceSynonymMapping.objects.filter(
        status=SubstanceMappingStatus.APPROVED, is_current=True
    ).select_related("release", "proposed_ingredient")
    matches = []
    for mapping in qs:
        if not _release_usable(mapping):
            continue
        if normalized_name and mapping.normalized_ingredient_name == normalized_name:
            matches.append((mapping, SubstanceMappingMethodLabel.EXACT_NAME))
        elif unii and mapping.raw_unii and mapping.raw_unii == unii:
            matches.append((mapping, SubstanceMappingMethodLabel.EXACT_UNII))
        elif cas_number and mapping.raw_cas_number and mapping.raw_cas_number == cas_number:
            matches.append((mapping, SubstanceMappingMethodLabel.EXACT_CAS))
    return matches


class SubstanceMappingMethodLabel:
    EXACT_NAME = "EXACT_NAME"
    EXACT_UNII = "EXACT_UNII"
    EXACT_CAS = "EXACT_CAS"
    APPROVED_SYNONYM = "REVIEWED_SYNONYM"


def resolve_substance_identity(
    *, normalized_name: str = "", unii: str = "", cas_number: str = ""
) -> SubstanceMatchResult:
    """Resolve a raw ingredient identity to a confirmed IIDIngredient,
    trying (in order): exact approved UNII mapping, exact approved CAS
    mapping, exact approved name mapping, exact IIDIngredient.unii, exact
    IIDIngredient.normalized_name. Multiple distinct resolutions -> never
    picks one; returns MULTIPLE_CANDIDATES. No usable identity at all ->
    REVIEW_REQUIRED (nothing was even proposed) or INGREDIENT_AMBIGUOUS
    (no identity information was supplied)."""
    if not normalized_name and not unii and not cas_number:
        return SubstanceMatchResult(
            status=SubstanceMatchStatus.INGREDIENT_AMBIGUOUS,
            reason_code="NO_IDENTITY_SUPPLIED",
        )

    candidates: list[SubstanceCandidate] = []
    seen_ingredient_ids: set[int] = set()

    approved_mappings = _approved_mappings_for(normalized_name, unii, cas_number)
    for mapping, method in approved_mappings:
        ingredient = mapping.proposed_ingredient
        ingredient_id = ingredient.pk if ingredient else None
        if ingredient_id in seen_ingredient_ids:
            continue
        seen_ingredient_ids.add(ingredient_id)
        candidates.append(
            SubstanceCandidate(
                mapping_public_id=str(mapping.public_id),
                ingredient_public_id=str(ingredient.public_id) if ingredient else None,
                ingredient_name=ingredient.canonical_name if ingredient else None,
                unii=ingredient.unii if ingredient else mapping.proposed_unii,
                method=method,
            )
        )

    # Fall back to a direct exact match against the canonical IIDIngredient
    # table itself (covers ingredients that never needed a governed
    # mapping row because the raw identity was already exact). This must
    # NEVER run if a non-approved SubstanceSynonymMapping already exists
    # for this identity -- a proposed/rejected/under-review/returned
    # mapping means this identity has been explicitly flagged for
    # governance, and string equality against IIDIngredient must not
    # silently bypass that unresolved state.
    unresolved_state = None
    if not candidates:
        unresolved_state = _unapproved_state_for(normalized_name, unii, cas_number)
    if not candidates and unresolved_state is None:
        direct_qs = IIDIngredient.objects.none()
        if unii:
            direct_qs = IIDIngredient.objects.filter(unii=unii)
        elif cas_number:
            direct_qs = IIDIngredient.objects.filter(cas_number=cas_number)
        elif normalized_name:
            direct_qs = IIDIngredient.objects.filter(normalized_name=normalized_name)
        for ingredient in direct_qs:
            if ingredient.pk in seen_ingredient_ids:
                continue
            seen_ingredient_ids.add(ingredient.pk)
            method = (
                SubstanceMappingMethodLabel.EXACT_UNII
                if unii
                else SubstanceMappingMethodLabel.EXACT_CAS
                if cas_number
                else SubstanceMappingMethodLabel.EXACT_NAME
            )
            candidates.append(
                SubstanceCandidate(
                    mapping_public_id=None,
                    ingredient_public_id=str(ingredient.public_id),
                    ingredient_name=ingredient.canonical_name,
                    unii=ingredient.unii,
                    method=method,
                )
            )

    if len(candidates) > 1:
        return SubstanceMatchResult(
            status=SubstanceMatchStatus.MULTIPLE_CANDIDATES, candidates=candidates
        )
    if len(candidates) == 1:
        return SubstanceMatchResult(status=SubstanceMatchStatus.EXACT_MATCH, candidates=candidates)

    # No approved identity. Distinguish an identity that was explicitly
    # REJECTED (a reviewer denied it -> the identity is ambiguous/unusable,
    # never silently retried) from one that is merely pending review
    # (proposed/under_review/returned -> a human still needs to decide) from
    # one where nothing was ever proposed. A rejected mapping must never be
    # treated the same as "not yet reviewed".
    if unresolved_state == "rejected":
        return SubstanceMatchResult(
            status=SubstanceMatchStatus.INGREDIENT_AMBIGUOUS, reason_code="REJECTED_MAPPING"
        )
    if unresolved_state == "pending":
        return SubstanceMatchResult(
            status=SubstanceMatchStatus.REVIEW_REQUIRED, reason_code="MAPPING_PENDING_REVIEW"
        )
    return SubstanceMatchResult(
        status=SubstanceMatchStatus.REVIEW_REQUIRED, reason_code="NO_APPROVED_MAPPING"
    )


def _unapproved_state_for(normalized_name: str, unii: str, cas_number: str) -> str | None:
    """Classify the best non-approved mapping state for a raw identity,
    considering only mappings scoped to a currently-usable release (or
    platform-master, release=None) -- see _release_usable(). A stale
    proposed/rejected mapping left over on a since-superseded release must
    never block a legitimate direct-IIDIngredient match for a brand-new
    active release; it remains available for any historical assessment
    snapshot that already referenced it, but it must not silently keep
    governing new resolutions. See docs/HUMAN_REVIEW_PR5_REMEDIATION.md
    (HR-04).

    Returns "pending" if any usable proposed/under_review/returned mapping
    matches, "rejected" if only a usable rejected mapping matches, or None
    if no usable mapping references this identity. Pending outranks
    rejected so that a fresh re-proposal after a rejection is treated as
    pending review, not denied."""
    from django.db.models import Q

    identity_q = Q()
    if normalized_name:
        identity_q |= Q(normalized_ingredient_name=normalized_name)
    if unii:
        identity_q |= Q(raw_unii=unii)
    if cas_number:
        identity_q |= Q(raw_cas_number=cas_number)
    if not identity_q:
        return None

    candidates = (
        SubstanceSynonymMapping.objects.filter(identity_q)
        .exclude(status=SubstanceMappingStatus.APPROVED)
        .select_related("release")
    )
    statuses = {m.status for m in candidates if _release_usable(m)}
    if not statuses:
        return None
    pending = {
        SubstanceMappingStatus.PROPOSED,
        SubstanceMappingStatus.UNDER_REVIEW,
        SubstanceMappingStatus.RETURNED,
    }
    if statuses & pending:
        return "pending"
    if SubstanceMappingStatus.REJECTED in statuses:
        return "rejected"
    return None


def affected_record_count(mapping: SubstanceSynonymMapping) -> int:
    """Best-effort count of IID precedent records referencing this raw
    identity -- informational only, never used to gate a decision."""
    from django.db.models import Q

    from .models import IIDPrecedentRecord

    filters = Q(ingredient_name_raw=mapping.raw_ingredient_name)
    return IIDPrecedentRecord.objects.filter(filters).count()
