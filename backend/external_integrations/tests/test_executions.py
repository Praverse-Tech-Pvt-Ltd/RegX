"""Executions: permissions, tenancy, idempotency, config versioning, transfers.

The two operations are exercised end to end against a transport double, so the
assertions are about what *would* have gone out and what was recorded -- never
about a real remote service. `netpolicy` is never doubled: destination policy is
tested against the real functions in `test_netpolicy`.
"""

import json

import pytest

from external_integrations import services
from external_integrations.models import (
    ConnectorExecution,
    ConnectorStatus,
    ExecutionStatus,
    ExternalObjectLink,
)
from external_integrations.tests.conftest import (
    BASE_CONFIG,
    EXECUTIONS_API,
    INTEGRATIONS_API,
    PDF_BYTES,
    enable,
    make_connector,
    make_frozen_package,
)

SYNTHETIC_SECRET = "synthetic-token-value-not-a-real-credential"


def _import_body(**overrides):
    return {
        "operation": "import_document",
        "payload": {
            "external_object_id": "remote-doc-1.pdf",
            "relative_path": "inbox/remote-doc-1.pdf",
            "title": "Imported synthetic document",
            "document_type": "pdf",
            **overrides,
        },
    }


def _push_body(package, **overrides):
    return {
        "operation": "push_frozen_package",
        "payload": {"package_public_id": str(package.public_id), **overrides},
    }


