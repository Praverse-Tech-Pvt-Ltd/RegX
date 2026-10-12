"""The stub scanner announces itself once per process at startup."""

import logging

from django.apps import apps
from django.test import override_settings


def _ready_logs(caplog):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="documents.apps"):
        apps.get_app_config("documents").ready()
    return [r.getMessage() for r in caplog.records if r.name == "documents.apps"]


@override_settings(DOCUMENT_SCANNER_BACKEND="stub")
def test_stub_scanner_logs_a_startup_warning(caplog):
    messages = _ready_logs(caplog)
    assert len(messages) == 1
    assert "Malware scanning is DISABLED" in messages[0]


@override_settings(DOCUMENT_SCANNER_BACKEND="clamav")
def test_real_scanner_logs_nothing(caplog):
    assert _ready_logs(caplog) == []
