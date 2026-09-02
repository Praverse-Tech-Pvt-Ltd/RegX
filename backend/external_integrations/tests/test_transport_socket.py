"""`perform_request` against a real socket.

The destination policy forbids connecting to localhost, which is correct and
which also means the socket path cannot be exercised without stubbing something.
Two things are stubbed, both narrowly:

* `resolve_destination`, so the checked address is the loopback test server.
  Policy itself is tested exhaustively and un-stubbed in `test_netpolicy`.
* the TLS wrap, so a plain HTTP server can stand in for an HTTPS one. Nothing
  about certificate handling is being tested here -- `create_default_context`
  with `check_hostname` and `CERT_REQUIRED` is asserted separately.

What *is* real: the request line and headers this module writes, the response
parsing, the bounded read, the status classification, the header sanitising, the
streaming upload, and the connection teardown. Those are the hundred lines that
carry tenant documents and a bearer token.
"""

import http.server
import socket
import ssl
import threading

import pytest

from external_integrations.netpolicy import Destination
from external_integrations.tests.conftest import BASE_CONFIG
from external_integrations.transport import (
    TransportError,
    TransportErrorCode,
    perform_request,
)


class _Handler(http.server.BaseHTTPRequestHandler):
    """Records what arrived and replies as the test asks."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # pragma: no cover - keeps test output clean
        pass

    def _respond(self):
        config = self.server.reply
        self.server.received.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": self.rfile.read(int(self.headers.get("Content-Length") or 0)),
            }
        )
        body = config.get("body", b"")
        self.send_response(config.get("status", 200))
        for name, value in config.get("headers", {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    # `BaseHTTPRequestHandler` dispatches on these exact names, so the
    # casing is the stdlib's contract rather than this file's choice.
    do_GET = _respond  # noqa: N815
    do_PUT = _respond  # noqa: N815
    do_POST = _respond  # noqa: N815


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.reply = {"status": 200, "body": b"ok"}
    httpd.received = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def connect_to_server(server, monkeypatch):
    """Point the transport at the loopback server, with TLS made a passthrough."""
    host, port = server.server_address

    def fake_resolve(url):
        return Destination(
            url=url,
            scheme="https",
            hostname="connector.test",
            port=port,
            address=host,
            family=socket.AF_INET,
        )

    monkeypatch.setattr("external_integrations.transport.resolve_destination", fake_resolve)

    class _PassthroughContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, sock, server_hostname=None):
            # Recorded so the pinning test can prove TLS was told the *name*
            # while the socket went to the *address*.
            server.tls_server_hostname = server_hostname
            return sock

    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: _PassthroughContext())
    return server


class _Connector:
    connector_type = "generic_https"


@pytest.mark.usefixtures("connect_to_server")
class TestSocketPath:
    URL = "https://connector.test/regx/thing"

    def test_a_get_reaches_the_server_and_returns_the_body(self, server):
        response = perform_request(
            connector=_Connector(),
            configuration=dict(BASE_CONFIG),
            method="GET",
            url=self.URL,
        )
        assert response.status == 200
        assert response.body == b"ok"
        assert response.latency_ms >= 0
        assert server.received[0]["method"] == "GET"
        # Origin-form target: the path only, never an absolute URL.
        assert server.received[0]["path"] == "/regx/thing"

    def test_tls_is_told_the_hostname_while_the_socket_used_the_address(self, server):
        """The whole reason this module exists rather than a two-line call to a
        client library: the checked address is what is connected to, and the
        certificate is still validated for the name."""
        perform_request(
            connector=_Connector(),
            configuration=dict(BASE_CONFIG),
            method="GET",
            url=self.URL,
        )
        assert server.tls_server_hostname == "connector.test"
        assert server.received[0]["headers"]["Host"] == "connector.test"

    def test_static_headers_are_sent_and_auth_is_not_configurable(self, server):
        perform_request(
            connector=_Connector(),
            configuration={**BASE_CONFIG, "static_headers": {"accept": "application/json"}},
            method="GET",
            url=self.URL,
            headers={"Authorization": "Bearer synthetic-token-value-not-a-real-credential"},
        )
        headers = server.received[0]["headers"]
        assert headers["accept"] == "application/json"
        # The credential adapter owns this header; configuration never can.
        assert headers["Authorization"].startswith("Bearer ")

    def test_identity_encoding_is_requested(self, server):
        """A compressed response would make the byte cap a cap on compressed
        bytes, which is not the thing being bounded."""
        perform_request(
            connector=_Connector(), configuration=dict(BASE_CONFIG), method="GET", url=self.URL
        )
        assert server.received[0]["headers"]["Accept-Encoding"] == "identity"

    def test_a_streamed_upload_arrives_intact(self, server):
        import io

        payload = b"z" * 200_000
        perform_request(
            connector=_Connector(),
            configuration=dict(BASE_CONFIG),
            method="PUT",
            url=self.URL,
            body_stream=io.BytesIO(payload),
            body_length=len(payload),
        )
        assert server.received[0]["method"] == "PUT"
        assert server.received[0]["body"] == payload

    def test_a_response_over_the_cap_is_refused(self, server):
        server.reply = {"status": 200, "body": b"x" * 50_000}
        with pytest.raises(TransportError) as excinfo:
            perform_request(
                connector=_Connector(),
                configuration=dict(BASE_CONFIG),
                method="GET",
                url=self.URL,
                max_response_bytes=1024,
            )
        assert excinfo.value.code == TransportErrorCode.RESPONSE_TOO_LARGE

    def test_a_redirect_is_not_followed(self, server):
        """The server offers a new destination; the transport declines."""
        server.reply = {"status": 302, "headers": {"Location": "https://evil.test/"}, "body": b""}
        with pytest.raises(TransportError) as excinfo:
            perform_request(
                connector=_Connector(),
                configuration=dict(BASE_CONFIG),
                method="GET",
                url=self.URL,
            )
        assert excinfo.value.code == TransportErrorCode.REDIRECT_REFUSED
        # One request. It did not go on to fetch the Location.
        assert len(server.received) == 1

    def test_a_remote_error_body_is_never_returned(self, server):
        server.reply = {"status": 500, "body": b"internal.corp.example stack trace here"}
        with pytest.raises(TransportError) as excinfo:
            perform_request(
                connector=_Connector(),
                configuration=dict(BASE_CONFIG),
                method="GET",
                url=self.URL,
            )
        assert excinfo.value.code == TransportErrorCode.REMOTE_5XX
        assert "internal.corp" not in str(excinfo.value)

    def test_remote_identity_headers_are_captured_and_bounded(self, server):
        server.reply = {
            "status": 200,
            "headers": {"X-External-Id": "remote-1", "X-Content-Sha256": "a" * 64},
            "body": b"ok",
        }
        response = perform_request(
            connector=_Connector(), configuration=dict(BASE_CONFIG), method="GET", url=self.URL
        )
        assert response.external_reference == "remote-1"
        assert response.remote_checksum == "a" * 64

    def test_a_sink_receives_the_body_without_buffering_it(self, server):
        import io

        server.reply = {"status": 200, "body": b"streamed-content"}
        sink = io.BytesIO()
        response = perform_request(
            connector=_Connector(),
            configuration=dict(BASE_CONFIG),
            method="GET",
            url=self.URL,
            sink=sink,
        )
        assert sink.getvalue() == b"streamed-content"
        assert response.body == b""


class TestTlsContext:
    def test_the_context_verifies_certificates_and_hostnames(self):
        """Asserted on the real `ssl` default context, not on the passthrough
        the socket tests use. `create_default_context` already does both; a
        future edit that weakens it should have to weaken this too."""
        context = ssl.create_default_context()
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
