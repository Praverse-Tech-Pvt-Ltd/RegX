"""PDF text extraction: empty pages are recorded and surfaced, never swallowed.

Before: `_process_pdf` caught any exception from `extract_text()` with a bare
`pass`, and a PDF with no text layer (a scan) ended `complete` with 0
characters per page and nothing anywhere saying so. Now each page records its
outcome, the version carries a summary, a fully text-less PDF gets its own
audit event, and the API exposes a warning wherever extracted text is read.

All PDFs are built here in code: no client data.
"""

from __future__ import annotations

import hashlib
import io
import logging
import pathlib

import pytest

from audit.models import AuditEvent
from documents.audit_events import DocumentEvent
from documents.models import (
    Document,
    DocumentLocator,
    DocumentType,
    DocumentVersion,
    LocatorType,
    ProcessingStatus,
    ScanStatus,
)
from documents.serializers import NO_TEXT_MESSAGE, PARTIAL_TEXT_MESSAGE
from documents.tasks import process_document_version

BACKEND = pathlib.Path(__file__).resolve().parents[2]
BASE = "/api/regx/v1/documents/"


def build_pdf(pages: list[str | None]) -> bytes:
    """A minimal valid PDF. A str page draws that text in Helvetica; None is a
    page with no text layer at all (what a scanned page looks like to a text
    extractor)."""
    objects: list[bytes] = []
    kids = []
    n_pages = len(pages)
    # 1 catalog, 2 pages, 3 font, then (page, content) pairs
    for i in range(n_pages):
        kids.append(f"{4 + 2 * i} 0 R")
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n_pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        content_obj = 5 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >>".encode()
        )
        if text is None:
            stream = b"q 0.9 g 72 72 451 698 re f Q"  # a grey box, no text
        else:
            safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream = f"BT /F1 14 Tf 72 760 Td ({safe}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


@pytest.fixture
def processed(settings, tmp_path, tenant_a, user_a):
    """Store a PDF, run processing (eager), return the refreshed version."""
    settings.DOCUMENT_STORAGE_BACKEND = "local"
    settings.DOCUMENT_LOCAL_STORAGE_ROOT = str(tmp_path / "store")
    settings.CELERY_TASK_ALWAYS_EAGER = True
    from documents.storage import LocalStorage

    def run(pdf: bytes, title: str = "PDF") -> DocumentVersion:
        sha = hashlib.sha256(pdf).hexdigest()
        key = LocalStorage().store(
            tenant_id=tenant_a.pk,
            file_obj=io.BytesIO(pdf),
            expected_sha256=sha,
            content_type="application/pdf",
            original_filename="t.pdf",
        )
        doc = Document.objects.create(
            tenant=tenant_a, title=title, document_type=DocumentType.PDF, created_by=user_a
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            original_filename="t.pdf",
            normalized_filename="t.pdf",
            extension="pdf",
            declared_mime_type="application/pdf",
            size_bytes=len(pdf),
            sha256_checksum=sha,
            storage_key=key,
            uploaded_by=user_a,
            scan_status=ScanStatus.CLEAN,
        )
        doc.current_version = version
        doc.save(update_fields=["current_version"])
        process_document_version(version.pk, tenant_a.pk)
        version.refresh_from_db()
        return version

    return run


def _outcomes(version):
    return [
        loc.structured_metadata.get("extraction_outcome")
        for loc in DocumentLocator.objects.filter(
            version=version, locator_type=LocatorType.PAGE
        ).order_by("ordering")
    ]


def _events(version, event_type):
    return AuditEvent.objects.filter(resource_id=str(version.public_id), event_type=event_type)


def test_build_pdf_helper_really_has_and_lacks_text():
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(build_pdf(["Hello page one", None])))
    assert "Hello page one" in reader.pages[0].extract_text()
    assert (reader.pages[1].extract_text() or "").strip() == ""


