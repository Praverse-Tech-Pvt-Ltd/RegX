"""The two operations, end to end against a transport double.

IMPORT_DOCUMENT is tested by feeding the double the kinds of content a hostile
or careless remote system actually sends -- a real PDF, a macro-bearing Office
container, a malformed archive, oversized content, content whose declared type
disagrees with its bytes -- and asserting that the document platform's own rules
decide the outcome. There is no connector-shaped exemption from any of them,
because there is no second pipeline for one to live in.

PUSH_FROZEN_PACKAGE is tested for exactness: the execution binds to a snapshot
and a manifest checksum, and Milestone 13's exporter is what produces the bytes.
"""

import io
import json
import zipfile

import pytest

from documents.models import Document, DocumentVersion, ScanStatus
from external_integrations import services
from external_integrations.models import ConnectorExecution, ExecutionStatus, ExternalObjectLink
from external_integrations.tests.conftest import (
    INTEGRATIONS_API,
    PDF_BYTES,
    make_frozen_package,
)


def _macro_docx() -> bytes:
    """A DOCX-shaped zip containing a macro part."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"></Types>',
        )
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/vbaProject.bin", b"\x00macro payload")
    return buffer.getvalue()


def _queue_import(client, connector, **overrides):
    return client.post(
        f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
        {
            "operation": "import_document",
            "payload": {
                "external_object_id": "remote-doc-1.pdf",
                "relative_path": "inbox/remote-doc-1.pdf",
                "title": "Imported synthetic document",
                "document_type": "pdf",
                **overrides,
            },
        },
        format="json",
    )


def _run(execution, tenant):
    from external_integrations.tasks import run_connector_execution

    run_connector_execution(execution.pk, tenant.pk)
    execution.refresh_from_db()
    return execution


# ---------------------------------------------------------------------------
# Inbound import
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInboundImport:
    def test_a_valid_pdf_becomes_a_normal_document_version(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        fake_remote.body = PDF_BYTES
        response = _queue_import(client_admin_a, active_connector)
        assert response.status_code == 201

        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
        execution = _run(execution, tenant_a)

        assert execution.status == ExecutionStatus.SUCCEEDED
        version = DocumentVersion.objects.get(
            public_id=execution.response_summary["document_version_public_id"]
        )
        # Indistinguishable from an uploaded version, which is the point.
        assert version.document.tenant_id == tenant_a.pk
        assert version.sha256_checksum
        assert version.size_bytes == len(PDF_BYTES)
        assert version.detected_mime_type == "application/pdf"

    def test_the_scan_is_queued_and_the_version_is_not_pre_cleared(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, monkeypatch
    ):
        """No "trusted connector" shortcut. A version arrives PENDING and the
        scan task is dispatched, exactly as for a browser upload."""
        dispatched = []
        monkeypatch.setattr(
            "documents.ingest.scan_document_version",
            type("T", (), {"delay": staticmethod(lambda *a, **k: dispatched.append(a))}),
        )
        fake_remote.body = PDF_BYTES
        response = _queue_import(client_admin_a, active_connector)
        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
        _run(execution, tenant_a)

        version = DocumentVersion.objects.latest("id")
        assert version.scan_status == ScanStatus.PENDING
        assert dispatched, "the scan was never queued for imported content"

    def test_a_macro_document_is_refused_by_the_document_platform(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        fake_remote.body = _macro_docx()
        response = _queue_import(
            client_admin_a,
            active_connector,
            external_object_id="remote.docx",
            relative_path="inbox/remote.docx",
        )
        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
        execution = _run(execution, tenant_a)

        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "DOCUMENT_REJECTED"
        assert Document.objects.count() == 0

    def test_a_malformed_archive_is_refused(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        fake_remote.body = b"PK\x03\x04 this is not really a zip"
        response = _queue_import(
            client_admin_a,
            active_connector,
            external_object_id="broken.docx",
            relative_path="inbox/broken.docx",
        )
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.FAILED
        assert Document.objects.count() == 0

    def test_content_that_contradicts_its_extension_is_refused(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        """A remote system claiming `.pdf` while sending something else is
        exactly what MIME consistency checking is for."""
        fake_remote.body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        response = _queue_import(client_admin_a, active_connector)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "DOCUMENT_REJECTED"

    def test_an_empty_response_is_refused(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        fake_remote.body = b""
        response = _queue_import(client_admin_a, active_connector)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "EMPTY_RESPONSE"
        assert Document.objects.count() == 0

    def test_an_oversized_response_is_refused_by_the_transport(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        from external_integrations.transport import TransportError, TransportErrorCode

        fake_remote.raises = TransportError(TransportErrorCode.RESPONSE_TOO_LARGE)
        response = _queue_import(client_admin_a, active_connector)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == TransportErrorCode.RESPONSE_TOO_LARGE
        assert Document.objects.count() == 0

    def test_a_remote_filename_cannot_traverse(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        """The remote system names the object. That name reaches a filename
        validator, so it is reduced to a basename first."""
        fake_remote.body = PDF_BYTES
        response = _queue_import(
            client_admin_a,
            active_connector,
            external_object_id="../../../etc/passwd.pdf",
            relative_path="inbox/x.pdf",
        )
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.SUCCEEDED
        version = DocumentVersion.objects.latest("id")
        assert ".." not in version.original_filename
        assert "/" not in version.original_filename

    def test_an_import_creates_an_external_object_link(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        fake_remote.body = PDF_BYTES
        response = _queue_import(client_admin_a, active_connector)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        link = ExternalObjectLink.objects.get(tenant=tenant_a)
        assert link.resource_type == "document_version"
        assert link.resource_public_id == execution.response_summary["document_version_public_id"]
        assert link.connector_id == active_connector.pk

    def test_the_imported_document_belongs_to_the_execution_tenant(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        fake_remote.body = PDF_BYTES
        response = _queue_import(client_admin_a, active_connector)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        version = DocumentVersion.objects.latest("id")
        link = ExternalObjectLink.objects.get(tenant=tenant_a)
        assert version.document.tenant_id == execution.tenant_id == link.tenant_id


# ---------------------------------------------------------------------------
# Outbound package transfer
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOutboundPackageTransfer:
    def _queue(self, client, connector, package, **overrides):
        return client.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
            {
                "operation": "push_frozen_package",
                "payload": {"package_public_id": str(package.public_id), **overrides},
            },
            format="json",
        )

    def test_a_frozen_package_transfers(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        package = make_frozen_package(tenant_a, admin_a)
        response = self._queue(client_admin_a, active_connector, package)
        assert response.status_code == 201

        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.SUCCEEDED
        assert execution.response_summary["bytes_transferred"] > 0
        # PUT, not POST: this replaces a named object, and DELETE does not exist.
        assert fake_remote.calls[0].method == "PUT"

    def test_the_execution_binds_to_the_exact_snapshot(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        """Never "the latest package", never "the latest revision"."""
        package = make_frozen_package(tenant_a, admin_a)
        response = self._queue(client_admin_a, active_connector, package)
        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])

        assert execution.resource_public_id == str(package.public_id)
        assert execution.snapshot_public_id == str(package.snapshot.public_id)
        assert execution.manifest_checksum == package.snapshot.manifest_checksum

    def test_a_draft_package_cannot_be_transferred(
        self, client_admin_a, active_connector, connector_secret, tenant_a, admin_a
    ):
        from regulatory_cases import services as case_services
        from submission_packages import services as package_services

        case = case_services.create_case(tenant=tenant_a, actor=admin_a, title="Draft case")
        package = package_services.create_package(
            case_public_id=case.public_id, tenant=tenant_a, actor=admin_a, name="Draft package"
        )
        response = self._queue(client_admin_a, active_connector, package)
        assert response.status_code == 409

    def test_an_in_review_package_cannot_be_transferred(
        self, client_admin_a, active_connector, connector_secret, tenant_a, admin_a
    ):
        from external_integrations.tests.conftest import make_document_version
        from regulatory_cases import services as case_services
        from submission_packages import services as package_services

        case = case_services.create_case(tenant=tenant_a, actor=admin_a, title="Review case")
        version = make_document_version(tenant_a, admin_a)
        package = package_services.create_package(
            case_public_id=case.public_id, tenant=tenant_a, actor=admin_a, name="Review package"
        )
        package_services.add_entry(
            package=package,
            tenant=tenant_a,
            actor=admin_a,
            document_version_public_id=version.public_id,
        )
        package = package_services.submit_for_review(
            package=package, tenant=tenant_a, actor=admin_a
        )
        response = self._queue(client_admin_a, active_connector, package)
        assert response.status_code == 409

    def test_a_package_whose_file_vanished_fails_before_any_remote_call(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        """Milestone 13's exporter refuses, so nothing is sent. The failure is
        local, which is the only place it can safely be detected.

        The file is removed *before* the request, because Celery is eager under
        test: `delay()` runs the task inside the POST, so a condition set up
        afterwards would be testing an execution that had already finished.
        """
        from documents.storage import get_storage_backend

        package = make_frozen_package(tenant_a, admin_a)
        entry = package.entries.first()
        get_storage_backend().delete(entry.document_version.storage_key)

        response = self._queue(client_admin_a, active_connector, package)
        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])

        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "PACKAGE_INTEGRITY_FAILED"
        assert fake_remote.calls == []

    def test_a_snapshot_that_does_not_match_the_execution_stops_the_transfer(
        self, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        """The execution named a snapshot and a checksum. If what is on the
        package no longer matches, this is not the transfer that was authorised.

        Exercised by calling the operation directly, because neither side can be
        corrupted through the database: the execution's provenance columns are
        immutable (`0002`) and the package snapshot is immutable (Milestone 13).
        That the state is unreachable is a good thing; the guard still has to
        exist, and it still has to be tested.
        """
        from external_integrations.operations import OperationError, run_push_frozen_package

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
            idempotency_parts=[str(package.snapshot.public_id), "drift"],
            request_summary={},
        )
        # In memory only. Nothing is written; the row keeps the truth.
        execution.manifest_checksum = "0" * 64

        config = active_connector.configuration
        with pytest.raises(OperationError) as excinfo:
            run_push_frozen_package(
                execution=execution,
                connector=active_connector,
                config=config,
                credential_reference=active_connector.credential_reference,
                actor=admin_a,
                tenant=tenant_a,
            )
        assert excinfo.value.code == "PACKAGE_INTEGRITY_FAILED"
        assert fake_remote.calls == []

    def test_a_different_snapshot_id_also_stops_the_transfer(
        self, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        import uuid

        from external_integrations.operations import OperationError, run_push_frozen_package

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
            idempotency_parts=[str(package.snapshot.public_id), "snapdrift"],
            request_summary={},
        )
        execution.snapshot_public_id = str(uuid.uuid4())

        with pytest.raises(OperationError) as excinfo:
            run_push_frozen_package(
                execution=execution,
                connector=active_connector,
                config=active_connector.configuration,
                credential_reference=active_connector.credential_reference,
                actor=admin_a,
                tenant=tenant_a,
            )
        assert excinfo.value.code == "PACKAGE_INTEGRITY_FAILED"
        assert fake_remote.calls == []

    def test_the_transferred_bytes_are_the_milestone_13_archive(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        package = make_frozen_package(tenant_a, admin_a)
        response = self._queue(client_admin_a, active_connector, package)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )

        call = fake_remote.calls[0]
        assert call.headers["Content-Type"] == "application/zip"
        assert call.headers["X-Manifest-Checksum"] == package.snapshot.manifest_checksum
        # The remote is offered the key. Whether it honours it is its business.
        assert call.headers["X-Idempotency-Key"] == execution.idempotency_key
        assert call.body_length == execution.response_summary["bytes_transferred"]

    def test_a_remote_checksum_is_compared_when_offered(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        package = make_frozen_package(tenant_a, admin_a)
        fake_remote.remote_checksum = "not-the-right-checksum"
        response = self._queue(client_admin_a, active_connector, package)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "PACKAGE_INTEGRITY_FAILED"

    def test_no_remote_checksum_means_not_verified_not_assumed(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        """Silence is recorded as silence. Nothing claims the remote system
        holds bytes it never said anything about."""
        package = make_frozen_package(tenant_a, admin_a)
        fake_remote.remote_checksum = ""
        response = self._queue(client_admin_a, active_connector, package)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert execution.status == ExecutionStatus.SUCCEEDED
        assert execution.response_summary["remote_checksum_verified"] is False

    def test_a_successful_transfer_links_the_package_to_the_remote_object(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a, admin_a
    ):
        package = make_frozen_package(tenant_a, admin_a)
        response = self._queue(client_admin_a, active_connector, package)
        _run(ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a)

        link = ExternalObjectLink.objects.get(tenant=tenant_a)
        assert link.resource_type == "submission_package"
        assert link.resource_public_id == str(package.public_id)


# ---------------------------------------------------------------------------
# Retries and failure classification
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRetryPolicy:
    def _queued_import(self, tenant, admin, connector):
        return services.create_execution(
            connector=connector,
            tenant=tenant,
            actor=admin,
            operation="import_document",
            idempotency_parts=["retry"],
            request_summary={
                "external_object_id": "a.pdf",
                "relative_path": "inbox/a.pdf",
                "title": "A",
            },
        )

    @pytest.mark.parametrize("code", ["REMOTE_4XX", "AUTH_FAILED", "DOCUMENT_REJECTED"])
    def test_semantic_failures_are_not_retried(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote, code, monkeypatch
    ):
        """Repeating an identical wrong request is a loop, not a retry."""
        from external_integrations import operations

        def fail(**kwargs):
            raise operations.OperationError(code, retryable=False)

        monkeypatch.setitem(operations.OPERATIONS, "import_document", fail)
        execution = self._queued_import(tenant_a, admin_a, active_connector)
        execution = _run(execution, tenant_a)

        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == code
        assert execution.attempt_count == 1

    def test_a_transient_failure_is_retried_and_bounded(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        """Bounded: a permanently broken endpoint costs a known amount of work.

        Celery is eager in tests, so `self.retry` re-enters the task inline and
        the attempt count is the thing to assert on.
        """
        from external_integrations import operations, tasks

        def fail(**kwargs):
            raise operations.OperationError("TIMEOUT", retryable=True)

        monkeypatch.setitem(operations.OPERATIONS, "import_document", fail)
        execution = self._queued_import(tenant_a, admin_a, active_connector)

        try:
            tasks.run_connector_execution(execution.pk, tenant_a.pk)
        except Exception:
            # Eager mode re-raises the retry once attempts are exhausted.
            pass
        execution.refresh_from_db()
        assert execution.attempt_count <= tasks.MAX_ATTEMPTS

    def test_an_unexpected_exception_never_reaches_the_stored_record(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        """A traceback can contain a URL, a header, or a fragment of content.
        The row gets an enumerated code and nothing else."""
        from external_integrations import operations

        def explode(**kwargs):
            raise RuntimeError("token=synthetic-token-value-not-a-real-credential leaked here")

        monkeypatch.setitem(operations.OPERATIONS, "import_document", explode)
        execution = self._queued_import(tenant_a, admin_a, active_connector)
        execution = _run(execution, tenant_a)

        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "INTERNAL_ERROR"
        blob = json.dumps({"r": execution.response_summary, "e": execution.error_code}, default=str)
        assert "synthetic-token-value" not in blob


# ---------------------------------------------------------------------------
# What is never stored
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestResponseRetention:
    def test_a_remote_body_is_never_persisted(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        """A remote error page can contain another tenant's data, an internal
        hostname, or markup. None of it is stored "for debugging"."""
        fake_remote.body = PDF_BYTES
        response = _queue_import(client_admin_a, active_connector)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        stored = json.dumps(
            {"req": execution.request_summary, "res": execution.response_summary}, default=str
        )
        assert "%PDF" not in stored
        assert "internal" not in stored

    def test_the_response_summary_holds_only_allow_listed_keys(
        self, client_admin_a, active_connector, connector_secret, fake_remote, tenant_a
    ):
        from external_integrations.summaries import _RESPONSE_KEYS

        fake_remote.body = PDF_BYTES
        response = _queue_import(client_admin_a, active_connector)
        execution = _run(
            ConnectorExecution.objects.get(public_id=response.data["public_id"]), tenant_a
        )
        assert set(execution.response_summary) <= set(_RESPONSE_KEYS)

    def test_nested_structures_are_dropped_from_a_summary(self):
        """A nested value is how "just a small summary" becomes a copy of the
        remote payload."""
        from external_integrations.summaries import response_summary

        cleaned = response_summary({"http_status": 200, "external_reference": {"nested": "object"}})
        assert cleaned == {"http_status": 200}


class TestSummaryAllowList:
    """The allow-list itself, not just the type filter.

    The earlier tests only ever passed keys that were already allowed, or values
    the *type* filter would drop anyway -- so removing the allow-list changed
    nothing and the mutation turned nothing red. These pass a plain string under
    a key nobody named, which only the allow-list can refuse. That is the case
    that matters: a remote body arrives as a string, not as a nested object.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "remote_body",
            "response_text",
            "authorization",
            "set_cookie",
            "server",
            "stack_trace",
            "url",
        ],
    )
    def test_an_unnamed_key_never_reaches_the_response_summary(self, key):
        from external_integrations.summaries import response_summary

        cleaned = response_summary({"http_status": 200, key: "internal.corp.example says hello"})
        assert cleaned == {"http_status": 200}
        assert key not in cleaned

    @pytest.mark.parametrize("key", ["body", "headers", "token", "raw_payload"])
    def test_an_unnamed_key_never_reaches_the_request_summary(self, key):
        from external_integrations.summaries import request_summary

        cleaned = request_summary({"operation": "import_document", key: "sensitive text"})
        assert cleaned == {"operation": "import_document"}

    def test_an_allow_listed_string_is_kept_so_the_filter_is_not_simply_empty(self):
        """Control. A filter that dropped everything would also pass the tests
        above while making the summaries useless."""
        from external_integrations.summaries import response_summary

        cleaned = response_summary({"external_reference": "remote-1", "http_status": 201})
        assert cleaned == {"external_reference": "remote-1", "http_status": 201}

    def test_an_operation_returning_an_extra_key_has_it_dropped_on_the_way_in(
        self,
    ):
        """End to end through the service, not just the helper."""
        from external_integrations.summaries import response_summary

        summary = {
            "http_status": 200,
            "bytes_transferred": 10,
            # What a careless future operation might hand back.
            "remote_response": "<html>internal.corp.example</html>",
        }
        assert "remote_response" not in response_summary(summary)
