"""QA-09 (external_integrations): a change and its audit record commit together.

Fault injection: `audit.testing.audit_writes_fail()` makes every audit INSERT fail in
PostgreSQL. On the old code the connection-test result was written with an autocommit
UPDATE, and the cancel view's actor-naming event was written after `finish_execution`
committed; both tests failed.
"""

from __future__ import annotations

import pytest

from audit.testing import attempt, audit_writes_fail
from external_integrations import services
from external_integrations.models import ConnectorExecution, ExecutionStatus, TestStatus

from .test_transport_and_api import EXECUTIONS_API

pytestmark = pytest.mark.django_db(transaction=True)


def test_connection_test_result_rolls_back_without_its_audit(tenant_a, admin_a, active_connector):
    before = (active_connector.last_tested_at, active_connector.last_test_status)
    with audit_writes_fail():
        attempt(
            services.record_test_result,
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            test_status=TestStatus.REACHABLE,
        )
    active_connector.refresh_from_db()
    assert (active_connector.last_tested_at, active_connector.last_test_status) == before


def test_cancel_rolls_back_without_its_audit(
    client_admin_a, tenant_a, admin_a, active_connector, connector_secret
):
    execution = services.create_execution(
        connector=active_connector,
        tenant=tenant_a,
        actor=admin_a,
        operation="import_document",
        idempotency_parts=["qa09-cancel"],
        request_summary={},
    )
    # Only the view's own event fails: it is the one that names the actor, and on the
    # old code it was written after finish_execution had already committed CANCELLED.
    with audit_writes_fail(when="NEW.actor_id IS NOT NULL"):
        attempt(client_admin_a.post, f"{EXECUTIONS_API}/{execution.public_id}/cancel/")
    assert ConnectorExecution.objects.get(pk=execution.pk).status == ExecutionStatus.QUEUED
