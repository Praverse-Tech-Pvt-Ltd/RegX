"""Connector configuration and execution lifecycle.

Everything that writes a governed row goes through here. The triggers in `0002`
are the floor; this is the part that also emits audit, takes locks in a fixed
order, and refuses combinations the database cannot see -- a permission, for
instance, is not a database concept.

LOCK ORDER
----------
    1. Connector          (row lock; the serialization point)
    2. ConnectorExecution (row lock, claimed by exactly one worker)

Never the reverse. A worker that holds an execution and then wants its connector
would deadlock against a configuration change that holds the connector and looks
at its executions.

WHAT AN EXECUTION FREEZES AT CREATION
-------------------------------------
The safe configuration and its version number. Not the credential -- that is
resolved by reference at request time, and a rotation between queue and run
means the *current* value is used, which is documented in `secrets` rather than
pretended away.

Freezing the configuration is not decoration. Without it, editing a connector's
`base_url` while an execution sits in the queue would silently redirect a
transfer that somebody authorised against a different destination.
"""

from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from common.structured_logging import get_request_id

from .audit_events import IntegrationEvent, emit
from .config_schema import ConfigurationError, public_configuration, validate_configuration
from .models import (
    Connector,
    ConnectorCredentialReference,
    ConnectorExecution,
    ConnectorOperation,
    ConnectorStatus,
    ExecutionStatus,
    ExternalObjectLink,
    ResourceType,
    TestStatus,
)

#: One message for "does not exist", "belongs to another tenant" and "you may
#: not use it". Three different messages would answer, for free, the question of
#: whether a given public id exists somewhere in the deployment.
INVALID_TARGET_MESSAGE = "No such connector."


class IntegrationError(Exception):
    """Base for service-level refusals."""


class InvalidTarget(IntegrationError):
    pass


class ConnectorNotExecutable(IntegrationError):
    pass


class DuplicateExecution(IntegrationError):
    """This exact transfer was already requested.

    Carries the existing execution so the caller can point at it rather than
    starting a second one.
    """

    def __init__(self, execution):
        self.execution = execution
        super().__init__("This transfer has already been requested.")


def _assert_tenant(obj, tenant) -> None:
    if obj is None or obj.tenant_id != tenant.pk:
        raise InvalidTarget(INVALID_TARGET_MESSAGE)


def get_connector(public_id, tenant):
    connector = Connector.objects.filter(public_id=public_id).first()
    _assert_tenant(connector, tenant)
    return connector


def _locked_connector(connector, tenant):
    locked = Connector.objects.select_for_update().filter(pk=connector.pk).first()
    _assert_tenant(locked, tenant)
    return locked


# ---------------------------------------------------------------------------
# Connector configuration
# ---------------------------------------------------------------------------
@transaction.atomic
def create_connector(
    *, tenant, actor, name, connector_type, configuration, description="", credential=None
):
    """A connector starts DRAFT. It cannot execute until somebody enables it."""
    config = validate_configuration(connector_type, configuration)

    connector = Connector.objects.create(
        tenant=tenant,
        name=name,
        description=description,
        connector_type=connector_type,
        status=ConnectorStatus.DRAFT,
        configuration=config,
        configuration_version=1,
        created_by=actor,
    )
    if credential:
        set_credential_reference(connector=connector, tenant=tenant, actor=actor, **credential)

    emit(
        event_type=IntegrationEvent.CONNECTOR_CREATED,
        resource_id=connector.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "created",
            "connector_public_id": str(connector.public_id),
            "connector_type": connector_type,
            "status": connector.status,
            "configuration_version": 1,
        },
    )
    return connector


