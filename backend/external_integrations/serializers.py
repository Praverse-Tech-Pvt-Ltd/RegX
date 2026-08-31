"""API shapes for external integrations.

**There is no field anywhere in this module that carries a secret value.** The
credential block returns a type and the *name* of the environment variable an
operator must set, which is what somebody configuring a connector needs to know.
The value is never read here, never rendered, and has no column to be read from.

Public ids only, never database ids -- same rule as every app before this one.
"""

from rest_framework import serializers

from documents.models import DocumentType

from .models import ConnectorOperation, ConnectorType, CredentialType


class CredentialReferenceSerializer(serializers.Serializer):
    """A credential's *name*. Never its value."""

    public_id = serializers.CharField(read_only=True)
    credential_type = serializers.ChoiceField(choices=CredentialType.choices)
    #: The environment variable an operator must set. A variable's name is not
    #: a secret; showing it is the only way somebody can configure the
    #: deployment correctly.
    environment_variable = serializers.CharField(read_only=True)
    #: Whether that variable is currently set. A boolean, resolved by presence
    #: only -- the value is never read, compared or echoed.
    is_resolvable = serializers.BooleanField(read_only=True)


class ConnectorSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    connector_type = serializers.CharField()
    status = serializers.CharField()
    configuration = serializers.DictField()
    configuration_version = serializers.IntegerField()
    last_tested_at = serializers.DateTimeField(allow_null=True)
    last_test_status = serializers.CharField()
    created_at = serializers.DateTimeField()
    credential = CredentialReferenceSerializer(allow_null=True)
    #: Advisory, for hiding controls the caller cannot use. Every endpoint
    #: re-checks its own permission regardless.
    permissions = serializers.DictField(required=False)


class CredentialInputSerializer(serializers.Serializer):
    credential_type = serializers.ChoiceField(choices=CredentialType.choices)
    #: Optional. Blank means "derive the variable name from the connector".
    reference_name = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default=""
    )

    def validate_reference_name(self, value):
        value = (value or "").strip()
        if value and not value.replace("_", "").isalnum():
            raise serializers.ValidationError(
                "An environment variable name may contain only letters, digits and underscores."
            )
        return value


class ConnectorCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    connector_type = serializers.ChoiceField(choices=ConnectorType.choices)
    #: Validated by `config_schema`, not here. A DRF serializer cannot express
    #: "this JSON is safe to point a server at", and two validators would drift.
    configuration = serializers.DictField()
    credential = CredentialInputSerializer(required=False)


class ConnectorUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    configuration = serializers.DictField(required=False)


class ConnectionTestSerializer(serializers.Serializer):
    """Technical reachability. Never a remote body, header or internal detail."""

    reachable = serializers.BooleanField()
    authenticated = serializers.BooleanField()
    status = serializers.CharField()
    latency_ms = serializers.IntegerField(allow_null=True)
    error_code = serializers.CharField(allow_blank=True)


class ExecutionSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    connector_public_id = serializers.CharField()
    operation = serializers.CharField()
    status = serializers.CharField()
    resource_type = serializers.CharField(allow_blank=True)
    resource_public_id = serializers.CharField(allow_blank=True)
    snapshot_public_id = serializers.CharField(allow_blank=True)
    manifest_checksum = serializers.CharField(allow_blank=True)
    requested_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    attempt_count = serializers.IntegerField()
    connector_configuration_version = serializers.IntegerField()
    error_code = serializers.CharField(allow_blank=True)
    external_reference = serializers.CharField(allow_blank=True)
    correlation_id = serializers.CharField(allow_blank=True)
    #: Allow-listed summaries only -- see `summaries`. Never a remote response.
    request_summary = serializers.DictField()
    response_summary = serializers.DictField()


class ImportDocumentPayloadSerializer(serializers.Serializer):
    """`IMPORT_DOCUMENT`. Names a remote object; cannot name a destination."""

    external_object_id = serializers.CharField(max_length=255)
    relative_path = serializers.CharField(max_length=1024)
    title = serializers.CharField(max_length=255)
    #: The SAME field the upload endpoint uses: the enum's choices, and
    #: **required**, because the upload endpoint requires it too.
    #:
    #: This was a free `CharField` defaulting to `"other"` -- which is not a
    #: `DocumentType` at all. Django does not enforce `choices` on
    #: `objects.create()`, so every import was quietly storing a type the
    #: enum does not contain and nothing downstream noticed. There is no
    #: honest default here: a remote object's type is something the caller
    #: knows and this app does not get to guess.
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    declared_mime = serializers.CharField(max_length=128, required=False, allow_blank=True)


class PushPackagePayloadSerializer(serializers.Serializer):
    """`PUSH_FROZEN_PACKAGE`. Names an exact package; cannot name a destination."""

    package_public_id = serializers.UUIDField()
    relative_path = serializers.CharField(max_length=1024, required=False, allow_blank=True)


class ExecutionCreateSerializer(serializers.Serializer):
    """An explicit operation and its own payload schema.

    Deliberately not `{"operation": <anything>, "payload": {<anything>}}`: the
    payload is validated by the schema belonging to the named operation, so
    there is no shape a caller can send that reaches the transport unexamined.
    """

    operation = serializers.ChoiceField(choices=ConnectorOperation.choices)
    payload = serializers.DictField()

    PAYLOAD_SERIALIZERS = {
        ConnectorOperation.IMPORT_DOCUMENT: ImportDocumentPayloadSerializer,
        ConnectorOperation.PUSH_FROZEN_PACKAGE: PushPackagePayloadSerializer,
    }

    def validate(self, attrs):
        serializer_class = self.PAYLOAD_SERIALIZERS.get(attrs["operation"])
        if serializer_class is None:  # pragma: no cover - ChoiceField covers this
            raise serializers.ValidationError({"operation": "Unsupported operation."})
        payload = serializer_class(data=attrs.get("payload") or {})
        payload.is_valid(raise_exception=True)
        attrs["payload"] = payload.validated_data
        return attrs


class ExternalObjectLinkSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    connector_public_id = serializers.CharField()
    resource_type = serializers.CharField()
    resource_public_id = serializers.CharField()
    external_object_id = serializers.CharField()
    external_version_id = serializers.CharField(allow_blank=True)
    #: Present only when it passed the connector destination policy; otherwise
    #: blank, and the UI shows the identifier as plain text.
    external_url = serializers.CharField(allow_blank=True)
    last_seen_at = serializers.DateTimeField(allow_null=True)