def _run_queued(execution, tenant):
    """Run the worker for one execution, in-process."""
    from external_integrations.tasks import run_connector_execution

    run_connector_execution(execution.pk, tenant.pk)
    execution.refresh_from_db()
    return execution


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExecutionRequestSchema:
    def test_an_unknown_operation_is_refused(self, client_admin_a, active_connector):
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/",
            {"operation": "do_anything", "payload": {}},
            format="json",
        )
        assert response.status_code == 400

    def test_an_arbitrary_payload_is_refused(self, client_admin_a, active_connector):
        """There is no `{"operation": ..., "payload": {anything}}` shape that
        reaches the transport unexamined."""
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/",
            {"operation": "import_document", "payload": {"url": "https://evil.test/x"}},
            format="json",
        )
        assert response.status_code == 400

    def test_the_payload_cannot_name_a_destination(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        """The path extends the connector's prefix; it can never replace the
        host. Refused at the schema, and refused again by `build_url`."""
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/",
            _import_body(relative_path="https://evil.test/steal"),
            format="json",
        )
        # Accepted as text by the serializer, then refused when the URL is built.
        if response.status_code == 201:
            execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
            execution = _run_queued(execution, active_connector.tenant)
            assert execution.status == ExecutionStatus.FAILED
            assert execution.error_code == "PATH_REJECTED"
            assert fake_remote.calls == []
        else:
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExecutionPermissions:
    def test_connector_permission_alone_does_not_allow_a_package_transfer(
        self, tenant_a, admin_a, doer_a, monkeypatch
    ):
        """DOER can run connectors and export packages. Take away
        `documents.view` and the transfer must still be refused -- connector
        permission is never content permission.
        """
        from rest_framework.test import APIClient

        import documents.permissions as document_permissions

        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        package = make_frozen_package(tenant_a, admin_a)

        monkeypatch.setattr(
            document_permissions,
            "ROLE_PERMISSIONS",
            {**document_permissions.ROLE_PERMISSIONS, "doer": []},
        )
        client = APIClient()
        client.force_authenticate(user=doer_a)
        client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)

        response = client.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
            _push_body(package),
            format="json",
        )
        assert response.status_code == 403
        assert ConnectorExecution.objects.count() == 0

    def test_connector_permission_alone_does_not_allow_a_package_export(
        self, tenant_a, admin_a, doer_a, monkeypatch
    ):
        from rest_framework.test import APIClient

        import submission_packages.permissions as package_permissions

        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        package = make_frozen_package(tenant_a, admin_a)

        monkeypatch.setattr(
            package_permissions,
            "ROLE_PERMISSIONS",
            {**package_permissions.ROLE_PERMISSIONS, "doer": []},
        )
        client = APIClient()
        client.force_authenticate(user=doer_a)
        client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)

        response = client.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
            _push_body(package),
            format="json",
        )
        assert response.status_code == 403

    def test_the_package_permission_gate_runs_before_the_package_is_resolved(
        self, tenant_a, admin_a, doer_a, monkeypatch
    ):
        """A caller without the target-domain permission must not learn whether
        a package id exists. Same answer for a real one and a made-up one."""
        import uuid

        from rest_framework.test import APIClient

        import submission_packages.permissions as package_permissions

        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        package = make_frozen_package(tenant_a, admin_a)

        monkeypatch.setattr(
            package_permissions,
            "ROLE_PERMISSIONS",
            {**package_permissions.ROLE_PERMISSIONS, "doer": []},
        )
        client = APIClient()
        client.force_authenticate(user=doer_a)
        client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)

        real = client.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
            _push_body(package),
            format="json",
        )
        fake = client.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
            {
                "operation": "push_frozen_package",
                "payload": {"package_public_id": str(uuid.uuid4())},
            },
            format="json",
        )
        assert real.status_code == fake.status_code == 403
        assert json.dumps(real.data, default=str) == json.dumps(fake.data, default=str)

    def test_importing_requires_document_creation_permission(
        self, tenant_a, admin_a, doer_a, monkeypatch
    ):
        from rest_framework.test import APIClient

        import documents.permissions as document_permissions

        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        monkeypatch.setattr(
            document_permissions,
            "ROLE_PERMISSIONS",
            {**document_permissions.ROLE_PERMISSIONS, "doer": ["documents.view"]},
        )
        client = APIClient()
        client.force_authenticate(user=doer_a)
        client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)

        response = client.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/", _import_body(), format="json"
        )
        assert response.status_code == 403

    def test_platform_support_cannot_run_a_connector(self, client_support_a, active_connector):
        response = client_support_a.post(
            f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/",
            _import_body(),
            format="json",
        )
        assert response.status_code == 403

    def test_platform_support_cannot_configure_a_connector(self, client_support_a):
        response = client_support_a.post(
            f"{INTEGRATIONS_API}/",
            {
                "name": "Support connector",
                "connector_type": "generic_https",
                "configuration": BASE_CONFIG,
            },
            format="json",
        )
        assert response.status_code == 403

    def test_a_doer_cannot_configure_a_connector(self, client_doer_a):
        """Pointing the server at a network address is an elevated act."""
        response = client_doer_a.post(
            f"{INTEGRATIONS_API}/",
            {
                "name": "Doer connector",
                "connector_type": "generic_https",
                "configuration": BASE_CONFIG,
            },
            format="json",
        )
        assert response.status_code == 403

    def test_a_doer_cannot_enable_a_connector(self, client_doer_a, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        response = client_doer_a.post(f"{INTEGRATIONS_API}/{connector.public_id}/enable/")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantIsolation:
    def test_a_foreign_connector_is_404_at_every_endpoint(self, client_admin_a, tenant_b, admin_b):
        connector = enable(make_connector(tenant_b, admin_b, name="B connector"), tenant_b, admin_b)
        base = f"{INTEGRATIONS_API}/{connector.public_id}"
        assert client_admin_a.get(f"{base}/").status_code == 404
        for url in ("enable/", "disable/", "archive/", "test/", "executions/"):
            assert client_admin_a.post(f"{base}/{url}", {}, format="json").status_code == 404, url
        assert client_admin_a.get(f"{base}/executions/").status_code == 404

    def test_a_foreign_connector_is_indistinguishable_from_a_missing_one(
        self, client_admin_a, tenant_b, admin_b
    ):
        import uuid

        connector = make_connector(tenant_b, admin_b, name="B connector")
        foreign = client_admin_a.get(f"{INTEGRATIONS_API}/{connector.public_id}/")
        missing = client_admin_a.get(f"{INTEGRATIONS_API}/{uuid.uuid4()}/")
        assert foreign.status_code == missing.status_code == 404
        assert json.dumps(foreign.data, default=str) == json.dumps(missing.data, default=str)

    def test_a_foreign_execution_is_not_readable(
        self, client_admin_a, tenant_b, admin_b, fake_remote, monkeypatch
    ):
        from external_integrations.secrets import environment_variable_name

        connector = enable(make_connector(tenant_b, admin_b, name="B connector"), tenant_b, admin_b)
        monkeypatch.setenv(
            environment_variable_name(connector, connector.credential_reference), SYNTHETIC_SECRET
        )
        execution = services.create_execution(
            connector=connector,
            tenant=tenant_b,
            actor=admin_b,
            operation="import_document",
            idempotency_parts=["x"],
            request_summary={"external_object_id": "x"},
        )
        assert client_admin_a.get(f"{EXECUTIONS_API}/{execution.public_id}/").status_code == 404

    def test_a_connector_list_shows_only_this_tenant(
        self, client_admin_a, tenant_a, admin_a, tenant_b, admin_b
    ):
        make_connector(tenant_a, admin_a, name="Mine")
        make_connector(tenant_b, admin_b, name="Theirs")
        response = client_admin_a.get(f"{INTEGRATIONS_API}/")
        names = {row["name"] for row in response.data["results"]}
        assert names == {"Mine"}

    def test_a_package_from_another_tenant_cannot_be_transferred(
        self, client_admin_a, tenant_a, admin_a, tenant_b, admin_b
    ):
        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        foreign_package = make_frozen_package(tenant_b, admin_b, name="B package")
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
            _push_body(foreign_package),
            format="json",
        )
        assert response.status_code == 404

    def test_the_database_refuses_a_cross_tenant_credential_reference(
        self, tenant_a, admin_a, tenant_b, admin_b
    ):
        from django.db import IntegrityError, transaction
        from django.db.utils import InternalError, ProgrammingError

        from external_integrations.models import ConnectorCredentialReference

        connector = make_connector(tenant_a, admin_a, credential=False)
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
        ):
            ConnectorCredentialReference.objects.create(
                tenant=tenant_b, connector=connector, credential_type="bearer_token"
            )

    def test_the_database_refuses_a_cross_tenant_execution(self, tenant_a, admin_a, tenant_b):
        from django.db import IntegrityError, transaction
        from django.db.utils import InternalError, ProgrammingError

        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
        ):
            ConnectorExecution.objects.create(
                tenant=tenant_b,
                connector=connector,
                operation="import_document",
                requested_by=admin_a,
                idempotency_key="k" * 64,
                connector_configuration_version=1,
            )

    def test_the_database_refuses_a_cross_tenant_object_link(self, tenant_a, admin_a, tenant_b):
        from django.db import IntegrityError, transaction
        from django.db.utils import InternalError, ProgrammingError

        connector = make_connector(tenant_a, admin_a)
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
        ):
            ExternalObjectLink.objects.create(
                tenant=tenant_b,
                connector=connector,
                resource_type="document_version",
                resource_public_id="x",
                external_object_id="y",
            )


