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
