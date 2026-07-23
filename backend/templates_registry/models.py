"""
Regulatory template registry domain models.

No SQLite. No AIDatabase. No 483/warning-letter/inspection content.
Internal BigAutoField PKs are never exposed in API responses.
Callers use public_id (UUID) for all external references.

This milestone builds the canonical data model, import pipeline,
provenance controls, reconciliation workflow, and approval lifecycle for
regulatory template *content* only. It does not implement checklist
execution, IIG calculations, scoring, AI, or report generation.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .managers import (
    ApprovalTenantScopedManager,
    SectionRelatedTenantScopedManager,
    SourcePackageRelatedTenantScopedManager,
    TenantOrPlatformScopedManager,
    VersionRelatedTenantScopedManager,
)


class TemplateLifecycleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    IMPORTED = "imported", "Imported"
    UNDER_REVIEW = "under_review", "Under Review"
    RETURNED = "returned", "Returned"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"
    RETIRED = "retired", "Retired"
    REJECTED = "rejected", "Rejected"


# Statuses that make a TemplateVersion's content immutable. Corrections
# require a new version, never an edit to one of these.
IMMUTABLE_VERSION_STATUSES = frozenset(
    {
        TemplateLifecycleStatus.APPROVED,
        TemplateLifecycleStatus.ACTIVE,
        TemplateLifecycleStatus.SUPERSEDED,
        TemplateLifecycleStatus.RETIRED,
    }
)


class ResponseType(models.TextChoices):
    YES_NO = "yes_no", "Yes / No"
    YES_NO_NA = "yes_no_na", "Yes / No / Not Applicable"
    TEXT = "text", "Free Text"
    SELECT_ONE = "select_one", "Select One"
    SELECT_MANY = "select_many", "Select Many"
    NARRATIVE = "narrative", "Narrative / Guidance Only"


class RegulatoryTemplate(PublicIDModel, TimeStampedModel):
    """A canonical, tenant-scoped (or platform-level master) regulatory
    template. Content lives on TemplateVersion; this row is the stable
    identity a template keeps across versions."""

    # Nullable only for an explicitly-supported platform-level master
    # template (a template not owned by any single tenant). Every other
    # row must have a tenant.
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="regulatory_templates",
        null=True,
        blank=True,
        db_index=True,
    )
    canonical_code = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=500)
    category = models.CharField(max_length=255, blank=True)
    regulatory_pathway = models.CharField(max_length=255, blank=True)
    dosage_form_applicability = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    lifecycle_status = models.CharField(
        max_length=20,
        choices=TemplateLifecycleStatus.choices,
        default=TemplateLifecycleStatus.DRAFT,
        db_index=True,
    )
    current_approved_version = models.OneToOneField(
        "templates_registry.TemplateVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_regulatory_templates",
    )

    objects = TenantOrPlatformScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "canonical_code"],
                name="unique_template_canonical_code_per_tenant",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "lifecycle_status"])]

    def __str__(self):
        return f"{self.canonical_code} ({self.title})"


class TemplateVersion(PublicIDModel, TimeStampedModel):
    template = models.ForeignKey(
        "templates_registry.RegulatoryTemplate",
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    raw_source_checksum = models.CharField(max_length=64, blank=True)
    normalized_checksum = models.CharField(max_length=64, blank=True)
    source_package = models.ForeignKey(
        "templates_registry.TemplateSourcePackage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="template_versions",
    )
    status = models.CharField(
        max_length=20,
        choices=TemplateLifecycleStatus.choices,
        default=TemplateLifecycleStatus.DRAFT,
        db_index=True,
    )
    effective_date = models.DateField(null=True, blank=True)
    superseded_date = models.DateField(null=True, blank=True)

    # Approval metadata (denormalized summary; the authoritative trail is
    # TemplateApproval rows).
    approved_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_template_versions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_template_versions",
    )

    objects = VersionRelatedTenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version_number"],
                name="unique_template_version_number",
            ),
            # Defense in depth: the lifecycle service enforces "only one
            # active version" transactionally with select_for_update, but a
            # DB-level partial unique index makes it impossible even if a
            # future code path bypasses the service.
            models.UniqueConstraint(
                fields=["template"],
                condition=models.Q(status=TemplateLifecycleStatus.ACTIVE),
                name="unique_active_version_per_template",
            ),
        ]
        indexes = [models.Index(fields=["template", "status"])]

    def __str__(self):
        return f"{self.template.canonical_code} v{self.version_number} ({self.status})"

    def clean(self):
        # Immutability guard at the model layer. The authoritative
        # enforcement is in the lifecycle service (transactional,
        # select_for_update); this is a defense-in-depth backstop for any
        # direct .save() call, including from the admin.
        if self.pk:
            original = TemplateVersion.objects.filter(pk=self.pk).first()
            if original and original.status in IMMUTABLE_VERSION_STATUSES:
                changed_fields = {
                    f.name
                    for f in self._meta.fields
                    if f.name not in ("status", "superseded_date", "updated_at")
                    and getattr(original, f.name) != getattr(self, f.name)
                }
                if changed_fields:
                    raise ValidationError(
                        f"TemplateVersion {self.pk} is {original.status} and immutable; "
                        f"cannot change {sorted(changed_fields)}. Create a new version instead."
                    )


class TemplateSection(PublicIDModel):
    template_version = models.ForeignKey(
        "templates_registry.TemplateVersion",
        on_delete=models.CASCADE,
        related_name="sections",
    )
    canonical_section_code = models.CharField(max_length=100)
    raw_title = models.TextField()
    normalized_title = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)
    parent_section = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="child_sections",
    )
    source_locator = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = VersionRelatedTenantScopedManager()

    class Meta:
        ordering = ["display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["template_version", "canonical_section_code"],
                name="unique_section_code_per_version",
            ),
        ]

    def __str__(self):
        return f"{self.canonical_section_code}: {self.normalized_title or self.raw_title[:60]}"


class TemplateItem(PublicIDModel):
    template_section = models.ForeignKey(
        "templates_registry.TemplateSection",
        on_delete=models.CASCADE,
        related_name="items",
    )
    canonical_item_code = models.CharField(max_length=100)
    raw_text = models.TextField()
    normalized_text = models.TextField(blank=True)
    guidance_text = models.TextField(blank=True)
    response_type = models.CharField(
        max_length=20, choices=ResponseType.choices, default=ResponseType.NARRATIVE
    )
    required = models.BooleanField(default=False)
    # Placeholder only -- no applicability-rule evaluation logic exists in
    # this milestone. Reserved for a future parameterized-template pattern
    # (e.g. IIG-style templates with separate parameter sets), which is
    # explicitly out of scope here.
    applicability_rule = models.JSONField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    legacy_identifier = models.CharField(max_length=255, blank=True)
    source_locator = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = SectionRelatedTenantScopedManager()

    class Meta:
        ordering = ["display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["template_section", "canonical_item_code"],
                name="unique_item_code_per_section",
            ),
        ]

    def __str__(self):
        return f"{self.canonical_item_code}: {self.normalized_text[:60] or self.raw_text[:60]}"


class TemplateItemOption(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    template_item = models.ForeignKey(
        "templates_registry.TemplateItem",
        on_delete=models.CASCADE,
        related_name="options",
    )
    code = models.CharField(max_length=100)
    raw_label = models.CharField(max_length=500)
    normalized_label = models.CharField(max_length=500, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["template_item", "code"],
                name="unique_option_code_per_item",
            ),
        ]

    def __str__(self):
        return f"{self.code}: {self.normalized_label or self.raw_label}"


class SourceApprovalState(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class TemplateSourcePackage(PublicIDModel, TimeStampedModel):
    """A registered, checksummed batch of source material staged for
    import. Registration alone does not import or activate anything."""

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="template_source_packages",
        null=True,
        blank=True,
        db_index=True,
    )
    source_name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=100)
    source_path_or_reference = models.CharField(max_length=1000)
    source_checksum = models.CharField(max_length=64)
    file_metadata = models.JSONField(default=dict, blank=True)
    source_version = models.CharField(max_length=100, blank=True)
    source_date = models.DateField(null=True, blank=True)
    licensing_ownership_status = models.CharField(max_length=255, blank=True)
    imported_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="registered_template_source_packages",
    )
    imported_at = models.DateTimeField(auto_now_add=True)
    approval_state = models.CharField(
        max_length=20, choices=SourceApprovalState.choices, default=SourceApprovalState.PENDING
    )

    objects = TenantOrPlatformScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_checksum"],
                name="unique_source_checksum_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.source_name} ({self.source_checksum[:12]})"


class MigrationDisposition(models.TextChoices):
    PENDING = "pending", "Pending"
    ELIGIBLE = "eligible", "Eligible"
    EXCLUDED = "excluded", "Excluded"
    REQUIRES_REVIEW = "requires_review", "Requires Review"


class TemplateSourceRecord(TimeStampedModel):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    source_package = models.ForeignKey(
        "templates_registry.TemplateSourcePackage",
        on_delete=models.CASCADE,
        related_name="source_records",
    )
    source_record_identifier = models.CharField(max_length=255)
    raw_payload = models.JSONField()
    raw_text = models.TextField(blank=True)
    raw_checksum = models.CharField(max_length=64, db_index=True)
    source_locator = models.CharField(max_length=500, blank=True)
    extraction_method = models.CharField(max_length=100, blank=True)
    encoding = models.CharField(max_length=50, blank=True)
    migration_disposition = models.CharField(
        max_length=20,
        choices=MigrationDisposition.choices,
        default=MigrationDisposition.PENDING,
        db_index=True,
    )

    objects = SourcePackageRelatedTenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_package", "source_record_identifier"],
                name="unique_source_record_identifier_per_package",
            ),
        ]
        indexes = [models.Index(fields=["source_package", "raw_checksum"])]

    def __str__(self):
        return f"{self.source_package.source_name}:{self.source_record_identifier}"


class NormalizationMapping(TimeStampedModel):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    source_record = models.ForeignKey(
        "templates_registry.TemplateSourceRecord",
        on_delete=models.CASCADE,
        related_name="normalization_mappings",
    )
    field_name = models.CharField(max_length=100)
    raw_value = models.TextField(blank=True)
    normalized_value = models.TextField(blank=True)
    normalization_rule = models.CharField(max_length=255)
    reviewer = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="normalization_mappings_reviewed",
    )
    reason = models.TextField(blank=True)

    def __str__(self):
        return f"{self.source_record_id}:{self.field_name} [{self.normalization_rule}]"


class DuplicateMatchType(models.TextChoices):
    EXACT_RAW_CHECKSUM = "exact_raw_checksum", "Exact Raw Checksum"
    EXACT_NORMALIZED_CHECKSUM = "exact_normalized_checksum", "Exact Normalized Checksum"
    CANONICAL_CODE = "canonical_code", "Canonical Code"
    LEGACY_IDENTIFIER = "legacy_identifier", "Legacy Identifier"
    NORMALIZED_TEXT = "normalized_text", "Normalized Text"
    FUZZY_SIMILARITY = "fuzzy_similarity", "Fuzzy Similarity (review only)"


class DuplicateResolution(models.TextChoices):
    PENDING = "pending", "Pending"
    SAME = "same", "Same"
    DISTINCT = "distinct", "Distinct"
    SUPERSEDED = "superseded", "Superseded"
    MERGE_APPROVED = "merge_approved", "Merge Approved"


class TemplateDuplicateCandidate(TimeStampedModel):
    """A deterministic (or, for fuzzy matches, human-reviewed-only)
    duplicate candidate. Never auto-collapses records -- resolution is
    always an explicit reviewer decision."""

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    # Exactly one of these identifies the "new" side of the candidate pair.
    subject_source_record = models.ForeignKey(
        "templates_registry.TemplateSourceRecord",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="duplicate_candidates_as_subject",
    )
    subject_template_item = models.ForeignKey(
        "templates_registry.TemplateItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="duplicate_candidates_as_subject",
    )
    suspected_match_item = models.ForeignKey(
        "templates_registry.TemplateItem",
        on_delete=models.CASCADE,
        related_name="duplicate_candidates_as_match",
    )
    match_type = models.CharField(max_length=30, choices=DuplicateMatchType.choices)
    similarity_evidence = models.JSONField(default=dict, blank=True)
    resolution = models.CharField(
        max_length=20, choices=DuplicateResolution.choices, default=DuplicateResolution.PENDING
    )
    reviewer = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicate_candidates_reviewed",
    )
    reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(
                        subject_source_record__isnull=False, subject_template_item__isnull=True
                    )
                    | models.Q(
                        subject_source_record__isnull=True, subject_template_item__isnull=False
                    )
                ),
                name="duplicate_candidate_exactly_one_subject",
            ),
        ]

    def __str__(self):
        return f"DuplicateCandidate({self.match_type}, {self.resolution})"


class MigrationBatchStatus(models.TextChoices):
    REGISTERED = "registered", "Registered"
    EXTRACTING = "extracting", "Extracting"
    VALIDATING = "validating", "Validating"
    CLASSIFYING = "classifying", "Classifying"
    NORMALIZING = "normalizing", "Normalizing"
    DUPLICATE_DETECTION = "duplicate_detection", "Duplicate Detection"
    IMPORTING = "importing", "Importing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class MigrationBatch(PublicIDModel, TimeStampedModel):
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="migration_batches",
        null=True,
        blank=True,
        db_index=True,
    )
    source_package = models.ForeignKey(
        "templates_registry.TemplateSourcePackage",
        on_delete=models.CASCADE,
        related_name="migration_batches",
    )
    status = models.CharField(
        max_length=20, choices=MigrationBatchStatus.choices, default=MigrationBatchStatus.REGISTERED
    )
    started_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="started_migration_batches",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    error_summary = models.TextField(blank=True)
    correlation_id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )

    objects = TenantOrPlatformScopedManager()

    def __str__(self):
        return f"MigrationBatch({self.correlation_id}, {self.status})"


class MigrationRecordResultType(models.TextChoices):
    IMPORTED = "imported", "Imported"
    SKIPPED = "skipped", "Skipped"
    EXCLUDED = "excluded", "Excluded"
    DUPLICATE = "duplicate", "Duplicate"
    FAILED = "failed", "Failed"
    REQUIRES_REVIEW = "requires_review", "Requires Review"


class MigrationRecordResult(TimeStampedModel):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    batch = models.ForeignKey(
        "templates_registry.MigrationBatch",
        on_delete=models.CASCADE,
        related_name="record_results",
    )
    source_record = models.ForeignKey(
        "templates_registry.TemplateSourceRecord",
        on_delete=models.CASCADE,
        related_name="migration_results",
    )
    target_public_identifier = models.UUIDField(null=True, blank=True)
    result = models.CharField(
        max_length=20, choices=MigrationRecordResultType.choices, db_index=True
    )
    reason_code = models.CharField(max_length=100, blank=True)
    safe_detail = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "source_record"],
                name="unique_result_per_batch_and_record",
            ),
        ]

    def __str__(self):
        return f"{self.source_record_id} -> {self.result}"


class ApprovalDecision(models.TextChoices):
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    RETURNED = "returned", "Returned for Correction"


class TemplateApproval(TimeStampedModel):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    template_version = models.ForeignKey(
        "templates_registry.TemplateVersion",
        on_delete=models.CASCADE,
        related_name="approvals",
    )
    reviewer = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="template_approvals",
    )
    decision = models.CharField(max_length=20, choices=ApprovalDecision.choices)
    comments = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(auto_now_add=True)
    approval_sequence = models.PositiveIntegerField()
    role_at_time = models.CharField(max_length=50)

    objects = ApprovalTenantScopedManager()

    class Meta:
        ordering = ["approval_sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["template_version", "approval_sequence"],
                name="unique_approval_sequence_per_version",
            ),
        ]

    def __str__(self):
        return f"{self.template_version_id} seq {self.approval_sequence}: {self.decision}"