@transaction.atomic
def update_connector(*, connector, tenant, actor, name=None, description=None, configuration=None):
    """Edit a connector, bumping its configuration version if the config moved.

    An ACTIVE connector is editable through here and only here. The version
    number is what makes that safe: an execution already in the queue keeps the
    configuration it was created with, so an edit cannot retarget work somebody
    already authorised.
    """
    locked = _locked_connector(connector, tenant)
    if locked.status == ConnectorStatus.ARCHIVED:
        raise ConnectorNotExecutable("An archived connector cannot be changed.")

    fields = []
    if name is not None and name != locked.name:
        locked.name = name
        fields.append("name")
    if description is not None and description != locked.description:
        locked.description = description
        fields.append("description")

    if configuration is not None:
        config = validate_configuration(locked.connector_type, configuration)
        if config != locked.configuration:
            locked.configuration = config
            # Only a real change bumps the version. Bumping on every save would
            # make the number meaningless, and it is the thing executions are
            # compared against.
            locked.configuration_version = locked.configuration_version + 1
            fields += ["configuration", "configuration_version"]

    if fields:
        locked.save(update_fields=[*fields, "updated_at"])
        emit(
            event_type=IntegrationEvent.CONNECTOR_UPDATED,
            resource_id=locked.public_id,
            actor=actor,
            tenant_id=tenant.pk,
            payload={
                "action": "updated",
                "connector_public_id": str(locked.public_id),
                "configuration_version": locked.configuration_version,
            },
        )
    return locked


@transaction.atomic
def set_credential_reference(*, connector, tenant, actor, credential_type, reference_name=""):
    """Name the credential this connector uses. Never a value.

    The row carries no secret column, so there is nothing here that could
    accidentally persist one.
    """
    _assert_tenant(connector, tenant)
    reference, _created = ConnectorCredentialReference.objects.update_or_create(
        connector=connector,
        defaults={
            "tenant": tenant,
            "credential_type": credential_type,
            "reference_name": (reference_name or "").strip(),
        },
    )
    return reference


@transaction.atomic
def set_connector_status(*, connector, tenant, actor, status):
    """Enable, disable or archive.

    Enabling requires a configuration that still validates today. A connector
    configured months ago under different rules must not become executable just
    because somebody pressed a button.
    """
    locked = _locked_connector(connector, tenant)
    if locked.status == ConnectorStatus.ARCHIVED:
        raise ConnectorNotExecutable("An archived connector cannot be changed.")

    if status == ConnectorStatus.ACTIVE:
        try:
            validate_configuration(locked.connector_type, locked.configuration)
        except ConfigurationError as exc:
            raise ConnectorNotExecutable(str(exc)) from exc

    locked.status = status
    locked.save(update_fields=["status", "updated_at"])

    event = {
        ConnectorStatus.ACTIVE: IntegrationEvent.CONNECTOR_ENABLED,
        ConnectorStatus.DISABLED: IntegrationEvent.CONNECTOR_DISABLED,
        ConnectorStatus.ARCHIVED: IntegrationEvent.CONNECTOR_ARCHIVED,
    }.get(status, IntegrationEvent.CONNECTOR_UPDATED)
    emit(
        event_type=event,
        resource_id=locked.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": status,
            "connector_public_id": str(locked.public_id),
            "status": status,
        },
    )
    return locked


@transaction.atomic  # QA-09: the test result and its audit record commit together.
def record_test_result(*, connector, tenant, actor, test_status, latency_ms=None, error_code=""):
    """Store the outcome of a connection test. Reachability, nothing else."""
    _assert_tenant(connector, tenant)
    Connector.objects.filter(pk=connector.pk).update(
        last_tested_at=timezone.now(), last_test_status=test_status
    )
    connector.refresh_from_db(fields=["last_tested_at", "last_test_status"])
    emit(
        event_type=IntegrationEvent.CONNECTOR_TESTED,
        resource_id=connector.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "tested",
            "connector_public_id": str(connector.public_id),
            "test_status": test_status,
            "reachable": test_status == TestStatus.REACHABLE,
            "latency_ms": latency_ms,
            "error_code": error_code,
        },
    )
    return connector


# ---------------------------------------------------------------------------
# Executions
# ---------------------------------------------------------------------------
def build_idempotency_key(*, connector, operation, parts: list[str]) -> str:
    """A stable name for "this exact transfer".

    Built only from things that cannot change: the connector's public id, the
    operation, and identifiers or checksums of what is being moved. A package's
    *name* is deliberately absent -- it is display text a user may edit, and a
    key that moved when somebody renamed something would let the same transfer
    run twice.
    """
    material = "|".join([str(connector.public_id), str(operation), *[str(p) for p in parts]])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@transaction.atomic