@pytest.mark.django_db
class TestImageOnlyPdf:
    def test_all_pages_without_text(self, processed, caplog):
        caplog.set_level(logging.WARNING, logger="documents.tasks")
        version = processed(build_pdf([None, None, None]))

        # The file was processed: the status stays complete, not failed.
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert version.failure_code == ""
        assert _outcomes(version) == ["no_text", "no_text", "no_text"]
        assert version.source_metadata["text_extraction"] == {
            "total_pages": 3,
            "pages_with_text": 0,
            "pages_without_text": 3,
            "pages_failed": 0,
            # Added with truncation tracking (deliberate API addition).
            "pages_truncated": 0,
            "result": "none",
        }
        # Its own audit event, counts only.
        event = _events(version, DocumentEvent.PROCESSING_NO_TEXT).get()
        assert event.payload == {
            "total_pages": 3,
            "pages_with_text": 0,
            "pages_without_text": 3,
            "pages_failed": 0,
        }
        assert _events(version, DocumentEvent.PROCESSING_COMPLETE).count() == 1
        # And a log line naming the document, not its content.
        assert any(
            "no extractable text, likely scanned" in r.getMessage()
            and str(version.public_id) in r.getMessage()
            for r in caplog.records
        )


@pytest.mark.django_db
class TestMixedPdf:
    def test_some_pages_without_text(self, processed):
        version = processed(build_pdf(["Page one text", None, "Page three text"]))
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert _outcomes(version) == ["text", "no_text", "text"]
        summary = version.source_metadata["text_extraction"]
        assert (summary["pages_with_text"], summary["pages_without_text"], summary["result"]) == (
            2,
            1,
            "partial",
        )
        # Partial gets a warning in the API, but not the "no text" audit event.
        assert not _events(version, DocumentEvent.PROCESSING_NO_TEXT).exists()


@pytest.mark.django_db
class TestExtractionError:
    def test_a_page_that_raises_is_recorded_and_logged_not_swallowed(
        self, processed, monkeypatch, caplog
    ):
        import pypdf

        original = pypdf.PageObject.extract_text

        def flaky(self, *args, **kwargs):
            text = original(self, *args, **kwargs)
            if "SECRET-BODY" in (text or ""):
                raise ValueError("boom quoting SECRET-BODY bytes")
            return text

        monkeypatch.setattr(pypdf.PageObject, "extract_text", flaky)
        caplog.set_level(logging.WARNING, logger="documents.tasks")
        version = processed(build_pdf(["Fine page", "SECRET-BODY page"]))

        assert version.processing_status == ProcessingStatus.COMPLETE
        assert _outcomes(version) == ["text", "error"]
        page2 = DocumentLocator.objects.get(version=version, locator_id="2")
        assert page2.structured_metadata["extraction_error"] == "ValueError"
        assert page2.extracted_text == ""
        summary = version.source_metadata["text_extraction"]
        assert (summary["pages_failed"], summary["result"]) == (1, "partial")

        messages = [r.getMessage() for r in caplog.records]
        failed = [m for m in messages if "pdf text extraction failed" in m]
        assert len(failed) == 1
        assert "page=2" in failed[0] and str(version.document.public_id) in failed[0]
        assert "ValueError" in failed[0]
        # Never the text, never str(exc).
        assert not any("SECRET-BODY" in m for m in messages)


@pytest.mark.django_db
class TestNormalTextPdf:
    def test_unchanged_behaviour(self, processed):
        version = processed(build_pdf(["One", "Two"]))
        assert version.processing_status == ProcessingStatus.COMPLETE
        assert _outcomes(version) == ["text", "text"]
        assert version.source_metadata["page_count"] == 2
        assert version.source_metadata["text_extraction"]["result"] == "complete"
        assert not _events(version, DocumentEvent.PROCESSING_NO_TEXT).exists()
        texts = list(
            DocumentLocator.objects.filter(version=version)
            .order_by("ordering")
            .values_list("extracted_text", flat=True)
        )
        assert [t.strip() for t in texts] == ["One", "Two"]


