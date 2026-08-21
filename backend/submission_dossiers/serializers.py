"""Request validation and serialisation. Validation is server-side and complete."""

from rest_framework import serializers

from .models import (
    BlockerSeverity,
    DossierSection,
    DossierSectionBlocker,
    SectionStatus,
    SubmissionDossier,
)


class DossierUserRefSerializer(serializers.Serializer):
    """`full_name` only -- never the email. See projection.py."""

    public_id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)


class DossierSerializer(serializers.ModelSerializer):
    owner = DossierUserRefSerializer(read_only=True)
    created_by = DossierUserRefSerializer(read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)
    regulatory_case_public_id = serializers.UUIDField(
        source="regulatory_case.public_id", read_only=True
    )

    class Meta:
        model = SubmissionDossier
        fields = [
            "public_id",
            "regulatory_case_public_id",
            "title",
            "description",
            "status",
            "owner",
            "target_date",
            "created_by",
            "created_at",
            "updated_at",
            "is_terminal",
        ]
        read_only_fields = fields


class SectionSerializer(serializers.ModelSerializer):
    """Flat row. The tree is assembled by the client from `parent_public_id` --
    recursive serialisation of an unbounded tree on every request is exactly
    the N+1 shape this avoids."""

    owner = DossierUserRefSerializer(read_only=True)
    parent_public_id = serializers.SerializerMethodField()
    is_retired = serializers.BooleanField(read_only=True)

    class Meta:
        model = DossierSection
        fields = [
            "public_id",
            "parent_public_id",
            "section_code",
            "title",
            "description",
            "notes",
            "sequence",
            "required",
            "status",
            "readiness",
            "readiness_reason",
            "owner",
            "due_date",
            "is_retired",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_parent_public_id(self, obj):
        return str(obj.parent.public_id) if obj.parent_id else None


class BlockerSerializer(serializers.ModelSerializer):
    created_by = DossierUserRefSerializer(read_only=True)
    resolved_by = DossierUserRefSerializer(read_only=True)
    section_public_id = serializers.UUIDField(source="section.public_id", read_only=True)

    class Meta:
        model = DossierSectionBlocker
        fields = [
            "public_id",
            "section_public_id",
            "title",
            "description",
            "severity",
            "status",
            "created_by",
            "created_at",
            "resolved_by",
            "resolved_at",
        ]
        read_only_fields = fields


class DossierCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    target_date = serializers.DateField(required=False, allow_null=True)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_title(self, v):
        if not v.strip():
            raise serializers.ValidationError("Title cannot be blank.")
        return v.strip()


class DossierUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    target_date = serializers.DateField(required=False, allow_null=True)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("No fields to update.")
        if "title" in attrs and not str(attrs["title"]).strip():
            raise serializers.ValidationError({"title": "This field cannot be blank."})
        return attrs


class SectionCreateSerializer(serializers.Serializer):
    section_code = serializers.CharField(max_length=100)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    parent_public_id = serializers.UUIDField(required=False, allow_null=True)
    sequence = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    required = serializers.BooleanField(required=False, default=True)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)

    def validate_section_code(self, v):
        if not v.strip():
            raise serializers.ValidationError("Section code cannot be blank.")
        return v.strip()

    def validate_title(self, v):
        if not v.strip():
            raise serializers.ValidationError("Title cannot be blank.")
        return v.strip()


class SectionUpdateSerializer(serializers.Serializer):
    section_code = serializers.CharField(max_length=100, required=False)
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    parent_public_id = serializers.UUIDField(required=False, allow_null=True)
    required = serializers.BooleanField(required=False)
    #: `readiness` is deliberately absent: it is derived, never claimed.
    status = serializers.ChoiceField(choices=SectionStatus.choices, required=False)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("No fields to update.")
        return attrs


class ReorderSerializer(serializers.Serializer):
    sequence = serializers.IntegerField(min_value=0)


class BlockerCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    severity = serializers.ChoiceField(
        choices=BlockerSeverity.choices, required=False, default=BlockerSeverity.MEDIUM
    )

    def validate_title(self, v):
        if not v.strip():
            raise serializers.ValidationError("Title cannot be blank.")
        return v.strip()


class SectionLinkRequestSerializer(serializers.Serializer):
    """The kind comes from the URL, not the body, so a document permission
    cannot be aimed at a workflow."""

    target_public_id = serializers.UUIDField()
    purpose = serializers.CharField(max_length=255, required=False, allow_blank=True)


class DossierStatusChangeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)
