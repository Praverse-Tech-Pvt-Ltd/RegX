"""Reconciliation report generation for a migration batch (JSON and CSV).

Deliberately does not attempt final branded PDF/Word reporting -- that is
explicitly out of scope for this milestone.
"""

import csv
import io

from .models import (
    MigrationRecordResult,
    MigrationRecordResultType,
    NormalizationMapping,
    TemplateApproval,
    TemplateDuplicateCandidate,
    TemplateSourceRecord,
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
    from django.db.models import Q

    duplicate_qs = TemplateDuplicateCandidate.objects.filter(
        Q(subject_source_record__source_package=batch.source_package)
        | Q(
            subject_template_item__template_section__template_version__source_package=(
                batch.source_package
            )
        )
    )

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
        "normalization_mappings": [
            {
                "source_record_identifier": m.source_record.source_record_identifier,
                "field_name": m.field_name,
                "normalization_rule": m.normalization_rule,
                "reviewer": m.reviewer.email if m.reviewer else None,
            }
            for m in mapping_qs
        ],
        "duplicate_candidates": [
            {
                "match_type": d.match_type,
                "resolution": d.resolution,
                "reviewer": d.reviewer.email if d.reviewer else None,
            }
            for d in duplicate_qs.distinct()
        ],
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
                row["source_record_identifier"],
                row["target_public_identifier"] or "",
                row["result"],
                row["reason_code"],
            ]
        )
    return buffer.getvalue()
