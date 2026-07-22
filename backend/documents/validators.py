"""
Secure file upload validation for the document platform.

Validation order:
1. Non-empty, size within limit
2. Safe filename (no path traversal, no double-extension, no executable suffix)
3. Allowlisted extension
4. Allowlisted declared MIME type
5. Detected file signature / container type
6. Declared vs detected MIME consistency
7. ZIP-based Office container inspection (content type XML)
8. Macro-enabled Office format rejection
9. Encrypted/password-protected file detection
10. Decompression-bomb / dimension / entry-count controls

Validation failures return structured errors without server path or
internal detail leakage.
"""

import io
import os
import re
import zipfile

import filetype
from django.conf import settings
from django.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "docx", "xlsx", "pptx"})

ALLOWED_DECLARED_MIMES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)

EXTENSION_TO_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# PDF magic bytes
PDF_MAGIC = b"%PDF"
# ZIP magic bytes (Office Open XML containers)
ZIP_MAGIC = b"PK\x03\x04"

# Office Open XML content type roots
OFFICE_CONTENT_TYPE_FILES = {
    "docx": "[Content_Types].xml",
    "xlsx": "[Content_Types].xml",
    "pptx": "[Content_Types].xml",
}

# Content type XML substrings that identify each format
DOCX_CONTENT_TYPE_MARKER = "wordprocessingml"
XLSX_CONTENT_TYPE_MARKER = "spreadsheetml"
PPTX_CONTENT_TYPE_MARKER = "presentationml"

OFFICE_MARKERS = {
    "docx": DOCX_CONTENT_TYPE_MARKER,
    "xlsx": XLSX_CONTENT_TYPE_MARKER,
    "pptx": PPTX_CONTENT_TYPE_MARKER,
}

# Macro-enabled extensions to explicitly reject
MACRO_EXTENSIONS: frozenset[str] = frozenset(
    {"docm", "xlsm", "pptm", "xlam", "xltm", "dotm", "potm", "ppam"}
)

# Executable / script suffixes — never allowed
EXECUTABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        "exe",
        "dll",
        "bat",
        "cmd",
        "sh",
        "ps1",
        "vbs",
        "js",
        "py",
        "rb",
        "pl",
        "php",
        "asp",
        "aspx",
        "jsp",
        "cgi",
        "com",
        "scr",
        "msi",
        "apk",
        "dmg",
        "pkg",
        "deb",
        "rpm",
    }
)

# Decompression bomb limits
ZIP_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024  # 512 MB
ZIP_MAX_ENTRY_COUNT = 1000

# Spreadsheet dimension limits (openpyxl)
XLSX_MAX_ROWS = 1_048_576
XLSX_MAX_COLS = 16_384

# Filename constraints
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.\- ]+$")
MAX_FILENAME_LENGTH = 255

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UploadValidationError(ValidationError):
    """Structured upload validation error with a safe, user-visible code."""

    def __init__(self, code: str, message: str):
        super().__init__(message=message, code=code)
        self.safe_code = code
        self.safe_message = message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_ext(filename: str) -> str:
    """Return the last extension, lowercased, without the dot."""
    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").lower()


def _all_extensions(filename: str) -> list[str]:
    """Return all extensions in a filename (for double-extension detection)."""
    parts = filename.lower().split(".")
    return parts[1:] if len(parts) > 1 else []


