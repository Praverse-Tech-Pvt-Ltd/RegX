"""Transport behaviour, the API surface, and query cost.

The transport tests exercise the real module. Where a socket would be needed,
the test drives the pieces that decide *whether* to open one -- status
classification, bounded reads, header sanitising, the request target -- because
those are where the policy lives. `perform_request` itself is proved to refuse
before connecting: a test that reached the network would be a test that could
fail because somebody's DNS was slow.
"""

import io
import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from external_integrations.tests.conftest import (
    BASE_CONFIG,
    EXECUTIONS_API,
    INTEGRATIONS_API,
    make_connector,
)
from external_integrations.transport import (
    ALLOWED_METHODS,
    TransportError,
    TransportErrorCode,
    _classify_status,
    _read_bounded,
    _request_target,
    perform_request,
)


class _FakeResponse:
    """Just enough of `http.client.HTTPResponse` for the bounded reader."""

    def __init__(self, payload: bytes, headers: dict | None = None, chunk: int = 4096):
        self._stream = io.BytesIO(payload)
        self._headers = headers or {}
        self._chunk = chunk

    def read(self, size=-1):
        return self._stream.read(size if size and size > 0 else self._chunk)

    def getheader(self, name, default=None):
        return self._headers.get(name, default)


# ---------------------------------------------------------------------------
# Transport policy
# ---------------------------------------------------------------------------
class TestStatusClassification:
    @pytest.mark.parametrize("status", [200, 201, 202, 204])
    def test_success_passes(self, status):
        assert _classify_status(status) is None

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_a_redirect_is_refused_not_followed(self, status):
        """A 3xx is the destination nominating a new destination. The whole
        point of the destination policy is that it does not get to choose."""
        with pytest.raises(TransportError) as excinfo:
            _classify_status(status)
        assert excinfo.value.code == TransportErrorCode.REDIRECT_REFUSED
        assert excinfo.value.retryable is False

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failures_are_not_retried(self, status):
        with pytest.raises(TransportError) as excinfo:
            _classify_status(status)
        assert excinfo.value.code == TransportErrorCode.AUTH_FAILED
        assert excinfo.value.retryable is False

    @pytest.mark.parametrize("status", [400, 404, 409, 422])
    def test_client_errors_are_not_retried(self, status):
        """Repeating an identical wrong request is a loop, not a retry."""
        with pytest.raises(TransportError) as excinfo:
            _classify_status(status)
        assert excinfo.value.retryable is False

    @pytest.mark.parametrize("status", [429, 502, 503, 504])
    def test_transient_failures_are_retryable(self, status):
        with pytest.raises(TransportError) as excinfo:
            _classify_status(status)
        assert excinfo.value.retryable is True

    def test_a_500_is_not_retried(self):
        """A generic server error is not evidence that a second identical
        request will do better; 502/503/504 are."""
        with pytest.raises(TransportError) as excinfo:
            _classify_status(500)
        assert excinfo.value.retryable is False


class TestBoundedReads:
    def test_content_within_the_limit_is_returned(self):
        assert _read_bounded(_FakeResponse(b"hello"), 1024) == b"hello"

    def test_content_over_the_limit_is_refused_not_truncated(self):
        """Truncation is worse than refusal: a document missing its last
        megabyte still hashes to something and looks fine."""
        with pytest.raises(TransportError) as excinfo:
            _read_bounded(_FakeResponse(b"x" * 5000, chunk=1000), 2000)
        assert excinfo.value.code == TransportErrorCode.RESPONSE_TOO_LARGE

    def test_the_limit_is_enforced_while_streaming_not_from_a_header(self):
        """A `Content-Length` is a claim. A hostile endpoint can send more."""
        response = _FakeResponse(b"y" * 100_000, headers={"Content-Length": "10"}, chunk=8192)
        with pytest.raises(TransportError):
            _read_bounded(response, 1024)

    def test_a_sink_receives_the_bytes_and_the_caller_does_not(self):
        sink = io.BytesIO()
        assert _read_bounded(_FakeResponse(b"streamed"), 1024, sink=sink) == b""
        assert sink.getvalue() == b"streamed"

    def test_an_oversized_stream_stops_writing_to_the_sink(self):
        sink = io.BytesIO()
        with pytest.raises(TransportError):
            _read_bounded(_FakeResponse(b"z" * 9000, chunk=1000), 2000, sink=sink)
        # It stopped; it did not write the whole thing and then complain.
        assert len(sink.getvalue()) <= 3000


