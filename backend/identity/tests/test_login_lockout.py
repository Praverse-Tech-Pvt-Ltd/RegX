"""Per-account password login lockout (identity/login_lockout.py)."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

LOGIN = "/api/regx/v1/auth/login/"
GOOD = "TestPass1234!"
BAD = "WrongPass9999!"


@pytest.fixture(autouse=True)
def _clean_cache():
    # Lockout state lives in the cache, which persists across tests in-process.
    cache.clear()
    yield
    cache.clear()


def _login(client, email, password):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


@pytest.mark.django_db
class TestLoginLockout:
    def test_twelve_wrong_attempts_are_blocked(self, api_client, user, settings):
        codes = [_login(api_client, user.email, BAD).status_code for _ in range(12)]
        threshold = settings.LOGIN_LOCKOUT_THRESHOLD
        assert codes[:threshold] == [status.HTTP_400_BAD_REQUEST] * threshold
        assert codes[threshold:] == [status.HTTP_429_TOO_MANY_REQUESTS] * (12 - threshold)

    def test_locked_response_has_retry_after(self, api_client, user, settings):
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD):
            _login(api_client, user.email, BAD)
        resp = _login(api_client, user.email, BAD)
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert 0 < int(resp["Retry-After"]) <= settings.LOGIN_LOCKOUT_SECONDS

    def test_correct_password_is_refused_while_locked(self, api_client, user, settings):
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD):
            _login(api_client, user.email, BAD)
        resp = _login(api_client, user.email, GOOD)
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "sessionid" not in resp.cookies

    def test_correct_password_succeeds_after_lockout_window(self, api_client, user, settings):
        start = timezone.now()
        with freeze_time(start):
            for _ in range(12):
                _login(api_client, user.email, BAD)
            assert _login(api_client, user.email, GOOD).status_code == 429
        with freeze_time(start + timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS + 1)):
            resp = _login(api_client, user.email, GOOD)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["email"] == user.email

    def test_success_resets_the_failure_count(self, api_client, user, settings):
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD - 1):
            _login(api_client, user.email, BAD)
        assert _login(api_client, user.email, GOOD).status_code == status.HTTP_200_OK
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD - 1):
            assert _login(api_client, user.email, BAD).status_code == 400

    def test_lock_is_per_account_and_case_insensitive(self, api_client, user, superuser, settings):
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD):
            _login(api_client, user.email.upper(), BAD)
        assert _login(api_client, user.email, GOOD).status_code == 429
        # Another account from the same client (the shared-IP case) is unaffected.
        assert _login(api_client, superuser.email, "AdminPass1234!").status_code == 200

    def test_unknown_email_locks_the_same_way(self, api_client, settings):
        # No difference between existing and unknown accounts: no enumeration.
        codes = [
            _login(api_client, "nobody@example.com", BAD).status_code
            for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD + 1)
        ]
        assert codes[-1] == status.HTTP_429_TOO_MANY_REQUESTS
