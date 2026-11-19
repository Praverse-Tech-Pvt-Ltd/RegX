from rest_framework import serializers

from fda_data.models import FDAReleaseStatus, OrangeBookProduct

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

    def validate(self, attrs):
        """The selection must name a real Orange Book product in the ACTIVE
        release, and every identifier sent must agree with that product.

        Until this check, any UUID or number was stored, so a selection could
        point at nothing. The snapshot design is unchanged: the identifiers are
        still copied, not linked, so a later release cannot rewrite a past
        selection.
        """
        product = (
            OrangeBookProduct.objects.select_related("release", "application")
            .filter(public_id=attrs["product_public_id"])
            .first()
        )
        if product is None:
            raise serializers.ValidationError(
                {"product_public_id": "No Orange Book product has this identifier."}
            )
        if product.release.status != FDAReleaseStatus.ACTIVE:
            raise serializers.ValidationError(
                {"product_public_id": "This product is not in the active Orange Book release."}
            )
        mismatched = [
            name
            for name, sent, actual in (
                ("release_public_id", attrs["release_public_id"], product.release.public_id),
                (
                    "application_number",
                    attrs["application_number"].strip(),
                    product.application.application_number,
                ),
                ("product_number", attrs["product_number"].strip(), product.product_number),
            )
            if sent != actual
        ]
        if mismatched:
            raise serializers.ValidationError(
                dict.fromkeys(mismatched, "Does not match the selected Orange Book product.")
            )
        return attrs


class FormulationVersionSerializer(serializers.ModelSerializer):
    product = serializers.UUIDField(source="product.public_id", read_only=True)
    created_by_email = serializers.EmailField(
        source="created_by.email", read_only=True, default=None
    )
    submitted_by_email = serializers.EmailField(
        source="submitted_by.email", read_only=True, default=None
    )
    returned_by_email = serializers.EmailField(
        source="returned_by.email", read_only=True, default=None
    )
    rejected_by_email = serializers.EmailField(
        source="rejected_by.email", read_only=True, default=None
    )
    approved_by_email = serializers.EmailField(
        source="approved_by.email", read_only=True, default=None
    )

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
            "created_by_email",
            "submitted_by_email",
            "submitted_at",
            "returned_by_email",
            "returned_at",
            "return_reason",
            "rejected_by_email",
            "rejected_at",
            "reject_reason",
            "approved_by_email",
            "approved_at",
            "approval_note",
            "superseded_at",
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

    def validate_total_dosage_unit_weight(self, value):
        if value <= 0:
            raise serializers.ValidationError("total_dosage_unit_weight must be greater than zero.")
        return value

    def validate_maximum_dosage_units_per_day(self, value):
        from iid_assessment.amount_limits import dosage_units_per_day_problem

        problem = dosage_units_per_day_problem(value)
        if problem:
            raise serializers.ValidationError(problem)
        return value


