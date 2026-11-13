"""MFA recovery: recovery codes at sign-in, and an audited admin reset.

A user who lost their authenticator signs in with the password, then a
single-use recovery code (shown once at enrolment, stored hashed) instead of
the TOTP code. If they have no codes left, a different administrator of their
organisation, who has MFA, resets their MFA; the reset is audited.
"""

from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient

from audit.models import AuditEvent
from authorization.models import MembershipRole, Role
from identity.models import MFADevice, RecoveryCode
from tenancy.models import TenantMembership

LOGIN = "/api/regx/v1/auth/login/"
LOGIN_MFA = "/api/regx/v1/auth/login/mfa/"
ENROL = "/api/regx/v1/mfa/enrol/"
VERIFY = "/api/regx/v1/mfa/verify/"
PASSWORD = "TestPass1234!"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def make_member(db, tenant, django_user_model):
    def _make(email, *role_names, member_of=None):
        user = django_user_model.objects.create_user(email=email, password=PASSWORD)
        membership = TenantMembership.objects.create(tenant=member_of or tenant, user=user)
        for name in role_names:
            MembershipRole.objects.create(
                membership=membership, role=Role.objects.get(name=name, tenant__isnull=True)
            )
        return user

    return _make


def _enrol(user):
    """Enrol through the real endpoints; return the 10 plaintext recovery codes."""
    client = APIClient()
    client.force_login(user)
    resp = client.post(ENROL)
    codes = resp.data["recovery_codes"]
    secret = parse_qs(urlparse(resp.data["totp_uri"]).query)["secret"][0]
    assert client.post(VERIFY, {"code": pyotp.TOTP(secret).now()}, format="json").status_code == 200
    return codes


def _password_step(email):
    client = APIClient()
    resp = client.post(LOGIN, {"email": email, "password": PASSWORD}, format="json")
    assert resp.data.get("mfa_pending") is True
    return client


