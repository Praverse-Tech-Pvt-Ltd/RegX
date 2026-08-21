"""Request validation and case serialisation.

Validation is server-side and complete: the frontend's own checks are a
convenience, never the gate.
"""

from rest_framework import serializers

from .models import CaseStatus, RegulatoryCase


class UserRefSerializer(serializers.Serializer):
    """Minimal actor reference. `full_name` only -- see projection.py."""

    public_id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)


class RegulatoryCaseSerializer(serializers.ModelSerializer):
    """Case fields. Internal PKs are never exposed."""

    owner = UserRefSerializer(read_only=True)
    created_by = UserRefSerializer(read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = RegulatoryCase
        fields = [
            "public_id",
            "case_number",
            "title",
            "product_name",
            "product_code",
            "market",
            "authority",
            "submission_type",
            "status",
            "owner",
            "target_date",
            "description",
            "created_by",
            "created_at",
            "updated_at",
            "is_terminal",
        ]
        read_only_fields = fields


class CaseCreateSerializer(serializers.Serializer):
    """Creation payload.

    `case_number` and `status` are absent on purpose: the number is assigned by
    the server under lock, and a case always starts OPEN.
    """

    title = serializers.CharField(max_length=255)
    product_name = serializers.CharField(max_length=255)
    product_code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    market = serializers.CharField(max_length=120)
    authority = serializers.CharField(max_length=120, required=False, allow_blank=True)
    submission_type = serializers.CharField(max_length=120)
    target_date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Title cannot be blank.")
        return value.strip()

    def validate_product_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Product name cannot be blank.")
        return value.strip()

    def validate_market(self, value):
        if not value.strip():
            raise serializers.ValidationError("Market cannot be blank.")
        return value.strip()

    def validate_submission_type(self, value):
        if not value.strip():
            raise serializers.ValidationError("Submission type cannot be blank.")
        return value.strip()


class CaseUpdateSerializer(serializers.Serializer):
    """PATCH payload. Every field optional; status changes go through the
    dedicated complete/cancel endpoints so each has its own permission."""

    title = serializers.CharField(max_length=255, required=False)
    product_name = serializers.CharField(max_length=255, required=False)
    product_code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    market = serializers.CharField(max_length=120, required=False)
    authority = serializers.CharField(max_length=120, required=False, allow_blank=True)
    submission_type = serializers.CharField(max_length=120, required=False)
    target_date = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("No fields to update.")
        for key in ("title", "product_name", "market", "submission_type"):
            if key in attrs and not str(attrs[key]).strip():
                raise serializers.ValidationError({key: "This field cannot be blank."})
        return attrs


class LinkRequestSerializer(serializers.Serializer):
    """Link payload. The target's kind comes from the URL, not the body, so a
    caller cannot aim a document permission at a workflow."""

    target_public_id = serializers.UUIDField()
    label = serializers.CharField(max_length=255, required=False, allow_blank=True)


class StatusChangeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class CaseFilterSerializer(serializers.Serializer):
    """List query parameters. Unknown parameters are ignored rather than
    erroring, matching the other list endpoints."""

    status = serializers.ChoiceField(choices=CaseStatus.choices, required=False)
    search = serializers.CharField(max_length=200, required=False, allow_blank=True)
