"""Blueprint serializers.

Component names are prefixed `Blueprint*` throughout. Milestone 9 shipped a
`LinkRequestSerializer` whose generated OpenAPI component collided with the
Milestone 8 one, and drf-spectacular quietly collapsed two different request
bodies into a single component -- so the published schema advertised the wrong
field name for one of them. Distinct names here are not cosmetic.
"""

from rest_framework import serializers

from .models import BlueprintVersionStatus


class BlueprintUserRefSerializer(serializers.Serializer):
    """`full_name` only -- never the email."""

    public_id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
class BlueprintSerializer(serializers.Serializer):
    public_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    owner = BlueprintUserRefSerializer(read_only=True)
    created_by = BlueprintUserRefSerializer(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class BlueprintVersionSerializer(serializers.Serializer):
    public_id = serializers.UUIDField(read_only=True)
    version_number = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    notes = serializers.CharField(read_only=True)
    created_by = BlueprintUserRefSerializer(read_only=True)
    activated_at = serializers.DateTimeField(read_only=True)
    retired_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class BlueprintSectionSerializer(serializers.Serializer):
    """Flat, with `parent_public_id`. The client assembles the tree.

    Recursive serialisation of an unbounded tree per request is the N+1 shape
    this avoids, and it is the same choice the dossier section API made.
    """

    public_id = serializers.UUIDField(read_only=True)
    parent_public_id = serializers.SerializerMethodField()
    section_code = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    sequence = serializers.IntegerField(read_only=True)
    required = serializers.BooleanField(read_only=True)
    default_due_offset_days = serializers.IntegerField(read_only=True, allow_null=True)
    is_retired = serializers.BooleanField(read_only=True)

    def get_parent_public_id(self, obj):
        return str(obj.parent.public_id) if obj.parent_id else None


class BlueprintProvenanceSerializer(serializers.Serializer):
    """What a dossier can say about where it came from.

    `blueprint_name` is the snapshot taken at instantiation, not a live read, so
    a later rename cannot rewrite history. The view withholds it entirely from a
    caller without `dossier_blueprints.view` -- see `restricted`.
    """

    instantiation_public_id = serializers.UUIDField(read_only=True)
    blueprint_public_id = serializers.UUIDField(read_only=True)
    version_public_id = serializers.UUIDField(read_only=True)
    version_number = serializers.IntegerField(read_only=True)
    section_count = serializers.IntegerField(read_only=True)
    instantiated_at = serializers.DateTimeField(read_only=True)
    blueprint_name = serializers.CharField(read_only=True, required=False)
    restricted = serializers.BooleanField(read_only=True, required=False)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
class BlueprintCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_name(self, v):
        if not v.strip():
            raise serializers.ValidationError("Name cannot be blank.")
        return v.strip()


class BlueprintUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("No fields to update.")
        if "name" in attrs and not str(attrs["name"]).strip():
            raise serializers.ValidationError({"name": "This field cannot be blank."})
        return attrs


class BlueprintVersionCreateSerializer(serializers.Serializer):
    """`source_version_public_id` clones an existing version's structure.

    Omitting it starts an empty draft. There is no way to edit an ACTIVE version
    into the next revision -- that is the point of versioning.
    """

    source_version_public_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class BlueprintSectionCreateSerializer(serializers.Serializer):
    section_code = serializers.CharField(max_length=100)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    parent_public_id = serializers.UUIDField(required=False, allow_null=True)
    sequence = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    required = serializers.BooleanField(required=False, default=True)
    default_due_offset_days = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    def validate_section_code(self, v):
        if not v.strip():
            raise serializers.ValidationError("Section code cannot be blank.")
        return v.strip()

    def validate_title(self, v):
        if not v.strip():
            raise serializers.ValidationError("Title cannot be blank.")
        return v.strip()


class BlueprintSectionUpdateSerializer(serializers.Serializer):
    section_code = serializers.CharField(max_length=100, required=False)
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    parent_public_id = serializers.UUIDField(required=False, allow_null=True)
    required = serializers.BooleanField(required=False)
    default_due_offset_days = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("No fields to update.")
        return attrs


class BlueprintReorderSerializer(serializers.Serializer):
    sequence = serializers.IntegerField(min_value=0)


class BlueprintInstantiateSerializer(serializers.Serializer):
    """The blueprint version comes from the URL; the tenant never from the client."""

    regulatory_case_public_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    owner_public_id = serializers.UUIDField(required=False, allow_null=True)
    target_date = serializers.DateField(required=False, allow_null=True)

    def validate_title(self, v):
        if not v.strip():
            raise serializers.ValidationError("Title cannot be blank.")
        return v.strip()


class BlueprintInstantiateResultSerializer(serializers.Serializer):
    dossier_public_id = serializers.UUIDField(read_only=True)
    case_public_id = serializers.UUIDField(read_only=True)
    blueprint_public_id = serializers.UUIDField(read_only=True)
    version_public_id = serializers.UUIDField(read_only=True)
    version_number = serializers.IntegerField(read_only=True)
    section_count = serializers.IntegerField(read_only=True)
    dossier_route = serializers.CharField(read_only=True)


VERSION_STATUS_CHOICES = BlueprintVersionStatus.choices
