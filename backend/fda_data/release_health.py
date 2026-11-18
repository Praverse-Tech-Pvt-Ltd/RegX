"""How many records of an IID release can never be matched, and what to do about it.

An IID record is matched in a preview only through its route and dosage-form
LINKS (the controlled terms an approved mapping gives its raw text). Links are
made at import, and by `reresolve_terminology` before the release is submitted
for review. A record without a link can never be found by a preview, so a
release imported before its mappings were approved silently answers "no
precedent" for everything (found on the real stack, 2026-11-18, QA-07).

`iid_link_health` counts those records, says how many an approved mapping could
fill now, lists the raw values still unmapped, and states the operator's next
step. Read-only: it never changes a record.
"""

from __future__ import annotations

from collections import Counter

from django.db.models import Count, Q

from .models import (
    DosageFormMapping,
    FDADatasetType,
    FDADataSourceRelease,
    IIDPrecedentRecord,
    RouteMapping,
)
from .reresolve import RESOLVABLE_STATUSES

_LINKS = (
    ("route", RouteMapping, "controlled_route"),
    ("dosage_form", DosageFormMapping, "controlled_dosage_form"),
)
_TOP = 5


def _approved_raw_values(model, target: str) -> set[str]:
    return set(
        model.objects.filter(
            source_dataset=FDADatasetType.FDA_IID,
            is_current=True,
            status="approved",
            **{f"{target}__isnull": False},
        ).values_list("source_raw_value", flat=True)
    )


def iid_link_health(release: FDADataSourceRelease | None) -> dict | None:
    """None for anything but an IID release; else counts, unmapped values and advice."""
    if release is None or release.dataset_type != FDADatasetType.FDA_IID:
        return None
    records = IIDPrecedentRecord.objects.filter(release=release)
    total = records.count()
    unlinked_qs = records.filter(
        Q(route_normalized__isnull=True) | Q(dosage_form_normalized__isnull=True)
    )
    unlinked = unlinked_qs.count()
    fillable_records: set[int] = set()
    unmapped: dict[str, Counter] = {}
    for prefix, model, target in _LINKS:
        approved = _approved_raw_values(model, target)
        rows = (
            records.filter(**{f"{prefix}_normalized__isnull": True})
            .values(f"{prefix}_raw")
            .annotate(n=Count("id"))
        )
        counter: Counter = Counter()
        for row in rows:
            raw = row[f"{prefix}_raw"]
            if raw in approved:
                fillable_records.update(
                    records.filter(
                        **{f"{prefix}_normalized__isnull": True, f"{prefix}_raw": raw}
                    ).values_list("id", flat=True)
                )
            else:
                counter[raw] = row["n"]
        unmapped[prefix] = counter
    fillable = len(fillable_records)
    resolvable = release.status in RESOLVABLE_STATUSES
    return {
        "total_records": total,
        "linked_records": total - unlinked,
        "unlinked_records": unlinked,
        "fillable_by_approved_mappings": fillable,
        "unmapped_routes": [
            {"raw_value": v, "records": n} for v, n in unmapped["route"].most_common(_TOP)
        ],
        "unmapped_dosage_forms": [
            {"raw_value": v, "records": n} for v, n in unmapped["dosage_form"].most_common(_TOP)
        ],
        "message": _message(total, unlinked),
        "operator_action": _action(release, unlinked, fillable, resolvable),
    }


def _message(total: int, unlinked: int) -> str:
    if unlinked == 0:
        return f"All {total:,} records have a route and dosage-form link."
    return (
        f"{unlinked:,} of {total:,} records have no route or dosage-form link, so a preview "
        "can never match them; for those records a preview says there is no precedent even "
        "when the FDA lists one."
    )


def _action(release, unlinked: int, fillable: int, resolvable: bool) -> str:
    if unlinked == 0:
        return ""
    parts = []
    if fillable and resolvable:
        parts.append(
            f"Approved mappings can now fill {fillable:,} of them: run "
            f"`python manage.py reresolve_terminology {release.public_id}` before submitting "
            "this release for review."
        )
    elif fillable:
        parts.append(
            f"Approved mappings could now fill {fillable:,} of them, but this release is "
            f"'{release.status}' and its content is fixed once it is submitted for review. "
            "Register the next FDA IID file as a new release (it is linked at import from the "
            "approved mappings) and take it through approval. Importing the same file again "
            "is refused as a duplicate."
        )
    if unlinked > fillable:
        parts.append(
            f"{unlinked - fillable:,} have a route or dosage form no reviewer has mapped yet "
            "(listed here): propose and approve those mappings on the Terminology Mappings page."
        )
    return " ".join(parts)
