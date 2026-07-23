"""
Template registry serializers.

Rules (matching the document platform):
- No internal numeric IDs in any response.
- No storage/source paths in any response, unless the requester has
  templates.view_raw permission (checked in the view, which then swaps in
  the *_raw serializer variant).
- UUID public_id used for all external references.
"""

from rest_framework import serializers

from .models import (
    MigrationBatch,
    MigrationRecordResult,
    NormalizationMapping,
    RegulatoryTemplate,
    TemplateApproval,
    TemplateDuplicateCandidate,
    TemplateItem,
    TemplateItemOption,
    TemplateSection,
    TemplateSourcePackage,
    TemplateVersion,
)


class TemplateItemOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateItemOption
        fields = ["public_id", "code", "normalized_label", "order"]
        read_only_fields = fields


class TemplateItemOptionRawSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateItemOption
        fields = ["public_id", "code", "raw_label", "normalized_label", "order"]
        read_only_fields = fields


class TemplateItemSerializer(serializers.ModelSerializer):
    options = TemplateItemOptionSerializer(many=True, read_only=True)
    template_section = serializers.UUIDField(source="template_section.public_id", read_only=True)

    class Meta:
        model = TemplateItem
        fields = [
            "public_id",
            "template_section",
            "canonical_item_code",
            "normalized_text",
            "guidance_text",
            "response_type",
            "required",
            "display_order",
            "options",
        ]
        read_only_fields = fields
        # raw_text, legacy_identifier, source_locator, metadata -- excluded;
        # only exposed via TemplateItemRawSerializer for view_raw holders.


class TemplateItemRawSerializer(serializers.ModelSerializer):
    options = TemplateItemOptionRawSerializer(many=True, read_only=True)
    template_section = serializers.UUIDField(source="template_section.public_id", read_only=True)

    class Meta:
        model = TemplateItem
        fields = [
            "public_id",
            "template_section",
            "canonical_item_code",
            "raw_text",
            "normalized_text",
            "guidance_text",
            "response_type",
            "required",
            "display_order",
            "legacy_identifier",
            "source_locator",
            "options",
        ]
        read_only_fields = fields


class TemplateSectionSerializer(serializers.ModelSerializer):
    parent_section = serializers.UUIDField(
        source="parent_section.public_id", read_only=True, default=None
    )

    class Meta:
        model = TemplateSection
        fields = [
            "public_id",
            "canonical_section_code",
            "normalized_title",
            "display_order",
            "parent_section",
        ]
        read_only_fields = fields


class TemplateSectionRawSerializer(TemplateSectionSerializer):
    class Meta(TemplateSectionSerializer.Meta):
        fields = [*TemplateSectionSerializer.Meta.fields, "raw_title", "source_locator"]


class TemplateVersionSerializer(serializers.ModelSerializer):
    template = serializers.UUIDField(source="template.public_id", read_only=True)

    class Meta:
        model = TemplateVersion
        fields = [
            "public_id",
            "template",
            "version_number",
            "status",
            "effective_date",
            "superseded_date",
            "approved_at",
        ]
        read_only_fields = fields
        # source_package, raw/normalized checksums -- excluded from the
        # default view; not internal IDs, but provenance detail reserved
        # for view_raw holders via TemplateVersionRawSerializer.


class TemplateVersionRawSerializer(TemplateVersionSerializer):
    source_package = serializers.UUIDField(
        source="source_package.public_id", read_only=True, default=None
    )

    class Meta(TemplateVersionSerializer.Meta):
        fields = [
            *TemplateVersionSerializer.Meta.fields,
            "raw_source_checksum",
            "normalized_checksum",
            "source_package",
        ]


