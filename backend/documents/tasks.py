"""
Celery processing tasks for the document platform.

Rules:
- Processing begins only after validation and clean scan.
- Tasks are idempotent — re-running produces the same result.
- Bounded retry with permanent vs retryable failure classification.
- Tenant context passed explicitly; no unscoped queries.
- No cross-tenant information access.
- Correlation ID tracked throughout.
"""

import io
import logging

from celery import shared_task
from django.utils import timezone

from .audit_events import DocumentEvent, emit
from .models import (
    DocumentProcessingJob,
    DocumentVersion,
    JobStatus,
    LocatorType,
    ProcessingStatus,
    ScanStatus,
)
from .scanner import ScanResult, get_scanner_backend
from .storage import get_storage_backend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scan task
# ---------------------------------------------------------------------------

MAX_SCAN_ATTEMPTS = 3
MAX_PROCESS_ATTEMPTS = 3


@shared_task(bind=True, max_retries=MAX_SCAN_ATTEMPTS, default_retry_delay=30)
def scan_document_version(self, version_pk: int, tenant_id: int) -> None:
    """Run malware scan on a document version.

    Fail-closed: scan failures do NOT mark the file clean.
    """
    try:
        version = DocumentVersion.objects.select_related("document__tenant").get(
            pk=version_pk,
            document__tenant_id=tenant_id,
        )
    except DocumentVersion.DoesNotExist:
        logger.error(
            "scan_document_version: version %s not found for tenant %s", version_pk, tenant_id
        )
        return

    # Idempotency: skip if already resolved
    if version.scan_status in (ScanStatus.CLEAN, ScanStatus.QUARANTINED):
        return

    storage = get_storage_backend()
    try:
        file_obj = storage.retrieve(version.storage_key)
    except Exception as exc:
        logger.error("scan_document_version: storage retrieval failed: %s", exc)
        version.scan_status = ScanStatus.SCAN_FAILED
        version.save(update_fields=["scan_status"])
        emit(
            event_type=DocumentEvent.SCAN_FAILED,
            resource_id=str(version.public_id),
            tenant_id=tenant_id,
            payload={"error": str(exc)[:200]},
        )
        return

    try:
        scanner = get_scanner_backend()
        outcome = scanner.scan(file_obj)
    finally:
        file_obj.close()

    if outcome.result == ScanResult.CLEAN:
        version.scan_status = ScanStatus.CLEAN
        version.save(update_fields=["scan_status"])
        emit(
            event_type=DocumentEvent.SCAN_COMPLETE,
            resource_id=str(version.public_id),
            tenant_id=tenant_id,
            payload={"result": "clean"},
        )
        # Trigger processing
        process_document_version.delay(version_pk, tenant_id)

    elif outcome.result == ScanResult.INFECTED:
        version.scan_status = ScanStatus.QUARANTINED
        version.processing_status = ProcessingStatus.SKIPPED
        version.failure_code = "infected"
        version.failure_detail = "File was quarantined after malware detection."
        version.save(
            update_fields=["scan_status", "processing_status", "failure_code", "failure_detail"]
        )
        emit(
            event_type=DocumentEvent.SCAN_INFECTED,
            resource_id=str(version.public_id),
            tenant_id=tenant_id,
            payload={"threat": outcome.threat_name[:200] if outcome.threat_name else ""},
        )
        emit(
            event_type=DocumentEvent.QUARANTINED,
            resource_id=str(version.public_id),
            tenant_id=tenant_id,
        )

    elif outcome.result in (ScanResult.SCAN_FAILED, ScanResult.SCANNER_UNAVAILABLE):
        version.scan_status = ScanStatus.SCAN_FAILED
        version.save(update_fields=["scan_status"])
        emit(
            event_type=DocumentEvent.SCAN_FAILED,
            resource_id=str(version.public_id),
            tenant_id=tenant_id,
            payload={"detail": outcome.detail[:200]},
        )
        # Retry for transient failures
        raise self.retry(exc=RuntimeError(outcome.detail))


