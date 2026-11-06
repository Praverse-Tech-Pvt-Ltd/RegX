"""Word, Excel and PowerPoint extraction: outcomes recorded, errors logged, never swallowed.

Same treatment as PDFs (test_text_extraction.py): each unit (paragraph or
table, sheet, slide) records `extraction_outcome`; the version carries the same
`text_extraction` summary (plus `unit`); a file with no text at all gets the
`document.processing.no_text` audit event and the API warning; silent
`except Exception: pass` blocks are now WARNING logs with ids only.

Before this change Excel sheets and Word tables stored no text at all; they now
store their cell text, so a spreadsheet is not reported as text-less.

All files are built here in code: no client data.
"""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile

import pytest

from audit.models import AuditEvent
from documents.audit_events import DocumentEvent
from documents.models import (
    Document,
    DocumentLocator,
    DocumentType,
    DocumentVersion,
    ProcessingStatus,
    ScanStatus,
)
from documents.serializers import (
    OFFICE_NO_TEXT_MESSAGE,
    OFFICE_PARTIAL_TEXT_MESSAGE,
    text_extraction_warning,
)
from documents.tasks import process_document_version

MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAIN_PART = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}


# --------------------------------------------------------------------------- builders


def make_docx(paragraphs=(), tables=()) -> bytes:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    for rows in tables:
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                t.cell(r, c).text = value
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def make_pptx(slides: list[str | None]) -> bytes:
    """A str slide gets a title with that text; None is a blank slide."""
    import pptx

    prs = pptx.Presentation()
    for text in slides:
        if text is None:
            prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
        else:
            slide = prs.slides.add_slide(prs.slide_layouts[5])  # title only
            slide.shapes.title.text = text
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def corrupt(valid: bytes, ext: str) -> bytes:
    """A real Office container (passes the ZIP and content-type checks) whose
    main part is not XML, so the library cannot open it."""
    src = zipfile.ZipFile(io.BytesIO(valid))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            data = b"this is not xml" if item.filename == MAIN_PART[ext] else src.read(item)
            z.writestr(item, data)
    return out.getvalue()


# --------------------------------------------------------------------------- harness


@pytest.fixture
def process(settings, tmp_path, tenant_a, user_a):
    settings.DOCUMENT_STORAGE_BACKEND = "local"
    settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
    settings.CELERY_TASK_ALWAYS_EAGER = True
    from documents.storage import LocalStorage

    def run(data: bytes, ext: str) -> DocumentVersion:
        sha = hashlib.sha256(data).hexdigest()
        key = LocalStorage().store(
            tenant_id=tenant_a.pk,
            file_obj=io.BytesIO(data),
            expected_sha256=sha,
            content_type=MIME[ext],
            original_filename=f"t.{ext}",
        )
        doc = Document.objects.create(
            tenant=tenant_a, title=ext, document_type=DocumentType(ext), created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename=f"t.{ext}",
            normalized_filename=f"t.{ext}",
            extension=ext,
            declared_mime_type=MIME[ext],
            size_bytes=len(data),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )
        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        return version

    return run


def _locators(version):
    return list(DocumentLocator.objects.filter(version=version).order_by("ordering"))


def _summary(version):
    return version.source_metadata["text_extraction"]


def _no_text_events(version):
    return AuditEvent.objects.filter(
        resource_id=str(version.public_id), event_type=DocumentEvent.PROCESSING_NO_TEXT
    )


# --------------------------------------------------------------------------- Word


@pytest.mark.django_db
class TestWord:
    def test_normal_file(self, process):
        version = process(
            make_docx(["Intro paragraph", "", "Second paragraph"], [[["A1", "B1"], ["A2", "B2"]]]),
            "docx",
        )
        assert version.processing_status == ProcessingStatus.COMPLETE
        s = _summary(version)
        assert (s["unit"], s["result"]) == ("paragraph or table", "complete")
        assert (s["total_pages"], s["pages_with_text"], s["pages_without_text"]) == (4, 3, 1)
        # A blank paragraph is layout, not missing text: no warning.
        assert text_extraction_warning(version) is None
        table = next(loc for loc in _locators(version) if loc.locator_type == "table")
        assert table.extracted_text == "A1\tB1\nA2\tB2"  # tables now carry their text
        assert table.structured_metadata["extraction_outcome"] == "text"
        assert not _no_text_events(version).exists()

    def test_table_only_document_is_not_text_less(self, process):
        version = process(make_docx([], [[["Only", "table"]]]), "docx")
        assert _summary(version)["result"] == "complete"

    def test_empty_file(self, process, caplog):
        caplog.set_level(logging.WARNING, logger="documents.tasks")
        version = process(make_docx(), "docx")
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert _summary(version)["result"] == "none"
        warning = text_extraction_warning(version)
        assert warning["code"] == "no_extractable_text"
        assert warning["message"] == OFFICE_NO_TEXT_MESSAGE
        assert "scanned" not in warning["message"]
        assert _no_text_events(version).get().payload["unit"] == "paragraph or table"
        assert any("office file has no extractable text" in r.getMessage() for r in caplog.records)

    def test_corrupt_file_fails_visibly(self, process):
        with pytest.raises(Exception):  # noqa: B017 - the parser's own error class
            process(corrupt(make_docx(["x"]), "docx"), "docx")
        version = DocumentVersion.objects.latest("uploaded_at")
        assert version.processing_status == ProcessingStatus.FAILED
        assert version.failure_code == "processing_error"
        assert AuditEvent.objects.filter(
            resource_id=str(version.public_id), event_type=DocumentEvent.PROCESSING_FAILED
        ).exists()