def create_execution(
    *,
    connector,
    tenant,
    actor,
    operation,
    resource_type="",
    resource_public_id="",
    snapshot_public_id="",
    manifest_checksum="",
    idempotency_parts: list[str],
    request_summary: dict | None = None,
):
    """Queue one transfer, or point at the one that already exists.

    The connector is locked first, and its status re-read under that lock: a
    connector disabled a moment ago must not acquire a queued execution.
    """
    from .summaries import request_summary as clean_request_summary

    locked = _locked_connector(connector, tenant)
    if locked.status != ConnectorStatus.ACTIVE:
        raise ConnectorNotExecutable("This connector is not enabled.")

    key = build_idempotency_key(connector=locked, operation=operation, parts=idempotency_parts)
    existing = ConnectorExecution.objects.filter(tenant=tenant, idempotency_key=key).first()
    if existing is not None:
        # Not an error to the caller by default -- see the view. The same
        # request arriving twice is usually a double click or a client retry,
        # and the right answer is the execution that already exists.
        raise DuplicateExecution(existing)

    execution = ConnectorExecution.objects.create(
        tenant=tenant,
        connector=locked,
        operation=operation,
        status=ExecutionStatus.QUEUED,
        resource_type=resource_type,
        resource_public_id=str(resource_public_id or ""),
        snapshot_public_id=str(snapshot_public_id or ""),
        manifest_checksum=manifest_checksum or "",
        requested_by=actor,
        idempotency_key=key,
        connector_configuration_version=locked.configuration_version,
        # Frozen here. The worker uses this, not today's row.
        configuration_snapshot=public_configuration(locked.configuration),
        request_summary=clean_request_summary(request_summary),
        correlation_id=get_request_id() or "",
    )

    emit(
        event_type=IntegrationEvent.EXECUTION_CREATED,
        resource_id=execution.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "created",
            "execution_public_id": str(execution.public_id),
            "connector_public_id": str(locked.public_id),
            "operation": operation,
            "status": execution.status,
            "resource_type": resource_type,
            "resource_public_id": str(resource_public_id or ""),
            "snapshot_public_id": str(snapshot_public_id or ""),
            "manifest_checksum": manifest_checksum or "",
            "configuration_version": locked.configuration_version,
            "correlation_id": execution.correlation_id,
        },
    )
    return execution


@transaction.atomic
def claim_execution(execution_pk: int):
    """Move QUEUED -> RUNNING under a row lock, or return None.

    The lock is what makes "two workers pick up the same execution" a
    non-event: the loser sees a status that is no longer QUEUED and stops,
    before any remote call is made.
    """
    execution = (
        ConnectorExecution.objects.select_for_update()
        .filter(pk=execution_pk)
        .select_related("connector", "tenant")
        .first()
    )
    if execution is None or execution.status != ExecutionStatus.QUEUED:
        return None

    execution.status = ExecutionStatus.RUNNING
    execution.started_at = timezone.now()
    execution.attempt_count = execution.attempt_count + 1
    ConnectorExecution.objects.filter(pk=execution.pk).update(
        status=execution.status,
        started_at=execution.started_at,
        attempt_count=execution.attempt_count,
    )
    emit(
        event_type=IntegrationEvent.EXECUTION_STARTED,
        resource_id=execution.public_id,
        tenant_id=execution.tenant_id,
        payload={
            "action": "started",
            "execution_public_id": str(execution.public_id),
            "connector_public_id": str(execution.connector.public_id),
            "operation": execution.operation,
            "attempt": execution.attempt_count,
        },
    )
    return execution


@transaction.atomic
def release_execution(execution):
    """Put a RUNNING execution back in the queue for a later attempt.

    Used when the failure was transient. It is not a terminal state, so nothing
    about the execution becomes immutable, and the attempt count already
    recorded the try.
    """
    ConnectorExecution.objects.filter(pk=execution.pk, status=ExecutionStatus.RUNNING).update(
        status=ExecutionStatus.QUEUED, started_at=None
    )


