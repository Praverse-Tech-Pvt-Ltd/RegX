"""Serializers for the IIG checklist definition-governance API.

UUID-only external identifiers; no `status` field on any plain-edit
serializer (status only changes through the dedicated lifecycle-action
endpoints, see views.py); code fields are normalized before validation.
"""

from rest_framework import serializers

from .codes import CodeValidationError, normalize_code
from .models import (
    ApplicabilityRule,
    ChecklistDefinition,
    ChecklistQuestion,
    ChecklistSection,
    ChecklistVersion,
)


def _normalize_code_field(value):
    try:
        return normalize_code(value)
    except CodeValidationError as exc:
        raise serializers.ValidationError(
            {"error_code": exc.error_code, "detail": str(exc)}
        ) from exc


class ChecklistDefinitionSerializer(serializers.ModelSerializer):
    tenant_public_id = serializers.UUIDField(source="tenant.public_id", read_only=True)

    class Meta:
        model = ChecklistDefinition
        fields = [
            "public_id",
            "code",
            "title",
            "description",
            "scope_type",
            "tenant_public_id",
        ]
        read_only_fields = ["public_id"]

    def validate_code(self, value):
        return _normalize_code_field(value)


class ChecklistVersionSerializer(serializers.ModelSerializer):
    definition_public_id = serializers.UUIDField(source="definition.public_id", read_only=True)

    class Meta:
        model = ChecklistVersion
        fields = [
            "public_id",
            "definition_public_id",
            "version_number",
            "status",
            "effective_date",
            "expiry_date",
            "regulatory_basis",
            "change_summary",
            "cloned_from_version_public_id",
        ]
        # status/version_number are never client-writable through this
        # plain serializer -- status only via the action endpoints,
        # version_number only via the create_next_version() service.
        read_only_fields = [
            "public_id",
            "version_number",
            "status",
            "cloned_from_version_public_id",
        ]


class ApplicabilityRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicabilityRule
        fields = [
            "public_id",
            "code",
            "rule_version",
            "condition_json",
            "outcome_if_true",
            "outcome_if_false",
            "reason_code",
            "explanation_template",
            "field_registry_version",
            "status",
        ]
        read_only_fields = ["public_id", "status"]

    def validate_code(self, value):
        return _normalize_code_field(value)


class ChecklistSectionSerializer(serializers.ModelSerializer):
    applicability_rule_public_id = serializers.UUIDField(
        source="applicability_rule.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = ChecklistSection
        fields = [
            "public_id",
            "code",
            "title",
            "description",
            "display_order",
            "applicability_rule_public_id",
            "criticality",
        ]
        read_only_fields = ["public_id"]

    def validate_code(self, value):
        return _normalize_code_field(value)


class ChecklistQuestionSerializer(serializers.ModelSerializer):
    applicability_rule_public_id = serializers.UUIDField(
        source="applicability_rule.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = ChecklistQuestion
        fields = [
            "public_id",
            "code",
            "question_text",
            "help_text",
            "display_order",
            "answer_type",
            "data_source_classification",
            "applicability_rule_public_id",
            "required",
            "allowed_units",
            "evidence_requirement",
            "calculation_binding_identifier",
            "prefill_source",
            "reviewer_confirmation_required",
            "escalation_rule_identifier",
            "criticality",
            "regulatory_reference",
            "default_value_binding",
            "validation_rule",
        ]
        read_only_fields = ["public_id"]

    def validate_code(self, value):
        return _normalize_code_field(value)


class VersionActionSerializer(serializers.Serializer):
    """Body for submit-review/approve/return/reject/activate/supersede/retire."""

    reason = serializers.CharField(required=False, allow_blank=True)


class CloneDefinitionSerializer(serializers.Serializer):
    source_version_public_id = serializers.UUIDField()
    target_scope_type = serializers.ChoiceField(choices=["platform_master", "tenant"])
    target_tenant_public_id = serializers.UUIDField(required=False, allow_null=True)
    new_code = serializers.CharField()
    new_title = serializers.CharField()
    clone_sections = serializers.BooleanField(default=True)
    clone_questions = serializers.BooleanField(default=True)
    clone_applicability_rules = serializers.BooleanField(default=True)
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["target_scope_type"] == "tenant" and not attrs.get("target_tenant_public_id"):
            raise serializers.ValidationError(
                "target_tenant_public_id is required when target_scope_type is 'tenant'."
            )
        return attrs
