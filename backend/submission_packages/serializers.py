"""Response shapes for submission packages.

Every identifier is a `public_id`; no internal PK appears anywhere, including in
the manifest.

Component names are prefixed `Package*` rather than reusing `Entry`, `Manifest`
or `Snapshot`. Milestone 9 shipped an OpenAPI collision from two apps naming a
serializer the same thing, and drf-spectacular resolves that by silently merging
the schemas.

**The document block is nullable on purpose.** A caller may hold
`submission_packages.view` and not `documents.view`; the entry still exists,
because the package is theirs to see, but everything about the document comes
back `null`. That is the Milestone 12 rule: `null` means *you are not entitled
to know*, and it is not the same as absent.
"""

from rest_framework import serializers


class PackageUserRefSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    full_name = serializers.CharField()


class PackageDocumentRefSerializer(serializers.Serializer):
    """Present only for a caller who independently holds `documents.view`."""

    document_public_id = serializers.CharField()
    document_version_public_id = serializers.CharField()
    version_number = serializers.IntegerField()
    title = serializers.CharField()
    checksum_sha256 = serializers.CharField()
    size_bytes = serializers.IntegerField()
    mime_type = serializers.CharField()
    scan_status = serializers.CharField()


class PackageEntrySerializer(serializers.Serializer):
    public_id = serializers.CharField()
    sequence = serializers.IntegerField()
    logical_path = serializers.CharField(allow_blank=True)
    export_filename = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_blank=True)
    dossier_section_public_id = serializers.CharField(allow_null=True)
    is_active = serializers.BooleanField()
    added_at = serializers.DateTimeField()
    #: `null` when the caller lacks `documents.view`. See the module docstring.
    document = PackageDocumentRefSerializer(allow_null=True)


class PackageSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    revision_number = serializers.IntegerField()
    case_public_id = serializers.CharField(allow_null=True)
    source_package_public_id = serializers.CharField(allow_null=True)
    entry_count = serializers.IntegerField()
    manifest_checksum = serializers.CharField(allow_blank=True)
    created_by = PackageUserRefSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    frozen_by = PackageUserRefSerializer(allow_null=True)
    frozen_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    #: Advisory, for hiding controls the caller cannot use. Every endpoint
    #: re-checks its own permission regardless.
    permissions = serializers.DictField(required=False)


class PackageDetailSerializer(PackageSerializer):
    entries = PackageEntrySerializer(many=True)


class PackageCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class PackageUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)


class PackageEntryCreateSerializer(serializers.Serializer):
    """The caller names an exact version. There is no "latest" option.

    A convenience that resolved "latest cleared" server-side would persist a
    version the user never saw, which is precisely the ambiguity this milestone
    exists to remove.
    """

    document_version_public_id = serializers.UUIDField()
    logical_path = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=400
    )
    display_name = serializers.CharField(required=False, allow_blank=True, default="")
    dossier_section_public_id = serializers.UUIDField(required=False, allow_null=True)


class PackageEntryReorderSerializer(serializers.Serializer):
    sequence = serializers.IntegerField(min_value=0)


class PackageIntegrityIssueSerializer(serializers.Serializer):
    code = serializers.CharField()
    entry_public_id = serializers.CharField(allow_null=True)
    detail = serializers.CharField(allow_null=True)


class PackageIntegritySerializer(serializers.Serializer):
    """Internal package integrity. Never a regulatory conclusion."""

    valid = serializers.BooleanField()
    issues = PackageIntegrityIssueSerializer(many=True)
    semantics = serializers.CharField()


class PackageManifestSerializer(serializers.Serializer):
    manifest_schema_version = serializers.IntegerField()
    manifest_checksum = serializers.CharField()
    entry_count = serializers.IntegerField()
    total_bytes = serializers.IntegerField()
    frozen_at = serializers.DateTimeField()
    manifest = serializers.DictField()


class PackageCloneSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
