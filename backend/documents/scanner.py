"""
Malware scanning abstraction for the document platform.

States: pending, clean, infected, scan_failed, scanner_unavailable, quarantined

Rules:
- No content extraction before clean scan status.
- Infected files must be quarantined immediately.
- Users must not download quarantined content.
- Scanner failures must not silently mark files clean.
- All scan transitions must be audited via AuditEvent.

Backends:
- StubScanner — development/test only, clearly labeled, marks all files clean.
  Set DOCUMENT_SCANNER_BACKEND=stub (default).
- ClamAVScanner — connects to a running clamd socket.
  Set DOCUMENT_SCANNER_BACKEND=clamav, DOCUMENT_CLAMAV_HOST, DOCUMENT_CLAMAV_PORT.

WARNING: The stub scanner provides NO real malware protection.
         Production deployments MUST configure a real scanner backend.
"""

import abc
import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)


class ScanResult:
    CLEAN = "clean"
    INFECTED = "infected"
    SCAN_FAILED = "scan_failed"
    SCANNER_UNAVAILABLE = "scanner_unavailable"


@dataclass
class ScanOutcome:
    result: str
    detail: str = ""
    threat_name: str = ""


class ScannerBackend(abc.ABC):
    @abc.abstractmethod
    def scan(self, file_obj) -> ScanOutcome:
        """Scan file_obj and return a ScanOutcome."""


class StubScanner(ScannerBackend):
    """
    DEVELOPMENT/TEST STUB — NOT FOR PRODUCTION USE.

    This scanner marks every file as clean without performing any real
    malware analysis. It exists solely to allow local development and
    automated tests to proceed without a running AV daemon.

    To enable real scanning, set DOCUMENT_SCANNER_BACKEND=clamav and
    configure a running ClamAV clamd service.
    """

    def scan(self, file_obj) -> ScanOutcome:
        logger.warning(
            "StubScanner: marking file as CLEAN without real scan. "
            "This is NOT safe for production. "
            "Set DOCUMENT_SCANNER_BACKEND=clamav for real scanning."
        )
        return ScanOutcome(result=ScanResult.CLEAN, detail="stub-clean")


class ClamAVScanner(ScannerBackend):
    """ClamAV clamd TCP adapter.

    Requires a running clamd instance at DOCUMENT_CLAMAV_HOST:DOCUMENT_CLAMAV_PORT.
    """

    def __init__(self):
        self.host = getattr(settings, "DOCUMENT_CLAMAV_HOST", "127.0.0.1")
        self.port = getattr(settings, "DOCUMENT_CLAMAV_PORT", 3310)

    def scan(self, file_obj) -> ScanOutcome:
        try:
            import socket

            file_obj.seek(0)
            data = file_obj.read()

            with socket.create_connection((self.host, self.port), timeout=30) as sock:
                sock.sendall(b"zINSTREAM\0")
                chunk_size = 4096
                offset = 0
                while offset < len(data):
                    chunk = data[offset : offset + chunk_size]
                    size_bytes = len(chunk).to_bytes(4, byteorder="big")
                    sock.sendall(size_bytes + chunk)
                    offset += chunk_size
                # Terminate stream
                sock.sendall(b"\x00\x00\x00\x00")
                response = b""
                while True:
                    part = sock.recv(4096)
                    if not part:
                        break
                    response += part

            response_str = response.decode("utf-8", errors="replace").strip()
            if "FOUND" in response_str:
                threat = response_str.split("FOUND")[0].split(":")[-1].strip()
                return ScanOutcome(result=ScanResult.INFECTED, threat_name=threat)
            if "OK" in response_str:
                return ScanOutcome(result=ScanResult.CLEAN)
            return ScanOutcome(result=ScanResult.SCAN_FAILED, detail=response_str[:200])

        except OSError as exc:
            logger.error("ClamAV connection failed: %s", exc)
            return ScanOutcome(result=ScanResult.SCANNER_UNAVAILABLE, detail=str(exc)[:200])
        except Exception as exc:
            logger.error("ClamAV scan error: %s", exc)
            return ScanOutcome(result=ScanResult.SCAN_FAILED, detail=str(exc)[:200])


def get_scanner_backend() -> ScannerBackend:
    backend = getattr(settings, "DOCUMENT_SCANNER_BACKEND", "stub")
    if backend == "stub":
        return StubScanner()
    if backend == "clamav":
        return ClamAVScanner()
    raise ValueError(f"Unknown scanner backend: {backend}")
