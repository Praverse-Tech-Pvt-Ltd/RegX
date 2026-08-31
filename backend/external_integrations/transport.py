"""The only code in RegX that makes an outbound request on a tenant's behalf.

Built on `http.client` rather than a request library, for one reason: this needs
to connect to **an address it has already checked**, while still presenting the
original hostname for TLS and `Host`. A convenience client resolves the name
again inside itself, which reopens the DNS-rebinding window `netpolicy` exists
to close. `HTTPSConnection` accepts a socket-level host and a separate
`server_hostname`, so the checked answer is the one actually used.

WHAT THIS REFUSES TO DO
-----------------------
* Follow a redirect. A 3xx is the destination nominating a new destination, and
  the destination does not get to choose. Redirects are reported as an
  enumerated failure, not followed and not silently treated as success.
* Read an unbounded body. Every read is capped and the cap is enforced while
  streaming, not checked afterwards from `Content-Length` -- a header is a
  claim, and a hostile endpoint can send more than it declares.
* Wait forever. Connect and read timeouts are always set.
* Return anything the remote said, verbatim. Callers get a status code, bounded
  bytes when they asked for bytes, and nothing else. A remote error body is
  attacker-influenced text; it is mapped to an enumerated code and dropped.

NO PROXIES
----------
No proxy support, and environment proxy variables are not consulted, because a
proxy is a destination that was never checked.
"""

from __future__ import annotations

import http.client
import logging
import ssl
import time

from .config_schema import validate_configuration
from .netpolicy import DestinationRefused, resolve_destination

logger = logging.getLogger("regx.external_integrations")

#: How much of a rejected response is read before the connection is dropped.
#: Enough to be polite about connection reuse, small enough to be free.
_DISCARD_CHUNK = 8192
_STREAM_CHUNK = 64 * 1024