class FormulationComponentSerializer(serializers.ModelSerializer):
    #: The meaning of `quantity_per_dosage_unit` (controlled units, increment 4).
    #: Omitted or null: an amount per dosage unit in `quantity_unit`, as before.
    quantity_expression_public_id = serializers.UUIDField(
        required=False, allow_null=True, write_only=True
    )
    quantity_meaning = serializers.SerializerMethodField()
    #: False for a component saved before units were checked whose unit REGX
    #: cannot convert or read (e.g. "furlongs"). Shown as "unit not recognised -
    #: cannot be compared"; the row itself is never changed.
    unit_recognised = serializers.SerializerMethodField()

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
            "quantity_expression_public_id",
            "quantity_meaning",
            "unit_recognised",
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

    def validate_quantity_per_dosage_unit(self, value):
        if value <= 0:
            raise serializers.ValidationError("quantity_per_dosage_unit must be greater than zero.")
        return value

    def validate(self, attrs):
        from fda_data.controlled_units import percentage_unit_problem
        from iid_assessment.amount_limits import (
            PERCENT_UNIT,
            amount_problem,
            is_percentage_unit,
            unit_problem,
        )

        current = self.instance
        # The unit as typed, before normalising: its written percentage basis is
        # checked against the meaning (shared rule, unit_meaning_problem).
        typed_unit = attrs.get("quantity_unit")
        # The unit must be one REGX can convert or read (QA-02). Any spelling of
        # a percentage is stored as "percent", the spelling a percentage meaning needs.
        if "quantity_unit" in attrs:
            problem = unit_problem(attrs["quantity_unit"]) or percentage_unit_problem(
                attrs["quantity_unit"]
            )
            if problem:
                raise serializers.ValidationError({"quantity_unit": problem})
            if is_percentage_unit(attrs["quantity_unit"]):
                attrs["quantity_unit"] = PERCENT_UNIT
        attrs = self._resolve_meaning(super().validate(attrs), typed_unit)
        # The same amount limits as the IID preview (iid_assessment/amount_limits.py).
        expression = (
            attrs["quantity_expression"]
            if "quantity_expression" in attrs
            else getattr(current, "quantity_expression", None)
        )
        unit = attrs.get("quantity_unit", getattr(current, "quantity_unit", "")) or ""
        value = attrs.get(
            "quantity_per_dosage_unit", getattr(current, "quantity_per_dosage_unit", None)
        )
        is_percentage = (
            expression is not None and expression.family == "percentage"
        ) or is_percentage_unit(unit)
        problem = amount_problem(value, unit, is_percentage=is_percentage)
        if problem:
            raise serializers.ValidationError({"quantity_per_dosage_unit": problem})
        if is_percentage_unit(unit) and expression is None:
            raise serializers.ValidationError(
                {
                    "quantity_expression_public_id": (
                        "A percentage needs its basis: choose %w/w, %w/v or %v/v under "
                        "'What the quantity means'."
                    )
                }
            )
        version = self.context.get("formulation_version")
        if version is not None:
            from .dosage_forms import per_volume_on_solid_problem

            problem = per_volume_on_solid_problem(version.product.dosage_form, expression)
            if problem:
                raise serializers.ValidationError({"quantity_expression_public_id": problem})
        return attrs

    def _resolve_meaning(self, attrs, typed_unit=None):
        from fda_data.controlled_units import in_force_expression, unit_meaning_problem

        if "quantity_expression_public_id" not in attrs:
            return attrs  # not mentioned: keep what is stored (or the default, none)
        public_id = attrs.pop("quantity_expression_public_id")
        if public_id is None:
            attrs["quantity_expression"] = None  # explicitly cleared
            return attrs
        expression = in_force_expression(public_id)
        if expression is None:
            raise serializers.ValidationError(
                {
                    "quantity_expression_public_id": (
                        "No such meaning in the active controlled-units list."
                    )
                }
            )
        unit = (
            typed_unit
            if typed_unit is not None
            else attrs.get("quantity_unit", getattr(self.instance, "quantity_unit", ""))
        )
        problem = unit_meaning_problem(expression, unit)
        if problem:
            raise serializers.ValidationError({"quantity_expression_public_id": problem})
        attrs["quantity_expression"] = expression
        return attrs

    def get_unit_recognised(self, obj) -> bool:
        from iid_assessment.amount_limits import recognised_unit

        return recognised_unit(obj.quantity_unit) is not None

    def get_quantity_meaning(self, obj) -> str:
        expression = obj.quantity_expression
        if expression is None:
            return f"{obj.quantity_unit} per dosage unit"
        return str(expression)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        expression = instance.quantity_expression
        data["quantity_expression_public_id"] = str(expression.public_id) if expression else None
        return data


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

    def validate_administrations_per_day(self, value):
        if value <= 0:
            raise serializers.ValidationError("administrations_per_day must be greater than zero.")
        return value

    def validate_maximum_units_per_day(self, value):
        from iid_assessment.amount_limits import dosage_units_per_day_problem

        problem = dosage_units_per_day_problem(value)
        if problem:
            raise serializers.ValidationError(problem)
        return value