@pytest.mark.django_db
class TestApiSurfacesTheWarning:
    @pytest.fixture
    def client(self, api_client_a, admin_membership, tenant_a):
        api_client_a.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
        return api_client_a

    def _get(self, client, version, suffix=""):
        doc = version.document
        if suffix == "doc":
            return client.get(f"{BASE}{doc.public_id}/")
        return client.get(f"{BASE}{doc.public_id}/versions/{version.public_id}/{suffix}")

    def test_no_text_warning_on_document_status_and_locators(self, processed, client):
        version = processed(build_pdf([None, None]))
        expected = {
            "level": "warning",
            "code": "no_extractable_text",
            "message": NO_TEXT_MESSAGE,
        }
        doc = self._get(client, version, "doc")
        assert doc.status_code == 200
        assert doc.data["current_version"]["text_extraction_warning"] == expected
        assert doc.data["current_version"]["processing_status"] == "complete"
        status = self._get(client, version, "status/")
        assert status.data["text_extraction_warning"] == expected
        assert status.data["text_extraction"]["result"] == "none"
        loc = self._get(client, version, "locators/")
        assert loc.status_code == 200
        assert loc.data["text_extraction_warning"] == expected
        assert [r["structured_metadata"]["extraction_outcome"] for r in loc.data["results"]] == [
            "no_text",
            "no_text",
        ]

    def test_partial_warning_counts_pages(self, processed, client):
        version = processed(build_pdf(["a", None, None, "d"]))
        warning = self._get(client, version, "status/").data["text_extraction_warning"]
        assert warning["code"] == "partial_text"
        assert (warning["pages_without_text"], warning["total_pages"]) == (2, 4)
        assert warning["message"] == PARTIAL_TEXT_MESSAGE.format(without=2, total=4)
        assert "incomplete" in warning["message"]

    def test_normal_pdf_has_no_warning(self, processed, client):
        version = processed(build_pdf(["only text"]))
        assert self._get(client, version, "status/").data["text_extraction_warning"] is None
        assert self._get(client, version, "locators/").data["text_extraction_warning"] is None


class TestConsumersOfExtractedText:
    """Guard: nothing may read extracted document text without handling the
    no-text case. Today the documents API is the only reader; gap analysis works
    on checklist answers and never reads documents. If that changes, this test
    fails and points at `text_extraction_warning`, so a text-less scan can never
    be read as "no gaps found"."""

    READERS = ("extracted_text", "DocumentLocator", ".locators.")

    def test_only_the_documents_app_reads_extracted_text(self):
        offenders = []
        for path in BACKEND.rglob("*.py"):
            parts = path.relative_to(BACKEND).parts
            if parts[0] == "documents" or "tests" in parts or "migrations" in parts:
                continue
            text = path.read_text(encoding="utf-8")
            if any(r in text for r in self.READERS) and "text_extraction_warning" not in text:
                offenders.append(path.relative_to(BACKEND).as_posix())
        assert offenders == [], (
            "These modules read extracted document text without handling a document "
            "with no extractable text (use documents.serializers.text_extraction_warning "
            "and refuse, or label the result 'incomplete: no extractable text'): "
            + ", ".join(offenders)
        )

    def test_gap_analysis_does_not_read_documents(self):
        source = (BACKEND / "iig_checklist" / "gap_analysis.py").read_text(encoding="utf-8")
        assert "documents" not in source and "extracted_text" not in source


class TestWording:
    def test_no_regulatory_claim_or_review_wording(self):
        from common.tests.test_regulatory_claim_guard import BANNED

        for message in (NO_TEXT_MESSAGE, PARTIAL_TEXT_MESSAGE):
            lowered = message.lower()
            assert not any(phrase in lowered for phrase in BANNED)
            for word in ("review", "approv", "compliant", "validated", "verified"):
                assert word not in lowered, word