# ---------------------------------------------------------------------------
# Processing task
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=MAX_PROCESS_ATTEMPTS, default_retry_delay=60)
def process_document_version(self, version_pk: int, tenant_id: int) -> None:
    """Extract locators and metadata from a validated, clean document version."""
    try:
        version = DocumentVersion.objects.select_related("document__tenant").get(
            pk=version_pk,
            document__tenant_id=tenant_id,
        )
    except DocumentVersion.DoesNotExist:
        logger.error(
            "process_document_version: version %s not found for tenant %s", version_pk, tenant_id
        )
        return

    # Guard: must be clean before processing
    if version.scan_status != ScanStatus.CLEAN:
        logger.warning(
            "process_document_version: version %s scan_status=%s — skipping",
            version_pk,
            version.scan_status,
        )
        return

    # Idempotency
    if version.processing_status == ProcessingStatus.COMPLETE:
        return

    # Create or get job record
    job, _ = DocumentProcessingJob.objects.get_or_create(
        version=version,
        job_type="extract",
        defaults={"status": JobStatus.QUEUED, "celery_task_id": self.request.id or ""},
    )

    if job.attempt_count >= job.max_attempts:
        job.status = JobStatus.FAILED_PERMANENT
        job.error_message = "Maximum processing attempts exceeded."
        job.save(update_fields=["status", "error_message"])
        version.processing_status = ProcessingStatus.FAILED
        version.failure_code = "max_attempts_exceeded"
        version.failure_detail = "Document processing failed after maximum retries."
        version.save(update_fields=["processing_status", "failure_code", "failure_detail"])
        return

    job.status = JobStatus.RUNNING
    job.attempt_count += 1
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id or ""
    job.save(update_fields=["status", "attempt_count", "started_at", "celery_task_id"])

    version.processing_status = ProcessingStatus.PROCESSING
    version.processing_started_at = timezone.now()
    version.save(update_fields=["processing_status", "processing_started_at"])

    emit(
        event_type=DocumentEvent.PROCESSING_STARTED,
        resource_id=str(version.public_id),
        tenant_id=tenant_id,
    )

    storage = get_storage_backend()
    try:
        file_obj = storage.retrieve(version.storage_key)
        raw = file_obj.read()
        file_obj.close()
    except Exception as exc:
        _fail_job(job, version, "storage_error", str(exc)[:200], retryable=True)
        raise self.retry(exc=exc) from exc

    try:
        ext = version.extension.lower()
        if ext == "pdf":
            _process_pdf(version, raw)
        elif ext == "docx":
            _process_docx(version, raw)
        elif ext == "xlsx":
            _process_xlsx(version, raw)
        elif ext == "pptx":
            _process_pptx(version, raw)

        job.status = JobStatus.SUCCESS
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])

        version.processing_status = ProcessingStatus.COMPLETE
        version.processing_finished_at = timezone.now()
        version.save(update_fields=["processing_status", "processing_finished_at"])

        emit(
            event_type=DocumentEvent.PROCESSING_COMPLETE,
            resource_id=str(version.public_id),
            tenant_id=tenant_id,
        )

    except Exception as exc:
        logger.exception("process_document_version failed for version %s", version_pk)
        _fail_job(job, version, "processing_error", str(exc)[:200], retryable=True)
        raise self.retry(exc=exc) from exc


def _fail_job(job, version, code: str, detail: str, *, retryable: bool) -> None:
    job.status = JobStatus.FAILED_RETRYABLE if retryable else JobStatus.FAILED_PERMANENT
    job.error_code = code
    job.error_message = detail
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_code", "error_message", "finished_at"])

    version.processing_status = ProcessingStatus.FAILED
    version.failure_code = code
    version.failure_detail = detail
    version.save(update_fields=["processing_status", "failure_code", "failure_detail"])


# ---------------------------------------------------------------------------
# Format-specific extractors
# ---------------------------------------------------------------------------


def _create_locator(
    version, locator_type, locator_id, display_label="", metadata=None, text="", order=0
):
    from .models import DocumentLocator

    DocumentLocator.objects.get_or_create(
        version=version,
        locator_type=locator_type,
        locator_id=str(locator_id),
        defaults={
            "display_label": display_label[:500],
            "structured_metadata": metadata or {},
            "extracted_text": text[:10000],
            "ordering": order,
        },
    )


