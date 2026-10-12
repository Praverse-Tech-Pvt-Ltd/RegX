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
    DosageFormMapping,
    FDADataSourceRelease,
    FdaImportRowResult,
    IIDPrecedentRecord,
    OrangeBookProduct,
    RouteMapping,
    SubstanceMappingMethod,
    SubstanceSynonymMapping,
    UnitMapping,
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
            "marketing_category",
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


# Each entry: (model_cls, controlled_fk_attr, controlled_label_attr,
# raw_value_attr, reason_attr). The substance mapping type uses different
# field names (raw_ingredient_name/review_reason) than the shared
# _BaseTerminologyMapping shape (source_raw_value/reason), so the
# serializer below reads through these per-type attribute names rather
# than assuming one fixed shape.
MAPPING_TYPE_CONFIG = {
    "route": (RouteMapping, "controlled_route", "canonical_label", "source_raw_value", "reason"),
    "dosage_form": (
        DosageFormMapping,
        "controlled_dosage_form",
        "canonical_label",
        "source_raw_value",
        "reason",
    ),
    "unit": (UnitMapping, "controlled_unit", "code", "source_raw_value", "reason"),
    "substance": (
        SubstanceSynonymMapping,
        "proposed_ingredient",
        "canonical_name",
        "raw_ingredient_name",
        "review_reason",
    ),
}


class TerminologyMappingSerializer(serializers.Serializer):
    """Normalized shape shared across RouteMapping/DosageFormMapping/
    UnitMapping/SubstanceSynonymMapping so the mapping-review UI can
    render one table regardless of type. No fuzzy mapping is ever exposed
    as auto-approved -- status always reflects the real, persisted
    mapping status."""

    public_id = serializers.UUIDField(read_only=True)
    mapping_type = serializers.CharField(read_only=True)
    source_dataset = serializers.CharField(read_only=True)
    source_raw_value = serializers.CharField(read_only=True)
    proposed_controlled_value = serializers.CharField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    is_current = serializers.BooleanField(read_only=True)
    reviewer_email = serializers.CharField(read_only=True, allow_null=True)
    reason = serializers.CharField(read_only=True)
    affected_record_count = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    # Substance-mapping-specific fields, null for other mapping types.
    proposed_unii = serializers.CharField(read_only=True, allow_null=True, required=False)
    proposed_cas_number = serializers.CharField(read_only=True, allow_null=True, required=False)
    mapping_method = serializers.CharField(read_only=True, allow_null=True, required=False)
    release_public_id = serializers.CharField(read_only=True, allow_null=True, required=False)

    @staticmethod
    def from_instance(mapping_type: str, instance, affected_record_count: int) -> dict:
        _, fk_name, label_field, raw_value_attr, reason_attr = MAPPING_TYPE_CONFIG[mapping_type]
        controlled = getattr(instance, fk_name, None)
        data = {
            "public_id": instance.public_id,
            "mapping_type": mapping_type,
            "source_dataset": instance.source_dataset,
            "source_raw_value": getattr(instance, raw_value_attr),
            "proposed_controlled_value": getattr(controlled, label_field, None)
            if controlled
            else None,
            "status": instance.status,
            "is_current": instance.is_current,
            "reviewer_email": instance.reviewer.email if instance.reviewer else None,
            "reason": getattr(instance, reason_attr),
            "affected_record_count": affected_record_count,
            "created_at": instance.created_at,
        }
        if mapping_type == "substance":
            data["proposed_unii"] = instance.proposed_unii or (
                controlled.unii if controlled else None
            )
            data["proposed_cas_number"] = instance.proposed_cas_number
            data["mapping_method"] = instance.mapping_method
            data["release_public_id"] = (
                str(instance.release.public_id) if instance.release_id else None
            )
        return data


class MappingReviewActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class SubstanceMappingProposalSerializer(serializers.Serializer):
    """Input for the production substance-mapping proposal endpoint. Never
    accepts a status field -- every proposal created through this endpoint
    is PROPOSED, full stop; there is no way to submit a pre-approved row.
    """

    release_public_id = serializers.UUIDField(required=False, allow_null=True)
    raw_ingredient_name = serializers.CharField(max_length=500)
    normalized_ingredient_name = serializers.CharField(max_length=500)
    raw_unii = serializers.CharField(max_length=20, required=False, allow_blank=True)
    raw_cas_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    source_row_locator = serializers.CharField(max_length=255, required=False, allow_blank=True)
    proposed_ingredient_public_id = serializers.UUIDField(required=False, allow_null=True)
    proposed_unii = serializers.CharField(max_length=20, required=False, allow_blank=True)
    proposed_cas_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    mapping_method = serializers.ChoiceField(choices=SubstanceMappingMethod.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class AffectedRecordSerializer(serializers.Serializer):
    record_public_id = serializers.CharField()
    dataset_type = serializers.CharField()
    release_public_id = serializers.CharField(allow_null=True)
    source_row_locator = serializers.CharField(allow_null=True, required=False)
    raw_value = serializers.CharField()
    normalized_value = serializers.CharField(allow_null=True)
    mapping_status = serializers.CharField(allow_null=True)
    calculability_status = serializers.CharField(allow_null=True, required=False)
    blocked = serializers.BooleanField()
    reason_code = serializers.CharField(allow_blank=True)
