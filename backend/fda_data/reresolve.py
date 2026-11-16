"""Re-resolve terminology on an imported release that is not yet under review.

Normalised route and dosage form are looked up once, at import time. A mapping
approved after the import therefore never reaches the release's records, and
re-importing the same file is refused (`importer.find_imported_duplicate`).
This module closes that gap without touching anything a reviewer has seen:

- Only releases that have not been submitted for review (`registered`,
  `staged`, `validated`). A release under review, approved, active, superseded
  or rejected is refused, so its content never changes under its reviewer.
- Only EMPTY links are filled, and only from APPROVED, current mappings (the
  same `lookup_*_mapping` the importer uses). An existing link is never changed
  or cleared.
- One audit event per changed record (old -> new, with the mapping), plus one
  summary event. `--dry-run` reports the same changes and writes nothing.
- Unit meanings (controlled units, increment 2): an IID record's empty
  `potency_expression` is filled from the APPROVED, current `UnitMapping` for
  its `potency_unit_raw`, and only when that meaning is in force (listed by the
  ACTIVE controlled-units release). Same rules: never overwrite, never clear,
  only before review. `potency_unit_normalized` and calculability are not
  touched by this link.

The generic part works on any record model with `route_raw`/`route_normalized`
and `dosage_form_raw`/`dosage_form_normalized`. What differs per dataset (which
records, what else to recompute) lives in `_DATASETS`. Only the IID is wired
up; the Orange Book has the same four fields and can be added there later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.db import transaction

from .audit_events import FdaDataEvent, emit
from .importer import _determine_calculability
from .models import (
    DosageFormMapping,
    FDADatasetType,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDPrecedentRecord,
    RouteMapping,
    UnitMapping,
)

#: Statuses a release can have before anyone has been asked to review it.
RESOLVABLE_STATUSES = (
    FDAReleaseStatus.REGISTERED,
    FDAReleaseStatus.STAGED,
    FDAReleaseStatus.VALIDATED,
)


class ReresolveRefused(Exception):
    """The release cannot be re-resolved (wrong status or dataset type)."""


@dataclass(frozen=True)
class _Dataset:
    records: Callable[[FDADataSourceRelease], object]  # queryset of records
    recompute: Callable[[object], list[str]]  # updates derived fields; returns their names


def _recompute_iid(record: IIDPrecedentRecord) -> list[str]:
    record.calculability_status = _determine_calculability(
        ingredient=record.ingredient,
        route_normalized=record.route_normalized,
        dosage_form_normalized=record.dosage_form_normalized,
        potency_amount=record.potency_amount,
        potency_unit=record.potency_unit_normalized,
        mde_amount=record.maximum_daily_exposure,
        potency_unparsed=record.potency_amount is None and bool(record.potency_amount_raw),
    )
    return ["calculability_status"]


_DATASETS: dict[str, _Dataset] = {
    FDADatasetType.FDA_IID: _Dataset(
        records=lambda release: IIDPrecedentRecord.objects.filter(release=release),
        recompute=_recompute_iid,
    ),
}

_LINKS = (
    # (record field prefix, mapping model, mapping FK to the controlled term)
    ("route", RouteMapping, "controlled_route"),
    ("dosage_form", DosageFormMapping, "controlled_dosage_form"),
)


@dataclass(frozen=True)
class Change:
    record_public_id: str
    field: str
    raw_value: str
    new_code: str
    mapping_public_id: str


def _approved_mapping(model, dataset_type: str, raw_value: str):
    """Same rule as `terminology.lookup_*_mapping`: approved and current only."""
    return model.objects.filter(
        source_dataset=dataset_type,
        source_raw_value=raw_value,
        is_current=True,
        status="approved",
    ).first()


def reresolve(release: FDADataSourceRelease, *, actor=None, dry_run: bool = False) -> list[Change]:
    dataset = _DATASETS.get(release.dataset_type)
    if dataset is None:
        raise ReresolveRefused(f"Re-resolving is not available for {release.dataset_type}.")

    changes: list[Change] = []
    with transaction.atomic():
        locked = FDADataSourceRelease.objects.select_for_update().get(pk=release.pk)
        if locked.status not in RESOLVABLE_STATUSES:
            raise ReresolveRefused(
                f"Release {locked.public_id} is '{locked.status}'. Only a release that has "
                "not been submitted for review can be re-resolved."
            )
        records = dataset.records(locked).select_for_update()
        in_force = None  # meanings of the active controlled-units release, read once
        for record in records:
            filled: list[str] = []
            for prefix, mapping_model, target in _LINKS:
                if getattr(record, f"{prefix}_normalized_id") is not None:
                    continue  # never change or clear an existing link
                raw = getattr(record, f"{prefix}_raw")
                mapping = _approved_mapping(mapping_model, locked.dataset_type, raw)
                if mapping is None or getattr(mapping, f"{target}_id") is None:
                    continue
                term = getattr(mapping, target)
                changes.append(
                    Change(str(record.public_id), prefix, raw, term.code, str(mapping.public_id))
                )
                if not dry_run:
                    setattr(record, f"{prefix}_normalized", term)
                    filled.append(f"{prefix}_normalized")
            if (
                locked.dataset_type == FDADatasetType.FDA_IID
                and record.potency_expression_id is None
                and record.potency_unit_raw
            ):
                if in_force is None:
                    from .controlled_units import in_force_expressions

                    in_force = in_force_expressions()
                mapping = _approved_mapping(
                    UnitMapping, locked.dataset_type, record.potency_unit_raw
                )
                if mapping is not None and mapping.quantity_expression_id in in_force:
                    expression = mapping.quantity_expression
                    changes.append(
                        Change(
                            str(record.public_id),
                            "potency_expression",
                            record.potency_unit_raw,
                            str(expression),
                            str(mapping.public_id),
                        )
                    )
                    if not dry_run:
                        record.potency_expression = expression
                        filled.append("potency_expression")
            if dry_run or not filled:
                continue
            derived = dataset.recompute(record)
            record.save(update_fields=[*filled, *derived, "updated_at"])
            emit(
                event_type=FdaDataEvent.RECORD_TERMINOLOGY_RERESOLVED,
                resource_type="fda_data_record",
                resource_id=str(record.public_id),
                actor_id=getattr(actor, "id", None),
                actor_email=getattr(actor, "email", ""),
                payload={
                    "release": str(locked.public_id),
                    "filled": [
                        {
                            "field": c.field,
                            "raw_value": c.raw_value,
                            "old": None,
                            "new_code": c.new_code,
                            "mapping": c.mapping_public_id,
                        }
                        for c in changes
                        if c.record_public_id == str(record.public_id)
                    ],
                    **{name: getattr(record, name) for name in derived},
                },
            )
        if changes and not dry_run:
            emit(
                event_type=FdaDataEvent.RELEASE_TERMINOLOGY_RERESOLVED,
                resource_id=str(locked.public_id),
                actor_id=getattr(actor, "id", None),
                actor_email=getattr(actor, "email", ""),
                payload={
                    "links_filled": len(changes),
                    "records_changed": len({c.record_public_id for c in changes}),
                },
            )
    return changes


def count_unmapped(release: FDADataSourceRelease) -> int | None:
    """Records still missing a route or dosage-form link, or None when the
    dataset is not covered here."""
    dataset = _DATASETS.get(release.dataset_type)
    if dataset is None:
        return None
    from django.db.models import Q

    return (
        dataset.records(release)
        .filter(Q(route_normalized__isnull=True) | Q(dosage_form_normalized__isnull=True))
        .count()
    )
