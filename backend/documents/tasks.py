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
        # Dispatched inline, deliberately.
        #
        # The status write above is a bare `save()` with no enclosing
        # transaction, so it is already committed by the time this runs -- there
        # is nothing to defer to. Milestone 15 added `on_commit` here and then
        # removed it: no measurement showed a race, and the standard applied to
        # every other change in that milestone was to change what evidence
        # justified. A deferral that cannot fire is not defence in depth, it is
        # a claim that a hazard was addressed when none was found.
        #
        # The two paths that *do* defer are the ones a caller can wrap in a
        # transaction: `documents.ingest` and the two request handlers.
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
        # PROCESSING_STARTED and PROCESSING_COMPLETE were both audited; the
        # failure paths were not, so a document could end permanently FAILED
        # with the trail showing only that processing began.
        emit(
            event_type=DocumentEvent.PROCESSING_FAILED,
            resource_id=str(version.public_id),
            tenant_id=tenant_id,
            payload={
                "failure_code": "max_attempts_exceeded",
                "retryable": False,
                "attempt_count": job.attempt_count,
            },
        )
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
        text_summary = None
        if ext == "pdf":
            text_summary = _process_pdf(version, raw)
        elif ext == "docx":
            text_summary = _process_docx(version, raw)
        elif ext == "xlsx":
            text_summary = _process_xlsx(version, raw)
        elif ext == "pptx":
            text_summary = _process_pptx(version, raw)

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
        # The file was processed, so the status stays COMPLETE; but a file that
        # yielded no text at all (a scanned PDF, an empty Office file) gets its
        # own audited event, so "processed" is never silently read as "has
        # usable text".
        if text_summary and text_summary["result"] == TEXT_RESULT_NONE:
            emit(
                event_type=DocumentEvent.PROCESSING_NO_TEXT,
                resource_id=str(version.public_id),
                tenant_id=tenant_id,
                payload={
                    k: text_summary[k] for k in (*_SUMMARY_COUNT_KEYS, "unit") if k in text_summary
                },
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

    # `code` is a fixed internal identifier. `detail` is not -- it carries
    # str(exc), which for a parse failure can quote bytes of the document being
    # processed. The code and the retryable flag are enough to see what
    # happened; the detail stays on the row, where it can be deleted.
    emit(
        event_type=DocumentEvent.PROCESSING_FAILED,
        resource_id=str(version.public_id),
        tenant_id=version.document.tenant_id,
        payload={
            "failure_code": code,
            "retryable": retryable,
            "attempt_count": job.attempt_count,
        },
    )


# ---------------------------------------------------------------------------
# Format-specific extractors
# ---------------------------------------------------------------------------


#: Characters of extracted text kept per locator.
LOCATOR_TEXT_LIMIT = 10000


def _create_locator(
    version,
    locator_type,
    locator_id,
    display_label="",
    metadata=None,
    text="",
    order=0,
    original_length=None,
) -> bool:
    """Store one locator; keep at most LOCATOR_TEXT_LIMIT characters of text.

    Pass the full text. When some of it is not stored, the locator's metadata
    records `truncated: True`, `original_length` and `stored_length`, so cut-off
    text is never silent. `original_length` overrides len(text) when the caller
    already shortened the text (Excel stops reading a sheet past the limit;
    PowerPoint caps each paragraph). Returns True when text was truncated.
    """
    from .models import DocumentLocator

    stored = text[:LOCATOR_TEXT_LIMIT]
    full_length = len(text) if original_length is None else original_length
    truncated = full_length > len(stored)
    meta = dict(metadata or {})
    if truncated:
        meta.update(
            {"truncated": True, "original_length": full_length, "stored_length": len(stored)}
        )
    DocumentLocator.objects.get_or_create(
        version=version,
        locator_type=locator_type,
        locator_id=str(locator_id),
        defaults={
            "display_label": display_label[:500],
            "structured_metadata": meta,
            "extracted_text": stored,
            "ordering": order,
        },
    )
    return truncated


#: Per-page outcome of PDF text extraction, stored on the page locator's
#: structured_metadata["extraction_outcome"].
PAGE_TEXT = "text"  # the page yielded text
PAGE_NO_TEXT = "no_text"  # the page yielded 0 characters (e.g. a scanned image)
PAGE_ERROR = "error"  # extract_text() raised; the page is stored empty

#: Version-level result, stored in source_metadata["text_extraction"]["result"].
TEXT_RESULT_COMPLETE = "complete"  # every page has text
TEXT_RESULT_PARTIAL = "partial"  # some pages have text, some do not
TEXT_RESULT_NONE = "none"  # no page has text: no extractable text, likely scanned

_SUMMARY_COUNT_KEYS = ("total_pages", "pages_with_text", "pages_without_text", "pages_failed")

#: Office formats count in their own units; the summary keeps the PDF key names
#: (the API contract) and adds `unit`, so `total_pages` means "total units".
UNIT_SLIDE = "slide"
UNIT_SHEET = "sheet"
UNIT_BLOCK = "paragraph or table"  # Word: body paragraphs and tables


def _log_unit_failure(version, unit: str, index: int, exc: BaseException, what: str) -> None:
    """A WARNING naming the document, version, unit and exception class only:
    never extracted content, never str(exc), which can quote document bytes."""
    logger.warning(
        "%s failed (document=%s, version=%s, %s=%s, error=%s)",
        what,
        version.document.public_id,
        version.public_id,
        unit.replace(" ", "_"),
        index,
        type(exc).__name__,
    )


def _office_summary(
    version, unit: str, outcomes: list[str], *, truncated: int = 0, layout_blanks: bool = False
) -> dict:
    """Record the Office text-extraction summary on the version and return it.

    `outcomes` holds one PAGE_* value per unit. With `layout_blanks` (Word),
    empty units are layout (blank lines), not missing text: the result is
    `partial` only when a unit failed to extract, and `none` when nothing at
    all has text.
    """
    with_text = outcomes.count(PAGE_TEXT)
    without_text = outcomes.count(PAGE_NO_TEXT)
    failed = outcomes.count(PAGE_ERROR)
    total = len(outcomes)
    if with_text == 0:
        result = TEXT_RESULT_NONE
    elif failed or (without_text and not layout_blanks):
        result = TEXT_RESULT_PARTIAL
    else:
        result = TEXT_RESULT_COMPLETE
    summary = {
        "unit": unit,
        "total_pages": total,
        "pages_with_text": with_text,
        "pages_without_text": without_text,
        "pages_failed": failed,
        "pages_truncated": truncated,
        "result": result,
    }
    version.source_metadata = {**(version.source_metadata or {}), "text_extraction": summary}
    version.save(update_fields=["source_metadata"])
    if result == TEXT_RESULT_NONE:
        logger.warning(
            "office file has no extractable text (document=%s, version=%s, unit=%s, total=%s)",
            version.document.public_id,
            version.public_id,
            unit.replace(" ", "_"),
            total,
        )
    return summary


def _outcome(text: str) -> str:
    return PAGE_TEXT if text.strip() else PAGE_NO_TEXT


def _process_pdf(version, raw: bytes) -> dict:
    """Extract text per page. Returns the text-extraction summary.

    A page whose extraction yields nothing, or raises, is still stored (empty),
    but its outcome is recorded instead of being silently swallowed, and the
    version carries a summary so callers can tell "processed" from "has text".
    """
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

    with_text = without_text = failed = truncated = 0
    for i, page in enumerate(reader.pages):
        page_number = i + 1
        text = ""
        page_meta = {"page_number": page_number}
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            # Never log the text or str(exc) (it can quote document bytes);
            # identify the page and the exception class only.
            logger.warning(
                "pdf text extraction failed (document=%s, version=%s, page=%s, error=%s)",
                version.document.public_id,
                version.public_id,
                page_number,
                type(exc).__name__,
            )
            text = ""
            page_meta["extraction_outcome"] = PAGE_ERROR
            page_meta["extraction_error"] = type(exc).__name__
            failed += 1
        else:
            if text.strip():
                page_meta["extraction_outcome"] = PAGE_TEXT
                with_text += 1
            else:
                page_meta["extraction_outcome"] = PAGE_NO_TEXT
                without_text += 1
        truncated += _create_locator(
            version,
            LocatorType.PAGE,
            page_number,
            display_label=f"Page {page_number}",
            metadata=page_meta,
            text=text,
            order=i,
        )

    if with_text == 0:
        result = TEXT_RESULT_NONE
    elif with_text < page_count:
        result = TEXT_RESULT_PARTIAL
    else:
        result = TEXT_RESULT_COMPLETE
    summary = {
        "total_pages": page_count,
        "pages_with_text": with_text,
        "pages_without_text": without_text,
        "pages_failed": failed,
        "pages_truncated": truncated,
        "result": result,
    }
    version.source_metadata = {**version.source_metadata, "text_extraction": summary}
    version.save(update_fields=["source_metadata"])
    if result == TEXT_RESULT_NONE:
        logger.warning(
            "pdf has no extractable text, likely scanned (document=%s, version=%s, pages=%s)",
            version.document.public_id,
            version.public_id,
            page_count,
        )
    return summary


def _table_text(table) -> str:
    """Cell text of a Word table: cells joined by tabs, rows by newlines."""
    return "\n".join("\t".join(cell.text for cell in row.cells) for row in table.rows)


def _process_docx(version, raw: bytes) -> dict:
    """Paragraph, heading and table locators. Returns the text summary.

    A file that cannot be opened at all raises (processing FAILED, audited).
    Tables now carry their cell text, so a table-only document is not
    reported as having no text.
    """
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
    except Exception as exc:
        _log_unit_failure(version, "document", 0, exc, "docx metadata read")

    version.source_metadata = meta
    version.save(update_fields=["source_metadata"])

    order = 0
    para_idx = 0
    table_idx = 0
    section_idx = 0
    outcomes: list[str] = []
    truncated = 0

    for block_idx, para in enumerate(doc.paragraphs):
        meta_p = {}
        try:
            style_name = para.style.name if para.style else ""
            text = para.text or ""
            outcome = _outcome(text)
        except Exception as exc:
            _log_unit_failure(version, UNIT_BLOCK, block_idx, exc, "docx paragraph extraction")
            style_name, text, outcome = "", "", PAGE_ERROR
            meta_p["extraction_error"] = type(exc).__name__
        meta_p.update({"style": style_name, "extraction_outcome": outcome})
        if "Heading" in style_name:
            truncated += _create_locator(
                version,
                LocatorType.SECTION,
                f"heading-{section_idx}",
                display_label=text[:200] or f"Section {section_idx + 1}",
                metadata=meta_p,
                text=text,
                order=order,
            )
            section_idx += 1
        else:
            truncated += _create_locator(
                version,
                LocatorType.PARAGRAPH,
                f"para-{para_idx}",
                display_label=f"Paragraph {para_idx + 1}",
                metadata=meta_p,
                text=text,
                order=order,
            )
            para_idx += 1
        outcomes.append(outcome)
        order += 1

    for table in doc.tables:
        meta_t = {}
        try:
            meta_t = {"rows": len(table.rows), "cols": len(table.columns)}
            text = _table_text(table)
            outcome = _outcome(text)
        except Exception as exc:
            _log_unit_failure(version, "table", table_idx, exc, "docx table extraction")
            text, outcome = "", PAGE_ERROR
            meta_t["extraction_error"] = type(exc).__name__
        meta_t["extraction_outcome"] = outcome
        truncated += _create_locator(
            version,
            LocatorType.TABLE,
            f"table-{table_idx}",
            display_label=f"Table {table_idx + 1}",
            metadata=meta_t,
            text=text,
            order=order,
        )
        outcomes.append(outcome)
        table_idx += 1
        order += 1

    return _office_summary(version, UNIT_BLOCK, outcomes, truncated=truncated, layout_blanks=True)


def _sheet_text(ws, limit: int = LOCATOR_TEXT_LIMIT) -> tuple[str, int]:
    """Non-empty cell values of a sheet, tab-separated per row.

    Keeps rows only until `limit` characters are collected (the locator stores
    at most that much) but keeps counting, so it returns (text, full_length)
    and truncation can be recorded."""
    lines: list[str] = []
    kept = 0
    full_length = 0
    for row in ws.iter_rows(values_only=True):
        cells = [str(v) for v in row if v is not None and str(v).strip()]
        if not cells:
            continue
        line = "\t".join(cells)
        full_length += len(line) + (1 if full_length else 0)
        if kept < limit:
            lines.append(line)
            kept += len(line) + 1
    return "\n".join(lines), full_length


def _process_xlsx(version, raw: bytes) -> dict:
    """One locator per sheet, now carrying the sheet's cell text. Returns the
    text summary (a workbook whose sheets are all empty has no text)."""
    import zipfile

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    meta = {"sheet_count": len(wb.sheetnames)}
    version.source_metadata = meta
    version.save(update_fields=["source_metadata"])

    outcomes: list[str] = []
    truncated = 0
    for idx, ws in enumerate(wb.worksheets):
        has_formulas = False
        try:
            # In data_only mode, formula results are returned
            # Check the raw XML for formula presence via zip
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                sheet_path = f"xl/worksheets/sheet{idx + 1}.xml"
                try:
                    sheet_xml = zf.read(sheet_path).decode("utf-8", errors="replace")
                    has_formulas = "<f>" in sheet_xml
                except KeyError:
                    pass  # sheet part named differently: formula flag unknown, not an error
        except Exception as exc:
            _log_unit_failure(version, UNIT_SHEET, idx, exc, "xlsx formula detection")

        sheet_meta = {"sheet_index": idx, "sheet_name": ws.title, "has_formulas": has_formulas}
        try:
            sheet_meta["max_row"] = ws.max_row
            sheet_meta["max_column"] = ws.max_column
            text, full_length = _sheet_text(ws)
            outcome = _outcome(text)
        except Exception as exc:
            _log_unit_failure(version, UNIT_SHEET, idx, exc, "xlsx sheet extraction")
            text, outcome, full_length = "", PAGE_ERROR, 0
            sheet_meta["extraction_error"] = type(exc).__name__
        sheet_meta["extraction_outcome"] = outcome

        truncated += _create_locator(
            version,
            LocatorType.SHEET,
            f"sheet-{idx}",
            display_label=ws.title[:200],
            metadata=sheet_meta,
            text=text,
            order=idx,
            original_length=full_length,
        )
        outcomes.append(outcome)
    wb.close()
    return _office_summary(version, UNIT_SHEET, outcomes, truncated=truncated)


def _process_pptx(version, raw: bytes) -> dict:
    """One locator per slide. Returns the text summary (picture-only slides
    count as slides without text)."""
    import pptx

    prs = pptx.Presentation(io.BytesIO(raw))
    meta = {"slide_count": len(prs.slides)}
    try:
        cp = prs.core_properties
        for attr in ("title", "author"):
            val = getattr(cp, attr, None)
            if val:
                meta[attr] = str(val)[:500]
    except Exception as exc:
        _log_unit_failure(version, "presentation", 0, exc, "pptx metadata read")

    version.source_metadata = meta
    version.save(update_fields=["source_metadata"])

    outcomes: list[str] = []
    truncated = 0
    for idx, slide in enumerate(prs.slides):
        text_parts = []
        full_parts = []
        table_count = 0
        object_count = 0
        slide_meta = {"slide_number": idx + 1}
        try:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = para.text.strip()
                        if t:
                            text_parts.append(t[:500])  # per-paragraph cap, recorded below
                            full_parts.append(t)
                if shape.has_table:
                    table_count += 1
                object_count += 1
            text = "\n".join(text_parts)
            full_length = len("\n".join(full_parts))
            outcome = _outcome(text)
        except Exception as exc:
            _log_unit_failure(version, UNIT_SLIDE, idx + 1, exc, "pptx slide extraction")
            text, outcome, full_length = "", PAGE_ERROR, 0
            slide_meta["extraction_error"] = type(exc).__name__

        title_text = ""
        try:
            if slide.shapes.title:
                title_text = slide.shapes.title.text or ""
        except Exception as exc:
            _log_unit_failure(version, UNIT_SLIDE, idx + 1, exc, "pptx slide title read")

        slide_meta.update(
            {"table_count": table_count, "shape_count": object_count, "extraction_outcome": outcome}
        )
        truncated += _create_locator(
            version,
            LocatorType.SLIDE,
            f"slide-{idx}",
            display_label=title_text[:200] or f"Slide {idx + 1}",
            metadata=slide_meta,
            text=text,
            order=idx,
            original_length=full_length,
        )
        outcomes.append(outcome)
    return _office_summary(version, UNIT_SLIDE, outcomes, truncated=truncated)
