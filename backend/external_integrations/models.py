"""Connectors, credential references, executions and external object links.

**A CONNECTOR IS A TECHNICAL DESTINATION AND NOTHING MORE.** `ACTIVE` means the
tenant has enabled it; it is not approval, not validation, not qualification of
the remote system, and there is deliberately no `APPROVED` state for it to be
confused with -- the same reasoning `regulatory_cases.CaseStatus` and
`submission_packages.PackageStatus` give.

**NO TRANSFER IS A SUBMISSION.** A `ConnectorExecution` records a technical
transfer attempt against an endpoint a tenant configured. It is not an agency
submission, not a filing, not a gateway transmission, and `SUCCEEDED` means the
remote endpoint accepted the bytes -- nothing about what it did with them.

**NOTHING HERE DUPLICATES CONTENT.** An execution names a document version or a
frozen package by public id; it never copies one. `ExternalObjectLink` records
that a RegX object and a remote object are the same thing, and stores no remote
payload.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .governance import IntegrationMutationForbidden

CONNECTOR_MUTATION_MESSAGE = (
    "Connectors are governed; use external_integrations.services rather than writing rows directly."
)
EXECUTION_MUTATION_MESSAGE = (
    "Connector executions are governed; use external_integrations.services "
    "rather than writing rows directly."
)


class ConnectorType(models.TextChoices):
    """Only what is actually implemented.

    `GENERIC_HTTPS` is the whole of this milestone. SFTP and the vendor names
    are absent rather than stubbed: an enum member with no working transport is
    a promise the code does not keep, and a tenant selecting `SHAREPOINT` would
    reasonably expect SharePoint.
    """

    GENERIC_HTTPS = "generic_https", "Generic HTTPS endpoint"


class ConnectorStatus(models.TextChoices):
    """Technical enablement, not approval.

    DRAFT     being configured; cannot execute.
    ACTIVE    enabled; may execute. Says nothing about the remote system.
    DISABLED  turned off. Terminal for new work, reversible by re-enabling.
    ARCHIVED  retired. Kept because executions reference it, and execution
              history is evidence of what was transferred.
    """

    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"
    ARCHIVED = "archived", "Archived"


class CredentialType(models.TextChoices):
    BEARER_TOKEN = "bearer_token", "Bearer token"
    API_KEY = "api_key", "API key header"
    BASIC_AUTH = "basic_auth", "Basic authentication"


class ConnectorOperation(models.TextChoices):
    """The complete set. There is no generic "call this endpoint" operation.

    Each member has its own validated payload schema and its own permission
    requirements. A free-form operation would make the connector an arbitrary
    HTTP client driven by tenant input, which is the thing this app exists to
    not be.
    """

    IMPORT_DOCUMENT = "import_document", "Import document"
    PUSH_FROZEN_PACKAGE = "push_frozen_package", "Transfer frozen package"


class ExecutionStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


#: Once an execution reaches one of these it is history, and history does not
#: change. Enforced by the service, by the manager below, and by a trigger.
TERMINAL_EXECUTION_STATUSES = frozenset(
    {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)


class TestStatus(models.TextChoices):
    """The outcome of a connection test. Technical reachability only."""

    NEVER_TESTED = "never_tested", "Never tested"
    REACHABLE = "reachable", "Reachable"
    UNREACHABLE = "unreachable", "Unreachable"
    UNAUTHORISED = "unauthorised", "Authentication failed"


class ResourceType(models.TextChoices):
    DOCUMENT_VERSION = "document_version", "Document version"
    SUBMISSION_PACKAGE = "submission_package", "Submission package"


class _TenantScopedManager(models.Manager):
    def for_tenant(self, tenant):
        return self.get_queryset().filter(tenant=tenant)


class GovernedManager(_TenantScopedManager):
    """Refuses bulk writes through the public manager.

    Not the guarantee -- `Model.save()` resolves through `_base_manager`, so
    this cannot cover `objects.create()` or a bare `save()`, and a raw cursor
    never runs a line of Python at all. `0002` is the floor. This exists to make
    the wrong call fail immediately and loudly in review, rather than in
    production.
    """

    def update(self, *args, **kwargs):
        raise IntegrationMutationForbidden(EXECUTION_MUTATION_MESSAGE)

    def delete(self, *args, **kwargs):
        raise IntegrationMutationForbidden(EXECUTION_MUTATION_MESSAGE)


class Connector(PublicIDModel, TimeStampedModel):
    """A configured external destination, owned by exactly one tenant."""

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="external_connectors"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    connector_type = models.CharField(
        max_length=32, choices=ConnectorType.choices, default=ConnectorType.GENERIC_HTTPS
    )
    status = models.CharField(
        max_length=16, choices=ConnectorStatus.choices, default=ConnectorStatus.DRAFT
    )

    #: Validated against `config_schema` on every write **and** again before
    #: every use. See that module for why the second check is not redundant.
    configuration = models.JSONField(default=dict)

    #: Bumped on every configuration change. An execution records the version it
    #: was created under, so a retry can prove whether the destination moved
    #: underneath it instead of silently following the edit.
    configuration_version = models.PositiveIntegerField(default=1)

    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_status = models.CharField(
        max_length=16, choices=TestStatus.choices, default=TestStatus.NEVER_TESTED
    )

    created_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="created_connectors"
    )

    objects = _TenantScopedManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "connector_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"], name="unique_connector_name_per_tenant"
            ),
            models.CheckConstraint(
                condition=models.Q(configuration_version__gte=1),
                name="connector_configuration_version_is_positive",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.status})"

    @property
    def is_executable(self) -> bool:
        return self.status == ConnectorStatus.ACTIVE


class ConnectorCredentialReference(PublicIDModel, TimeStampedModel):
    """The *name* of a credential. Never a credential.

    There is no value column, and that is a structural guarantee rather than a
    convention: a column that does not exist cannot be written to by a raw
    cursor, cannot be serialised by a mistake in a serialiser, and cannot leak
    into a database backup.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="connector_credentials"
    )
    #: One credential per connector. A connector that needed two would need a
    #: reason, and "it might one day" is not one.
    connector = models.OneToOneField(
        Connector, on_delete=models.CASCADE, related_name="credential_reference"
    )
    #: The environment variable to read. Blank means "derive it" -- see
    #: `secrets.environment_variable_name`. A *name* is not a secret; an
    #: operator has to be told exactly what to export.
    reference_name = models.CharField(max_length=255, blank=True)
    credential_type = models.CharField(max_length=32, choices=CredentialType.choices)
    #: Non-secret notes only: which account, which team owns it. Never a value.
    notes = models.TextField(blank=True)

    objects = _TenantScopedManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.credential_type} for {self.connector_id}"