# ---------------------------------------------------------------------------
# Idempotency and concurrency
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestIdempotency:
    def test_the_same_package_transfer_twice_reuses_the_execution(
        self, client_admin_a, active_connector, connector_secret, tenant_a, admin_a, fake_remote
    ):
        package = make_frozen_package(tenant_a, admin_a)
        url = f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/"

        first = client_admin_a.post(url, _push_body(package), format="json")
        second = client_admin_a.post(url, _push_body(package), format="json")

        assert first.status_code == 201
        # 200, not a second 201 and not an error: the useful answer to "do this
        # again" is the execution that already exists.
        assert second.status_code == 200
        assert first.data["public_id"] == second.data["public_id"]
        assert ConnectorExecution.objects.count() == 1

    def test_the_idempotency_key_is_built_from_the_snapshot_not_the_name(
        self, client_admin_a, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """A package name is display text a user may edit. A key derived from
        one would change when somebody renamed something, and the same transfer
        would run a second time.

        Proved without renaming a frozen package -- Milestone 13 refuses that,
        correctly -- by showing the key the endpoint actually stored is exactly
        the snapshot-and-checksum key, and is not the key a name would produce.
        """
        package = make_frozen_package(tenant_a, admin_a, name="Original name")
        snapshot = package.snapshot

        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/",
            _push_body(package),
            format="json",
        )
        assert response.status_code == 201
        stored = ConnectorExecution.objects.get(public_id=response.data["public_id"])

        from_snapshot = services.build_idempotency_key(
            connector=active_connector,
            operation="push_frozen_package",
            parts=[str(snapshot.public_id), snapshot.manifest_checksum],
        )
        from_name = services.build_idempotency_key(
            connector=active_connector,
            operation="push_frozen_package",
            parts=[package.name, str(package.revision_number)],
        )
        assert stored.idempotency_key == from_snapshot
        assert stored.idempotency_key != from_name

    def test_two_different_packages_get_different_keys(self, tenant_a, admin_a):
        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        one = make_frozen_package(tenant_a, admin_a, name="One")
        two = make_frozen_package(tenant_a, admin_a, name="Two")
        assert services.build_idempotency_key(
            connector=connector,
            operation="push_frozen_package",
            parts=[str(one.snapshot.public_id)],
        ) != services.build_idempotency_key(
            connector=connector,
            operation="push_frozen_package",
            parts=[str(two.snapshot.public_id)],
        )

    def test_the_database_refuses_a_duplicate_key(self, tenant_a, admin_a, connector_secret):
        from django.db import IntegrityError, transaction

        connector = enable(make_connector(tenant_a, admin_a, name="Dup"), tenant_a, admin_a)
        services.create_execution(
            connector=connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["same"],
            request_summary={},
        )
        key = services.build_idempotency_key(
            connector=connector, operation="import_document", parts=["same"]
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ConnectorExecution.objects.create(
                tenant=tenant_a,
                connector=connector,
                operation="import_document",
                requested_by=admin_a,
                idempotency_key=key,
                connector_configuration_version=connector.configuration_version,
            )

    def test_a_second_worker_makes_no_remote_call(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """Claiming is a row lock. The loser stops before the transport."""
        package = make_frozen_package(tenant_a, admin_a)
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="push_frozen_package",
            resource_type="submission_package",
            resource_public_id=str(package.public_id),
            snapshot_public_id=str(package.snapshot.public_id),
            manifest_checksum=package.snapshot.manifest_checksum,
            idempotency_parts=[str(package.snapshot.public_id)],
            request_summary={},
        )
        _run_queued(execution, tenant_a)
        calls_after_first = len(fake_remote.calls)

        # The same task again, as a duplicate delivery would.
        _run_queued(execution, tenant_a)
        assert len(fake_remote.calls) == calls_after_first


# ---------------------------------------------------------------------------
# Configuration versioning and disablement
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestConfigurationAtExecutionTime:
    def test_an_execution_records_the_version_it_was_created_under(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["a"],
            request_summary={},
        )
        assert execution.connector_configuration_version == active_connector.configuration_version
        assert execution.configuration_snapshot["base_url"] == BASE_CONFIG["base_url"]

    def test_editing_the_connector_does_not_redirect_a_queued_execution(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """THE config-change test. An edit between queue and run must not send
        the transfer somewhere else."""
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["a"],
            request_summary={
                "external_object_id": "a.pdf",
                "relative_path": "inbox/a.pdf",
                "title": "A",
                "document_type": "pdf",
            },
        )
        services.update_connector(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            configuration={**BASE_CONFIG, "base_url": "https://somewhere-else.test/"},
        )
        active_connector.refresh_from_db()
        assert active_connector.configuration_version == 2

        fake_remote.body = PDF_BYTES
        _run_queued(execution, tenant_a)

        assert len(fake_remote.calls) == 1
        assert fake_remote.calls[0].url.startswith("https://connector.test/")
        assert "somewhere-else.test" not in fake_remote.calls[0].url

    def test_a_connector_disabled_before_the_worker_starts_makes_no_remote_call(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["a"],
            request_summary={
                "external_object_id": "a.pdf",
                "relative_path": "a.pdf",
                "title": "A",
                "document_type": "pdf",
            },
        )
        services.set_connector_status(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            status=ConnectorStatus.DISABLED,
        )

        execution = _run_queued(execution, tenant_a)
        assert execution.status == ExecutionStatus.CANCELLED
        assert execution.error_code == "CONNECTOR_DISABLED"
        assert fake_remote.calls == []

    def test_a_disabled_connector_refuses_a_new_execution(self, client_admin_a, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/", _import_body(), format="json"
        )
        assert response.status_code == 409

    def test_a_secret_rotation_between_queue_and_run_uses_the_current_value(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote, monkeypatch
    ):
        """Documented behaviour, not an accident: nothing records which secret
        value was used, so a retry resolves whatever the environment says now.
        Pinning a credential version is secret-manager work."""
        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["a"],
            request_summary={
                "external_object_id": "a.pdf",
                "relative_path": "a.pdf",
                "title": "A",
                "document_type": "pdf",
            },
        )
        monkeypatch.setenv(connector_secret, "rotated-synthetic-value")
        fake_remote.body = PDF_BYTES
        _run_queued(execution, tenant_a)

        assert fake_remote.calls[0].headers["Authorization"] == "Bearer rotated-synthetic-value"
        # And the value is nowhere in the stored record.
        execution.refresh_from_db()
        assert "rotated-synthetic-value" not in json.dumps(
            {
                "req": execution.request_summary,
                "res": execution.response_summary,
                "snap": execution.configuration_snapshot,
            },
            default=str,
        )