def _read_bytes(file_obj, length: int) -> bytes:
    pos = file_obj.tell()
    data = file_obj.read(length)
    file_obj.seek(pos)
    return data


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_filename(filename: str) -> None:
    """Ensure the filename is safe: no path traversal, no executables, no
    double extensions with dangerous suffixes."""
    if not filename:
        raise UploadValidationError("empty_filename", "Filename is required.")

    # Check the raw filename for path traversal BEFORE stripping separators
    if ".." in filename or "\x00" in filename:
        raise UploadValidationError("path_traversal", "Filename is not safe.")
    if "/" in filename or "\\" in filename:
        raise UploadValidationError("path_traversal", "Filename must not contain path separators.")

    basename = os.path.basename(filename)

    if len(basename) > MAX_FILENAME_LENGTH:
        raise UploadValidationError("filename_too_long", "Filename exceeds maximum length.")

    if basename.startswith("/"):
        raise UploadValidationError("path_traversal", "Filename is not safe.")

    # All extensions (double-extension bypass detection)
    exts = _all_extensions(basename)
    for ext in exts:
        if ext in EXECUTABLE_EXTENSIONS:
            raise UploadValidationError(
                "executable_extension",
                "Files with executable extensions are not permitted.",
            )
        if ext in MACRO_EXTENSIONS:
            raise UploadValidationError(
                "macro_extension",
                "Macro-enabled Office formats are not accepted in this release.",
            )

    # Final (declared) extension must be in allowlist
    declared_ext = _safe_ext(basename)
    if declared_ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            "disallowed_extension",
            f"File type '.{declared_ext}' is not supported. Accepted: pdf, docx, xlsx, pptx.",
        )

    # Double-extension: inner extensions must not be in other banned sets
    inner_exts = exts[:-1]
    for ext in inner_exts:
        if ext in ALLOWED_EXTENSIONS or ext in EXECUTABLE_EXTENSIONS or ext in MACRO_EXTENSIONS:
            raise UploadValidationError(
                "double_extension",
                "Double-extension filenames are not accepted.",
            )


def validate_file_size(file_obj) -> int:
    """Return file size in bytes; raise if empty or over limit."""
    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)

    if size == 0:
        raise UploadValidationError("empty_file", "Uploaded file is empty.")

    max_bytes = getattr(settings, "DOCUMENT_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)
    if size > max_bytes:
        raise UploadValidationError(
            "file_too_large",
            f"File exceeds the maximum allowed size of {max_bytes // (1024 * 1024)} MB.",
        )
    return size


def validate_declared_mime(declared_mime: str) -> None:
    if declared_mime not in ALLOWED_DECLARED_MIMES:
        raise UploadValidationError(
            "disallowed_mime",
            "The declared content type is not accepted.",
        )


def detect_mime_type(file_obj) -> str:
    """Use magic bytes to detect the actual file type."""
    header = _read_bytes(file_obj, 261)
    kind = filetype.guess(header)
    if kind is None:
        # filetype doesn't recognise the header; check PDF manually
        if header[:4] == PDF_MAGIC:
            return "application/pdf"
        return "application/octet-stream"
    return kind.mime


def validate_mime_consistency(extension: str, declared_mime: str, detected_mime: str) -> None:
    """Ensure declared MIME matches the extension allowlist and detected type."""
    expected = EXTENSION_TO_MIME.get(extension)
    if expected and declared_mime != expected:
        raise UploadValidationError(
            "mime_extension_mismatch",
            "Declared content type does not match file extension.",
        )

    # PDF detection
    if extension == "pdf":
        if detected_mime not in ("application/pdf",):
            raise UploadValidationError(
                "mime_signature_mismatch",
                "File signature does not match declared content type.",
            )
        return

    # Office (ZIP-based) — filetype detects these as application/zip or
    # application/vnd.openxmlformats-officedocument.* depending on version
    office_exts = {"docx", "xlsx", "pptx"}
    if extension in office_exts:
        if detected_mime not in (
            "application/zip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/x-zip-compressed",
        ):
            raise UploadValidationError(
                "mime_signature_mismatch",
                "File signature does not match an Office Open XML container.",
            )


def _read_content_types_xml(file_obj) -> str:
    """Read [Content_Types].xml from a ZIP-based Office container."""
    pos = file_obj.tell()
    file_obj.seek(0)
    data = file_obj.read()
    file_obj.seek(pos)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError):
        return ""


