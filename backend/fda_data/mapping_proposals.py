"""Propose IID route and dosage-form mappings onto the active SPL vocabulary.

For each distinct route and dosage-form value in an IID release, a mapping is
created in state PROPOSED only when the value equals the label of an ACTIVE
controlled term exactly (case-insensitive, surrounding spaces ignored).
Everything else is reported, never guessed: no fuzzy match, no "closest" term,
no alias. Nothing is ever approved here; a VP reviews and approves the
proposals in the app.

Idempotent: a value that already has a current mapping (in any status) is
skipped, so running twice creates nothing new.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from .audit_events import FdaDataEvent, emit
from .models import (
    ControlledDosageForm,
    ControlledRoute,
    DosageFormMapping,
    FDADatasetType,
    FDADataSourceRelease,
    IIDPrecedentRecord,
    MappingDecisionStatus,
    RouteMapping,
)

#: (record field, controlled model, mapping model, mapping FK name)
_KINDS = {
    "route": ("route_raw", ControlledRoute, RouteMapping, "controlled_route"),
    "dosage_form": (
        "dosage_form_raw",
        ControlledDosageForm,
        DosageFormMapping,
        "controlled_dosage_form",
    ),
}

REASON = (
    "Exact match (case-insensitive, trimmed) to an active FDA SPL term. "
    "Proposed automatically; needs review."
)


def _key(value: str) -> str:
    return (value or "").strip().upper()


@dataclass
class KindReport:
    distinct_values: int = 0
    proposed: list[tuple[str, str]] = field(default_factory=list)  # (raw value, term code)
    already_mapped: list[tuple[str, str]] = field(default_factory=list)  # (raw value, status)
    not_exact: list[tuple[str, int]] = field(default_factory=list)  # (raw value, record count)


def propose_iid_mappings(release: FDADataSourceRelease, *, actor=None, dry_run=False) -> dict:
    if release.dataset_type != FDADatasetType.FDA_IID:
        raise ValueError(f"Release {release.public_id} is not an IID release.")
    dataset = FDADatasetType.FDA_IID
    reports = {}
    with transaction.atomic():
        for kind, (raw_field, term_model, mapping_model, fk) in _KINDS.items():
            report = KindReport()
            terms = {}
            for term in term_model.objects.filter(lifecycle="active"):
                terms.setdefault(_key(term.canonical_label), []).append(term)
            counts: dict[str, int] = {}
            for value in IIDPrecedentRecord.objects.filter(release=release).values_list(
                raw_field, flat=True
            ):
                counts[value] = counts.get(value, 0) + 1
            report.distinct_values = len(counts)
            for raw in sorted(counts):
                existing = mapping_model.objects.filter(
                    source_dataset=dataset, source_raw_value=raw, is_current=True
                ).first()
                if existing:
                    report.already_mapped.append((raw, existing.status))
                    continue
                matches = terms.get(_key(raw), [])
                if len(matches) != 1:
                    # None, or (should never happen) two active terms with the
                    # same label: either way not an exact single match.
                    report.not_exact.append((raw, counts[raw]))
                    continue
                term = matches[0]
                report.proposed.append((raw, term.code))
                if dry_run:
                    continue
                mapping = mapping_model.objects.create(
                    source_dataset=dataset,
                    source_raw_value=raw,
                    status=MappingDecisionStatus.PROPOSED,
                    reason=REASON,
                    **{fk: term},
                )
                emit(
                    event_type=FdaDataEvent.MAPPING_PROPOSED,
                    resource_type="fda_data_mapping",
                    resource_id=str(mapping.public_id),
                    actor_id=getattr(actor, "id", None),
                    actor_email=getattr(actor, "email", ""),
                    payload={
                        "mapping_type": kind,
                        "source_dataset": dataset,
                        "source_raw_value": raw,
                        "controlled_code": term.code,
                        "release": str(release.public_id),
                        "rule": "exact_active_spl_label",
                    },
                )
            reports[kind] = report
    return reports