class TestRequestShape:
    def test_the_request_target_is_origin_form(self):
        """Absolute-form would let the path smuggle a different host past a
        socket already connected to a checked address."""
        assert _request_target("https://host.test/regx/a.pdf") == "/regx/a.pdf"
        assert _request_target("https://host.test/regx/a?b=c") == "/regx/a?b=c"
        assert _request_target("https://host.test") == "/"

    def test_only_safe_methods_are_allowed(self):
        assert ALLOWED_METHODS == frozenset({"GET", "HEAD", "POST", "PUT"})
        for forbidden in ("DELETE", "TRACE", "CONNECT", "PATCH", "OPTIONS"):
            assert forbidden not in ALLOWED_METHODS

    def test_a_forbidden_method_is_refused_before_anything_else(self):
        with pytest.raises(TransportError) as excinfo:
            perform_request(
                connector=None, configuration={}, method="DELETE", url="https://public.test/"
            )
        assert excinfo.value.code == TransportErrorCode.METHOD_REJECTED

    def test_a_blocked_destination_is_refused_before_connecting(self, monkeypatch):
        """No socket. The refusal comes from policy, and the error carries a
        code rather than anything learned from the network."""
        import socket as socket_module

        def explode(*args, **kwargs):  # pragma: no cover - must not be reached
            raise AssertionError("a socket was opened for a blocked destination")

        monkeypatch.setattr(socket_module, "create_connection", explode)

        class _Connector:
            connector_type = "generic_https"

        # The configuration is valid -- a blocked base URL would be refused
        # earlier, by `config_schema`. What is under test here is the
        # destination check inside the transport itself.
        with pytest.raises(TransportError) as excinfo:
            perform_request(
                connector=_Connector(),
                configuration=dict(BASE_CONFIG),
                method="GET",
                url="https://169.254.169.254/latest/meta-data/",
            )
        assert excinfo.value.code == TransportErrorCode.DNS_BLOCKED

    def test_the_configuration_is_revalidated_at_request_time(self):
        """The row could have been written by something that is not the service.
        This is the last moment before bytes leave the process."""
        from external_integrations.config_schema import ConfigurationError

        class _Connector:
            connector_type = "generic_https"

        with pytest.raises(ConfigurationError):
            perform_request(
                connector=_Connector(),
                configuration={"base_url": "https://public.test/", "verify_tls": False},
                method="GET",
                url="https://public.test/x",
            )


