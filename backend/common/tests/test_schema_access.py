"""The API schema and Swagger UI require login in production only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

BACKEND = Path(__file__).resolve().parents[2]
REQUIRED = ["rest_framework.permissions.IsAuthenticated"]


def _settings_value(module: str) -> dict:
    # A separate interpreter: importing regx.settings.production here would
    # mutate the LOGGING dict this test process shares with every other test.
    env = {**os.environ, "DOCUMENT_SCANNER_ALLOW_STUB": "true"}
    code = (
        "import importlib, json; "
        f"m = importlib.import_module({module!r}); "
        "print(json.dumps(m.SPECTACULAR_SETTINGS.get('SERVE_PERMISSIONS')))"
    )
    # Fixed interpreter and fixed code; nothing here comes from user input.
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_production_serves_schema_only_to_signed_in_users():
    assert _settings_value("regx.settings.production") == REQUIRED


def test_development_keeps_schema_open():
    assert _settings_value("regx.settings.development") is None


def test_test_settings_keep_schema_open():
    assert "SERVE_PERMISSIONS" not in settings.SPECTACULAR_SETTINGS


@pytest.mark.django_db
def test_schema_is_anonymous_outside_production(api_client):
    resp = api_client.get("/api/schema/")
    assert resp.status_code == 200
    assert b"openapi" in resp.content
