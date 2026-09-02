"""Database governance, migration classification, audit, and what is not claimed.

The last group asks whether the code says anything it cannot prove: that a
transfer is a submission, that a remote system stored something, that delivery
happened exactly once. Those claims are easy to make by accident in a status
name or a docstring, so they are checked mechanically.
"""

import importlib
import json

import pytest
from django.db import connection, migrations, transaction
from django.db.utils import IntegrityError, InternalError, ProgrammingError

from external_integrations import services
from external_integrations.models import (
    Connector,
    ConnectorExecution,
    ConnectorStatus,
    ExecutionStatus,
    ExternalObjectLink,
)
from external_integrations.tests.conftest import (
    BASE_CONFIG,
    INTEGRATIONS_API,
    make_connector,
    make_frozen_package,
)

DB_REFUSAL = (InternalError, ProgrammingError, IntegrityError)


# ---------------------------------------------------------------------------
# The database floor
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDatabaseGovernance:
    def test_a_connector_configuration_must_be_an_object(self, tenant_a, admin_a):
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            Connector.objects.create(
                tenant=tenant_a,
                name="Scalar config",
                connector_type="generic_https",
                configuration=["not", "an", "object"],
                created_by=admin_a,
            )

    def test_a_configuration_change_must_bump_the_version(self, tenant_a, admin_a):
        """The version is what a queued execution compares itself against. A
        configuration that moved without it would let a retry follow an edit
        while still claiming to run the version it was created under."""
        connector = make_connector(tenant_a, admin_a)
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connector SET configuration = %s WHERE id = %s",
                [json.dumps({**BASE_CONFIG, "read_timeout_seconds": 99}), connector.pk],
            )

    def test_a_configuration_version_never_decreases(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        services.update_connector(
            connector=connector,
            tenant=tenant_a,
            actor=admin_a,
            configuration={**BASE_CONFIG, "read_timeout_seconds": 45},
        )
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connector "
                "SET configuration_version = 1 WHERE id = %s",
                [connector.pk],
            )

    def test_a_connector_cannot_change_tenant(self, tenant_a, admin_a, tenant_b):
        connector = make_connector(tenant_a, admin_a)
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connector SET tenant_id = %s WHERE id = %s",
                [tenant_b.pk, connector.pk],
            )

    def test_a_connector_cannot_change_type(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connector SET connector_type = 'sftp' WHERE id = %s",
                [connector.pk],
            )

    def test_an_execution_must_name_a_configuration_version_that_exists(
        self, tenant_a, admin_a, active_connector
    ):
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            ConnectorExecution.objects.create(
                tenant=tenant_a,
                connector=active_connector,
                operation="import_document",
                requested_by=admin_a,
                idempotency_key="v" * 64,
                connector_configuration_version=99,
            )

    def test_an_execution_must_carry_an_idempotency_key(self, tenant_a, admin_a, active_connector):
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            ConnectorExecution.objects.create(
                tenant=tenant_a,
                connector=active_connector,
                operation="import_document",
                requested_by=admin_a,
                idempotency_key="short",
                connector_configuration_version=1,
            )

    def test_an_object_link_must_name_a_remote_object(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            ExternalObjectLink.objects.create(
                tenant=tenant_a,
                connector=connector,
                resource_type="document_version",
                resource_public_id="x",
                external_object_id="",
            )

    def test_an_object_link_cannot_be_deleted(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        link = services.link_external_object(
            tenant=tenant_a,
            connector=connector,
            resource_type="document_version",
            resource_public_id="r",
            external_object_id="remote-1",
        )
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "DELETE FROM external_integrations_externalobjectlink WHERE id = %s", [link.pk]
            )

    def test_an_execution_cannot_move_to_an_illegal_status(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["illegal"],
            request_summary={},
        )
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            # queued -> succeeded, skipping running and with no finished stamp.
            cursor.execute(
                "UPDATE external_integrations_connectorexecution "
                "SET status = 'succeeded' WHERE id = %s",
                [execution.pk],
            )

    def test_a_connector_with_execution_history_cannot_be_deleted(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        """`PROTECT`, because execution history is evidence of what was
        transferred and deleting the connector would strand it."""
        from django.db.models import ProtectedError

        services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["protect"],
            request_summary={},
        )
        with pytest.raises(ProtectedError), transaction.atomic():
            active_connector.delete()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMigrations:
    """Docstring counts drift silently; SQL does not.

    Milestone 10 shipped a docstring claiming five functions and eight triggers
    where the SQL had seven of each, and Milestone 11 claimed a symmetry test
    covered its counts when the test lived in another app. This one ships with
    the migration it describes -- and it caught this migration's own docstring
    claiming six functions where there are eight.
    """

    FUNCTIONS = 8
    TRIGGERS = 9

    def _module(self, name):
        return importlib.import_module(f"external_integrations.migrations.{name}")

    def test_create_and_drop_are_symmetric(self):
        m = self._module("0002_integration_db_governance")
        assert m.CREATE_SQL.count("CREATE OR REPLACE FUNCTION") == self.FUNCTIONS
        assert m.CREATE_SQL.count("CREATE TRIGGER") == self.TRIGGERS
        assert m.DROP_SQL.count("DROP FUNCTION") == self.FUNCTIONS
        assert m.DROP_SQL.count("DROP TRIGGER") == self.TRIGGERS

    def test_the_docstring_states_the_real_counts(self):
        m = self._module("0002_integration_db_governance")
        doc = " ".join((m.__doc__ or "").split())
        assert f"{self.FUNCTIONS} plpgsql functions" in doc, doc[:300]
        assert f"{self.TRIGGERS} triggers" in doc, doc[:300]

    def test_every_created_trigger_is_dropped_by_name(self):
        m = self._module("0002_integration_db_governance")
        created = {
            line.split()[2]
            for line in m.CREATE_SQL.splitlines()
            if line.startswith("CREATE TRIGGER")
        }
        dropped = {
            line.split()[4] for line in m.DROP_SQL.splitlines() if line.startswith("DROP TRIGGER")
        }
        assert created == dropped

    def test_the_governance_migration_declares_its_class(self):
        m = self._module("0002_integration_db_governance")
        doc = " ".join((m.__doc__ or "").split())
        assert "FORWARD: Class A." in doc
        assert "ROLLBACK: Class A **on its own terms**." in doc
        # And it does not quietly relax 0001.
        assert "CLASS C -- DATA RESTORE REQUIRED" in doc

    def test_the_initial_migration_is_reversible_only_in_the_schema_sense(self):
        """`0001` creates tables. Reversing it destroys execution history, which
        is the record that something left this deployment."""
        m = self._module("0002_integration_db_governance")
        doc = " ".join((m.__doc__ or "").split())
        assert "not derivable from anything else" in doc

    def test_the_governance_migration_does_not_claim_to_validate_destinations(self):
        """It checks shape. Reproducing `netpolicy` in plpgsql would be two
        implementations of a security policy in two languages."""
        m = self._module("0002_integration_db_governance")
        doc = " ".join((m.__doc__ or "").split())
        assert "It cannot tell whether `configuration` is *safe*" in doc
        assert "would be claiming a guarantee that is not there" in doc

    def test_the_raw_sql_step_declares_a_reverse(self):
        m = self._module("0002_integration_db_governance")
        raw = [op for op in m.Migration.operations if isinstance(op, migrations.RunSQL)]
        assert len(raw) == 1
        assert raw[0].reverse_sql

    def test_the_triggers_are_installed_and_armed(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tgname, tgenabled FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgrelid::regclass::text LIKE 'external_integrations%%'"
            )
            rows = dict(cursor.fetchall())
        assert len(rows) == self.TRIGGERS, rows
        assert all(state == "O" for state in rows.values()), rows


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAudit:
    def test_the_lifecycle_is_audited(
        self,
        client_admin_a,
        tenant_a,
        admin_a,
        active_connector,
        connector_secret,
        fake_remote,
        django_capture_on_commit_callbacks,
    ):
        from audit.models import AuditEvent

        package = make_frozen_package(tenant_a, admin_a)
        # The execution task is dispatched on commit, so the deferred work has
        # to be run for the started/succeeded events to exist at all.
        with django_capture_on_commit_callbacks(execute=True):
            client_admin_a.post(
                f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/",
                {
                    "operation": "push_frozen_package",
                    "payload": {"package_public_id": str(package.public_id)},
                },
                format="json",
            )
        events = set(
            AuditEvent.objects.filter(resource_type="external_integration").values_list(
                "event_type", flat=True
            )
        )
        assert "external_connector.created" in events
        assert "external_connector.enabled" in events
        assert "external_execution.created" in events
        assert "external_execution.started" in events
        assert "external_execution.succeeded" in events
        assert "external_object.linked" in events

    def test_every_emitted_event_name_is_declared(self, tenant_a, admin_a, active_connector):
        """An event nobody declared is an event nobody can filter on."""
        from audit.models import AuditEvent
        from external_integrations.audit_events import IntegrationEvent

        declared = {
            value
            for name, value in vars(IntegrationEvent).items()
            if not name.startswith("_") and isinstance(value, str)
        }
        emitted = set(
            AuditEvent.objects.filter(resource_type="external_integration").values_list(
                "event_type", flat=True
            )
        )
        assert emitted <= declared, emitted - declared

    def test_the_payload_allow_list_holds(self, tenant_a, admin_a):
        """Anything not named is dropped, including the connector's own name."""
        from external_integrations.audit_events import _filtered

        cleaned = _filtered(
            {
                "connector_public_id": "abc",
                "name": "My connector",
                "base_url": "https://connector.test/",
                "authorization": "Bearer x",
                "response_body": "<html/>",
            }
        )
        assert cleaned == {"connector_public_id": "abc"}

    def test_an_allow_listed_value_is_still_bounded(self):
        """A remote system returning a megabyte of "id" costs one truncated
        row, not a megabyte per attempt."""
        from external_integrations.audit_events import _filtered

        cleaned = _filtered({"external_object_id": "x" * 5000})
        assert len(cleaned["external_object_id"]) == 255

    def test_no_base_url_or_header_reaches_audit(
        self, client_admin_a, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        from audit.models import AuditEvent

        client_admin_a.post(f"{INTEGRATIONS_API}/{active_connector.public_id}/test/")
        blob = json.dumps(list(AuditEvent.objects.values("payload")), default=str)
        assert "connector.test" not in blob
        assert "Bearer" not in blob
        assert "Authorization" not in blob


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStructuredLogging:
    def test_the_task_logs_ids_and_never_content(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote, caplog
    ):
        from external_integrations.tests.conftest import PDF_BYTES

        fake_remote.body = PDF_BYTES
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["log"],
            request_summary={
                "external_object_id": "a.pdf",
                "relative_path": "inbox/a.pdf",
                "title": "A",
            },
        )
        with caplog.at_level("INFO", logger="regx.external_integrations"):
            from external_integrations.tasks import run_connector_execution

            run_connector_execution(execution.pk, tenant_a.pk)

        assert caplog.records, "the task logged nothing at all"
        record = caplog.records[-1]
        assert record.execution_public_id == str(execution.public_id)
        assert record.operation == "import_document"

        blob = "\n".join(r.getMessage() + json.dumps(vars(r), default=str) for r in caplog.records)
        assert "synthetic-token-value" not in blob
        assert "%PDF" not in blob
        assert "Bearer" not in blob


# ---------------------------------------------------------------------------
# Regulatory boundaries
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRegulatoryBoundary:
    def test_no_status_or_operation_implies_regulatory_meaning(self):
        from external_integrations.models import ConnectorOperation

        statuses = {value for value, _ in ConnectorStatus.choices}
        statuses |= {value for value, _ in ExecutionStatus.choices}
        operations = {value for value, _ in ConnectorOperation.choices}

        for banned in ("approved", "submitted", "filed", "accepted", "validated", "released"):
            assert banned not in statuses
            assert banned not in operations

    def test_no_module_claims_agency_readiness(self):
        """Pinned. Every match must sit inside an explicit disclaimer."""
        import pathlib

        banned = [
            "agency ready",
            "fda ready",
            "ema ready",
            "submitted to agency",
            "regulatory filed",
            "regulatory approved",
            "regulatory compliant",
            "part 11 compliant",
            "validated system",
            "validated production",
            "exactly-once delivery",
        ]
        root = pathlib.Path("external_integrations")
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == pathlib.Path(__file__).name:
                # This file owns the banned list, so every phrase appears in it
                # by construction. Skipping it is not a loophole: nothing here
                # ships, and the phrases exist only to keep them out of what does.
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for phrase in banned:
                if phrase in text:
                    for line in text.splitlines():
                        if phrase in line and not any(
                            marker in line for marker in ("not ", "never", "no ", "banned")
                        ):
                            offenders.append(f"{path}: {phrase}")
        assert offenders == [], offenders

    def test_no_agency_format_or_gateway_appears(self):
        import pathlib

        root = pathlib.Path("external_integrations")
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == pathlib.Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for phrase in ("ectd", "nees", "esg gateway", "regional module", "xml backbone"):
                if phrase in text:
                    offenders.append(f"{path}: {phrase}")
        assert offenders == [], offenders

    def test_the_operations_module_states_what_it_does_not_claim(self):
        from external_integrations import operations

        doc = " ".join((operations.__doc__ or "").split())
        assert "It does not mean the remote system stored them" in doc
        assert "remote_checksum_verified` is `False`" in doc

    def test_the_secrets_module_does_not_pretend_to_be_a_secret_manager(self):
        from external_integrations import secrets

        doc = " ".join((secrets.__doc__ or "").split())
        assert "This is not a secret manager" in doc
        assert "It reads an environment variable" in doc

    def test_no_sftp_or_vendor_type_is_offered_without_an_implementation(self):
        """An enum member with no working transport is a promise the code does
        not keep, and a tenant selecting it would reasonably expect it to work."""
        from external_integrations.models import ConnectorType

        assert {value for value, _ in ConnectorType.choices} == {"generic_https"}

    def test_no_destructive_remote_operation_exists(self):
        from external_integrations.models import ConnectorOperation
        from external_integrations.transport import ALLOWED_METHODS

        assert "DELETE" not in ALLOWED_METHODS
        for value, _label in ConnectorOperation.choices:
            assert "delete" not in value and "remove" not in value


@pytest.mark.django_db
class TestTerminalExecutionIsFrozenEntirely:
    """A finished execution refuses **every** UPDATE, not just a status change.

    The status-transition rules already refuse `succeeded -> failed`, so a test
    that only tried that proved nothing about the terminal guard: removing the
    guard left the transition check to raise, and the mutation turned nothing
    red. These rewrite fields the transition rules say nothing about, so the
    only thing that can refuse them is "a finished execution cannot be changed".

    It matters because the fields below are the *result*. An execution whose
    error code or byte count could be edited afterwards would be a record of
    what somebody last said happened, not of what happened.
    """

    def _succeeded(self, tenant, admin, connector):
        execution = services.create_execution(
            connector=connector,
            tenant=tenant,
            actor=admin,
            operation="import_document",
            idempotency_parts=["frozen-entirely"],
            request_summary={},
        )
        services.claim_execution(execution.pk)
        execution.refresh_from_db()
        return services.finish_execution(
            execution=execution,
            status=ExecutionStatus.SUCCEEDED,
            response_summary={"http_status": 200, "bytes_transferred": 4096},
            external_reference="remote-1",
        )

    @pytest.mark.parametrize(
        "column,value",
        [
            ("error_code", "'REWRITTEN'"),
            ("external_reference", "'somewhere-else'"),
            ("attempt_count", "99"),
            ("finished_at", "now()"),
            ("started_at", "now()"),
        ],
    )
    def test_no_field_of_a_finished_execution_can_be_rewritten(
        self, tenant_a, admin_a, active_connector, connector_secret, column, value
    ):
        execution = self._succeeded(tenant_a, admin_a, active_connector)
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connectorexecution "
                f"SET {column} = {value} WHERE id = %s",
                [execution.pk],
            )

    def test_the_response_summary_of_a_finished_execution_cannot_be_rewritten(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        execution = self._succeeded(tenant_a, admin_a, active_connector)
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connectorexecution "
                "SET response_summary = %s WHERE id = %s",
                [json.dumps({"http_status": 500}), execution.pk],
            )

    def test_a_cancelled_execution_is_equally_frozen(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["cancelled-frozen"],
            request_summary={},
        )
        services.finish_execution(
            execution=execution,
            status=ExecutionStatus.CANCELLED,
            error_code="CANCELLED_BY_USER",
        )
        with (
            pytest.raises(DB_REFUSAL),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connectorexecution "
                "SET error_code = 'REOPENED' WHERE id = %s",
                [execution.pk],
            )
