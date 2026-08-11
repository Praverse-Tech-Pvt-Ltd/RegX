from rest_framework import serializers

from .models import AssessmentSnapshot


class MatchPreviewRequestSerializer(serializers.Serializer):
    # Exactly one identity path must be supplied: either an already-resolved
    # ingredient_public_id, or a raw substance identity (name/UNII/CAS) that
    # is resolved through the governed SubstanceSynonymMapping service.
    # Supplying neither leaves ingredient identity unresolved
    # (INGREDIENT_AMBIGUOUS); supplying a raw identity never bypasses
    # approved-mapping governance.
    ingredient_public_id = serializers.UUIDField(required=False, allow_null=True)
    substance_name = serializers.CharField(max_length=500, required=False, allow_blank=True)
    substance_unii = serializers.CharField(max_length=20, required=False, allow_blank=True)
    substance_cas = serializers.CharField(max_length=50, required=False, allow_blank=True)
    route_code = serializers.CharField(max_length=50)
    dosage_form_code = serializers.CharField(max_length=50)
    active_release_public_id = serializers.UUIDField()
    proposed_quantity_per_unit = serializers.DecimalField(max_digits=20, decimal_places=6)
    proposed_quantity_unit = serializers.CharField(max_length=50)
    total_dosage_unit_weight = serializers.DecimalField(max_digits=20, decimal_places=6)
    total_dosage_unit_weight_unit = serializers.CharField(max_length=50)
    maximum_dosage_units_per_day = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True
    )
    density_g_per_ml = serializers.DecimalField(
        max_digits=20, decimal_places=6, required=False, allow_null=True
    )
    selected_precedent_record_public_id = serializers.UUIDField(required=False, allow_null=True)


class SnapshotRequestSerializer(MatchPreviewRequestSerializer):
    """Transport shape for the **persisted** snapshot endpoint.

    M4D3-MDU-006: "no dosing value shall ever be accepted from a client request
    payload", and the acceptance matrix names the request serializer as the
    enforcement point. ``maximum_dosage_units_per_day`` is therefore removed from
    the accepted fields here and derived server-side through the governed Part
    14.1 selection instead.

    It stays on ``MatchPreviewRequestSerializer``: that endpoint persists
    nothing, so a caller exploring a hypothetical dosing figure freezes no
    regulated record. Only the snapshot -- an immutable record whose
    ``decision_status`` depends on the value -- is governed by M4D3-MDU-006.

    A request that supplies the field is **rejected**, never silently ignored: a
    caller who believes they set the dosing basis for a regulated assessment must
    not be told it succeeded.
    """

    #: Fields the persisted endpoint refuses rather than accepts or drops.
    PROHIBITED_FIELDS = ("maximum_dosage_units_per_day",)

    formulation_component_public_id = serializers.UUIDField()
    formulation_version_public_id = serializers.UUIDField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Not merely unused -- not part of this endpoint's contract at all, so it
        # is absent from the generated schema too.
        for name in self.PROHIBITED_FIELDS:
            self.fields.pop(name, None)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        supplied = sorted(
            name
            for name in self.PROHIBITED_FIELDS
            if isinstance(self.initial_data, dict) and name in self.initial_data
        )
        if supplied:
            raise serializers.ValidationError(
                {
                    "error_code": "prohibited_request_field",
                    "detail": (
                        "Dosing values are derived from the governed formulation "
                        "and cannot be supplied by a client (M4D3-MDU-006)."
                    ),
                    "fields": supplied,
                }
            )
        return attrs


class AssessmentSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentSnapshot
        fields = [
            "public_id",
            "formulation_component_public_id",
            "formulation_version_public_id",
            "iid_release_public_id",
            "iid_precedent_record_public_id",
            "iid_substance_mapping_public_id",
            "iid_ingredient_name",
            "iid_route",
            "iid_dosage_form",
            "iid_potency_amount",
            "iid_potency_unit",
            "iid_mde",
            "iid_mde_unit",
            "proposed_quantity_per_unit",
            "proposed_quantity_unit",
            "proposed_daily_exposure",
            "calculation_results",
            "match_status",
            "decision_status",
            "decision_note",
            "reviewer_confirmed_match",
            "override_applied",
            "override_justification",
            "final_conclusion",
            "created_at",
        ]
        read_only_fields = fields
