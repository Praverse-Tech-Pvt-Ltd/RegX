"""Celery tasks for connector executions.

Rules, following `documents.tasks`:

* Idempotent. An execution is claimed under a row lock, so a task that runs
  twice does the work at most once, and a second worker that arrives while the
  first is running makes no remote call at all.
* Bounded retries, and only for failures that are actually transient. A 403 is
  not retried; a timeout is.
* Tenant passed explicitly, never inferred from thread-local state -- a worker
  has no request and therefore no tenant context.
* Correlation id carried from the request that created the execution, so the log
  line for a transfer that happens minutes later still joins up with the click
  that asked for it.
* Nothing sensitive logged. The structured fields below are the whole of what
  this module ever writes: ids, an operation name, a status, an attempt number
  and an enumerated code.

THE CONNECTOR IS RE-CHECKED AT START
------------------------------------
Between queueing and running, a connector can be disabled. The task re-reads it
under the execution's lock and, if it is no longer ACTIVE, ends the execution
without a remote call. Enabling is a deliberate act; so is disabling, and a
transfer that leaves after somebody turned the connector off would make the
switch a lie.
"""

from __future__ import annotations

import logging

from celery import shared_task

from . import services
from .config_schema import ConfigurationError, validate_configuration
from .models import ConnectorStatus, ExecutionStatus
from .operations import OperationError, run

logger = logging.getLogger("regx.external_integrations")

#: Total attempts, including the first. Bounded so a permanently broken
#: endpoint costs a known amount of work rather than an unbounded amount.
MAX_ATTEMPTS = 3

#: Backoff in seconds per attempt. Jitter is added by Celery's `retry_jitter`.
RETRY_BACKOFF_SECONDS = 30


class ExecutionErrorCode:
    CONNECTOR_DISABLED = "CONNECTOR_DISABLED"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def _log(execution, event, **extra):
    logger.info(
        event,
        extra={
            "correlation_id": execution.correlation_id,
            "execution_public_id": str(execution.public_id),
            "connector_public_id": str(execution.connector.public_id),
            "operation": execution.operation,
            "status": execution.status,
            "attempt": execution.attempt_count,
            **extra,
        },
    )


@shared_task(bind=True, max_retries=MAX_ATTEMPTS, default_retry_delay=RETRY_BACKOFF_SECONDS)
def run_connector_execution(self, execution_pk: int, tenant_id: int) -> None:
    """Perform one queued execution."""
    from tenancy.models import Tenant

    # Claimed under a row lock. `None` means somebody else has it, or it is
    # already finished -- either way this worker does nothing, and in
    # particular makes no remote call.
    execution = services.claim_execution(execution_pk)
    if execution is None:
        return
    if execution.tenant_id != tenant_id:  # pragma: no cover - defensive
        return

    connector = execution.connector
    tenant = Tenant.objects.filter(pk=tenant_id).first()
    if tenant is None:  # pragma: no cover - defensive
        services.finish_execution(
            execution=execution,
            status=ExecutionStatus.FAILED,
            error_code=ExecutionErrorCode.INTERNAL_ERROR,
        )
        return

    # Re-read at start, not trusted from queue time.
    connector.refresh_from_db(fields=["status", "configuration", "configuration_version"])
    if connector.status != ConnectorStatus.ACTIVE:
        _log(execution, "connector execution refused: connector not active")
        services.finish_execution(
            execution=execution,
            status=ExecutionStatus.CANCELLED,
            error_code=ExecutionErrorCode.CONNECTOR_DISABLED,
        )
        return

    # The frozen snapshot, not today's row. An edit between queue and run does
    # not move a transfer somebody already authorised; it is re-validated
    # because a stored snapshot is still a stored value.
    try:
        config = validate_configuration(connector.connector_type, execution.configuration_snapshot)
    except ConfigurationError:
        services.finish_execution(
            execution=execution,
            status=ExecutionStatus.FAILED,
            error_code=ExecutionErrorCode.CONFIGURATION_INVALID,
        )
        return

    credential_reference = getattr(connector, "credential_reference", None)

    try:
        summary = run(
            execution.operation,
            execution=execution,
            connector=connector,
            config=config,
            credential_reference=credential_reference,
            actor=execution.requested_by,
            tenant=tenant,
        )
    except OperationError as exc:
        if exc.retryable and execution.attempt_count < MAX_ATTEMPTS:
            # Back into the queue, not into a terminal state: the attempt count
            # is already recorded, and a retry is another attempt at the same
            # execution rather than a new one.
            services.release_execution(execution)
            _log(execution, "connector execution retrying", error_code=exc.code)
            raise self.retry(
                countdown=RETRY_BACKOFF_SECONDS * execution.attempt_count, exc=exc
            ) from exc

        code = exc.code if not exc.retryable else ExecutionErrorCode.ATTEMPTS_EXHAUSTED
        _log(execution, "connector execution failed", error_code=code)
        services.finish_execution(
            execution=execution, status=ExecutionStatus.FAILED, error_code=code
        )
        return
    except Exception:
        # Nothing from an unexpected exception reaches the execution row. The
        # traceback goes to the log with `exc_info`, where the redaction filter
        # applies; the row gets an enumerated code.
        logger.exception(
            "connector execution raised",
            extra={
                "correlation_id": execution.correlation_id,
                "execution_public_id": str(execution.public_id),
                "operation": execution.operation,
            },
        )
        services.finish_execution(
            execution=execution,
            status=ExecutionStatus.FAILED,
            error_code=ExecutionErrorCode.INTERNAL_ERROR,
        )
        return

    finished = services.finish_execution(
        execution=execution,
        status=ExecutionStatus.SUCCEEDED,
        response_summary=summary,
        external_reference=summary.get("external_reference", ""),
    )

    external_object_id = summary.get("external_object_id")
    if external_object_id and execution.resource_type and execution.resource_public_id:
        services.link_external_object(
            tenant=tenant,
            connector=connector,
            resource_type=execution.resource_type,
            resource_public_id=execution.resource_public_id,
            external_object_id=external_object_id,
        )
    elif external_object_id and summary.get("document_version_public_id"):
        # An import creates the resource, so the link is made against what was
        # created rather than against something the request named.
        services.link_external_object(
            tenant=tenant,
            connector=connector,
            resource_type="document_version",
            resource_public_id=summary["document_version_public_id"],
            external_object_id=external_object_id,
        )

    _log(finished or execution, "connector execution succeeded")
