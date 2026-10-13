"""FDA SPL route and dosage-form lists as REGX's controlled vocabulary.

Decision: docs/TERMINOLOGY_VOCABULARY_DECISION.md. `ControlledRoute` and
`ControlledDosageForm` hold FDA's Structured Product Labeling terms, with
`code` = the NCI Thesaurus code (e.g. C38288) and `canonical_label` = the SPL
term (e.g. ORAL). Units are out of scope here (they need a model change).

HOW A LIST GETS IN
------------------
1. An operator saves FDA's page and turns its table into a CSV snapshot
   (`spl_term,nci_code`). Nothing is fetched from fda.gov at runtime.
2. `load_snapshot` registers the snapshot as an `FDADataSourceRelease` of type
   `fda_route_terminology` / `fda_dosage_form_terminology` -- the same
   versioned, checksummed, platform-level record every FDA source gets -- and
   records one `FdaImportRowResult` per term. New codes are created as
   `draft`. Existing terms are NOT changed at load time.
3. The release goes through the normal lifecycle. Only `lifecycle.activate`
   (approver != loader) calls `apply_on_activation`, which makes the
   snapshot's terms `active`, applies label changes (keeping the old label as
   an alias) and retires terms the snapshot no longer lists. Retired terms are
   never deleted: mappings and IID records point at them.

Loading the same bytes twice returns the same release and changes nothing.
"""

from __future__ import annotations

import csv
import io
import re

from django.db import transaction
from django.utils import timezone

from .checksums import sha256_payload
from .importer import register_release
from .models import (
    ControlledDosageForm,
    ControlledRoute,
    FDADatasetType,
    FDADataSourceRelease,
    FdaImportRowResult,
    FdaImportRowResultType,
)

PARSER_IDENTIFIER = "fda_spl_terminology_csv:1"
SNAPSHOT_HEADER = ["spl_term", "nci_code"]
_NCI_CODE = re.compile(r"^C[0-9]+$")

#: list name -> (dataset type, model, human label)
SPL_LISTS = {
    "routes": (
        FDADatasetType.FDA_ROUTE_TERMINOLOGY,
        ControlledRoute,
        "FDA SPL Route of Administration",
    ),
    "dosage-forms": (
        FDADatasetType.FDA_DOSAGE_FORM_TERMINOLOGY,
        ControlledDosageForm,
        "FDA SPL Dosage Forms",
    ),
}
TERMINOLOGY_DATASET_TYPES = {dataset_type for dataset_type, _, _ in SPL_LISTS.values()}

#: reason_code on each term's FdaImportRowResult.
NEW, UNCHANGED, LABEL_CHANGED = "new_term", "unchanged", "label_changed"


class SnapshotError(Exception):
    """The snapshot is not a clean (spl_term, nci_code) list."""


