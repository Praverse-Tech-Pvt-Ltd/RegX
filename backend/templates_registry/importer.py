"""
Staged import pipeline orchestration.

register_source_package -> checksum -> extract -> preserve raw ->
validate schema -> classify -> normalize -> generate duplicate candidates
-> import (inactive) -> reconciliation report -> regulatory review ->
approval -> controlled activation.

Guarantees:
- idempotent: rerunning a batch never creates duplicate SourceRecord,
  MigrationRecordResult, or TemplateItem rows for the same identifier;
- every source record gets exactly one MigrationRecordResult per batch;
- imported content is always DRAFT/IMPORTED, never auto-activated;
- transaction boundaries wrap each record's import so a mid-batch failure
  cannot leave a partially-created TemplateItem tree.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from .audit_events import TemplateEvent, emit
from .checksums import sha256_payload, sha256_text
from .classification import classify_source_package, classify_source_record
from .duplicates import find_duplicate_candidates_for_item
from .models import (
    MigrationBatch,
    MigrationBatchStatus,
    MigrationDisposition,
    MigrationRecordResult,
    MigrationRecordResultType,
    RegulatoryTemplate,
    ResponseType,
    TemplateItem,
    TemplateLifecycleStatus,
    TemplateSection,
    TemplateSourcePackage,
    TemplateSourceRecord,
    TemplateVersion,
)
from .normalization import normalize_category_value, normalize_text_field


class SourceExcluded(Exception):
    """Raised by register_source_package when the package itself is
    disallowed content (483/warning-letter/AIDatabase-sourced)."""


def register_source_package(
    *,
    tenant,
    source_name: str,
    source_type: str,
    source_path_or_reference: str,
    payload_for_checksum: dict,
    file_metadata: dict | None = None,
    source_version: str = "",
    source_date=None,
    licensing_ownership_status: str = "",
    imported_by=None,
) -> TemplateSourcePackage:
    exclusion = classify_source_package(source_type, source_name)
    if exclusion:
        raise SourceExcluded(f"Source package rejected: {exclusion}")

    checksum = sha256_payload(payload_for_checksum)
    package, created = TemplateSourcePackage.objects.get_or_create(
        tenant=tenant,
        source_checksum=checksum,
        defaults={
            "source_name": source_name,
            "source_type": source_type,
            "source_path_or_reference": source_path_or_reference,
            "file_metadata": file_metadata or {},
            "source_version": source_version,
            "source_date": source_date,
            "licensing_ownership_status": licensing_ownership_status,
            "imported_by": imported_by,
        },
    )
    if created:
        emit(
            event_type=TemplateEvent.SOURCE_PACKAGE_REGISTERED,
            resource_type="template_source_package",
            resource_id=str(package.public_id),
            tenant_id=getattr(tenant, "id", None),
            payload={"source_name": source_name, "checksum": checksum},
            actor_id=getattr(imported_by, "id", None),
            actor_email=getattr(imported_by, "email", ""),
        )
    return package


def create_migration_batch(source_package: TemplateSourcePackage, actor) -> MigrationBatch:
    batch = MigrationBatch.objects.create(
        tenant=source_package.tenant,
        source_package=source_package,
        status=MigrationBatchStatus.REGISTERED,
        started_by=actor,
    )
    emit(
        event_type=TemplateEvent.MIGRATION_BATCH_STARTED,
        resource_type="migration_batch",
        resource_id=str(batch.public_id),
        tenant_id=getattr(source_package.tenant, "id", None),
        payload={"correlation_id": str(batch.correlation_id)},
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", ""),
    )
    return batch


def extract_records(
    batch: MigrationBatch, neutral_records: list[dict]
) -> list[TemplateSourceRecord]:
    """Idempotent: reruns with the same neutral_records list produce the
    same TemplateSourceRecord rows (get_or_create keyed on identifier),
    never duplicates."""
    batch.status = MigrationBatchStatus.EXTRACTING
    batch.save(update_fields=["status", "updated_at"])

    extracted = []
    for record in neutral_records:
        raw_text = record.get("raw_text", "")
        source_record, _created = TemplateSourceRecord.objects.get_or_create(
            source_package=batch.source_package,
            source_record_identifier=record["identifier"],
            defaults={
                # "fields" (the structural template/section/item mapping)
                # is preserved alongside the original row so
                # _import_single_record can read it back out of the
                # persisted TemplateSourceRecord -- see the neutral record
                # schema docstring above.
                "raw_payload": {
                    **record.get("raw_payload", {}),
                    "fields": record.get("fields", {}),
                },
                "raw_text": raw_text,
                "raw_checksum": sha256_text(raw_text),
                "source_locator": record.get("locator", ""),
                "extraction_method": record.get("extraction_method", ""),
                "encoding": record.get("encoding", "utf-8"),
                "migration_disposition": MigrationDisposition.PENDING,
            },
        )
        extracted.append(source_record)
        emit(
            event_type=TemplateEvent.SOURCE_RECORD_EXTRACTED,
            resource_type="template_source_record",
            resource_id=str(source_record.public_id),
            tenant_id=getattr(batch.tenant, "id", None),
            payload={"batch": str(batch.correlation_id)},
        )

    counts = dict(batch.counts or {})
    counts["extracted"] = len(extracted)
    batch.counts = counts
    batch.save(update_fields=["counts", "updated_at"])
    return extracted


def classify_records(batch: MigrationBatch) -> None:
    batch.status = MigrationBatchStatus.CLASSIFYING
    batch.save(update_fields=["status", "updated_at"])

    excluded = 0
    eligible = 0
    for record in TemplateSourceRecord.objects.filter(
        source_package=batch.source_package, migration_disposition=MigrationDisposition.PENDING
    ):
        reason = classify_source_record(
            record.source_record_identifier,
            record.raw_text,
            record.raw_payload,
            record.source_locator,
        )
        if reason:
            record.migration_disposition = MigrationDisposition.EXCLUDED
            record.save(update_fields=["migration_disposition", "updated_at"])
            MigrationRecordResult.objects.get_or_create(
                batch=batch,
                source_record=record,
                defaults={
                    "result": MigrationRecordResultType.EXCLUDED,
                    "reason_code": reason,
                    "safe_detail": "Record excluded during classification.",
                },
            )
            emit(
                event_type=TemplateEvent.SOURCE_RECORD_EXCLUDED,
                resource_type="template_source_record",
                resource_id=str(record.public_id),
                tenant_id=getattr(batch.tenant, "id", None),
                payload={"reason": reason},
            )
            excluded += 1
        else:
            record.migration_disposition = MigrationDisposition.ELIGIBLE
            record.save(update_fields=["migration_disposition", "updated_at"])
            eligible += 1

    counts = dict(batch.counts or {})
    counts["excluded"] = counts.get("excluded", 0) + excluded
    counts["eligible"] = counts.get("eligible", 0) + eligible
    batch.counts = counts
    batch.save(update_fields=["counts", "updated_at"])


def _get_or_create_template(tenant, canonical_code: str, title: str, category: str, created_by):
    template, _ = RegulatoryTemplate.objects.get_or_create(
        tenant=tenant,
        canonical_code=canonical_code,
        defaults={"title": title, "category": category, "created_by": created_by},
    )
    return template


def _get_or_create_draft_version(template: RegulatoryTemplate, source_package, created_by):
    """Every import batch for a template lands in its own new
    draft/imported version (never edits an existing version, immutable or
    not) -- corrections and re-imports both flow through new versions.

    Concurrency: two imports for the same template running at the same time
    must not race on the next version_number. select_for_update() locks the
    parent RegulatoryTemplate row before computing it, so a second concurrent
    caller blocks until the first commits (and then sees its new version via
    the re-check below) instead of independently computing the same number.
    The unique_template_version_number DB constraint remains a backstop; a
    small bounded retry absorbs the rare case where it still fires (e.g. a
    caller reusing a connection/isolation level that doesn't block on the
    row lock the way default PostgreSQL READ COMMITTED does)."""
    existing_draft = TemplateVersion.objects.filter(
        template=template,
        source_package=source_package,
        status__in=[TemplateLifecycleStatus.DRAFT, TemplateLifecycleStatus.IMPORTED],
    ).first()
    if existing_draft:
        return existing_draft

    for _attempt in range(3):
        try:
            with transaction.atomic():
                RegulatoryTemplate.objects.select_for_update().get(pk=template.pk)
                # Re-check now that we hold the lock -- another concurrent
                # import for this exact template+source_package may have
                # created the draft between the unlocked check above and
                # acquiring the lock here.
                existing_draft = TemplateVersion.objects.filter(
                    template=template,
                    source_package=source_package,
                    status__in=[
                        TemplateLifecycleStatus.DRAFT,
                        TemplateLifecycleStatus.IMPORTED,
                    ],
                ).first()
                if existing_draft:
                    return existing_draft
                last_version = (
                    TemplateVersion.objects.filter(template=template)
                    .order_by("-version_number")
                    .first()
                )
                next_number = (last_version.version_number + 1) if last_version else 1
                return TemplateVersion.objects.create(
                    template=template,
                    version_number=next_number,
                    source_package=source_package,
                    status=TemplateLifecycleStatus.IMPORTED,
                    created_by=created_by,
                )
        except IntegrityError:
            continue
    raise IntegrityError(
        f"Could not allocate a version number for template {template.pk} after 3 attempts."
    )


def _get_or_create_section(
    version: TemplateVersion, code: str, raw_title: str, normalized_title: str
):
    section, _ = TemplateSection.objects.get_or_create(
        template_version=version,
        canonical_section_code=code,
        defaults={"raw_title": raw_title, "normalized_title": normalized_title},
    )
    return section


def import_eligible_records(
    batch: MigrationBatch, actor, category_mapping_table: dict[str, str] | None = None
) -> None:
    """Normalize, duplicate-check, and import every ELIGIBLE (not yet
    resulted) source record in this batch as an inactive TemplateItem
    under a new draft/imported TemplateVersion. Idempotent: a source
    record that already has a MigrationRecordResult for this batch is
    skipped, not reprocessed."""
    batch.status = MigrationBatchStatus.NORMALIZING
    batch.save(update_fields=["status", "updated_at"])

    already_resulted_ids = set(
        MigrationRecordResult.objects.filter(batch=batch).values_list("source_record_id", flat=True)
    )

    imported = 0
    requires_review = 0
    failed = 0

    for record in TemplateSourceRecord.objects.filter(
        source_package=batch.source_package, migration_disposition=MigrationDisposition.ELIGIBLE
    ).exclude(pk__in=already_resulted_ids):
        try:
            with transaction.atomic():
                imported_ok, item, needs_review = _import_single_record(
                    batch, record, actor, category_mapping_table
                )
                result_type = (
                    MigrationRecordResultType.REQUIRES_REVIEW
                    if needs_review
                    else MigrationRecordResultType.IMPORTED
                )
                MigrationRecordResult.objects.create(
                    batch=batch,
                    source_record=record,
                    target_public_identifier=item.public_id if item else None,
                    result=result_type,
                    reason_code="duplicate_candidates_found" if needs_review else "",
                )
                if needs_review:
                    requires_review += 1
                else:
                    imported += 1
                if item:
                    emit(
                        event_type=TemplateEvent.VERSION_IMPORTED,
                        resource_type="template_item",
                        resource_id=str(item.public_id),
                        tenant_id=getattr(batch.tenant, "id", None),
                        payload={"batch": str(batch.correlation_id)},
                        actor_id=getattr(actor, "id", None),
                        actor_email=getattr(actor, "email", ""),
                    )
        except Exception as exc:
            MigrationRecordResult.objects.get_or_create(
                batch=batch,
                source_record=record,
                defaults={
                    "result": MigrationRecordResultType.FAILED,
                    "reason_code": "import_exception",
                    "safe_detail": str(exc)[:500],
                },
            )
            failed += 1

    counts = dict(batch.counts or {})
    counts["imported"] = counts.get("imported", 0) + imported
    counts["requires_review"] = counts.get("requires_review", 0) + requires_review
    counts["failed"] = counts.get("failed", 0) + failed
    batch.counts = counts
    batch.status = MigrationBatchStatus.COMPLETED
    batch.completed_at = _now()
    batch.save(update_fields=["counts", "status", "completed_at", "updated_at"])

    emit(
        event_type=TemplateEvent.MIGRATION_BATCH_COMPLETED,
        resource_type="migration_batch",
        resource_id=str(batch.public_id),
        tenant_id=getattr(batch.tenant, "id", None),
        payload=counts,
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", ""),
    )


def _import_single_record(batch, record, actor, category_mapping_table):
    # extract_records() always stores the neutral record's "fields" dict
    # (the template/section/item structural mapping) under
    # raw_payload["fields"] -- see extract_records() and the module
    # docstring's neutral record schema.
    fields = record.raw_payload.get("fields") or {}

    text_result = normalize_text_field(record.raw_text)
    for step in text_result["steps"]:
        _record_normalization_mapping(record, step)

    category_result = normalize_category_value(
        fields.get("template_category", ""), category_mapping_table
    )
    if category_result["changed"]:
        _record_normalization_mapping(
            record,
            {
                "rule": category_result["rule"],
                "raw_value": fields.get("template_category", ""),
                "normalized_value": category_result["normalized_value"],
            },
        )

    template = _get_or_create_template(
        tenant=batch.tenant,
        canonical_code=fields.get("template_canonical_code", f"UNSPECIFIED-{record.pk}"),
        title=fields.get("template_title", "Untitled Template"),
        category=category_result["normalized_value"],
        created_by=actor,
    )
    version = _get_or_create_draft_version(template, batch.source_package, actor)
    section = _get_or_create_section(
        version,
        code=fields.get("section_code", "general"),
        raw_title=fields.get("section_title", "General"),
        normalized_title=fields.get("section_title", "General"),
    )

    response_type = fields.get("response_type", ResponseType.NARRATIVE)
    if response_type not in ResponseType.values:
        response_type = ResponseType.NARRATIVE

    item, item_created = TemplateItem.objects.get_or_create(
        template_section=section,
        canonical_item_code=fields.get("item_code", f"item-{record.pk}"),
        defaults={
            "raw_text": record.raw_text,
            "normalized_text": text_result["normalized_text"],
            "response_type": response_type,
            "required": bool(fields.get("required", False)),
            "legacy_identifier": record.source_record_identifier,
            "source_locator": record.source_locator,
            "metadata": {
                "numbering_prefix": text_result["numbering_prefix"],
                "raw_source_record": str(record.public_id),
            },
        },
    )

    needs_review = False
    if item_created:
        candidates = find_duplicate_candidates_for_item(item)
        if candidates:
            needs_review = True
            for candidate in candidates:
                emit(
                    event_type=TemplateEvent.DUPLICATE_CANDIDATE_CREATED,
                    resource_type="template_duplicate_candidate",
                    resource_id=str(candidate.public_id),
                    tenant_id=getattr(batch.tenant, "id", None),
                    payload={"match_type": candidate.match_type},
                )

    return True, item, needs_review


def _record_normalization_mapping(record: TemplateSourceRecord, step: dict) -> None:
    from .models import NormalizationMapping

    NormalizationMapping.objects.get_or_create(
        source_record=record,
        field_name=step["rule"],
        raw_value=step["raw_value"],
        normalized_value=step["normalized_value"],
        normalization_rule=step["rule"],
    )
    emit(
        event_type=TemplateEvent.NORMALIZATION_APPLIED,
        resource_type="template_source_record",
        resource_id=str(record.public_id),
        payload={"rule": step["rule"]},
    )


def _now():
    from django.utils import timezone

    return timezone.now()


def run_migration_batch(
    batch: MigrationBatch,
    neutral_records: list[dict],
    actor,
    category_mapping_table: dict[str, str] | None = None,
) -> MigrationBatch:
    """Convenience wrapper running the full extract -> classify -> import
    sequence for a batch. Safe to call again with the same neutral_records
    for the same batch -- every stage is independently idempotent."""
    try:
        extract_records(batch, neutral_records)
        classify_records(batch)
        import_eligible_records(batch, actor, category_mapping_table)
    except Exception as exc:
        batch.status = MigrationBatchStatus.FAILED
        batch.error_summary = str(exc)[:2000]
        batch.completed_at = _now()
        batch.save(update_fields=["status", "error_summary", "completed_at", "updated_at"])
        emit(
            event_type=TemplateEvent.MIGRATION_BATCH_FAILED,
            resource_type="migration_batch",
            resource_id=str(batch.public_id),
            tenant_id=getattr(batch.tenant, "id", None),
            payload={"error": str(exc)[:500]},
        )
        raise
    return batch