@pytest.mark.django_db
class TestRecoveryCodeAtSignIn:
    def test_recovery_code_signs_in_once_and_is_audited(self, make_member):
        user = make_member("rv@rec.test", Role.BuiltIn.REVIEWER)
        codes = _enrol(user)
        client = _password_step(user.email)
        resp = client.post(LOGIN_MFA, {"recovery_code": codes[0]}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["email"] == user.email
        assert resp.data["recovery_codes_remaining"] == 9
        assert client.get("/api/regx/v1/auth/me/").status_code == 200
        event = AuditEvent.objects.get(event_type="identity.mfa.recovery_code_used")
        assert event.resource_id == str(user.public_id)
        assert event.payload == {"recovery_codes_remaining": 9}
        # The plaintext code is never stored or logged.
        assert codes[0] not in str(event.payload)
        assert not RecoveryCode.objects.filter(code_hash=codes[0]).exists()

    def test_a_used_code_cannot_be_used_again(self, make_member):
        user = make_member("rv2@rec.test", Role.BuiltIn.REVIEWER)
        codes = _enrol(user)
        _password_step(user.email).post(LOGIN_MFA, {"recovery_code": codes[0]}, format="json")
        client = _password_step(user.email)
        resp = client.post(LOGIN_MFA, {"recovery_code": codes[0]}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["error_code"] == "mfa_invalid_code"
        assert client.get("/api/regx/v1/auth/me/").status_code == 403

    def test_wrong_recovery_codes_count_toward_the_lockout(self, make_member):
        user = make_member("rv3@rec.test", Role.BuiltIn.REVIEWER)
        codes = _enrol(user)
        client = _password_step(user.email)
        for _ in range(5):
            client.post(LOGIN_MFA, {"recovery_code": "0" * 20}, format="json")
        resp = client.post(LOGIN_MFA, {"recovery_code": codes[1]}, format="json")
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert RecoveryCode.objects.filter(device__user=user, used_at__isnull=True).count() == 10

    def test_recovery_code_without_a_pending_sign_in_is_refused(self, make_member):
        user = make_member("rv4@rec.test", Role.BuiltIn.REVIEWER)
        codes = _enrol(user)
        resp = APIClient().post(LOGIN_MFA, {"recovery_code": codes[0]}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["error_code"] == "mfa_not_pending"

    def test_totp_code_still_works(self, make_member):
        user = make_member("rv5@rec.test", Role.BuiltIn.REVIEWER)
        _enrol(user)
        device = MFADevice.objects.get(user=user)
        device.last_used_counter = None
        device.save(update_fields=["last_used_counter"])
        client = _password_step(user.email)
        code = pyotp.TOTP(device.get_secret()).now()
        assert client.post(LOGIN_MFA, {"code": code}, format="json").status_code == 200


def _reset(caller, target, reason="Lost phone; identity confirmed by call"):
    client = APIClient()
    client.force_login(caller)
    return client.post(
        f"/api/regx/v1/permissions/users/{target.public_id}/mfa-reset/",
        {"reason": reason},
        format="json",
    )


@pytest.mark.django_db
class TestAdminReset:
    def test_a_different_admin_with_mfa_resets_and_it_is_audited(self, make_member, tenant):
        target = make_member("vp@reset.test", Role.BuiltIn.VP)
        _enrol(target)
        admin = make_member("admin@reset.test", Role.BuiltIn.TENANT_ADMIN)
        _enrol(admin)
        resp = _reset(admin, target)
        assert resp.status_code == status.HTTP_200_OK
        assert not MFADevice.objects.filter(user=target).exists()
        assert not RecoveryCode.objects.filter(device__user=target).exists()
        target.refresh_from_db()
        assert target.mfa_required is False
        event = AuditEvent.objects.get(event_type="identity.mfa.reset")
        assert event.resource_id == str(target.public_id)
        assert event.payload["by"] == str(admin.public_id)
        assert event.payload["reason"].startswith("Lost phone")
        assert event.tenant_id == tenant.pk
        # Next sign-in: password only, then the gate blocks writes until re-enrolment.
        resp = APIClient().post(LOGIN, {"email": target.email, "password": PASSWORD}, format="json")
        assert resp.data["email"] == target.email and "mfa_pending" not in resp.data

    def test_self_reset_is_refused(self, make_member):
        admin = make_member("self@reset.test", Role.BuiltIn.TENANT_ADMIN)
        _enrol(admin)
        resp = _reset(admin, admin)
        assert resp.status_code == 403
        assert resp.data["error_code"] == "mfa_reset_self_forbidden"
        assert MFADevice.objects.filter(user=admin).exists()

    def test_admin_without_mfa_is_refused(self, make_member):
        target = make_member("t1@reset.test", Role.BuiltIn.REVIEWER)
        _enrol(target)
        admin = make_member("nomfa@reset.test", Role.BuiltIn.TENANT_ADMIN)
        resp = _reset(admin, target)
        assert resp.status_code == 403
        assert MFADevice.objects.filter(user=target).exists()

    def test_non_admin_is_refused(self, make_member):
        target = make_member("t2@reset.test", Role.BuiltIn.REVIEWER)
        _enrol(target)
        peer = make_member("peer@reset.test", Role.BuiltIn.VP)
        _enrol(peer)
        resp = _reset(peer, target)
        assert resp.status_code == 403
        assert resp.data["error_code"] == "mfa_reset_forbidden"

    def test_admin_of_another_tenant_is_refused(self, make_member, django_user_model):
        from tenancy.models import Tenant

        other = Tenant.objects.create(name="Other Org", slug="other-org")
        target = make_member("t3@reset.test", Role.BuiltIn.REVIEWER)
        _enrol(target)
        outsider = make_member("outsider@reset.test", Role.BuiltIn.TENANT_ADMIN, member_of=other)
        _enrol(outsider)
        resp = _reset(outsider, target)
        assert resp.status_code == 403
        assert MFADevice.objects.filter(user=target).exists()

    def test_reason_is_required(self, make_member):
        target = make_member("t4@reset.test", Role.BuiltIn.REVIEWER)
        _enrol(target)
        admin = make_member("adm4@reset.test", Role.BuiltIn.TENANT_ADMIN)
        _enrol(admin)
        resp = _reset(admin, target, reason="short")
        assert resp.status_code == 400
        assert MFADevice.objects.filter(user=target).exists()

    def test_target_without_a_device(self, make_member):
        target = make_member("t5@reset.test", Role.BuiltIn.REVIEWER)
        admin = make_member("adm5@reset.test", Role.BuiltIn.TENANT_ADMIN)
        _enrol(admin)
        assert _reset(admin, target).status_code == 409
        assert not AuditEvent.objects.filter(event_type="identity.mfa.reset").exists()