class TestHeaderSanitising:
    def test_a_remote_header_is_bounded_and_printable(self):
        from external_integrations.transport import _safe_header

        response = _FakeResponse(b"", headers={"X-External-Id": "a" * 5000})
        assert len(_safe_header(response, "X-External-Id")) == 255

    def test_control_characters_are_stripped_from_a_remote_header(self):
        from external_integrations.transport import _safe_header

        response = _FakeResponse(b"", headers={"X-External-Id": "ok\r\nX-Evil: 1"})
        value = _safe_header(response, "X-External-Id")
        assert "\r" not in value and "\n" not in value

    def test_a_missing_header_is_empty_not_none(self):
        from external_integrations.transport import _safe_header

        assert _safe_header(_FakeResponse(b""), "X-Absent") == ""


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestApiSurface:
    def test_creating_a_connector_through_the_api(self, client_admin_a):
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/",
            {
                "name": "API connector",
                "connector_type": "generic_https",
                "configuration": BASE_CONFIG,
                "credential": {"credential_type": "bearer_token"},
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["status"] == "draft"
        assert response.data["configuration_version"] == 1

    def test_an_unsafe_configuration_is_rejected_with_a_code(self, client_admin_a):
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/",
            {
                "name": "Bad connector",
                "connector_type": "generic_https",
                "configuration": {**BASE_CONFIG, "base_url": "https://169.254.169.254/"},
            },
            format="json",
        )
        assert response.status_code == 400
        # The enumerated code travels inside the standard error envelope;
        # the offending value is never echoed back.
        detail = json.dumps(response.data, default=str)
        assert "CONFIG_" in detail
        assert "169.254.169.254" not in detail

    def test_no_database_id_is_ever_exposed(self, client_admin_a, tenant_a, admin_a):
        make_connector(tenant_a, admin_a)
        listing = client_admin_a.get(f"{INTEGRATIONS_API}/")
        body = json.dumps(listing.data, default=str)
        assert '"id"' not in body
        assert '"tenant_id"' not in body
        assert '"connector_id"' not in body

    def test_the_detail_endpoint_carries_advisory_permissions(
        self, client_admin_a, tenant_a, admin_a
    ):
        connector = make_connector(tenant_a, admin_a)
        response = client_admin_a.get(f"{INTEGRATIONS_API}/{connector.public_id}/")
        assert set(response.data["permissions"]) == {
            "can_edit",
            "can_enable",
            "can_test",
            "can_execute",
        }

    def test_an_archived_connector_leaves_the_list(self, client_admin_a, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        client_admin_a.post(f"{INTEGRATIONS_API}/{connector.public_id}/archive/")
        listing = client_admin_a.get(f"{INTEGRATIONS_API}/")
        assert listing.data["count"] == 0
        # Still readable by public id, because its executions still name it.
        assert client_admin_a.get(f"{INTEGRATIONS_API}/{connector.public_id}/").status_code == 200

    def test_a_queued_execution_can_be_cancelled(
        self, client_admin_a, tenant_a, admin_a, active_connector, connector_secret
    ):
        from external_integrations import services

        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["cancel"],
            request_summary={},
        )
        response = client_admin_a.post(f"{EXECUTIONS_API}/{execution.public_id}/cancel/")
        assert response.status_code == 200
        assert response.data["status"] == "cancelled"

    def test_a_finished_execution_cannot_be_cancelled(
        self, client_admin_a, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """Marking a transfer cancelled after it may already have sent bytes
        would make the record say something untrue."""
        from external_integrations import services
        from external_integrations.models import ExecutionStatus

        execution = services.create_execution(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            operation="import_document",
            idempotency_parts=["done"],
            request_summary={},
        )
        services.claim_execution(execution.pk)
        execution.refresh_from_db()
        services.finish_execution(execution=execution, status=ExecutionStatus.SUCCEEDED)

        response = client_admin_a.post(f"{EXECUTIONS_API}/{execution.public_id}/cancel/")
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# Query cost
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestQueryCost:
    """Bounded, not tiny. Compared across sizes rather than pinned, because an
    absolute number breaks on every harmless refactor and still would not catch
    the thing that matters."""

    def _connectors(self, tenant, actor, count, start=0):
        for i in range(start, count):
            make_connector(tenant, actor, name=f"Connector {i}")

    def test_the_connector_list_cost_does_not_grow_with_the_list(
        self, client_admin_a, tenant_a, admin_a
    ):
        self._connectors(tenant_a, admin_a, 10)
        with CaptureQueriesContext(connection) as small:
            client_admin_a.get(f"{INTEGRATIONS_API}/?page_size=100")

        self._connectors(tenant_a, admin_a, 60, start=10)
        with CaptureQueriesContext(connection) as large:
            client_admin_a.get(f"{INTEGRATIONS_API}/?page_size=100")

        assert len(large) == len(small), (
            f"connector list is N+1: {len(small)} queries for 10, {len(large)} for 60"
        )

    def test_the_execution_history_cost_does_not_grow_with_the_history(
        self, client_admin_a, tenant_a, admin_a, active_connector, connector_secret
    ):
        from external_integrations import services

        def grow(n, start=0):
            for i in range(start, n):
                services.create_execution(
                    connector=active_connector,
                    tenant=tenant_a,
                    actor=admin_a,
                    operation="import_document",
                    idempotency_parts=[f"exec-{i}"],
                    request_summary={},
                )

        url = f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/?page_size=100"
        grow(10)
        with CaptureQueriesContext(connection) as small:
            client_admin_a.get(url)

        grow(60, start=10)
        with CaptureQueriesContext(connection) as large:
            client_admin_a.get(url)

        assert len(large) == len(small), (
            f"execution history is N+1: {len(small)} queries for 10, {len(large)} for 60"
        )
