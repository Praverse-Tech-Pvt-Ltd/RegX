"""MFA is enforced at login for users who enrolled (bug fix, not a policy change).

Before: `login_view` granted a full session from the password alone, even for a
user with a verified MFA device. Now the password step answers
`mfa_required: true` with no session, and `POST /auth/login/mfa/` grants the
session only for a valid TOTP code. Users without MFA are unchanged. Wrong
codes count toward the same per-account lockout as wrong passwords.
"""

from datetime import timedelta

import pyotp
import pytest
from django.core.cache import cache
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from identity.models import MFADevice

LOGIN = "/api/regx/v1/auth/login/"
LOGIN_MFA = "/api/regx/v1/auth/login/mfa/"
LOGOUT = "/api/regx/v1/auth/logout/"
ME = "/api/regx/v1/auth/me/"
GOOD = "TestPass1234!"
BAD = "WrongPass9999!"


@pytest.fixture(autouse=True)
def _clean_cache():
    # Lockout state lives in the cache, which persists across tests in-process.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def secret():
    return pyotp.random_base32()


@pytest.fixture
def enrolled(user, secret):
    device = MFADevice.objects.create(user=user, is_verified=True)
    device.set_secret(secret)
    device.save()
    user.mfa_required = True
    user.save(update_fields=["mfa_required"])
    return user


def _password(client, email, password=GOOD):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


def _code(client, code):
    return client.post(LOGIN_MFA, {"code": code}, format="json")


def _wrong(secret):
    return "000000" if pyotp.TOTP(secret).now() != "000000" else "111111"


def _has_session(client):
    return client.get(ME).status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestEnrolledUser:
    def test_password_alone_gives_no_session(self, api_client, enrolled):
        resp = _password(api_client, enrolled.email)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {"mfa_required": True, "mfa_pending": True, "email": enrolled.email}
        assert not _has_session(api_client)

    def test_password_then_valid_code_gives_session(self, api_client, enrolled, secret):
        _password(api_client, enrolled.email)
        resp = _code(api_client, pyotp.TOTP(secret).now())
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["email"] == enrolled.email
        assert resp.data["id"] == str(enrolled.public_id)
        me = api_client.get(ME)
        assert me.status_code == status.HTTP_200_OK
        assert me.data["email"] == enrolled.email

    def test_wrong_code_is_refused(self, api_client, enrolled, secret):
        _password(api_client, enrolled.email)
        resp = _code(api_client, _wrong(secret))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["error_code"] == "mfa_invalid_code"
        assert not _has_session(api_client)

    def test_malformed_code_is_refused(self, api_client, enrolled):
        _password(api_client, enrolled.email)
        resp = _code(api_client, "abc")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert not _has_session(api_client)

    def test_code_without_password_step_is_refused(self, api_client, enrolled, secret):
        resp = _code(api_client, pyotp.TOTP(secret).now())
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["error_code"] == "mfa_not_pending"
        assert not _has_session(api_client)

    def test_pending_login_expires(self, api_client, enrolled, secret):
        start = timezone.now()
        with freeze_time(start):
            _password(api_client, enrolled.email)
        with freeze_time(start + timedelta(minutes=6)):
            resp = _code(api_client, pyotp.TOTP(secret).now())
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["error_code"] == "mfa_not_pending"
        assert not _has_session(api_client)

    def test_a_used_code_cannot_be_replayed(self, api_client, enrolled, secret):
        code = pyotp.TOTP(secret).now()
        _password(api_client, enrolled.email)
        assert _code(api_client, code).status_code == status.HTTP_200_OK
        api_client.post(LOGOUT)
        _password(api_client, enrolled.email)
        resp = _code(api_client, code)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert not _has_session(api_client)

    def test_password_step_ends_an_existing_session(self, api_client, enrolled, secret):
        _password(api_client, enrolled.email)
        _code(api_client, pyotp.TOTP(secret).now())
        assert _has_session(api_client)
        _password(api_client, enrolled.email)
        assert not _has_session(api_client)

    def test_unverified_device_does_not_count_as_enrolled(self, api_client, user):
        """Enrolment started but never confirmed: the user has no working code."""
        device = MFADevice.objects.create(user=user, is_verified=False)
        device.set_secret(pyotp.random_base32())
        device.save()
        resp = _password(api_client, user.email)
        assert resp.data["email"] == user.email and "id" in resp.data
        assert _has_session(api_client)


@pytest.mark.django_db
class TestLockoutCoversBothSteps:
    def test_wrong_codes_lock_the_account(self, api_client, enrolled, secret, settings):
        _password(api_client, enrolled.email)
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD):
            assert _code(api_client, _wrong(secret)).status_code == 400
        # Locked: even the right code is refused, and so is the password step.
        resp = _code(api_client, pyotp.TOTP(secret).now())
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert not _has_session(api_client)
        assert _password(api_client, enrolled.email).status_code == 429

    def test_wrong_passwords_and_wrong_codes_add_up(self, api_client, enrolled, secret, settings):
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD - 2):
            _password(api_client, enrolled.email, BAD)
        _password(api_client, enrolled.email)  # right password: counter NOT cleared
        _code(api_client, _wrong(secret))
        _code(api_client, _wrong(secret))
        assert _password(api_client, enrolled.email).status_code == 429

    def test_right_password_does_not_reset_wrong_codes(
        self, api_client, enrolled, secret, settings
    ):
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD):
            _password(api_client, enrolled.email)
            _code(api_client, _wrong(secret))
        assert _code(api_client, pyotp.TOTP(secret).now()).status_code == 429

    def test_valid_code_clears_the_counter(self, api_client, enrolled, secret, settings):
        _password(api_client, enrolled.email)
        for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD - 1):
            _code(api_client, _wrong(secret))
        assert _code(api_client, pyotp.TOTP(secret).now()).status_code == 200
        api_client.post(LOGOUT)
        _password(api_client, enrolled.email)
        assert _code(api_client, _wrong(secret)).status_code == 400  # not 429


@pytest.mark.django_db
class TestUserWithoutMfaIsUnchanged:
    def test_password_gives_full_profile_and_session(self, api_client, user):
        resp = _password(api_client, user.email)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == str(user.public_id)
        assert resp.data["mfa_required"] is False
        assert "mfa_pending" not in resp.data
        assert _has_session(api_client)

    def test_login_mfa_endpoint_does_nothing_for_them(self, api_client, user):
        _password(api_client, user.email)
        api_client.post(LOGOUT)
        resp = _code(api_client, "123456")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["error_code"] == "mfa_not_pending"


@pytest.mark.django_db
class TestSharedCompanyLoginContract:
    """company_site's AdminMaster/regx_auth.py posts to /auth/login/ and, on a
    200, refuses the login when the body has `mfa_required` (it also needs
    `email`, or it treats the answer as an outage). REGX must not import
    company_site, so this pins the fields it reads; the live check exercises
    regx_auth itself."""

    def test_enrolled_user_gets_the_fields_regx_auth_refuses_on(self, api_client, enrolled):
        resp = _password(api_client, enrolled.email)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("email") == enrolled.email
        assert body.get("mfa_required") is True
        # The session regx_auth carries on to /permissions/mine/ is not a login.
        assert api_client.get("/api/regx/v1/permissions/mine/").status_code in (401, 403)
