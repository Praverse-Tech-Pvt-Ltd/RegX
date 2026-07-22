"""
Document domain models.

No SQLite. No AIDatabase. No legacy content.
Internal BigAutoField PKs are never exposed in API responses.
Callers use public_id (UUID) for all external references.
"""

import uuid

from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .managers import TenantScopedManager, VersionTenantScopedManager


class DocumentType(models.TextChoices):
    PDF = "pdf", "PDF"
    DOCX = "docx", "DOCX"
    XLSX = "xlsx", "XLSX"
    PPTX = "pptx", "PPTX"


class DocumentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class Document(PublicIDModel, TimeStampedModel):
    """A tenant-scoped logical document. Versions track individual uploads."""

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="documents",
        db_index=True,
    )
    title = models.CharField(max_length=500)
    document_type = models.CharField(max_length=10, choices=DocumentType.choices, db_index=True)
    current_version = models.OneToOneField(
        "documents.DocumentVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.ACTIVE,
        db_index=True,
    )
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_documents",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_documents",
    )

    objects = TenantScopedManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "document_type"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.tenant})"


class ScanStatus(models.TextChoices):
    PENDING = "pending", "Pending Scan"
    CLEAN = "clean", "Clean"
    INFECTED = "infected", "Infected"
    SCAN_FAILED = "scan_failed", "Scan Failed"
    SCANNER_UNAVAILABLE = "scanner_unavailable", "Scanner Unavailable"
    QUARANTINED = "quarantined", "Quarantined"


class ProcessingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"  # e.g. infected file


class DocumentVersion(PublicIDModel, TimeStampedModel):
    """An immutable upload associated with a Document.

    Once created and processed, file metadata is immutable.
    version_number is assigned atomically with select_for_update.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    original_filename = models.CharField(max_length=500)
    normalized_filename = models.CharField(max_length=500)
    extension = models.CharField(max_length=20)
    declared_mime_type = models.CharField(max_length=100)
    detected_mime_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.BigIntegerField()
    sha256_checksum = models.CharField(max_length=64, db_index=True)
    storage_key = models.CharField(max_length=500)
    scan_status = models.CharField(
        max_length=25,
        choices=ScanStatus.choices,
        default=ScanStatus.PENDING,
        db_index=True,
    )
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
    )
    failure_code = models.CharField(max_length=100, blank=True)
    failure_detail = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_versions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_finished_at = models.DateTimeField(null=True, blank=True)
    source_metadata = models.JSONField(default=dict)

    objects = VersionTenantScopedManager()

    class Meta:
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="unique_document_version_number",
            ),
        ]
        indexes = [
            models.Index(fields=["document", "version_number"]),
            models.Index(fields=["sha256_checksum"]),
            models.Index(fields=["scan_status"]),
            models.Index(fields=["processing_status"]),
        ]

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"


class LocatorType(models.TextChoices):
    PAGE = "page", "Page"
    SECTION = "section", "Section"
    PARAGRAPH = "paragraph", "Paragraph"
    TABLE = "table", "Table"
    SHEET = "sheet", "Sheet"
    ROW = "row", "Row"
    COLUMN = "column", "Column"
    SLIDE = "slide", "Slide"
    OBJECT = "object", "Object"


class DocumentLocator(TimeStampedModel):
    """A structural reference point within a document version."""

    version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.CASCADE,
        related_name="locators",
    )
    locator_type = models.CharField(max_length=20, choices=LocatorType.choices, db_index=True)
    locator_id = models.CharField(max_length=200)
    display_label = models.CharField(max_length=500, blank=True)
    structured_metadata = models.JSONField(default=dict)
    extracted_text = models.TextField(blank=True)
    ordering = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        ordering = ["ordering", "locator_type", "locator_id"]
        indexes = [
            models.Index(fields=["version", "locator_type"]),
            models.Index(fields=["version", "ordering"]),
        ]

    def __str__(self):
        return f"{self.locator_type}:{self.locator_id} in {self.version}"


class JobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    FAILED_RETRYABLE = "failed_retryable", "Failed (Retryable)"
    FAILED_PERMANENT = "failed_permanent", "Failed (Permanent)"


class DocumentProcessingJob(TimeStampedModel):
    """Tracks a Celery processing job for a document version."""

    version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.CASCADE,
        related_name="processing_jobs",
    )
    job_type = models.CharField(max_length=50, db_index=True)
    status = models.CharField(
        max_length=25,
        choices=JobStatus.choices,
        default=JobStatus.QUEUED,
        db_index=True,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    correlation_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["version", "job_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["correlation_id"]),
        ]

    def __str__(self):
        return f"{self.job_type} for {self.version} ({self.status})"


class DuplicateRelationType(models.TextChoices):
    EXACT = "exact", "Exact Duplicate"
    SAME_CONTENT = "same_content", "Same Content"


class DocumentDuplicateLink(TimeStampedModel):
    """Cross-reference for SHA-256 duplicates within a tenant.

    No cross-tenant information leakage: tenant is always stored and checked.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="duplicate_links",
    )
    source_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.CASCADE,
        related_name="duplicate_source_links",
    )
    matching_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.CASCADE,
        related_name="duplicate_match_links",
    )
    checksum = models.CharField(max_length=64, db_index=True)
    relationship_type = models.CharField(
        max_length=20,
        choices=DuplicateRelationType.choices,
        default=DuplicateRelationType.EXACT,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_version", "matching_version"],
                name="unique_duplicate_link",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "checksum"]),
        ]

    def __str__(self):
        return f"Duplicate: {self.source_version} ~ {self.matching_version}"
