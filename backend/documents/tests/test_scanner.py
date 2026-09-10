"""Malware scanner abstraction tests."""

import io

import pytest

from documents.scanner import ScanResult, StubScanner


class TestStubScanner:
    def test_stub_returns_clean(self):
        scanner = StubScanner()
        f = io.BytesIO(b"any content")
        outcome = scanner.scan(f)
        assert outcome.result == ScanResult.CLEAN

    def test_stub_detail_identifies_as_stub(self):
        scanner = StubScanner()
        f = io.BytesIO(b"content")
        outcome = scanner.scan(f)
        assert "stub" in outcome.detail


class TestScannerBackendSelection:
    def test_get_scanner_returns_stub(self, settings):
        settings.DOCUMENT_SCANNER_BACKEND = "stub"
        from documents.scanner import get_scanner_backend

        scanner = get_scanner_backend()
        assert isinstance(scanner, StubScanner)

    def test_unknown_backend_raises(self, settings):
        settings.DOCUMENT_SCANNER_BACKEND = "nonexistent"
        from documents.scanner import get_scanner_backend

        with pytest.raises(ValueError):
            get_scanner_backend()


class _FakeSocket:
    """Stands in for a clamd TCP connection.

    Records what was written so the INSTREAM framing can be asserted, and
    replays a scripted response. The scanner uses `create_connection` as a
    context manager, so this implements the protocol rather than being a Mock:
    a Mock would let a framing regression pass silently.
    """

    def __init__(self, response: bytes):
        self._response = response
        self._sent = bytearray()
        self._served = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sendall(self, data):
        self._sent.extend(data)

    def recv(self, _size):
        if self._served:
            return b""
        self._served = True
        return self._response

    @property
    def sent(self) -> bytes:
        return bytes(self._sent)


def _patch_socket(monkeypatch, sock=None, error=None):
    """Point socket.create_connection at a fake, or make it raise."""
    import socket as socket_module

    def _create_connection(address, timeout=None):
        if error is not None:
            raise error
        return sock

    monkeypatch.setattr(socket_module, "create_connection", _create_connection)
    return sock


class TestClamAVScanner:
    """Direct coverage for the backend a production deployment actually uses.

    Before this, `ClamAVScanner` had no test of any kind: the only scanner
    covered was the stub, which is the one backend production must never run.
    """

    def _scanner(self, settings):
        settings.DOCUMENT_CLAMAV_HOST = "clamav.invalid"
        settings.DOCUMENT_CLAMAV_PORT = 3310
        from documents.scanner import ClamAVScanner

        return ClamAVScanner()

    def test_ok_response_is_clean(self, settings, monkeypatch):
        sock = _FakeSocket(b"stream: OK\0")
        _patch_socket(monkeypatch, sock=sock)
        outcome = self._scanner(settings).scan(io.BytesIO(b"harmless bytes"))
        assert outcome.result == ScanResult.CLEAN
        assert not outcome.threat_name

    def test_found_response_is_infected_and_names_threat(self, settings, monkeypatch):
        # The shape clamd returns for the EICAR test string.
        sock = _FakeSocket(b"stream: Eicar-Signature FOUND\0")
        _patch_socket(monkeypatch, sock=sock)
        outcome = self._scanner(settings).scan(io.BytesIO(b"eicar-like payload"))
        assert outcome.result == ScanResult.INFECTED
        assert outcome.threat_name == "Eicar-Signature"

    def test_infected_is_checked_before_clean(self, settings, monkeypatch):
        """A threat name containing "OK" must not be read as a clean result."""
        sock = _FakeSocket(b"stream: Trojan.OK-Variant FOUND\0")
        _patch_socket(monkeypatch, sock=sock)
        outcome = self._scanner(settings).scan(io.BytesIO(b"payload"))
        assert outcome.result == ScanResult.INFECTED

    def test_connection_refused_is_scanner_unavailable_not_clean(self, settings, monkeypatch):
        """The fail-closed case. This must never degrade to CLEAN."""
        _patch_socket(monkeypatch, error=ConnectionRefusedError("connection refused"))
        outcome = self._scanner(settings).scan(io.BytesIO(b"content"))
        assert outcome.result == ScanResult.SCANNER_UNAVAILABLE
        assert outcome.result != ScanResult.CLEAN

    def test_timeout_is_scanner_unavailable(self, settings, monkeypatch):
        # socket.timeout is an alias of TimeoutError, which is an OSError, so
        # the scanner's `except OSError` catches it -- same fail-closed path.
        _patch_socket(monkeypatch, error=TimeoutError("timed out"))
        outcome = self._scanner(settings).scan(io.BytesIO(b"content"))
        assert outcome.result == ScanResult.SCANNER_UNAVAILABLE

    def test_size_limit_response_is_scan_failed(self, settings, monkeypatch):
        sock = _FakeSocket(b"INSTREAM size limit exceeded. ERROR\0")
        _patch_socket(monkeypatch, sock=sock)
        outcome = self._scanner(settings).scan(io.BytesIO(b"x" * 32))
        assert outcome.result == ScanResult.SCAN_FAILED
        assert "size limit" in outcome.detail

    def test_unparseable_response_is_scan_failed(self, settings, monkeypatch):
        sock = _FakeSocket(b"\xff\xfe garbage")
        _patch_socket(monkeypatch, sock=sock)
        outcome = self._scanner(settings).scan(io.BytesIO(b"content"))
        assert outcome.result == ScanResult.SCAN_FAILED

    def test_empty_response_is_scan_failed(self, settings, monkeypatch):
        sock = _FakeSocket(b"")
        _patch_socket(monkeypatch, sock=sock)
        outcome = self._scanner(settings).scan(io.BytesIO(b"content"))
        assert outcome.result == ScanResult.SCAN_FAILED

    def test_instream_framing_is_wire_correct(self, settings, monkeypatch):
        """Guards the clamd wire protocol: zINSTREAM, length-prefixed chunks,
        then a zero-length terminator. Getting this wrong makes clamd hang or
        reject the stream, which surfaces as SCAN_FAILED in production."""
        payload = b"A" * 5000  # spans more than one 4096-byte chunk
        sock = _FakeSocket(b"stream: OK\0")
        _patch_socket(monkeypatch, sock=sock)
        self._scanner(settings).scan(io.BytesIO(payload))

        sent = sock.sent
        assert sent.startswith(b"zINSTREAM\0")
        assert sent.endswith(b"\x00\x00\x00\x00")
        body = sent[len(b"zINSTREAM\0") : -4]
        # First frame: 4-byte big-endian length, then that many bytes.
        first_len = int.from_bytes(body[:4], "big")
        assert first_len == 4096
        second_len = int.from_bytes(body[4 + 4096 : 4 + 4096 + 4], "big")
        assert second_len == len(payload) - 4096

    def test_file_is_read_from_start(self, settings, monkeypatch):
        """The scanner must seek(0); a consumed stream would scan zero bytes
        and clamd would answer OK on content nobody looked at."""
        sock = _FakeSocket(b"stream: OK\0")
        _patch_socket(monkeypatch, sock=sock)
        f = io.BytesIO(b"important content")
        f.read()  # leave the cursor at EOF
        self._scanner(settings).scan(f)
        body = sock.sent[len(b"zINSTREAM\0") : -4]
        assert int.from_bytes(body[:4], "big") == len(b"important content")


