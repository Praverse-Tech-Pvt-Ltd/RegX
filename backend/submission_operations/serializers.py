"""Response shapes for the operations dashboard.

Every identifier is a `public_id`. No internal PK appears anywhere in this
module, including the tenant's -- the dashboard is the one screen that touches
seven domains at once, so it is the worst possible place to leak a database id.

Component names are prefixed `Operations*` rather than reusing `Case`, `Dossier`
or `Summary`. Milestone 9 shipped an OpenAPI collision from two apps naming a
serializer the same thing, and drf-spectacular resolves that by silently merging
the schemas.
"""

from rest_framework import serializers


class OperationsUserRefSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    full_name = serializers.CharField()


class OperationsCaseCountsSerializer(serializers.Serializer):
    open = serializers.IntegerField()
    on_hold = serializers.IntegerField()
    completed = serializers.IntegerField()
    cancelled = serializers.IntegerField()


class OperationsDossierCountsSerializer(serializers.Serializer):
    open = serializers.IntegerField()
    on_hold = serializers.IntegerField()
    completed = serializers.IntegerField()
    cancelled = serializers.IntegerField()


class OperationsSectionCountsSerializer(serializers.Serializer):
    required_total = serializers.IntegerField()
    required_complete = serializers.IntegerField()
    required_blocked = serializers.IntegerField()
    required_overdue = serializers.IntegerField()
    required_due_soon = serializers.IntegerField()
    required_not_started = serializers.IntegerField()


class OperationsBlockerCountsSerializer(serializers.Serializer):
    open = serializers.IntegerField()


class OperationsWorkflowCountsSerializer(serializers.Serializer):
    waiting_review = serializers.IntegerField()
    rejected = serializers.IntegerField()
    overdue = serializers.IntegerField()


class OperationsDocumentCountsSerializer(serializers.Serializer):
    linked = serializers.IntegerField()


class OperationsChecklistCountsSerializer(serializers.Serializer):
    incomplete = serializers.IntegerField()


class OperationsUpgradeCountsSerializer(serializers.Serializer):
    open = serializers.IntegerField()
    blocked = serializers.IntegerField()
    stale = serializers.IntegerField()


class OperationsOverviewSerializer(serializers.Serializer):
    """`allow_null` on every module block is the contract, not a convenience.

    `null` means the caller may not know. It is distinct from a block of zeroes,
    which means the caller may know and the answer is none.
    """

    cases = OperationsCaseCountsSerializer(allow_null=True)
    dossiers = OperationsDossierCountsSerializer(allow_null=True)
    sections = OperationsSectionCountsSerializer(allow_null=True)
    blockers = OperationsBlockerCountsSerializer(allow_null=True)
    workflows = OperationsWorkflowCountsSerializer(allow_null=True)
    documents = OperationsDocumentCountsSerializer(allow_null=True)
    checklists = OperationsChecklistCountsSerializer(allow_null=True)
    upgrades = OperationsUpgradeCountsSerializer(allow_null=True)
    restricted_modules = serializers.ListField(child=serializers.CharField())
    due_soon_days = serializers.IntegerField()
    generated_at = serializers.DateTimeField()
    semantics = serializers.CharField()


class OperationsAttentionRowSerializer(serializers.Serializer):
    """An enumerated reason, never a generated sentence. See `attention`."""

    reason_code = serializers.CharField()
    severity = serializers.CharField()
    resource_type = serializers.CharField()
    resource_public_id = serializers.CharField()
    resource_label = serializers.CharField()
    case_public_id = serializers.CharField(allow_null=True)
    dossier_public_id = serializers.CharField(allow_null=True)
    due_date = serializers.DateField(allow_null=True)
    operational_state = serializers.CharField()


class OperationsCaseRowSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    case_number = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    target_date = serializers.DateField(allow_null=True)
    owner = OperationsUserRefSerializer(allow_null=True)
    last_activity_at = serializers.DateTimeField()
    dossiers = serializers.DictField(allow_null=True)
    sections = serializers.DictField(allow_null=True)
    open_blockers = serializers.IntegerField(allow_null=True)
    internal_readiness = serializers.CharField(allow_null=True)
    workflow_attention = serializers.IntegerField(allow_null=True)
    upgrade_attention = serializers.IntegerField(allow_null=True)


class OperationsDossierRowSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    case_public_id = serializers.CharField(allow_null=True)
    case_number = serializers.CharField(allow_null=True)
    internal_readiness = serializers.CharField()
    required_total = serializers.IntegerField()
    required_complete = serializers.IntegerField()
    blocked_sections = serializers.IntegerField()
    overdue_sections = serializers.IntegerField()
    due_soon_sections = serializers.IntegerField()
    open_blockers = serializers.IntegerField()
    target_date = serializers.DateField(allow_null=True)
    owner = OperationsUserRefSerializer(allow_null=True)
    last_activity_at = serializers.DateTimeField()
    upgrade = serializers.DictField(allow_null=True)


class OperationsOwnerRowSerializer(serializers.Serializer):
    owner = OperationsUserRefSerializer(allow_null=True)
    unassigned = serializers.BooleanField()
    required_total = serializers.IntegerField()
    outstanding = serializers.IntegerField()
    blocked = serializers.IntegerField()
    overdue = serializers.IntegerField()


class OperationsActivityRowSerializer(serializers.Serializer):
    event_type = serializers.CharField()
    resource_type = serializers.CharField()
    resource_public_id = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    actor_email = serializers.CharField(allow_null=True)
    detail = serializers.DictField()
