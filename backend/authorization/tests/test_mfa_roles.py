"""SOW 4.3: Reviewer, VP, Tenant Admin and Platform Support must enrol in MFA before they act.

The list is `settings.REGX_MFA_REQUIRED_ROLES`. A user holding one of those roles
with no verified MFA device may sign in and read, but every
state-changing API call outside `auth/` and `mfa/` is refused with 403
`mfa_enrolment_required` until they enrol. Other roles are unaffected.

These tests sign in with a real session (`force_login`), not
`force_authenticate`: the gate is a Django middleware and sees the session user,
exactly as in production where `SessionAuthentication` is the only scheme.
"""

from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from authorization.models import MembershipRole, Role
from identity.models import MFADevice
from tenancy.models import TenantMembership

WRITE = "/api/regx/v1/tenants/active/"  # an ordinary member POST; 200 when allowed
READ = "/api/regx/v1/tenants/"
STATUS = "/api/regx/v1/permissions/mfa-status/"
ENROL = "/api/regx/v1/mfa/enrol/"
VERIFY = "/api/regx/v1/mfa/verify/"
LOGIN = "/api/regx/v1/auth/login/"
LOGOUT = "/api/regx/v1/auth/logout/"
PASSWORD = "TestPass1234!"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def make_member(db, tenant, django_user_model):
    def _make(email, *role_names, active=True):
        user = django_user_model.objects.create_user(email=email, password=PASSWORD)
        membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=active)
        for name in role_names:
            MembershipRole.objects.create(
                membership=membership, role=Role.objects.get(name=name, is_system=True)
            )
        return user

    return _make


def _session(user):
    client = APIClient()
    client.force_login(user)
    return client


def _post_write(client, tenant):
    return client.post(WRITE, {"tenant_id": str(tenant.public_id)}, format="json")


def _enrol(client):
    resp = client.post(ENROL)
    assert resp.status_code == 200, resp.content
    secret = parse_qs(urlparse(resp.data["totp_uri"]).query)["secret"][0]
    resp = client.post(VERIFY, {"code": pyotp.TOTP(secret).now()}, format="json")
    assert resp.status_code == 200, resp.content


GATED = [
    Role.BuiltIn.REVIEWER,
    Role.BuiltIn.VP,
    Role.BuiltIn.TENANT_ADMIN,
    Role.BuiltIn.PLATFORM_SUPPORT,
]