class TestClamAVBackendSelection:
    def test_get_scanner_returns_clamav(self, settings):
        settings.DOCUMENT_SCANNER_BACKEND = "clamav"
        from documents.scanner import ClamAVScanner, get_scanner_backend

        assert isinstance(get_scanner_backend(), ClamAVScanner)


class TestProductionRefusesStubScanner:
    """The production settings module must not import with the stub selected.

    This is the guard that keeps a deployment from reporting every upload
    CLEAN without inspecting it. It is asserted by importing the real module,
    because the failure has to happen at process start rather than at first
    upload.
    """

    def _load_production_settings(self, monkeypatch, env):
        import importlib

        for key, value in env.items():
            monkeypatch.setenv(key, value)
        # Enough of a production environment for the module to reach the guard.
        monkeypatch.setenv("DJANGO_SECRET_KEY", "test-only-not-a-real-secret")
        monkeypatch.setenv("MFA_ENCRYPTION_KEY", "dGVzdC1vbmx5LWZlcm5ldC1rZXktMzItYnl0ZXMh")
        # `production` gets DOCUMENT_SCANNER_BACKEND through `from .base import
        # *`, and reloading `production` alone re-imports a CACHED `base` still
        # holding the value read at first import. A real process imports base
        # once against the real environment, so reload base first to reproduce
        # that faithfully -- otherwise this asserts against a stale value.
        import regx.settings.base as base_settings
        import regx.settings.production as production

        importlib.reload(base_settings)
        return importlib.reload(production)

    def test_stub_without_optout_raises(self, monkeypatch):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured) as exc:
            self._load_production_settings(
                monkeypatch,
                {
                    "DOCUMENT_SCANNER_BACKEND": "stub",
                    "DOCUMENT_SCANNER_ALLOW_STUB": "false",
                },
            )
        assert "stub" in str(exc.value).lower()

    def test_stub_with_explicit_optout_is_allowed(self, monkeypatch):
        """The local compose stack and the CI compose job both run production
        settings, so the escape hatch has to work -- explicitly, never by
        default."""
        module = self._load_production_settings(
            monkeypatch,
            {
                "DOCUMENT_SCANNER_BACKEND": "stub",
                "DOCUMENT_SCANNER_ALLOW_STUB": "true",
            },
        )
        assert module.DOCUMENT_SCANNER_BACKEND == "stub"

    def test_clamav_needs_no_optout(self, monkeypatch):
        module = self._load_production_settings(
            monkeypatch,
            {
                "DOCUMENT_SCANNER_BACKEND": "clamav",
                "DOCUMENT_SCANNER_ALLOW_STUB": "false",
            },
        )
        assert module.DOCUMENT_SCANNER_BACKEND == "clamav"
