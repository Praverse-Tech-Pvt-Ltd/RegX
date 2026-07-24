from rest_framework import serializers

from .models import (
    DosingRegimen,
    FormulationComponent,
    FormulationVersion,
    ProductDevelopmentRecord,
)


class ProductDevelopmentRecordSerializer(serializers.ModelSerializer):
    selecting_user_email = serializers.EmailField(
        source="selecting_user.email", read_only=True, default=None
    )

    class Meta:
        model = ProductDevelopmentRecord
        fields = [
            "public_id",
            "product_code",
            "proposed_product_name",
            "active_ingredient",
            "is_combination_product",
            "release_type",
            "route",
            "dosage_form",
            "proposed_strength_amount",
            "proposed_strength_unit",
            "regulatory_market_context",
            "selected_ob_application_number",
            "selected_ob_product_number",
            "selected_ob_product_public_id",
            "selected_ob_release_public_id",
            "selection_timestamp",
            "selecting_user_email",
            "selection_justification",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "public_id",
            "selected_ob_application_number",
            "selected_ob_product_number",
            "selected_ob_product_public_id",
            "selected_ob_release_public_id",
            "selection_timestamp",
            "selecting_user_email",
            "created_at",
        ]


class ProductDevelopmentRecordCreateSerializer(serializers.Serializer):
    product_code = serializers.CharField(max_length=100)
    proposed_product_name = serializers.CharField(max_length=500)
    active_ingredient = serializers.CharField(max_length=500)
    is_combination_product = serializers.BooleanField(required=False, default=False)
    release_type = serializers.CharField(max_length=20, required=False, default="immediate")
    route = serializers.CharField(max_length=255, required=False, allow_blank=True)
    dosage_form = serializers.CharField(max_length=255, required=False, allow_blank=True)
    proposed_strength_amount = serializers.DecimalField(
        max_digits=20, decimal_places=6, required=False, allow_null=True
    )
    proposed_strength_unit = serializers.CharField(max_length=50, required=False, allow_blank=True)
    regulatory_market_context = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )


class ReferenceProductSelectionSerializer(serializers.Serializer):
    application_number = serializers.CharField(max_length=50)
    product_number = serializers.CharField(max_length=50)
    product_public_id = serializers.UUIDField()
    release_public_id = serializers.UUIDField()
    justification = serializers.CharField(required=False, allow_blank=True)


class FormulationVersionSerializer(serializers.ModelSerializer):
    product = serializers.UUIDField(source="product.public_id", read_only=True)

    class Meta:
        model = FormulationVersion
        fields = [
            "public_id",
            "product",
            "version_number",
            "status",
            "total_dosage_unit_weight",
            "total_dosage_unit_weight_unit",
            "batch_size",
            "batch_size_unit",
            "overage_percentage",
            "maximum_dosage_units_per_day",
            "dosing_basis",
            "rationale",
            "created_at",
        ]
        read_only_fields = fields


class FormulationVersionCreateSerializer(serializers.Serializer):
    total_dosage_unit_weight = serializers.DecimalField(max_digits=20, decimal_places=6)
    total_dosage_unit_weight_unit = serializers.CharField(max_length=50)
    batch_size = serializers.DecimalField(
        max_digits=20, decimal_places=6, required=False, allow_null=True
    )
    batch_size_unit = serializers.CharField(max_length=50, required=False, allow_blank=True)
    overage_percentage = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True
    )
    maximum_dosage_units_per_day = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True
    )
    dosing_basis = serializers.CharField(max_length=255, required=False, allow_blank=True)
    rationale = serializers.CharField(required=False, allow_blank=True)


class FormulationComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormulationComponent
        fields = [
            "public_id",
            "component_type",
            "ingredient_name",
            "resolved_ingredient_public_id",
            "resolved_unii",
            "function",
            "grade",
            "quantity_per_dosage_unit",
            "quantity_unit",
            "percentage_w_w_snapshot",
            "quantity_per_batch",
            "batch_quantity_unit",
            "overage_amount",
            "justification",
            "specification_reference",
            "evidence_document_reference",
            "display_order",
        ]
        read_only_fields = ["public_id", "percentage_w_w_snapshot"]


class DosingRegimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DosingRegimen
        fields = [
            "public_id",
            "units_per_administration",
            "administrations_per_day",
            "maximum_units_per_day",
            "patient_population",
            "basis",
            "source_justification",
        ]
        read_only_fields = ["public_id"]
