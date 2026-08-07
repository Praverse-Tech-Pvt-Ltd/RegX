"""Serializers for the IIG checklist definition-governance API.

UUID-only external identifiers; no `status` field on any plain-edit
serializer (status only changes through the dedicated lifecycle-action
endpoints, see views.py); code fields are normalized before validation.
"""

import json

from rest_framework import serializers

from .codes import CodeValidationError, normalize_code
from .execution_constants import (
    MAX_NOT_APPLICABLE_REASON_CHARS,
    MAX_RAW_VALUE_BYTES,
    MAX_RETURN_REASON_CHARS,
    MAX_REVIEWER_CONCLUSION_CHARS,
)
from .models import (
    ApplicabilityRule,
    ChecklistDefinition,
    ChecklistExecution,
    ChecklistQuestion,
    ChecklistResponse,
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
    scope_type = serializers.CharField(source="definition.scope_type", read_only=True)

    class Meta:
        model = ChecklistVersion
        fields = [
            "public_id",
            "definition_public_id",
            "scope_type",
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


# ---------------------------------------------------------------------------
# Milestone 4D-2 -- Execution and Response serializers
# ---------------------------------------------------------------------------


class _ChecklistVersionSummarySerializer(serializers.Serializer):
    public_id = serializers.UUIDField()
    version_number = serializers.IntegerField()
    status = serializers.CharField()


class ChecklistExecutionSerializer(serializers.ModelSerializer):
    checklist_version = _ChecklistVersionSummarySerializer(read_only=True)
    formulation_version_public_id = serializers.UUIDField(
        source="formulation_version.public_id",
        read_only=True,
    )
    created_by_email = serializers.EmailField(
        source="created_by.email",
        read_only=True,
        default=None,
    )
    submitted_by_email = serializers.SerializerMethodField()
    returned_by_email = serializers.SerializerMethodField()
    approved_by_email = serializers.SerializerMethodField()
    rejected_by_email = serializers.SerializerMethodField()
    cancelled_by_email = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistExecution
        fields = [
            "public_id",
            "status",
            "checklist_version",
            "formulation_version_public_id",
            "created_by_email",
            "submitted_by_email",
            "submitted_at",
            "returned_by_email",
            "returned_at",
            "return_reason",
            "approved_by_email",
            "approved_at",
            "rejected_by_email",
            "rejected_at",
            "cancelled_by_email",
            "cancelled_at",
            "reviewer_conclusion_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_submitted_by_email(self, obj):
        return getattr(obj.submitted_by, "email", None)

    def get_returned_by_email(self, obj):
        return getattr(obj.returned_by, "email", None)

    def get_approved_by_email(self, obj):
        return getattr(obj.approved_by, "email", None)

    def get_rejected_by_email(self, obj):
        return getattr(obj.rejected_by, "email", None)

    def get_cancelled_by_email(self, obj):
        return getattr(obj.cancelled_by, "email", None)


class ChecklistExecutionCreateSerializer(serializers.Serializer):
    checklist_version_public_id = serializers.UUIDField()
    formulation_version_public_id = serializers.UUIDField()

    def validate(self, attrs):
        # Reject any unknown fields via strict mass-assignment guard.
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        return attrs


class ChecklistResponseSerializer(serializers.ModelSerializer):
    question_public_id = serializers.UUIDField(source="question.public_id", read_only=True)
    entered_by_email = serializers.SerializerMethodField()
    confirmed_by_email = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistResponse
        fields = [
            "public_id",
            "question_public_id",
            "data_source_type_snapshot",
            "raw_value",
            "is_not_applicable",
            "not_applicable_reason",
            "entered_by_email",
            "entered_at",
            "confirmed_by_email",
            "confirmed_at",
            "override_reason",
            "system_derived_value",
            "version",
        ]
        read_only_fields = fields

    def get_entered_by_email(self, obj):
        return getattr(obj.entered_by, "email", None)

    def get_confirmed_by_email(self, obj):
        return getattr(obj.confirmed_by, "email", None)


class ChecklistResponseUpdateSerializer(serializers.Serializer):
    #: M4D3-VER-002 -- required, not additive. M4D3-VER-001 records this as a
    #: controlled breaking API contract change: the ordinary response PATCH did
    #: not previously accept it, and optimistic concurrency is mandatory rather
    #: than opt-in, so there is no value that skips the check.
    expected_version = serializers.IntegerField(min_value=1, required=False)
    raw_value = serializers.JSONField(allow_null=True, required=False)
    is_not_applicable = serializers.BooleanField(required=False)
    not_applicable_reason = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        max_length=MAX_NOT_APPLICABLE_REASON_CHARS,
        required=False,
    )
    override_reason = serializers.CharField(allow_blank=True, required=False, default="")

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        # Reject client-supplied version.
        if "version" in self.initial_data:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": "version is not client-writable."}
            )

        # M4D3-VER-004 -- an omitted expected_version is rejected with its own
        # governed code and no write. Declared ``required=False`` only so this
        # contract is reported instead of DRF's generic "This field is
        # required."; it is mandatory in every other sense. Silent overwrite of
        # a concurrently changed response is prohibited.
        if "expected_version" not in attrs:
            raise serializers.ValidationError(
                {
                    "error_code": "expected_version_required",
                    "detail": "expected_version is required on a governed response update.",
                }
            )

        question = self.context.get("question")
        raw_value = attrs.get("raw_value")
        is_not_applicable = attrs.get("is_not_applicable")

        if question is not None and "raw_value" in attrs:
            from .response_validation import InvalidRawValueShape, validate_raw_value_shape

            try:
                validate_raw_value_shape(
                    question.answer_type,
                    raw_value,
                    question=question,
                    execution=self.context.get("execution"),
                    tenant=self.context.get("tenant"),
                )
            except InvalidRawValueShape as exc:
                raise serializers.ValidationError(
                    {"error_code": "invalid_raw_value_shape", "detail": str(exc)}
                ) from exc

        if (
            question is not None
            and is_not_applicable
            and question.answer_type
            in {"calculated_value", "calculated_status", "approval_metadata"}
        ):
            raise serializers.ValidationError(
                {
                    "error_code": "invalid_raw_value_shape",
                    "detail": f"{question.answer_type} does not support is_not_applicable.",
                }
            )
        return attrs

    def validate_raw_value(self, value):
        if value is None:
            return value
        size = len(json.dumps(value).encode("utf-8"))
        if size > MAX_RAW_VALUE_BYTES:
            raise serializers.ValidationError(
                {"error_code": "payload_too_large", "detail": "raw_value exceeds byte limit."}
            )
        return value


class ReviewerConclusionSerializer(serializers.Serializer):
    raw_value = serializers.JSONField()
    expected_version = serializers.IntegerField(min_value=1)
    correction_reason = serializers.CharField(
        allow_blank=True,
        required=False,
        default="",
        max_length=MAX_REVIEWER_CONCLUSION_CHARS,
    )

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        raw_value = attrs.get("raw_value")
        if not isinstance(raw_value, dict):
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_invalid_payload",
                    "detail": "raw_value must be an object.",
                }
            )
        if set(raw_value.keys()) != {"value"}:
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_invalid_payload",
                    "detail": "raw_value must contain only a 'value' key.",
                }
            )
        value_str = raw_value.get("value")
        if not isinstance(value_str, str):
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_invalid_payload",
                    "detail": "raw_value.value must be a string.",
                }
            )
        if not value_str.strip():
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_empty",
                    "detail": "Reviewer conclusion must not be empty.",
                }
            )
        if len(value_str) > MAX_REVIEWER_CONCLUSION_CHARS:
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_too_long",
                    "detail": (
                        f"Reviewer conclusion exceeds {MAX_REVIEWER_CONCLUSION_CHARS} characters."
                    ),
                }
            )
        payload_size = len(json.dumps(raw_value).encode("utf-8"))
        if payload_size > MAX_RAW_VALUE_BYTES:
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_payload_too_large",
                    "detail": "Payload exceeds byte limit.",
                }
            )
        return attrs


class ReturnSerializer(serializers.Serializer):
    return_reason = serializers.CharField(max_length=MAX_RETURN_REASON_CHARS)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        if not attrs.get("return_reason", "").strip():
            raise serializers.ValidationError(
                {"error_code": "missing_return_reason", "detail": "return_reason is required."}
            )
        return attrs


class ApproveSerializer(serializers.Serializer):
    reviewer_conclusion_note = serializers.CharField(max_length=MAX_REVIEWER_CONCLUSION_CHARS)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        if not attrs.get("reviewer_conclusion_note", "").strip():
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_required",
                    "detail": "reviewer_conclusion_note is required.",
                }
            )
        return attrs


class EmptyActionSerializer(serializers.Serializer):
    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        return attrs