def parse_snapshot(raw: bytes) -> list[tuple[str, str]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SnapshotError(f"Snapshot is not UTF-8: {exc}") from exc
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or [c.strip() for c in rows[0]] != SNAPSHOT_HEADER:
        raise SnapshotError(f"Snapshot header must be exactly: {','.join(SNAPSHOT_HEADER)}.")
    terms: list[tuple[str, str]] = []
    for number, row in enumerate(rows[1:], start=2):
        if not row:
            continue
        if len(row) != 2:
            raise SnapshotError(f"Line {number}: expected 2 fields, found {len(row)}.")
        term, code = row[0].strip(), row[1].strip()
        if not term:
            raise SnapshotError(f"Line {number}: empty SPL term.")
        if not _NCI_CODE.match(code):
            raise SnapshotError(f"Line {number}: {code!r} is not an NCI Thesaurus code.")
        terms.append((term, code))
    if not terms:
        raise SnapshotError("Snapshot has a header but no terms.")
    for index, what in ((1, "code"), (0, "term")):
        seen: set[str] = set()
        for row in terms:
            key = row[index].upper()
            if key in seen:
                raise SnapshotError(f"Duplicate {what} in snapshot: {row[index]!r}.")
            seen.add(key)
    return terms


def fda_source_for(release: FDADataSourceRelease, label: str) -> str:
    page_date = release.publication_date.isoformat() if release.publication_date else "unknown"
    return (
        f"{label}; page current as of {page_date}; snapshot sha256 "
        f"{release.source_checksum_sha256}. Code: NCI Thesaurus (NCI EVS, CC BY 4.0)."
    )[:255]


def load_snapshot(
    *,
    list_name: str,
    raw: bytes,
    filename: str,
    page_date,
    source_reference: str,
    actor=None,
) -> tuple[FDADataSourceRelease, dict]:
    dataset_type, model, label = SPL_LISTS[list_name]
    terms = parse_snapshot(raw)

    with transaction.atomic():
        release = register_release(
            dataset_type=dataset_type,
            source_name=f"{label} (page current as of {page_date.isoformat()})",
            official_source_reference=source_reference,
            file_obj=io.BytesIO(raw),
            original_filename=filename,
            media_type="text/csv",
            publication_date=page_date,
            imported_by=actor,
            normalized_payload_sha256=sha256_payload({"rows": terms}),
            parser_identifier=PARSER_IDENTIFIER,
        )
        results = FdaImportRowResult.objects.filter(release=release)
        if results.exists():
            return release, {"already_loaded": True, **_summarise(release, model)}

        existing = {t.code: t for t in model.objects.all()}
        source = fda_source_for(release, label)
        for number, (term, code) in enumerate(terms, start=1):
            current = existing.get(code)
            if current is None:
                current = model.objects.create(
                    code=code, canonical_label=term, fda_source=source, lifecycle="draft"
                )
                outcome = NEW
            elif current.canonical_label == term:
                outcome = UNCHANGED
            else:
                outcome = LABEL_CHANGED
            FdaImportRowResult.objects.create(
                release=release,
                row_locator=f"row:{number}",
                target_public_identifier=current.public_id,
                result=FdaImportRowResultType.IMPORTED,
                reason_code=outcome,
                # The snapshot's label; applied only when the release is activated.
                safe_detail=term if outcome == LABEL_CHANGED else "",
            )

        release.record_count_expected = len(terms)
        release.record_count_extracted = len(terms)
        release.record_count_imported = len(terms)
        release.record_count_failed = 0
        release.imported_at = timezone.now()
        release.save(
            update_fields=[
                "record_count_expected",
                "record_count_extracted",
                "record_count_imported",
                "record_count_failed",
                "imported_at",
                "updated_at",
            ]
        )
    return release, {"already_loaded": False, **_summarise(release, model)}


def _summarise(release: FDADataSourceRelease, model) -> dict:
    results = FdaImportRowResult.objects.filter(release=release)
    listed = set(results.values_list("target_public_identifier", flat=True))
    return {
        "terms": results.count(),
        NEW: results.filter(reason_code=NEW).count(),
        UNCHANGED: results.filter(reason_code=UNCHANGED).count(),
        LABEL_CHANGED: results.filter(reason_code=LABEL_CHANGED).count(),
        "not_in_snapshot": model.objects.exclude(public_id__in=listed)
        .exclude(lifecycle="retired")
        .count(),
    }


def apply_on_activation(release: FDADataSourceRelease) -> None:
    """Called by `lifecycle.activate` inside its transaction, after the
    release itself became ACTIVE. Never called at load time."""
    _, model, label = next(v for v in SPL_LISTS.values() if v[0] == release.dataset_type)
    source = fda_source_for(release, label)
    listed = []
    for result in FdaImportRowResult.objects.filter(release=release):
        term = model.objects.select_for_update().get(public_id=result.target_public_identifier)
        if result.reason_code == LABEL_CHANGED and term.canonical_label != result.safe_detail:
            if term.canonical_label not in term.aliases:
                term.aliases = [*term.aliases, term.canonical_label]
            term.canonical_label = result.safe_detail
        term.lifecycle = "active"
        term.active_release = release
        term.fda_source = source
        term.save()
        listed.append(term.pk)
    model.objects.exclude(pk__in=listed).exclude(lifecycle="retired").update(
        lifecycle="retired", updated_at=timezone.now()
    )
