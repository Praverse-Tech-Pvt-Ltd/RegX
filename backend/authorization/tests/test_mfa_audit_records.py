"""MFA changes are audited, in the same transaction as the change, with no secrets.

Before this change MFA setup (a new secret and 10 recovery codes), activation (verify)
and the standalone recovery-code endpoint changed MFA state with no audit record at all.
The admin reset was already audited inside its transaction; it is pinned here too.

Each record names who and what happened (counts only). It never contains the TOTP
secret, the provisioning URI, a recovery code or a one-time code: every test checks the
stored payload against the real values.

Same transaction: `audit.testing.audit_writes_fail()` (the helper from QA-09) makes the
audit INSERT fail in PostgreSQL; the MFA change must then roll back too.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from rest_framework.test import APIClient

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from authorization.models import Role
from identity.models import MFADevice, RecoveryCode

from .test_mfa_recovery import (  # noqa: F401
    ENROL,
    VERIFY,
    _clean_cache,
    _enrol,
    _reset,
    make_member,
)

RECOVERY = "/api/regx/v1/mfa/recovery/"


def _client(user):
    c = APIClient()
    c.force_login(user)
    return c


def _secret(totp_uri):
    return parse_qs(urlparse(totp_uri).query)["secret"][0]


def _assert_no_secrets(event, *secrets):
    text = json.dumps(event.payload) + event.resource_id + event.resource_type
    for s in secrets:
        assert s and s not in text, "a secret or code reached the audit record"
    assert "otpauth" not in text


def _events(name, user):
    return AuditEvent.objects.filter(event_type=name, resource_id=str(user.public_id))


# --------------------------------------------------------------- records exist, no secrets


@pytest.mark.django_db
class TestMfaChangesAreAudited:
    def test_setup_is_audited_without_the_secret_or_codes(self, make_member):  # noqa: F811
        user = make_member("setup@mfa-audit.test", Role.BuiltIn.DOER)
        resp = _client(user).post(ENROL)
        assert resp.status_code == 200
        events = _events("identity.mfa.enrolment_started", user)
        assert events.count() == 1
        event = events.get()
        assert event.actor_id == user.pk
        assert event.payload == {"recovery_codes_issued": 10}
        _assert_no_secrets(event, _secret(resp.data["totp_uri"]), *resp.data["recovery_codes"])

    def test_activation_is_audited_without_the_code(self, make_member):  # noqa: F811
        user = make_member("verify@mfa-audit.test", Role.BuiltIn.DOER)
        client = _client(user)
        resp = client.post(ENROL)
        secret = _secret(resp.data["totp_uri"])
        code = pyotp.TOTP(secret).now()
        assert client.post(VERIFY, {"code": code}, format="json").status_code == 200
        event = _events("identity.mfa.activated", user).get()
        assert event.actor_id == user.pk
        assert event.payload == {"mfa_required": True}
        _assert_no_secrets(event, secret, code, *resp.data["recovery_codes"])

    def test_recovery_code_use_is_audited_without_the_code(self, make_member):  # noqa: F811
        user = make_member("recovery@mfa-audit.test", Role.BuiltIn.DOER)
        codes = _enrol(user)
        resp = _client(user).post(RECOVERY, {"recovery_code": codes[0]}, format="json")
        assert resp.status_code == 200
        event = _events("identity.mfa.recovery_code_used", user).get()
        assert event.payload == {"recovery_codes_remaining": 9, "via": "mfa_recovery_endpoint"}
        _assert_no_secrets(event, *codes)

    def test_admin_reset_is_audited_without_secrets(self, make_member):  # noqa: F811
        """Guard: already true before this change."""
        target = make_member("target@mfa-audit.test", Role.BuiltIn.VP)
        codes = _enrol(target)
        admin = make_member("admin@mfa-audit.test", Role.BuiltIn.TENANT_ADMIN)
        _enrol(admin)
        assert _reset(admin, target).status_code == 200
        event = _events("identity.mfa.reset", target).get()
        _assert_no_secrets(event, *codes)


# --------------------------------------------------------------- refused changes: no record


@pytest.mark.django_db
class TestRefusedChangesWriteNoRecord:
    def test_a_wrong_code_activates_nothing_and_records_no_activation(self, make_member):  # noqa: F811
        user = make_member("wrong@mfa-audit.test", Role.BuiltIn.DOER)
        client = _client(user)
        client.post(ENROL)
        assert client.post(VERIFY, {"code": "000000"}, format="json").status_code == 400
        assert not _events("identity.mfa.activated", user).exists()

    def test_setup_refused_when_active_records_nothing_new(self, make_member):  # noqa: F811
        user = make_member("again@mfa-audit.test", Role.BuiltIn.DOER)
        _enrol(user)
        before = _events("identity.mfa.enrolment_started", user).count()
        assert _client(user).post(ENROL).status_code == 409
        assert _events("identity.mfa.enrolment_started", user).count() == before

    def test_a_used_recovery_code_records_nothing(self, make_member):  # noqa: F811
        user = make_member("used@mfa-audit.test", Role.BuiltIn.DOER)
        codes = _enrol(user)
        client = _client(user)
        client.post(RECOVERY, {"recovery_code": codes[0]}, format="json")
        assert client.post(RECOVERY, {"recovery_code": codes[0]}, format="json").status_code == 400
        assert _events("identity.mfa.recovery_code_used", user).count() == 1


# --------------------------------------------------------------- same transaction


@pytest.mark.django_db(transaction=True)
class TestAFailedAuditWriteRollsTheChangeBack:
    def test_setup(self, make_member):  # noqa: F811
        user = make_member("tx-setup@mfa-audit.test", Role.BuiltIn.DOER)
        with audit_writes_fail():
            attempt(_client(user).post, ENROL)
        assert not MFADevice.objects.filter(user=user).exists()
        assert not RecoveryCode.objects.filter(device__user=user).exists()

    def test_activation(self, make_member):  # noqa: F811
        user = make_member("tx-verify@mfa-audit.test", Role.BuiltIn.DOER)
        client = _client(user)
        secret = _secret(client.post(ENROL).data["totp_uri"])
        with audit_writes_fail():
            attempt(client.post, VERIFY, {"code": pyotp.TOTP(secret).now()}, format="json")
        user.refresh_from_db()
        assert MFADevice.objects.get(user=user).is_verified is False
        assert user.mfa_required is False

    def test_recovery_code_use(self, make_member):  # noqa: F811
        user = make_member("tx-recovery@mfa-audit.test", Role.BuiltIn.DOER)
        codes = _enrol(user)
        with audit_writes_fail():
            attempt(_client(user).post, RECOVERY, {"recovery_code": codes[0]}, format="json")
        assert RecoveryCode.objects.filter(device__user=user, used_at__isnull=True).count() == 10

    def test_admin_reset(self, make_member):  # noqa: F811
        """Guard: already true before this change."""
        target = make_member("tx-target@mfa-audit.test", Role.BuiltIn.VP)
        _enrol(target)
        admin = make_member("tx-admin@mfa-audit.test", Role.BuiltIn.TENANT_ADMIN)
        _enrol(admin)
        with audit_writes_fail():
            attempt(_reset, admin, target)
        assert MFADevice.objects.filter(user=target).exists()