class ConnectorExecution(PublicIDModel, TimeStampedModel):
    """One transfer attempt. Permanent once it reaches a terminal state.

    An execution says what was attempted, against which connector, under which
    configuration version, and how it ended. It is the record a person reads
    when asked "did that document actually go out, and which bytes were they" --
    so it names the exact `DocumentVersion` or the exact frozen package snapshot,
    never "the latest".
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="connector_executions"
    )
    #: PROTECT, not CASCADE: deleting a connector must not delete the evidence
    #: of what it transferred. Connectors are archived, never deleted.
    connector = models.ForeignKey(Connector, on_delete=models.PROTECT, related_name="executions")

    operation = models.CharField(max_length=32, choices=ConnectorOperation.choices)
    status = models.CharField(
        max_length=16, choices=ExecutionStatus.choices, default=ExecutionStatus.QUEUED
    )

    #: What this execution is about. Held as a public id rather than a foreign
    #: key so that history survives even if the resource app changes shape --
    #: and so this app does not acquire a write relationship to `documents` or
    #: `submission_packages`.
    resource_type = models.CharField(max_length=32, choices=ResourceType.choices, blank=True)
    resource_public_id = models.CharField(max_length=64, blank=True)

    #: For a package transfer, exactly which frozen manifest went. Recorded at
    #: creation and never recomputed: "the package's current snapshot" would
    #: make the record a function of today's database.
    snapshot_public_id = models.CharField(max_length=64, blank=True)
    manifest_checksum = models.CharField(max_length=64, blank=True)

    requested_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="requested_executions"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)

    #: Derived from what is being transferred, never from anything mutable.
    #: Unique per tenant, so a repeated request is recognised rather than
    #: performed twice.
    idempotency_key = models.CharField(max_length=128)

    connector_configuration_version = models.PositiveIntegerField()
    #: The safe configuration as it stood when the execution was created. A
    #: retry uses this, not today's row, so an edit between queue and run cannot
    #: silently redirect a transfer. Contains no credential: the secret is
    #: resolved at request time by reference.
    configuration_snapshot = models.JSONField(default=dict)

    #: Allow-listed summaries. Never a raw remote response -- see `summaries`.
    request_summary = models.JSONField(default=dict)
    response_summary = models.JSONField(default=dict)

    error_code = models.CharField(max_length=64, blank=True)
    external_reference = models.CharField(max_length=255, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)

    objects = GovernedManager()

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["connector", "-requested_at"]),
            models.Index(fields=["tenant", "operation"]),
        ]
        constraints = [
            #: The floor under "the same transfer is not performed twice".
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="unique_execution_idempotency_key"
            ),
        ]

    def __str__(self):
        return f"{self.operation} {self.status}"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_EXECUTION_STATUSES


class ExternalObjectLink(PublicIDModel, TimeStampedModel):
    """ "This RegX object and that remote object are the same thing."

    Identity only. No remote payload, no cached content, no mirrored metadata --
    a copy of a remote record is a second source of truth that nothing keeps
    correct.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="external_object_links"
    )
    connector = models.ForeignKey(
        Connector, on_delete=models.PROTECT, related_name="external_object_links"
    )
    resource_type = models.CharField(max_length=32, choices=ResourceType.choices)
    resource_public_id = models.CharField(max_length=64)

    #: Remote identifiers are remote input. Bounded, and rendered as text unless
    #: `external_url` passes the same destination policy the connector does.
    external_object_id = models.CharField(max_length=255)
    external_version_id = models.CharField(max_length=255, blank=True)
    external_url = models.URLField(max_length=2048, blank=True)

    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects = _TenantScopedManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "resource_type", "resource_public_id"]),
            models.Index(fields=["connector", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "connector", "resource_type", "resource_public_id"],
                name="unique_external_link_per_resource",
            ),
        ]

    def __str__(self):
        return f"{self.resource_type}:{self.resource_public_id} -> {self.external_object_id}"
