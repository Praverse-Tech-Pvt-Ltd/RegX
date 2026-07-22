"""Tests for identity API endpoints."""

import pytest
from rest_framework import status


@pytest.mark.django_db
class TestRegisterView:
    def test_register_creates_user(self, api_client):
        resp = api_client.post(
            "/api/regx/v1/auth/register/",
            {"email": "newuser@example.com", "password": "NewPass1234!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["email"] == "newuser@example.com"
        assert "id" in resp.data
        # Internal PK must never appear in response
        assert "pk" not in resp.data
        assert resp.data["id"] != 1  # UUID, not integer

    def test_duplicate_email_rejected(self, api_client, user):
        resp = api_client.post(
            "/api/regx/v1/auth/register/",
            {"email": user.email, "password": "AnotherPass1234!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_weak_password_rejected(self, api_client):
        resp = api_client.post(
            "/api/regx/v1/auth/register/",
            {"email": "weak@example.com", "password": "short"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


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