@pytest.mark.django_db
class TestGate:
    def test_the_setting_lists_the_gated_roles(self):
        assert set(settings.REGX_MFA_REQUIRED_ROLES) == {str(r) for r in GATED}

    @override_settings(REGX_MFA_REQUIRED_ROLES=("reviewer",))
    def test_changing_the_setting_changes_who_is_gated(self, make_member, tenant):
        """One line in settings decides; nothing else is hardcoded."""
        assert (
            _post_write(_session(make_member("vp1@mfa.test", Role.BuiltIn.VP)), tenant).status_code
            == 200
        )
        assert (
            _post_write(
                _session(make_member("rv1@mfa.test", Role.BuiltIn.REVIEWER)), tenant
            ).status_code
            == 403
        )

    @pytest.mark.parametrize("role", GATED)
    def test_unenrolled_gated_role_cannot_write(self, make_member, tenant, role):
        client = _session(make_member(f"{role}@mfa.test", role))
        resp = _post_write(client, tenant)
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json()["error_code"] == "mfa_enrolment_required"
        assert "/mfa/setup" in resp.json()["detail"]

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_every_unsafe_method_is_gated(self, make_member, method):
        client = _session(make_member("rv@mfa.test", Role.BuiltIn.REVIEWER))
        resp = getattr(client, method)(WRITE, {}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json()["error_code"] == "mfa_enrolment_required"

    @pytest.mark.parametrize("role", GATED)
    def test_unenrolled_gated_role_can_still_read(self, make_member, tenant, role):
        client = _session(make_member(f"{role}@mfa.test", role))
        resp = client.get(READ)
        assert resp.status_code == status.HTTP_200_OK
        assert [t["slug"] for t in resp.data] == [tenant.slug]

    @pytest.mark.parametrize("role", [Role.BuiltIn.DOER])
    def test_other_roles_are_not_gated(self, make_member, tenant, role):
        client = _session(make_member(f"{role}@mfa.test", role))
        resp = _post_write(client, tenant)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["slug"] == tenant.slug

    def test_user_with_no_role_is_not_gated(self, make_member, tenant):
        client = _session(make_member("plain@mfa.test"))
        assert _post_write(client, tenant).status_code == status.HTTP_200_OK

    def test_doer_who_is_also_reviewer_is_gated(self, make_member, tenant):
        """The rule is per account: holding Reviewer anywhere is enough."""
        client = _session(make_member("both@mfa.test", Role.BuiltIn.DOER, Role.BuiltIn.REVIEWER))
        assert _post_write(client, tenant).status_code == status.HTTP_403_FORBIDDEN

    def test_reviewer_role_in_an_inactive_membership_does_not_gate(self, make_member, tenant):
        client = _session(make_member("gone@mfa.test", Role.BuiltIn.REVIEWER, active=False))
        # No longer a member, so the view refuses the write; the gate does not.
        resp = _post_write(client, tenant)
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json().get("error_code") != "mfa_enrolment_required"

    def test_unfinished_enrolment_still_blocks(self, make_member, tenant):
        client = _session(make_member("half@mfa.test", Role.BuiltIn.VP))
        assert client.post(ENROL).status_code == 200  # device exists, not verified
        assert _post_write(client, tenant).status_code == status.HTTP_403_FORBIDDEN

    def test_enrolment_lifts_the_block_in_the_same_session(self, make_member, tenant):
        user = make_member("rv@mfa.test", Role.BuiltIn.REVIEWER)
        client = _session(user)
        assert _post_write(client, tenant).status_code == status.HTTP_403_FORBIDDEN
        _enrol(client)  # auth/ and mfa/ stay reachable while blocked
        assert MFADevice.objects.get(user=user).is_verified
        resp = _post_write(client, tenant)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["slug"] == tenant.slug

    def test_blocked_user_can_sign_in_and_out(self, make_member):
        make_member("rv@mfa.test", Role.BuiltIn.REVIEWER)
        client = APIClient()
        resp = client.post(LOGIN, {"email": "rv@mfa.test", "password": PASSWORD}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["email"] == "rv@mfa.test"  # a session, not mfa_pending
        assert client.post(LOGOUT).status_code == status.HTTP_204_NO_CONTENT

    def test_enrolled_reviewer_needs_the_code_at_next_sign_in(self, make_member):
        """After enrolment the existing two-step login applies (PR #96)."""
        client = _session(make_member("rv@mfa.test", Role.BuiltIn.REVIEWER))
        _enrol(client)
        resp = APIClient().post(
            LOGIN, {"email": "rv@mfa.test", "password": PASSWORD}, format="json"
        )
        assert resp.data == {"mfa_required": True, "mfa_pending": True, "email": "rv@mfa.test"}

    def test_anonymous_requests_are_left_to_the_views(self):
        resp = APIClient().post(WRITE, {}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json().get("error_code") != "mfa_enrolment_required"

    def test_session_is_the_only_authentication_scheme(self):
        """The gate reads the session user in middleware. A second DRF scheme
        (token, JWT) would authenticate inside the view and bypass it, so adding
        one must come with a change to the gate."""
        assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
            "rest_framework.authentication.SessionAuthentication"
        ]
        mw = settings.MIDDLEWARE
        assert mw.index("authorization.middleware.MFAEnrolmentMiddleware") > mw.index(
            "django.contrib.auth.middleware.AuthenticationMiddleware"
        )


@pytest.mark.django_db
class TestStatusEndpoint:
    def test_unenrolled_reviewer(self, make_member):
        client = _session(make_member("rv@mfa.test", Role.BuiltIn.REVIEWER))
        assert client.get(STATUS).data == {
            "mfa_enrolled": False,
            "holds_mfa_required_role": True,
            "mfa_enrolment_required": True,
        }

    def test_enrolled_vp(self, make_member):
        client = _session(make_member("vp@mfa.test", Role.BuiltIn.VP))
        _enrol(client)
        assert client.get(STATUS).data == {
            "mfa_enrolled": True,
            "holds_mfa_required_role": True,
            "mfa_enrolment_required": False,
        }

    def test_doer(self, make_member):
        client = _session(make_member("doer@mfa.test", Role.BuiltIn.DOER))
        assert client.get(STATUS).data["mfa_enrolment_required"] is False

    def test_anonymous_rejected(self):
        assert APIClient().get(STATUS).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPrivilegedRoles:
    @pytest.mark.parametrize("role", [Role.BuiltIn.TENANT_ADMIN, Role.BuiltIn.PLATFORM_SUPPORT])
    def test_enrolment_lifts_the_block_for_privileged_roles(self, make_member, tenant, role):
        client = _session(make_member(f"{role}-lift@mfa.test", role))
        assert _post_write(client, tenant).status_code == status.HTTP_403_FORBIDDEN
        _enrol(client)
        assert _post_write(client, tenant).status_code == status.HTTP_200_OK

    def test_status_endpoint_for_a_tenant_admin(self, make_member):
        client = _session(make_member("ta@mfa.test", Role.BuiltIn.TENANT_ADMIN))
        assert client.get(STATUS).data == {
            "mfa_enrolled": False,
            "holds_mfa_required_role": True,
            "mfa_enrolment_required": True,
        }

    def test_operator_commands_still_work_and_their_users_are_gated(self, monkeypatch):
        """The #107 operator commands run on the server, not through the API, so the
        gate never blocks them; the tenant admin they create must still enrol."""
        monkeypatch.setenv("NEW_ADMIN_PW", "Str0ng-Enough-Pass!")
        call_command("create_tenant", "--slug", "mfa-ops", "--name", "MFA Ops")
        call_command(
            "create_tenant_user", "--tenant", "mfa-ops", "--email", "admin@mfa-ops.test",
            "--role", "tenant_admin", "--password-env", "NEW_ADMIN_PW",
        )  # fmt: skip
        from tenancy.models import Tenant

        tenant = Tenant.objects.get(slug="mfa-ops")
        client = APIClient()
        resp = client.post(
            LOGIN, {"email": "admin@mfa-ops.test", "password": "Str0ng-Enough-Pass!"}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert _post_write(client, tenant).json()["error_code"] == "mfa_enrolment_required"