@transaction.atomic
def finish_execution(
    *,
    execution,
    status,
    error_code="",
    response_summary: dict | None = None,
    external_reference="",
):
    """Write the terminal state. After this the row is history.

    Guarded against a second write: a task that timed out, was retried, and then
    had its first attempt come back to life must not overwrite the outcome that
    was already recorded. The database refuses it too -- this is the part that
    refuses it *politely*.
    """
    from .summaries import response_summary as clean_response_summary

    current = ConnectorExecution.objects.select_for_update().filter(pk=execution.pk).first()
    if current is None or current.is_terminal:
        return current

    ConnectorExecution.objects.filter(pk=current.pk).update(
        status=status,
        finished_at=timezone.now(),
        error_code=(error_code or "")[:64],
        response_summary=clean_response_summary(response_summary),
        external_reference=(external_reference or "")[:255],
    )
    current.refresh_from_db()

    event = {
        ExecutionStatus.SUCCEEDED: IntegrationEvent.EXECUTION_SUCCEEDED,
        ExecutionStatus.FAILED: IntegrationEvent.EXECUTION_FAILED,
        ExecutionStatus.CANCELLED: IntegrationEvent.EXECUTION_CANCELLED,
    }.get(status, IntegrationEvent.EXECUTION_FAILED)
    emit(
        event_type=event,
        resource_id=current.public_id,
        tenant_id=current.tenant_id,
        payload={
            "action": status,
            "execution_public_id": str(current.public_id),
            "connector_public_id": str(current.connector.public_id),
            "operation": current.operation,
            "status": status,
            "error_code": current.error_code,
            "attempt_count": current.attempt_count,
            "bytes_transferred": (response_summary or {}).get("bytes_transferred"),
            "http_status": (response_summary or {}).get("http_status"),
            "remote_checksum_verified": (response_summary or {}).get("remote_checksum_verified"),
        },
    )
    return current


@transaction.atomic
def link_external_object(
    *,
    tenant,
    connector,
    resource_type,
    resource_public_id,
    external_object_id,
    external_version_id="",
    external_url="",
):
    """Record that a RegX object and a remote object are the same thing.

    `external_url` is stored only if it passes the same destination policy a
    connector does. A URL that came from a remote system and would be rendered
    as a link is exactly the sort of thing that should not be taken on trust.
    """
    from .netpolicy import DestinationRefused, validate_url

    safe_url = ""
    if external_url:
        try:
            validate_url(external_url)
            safe_url = external_url[:2048]
        except DestinationRefused:
            # Dropped, not stored-and-flagged. A field that sometimes holds an
            # unsafe URL is a field every reader has to remember to check.
            safe_url = ""

    link, _created = ExternalObjectLink.objects.update_or_create(
        tenant=tenant,
        connector=connector,
        resource_type=resource_type,
        resource_public_id=str(resource_public_id),
        defaults={
            "external_object_id": str(external_object_id)[:255],
            "external_version_id": str(external_version_id or "")[:255],
            "external_url": safe_url,
            "last_seen_at": timezone.now(),
        },
    )
    emit(
        event_type=IntegrationEvent.OBJECT_LINKED,
        resource_id=link.public_id,
        tenant_id=tenant.pk,
        payload={
            "action": "linked",
            "connector_public_id": str(connector.public_id),
            "resource_type": resource_type,
            "resource_public_id": str(resource_public_id),
            "external_object_id": link.external_object_id,
        },
    )
    return link


def executions_for(connector, tenant):
    _assert_tenant(connector, tenant)
    return (
        ConnectorExecution.objects.for_tenant(tenant)
        .filter(connector=connector)
        .select_related("connector", "requested_by")
    )


__all__ = [
    "ConnectorNotExecutable",
    "ConnectorOperation",
    "DuplicateExecution",
    "IntegrationError",
    "InvalidTarget",
    "ResourceType",
    "build_idempotency_key",
    "claim_execution",
    "create_connector",
    "create_execution",
    "executions_for",
    "finish_execution",
    "get_connector",
    "link_external_object",
    "record_test_result",
    "release_execution",
    "set_connector_status",
    "set_credential_reference",
    "update_connector",
]
