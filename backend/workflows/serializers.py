"""Workflow serializers. public_id only -- internal PKs are never exposed."""

from rest_framework import serializers

from .models import WorkflowItem, WorkflowTransition


class UserRefSerializer(serializers.Serializer):
    """Minimal user reference. Enough to render an assignee, nothing more."""

    public_id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)


class WorkflowTransitionSerializer(serializers.ModelSerializer):
    actor = UserRefSerializer(read_only=True)

    class Meta:
        model = WorkflowTransition
        fields = [
            "public_id",
            "action",
            "from_state",
            "to_state",
            "actor",
            "reason",
            "created_at",
        ]
        read_only_fields = fields


class WorkflowItemSerializer(serializers.ModelSerializer):
    created_by = UserRefSerializer(read_only=True)
    assigned_to = UserRefSerializer(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)
    # Populated by the view: structurally-legal actions intersected with the
    # caller's permissions. Advisory for rendering; every endpoint re-checks.
    available_actions = serializers.ListField(
        child=serializers.CharField(), read_only=True, required=False
    )

    class Meta:
        model = WorkflowItem
        fields = [
            "public_id",
            "title",
            "description",
            "state",
            "created_by",
            "assigned_to",
            "assigned_at",
            "due_at",
            "is_overdue",
            "is_terminal",
            "available_actions",
            "created_at",
            "updated_at",
        ]
        # `state` is read-only by design. It changes only through the action
        # endpoints, so a PATCH carrying `state` cannot move the item -- see
        # docs/WORKFLOW_ENGINE.md "API".
        read_only_fields = [
            "public_id",
            "state",
            "created_by",
            "assigned_to",
            "assigned_at",
            "is_overdue",
            "is_terminal",
            "available_actions",
            "created_at",
            "updated_at",
        ]


class WorkflowItemWriteSerializer(serializers.Serializer):
    """Create/edit payload. Deliberately narrow: only these three fields are
    ever writable, so no future model field becomes writable by accident."""

    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    due_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class WorkflowItemPatchSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)


class TransitionRequestSerializer(serializers.Serializer):
    """Reason is optional here and enforced per-action by the service layer,
    which is the only place that knows which actions require one."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")


class AssignRequestSerializer(serializers.Serializer):
    """`assigned_to` null clears the assignment."""

    assigned_to = serializers.UUIDField(required=False, allow_null=True, default=None)


class WorkflowEvidenceSerializer(serializers.Serializer):
    """Evidence link. public_id only, and document detail is conditional.

    `document` is populated only when the caller holds `documents.view` in this
    tenant. Workflow permission and document permission are separate gates:
    seeing a workflow must not confer document access. PLATFORM_SUPPORT is the
    live case -- it holds `workflows.view` and no document permission at all.
    """

    public_id = serializers.UUIDField(read_only=True)
    label = serializers.CharField(read_only=True)
    linked_by = UserRefSerializer(read_only=True)
    linked_at = serializers.DateTimeField(read_only=True)
    # Always present: identity of the cited version. These are opaque UUIDs and
    # disclose nothing on their own.
    document_version_public_id = serializers.UUIDField(read_only=True)
    document_public_id = serializers.UUIDField(read_only=True)
    # Present only with documents.view.
    document = serializers.DictField(read_only=True, required=False)


class EvidenceLinkRequestSerializer(serializers.Serializer):
    document_version_public_id = serializers.UUIDField()
    label = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
