"""Tests for health and readiness endpoints."""

import pytest


@pytest.mark.django_db
class TestHealthEndpoints:
    def test_health(self, api_client):
        resp = api_client.get("/api/regx/v1/health/")
        assert resp.status_code == 200
        assert resp.data["status"] == "ok"

    def test_version(self, api_client):
        resp = api_client.get("/api/regx/v1/version/")
        assert resp.status_code == 200
        assert "version" in resp.data
        assert "environment" in resp.data

    def test_readiness_with_db(self, api_client):
        resp = api_client.get("/api/regx/v1/readiness/")
        # In test environment DB and cache may succeed or gracefully degrade
        assert resp.status_code in (200, 503)
        assert "checks" in resp.data
