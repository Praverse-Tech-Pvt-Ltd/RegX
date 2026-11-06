"""
Document domain serializers.

Rules:
- No internal numeric IDs in any response.
- No storage keys in any response.
- UUID public_id used for all external references.
- No server filesystem paths.
"""

from rest_framework import serializers

from .models import (
    Document,
    DocumentLocator,
    DocumentProcessingJob,
    DocumentType,
    DocumentVersion,
)

#: Wording for the text-extraction warning. A warning, not an error: the file
#: was processed. Says nothing about review or approval of the document.
NO_TEXT_MESSAGE = (
    "No extractable text, likely scanned. Text-based features cannot use this "
    "document; its extracted text is incomplete: no extractable text."
)
PARTIAL_TEXT_MESSAGE = (
    "{without} of {total} pages have no extractable text. Extracted text for this "
    "document is incomplete."
)
#: Word, Excel and PowerPoint: "likely scanned" does not apply.
OFFICE_NO_TEXT_MESSAGE = (
    "No extractable text. Text-based features cannot use this document; its "
    "extracted text is incomplete: no extractable text."
)
OFFICE_PARTIAL_TEXT_MESSAGE = (
    "{without} of {total} {units} have no extractable text. Extracted text for "
    "this document is incomplete."
)
#: Word: blank paragraphs are layout, so "partial" means some could not be read.
WORD_PARTIAL_TEXT_MESSAGE = (
    "{without} of {total} paragraphs or tables could not be read. Extracted text "
    "for this document is incomplete."
)
_UNIT_PLURAL = {"slide": "slides", "sheet": "sheets", "paragraph or table": "paragraphs or tables"}


def text_extraction_summary(version) -> dict | None:
    """The per-upload summary written by processing (PDF, Word, Excel,
    PowerPoint), or None (versions processed before the summary existed).

    Counts keep the PDF key names (`total_pages`, `pages_with_text`, ...);
    for Office files `unit` says what they count (slide, sheet, paragraph or
    table). No `unit` means pages."""
    summary = (version.source_metadata or {}).get("text_extraction")
    return summary if isinstance(summary, dict) else None


def text_extraction_warning(version) -> dict | None:
    """A warning when some or all units yielded no text; None otherwise."""
    summary = text_extraction_summary(version)
    if not summary:
        return None
    unit = summary.get("unit")
    total = summary.get("total_pages", 0)
    with_text = summary.get("pages_with_text", 0)
    if summary.get("result") == "none":
        message = OFFICE_NO_TEXT_MESSAGE if unit else NO_TEXT_MESSAGE
        warning = {"level": "warning", "code": "no_extractable_text", "message": message}
        if unit:
            warning["unit"] = unit
        return warning
    if summary.get("result") == "partial":
        if unit == "paragraph or table":
            without = summary.get("pages_failed", 0)
            message = WORD_PARTIAL_TEXT_MESSAGE.format(without=without, total=total)
        elif unit:
            without = total - with_text
            message = OFFICE_PARTIAL_TEXT_MESSAGE.format(
                without=without, total=total, units=_UNIT_PLURAL.get(unit, unit)
            )
        else:
            without = total - with_text
            message = PARTIAL_TEXT_MESSAGE.format(without=without, total=total)
        warning = {
            "level": "warning",
            "code": "partial_text",
            "pages_without_text": without,
            "total_pages": total,
            "message": message,
        }
        if unit:
            warning["unit"] = unit
        return warning
    return None


class _TextExtractionFieldsMixin(serializers.Serializer):
    text_extraction = serializers.SerializerMethodField()
    text_extraction_warning = serializers.SerializerMethodField()

    def get_text_extraction(self, obj):
        return text_extraction_summary(obj)

    def get_text_extraction_warning(self, obj):
        return text_extraction_warning(obj)


class DocumentVersionStatusSerializer(_TextExtractionFieldsMixin, serializers.ModelSerializer):
    """Lightweight version status for polling."""

    class Meta:
        model = DocumentVersion
        fields = [
            "public_id",
            "version_number",
            "scan_status",
            "processing_status",
            "failure_code",
            "failure_detail",
            "processing_started_at",
            "processing_finished_at",
            "uploaded_at",
            "text_extraction",
            "text_extraction_warning",
        ]
        read_only_fields = fields


class DocumentVersionSerializer(_TextExtractionFieldsMixin, serializers.ModelSerializer):
    uploaded_by_email = serializers.EmailField(
        source="uploaded_by.email", read_only=True, default=None
    )

    class Meta:
        model = DocumentVersion
        fields = [
            "public_id",
            "version_number",
            "original_filename",
            "extension",
            "declared_mime_type",
            "detected_mime_type",
            "size_bytes",
            "sha256_checksum",
            "scan_status",
            "processing_status",
            "failure_code",
            "failure_detail",
            "uploaded_by_email",
            "uploaded_at",
            "processing_started_at",
            "processing_finished_at",
            "source_metadata",
            "text_extraction",
            "text_extraction_warning",
        ]
        read_only_fields = fields
        # storage_key is explicitly excluded — never exposed


class DocumentSerializer(serializers.ModelSerializer):
    current_version = DocumentVersionSerializer(read_only=True)
    created_by_email = serializers.EmailField(
        source="created_by.email", read_only=True, default=None
    )

    class Meta:
        model = Document
        fields = [
            "public_id",
            "title",
            "document_type",
            "status",
            "current_version",
            "created_by_email",
            "created_at",
            "updated_at",
            "archived_at",
        ]
        read_only_fields = [
            "public_id",
            "status",
            "current_version",
            "created_by_email",
            "created_at",
            "updated_at",
            "archived_at",
        ]


class DocumentCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=500)
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    file = serializers.FileField(write_only=True)

    def validate_title(self, value):
        return value.strip()


class DocumentVersionUploadSerializer(serializers.Serializer):
    file = serializers.FileField(write_only=True)


class DocumentLocatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentLocator
        fields = [
            "locator_type",
            "locator_id",
            "display_label",
            "structured_metadata",
            "extracted_text",
            "ordering",
        ]
        read_only_fields = fields


class DocumentProcessingJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentProcessingJob
        fields = [
            "job_type",
            "status",
            "attempt_count",
            "max_attempts",
            "started_at",
            "finished_at",
            "error_code",
            "error_message",
            "correlation_id",
        ]
        read_only_fields = fields
        # celery_task_id excluded — internal
