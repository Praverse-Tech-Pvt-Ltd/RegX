"""Tests for identity API endpoints."""

import pytest
from rest_framework import status


@pytest.mark.django_db
class TestLoginView:
    def test_valid_login_returns_user(self, api_client, user):
        resp = api_client.post(
            "/api/regx/v1/auth/login/",
            {"email": user.email, "password": "TestPass1234!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["email"] == user.email

    def test_wrong_password_rejected(self, api_client, user):
        resp = api_client.post(
            "/api/regx/v1/auth/login/",
            {"email": user.email, "password": "WrongPass9999!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestMeView:
    def test_authenticated_returns_user(self, auth_client, user):
        resp = auth_client.get("/api/regx/v1/auth/me/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["email"] == user.email

    def test_unauthenticated_rejected(self, api_client):
        resp = api_client.get("/api/regx/v1/auth/me/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCsrfView:
    def test_returns_csrf_token(self, api_client):
        resp = api_client.get("/api/regx/v1/auth/csrf/")
        assert resp.status_code == status.HTTP_200_OK
        assert "csrfToken" in resp.data
        assert isinstance(resp.data["csrfToken"], str)
        assert len(resp.data["csrfToken"]) > 0

    def test_unauthenticated_allowed(self, api_client):
        # CSRF endpoint must be public — frontend calls it before login
        resp = api_client.get("/api/regx/v1/auth/csrf/")
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestMfaEnrolView:
    def test_enrol_alias_works(self, auth_client):
        # /mfa/enrol/ is an alias for /mfa/setup/
        resp = auth_client.post("/api/regx/v1/mfa/enrol/")
        assert resp.status_code == status.HTTP_200_OK
        assert "totp_uri" in resp.data
        assert "recovery_codes" in resp.data
        assert len(resp.data["recovery_codes"]) == 10