def _process_pdf(version, raw: bytes) -> None:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(raw))
    page_count = len(reader.pages)

    # Source metadata
    meta = {}
    if reader.metadata:
        for key in ("/Title", "/Author", "/Creator", "/Producer"):
            val = reader.metadata.get(key)
            if val:
                meta[key.lstrip("/")] = str(val)[:500]

    version.source_metadata = {"page_count": page_count, **meta}
    version.save(update_fields=["source_metadata"])

    for i, page in enumerate(reader.pages):
        text = ""
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: S110
            pass
        _create_locator(
            version,
            LocatorType.PAGE,
            i + 1,
            display_label=f"Page {i + 1}",
            metadata={"page_number": i + 1},
            text=text[:10000],
            order=i,
        )


def _process_docx(version, raw: bytes) -> None:
    import docx

    doc = docx.Document(io.BytesIO(raw))

    # Core properties
    meta = {}
    try:
        cp = doc.core_properties
        for attr in ("title", "author", "created", "modified"):
            val = getattr(cp, attr, None)
            if val is not None:
                meta[attr] = str(val)[:500]
    except Exception:  # noqa: S110
        pass

    version.source_metadata = meta
    version.save(update_fields=["source_metadata"])

    order = 0
    para_idx = 0
    table_idx = 0
    section_idx = 0

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        if "Heading" in style_name:
            _create_locator(
                version,
                LocatorType.SECTION,
                f"heading-{section_idx}",
                display_label=para.text[:200] or f"Section {section_idx + 1}",
                metadata={"style": style_name},
                text=para.text[:10000],
                order=order,
            )
            section_idx += 1
        else:
            _create_locator(
                version,
                LocatorType.PARAGRAPH,
                f"para-{para_idx}",
                display_label=f"Paragraph {para_idx + 1}",
                metadata={"style": style_name},
                text=para.text[:10000],
                order=order,
            )
            para_idx += 1
        order += 1

    for table in doc.tables:
        _create_locator(
            version,
            LocatorType.TABLE,
            f"table-{table_idx}",
            display_label=f"Table {table_idx + 1}",
            metadata={"rows": len(table.rows), "cols": len(table.columns)},
            order=order,
        )
        table_idx += 1
        order += 1


def _process_xlsx(version, raw: bytes) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    meta = {"sheet_count": len(wb.sheetnames)}
    version.source_metadata = meta
    version.save(update_fields=["source_metadata"])

    for idx, ws in enumerate(wb.worksheets):
        has_formulas = False
        try:
            # In data_only mode, formula results are returned
            # Check the raw XML for formula presence via zip
            import zipfile

            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                sheet_path = f"xl/worksheets/sheet{idx + 1}.xml"
                try:
                    sheet_xml = zf.read(sheet_path).decode("utf-8", errors="replace")
                    has_formulas = "<f>" in sheet_xml
                except KeyError:
                    pass
        except Exception:  # noqa: S110
            pass

        _create_locator(
            version,
            LocatorType.SHEET,
            f"sheet-{idx}",
            display_label=ws.title[:200],
            metadata={
                "sheet_index": idx,
                "sheet_name": ws.title,
                "max_row": ws.max_row,
                "max_column": ws.max_column,
                "has_formulas": has_formulas,
            },
            order=idx,
        )
    wb.close()


def _process_pptx(version, raw: bytes) -> None:
    import pptx

    prs = pptx.Presentation(io.BytesIO(raw))
    meta = {"slide_count": len(prs.slides)}
    try:
        cp = prs.core_properties
        for attr in ("title", "author"):
            val = getattr(cp, attr, None)
            if val:
                meta[attr] = str(val)[:500]
    except Exception:  # noqa: S110
        pass

    version.source_metadata = meta
    version.save(update_fields=["source_metadata"])

    for idx, slide in enumerate(prs.slides):
        text_parts = []
        table_count = 0
        object_count = 0

        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = para.text.strip()
                    if t:
                        text_parts.append(t[:500])
            if shape.has_table:
                table_count += 1
            object_count += 1

        title_text = ""
        try:
            if slide.shapes.title:
                title_text = slide.shapes.title.text or ""
        except Exception:  # noqa: S110
            pass

        _create_locator(
            version,
            LocatorType.SLIDE,
            f"slide-{idx}",
            display_label=title_text[:200] or f"Slide {idx + 1}",
            metadata={
                "slide_number": idx + 1,
                "table_count": table_count,
                "shape_count": object_count,
            },
            text="\n".join(text_parts)[:10000],
            order=idx,
        )
