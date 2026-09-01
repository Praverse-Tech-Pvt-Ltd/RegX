"""Tests for health and readiness endpoints."""

import json

import pytest
from django.db.utils import OperationalError


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


@pytest.mark.django_db
class TestReadinessDoesNotLeakDependencyInternals:
    """`readiness` is `AllowAny`.

    It previously returned `f"error: {e}"`, and a psycopg failure message names
    the host, the port and the database -- so an unauthenticated probe published
    internal topology, at exactly the moment something was already wrong.
    """

    def test_a_database_failure_reports_a_status_not_a_message(self, client, monkeypatch):
        from django.db import connection

        def boom():
            raise OperationalError(
                'connection to server at "db" (172.18.0.2), port 5432 failed: '
                'FATAL: password authentication failed for user "regx"'
            )

        monkeypatch.setattr(connection, "ensure_connection", boom)

        response = client.get("/api/regx/v1/readiness/")
        assert response.status_code == 503

        body = json.dumps(response.json())
        assert response.json()["checks"]["database"] == "unavailable"
        for secret in ("172.18.0.2", "5432", "password", 'regx\\"', "FATAL"):
            assert secret not in body, f"readiness leaked {secret!r}"

    def test_liveness_does_not_depend_on_the_database(self, client, monkeypatch):
        """A liveness probe that fails during a database outage asks the
        orchestrator to restart a process that has nothing wrong with it."""
        from django.db import connection

        def boom():
            raise OperationalError("down")

        monkeypatch.setattr(connection, "ensure_connection", boom)

        response = client.get("/api/regx/v1/health/")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readiness_says_it_is_not_a_worker_health_signal(self, client):
        response = client.get("/api/regx/v1/readiness/")
        assert "Celery worker health" in response.json()["note"]
