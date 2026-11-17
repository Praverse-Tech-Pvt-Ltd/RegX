"""Test-suite guard: refuse any socket connection to a non-local address.

Installed for the whole pytest session by `backend/conftest.py`. A test that
tries to reach the internet fails loudly instead of quietly depending on (or
sending data to) a real service.

"Local" means loopback, or a private network range the test harness's own
services live on (RFC 1918 IPv4, unique-local IPv6) -- Postgres and Redis run
in containers on such a network under compose and in CI. Link-local addresses
(including the cloud metadata address 169.254.169.254) and every public address
are refused. Unix sockets are always allowed. A host name is resolved and every
address it returns must be local.

The check runs before the real connect, so a refused connection sends nothing.
"""

from __future__ import annotations

import ipaddress
import socket

_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NonLocalConnectionBlocked(ConnectionRefusedError):
    """A test tried to open a connection to a non-local address."""


def is_local_ip(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return any(ip in net for net in _LOCAL_NETWORKS if net.version == ip.version)


def _host_is_local(host: str) -> bool:
    if is_local_ip(host):
        return True
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return False  # a literal address that is not local
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(is_local_ip(info[4][0]) for info in infos)


def _check(sock: socket.socket, address) -> None:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    host = address[0] if isinstance(address, tuple) else str(address)
    if not _host_is_local(host):
        raise NonLocalConnectionBlocked(f"test tried to connect to non-local address {host!r}")


def _guarded_connect(self, address):
    _check(self, address)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    _check(self, address)
    return _real_connect_ex(self, address)


def install() -> None:
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex


def uninstall() -> None:
    socket.socket.connect = _real_connect
    socket.socket.connect_ex = _real_connect_ex


def installed() -> bool:
    return socket.socket.connect is _guarded_connect
