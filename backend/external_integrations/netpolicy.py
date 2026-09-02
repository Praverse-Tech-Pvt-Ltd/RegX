"""What this deployment is allowed to connect to.

This module is the whole security case for `GENERIC_HTTPS`. A connector lets an
authenticated tenant user cause the RegX server to make an outbound request, and
that is server-side request forgery unless every destination is proved
acceptable first. The server sits inside a private network and, on most cloud
providers, next to an unauthenticated metadata endpoint that hands out
credentials to anything that asks.

WHY TEXT VALIDATION IS NOT ENOUGH
---------------------------------
Checking that a URL *looks* public proves nothing: `evil.test` can resolve to
`169.254.169.254`. So the hostname is resolved here, every returned address is
classified, and the connection is then made **to a checked address**, not to the
name. If any answer in the resolver's response is prohibited, the whole
destination is refused -- picking the one public address out of a mixed answer
set would be choosing to lose the race rather than avoiding it.

There is still a residual TOCTOU window between this resolution and the socket
connect, because the standard HTTP client resolves the name again. `connect_to`
closes it by pinning the checked address: the socket goes to the literal IP and
the TLS handshake and `Host` header still carry the original hostname, so
certificate validation is unaffected. That is the difference between checking
DNS and *using* the DNS answer that was checked.

REDIRECTS
---------
Disabled. A redirect is the destination choosing a new destination, and the
whole point of this module is that the destination does not get to choose. See
`transport`.

THE DEFAULT IS THE PUBLIC INTERNET
----------------------------------
Private and internal destinations are refused. Not "warned about", not "allowed
with a flag a tenant can set" -- refused, because the caller is a tenant user
and the network is the deployment's. Allowing internal destinations would be an
owner-policy decision, and this milestone does not make owner-policy decisions.
"""

from __future__ import annotations

import ipaddress
import posixpath
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

#: The only scheme a connector may use. `http://` is absent deliberately: this
#: carries tenant documents and credentials, and there is no development-only
#: escape hatch, because an escape hatch that exists in the code exists in
#: production.
ALLOWED_SCHEMES = frozenset({"https"})

#: Refused outright. Not an exhaustive list of every scheme that has ever
#: existed -- the allow-list above is what actually decides -- but named so the
#: refusal is a specific, testable answer rather than a generic parse failure.
REJECTED_SCHEMES = frozenset(
    {"http", "file", "ftp", "ftps", "gopher", "data", "javascript", "ws", "wss", "unix", "ssh"}
)

DEFAULT_HTTPS_PORT = 443

#: Ports a connector may address. Restricting this is not about the protocol --
#: TLS is TLS on any port -- but about not turning the connector into a port
#: scanner that reports reachability of arbitrary services by timing.
ALLOWED_PORTS = frozenset({443, 8443})

MAX_URL_LENGTH = 2048
MAX_HOSTNAME_LENGTH = 253


class DestinationRefused(Exception):
    """A destination failed policy. Carries a safe, enumerated code.

    The message never contains the resolved address or anything else learned
    from the network: an error string is a side channel, and "which private
    address did it resolve to" is exactly the question this module exists to
    stop the caller answering.
    """

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(detail or code)


class ErrorCode:
    URL_INVALID = "URL_INVALID"
    SCHEME_REJECTED = "SCHEME_REJECTED"
    CREDENTIALS_IN_URL = "CREDENTIALS_IN_URL"
    PORT_REJECTED = "PORT_REJECTED"
    HOSTNAME_INVALID = "HOSTNAME_INVALID"
    DNS_UNRESOLVED = "DNS_UNRESOLVED"
    DNS_BLOCKED = "DNS_BLOCKED"
    PATH_REJECTED = "PATH_REJECTED"


@dataclass(frozen=True)
class Destination:
    """A destination that has been resolved and cleared.

    `address` is what the socket must actually connect to. `hostname` is what
    TLS and the `Host` header must still say. Keeping both is the point: one is
    the thing that was checked, the other is the thing the certificate is for.
    """

    url: str
    scheme: str
    hostname: str
    port: int
    address: str
    family: int


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Is this address on the public internet?

    Built from the properties the stdlib already tracks rather than a
    hand-written CIDR list, because a hand-written list is a list somebody has
    to remember to extend. `is_global` is False for private, loopback,
    link-local, multicast, reserved and unspecified ranges -- including
    169.254.169.254, which is link-local and therefore already covered before
    anyone thinks to name it.

    IPv4-mapped and 6to4-style IPv6 addresses are unwrapped first: `::ffff:127.0.0.1`
    is loopback wearing a different spelling, and `is_global` on the wrapper does
    not always say so.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    sixtofour = getattr(ip, "sixtofour", None)
    if sixtofour is not None:
        ip = sixtofour
    teredo = getattr(ip, "teredo", None)
    if teredo is not None:
        # (server, client) -- the server address is the one packets go to.
        ip = teredo[0]

    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return bool(ip.is_global)


