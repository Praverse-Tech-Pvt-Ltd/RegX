"""Reconciliation report generation for a migration batch (JSON and CSV).

Deliberately does not attempt final branded PDF/Word reporting -- that is
explicitly out of scope for this milestone.
"""

import csv
import io

from django.db.models import Q

from .models import (
    MigrationRecordResult,
    MigrationRecordResultType,
    NormalizationMapping,
    TemplateApproval,
    TemplateDuplicateCandidate,
    TemplateSourceRecord,
)
from .serializers import NormalizationMappingSerializer, TemplateDuplicateCandidateSerializer

# Any string whose effective first character (after skipping plain leading
# spaces) is one of these is a formula/DDE trigger in Excel, Google Sheets,
# and LibreOffice (CWE-1236). A leading apostrophe is the standard,
# universally-supported "force text" escape: it makes the affected cell
# display its original value verbatim while never being evaluated.
_CSV_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r", "\n")


def _csv_safe_cell(value) -> str:
    """Neutralize a single CSV cell value against spreadsheet formula
    injection. This only affects the rendered export -- it never touches
    the underlying database value (callers pass in already-fetched strings;
    nothing here performs a .save())."""
    text = "" if value is None else str(value)
    effective_first_char = text.lstrip(" ")[:1]
    if effective_first_char in _CSV_FORMULA_TRIGGER_CHARS:
        return "'" + text
    return text


def duplicate_candidates_for_source_package(source_package):
    """Every TemplateDuplicateCandidate whose "new" side traces back to this
    source package, via either subject form (subject_source_record or
    subject_template_item). Shared by the reconciliation report and the
    duplicate-review endpoint so a candidate can only ever be reported on or
    resolved within the scope of the source package it actually belongs to
    -- never by public_id alone."""
    return TemplateDuplicateCandidate.objects.filter(
        Q(subject_source_record__source_package=source_package)
        | Q(
            subject_template_item__template_section__template_version__source_package=(
                source_package
            )
        )
    )


def build_reconciliation_report(batch) -> dict:
    results = MigrationRecordResult.objects.filter(batch=batch).select_related("source_record")
    all_source_records = TemplateSourceRecord.objects.filter(source_package=batch.source_package)

    by_result = {}
    for result_type in MigrationRecordResultType.values:
        by_result[result_type] = results.filter(result=result_type).count()

    unmatched = all_source_records.exclude(
        pk__in=results.values_list("source_record_id", flat=True)
    )

    mapping_qs = NormalizationMapping.objects.filter(
        source_record__source_package=batch.source_package
    )

    duplicate_qs = duplicate_candidates_for_source_package(batch.source_package)

    approvals = TemplateApproval.objects.filter(
        template_version__source_package=batch.source_package
    ).select_related("reviewer")

    return {
        "batch": {
            "correlation_id": str(batch.correlation_id),
            "public_id": str(batch.public_id),
            "status": batch.status,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        },
        "source_package": {
            "public_id": str(batch.source_package.public_id),
            "source_name": batch.source_package.source_name,
            "source_checksum": batch.source_package.source_checksum,
        },
        "counts": {
            "expected_records": all_source_records.count(),
            "extracted_records": all_source_records.count(),
            "imported": by_result.get(MigrationRecordResultType.IMPORTED, 0),
            "excluded": by_result.get(MigrationRecordResultType.EXCLUDED, 0),
            "duplicate": by_result.get(MigrationRecordResultType.DUPLICATE, 0),
            "failed": by_result.get(MigrationRecordResultType.FAILED, 0),
            "requires_review": by_result.get(MigrationRecordResultType.REQUIRES_REVIEW, 0),
            "unmatched": unmatched.count(),
        },
        "records": [
            {
                "source_record_identifier": r.source_record.source_record_identifier,
                "target_public_identifier": str(r.target_public_identifier)
                if r.target_public_identifier
                else None,
                "result": r.result,
                "reason_code": r.reason_code,
                "safe_detail": r.safe_detail,
            }
            for r in results
        ],
        "unmatched_records": [
            {
                "source_record_identifier": r.source_record_identifier,
                "migration_disposition": r.migration_disposition,
            }
            for r in unmatched
        ],
        "normalization_mappings": NormalizationMappingSerializer(
            mapping_qs.select_related("source_record", "reviewer"), many=True
        ).data,
        "duplicate_candidates": TemplateDuplicateCandidateSerializer(
            duplicate_qs.select_related("reviewer", "suspected_match_item").distinct(), many=True
        ).data,
        "approvals": [
            {
                "template_version": str(a.template_version.public_id),
                "reviewer": a.reviewer.email if a.reviewer else None,
                "decision": a.decision,
                "approval_sequence": a.approval_sequence,
                "role_at_time": a.role_at_time,
            }
            for a in approvals
        ],
    }


def render_reconciliation_csv(report: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["source_record_identifier", "target_public_identifier", "result", "reason_code"]
    )
    for row in report["records"]:
        writer.writerow(
            [
                _csv_safe_cell(row["source_record_identifier"]),
                _csv_safe_cell(row["target_public_identifier"] or ""),
                _csv_safe_cell(row["result"]),
                _csv_safe_cell(row["reason_code"]),
            ]
        )
    return buffer.getvalue()
