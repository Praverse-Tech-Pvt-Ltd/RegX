"""Smoke tests for the company site: it starts, logins work, main pages render,
and nothing ever calls OpenAI.

Every test runs with outbound network blocked (``NetworkGuard``): any socket
connection to a non-loopback address fails the test. The shared REGX login is
exercised against a fake ``requests.Session``, never a real server. The FDA-483
spreadsheet is a temporary copy of the repository's fallback file, and every
file the cache refresh writes (snapshots, summary checkpoints) goes to a temp
directory, so no repository file or database is changed. The test database is
Django's in-memory SQLite database.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from AdminMaster.models import AssignChecker, CustomUser

REGX = "http://regx.test"
PASSWORD = "Smoke-test-only-1!"
FALLBACK_483 = (
    Path(settings.BASE_DIR) / "AIDatabase" / "management" / "commands"
    / "Final_File_FDA_Observations_15_12_2025.xlsx"
)
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


# --------------------------------------------------------------------------- network guard


class NetworkGuard:
    """Block every outbound connection that is not loopback, and record attempts.

    Patches socket.connect / connect_ex / create_connection and getaddrinfo, so
    the OpenAI SDK, requests and raw sockets are all covered."""

    def __init__(self):
        self.attempts: list[str] = []
        self._patches = []

    def _host(self, address):
        return address[0] if isinstance(address, tuple) else str(address)

    def _check(self, host):
        if str(host) not in LOOPBACK:
            self.attempts.append(str(host))
            raise OSError(f"NetworkGuard: outbound connection to {host!r} blocked in tests")

    def __enter__(self):
        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex
        real_getaddrinfo = socket.getaddrinfo
        guard = self

        def connect(sock, address):
            guard._check(guard._host(address))
            return real_connect(sock, address)

        def connect_ex(sock, address):
            guard._check(guard._host(address))
            return real_connect_ex(sock, address)

        def getaddrinfo(host, *args, **kwargs):
            guard._check(host)
            return real_getaddrinfo(host, *args, **kwargs)

        def create_connection(address, *args, **kwargs):
            guard._check(guard._host(address))
            raise OSError("NetworkGuard: create_connection is not used by these tests")

        for target, new in (
            ("socket.socket.connect", connect),
            ("socket.socket.connect_ex", connect_ex),
            ("socket.getaddrinfo", getaddrinfo),
            ("socket.create_connection", create_connection),
        ):
            p = mock.patch(target, new)
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


class GuardedTestCase(TestCase):
    """Base: network blocked, OPENAI_API_KEY absent everywhere, SERVER=LOCAL."""

    def setUp(self):
        super().setUp()
        self.assertFalse(os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY must be unset")
        self.assertFalse(getattr(settings, "OPENAI_API_KEY", None), "settings.OPENAI_API_KEY must be unset")
        self.guard = NetworkGuard().__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)
        env = mock.patch.dict(os.environ, {"SERVER": "LOCAL"})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.assertEqual(self.guard.attempts, [], f"outbound connections attempted: {self.guard.attempts}")
        super().tearDown()


# --------------------------------------------------------------------------- fake REGX


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeCookies(dict):
    def set(self, name, value):
        self[name] = value


class FakeRegx:
    """Stands in for requests.Session against the REGX auth API."""

    def __init__(self, login_status, login_body, roles=("doer",)):
        self.login_status = login_status
        self.login_body = login_body
        self.roles = list(roles)
        self.calls: list[tuple[str, str]] = []

    def session(self):
        fake = self

        class Session:
            def __init__(self):
                self.cookies = FakeCookies(csrftoken="fake-csrf")

            def get(self, url, timeout=None):
                fake.calls.append(("GET", url))
                if url.endswith("/auth/csrf/"):
                    return FakeResponse(200, {"csrfToken": "fake-csrf"})
                if url.endswith("/permissions/mine/"):
                    return FakeResponse(200, {"roles": fake.roles})
                return FakeResponse(404, {})

            def post(self, url, json=None, headers=None, timeout=None):
                fake.calls.append(("POST", url))
                if fake.login_status == 200:
                    self.cookies["sessionid"] = "fake-regx-session"
                return FakeResponse(fake.login_status, fake.login_body)

        return Session


def _login(client, username, password=PASSWORD):
    return client.post("/adminmaster/login/", {"username": username, "password": password})


# --------------------------------------------------------------------------- 1. the app starts


class AppStartsTests(GuardedTestCase):
    def test_system_checks_pass(self):
        call_command("check", verbosity=0)

    def test_health_route_renders(self):
        """The compose health check fetches /termsofuse/."""
        response = self.client.get("/termsofuse/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Terms of Use | iPharmaAI")

    def test_login_page_renders(self):
        response = self.client.get("/adminmaster/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iPharmaAI Login")


# --------------------------------------------------------------------------- 2. shared REGX login


@override_settings(REGX_AUTH_URL=REGX)
class SharedRegxLoginTests(GuardedTestCase):
    def _with_regx(self, fake):
        p = mock.patch("AdminMaster.regx_auth.requests.Session", fake.session())
        p.start()
        self.addCleanup(p.stop)

    def test_normal_user_is_signed_in_and_mirrored(self):
        fake = FakeRegx(200, {"email": "doer@smoke.invalid", "full_name": "Smoke Doer",
                              "is_active": True, "mfa_required": False}, roles=["doer"])
        self._with_regx(fake)
        response = _login(self.client, "doer@smoke.invalid")
        self.assertRedirects(response, "/ratools/", fetch_redirect_response=False)
        user = CustomUser.objects.get(username="doer@smoke.invalid")
        self.assertEqual(user.role, "company_user")
        self.assertFalse(user.has_usable_password())  # REGX is the only password check
        self.assertTrue(AssignChecker.objects.filter(user=user).exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertIn(("POST", f"{REGX}/api/regx/v1/auth/login/"), fake.calls)

    def test_mfa_enrolled_user_is_refused(self):
        """REGX answers the password step of an MFA-enrolled user with
        mfa_required (PR #96); the company login must not open a session."""
        fake = FakeRegx(200, {"mfa_required": True, "mfa_pending": True,
                              "email": "vp@smoke.invalid"})
        self._with_regx(fake)
        response = _login(self.client, "vp@smoke.invalid")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid Credential")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(CustomUser.objects.filter(username="vp@smoke.invalid").exists())

    def test_wrong_password_is_refused(self):
        self._with_regx(FakeRegx(400, {"detail": "Invalid credentials."}))
        response = _login(self.client, "doer@smoke.invalid", "wrong")
        self.assertContains(response, "Invalid Credential")
        self.assertNotIn("_auth_user_id", self.client.session)


# --------------------------------------------------------------------------- 3. local fallback


@override_settings(REGX_AUTH_URL="")
class LocalFallbackLoginTests(GuardedTestCase):
    def setUp(self):
        super().setUp()
        self.user = CustomUser.objects.create_user(
            username="local@smoke.invalid", email="local@smoke.invalid",
            password=PASSWORD, role="company_user",
        )
        session = mock.patch("AdminMaster.regx_auth.requests.Session")
        self.session_mock = session.start()
        self.addCleanup(session.stop)

    def test_local_password_works_without_regx(self):
        response = _login(self.client, "local@smoke.invalid")
        self.assertRedirects(response, "/ratools/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.session_mock.assert_not_called()  # blank REGX_AUTH_URL: REGX never contacted

    def test_wrong_local_password_is_refused(self):
        response = _login(self.client, "local@smoke.invalid", "wrong")
        self.assertContains(response, "Invalid Credential")
        self.assertNotIn("_auth_user_id", self.client.session)


# --------------------------------------------------------------------------- 4/5. pages + no OpenAI


class Form483DataMixin:
    """Point the FDA-483 cache at a temp copy of the fallback spreadsheet and send
    every file the refresh writes to a temp directory."""

    def setUp(self):
        super().setUp()
        from AIDatabase import observation_summary, views

        self.tmp = Path(tempfile.mkdtemp(prefix="cs-smoke-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.xlsx = self.tmp / "observations.xlsx"
        shutil.copy2(FALLBACK_483, self.xlsx)
        self.xlsx_bytes = self.xlsx.read_bytes()

        source = {"path": str(self.xlsx), "source_key": "smoke:observations", "active_id": None}
        for target, new in (
            ("AIDatabase.views.get_active_excel_source", lambda: dict(source)),
            ("AIDatabase.views._get_excel_snapshot_path",
             lambda key: str(self.tmp / f"{key}.pkl")),
        ):
            p = mock.patch(target, new)
            p.start()
            self.addCleanup(p.stop)
        mock.patch.object(observation_summary, "SUMMARY_CHECKPOINT_DIR", str(self.tmp)).start()
        self.addCleanup(mock.patch.stopall)
        # Fresh module caches, as for a cold process.
        for entry in views.EXCEL_DF_CACHE.values():
            entry.update({"path": None, "source_key": None, "df": None})
        observation_summary._openai_client = None
        observation_summary._openai_client_initialized = False


class MainPagesTests(Form483DataMixin, GuardedTestCase):
    def setUp(self):
        super().setUp()
        self.user = CustomUser.objects.create_user(
            username="admin@smoke.invalid", email="admin@smoke.invalid",
            password=PASSWORD, role="admin", first_name="Smoke",
        )
        AssignChecker.objects.create(user=self.user)
        self.client.force_login(self.user)

    def test_home(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RA-AI Tools | iTechnicalTools")

    def test_technical_tools(self):
        response = self.client.get("/ratools/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iPharmaAI | Technical Tools")

    def test_audit_iq(self):
        response = self.client.get("/aidatabase/auditiq/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AuditIQ - One Platform")

    def test_form483_dashboard(self):
        response = self.client.get("/aidatabase/form483/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RA-AI Tools")

    def test_admin_console(self):
        response = self.client.get("/adminmaster/adminbase")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RA-AI Tools")

    def test_pages_left_the_spreadsheet_untouched(self):
        for url in ("/", "/aidatabase/form483/"):
            self.client.get(url)
        self.assertEqual(self.xlsx.read_bytes(), self.xlsx_bytes)


class NoOpenAICallTests(Form483DataMixin, GuardedTestCase):
    """The pages that run the FDA-483 summariser must not reach OpenAI.

    The summariser path is really exercised (the client getter is called), it
    stops because no key is set, no SDK client is built, no completion is
    requested and no socket is opened."""

    def setUp(self):
        super().setUp()
        from AIDatabase import observation_summary

        self.os = observation_summary
        self.client_getter = mock.patch.object(
            observation_summary, "_get_openai_client",
            wraps=observation_summary._get_openai_client,
        ).start()
        self.sdk_client = mock.patch.object(
            observation_summary, "OpenAI",
            side_effect=AssertionError("OpenAI client constructed"),
        ).start()
        self.legacy = mock.patch.object(
            observation_summary.openai.ChatCompletion, "create",
            side_effect=AssertionError("legacy ChatCompletion called"),
            create=True,
        ).start()
        user = CustomUser.objects.create_user(
            username="user@smoke.invalid", email="user@smoke.invalid",
            password=PASSWORD, role="company_user",
        )
        AssignChecker.objects.create(user=user)
        self.client.force_login(user)

    def _blank_summaries(self):
        """Clear the Summary column in the temp copy so every block needs one."""
        import pandas as pd

        df = pd.read_excel(self.xlsx)
        df["Summary"] = None
        df.head(40).to_excel(self.xlsx, index=False, sheet_name="Sheet1")
        self.xlsx_bytes = self.xlsx.read_bytes()

    def test_home_and_dashboards_make_no_openai_call(self):
        self._blank_summaries()
        for url in ("/", "/aidatabase/form483/", "/aidatabase/auditiq/", "/aidatabase/gmpc_module/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
        self.assertTrue(self.client_getter.called, "summariser path was not exercised")
        self.sdk_client.assert_not_called()
        self.legacy.assert_not_called()
        self.assertEqual(self.guard.attempts, [])
        self.assertEqual(self.xlsx.read_bytes(), self.xlsx_bytes)  # no summaries written

    def test_summariser_without_key_generates_nothing(self):
        import pandas as pd

        df = pd.DataFrame({
            "Company Name": ["Smoke Co", "Smoke Co"],
            "Form 483 Observation": ["Observation 1", "Observation 2"],
            "Observation Details": ["Procedures were not followed. " * 20, "Records were missing. " * 20],
            "Summary": [None, None],
        })
        out = self.os.process_observation_summary(df)
        self.assertTrue(out["Summary"].isna().all())
        self.assertTrue(self.client_getter.called)
        self.sdk_client.assert_not_called()
        self.legacy.assert_not_called()

    def test_network_guard_really_blocks(self):
        """Proof the guard is armed: a direct attempt to reach api.openai.com fails."""
        with self.assertRaises(OSError):
            socket.getaddrinfo("api.openai.com", 443)
        self.assertEqual(self.guard.attempts, ["api.openai.com"])
        self.guard.attempts.clear()  # expected; tearDown checks for unexpected attempts only