def classify_address(raw: str) -> bool:
    """True when `raw` is a public address. Unparseable is not public."""
    try:
        return _is_public(ipaddress.ip_address(raw))
    except ValueError:
        return False


def _resolve(hostname: str, port: int) -> list[tuple[int, str]]:
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise DestinationRefused(
            ErrorCode.DNS_UNRESOLVED, "The host could not be resolved."
        ) from exc
    answers: list[tuple[int, str]] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if sockaddr and sockaddr[0]:
            answers.append((family, sockaddr[0]))
    if not answers:
        raise DestinationRefused(ErrorCode.DNS_UNRESOLVED, "The host could not be resolved.")
    return answers


def validate_url(url: str) -> tuple[str, str, int, str]:
    """Parse and check the *text* of a URL. Returns (scheme, host, port, path).

    Text-only. It proves nothing about where the name points, which is why no
    caller may stop here -- `resolve_destination` is the function that decides.
    """
    if not url or len(url) > MAX_URL_LENGTH:
        raise DestinationRefused(ErrorCode.URL_INVALID, "The URL is missing or too long.")
    if any(ch in url for ch in ("\n", "\r", "\t", "\x00", " ")):
        # Header injection and request smuggling both start here.
        raise DestinationRefused(ErrorCode.URL_INVALID, "The URL contains control characters.")

    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise DestinationRefused(ErrorCode.URL_INVALID, "The URL could not be parsed.") from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise DestinationRefused(
            ErrorCode.SCHEME_REJECTED, "Only https:// destinations are supported."
        )

    if parts.username or parts.password or "@" in (parts.netloc or ""):
        # https://user:pass@host/ puts a credential in every log line that ever
        # records the URL, and in the audit trail, and in the error message.
        raise DestinationRefused(
            ErrorCode.CREDENTIALS_IN_URL, "Credentials may not be embedded in a URL."
        )

    hostname = (parts.hostname or "").strip().rstrip(".").lower()
    if not hostname or len(hostname) > MAX_HOSTNAME_LENGTH:
        raise DestinationRefused(ErrorCode.HOSTNAME_INVALID, "The URL has no usable host.")

    try:
        port = parts.port if parts.port is not None else DEFAULT_HTTPS_PORT
    except ValueError as exc:
        raise DestinationRefused(ErrorCode.PORT_REJECTED, "The URL port is not valid.") from exc
    if port not in ALLOWED_PORTS:
        raise DestinationRefused(ErrorCode.PORT_REJECTED, "That port is not permitted.")

    # A hostname that is already a literal address is classified now, so
    # `https://127.0.0.1/` and `https://2130706433/` never reach the resolver.
    # Integer and hex spellings of an address are handled by the same call:
    # `ip_address` rejects them, and an unparseable host falls through to DNS,
    # where a name that does not exist fails and one that does gets checked.
    if not classify_address(hostname) and _looks_like_address(hostname):
        raise DestinationRefused(ErrorCode.DNS_BLOCKED, "That destination is not permitted.")

    return scheme, hostname, port, parts.path or "/"


def _looks_like_address(hostname: str) -> bool:
    """Is this text an attempt to write an address rather than a name?

    `ip_address` accepts only dotted-quad and standard IPv6, so `2130706433`
    (integer) and `0x7f000001` (hex) reach here as "names". They are not names:
    no resolver will return them as a hostname lookup, but some HTTP clients and
    many operating systems will happily interpret them as 127.0.0.1. Anything
    that is entirely digits, or looks like a hex literal, or parses as an
    address, is treated as an address -- and since it is not a *public* address
    (checked by the caller), it is refused.
    """
    stripped = hostname.strip("[]")
    try:
        ipaddress.ip_address(stripped)
        return True
    except ValueError:
        pass
    if stripped.isdigit():
        return True
    if stripped.startswith(("0x", "0X")):
        return True
    # Dotted forms with octal or hex components: 0177.0.0.1, 0x7f.0.0.1
    labels = stripped.split(".")
    if len(labels) == 4 and all(
        label and (label.isdigit() or label.lower().startswith("0x")) for label in labels
    ):
        return True
    return False