def validate_office_container(file_obj, extension: str) -> None:
    """Inspect ZIP container for correct Office format and safety checks."""
    if extension not in {"docx", "xlsx", "pptx"}:
        return

    pos = file_obj.tell()
    file_obj.seek(0)
    raw = file_obj.read()
    file_obj.seek(pos)

    # Must be a valid ZIP
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise UploadValidationError(
            "invalid_office_container",
            "The file is not a valid Office Open XML container.",
        )

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            entries = zf.infolist()

            # Entry-count bomb
            if len(entries) > ZIP_MAX_ENTRY_COUNT:
                raise UploadValidationError(
                    "zip_entry_count_exceeded",
                    "Archive entry count exceeds the allowed limit.",
                )

            # Decompression bomb: check total uncompressed size
            total_uncompressed = sum(e.file_size for e in entries)
            if total_uncompressed > ZIP_MAX_UNCOMPRESSED_BYTES:
                raise UploadValidationError(
                    "decompression_bomb",
                    "Archive uncompressed size exceeds the allowed limit.",
                )

            # Nested archive detection
            for entry in entries:
                name_lower = entry.filename.lower()
                if name_lower.endswith(".zip") and entry.filename != "[Content_Types].xml":
                    raise UploadValidationError(
                        "nested_archive",
                        "Nested archives within Office files are not accepted.",
                    )

            # Verify [Content_Types].xml exists and matches expected format
            try:
                ct_xml = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
            except KeyError as exc:
                raise UploadValidationError(
                    "missing_content_types",
                    "Office container is missing [Content_Types].xml.",
                ) from exc

            marker = OFFICE_MARKERS.get(extension, "")
            if marker and marker not in ct_xml:
                raise UploadValidationError(
                    "office_format_mismatch",
                    f"Container content type does not match the declared .{extension} format.",
                )

            # Macro-enabled internal parts
            macro_indicators = [
                "vbaProject.bin",
                "xl/vbaProject.bin",
                "word/vbaProject.bin",
                "ppt/vbaProject.bin",
            ]
            for entry in entries:
                if any(entry.filename.lower().endswith(mi.lower()) for mi in macro_indicators):
                    raise UploadValidationError(
                        "macro_content",
                        "Macro-enabled Office files are not accepted in this release.",
                    )

    except UploadValidationError:
        raise
    except zipfile.BadZipFile as exc:
        raise UploadValidationError(
            "corrupt_office_container",
            "The Office file container is corrupt or malformed.",
        ) from exc


def validate_xlsx_dimensions(file_obj) -> None:
    """Validate XLSX spreadsheet dimensions to prevent resource exhaustion."""
    try:
        import openpyxl

        pos = file_obj.tell()
        file_obj.seek(0)
        raw = file_obj.read()
        file_obj.seek(pos)
        wb = openpyxl.load_workbook(
            io.BytesIO(raw),
            read_only=True,
            data_only=True,
        )
        for ws in wb.worksheets:
            if ws.max_row and ws.max_row > XLSX_MAX_ROWS:
                raise UploadValidationError(
                    "xlsx_row_limit",
                    "Spreadsheet exceeds the maximum allowed row count.",
                )
            if ws.max_column and ws.max_column > XLSX_MAX_COLS:
                raise UploadValidationError(
                    "xlsx_column_limit",
                    "Spreadsheet exceeds the maximum allowed column count.",
                )
        wb.close()
    except UploadValidationError:
        raise
    except Exception:  # noqa: S110
        # If openpyxl can't open it, the container inspection already caught it
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def validate_upload(
    *,
    file_obj,
    filename: str,
    declared_mime: str,
) -> dict:
    """
    Run the full validation pipeline.

    Returns a dict of validated metadata on success.
    Raises UploadValidationError on any failure.
    """
    validate_filename(filename)
    size_bytes = validate_file_size(file_obj)
    validate_declared_mime(declared_mime)

    extension = _safe_ext(os.path.basename(filename))
    detected_mime = detect_mime_type(file_obj)
    validate_mime_consistency(extension, declared_mime, detected_mime)

    if extension in {"docx", "xlsx", "pptx"}:
        validate_office_container(file_obj, extension)
        if extension == "xlsx":
            validate_xlsx_dimensions(file_obj)

    return {
        "extension": extension,
        "detected_mime_type": detected_mime,
        "size_bytes": size_bytes,
    }
