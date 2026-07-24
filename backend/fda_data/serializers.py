"""FDA data-governance serializers.

No internal numeric IDs in any response. storage_key/source file paths are
excluded from the default serializer and only exposed via the raw variant
to holders of fda_data.view_raw.
"""

from rest_framework import serializers

from .models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    FDADataSourceRelease,
    FdaImportRowResult,
    IIDPrecedentRecord,
    OrangeBookProduct,
)


class FDADataSourceReleaseSerializer(serializers.ModelSerializer):
    superseded_by_release = serializers.UUIDField(
        source="superseded_by_release.public_id", read_only=True, default=None
    )
    imported_by_email = serializers.EmailField(
        source="imported_by.email", read_only=True, default=None
    )
    approved_by_email = serializers.EmailField(
        source="approved_by.email", read_only=True, default=None
    )
    activated_by_email = serializers.EmailField(
        source="activated_by.email", read_only=True, default=None
    )

    class Meta:
        model = FDADataSourceRelease
        fields = [
            "public_id",
            "dataset_type",
            "source_name",
            "official_source_reference",
            "schema_version",
            "publication_date",
            "retrieved_at",
            "imported_at",
            "imported_by_email",
            "record_count_expected",
            "record_count_extracted",
            "record_count_imported",
            "record_count_failed",
            "status",
            "approved_by_email",
            "approved_at",
            "activated_by_email",
            "activated_at",
            "superseded_by_release",
            "correlation_id",
            "created_at",
        ]
        read_only_fields = fields


class FDADataSourceReleaseRawSerializer(FDADataSourceReleaseSerializer):
    class Meta(FDADataSourceReleaseSerializer.Meta):
        fields = [
            *FDADataSourceReleaseSerializer.Meta.fields,
            "original_filename",
            "media_type",
            "source_checksum_sha256",
            "notes",
        ]


class ControlledRouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlledRoute
        fields = ["public_id", "code", "canonical_label", "lifecycle"]
        read_only_fields = fields


class ControlledDosageFormSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlledDosageForm
        fields = ["public_id", "code", "canonical_label", "lifecycle"]
        read_only_fields = fields


class ControlledUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlledUnit
        fields = ["public_id", "code", "symbol", "dimension", "active"]
        read_only_fields = fields


class OrangeBookProductSerializer(serializers.ModelSerializer):
    release = serializers.UUIDField(source="release.public_id", read_only=True)
    application_number = serializers.CharField(
        source="application.application_number", read_only=True
    )
    application_type = serializers.CharField(source="application.application_type", read_only=True)
    route_normalized = serializers.CharField(
        source="route_normalized.canonical_label", read_only=True, default=None
    )
    dosage_form_normalized = serializers.CharField(
        source="dosage_form_normalized.canonical_label", read_only=True, default=None
    )

    class Meta:
        model = OrangeBookProduct
        fields = [
            "public_id",
            "release",
            "application_number",
            "application_type",
            "product_number",
            "trade_name",
            "active_ingredient_raw",
            "dosage_form_raw",
            "route_raw",
            "dosage_form_normalized",
            "route_normalized",
            "strength_raw",
            "strength_amount",
            "strength_parse_status",
            "rld_flag",
            "reference_standard_flag",
            "te_code",
            "approval_date",
            "approval_date_text",
            "discontinued",
        ]
        read_only_fields = fields


class IIDPrecedentRecordSerializer(serializers.ModelSerializer):
    release = serializers.UUIDField(source="release.public_id", read_only=True)
    route_normalized = serializers.CharField(
        source="route_normalized.canonical_label", read_only=True, default=None
    )
    dosage_form_normalized = serializers.CharField(
        source="dosage_form_normalized.canonical_label", read_only=True, default=None
    )
    potency_unit_normalized = serializers.CharField(
        source="potency_unit_normalized.symbol", read_only=True, default=None
    )
    mde_unit_normalized = serializers.CharField(
        source="mde_unit_normalized.symbol", read_only=True, default=None
    )

    class Meta:
        model = IIDPrecedentRecord
        fields = [
            "public_id",
            "release",
            "ingredient_name_raw",
            "route_raw",
            "route_normalized",
            "dosage_form_raw",
            "dosage_form_normalized",
            "potency_amount",
            "potency_unit_raw",
            "potency_unit_normalized",
            "maximum_daily_exposure",
            "mde_unit_raw",
            "mde_unit_normalized",
            "calculability_status",
        ]
        read_only_fields = fields


class FdaImportRowResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = FdaImportRowResult
        fields = [
            "public_id",
            "row_locator",
            "target_public_identifier",
            "result",
            "reason_code",
            "safe_detail",
        ]
        read_only_fields = fields


class ReleaseRegistrationSerializer(serializers.Serializer):
    dataset_type = serializers.ChoiceField(
        choices=[
            "orange_book_products",
            "orange_book_discontinued",
            "orange_book_patents",
            "orange_book_exclusivity",
            "fda_iid",
            "fda_substance_identifiers",
            "fda_route_terminology",
            "fda_dosage_form_terminology",
        ]
    )
    source_name = serializers.CharField(max_length=255)
    official_source_reference = serializers.CharField(max_length=500)
    schema_version = serializers.CharField(max_length=50, required=False, allow_blank=True)
    publication_date = serializers.DateField(required=False, allow_null=True)
    rows = serializers.ListField(child=serializers.DictField(), allow_empty=True)
    file_name = serializers.CharField(
        max_length=255, required=False, default="synthetic-upload.json"
    )


class ReviewActionSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True)