def resolve_destination(url: str) -> Destination:
    """Prove a destination is acceptable, and return the address to use.

    THE function. Text is checked, the name is resolved, **every** answer is
    classified, and the first public answer is pinned for the connection. One
    prohibited answer refuses the whole destination.
    """
    scheme, hostname, port, _path = validate_url(url)

    answers = _resolve(hostname, port)
    for _family, address in answers:
        if not classify_address(address):
            # Refused on the strength of any bad answer, not the absence of a
            # good one. A resolver that returns one public and one private
            # address is a rebinding attempt, and choosing the public one would
            # be agreeing to run the race.
            raise DestinationRefused(ErrorCode.DNS_BLOCKED, "That destination is not permitted.")

    family, address = answers[0]
    return Destination(
        url=url, scheme=scheme, hostname=hostname, port=port, address=address, family=family
    )


def normalize_path_prefix(prefix: str) -> str:
    """A configured prefix, in the one shape everything else compares against."""
    if not prefix:
        raise DestinationRefused(ErrorCode.PATH_REJECTED, "A path prefix is required.")
    if not prefix.startswith("/"):
        raise DestinationRefused(ErrorCode.PATH_REJECTED, "A path prefix must start with '/'.")
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    _assert_path_is_safe(prefix)
    return prefix


def _assert_path_is_safe(path: str) -> None:
    if any(ch in path for ch in ("\n", "\r", "\t", "\x00", " ", "\\")):
        raise DestinationRefused(ErrorCode.PATH_REJECTED, "The path contains illegal characters.")
    lowered = path.lower()
    # Percent-encoded traversal, and the double-encoded form that survives one
    # decode. Nothing here decodes the path -- the check is on the literal text,
    # so a sequence that *would* become `..` after the remote server decodes it
    # is refused before it is ever sent.
    for encoded in ("%2e", "%2f", "%5c", "%25"):
        if encoded in lowered:
            raise DestinationRefused(
                ErrorCode.PATH_REJECTED, "The path contains encoded separators."
            )
    if ".." in path.split("/"):
        raise DestinationRefused(ErrorCode.PATH_REJECTED, "The path contains a traversal segment.")


def build_url(*, base_url: str, allowed_path_prefix: str, relative_path: str) -> str:
    """Join an operation's path onto a connector's base, or refuse.

    The relative path comes from an execution payload, so it is untrusted, and
    it may only ever *extend* the configured prefix. It can never replace the
    host: an absolute URL, a scheme-relative `//host/x` and a leading `/` are
    all refused rather than resolved, because `urljoin` would happily honour
    every one of them and send tenant data somewhere nobody configured.
    """
    prefix = normalize_path_prefix(allowed_path_prefix)
    scheme, hostname, port, _ = validate_url(base_url)

    if relative_path is None:
        relative_path = ""
    if relative_path.startswith("/") or "//" in relative_path or ":" in relative_path.split("/")[0]:
        raise DestinationRefused(
            ErrorCode.PATH_REJECTED, "The path must be relative to the connector's prefix."
        )
    _assert_path_is_safe(relative_path)

    full_path = prefix + relative_path.lstrip("/")
    # Re-checked after joining, so a prefix and a suffix that are each harmless
    # cannot combine into something that is not.
    _assert_path_is_safe(full_path)

    # Containment, checked on the RESOLVED path.
    #
    # `startswith` on the raw string would be a tautology -- the string was just
    # built by concatenating the prefix onto it -- and a guard that cannot fail
    # is not a guard. Resolving `.` and `..` first makes it a real check: it
    # fires if the traversal rejection above is ever weakened or bypassed, which
    # is exactly the failure it exists to catch. `normpath` also collapses `//`
    # and a trailing `/.`, so the comparison is against a canonical form rather
    # than a spelling.
    #
    # The `/` is appended to the prefix before comparing so that `/regx-other/x`
    # cannot pass a `/regx/` prefix on a string match.
    root = prefix.rstrip("/")
    resolved = posixpath.normpath(full_path)
    if resolved != root and not resolved.startswith(root + "/"):
        raise DestinationRefused(
            ErrorCode.PATH_REJECTED, "The path escapes the connector's prefix."
        )

    netloc = hostname if port == DEFAULT_HTTPS_PORT else f"{hostname}:{port}"
    return f"{scheme}://{netloc}{full_path}"
