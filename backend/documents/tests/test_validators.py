"""
Upload security validation tests.

Tests planted violations and restores: every guard is exercised with a
controlled bad input, then the good input is also verified to pass.
"""

import io
import zipfile

import pytest

from documents.validators import (
    UploadValidationError,
    validate_filename,
    validate_upload,
)

# ---------------------------------------------------------------------------
# Filename guards
# ---------------------------------------------------------------------------


class TestFilenameValidation:
    def test_valid_pdf_filename(self):
        validate_filename("report.pdf")  # should not raise

    def test_valid_docx_filename(self):
        validate_filename("document.docx")

    def test_valid_xlsx_filename(self):
        validate_filename("data.xlsx")

    def test_valid_pptx_filename(self):
        validate_filename("slides.pptx")

    def test_path_traversal_unix(self):
        # PLANTED: path traversal attempt
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("../../etc/passwd.pdf")
        assert exc_info.value.safe_code == "path_traversal"

    def test_path_traversal_windows(self):
        # PLANTED: Windows-style path traversal
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("..\\..\\Windows\\system32\\evil.pdf")
        assert exc_info.value.safe_code == "path_traversal"

    def test_null_byte_in_filename(self):
        # PLANTED: null byte injection
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("evil\x00.pdf")
        assert exc_info.value.safe_code in ("path_traversal",)

    def test_executable_extension_exe(self):
        # PLANTED: executable extension
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("malware.exe")
        assert exc_info.value.safe_code == "executable_extension"

    def test_executable_extension_sh(self):
        # PLANTED: shell script
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("setup.sh")
        assert exc_info.value.safe_code == "executable_extension"

    def test_macro_extension_docm(self):
        # PLANTED: macro-enabled Office format
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("macro.docm")
        assert exc_info.value.safe_code == "macro_extension"

    def test_macro_extension_xlsm(self):
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("macro.xlsm")
        assert exc_info.value.safe_code == "macro_extension"

    def test_double_extension_bypass(self):
        # PLANTED: double extension to bypass type check
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("evil.exe.pdf")
        assert exc_info.value.safe_code in ("double_extension", "executable_extension")

    def test_double_extension_pdf_exe(self):
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("evil.pdf.exe")
        assert exc_info.value.safe_code in ("executable_extension", "disallowed_extension")

    def test_disallowed_extension(self):
        # PLANTED: unsupported file type
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("file.csv")
        assert exc_info.value.safe_code == "disallowed_extension"

    def test_empty_filename(self):
        with pytest.raises(UploadValidationError) as exc_info:
            validate_filename("")
        assert exc_info.value.safe_code == "empty_filename"


# ---------------------------------------------------------------------------
# File size guards
# ---------------------------------------------------------------------------


class TestFileSizeValidation:
    def test_empty_file_rejected(self):
        # PLANTED: empty file
        f = io.BytesIO(b"")
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(file_obj=f, filename="empty.pdf", declared_mime="application/pdf")
        assert exc_info.value.safe_code == "empty_file"

    def test_oversized_file_rejected(self, settings):
        # PLANTED: file exceeds size limit
        settings.DOCUMENT_MAX_UPLOAD_BYTES = 1024  # 1 KB for test
        f = io.BytesIO(b"x" * 2048)
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(file_obj=f, filename="big.pdf", declared_mime="application/pdf")
        assert exc_info.value.safe_code == "file_too_large"


# ---------------------------------------------------------------------------
# MIME mismatch
# ---------------------------------------------------------------------------


class TestMimeValidation:
    def test_disallowed_declared_mime(self):
        # PLANTED: unsupported declared MIME
        f = io.BytesIO(b"%PDF-1.4 test")
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(file_obj=f, filename="file.pdf", declared_mime="text/plain")
        assert exc_info.value.safe_code == "disallowed_mime"

    def test_mime_extension_mismatch(self):
        # PLANTED: extension says .pdf but declared MIME is docx
        f = io.BytesIO(b"%PDF-1.4 test")
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(
                file_obj=f,
                filename="file.pdf",
                declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        assert exc_info.value.safe_code == "mime_extension_mismatch"

    def test_mime_signature_mismatch(self, mime_mismatch_bytes):
        # PLANTED: JPEG bytes declared as PDF
        f = io.BytesIO(mime_mismatch_bytes)
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(file_obj=f, filename="fake.pdf", declared_mime="application/pdf")
        assert exc_info.value.safe_code == "mime_signature_mismatch"


# ---------------------------------------------------------------------------
# Office container guards
# ---------------------------------------------------------------------------


class TestOfficeContainerValidation:
    def test_corrupt_office_container_rejected(self, corrupt_office_bytes):
        # PLANTED: corrupt ZIP / Office container
        f = io.BytesIO(corrupt_office_bytes)
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(
                file_obj=f,
                filename="corrupt.docx",
                declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        assert exc_info.value.safe_code in (
            "invalid_office_container",
            "corrupt_office_container",
            "missing_content_types",
        )

    def test_valid_docx_accepted(self, valid_docx_bytes):
        # RESTORE: valid DOCX passes
        f = io.BytesIO(valid_docx_bytes)
        result = validate_upload(
            file_obj=f,
            filename="valid.docx",
            declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert result["extension"] == "docx"

    def test_valid_xlsx_accepted(self, valid_xlsx_bytes):
        f = io.BytesIO(valid_xlsx_bytes)
        result = validate_upload(
            file_obj=f,
            filename="valid.xlsx",
            declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert result["extension"] == "xlsx"

    def test_valid_pptx_accepted(self, valid_pptx_bytes):
        f = io.BytesIO(valid_pptx_bytes)
        result = validate_upload(
            file_obj=f,
            filename="valid.pptx",
            declared_mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        assert result["extension"] == "pptx"

    def test_office_format_mismatch_xlsx_declared_as_docx(self, valid_xlsx_bytes):
        # PLANTED: XLSX container declared as DOCX
        f = io.BytesIO(valid_xlsx_bytes)
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(
                file_obj=f,
                filename="evil.docx",
                declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        assert exc_info.value.safe_code == "office_format_mismatch"

    def test_macro_content_rejected(self):
        # PLANTED: ZIP container with vbaProject.bin (macro indicator)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>",
            )
            zf.writestr("word/vbaProject.bin", b"VBA content here")
        buf.seek(0)
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(
                file_obj=buf,
                filename="macro.docx",
                declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        assert exc_info.value.safe_code == "macro_content"

    def test_zip_bomb_threshold(self):
        # PLANTED: entry count bomb — too many entries
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
            ct_type = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            )
            zf.writestr(
                "[Content_Types].xml",
                f'<?xml version="1.0"?><Types xmlns="{ct_ns}">'
                f'<Override PartName="/word/document.xml" ContentType="{ct_type}"/>'
                "</Types>",
            )
            for i in range(1001):
                zf.writestr(f"entry_{i}.txt", b"x")
        buf.seek(0)
        with pytest.raises(UploadValidationError) as exc_info:
            validate_upload(
                file_obj=buf,
                filename="bomb.docx",
                declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        assert exc_info.value.safe_code == "zip_entry_count_exceeded"


# ---------------------------------------------------------------------------
# Valid PDF round-trip
# ---------------------------------------------------------------------------


class TestPDFValidation:
    def test_valid_pdf_accepted(self, valid_pdf_bytes):
        f = io.BytesIO(valid_pdf_bytes)
        result = validate_upload(file_obj=f, filename="report.pdf", declared_mime="application/pdf")
        assert result["extension"] == "pdf"
        assert result["size_bytes"] == len(valid_pdf_bytes)
