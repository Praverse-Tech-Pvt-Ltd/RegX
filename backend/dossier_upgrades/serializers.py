"""Upgrade plan serializers.

Component names are prefixed `Upgrade*` throughout. Milestone 9 shipped a
`LinkRequestSerializer` whose generated OpenAPI component collided with the
Milestone 8 one, and drf-spectacular quietly collapsed two different request
bodies into a single component. Distinct names here are not cosmetic.
"""

from rest_framework import serializers


class UpgradeUserRefSerializer(serializers.Serializer):
    """`full_name` only -- never the email."""

    public_id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)


class UpgradeVersionRefSerializer(serializers.Serializer):
    """A blueprint version, as much of it as the caller is entitled to see.

    `name` is present only for a caller who independently holds
    `dossier_blueprints.view` -- a blueprint name is tenant-authored free text,
    and holding an upgrade permission does not entitle a caller to read the
    library. See `views._version_ref`.
    """

    public_id = serializers.UUIDField(read_only=True)
    version_number = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True, required=False)
    restricted = serializers.BooleanField(read_only=True, required=False)


class UpgradePlanItemSerializer(serializers.Serializer):
    """One proposed change.

    `before_value` / `after_value` are short scalar renderings of the single
    field the change touches -- "Required: yes -> no" -- never a JSON dump of
    the whole section. A reviewer has to be able to read the whole list.
    """

    public_id = serializers.UUIDField(read_only=True)
    change_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    section_code = serializers.CharField(read_only=True)
    field_name = serializers.CharField(read_only=True)
    before_value = serializers.CharField(read_only=True)
    after_value = serializers.CharField(read_only=True)
    blocking_reason = serializers.CharField(read_only=True)
    requires_manual_review = serializers.BooleanField(read_only=True)
    dossier_section_public_id = serializers.UUIDField(read_only=True, allow_null=True)
    target_section_public_id = serializers.UUIDField(read_only=True, allow_null=True)
    sequence = serializers.IntegerField(read_only=True)


class UpgradePlanSerializer(serializers.Serializer):
    public_id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    notes = serializers.CharField(read_only=True)
    is_stale = serializers.BooleanField(read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    actionable_items = serializers.IntegerField(read_only=True)
    conflict_items = serializers.IntegerField(read_only=True)
    accepted_items = serializers.IntegerField(read_only=True)
    rejected_items = serializers.IntegerField(read_only=True)
    blocked_items = serializers.IntegerField(read_only=True)
    created_by = UpgradeUserRefSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    reviewed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    applied_at = serializers.DateTimeField(read_only=True, allow_null=True)
    cancelled_at = serializers.DateTimeField(read_only=True, allow_null=True)


class UpgradeApplicationSerializer(serializers.Serializer):
    """One entry in a dossier's upgrade history."""

    public_id = serializers.UUIDField(read_only=True)
    plan_public_id = serializers.UUIDField(read_only=True)
    source_version_number = serializers.IntegerField(read_only=True)
    target_version_number = serializers.IntegerField(read_only=True)
    sections_added = serializers.IntegerField(read_only=True)
    sections_retired = serializers.IntegerField(read_only=True)
    sections_updated = serializers.IntegerField(read_only=True)
    applied_at = serializers.DateTimeField(read_only=True)
    applied_by = UpgradeUserRefSerializer(read_only=True)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
class UpgradePlanCreateSerializer(serializers.Serializer):
    """The dossier comes from the URL; the source version comes from the
    dossier's own provenance. Neither is ever accepted from the client, and
    the tenant never is either."""

    target_blueprint_version_public_id = serializers.UUIDField()
    notes = serializers.CharField(required=False, allow_blank=True)


class UpgradePermissionsSerializer(serializers.Serializer):
    """Advisory only -- every endpoint re-checks."""

    can_view = serializers.BooleanField(read_only=True)
    can_generate = serializers.BooleanField(read_only=True)
    can_review = serializers.BooleanField(read_only=True)
    can_apply = serializers.BooleanField(read_only=True)
    can_cancel = serializers.BooleanField(read_only=True)