#: Methods a connector may use. Read, create, replace. `DELETE` is absent
#: because this milestone performs no destructive remote operation at all;
#: `TRACE` and `CONNECT` because they exist to make a server do something other
#: than serve a resource.
ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT"})


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connects to a checked address, validates the certificate for the name.

    `HTTPSConnection` uses `self.host` for both the socket and TLS's
    `server_hostname`, so passing the address gives an unverifiable certificate
    and passing the name re-resolves it -- which is the rebinding window again.
    Splitting the two is the entire purpose of this subclass, and it is the
    reason this app does not use a higher-level HTTP client.
    """

    def __init__(self, *, address, hostname, port, timeout, context, blocksize):
        super().__init__(hostname, port=port, timeout=timeout, context=context, blocksize=blocksize)
        self._pinned_address = address

    def connect(self):
        self.sock = self._create_connection(
            (self._pinned_address, self.port), self.timeout, self.source_address
        )
        if getattr(self, "_tunnel_host", None):  # pragma: no cover - no proxy support
            raise TransportError(TransportErrorCode.CONNECTION_FAILED)
        # `self.host` is the hostname, so SNI and hostname verification both use
        # the name the certificate is for.
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class TransportError(Exception):
    """An outbound request failed, with a safe enumerated code.

    `retryable` is a property of the failure, not a policy: a timeout may be
    worth another attempt, a 403 never is. `tasks` decides what to do about it.
    """

    def __init__(self, code: str, *, retryable: bool = False, http_status: int | None = None):
        self.code = code
        self.retryable = retryable
        self.http_status = http_status
        super().__init__(code)


class TransportErrorCode:
    DNS_BLOCKED = "DNS_BLOCKED"
    DNS_UNRESOLVED = "DNS_UNRESOLVED"
    TLS_ERROR = "TLS_ERROR"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    REDIRECT_REFUSED = "REDIRECT_REFUSED"
    AUTH_FAILED = "AUTH_FAILED"
    REMOTE_4XX = "REMOTE_4XX"
    REMOTE_5XX = "REMOTE_5XX"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    METHOD_REJECTED = "METHOD_REJECTED"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"


class Response:
    """What a caller is allowed to know about a remote reply."""

    __slots__ = ("body", "external_reference", "latency_ms", "remote_checksum", "status")

    def __init__(self, *, status, body, latency_ms, external_reference="", remote_checksum=""):
        self.status = status
        self.body = body
        self.latency_ms = latency_ms
        self.external_reference = external_reference
        self.remote_checksum = remote_checksum


def _classify_status(status: int) -> None:
    if 200 <= status < 300:
        return
    if status in (301, 302, 303, 307, 308):
        raise TransportError(TransportErrorCode.REDIRECT_REFUSED, http_status=status)
    if status in (401, 403):
        raise TransportError(TransportErrorCode.AUTH_FAILED, http_status=status)
    if status == 429:
        # Rate limiting is the endpoint asking for another attempt later, which
        # is exactly what retryable means.
        raise TransportError(TransportErrorCode.REMOTE_4XX, retryable=True, http_status=status)
    if 400 <= status < 500:
        # A 4xx is the endpoint saying the request was wrong. Repeating an
        # identical wrong request is not a retry, it is a loop.
        raise TransportError(TransportErrorCode.REMOTE_4XX, http_status=status)
    if status in (502, 503, 504):
        raise TransportError(TransportErrorCode.REMOTE_5XX, retryable=True, http_status=status)
    raise TransportError(TransportErrorCode.REMOTE_5XX, http_status=status)


def _read_bounded(response, limit: int, sink=None) -> bytes:
    """Read at most `limit` bytes, refusing rather than truncating.

    Truncation would be worse than refusal: a document silently missing its last
    megabyte still hashes to something, gets stored, and looks fine.
    """
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = response.read(_STREAM_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise TransportError(TransportErrorCode.RESPONSE_TOO_LARGE)
        if sink is not None:
            sink.write(chunk)
        else:
            chunks.append(chunk)
    return b"" if sink is not None else b"".join(chunks)


def _safe_header(response, name: str, limit: int = 255) -> str:
    """One header, bounded and stripped of anything that is not printable.

    Remote headers are remote input. These two values reach the database, so
    they are cut to size and to a conservative character set here rather than
    trusted to be reasonable.
    """
    raw = response.getheader(name) or ""
    cleaned = "".join(ch for ch in raw if ch.isprintable())
    return cleaned[:limit]


def perform_request(
    *,
    connector,
    configuration: dict,
    method: str,
    url: str,
    headers: dict | None = None,
    body: bytes | None = None,
    body_stream=None,
    body_length: int | None = None,
    sink=None,
    max_response_bytes: int | None = None,
) -> Response:
    """Make one checked request. No redirects, bounded everything.

    `configuration` is re-validated here even though the service validated it on
    write. The row could have been changed by something that is not the service,
    and this is the last moment before bytes leave the process.
    """
    if method not in ALLOWED_METHODS:
        raise TransportError(TransportErrorCode.METHOD_REJECTED)

    config = validate_configuration(connector.connector_type, configuration)
    limit = max_response_bytes or config["max_response_bytes"]

    try:
        destination = resolve_destination(url)
    except DestinationRefused as exc:
        # The refusal code travels; the resolved address never does.
        raise TransportError(exc.code) from None

    context = ssl.create_default_context()
    # Belt and braces. `create_default_context` already does both, and a future
    # edit that weakens the default should have to weaken it here too.
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    request_headers = {str(k): str(v) for k, v in (config["static_headers"] or {}).items()}
    if headers:
        request_headers.update({str(k): str(v) for k, v in headers.items()})
    request_headers.setdefault("Host", destination.hostname)
    request_headers.setdefault("User-Agent", "RegX-Connector/1")
    request_headers["Accept-Encoding"] = "identity"

    if body is not None:
        request_headers["Content-Length"] = str(len(body))
    elif body_stream is not None and body_length is not None:
        request_headers["Content-Length"] = str(body_length)

    started = time.monotonic()
    # The socket goes to the address that was checked; TLS and the certificate
    # check still use the hostname.
    connection = _PinnedHTTPSConnection(
        address=destination.address,
        hostname=destination.hostname,
        port=destination.port,
        timeout=config["connect_timeout_seconds"],
        context=context,
        blocksize=_STREAM_CHUNK,
    )

    try:
        try:
            connection.connect()
            # The connect timeout got us a socket; reads get their own, longer
            # budget. Neither is ever unset.
            connection.sock.settimeout(config["read_timeout_seconds"])
        except ssl.SSLError as exc:
            raise TransportError(TransportErrorCode.TLS_ERROR) from exc
        except TimeoutError as exc:
            raise TransportError(TransportErrorCode.TIMEOUT, retryable=True) from exc
        except OSError as exc:
            raise TransportError(TransportErrorCode.CONNECTION_FAILED, retryable=True) from exc

        try:
            connection.putrequest(
                method, _request_target(url), skip_host=True, skip_accept_encoding=True
            )
            for name, value in request_headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            if body is not None:
                connection.send(body)
            elif body_stream is not None:
                while True:
                    chunk = body_stream.read(_STREAM_CHUNK)
                    if not chunk:
                        break
                    connection.send(chunk)

            response = connection.getresponse()
        except TimeoutError as exc:
            raise TransportError(TransportErrorCode.TIMEOUT, retryable=True) from exc
        except ssl.SSLError as exc:
            raise TransportError(TransportErrorCode.TLS_ERROR) from exc
        except OSError as exc:
            raise TransportError(TransportErrorCode.CONNECTION_FAILED, retryable=True) from exc

        status = response.status
        if status >= 300:
            # Read a little and throw it away. The body of a failure is the
            # part most likely to contain something hostile, and it is never
            # stored, logged or returned.
            try:
                response.read(_DISCARD_CHUNK)
            except OSError:  # pragma: no cover - draining must not mask the status
                logger.debug("discarding a failed response body did not complete")
            _classify_status(status)

        external_reference = _safe_header(response, "X-External-Id")
        remote_checksum = _safe_header(response, "X-Content-Sha256", limit=128)

        try:
            payload = _read_bounded(response, limit, sink=sink)
        except TimeoutError as exc:
            raise TransportError(TransportErrorCode.TIMEOUT, retryable=True) from exc
        except TransportError:
            raise
        except OSError as exc:
            raise TransportError(TransportErrorCode.CONNECTION_FAILED, retryable=True) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        return Response(
            status=status,
            body=payload,
            latency_ms=latency_ms,
            external_reference=external_reference,
            remote_checksum=remote_checksum,
        )
    finally:
        try:
            connection.close()
        except OSError:  # pragma: no cover - closing must never mask a result
            logger.debug("closing a connector connection did not complete cleanly")


def _request_target(url: str) -> str:
    """The origin-form path the request line carries.

    Absolute-form would let the path smuggle a different host past the socket
    that was already connected to a checked address.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return target