class RegulatoryTemplateSerializer(serializers.ModelSerializer):
    current_approved_version = serializers.UUIDField(
        source="current_approved_version.public_id", read_only=True, default=None
    )

    class Meta:
        model = RegulatoryTemplate
        fields = [
            "public_id",
            "canonical_code",
            "title",
            "category",
            "regulatory_pathway",
            "dosage_form_applicability",
            "description",
            "lifecycle_status",
            "current_approved_version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TemplateSourcePackageSerializer(serializers.ModelSerializer):
    imported_by_email = serializers.EmailField(
        source="imported_by.email", read_only=True, default=None
    )

    class Meta:
        model = TemplateSourcePackage
        fields = [
            "public_id",
            "source_name",
            "source_type",
            "source_checksum",
            "source_version",
            "source_date",
            "approval_state",
            "imported_by_email",
            "imported_at",
        ]
        read_only_fields = fields
        # source_path_or_reference -- excluded; server-side path, view_raw only.


class TemplateSourcePackageRawSerializer(TemplateSourcePackageSerializer):
    class Meta(TemplateSourcePackageSerializer.Meta):
        fields = [
            *TemplateSourcePackageSerializer.Meta.fields,
            "source_path_or_reference",
            "file_metadata",
            "licensing_ownership_status",
        ]


class TemplateSourcePackageCreateSerializer(serializers.Serializer):
    source_name = serializers.CharField(max_length=255)
    source_type = serializers.CharField(max_length=100)
    source_path_or_reference = serializers.CharField(max_length=1000)
    source_version = serializers.CharField(max_length=100, required=False, allow_blank=True)
    source_date = serializers.DateField(required=False, allow_null=True)
    licensing_ownership_status = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    payload = serializers.JSONField()


class MigrationBatchSerializer(serializers.ModelSerializer):
    source_package = serializers.UUIDField(source="source_package.public_id", read_only=True)
    started_by_email = serializers.EmailField(
        source="started_by.email", read_only=True, default=None
    )

    class Meta:
        model = MigrationBatch
        fields = [
            "public_id",
            "source_package",
            "status",
            "started_by_email",
            "started_at",
            "completed_at",
            "counts",
            "correlation_id",
        ]
        read_only_fields = fields
        # error_summary excluded from default -- may contain internal detail;
        # exposed only via the reconciliation report for view_raw holders.


class MigrationBatchCreateSerializer(serializers.Serializer):
    source_package = serializers.UUIDField()
    records = serializers.ListField(child=serializers.JSONField(), allow_empty=False)


class MigrationRecordResultSerializer(serializers.ModelSerializer):
    source_record_identifier = serializers.CharField(
        source="source_record.source_record_identifier", read_only=True
    )

    class Meta:
        model = MigrationRecordResult
        fields = [
            "public_id",
            "source_record_identifier",
            "target_public_identifier",
            "result",
            "reason_code",
            "safe_detail",
        ]
        read_only_fields = fields


class NormalizationMappingSerializer(serializers.ModelSerializer):
    source_record_identifier = serializers.CharField(
        source="source_record.source_record_identifier", read_only=True
    )
    reviewer_email = serializers.EmailField(source="reviewer.email", read_only=True, default=None)

    class Meta:
        model = NormalizationMapping
        fields = [
            "public_id",
            "source_record_identifier",
            "field_name",
            "raw_value",
            "normalized_value",
            "normalization_rule",
            "reviewer_email",
            "reason",
            "created_at",
        ]
        read_only_fields = fields


class TemplateDuplicateCandidateSerializer(serializers.ModelSerializer):
    reviewer_email = serializers.EmailField(source="reviewer.email", read_only=True, default=None)
    suspected_match_item = serializers.UUIDField(
        source="suspected_match_item.public_id", read_only=True
    )

    class Meta:
        model = TemplateDuplicateCandidate
        fields = [
            "public_id",
            "match_type",
            "similarity_evidence",
            "resolution",
            "reviewer_email",
            "reason",
            "suspected_match_item",
            "created_at",
        ]
        read_only_fields = fields


class DuplicateCandidateResolutionSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(
        choices=["same", "distinct", "superseded", "merge_approved"]
    )
    reason = serializers.CharField(required=False, allow_blank=True)


class TemplateApprovalSerializer(serializers.ModelSerializer):
    reviewer_email = serializers.EmailField(source="reviewer.email", read_only=True, default=None)

    class Meta:
        model = TemplateApproval
        fields = [
            "public_id",
            "reviewer_email",
            "decision",
            "comments",
            "reviewed_at",
            "approval_sequence",
            "role_at_time",
        ]
        read_only_fields = fields


class ReviewActionSerializer(serializers.Serializer):
    comments = serializers.CharField(required=False, allow_blank=True)


class MigrationBatchReviewSerializer(serializers.Serializer):
    """Accepts duplicate-candidate resolutions in bulk as part of the
    reconciliation review step."""

    duplicate_resolutions = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