# ---------------------------------------------------------------------------
# Execution immutability
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExecutionImmutability:
    def _terminal(self, tenant, admin, connector):
        execution = services.create_execution(
            connector=connector,
            tenant=tenant,
            actor=admin,
            operation="import_document",
            idempotency_parts=["term"],
            request_summary={},
        )
        services.claim_execution(execution.pk)
        execution.refresh_from_db()
        return services.finish_execution(
            execution=execution, status=ExecutionStatus.SUCCEEDED, response_summary={}
        )

    def test_the_governed_manager_refuses_bulk_update(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        from external_integrations.governance import IntegrationMutationForbidden

        self._terminal(tenant_a, admin_a, active_connector)
        with pytest.raises(IntegrationMutationForbidden):
            ConnectorExecution.objects.update(status=ExecutionStatus.FAILED)

    def test_the_database_refuses_rewriting_a_terminal_execution(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        from django.db import connection, transaction
        from django.db.utils import IntegrityError, InternalError, ProgrammingError

        execution = self._terminal(tenant_a, admin_a, active_connector)
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connectorexecution SET status = 'failed' WHERE id = %s",
                [execution.pk],
            )

    def test_the_database_refuses_rewriting_what_was_transferred(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        """`resource_public_id` and the snapshot fields are the statement of
        *what went out*. A row whose subject could be rewritten afterwards would
        be worse than no record."""
        from django.db import connection, transaction
        from django.db.utils import IntegrityError, InternalError, ProgrammingError

        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            resource_type="document_version",
            resource_public_id="original",
            idempotency_parts=["subject"],
            request_summary={},
        )
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connectorexecution "
                "SET resource_public_id = 'rewritten' WHERE id = %s",
                [execution.pk],
            )

    def test_the_database_refuses_moving_an_execution_between_tenants(
        self, tenant_a, admin_a, tenant_b, active_connector, connector_secret
    ):
        from django.db import connection, transaction
        from django.db.utils import IntegrityError, InternalError, ProgrammingError

        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["tenantmove"],
            request_summary={},
        )
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_connectorexecution SET tenant_id = %s WHERE id = %s",
                [tenant_b.pk, execution.pk],
            )

    def test_the_database_refuses_deleting_execution_history(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        from django.db import connection, transaction
        from django.db.utils import IntegrityError, InternalError, ProgrammingError

        execution = self._terminal(tenant_a, admin_a, active_connector)
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "DELETE FROM external_integrations_connectorexecution WHERE id = %s",
                [execution.pk],
            )

    def test_the_database_refuses_repointing_an_object_link(self, tenant_a, admin_a):
        from django.db import connection, transaction
        from django.db.utils import IntegrityError, InternalError, ProgrammingError

        connector = make_connector(tenant_a, admin_a)
        link = services.link_external_object(
            tenant=tenant_a,
            connector=connector,
            resource_type="document_version",
            resource_public_id="original-resource",
            external_object_id="remote-1",
        )
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE external_integrations_externalobjectlink "
                "SET resource_public_id = 'rewritten' WHERE id = %s",
                [link.pk],
            )

    def test_an_execution_cannot_be_created_already_finished(
        self, tenant_a, admin_a, active_connector
    ):
        from django.db import transaction
        from django.db.utils import IntegrityError, InternalError, ProgrammingError
        from django.utils import timezone

        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
        ):
            ConnectorExecution.objects.create(
                tenant=tenant_a,
                connector=active_connector,
                operation="import_document",
                status=ExecutionStatus.SUCCEEDED,
                finished_at=timezone.now(),
                requested_by=admin_a,
                idempotency_key="z" * 64,
                connector_configuration_version=1,
            )

    def test_a_finished_execution_cannot_be_finished_again(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        """A first attempt that comes back to life after a retry must not
        overwrite the outcome that was already recorded."""
        execution = self._terminal(tenant_a, admin_a, active_connector)
        again = services.finish_execution(
            execution=execution, status=ExecutionStatus.FAILED, error_code="LATE"
        )
        assert again.status == ExecutionStatus.SUCCEEDED
        assert again.error_code == ""


@pytest.mark.django_db
class TestServiceLevelTenantGate:
    """The service's own tenant assertion, exercised directly.

    The API endpoints scope by tenant in the queryset, so `_assert_tenant` is
    never reached through them -- which means a mutation that neutered it turned
    nothing red. That was a test-coverage gap, not a reason to delete the check:
    the service is importable, callable from a task, and will be called from a
    future endpoint by somebody who assumes it is safe. So it is tested where it
    actually lives.
    """

    def test_get_connector_refuses_another_tenants_row(self, tenant_a, tenant_b, admin_b):
        from external_integrations.tests.conftest import make_connector

        foreign = make_connector(tenant_b, admin_b, name="B connector")
        with pytest.raises(services.InvalidTarget):
            services.get_connector(foreign.public_id, tenant_a)

    def test_update_refuses_another_tenants_connector(self, tenant_a, tenant_b, admin_a, admin_b):
        from external_integrations.tests.conftest import make_connector

        foreign = make_connector(tenant_b, admin_b, name="B connector")
        with pytest.raises(services.InvalidTarget):
            services.update_connector(
                connector=foreign, tenant=tenant_a, actor=admin_a, name="Hijacked"
            )

    def test_status_change_refuses_another_tenants_connector(
        self, tenant_a, tenant_b, admin_a, admin_b
    ):
        from external_integrations.tests.conftest import make_connector

        foreign = make_connector(tenant_b, admin_b, name="B connector")
        with pytest.raises(services.InvalidTarget):
            services.set_connector_status(
                connector=foreign,
                tenant=tenant_a,
                actor=admin_a,
                status=ConnectorStatus.ACTIVE,
            )

    def test_creating_an_execution_refuses_another_tenants_connector(
        self, tenant_a, tenant_b, admin_a, admin_b
    ):
        from external_integrations.tests.conftest import enable, make_connector

        foreign = enable(make_connector(tenant_b, admin_b, name="B connector"), tenant_b, admin_b)
        with pytest.raises(services.InvalidTarget):
            services.create_execution(
                connector=foreign,
                tenant=tenant_a,
                actor=admin_a,
                operation="import_document",
                idempotency_parts=["x"],
                request_summary={},
            )

    def test_credential_reference_refuses_another_tenants_connector(
        self, tenant_a, tenant_b, admin_a, admin_b
    ):
        """Tenant A must not be able to name a credential on tenant B's
        connector. Refused by the service, and by `0002` underneath it."""
        from external_integrations.tests.conftest import make_connector

        foreign = make_connector(tenant_b, admin_b, name="B connector", credential=False)
        with pytest.raises(services.InvalidTarget):
            services.set_credential_reference(
                connector=foreign,
                tenant=tenant_a,
                actor=admin_a,
                credential_type="bearer_token",
            )

    def test_execution_history_refuses_another_tenants_connector(self, tenant_a, tenant_b, admin_b):
        from external_integrations.tests.conftest import make_connector

        foreign = make_connector(tenant_b, admin_b, name="B connector")
        with pytest.raises(services.InvalidTarget):
            services.executions_for(foreign, tenant_a)

    def test_recording_a_test_result_refuses_another_tenants_connector(
        self, tenant_a, tenant_b, admin_a, admin_b
    ):
        from external_integrations.models import TestStatus
        from external_integrations.tests.conftest import make_connector

        foreign = make_connector(tenant_b, admin_b, name="B connector")
        with pytest.raises(services.InvalidTarget):
            services.record_test_result(
                connector=foreign,
                tenant=tenant_a,
                actor=admin_a,
                test_status=TestStatus.REACHABLE,
            )
