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


class DocumentVersionStatusSerializer(serializers.ModelSerializer):
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
        ]
        read_only_fields = fields


class DocumentVersionSerializer(serializers.ModelSerializer):
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