# --------------------------------------------------------------------------- Excel


@pytest.mark.django_db
class TestExcel:
    def test_normal_file(self, process):
        version = process(make_xlsx({"Data": [["Name", "Qty"], ["ACACIA", 2]]}), "xlsx")
        assert version.processing_status == ProcessingStatus.COMPLETE
        s = _summary(version)
        assert (s["unit"], s["result"], s["total_pages"], s["pages_with_text"]) == (
            "sheet",
            "complete",
            1,
            1,
        )
        sheet = _locators(version)[0]
        assert sheet.extracted_text == "Name\tQty\nACACIA\t2"  # sheets now carry their text
        assert sheet.structured_metadata["extraction_outcome"] == "text"
        assert sheet.structured_metadata["sheet_name"] == "Data"
        assert text_extraction_warning(version) is None

    def test_empty_sheet_beside_a_full_one_is_partial(self, process):
        version = process(make_xlsx({"Data": [["x"]], "Blank": []}), "xlsx")
        warning = text_extraction_warning(version)
        assert warning["code"] == "partial_text"
        assert warning["message"] == OFFICE_PARTIAL_TEXT_MESSAGE.format(
            without=1, total=2, units="sheets"
        )
        assert not _no_text_events(version).exists()

    def test_empty_file(self, process):
        version = process(make_xlsx({"Sheet1": []}), "xlsx")
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert _summary(version)["result"] == "none"
        assert text_extraction_warning(version)["code"] == "no_extractable_text"
        assert _no_text_events(version).get().payload == {
            "unit": "sheet",
            "total_pages": 1,
            "pages_with_text": 0,
            "pages_without_text": 1,
            "pages_failed": 0,
        }

    def test_corrupt_file_fails_visibly(self, process):
        with pytest.raises(Exception):  # noqa: B017 - the parser's own error class
            process(corrupt(make_xlsx({"S": [["x"]]}), "xlsx"), "xlsx")
        version = DocumentVersion.objects.latest("uploaded_at")
        assert version.processing_status == ProcessingStatus.FAILED
        assert version.failure_code == "processing_error"


# --------------------------------------------------------------------------- PowerPoint


@pytest.mark.django_db
class TestPowerPoint:
    def test_normal_file(self, process):
        version = process(make_pptx(["Slide one", "Slide two"]), "pptx")
        assert version.processing_status == ProcessingStatus.COMPLETE
        s = _summary(version)
        assert (s["unit"], s["result"], s["total_pages"], s["pages_with_text"]) == (
            "slide",
            "complete",
            2,
            2,
        )
        assert [loc.extracted_text for loc in _locators(version)] == ["Slide one", "Slide two"]
        assert text_extraction_warning(version) is None

    def test_picture_slide_makes_it_partial(self, process):
        version = process(make_pptx(["Title slide", None]), "pptx")
        warning = text_extraction_warning(version)
        assert warning["message"] == OFFICE_PARTIAL_TEXT_MESSAGE.format(
            without=1, total=2, units="slides"
        )

    def test_empty_file(self, process):
        version = process(make_pptx([None]), "pptx")
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert _summary(version)["result"] == "none"
        assert text_extraction_warning(version)["code"] == "no_extractable_text"
        assert _no_text_events(version).exists()

    def test_corrupt_file_fails_visibly(self, process):
        with pytest.raises(Exception):  # noqa: B017 - the parser's own error class
            process(corrupt(make_pptx(["x"]), "pptx"), "pptx")
        version = DocumentVersion.objects.latest("uploaded_at")
        assert version.processing_status == ProcessingStatus.FAILED
        assert version.failure_code == "processing_error"

    def test_a_slide_that_raises_is_recorded_and_logged_not_swallowed(
        self, process, monkeypatch, caplog
    ):
        from documents import tasks

        original = tasks._outcome

        def flaky(text):
            # Raise inside the per-slide extraction step for one slide only.
            if "SECRET-BODY" in text:
                raise ValueError("boom quoting SECRET-BODY")
            return original(text)

        monkeypatch.setattr(tasks, "_outcome", flaky)
        caplog.set_level(logging.WARNING, logger="documents.tasks")
        version = process(make_pptx(["Fine", "SECRET-BODY"]), "pptx")
        assert version.processing_status == ProcessingStatus.COMPLETE
        locs = _locators(version)
        assert [loc.structured_metadata["extraction_outcome"] for loc in locs] == ["text", "error"]
        assert locs[1].structured_metadata["extraction_error"] == "ValueError"
        assert _summary(version)["pages_failed"] == 1
        messages = [r.getMessage() for r in caplog.records]
        failed = [m for m in messages if "pptx slide extraction failed" in m]
        assert failed and "slide=2" in failed[0] and str(version.document.public_id) in failed[0]
        assert not any("SECRET-BODY" in m for m in messages)


