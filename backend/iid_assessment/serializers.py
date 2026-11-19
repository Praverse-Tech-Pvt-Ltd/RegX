from rest_framework import serializers

from .models import AssessmentSnapshot

_PERCENT_BASES = {"w/w": "w_w", "w/v": "w_v", "v/v": "v_v"}


def _unit_meaning_problem(expression, unit: str) -> str | None:
    """Why the typed unit cannot carry this meaning, or None when it can.

    Mass and volume meanings: the unit must be the meaning's own unit, in any
    spelling a formulation component accepts ("mg", "milligram"; "mL",
    "millilitre"). Percentage meanings: any percentage spelling ("%", "% w/w",
    "percent"), but a basis written in the unit must be the meaning's basis.
    """
    from fda_data.controlled_units import PERCENT_UNIT, stated_amount_problem
    from iid_assessment.amount_limits import is_percentage_unit

    if is_percentage_unit(unit):
        text = unit.lower().replace(" ", "")
        typed = next((code for spelled, code in _PERCENT_BASES.items() if spelled in text), None)
        if typed is not None and expression.family == "percentage" and typed != expression.basis:
            return (
                f"the unit says %{typed.replace('_', '/')} but the meaning chosen is "
                f"%{expression.basis.replace('_', '/')}; choose the meaning that matches, "
                f"or type the unit as '{PERCENT_UNIT}'"
            )
        unit = PERCENT_UNIT
    return stated_amount_problem(expression, unit)


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
    #: The meaning of the proposed quantity (controlled units, increment 4):
    #: a controlled-units meaning such as "mg/5mL" or "%w/w". Omitted: per
    #: dosage unit in `proposed_quantity_unit`, as before.
    proposed_quantity_expression_public_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_proposed_quantity_expression_public_id(self, value):
        if value is None:
            return None
        from fda_data.models import QuantityExpression

        expression = (
            QuantityExpression.objects.select_related("numerator_unit", "denominator_unit")
            .filter(public_id=value)
            .first()
        )
        if expression is None:
            raise serializers.ValidationError("No such quantity meaning.")
        return expression

    def validate(self, attrs):
        # The same amount limits as a formulation component (iid_assessment/amount_limits.py):
        # a zero amount is refused here too, and so are absurdly large ones.
        from iid_assessment.amount_limits import (
            amount_problem,
            dosage_units_per_day_problem,
            is_percentage_unit,
        )

        attrs = super().validate(attrs)
        expression = attrs.get("proposed_quantity_expression_public_id")
        unit = (attrs.get("proposed_quantity_unit") or "").strip()
        if expression is not None:
            # With a meaning, the amount is read in the meaning's own unit, so the
            # typed unit must be exactly that unit. Without this check "0.03 g" with
            # "mg per dose unit" was read as 0.03 mg (validation report 2026-11-19,
            # F-1). Same rule as a formulation component (stated_amount_problem).
            problem = _unit_meaning_problem(expression, unit)
            if problem:
                raise serializers.ValidationError({"proposed_quantity_unit": problem})
        # Any spelling of a percentage ("% w/w", "%w/v", "percent") is capped at 100.
        is_percentage = (
            expression is not None and expression.family == "percentage"
        ) or is_percentage_unit(unit)
        problem = amount_problem(
            attrs.get("proposed_quantity_per_unit"), unit, is_percentage=is_percentage
        )
        if problem:
            raise serializers.ValidationError({"proposed_quantity_per_unit": problem})
        per_day = dosage_units_per_day_problem(attrs.get("maximum_dosage_units_per_day"))
        if per_day:
            raise serializers.ValidationError({"maximum_dosage_units_per_day": per_day})
        return attrs


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
    PROHIBITED_FIELDS = (
        "maximum_dosage_units_per_day",
        # The persisted snapshot reads the meaning from the governed component
        # row, never from the request.
        "proposed_quantity_expression_public_id",
    )

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
