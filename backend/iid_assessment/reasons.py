"""Plain, honest reasons for an IID preview that found nothing to compare against.

The match engine answers in codes (`ROUTE_MISMATCH`, `REVIEW_REQUIRED`, ...).
Before this module the screen turned them into sentences that were sometimes
wrong for the case at hand (QA-06, 2026-11-18): a dosage form that the IID does
list, but that no reviewer has mapped yet, was reported as "route and dosage
form must match exactly", and an ingredient that is simply not in the IID was
reported as "synonym mapping requires reviewer confirmation".

`refine` looks at what the user typed and at the active release, and returns
one specific reason code and sentence. It never changes the match status or the
decision status (the governance outcome stays exactly as before); it only
explains it. Read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from fda_data.models import IIDPrecedentRecord

from .matching import MatchResult, MatchStatus

#: Every reason code this module can return, with its short heading for the screen.
HEADINGS = {
    "INGREDIENT_NOT_FOUND": "Ingredient not found in the active IID release",
    "INGREDIENT_MAPPING_PENDING": "Ingredient synonym waiting for a reviewer",
    "INGREDIENT_MAPPING_REJECTED": "Ingredient synonym rejected by a reviewer",
    "INGREDIENT_MULTIPLE_CANDIDATES": "Ingredient matches more than one IID ingredient",
    "INGREDIENT_NOT_ENTERED": "No ingredient entered",
    "ROUTE_NOT_MAPPED": "Route not yet mapped by a reviewer",
    "ROUTE_NOT_RECOGNISED": "Route not recognised",
    "DOSAGE_FORM_NOT_MAPPED": "Dosage form not yet mapped by a reviewer",
    "DOSAGE_FORM_NOT_RECOGNISED": "Dosage form not recognised",
    "INGREDIENT_NOT_IN_RELEASE": "Ingredient has no record in the active IID release",
    "RECORDS_NOT_LINKED": "Some IID records for this ingredient are not yet mapped",
    "NO_RECORD_FOR_ROUTE_AND_FORM": "No IID record with this route and dosage form",
}


@dataclass(frozen=True)
class Reason:
    code: str
    text: str

    @property
    def heading(self) -> str:
        return HEADINGS[self.code]


def _records(release):
    return IIDPrecedentRecord.objects.filter(release=release) if release else None


def _term_reason(kind: str, typed: str, release, field: str) -> Reason:
    """A route or dosage form that is not a controlled term: listed in the IID
    but unmapped, or simply not recognised."""
    typed = (typed or "").strip()
    label = "route" if kind == "ROUTE" else "dosage form"
    records = _records(release)
    in_iid = (
        records.filter(
            **{f"{field}_raw__iexact": typed, f"{field}_normalized__isnull": True}
        ).count()
        if records is not None and typed
        else 0
    )
    if in_iid:
        return Reason(
            f"{kind}_NOT_MAPPED",
            f"'{typed}' appears in the active IID release ({in_iid:,} records), but no "
            f"reviewer has mapped this {label} to a controlled {label} yet, so those records "
            "cannot be matched. A reviewer can propose and approve the mapping on the "
            "Terminology Mappings page.",
        )
    example = "ORAL" if kind == "ROUTE" else "TABLET"
    return Reason(
        f"{kind}_NOT_RECOGNISED",
        f"'{typed}' is not a recognised {label}. Choose a {label} from the list "
        f"(for example {example}).",
    )


def _ingredient_reason(reason_code: str | None, name: str) -> Reason | None:
    shown = name.strip() or "This ingredient"
    if reason_code == "NO_APPROVED_MAPPING":
        return Reason(
            "INGREDIENT_NOT_FOUND",
            f"'{shown}' was not found in the active IID release: no IID ingredient or approved "
            "synonym has this name. Check the spelling against the IID; if the ingredient is "
            "listed under another name, a reviewer can approve a synonym mapping.",
        )
    if reason_code == "MAPPING_PENDING_REVIEW":
        return Reason(
            "INGREDIENT_MAPPING_PENDING",
            f"A synonym mapping for '{shown}' is waiting for a reviewer; it cannot be compared "
            "until the mapping is approved.",
        )
    if reason_code == "REJECTED_MAPPING":
        return Reason(
            "INGREDIENT_MAPPING_REJECTED",
            f"A reviewer rejected the synonym mapping for '{shown}', so it cannot be compared.",
        )
    if reason_code == "NO_IDENTITY_SUPPLIED":
        return Reason(
            "INGREDIENT_NOT_ENTERED", "No ingredient name, UNII or CAS number was entered."
        )
    if reason_code is None:
        return None
    return None


def refine(
    *,
    match: MatchResult,
    release,
    route,
    dosage_form,
    route_code: str,
    dosage_form_code: str,
    ingredient_public_id,
    ingredient_name: str,
    substance_status: str | None,
) -> Reason | None:
    """The specific reason, or None when the match found something to compare."""
    status = match.status
    if (
        status in (MatchStatus.REVIEW_REQUIRED, MatchStatus.INGREDIENT_AMBIGUOUS)
        and not match.candidates
    ):
        if substance_status == "MULTIPLE_CANDIDATES":
            return Reason(
                "INGREDIENT_MULTIPLE_CANDIDATES",
                f"'{ingredient_name.strip()}' matches more than one IID ingredient through "
                "approved mappings; a reviewer must decide which one it is.",
            )
        return _ingredient_reason(match.reason_code, ingredient_name)
    if status == MatchStatus.ROUTE_MISMATCH and route is None:
        return _term_reason("ROUTE", route_code, release, "route")
    if status == MatchStatus.DOSAGE_FORM_MISMATCH and dosage_form is None:
        return _term_reason("DOSAGE_FORM", dosage_form_code, release, "dosage_form")
    if status == MatchStatus.NO_MATCHING_IID_PRECEDENT:
        records = _records(release)
        if records is None or ingredient_public_id is None:
            return None
        for_ingredient = records.filter(ingredient__public_id=ingredient_public_id)
        name = ingredient_name.strip() or "This ingredient"
        if not for_ingredient.exists():
            return Reason(
                "INGREDIENT_NOT_IN_RELEASE",
                f"'{name}' is a known IID ingredient, but the active IID release has no record "
                "for it.",
            )
        unlinked = (
            for_ingredient.filter(route_normalized__isnull=True).count()
            + for_ingredient.filter(
                route_normalized__isnull=False, dosage_form_normalized__isnull=True
            ).count()
        )
        route_label = route.canonical_label if route else route_code
        form_label = dosage_form.canonical_label if dosage_form else dosage_form_code
        if unlinked:
            return Reason(
                "RECORDS_NOT_LINKED",
                f"None of the mapped IID records for '{name}' has route {route_label} and dosage "
                f"form {form_label}, but {unlinked:,} of its records have a route or dosage form "
                "that no reviewer has mapped yet, so they cannot be checked. A reviewer can map "
                "them on the Terminology Mappings page.",
            )
        return Reason(
            "NO_RECORD_FOR_ROUTE_AND_FORM",
            f"The active IID release has records for '{name}', but none with route "
            f"{route_label} and dosage form {form_label}.",
        )
    return None