# --------------------------------------------------------------------------- upload path


@pytest.mark.django_db
class TestCorruptFilesReachProcessing:
    """The corrupt files above pass the upload validator (they are real Office
    containers), which is why processing must fail them visibly."""

    @pytest.mark.parametrize(
        "ext,build",
        [
            ("docx", lambda: make_docx(["x"])),
            ("xlsx", lambda: make_xlsx({"S": [["x"]]})),
            ("pptx", lambda: make_pptx(["x"])),
        ],
    )
    def test_validator_accepts_the_container(self, ext, build):
        from documents.validators import validate_upload

        data = corrupt(build(), ext)
        validate_upload(file_obj=io.BytesIO(data), filename=f"t.{ext}", declared_mime=MIME[ext])


# --------------------------------------------------------------------------- truncation


@pytest.mark.django_db
class TestTruncationIsRecorded:
    """Text over the 10,000-character locator cap is cut, and the cut is recorded:
    per unit in the locator metadata, and as a count in the summary."""

    def test_sheet_over_the_cap(self, process):
        rows = [[f"row-{i:05d}", "x" * 90] for i in range(400)]  # about 40,000 characters
        version = process(make_xlsx({"Big": rows, "Small": [["tiny"]]}), "xlsx")
        big, small = _locators(version)
        full_length = sum(len(f"row-{i:05d}\t" + "x" * 90) for i in range(400)) + 399
        assert big.structured_metadata["truncated"] is True
        assert big.structured_metadata["original_length"] == full_length
        assert big.structured_metadata["stored_length"] == len(big.extracted_text) == 10000
        assert big.extracted_text.startswith("row-00000\t")
        assert "truncated" not in small.structured_metadata
        s = _summary(version)
        assert (s["pages_truncated"], s["result"]) == (1, "complete")

    def test_word_paragraph_over_the_cap(self, process):
        version = process(make_docx(["y" * 12000, "short"]), "docx")
        long, short = _locators(version)
        assert long.structured_metadata["truncated"] is True
        assert long.structured_metadata["original_length"] == 12000
        assert len(long.extracted_text) == 10000
        assert "truncated" not in short.structured_metadata
        assert _summary(version)["pages_truncated"] == 1

    def test_powerpoint_paragraph_cap_is_recorded(self, process):
        """PowerPoint keeps at most 500 characters per paragraph (unchanged);
        that cut is now recorded too."""
        version = process(make_pptx(["z" * 600]), "pptx")
        slide = _locators(version)[0]
        assert len(slide.extracted_text) == 500
        assert slide.structured_metadata["truncated"] is True
        assert slide.structured_metadata["original_length"] == 600
        assert _summary(version)["pages_truncated"] == 1

    def test_no_truncation_reports_zero(self, process):
        version = process(make_xlsx({"S": [["a", "b"]]}), "xlsx")
        assert _summary(version)["pages_truncated"] == 0
        assert "truncated" not in _locators(version)[0].structured_metadata

    def test_pdf_summary_counts_truncation_too(self, process, monkeypatch):
        """The shared locator helper records truncation for PDF pages as well."""
        import pypdf

        from documents.tests.test_text_extraction import build_pdf

        monkeypatch.setattr(pypdf.PageObject, "extract_text", lambda self, *a, **k: "p" * 15000)
        data = build_pdf(["anything"])
        # Reuse the Office harness with a PDF: MIME lookup needs the key.
        MIME["pdf"] = "application/pdf"
        try:
            version = process(data, "pdf")
        finally:
            MIME.pop("pdf")
        page = _locators(version)[0]
        assert page.structured_metadata["truncated"] is True
        assert page.structured_metadata["original_length"] == 15000
        assert _summary(version)["pages_truncated"] == 1
