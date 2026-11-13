"""Smoke tests for the company site: it starts, logins work, main pages render,
and nothing ever calls OpenAI.

Every test runs with outbound network blocked (``NetworkGuard``): any socket
connection to a non-loopback address fails the test. The shared REGX login is
exercised against a fake ``requests.Session``, never a real server. The FDA-483
spreadsheet is a small synthetic workbook built in the test (the real one is
client data and git-ignored), and every
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

import requests
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from AdminMaster.models import AssignChecker, CustomUser

REGX = "http://regx.test"
PASSWORD = "Smoke-test-only-1!"
#: Column headers of the company's FDA-483 workbook (headers only; the real
#: workbook is client data, git-ignored, and not available in CI).
FORM483_COLUMNS = [
    "Sr. No.", "Company Name", "City, Country", "Type of establishment",
    "Month of Inspection", "FDA Investigator(s) name", "Year of Inspection",
    "System", "Form 483 Observation", "Observation Details", "Summary",
]


def build_synthetic_483(path: Path, *, summaries: bool) -> None:
    """A small, made-up FDA-483 workbook with the real column layout.

    Two observations per company, two detail rows per observation (one
    summariser block each), across several companies, systems and years. With
    `summaries=False` every block lacks a summary, so the summariser would try
    to generate each one."""
    import datetime

    import pandas as pd

    companies = [
        ("Example Pharma Ltd", "Mumbai, India", "API"),
        ("Sample Labs Inc", "Boston, United States", "Finished Dosage"),
        ("Demo Biologics GmbH", "Berlin, Germany", "Biologics"),
        ("Test Generics Pvt Ltd", "Hyderabad, India", "Finished Dosage"),
    ]
    systems = ["Quality System", "Laboratory Control System", "Production System",
               "Facilities and Equipment System"]
    rows, n = [], 0
    for c, (company, city, kind) in enumerate(companies):
        for o in range(2):
            for d in range(2):
                n += 1
                rows.append({
                    "Sr. No.": n,
                    "Company Name": company,
                    "City, Country": city,
                    "Type of establishment": kind,
                    "Month of Inspection": datetime.datetime(2020 + c, 1 + o, 15),
                    "FDA Investigator(s) name": f"Investigator {c + 1}",
                    "Year of Inspection": 2020 + c,
                    "System": systems[(c + o) % len(systems)],
                    "Form 483 Observation": f"Observation {o + 1}",
                    "Observation Details": (
                        f"Made-up detail {d + 1} for test company {c + 1}: written procedures "
                        "were not followed and records were incomplete. " * 4
                    ),
                    "Summary": None if not summaries else f"Made-up summary {c}-{o}",
                })
    pd.DataFrame(rows, columns=FORM483_COLUMNS).to_excel(path, index=False, sheet_name="Sheet1")
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
    def __init__(self, status_code, payload, cookies=None):
        self.status_code = status_code
        self._payload = payload
        self.cookies = cookies or {}
        self.headers = {}

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


class FakeRegxMfa:
    """REGX for an MFA-enrolled account: password step answers mfa_pending; the
    code step accepts GOOD_CODE once, counts every refusal (as REGX's lockout
    does) and answers 429 once `lock_after` refusals are reached."""

    GOOD_CODE = "123456"
    GOOD_RECOVERY = "0123456789abcdef0123"

    def __init__(self, roles=("vp",), lock_after=5, pending=True):
        self.roles = list(roles)
        self.lock_after = lock_after
        self.pending = pending
        self.failures = 0
        self.calls: list[tuple[str, str, dict]] = []

    def session(self):
        fake = self

        class Session:
            def __init__(self):
                # A real jar: like REGX, responses set cookies scoped to the REGX
                # host, so a cookie set by hand and one from a response can share
                # a name. This is what broke the first live run (500).
                self.cookies = requests.cookies.RequestsCookieJar()
                self.cookies.set("csrftoken", "fake-csrf", domain="regx.test")

            def _snapshot(self):
                return {c.name: c.value for c in self.cookies}

            def get(self, url, timeout=None):
                fake.calls.append(("GET", url, {}))
                if url.endswith("/permissions/mine/") and len([c for c in self.cookies if c.name == "sessionid"]) != 1:
                    raise AssertionError("ambiguous sessionid cookies sent to REGX")
                if url.endswith("/auth/csrf/"):
                    return FakeResponse(200, {"csrfToken": "fake-csrf"})
                if url.endswith("/permissions/mine/"):
                    return FakeResponse(200, {"roles": fake.roles})
                return FakeResponse(404, {})

            def post(self, url, json=None, headers=None, timeout=None):
                fake.calls.append(("POST", url, self._snapshot()))
                if url.endswith("/auth/login/"):
                    self.cookies.set("sessionid", "fake-pending-session", domain="regx.test")
                    return FakeResponse(200, {"mfa_required": True, "mfa_pending": True,
                                              "email": "vp@smoke.invalid"})
                if url.endswith("/auth/login/mfa/"):
                    if not fake.pending or self.cookies.get("sessionid") != "fake-pending-session":
                        return FakeResponse(400, {"error_code": "mfa_not_pending"})
                    if fake.failures >= fake.lock_after:
                        return FakeResponse(429, {"detail": "Locked."})
                    fake.last_payload = dict(json or {})
                    good = (json or {}).get("code") == FakeRegxMfa.GOOD_CODE or (
                        (json or {}).get("recovery_code") == FakeRegxMfa.GOOD_RECOVERY
                    )
                    if not good:
                        fake.failures += 1
                        return FakeResponse(400, {"error_code": "mfa_invalid_code"})
                    self.cookies.set("sessionid", "fake-regx-session", domain="regx.test")
                    return FakeResponse(200, {"email": "vp@smoke.invalid", "full_name": "Smoke VP",
                                              "is_active": True, "mfa_required": True},
                                        cookies={"sessionid": "fake-regx-session"})
                if url.endswith("/auth/logout/"):
                    return FakeResponse(204, {})
                return FakeResponse(404, {})

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


class SecretKeyRequiredTests(TestCase):
    """settings.py has no fallback key any more: without SECRET_KEY it refuses to load.

    Runs the import in a child process so this test's own settings are untouched.
    No network is involved (the child only imports settings)."""

    def _import_settings(self, secret_key):
        import subprocess
        import sys

        env = {k: v for k, v in os.environ.items() if k != "SECRET_KEY"}
        if secret_key is not None:
            env["SECRET_KEY"] = secret_key
        return subprocess.run(
            [sys.executable, "-c", "import RAAI.settings"],
            cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60,
        )

    def test_missing_key_refuses_to_start(self):
        result = self._import_settings(None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("SECRET_KEY is not set", result.stderr)

    def test_empty_key_refuses_to_start(self):
        result = self._import_settings("")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY is not set", result.stderr)

    def test_supplied_key_loads(self):
        result = self._import_settings("tests-only-throwaway-key-for-this-check")
        self.assertEqual(result.returncode, 0, result.stderr[-500:])


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

    def test_mfa_enrolled_user_gets_the_code_page_not_a_session(self):
        """REGX answers the password step of an MFA-enrolled user with
        mfa_required + mfa_pending (PR #96): no company session yet, code page next."""
        fake = FakeRegxMfa()
        self._with_regx(fake)
        response = _login(self.client, "vp@smoke.invalid")
        self.assertRedirects(response, "/adminmaster/login/mfa/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(CustomUser.objects.filter(username="vp@smoke.invalid").exists())
        page = self.client.get("/adminmaster/login/mfa/")
        self.assertContains(page, "Enter the 6-digit code")
        self.assertContains(page, 'name="code"')

    def test_wrong_password_is_refused(self):
        self._with_regx(FakeRegx(400, {"detail": "Invalid credentials."}))
        response = _login(self.client, "doer@smoke.invalid", "wrong")
        self.assertContains(response, "Invalid Credential")
        self.assertNotIn("_auth_user_id", self.client.session)


@override_settings(REGX_AUTH_URL=REGX)
class SharedRegxMfaCodeStepTests(GuardedTestCase):
    """company_site's MFA code step (PROJECT_OVERVIEW.md §11 #10k): the code goes to
    REGX's /auth/login/mfa/; the company session exists only after REGX accepts it."""

    def setUp(self):
        super().setUp()
        self.fake = FakeRegxMfa()
        p = mock.patch("AdminMaster.regx_auth.requests.Session", self.fake.session())
        p.start()
        self.addCleanup(p.stop)
        _login(self.client, "vp@smoke.invalid")

    def _code(self, code):
        return self.client.post("/adminmaster/login/mfa/", {"code": code})

    def _mfa_posts(self):
        return [c for c in self.fake.calls if c[1].endswith("/auth/login/mfa/")]

    def test_correct_code_signs_in_with_the_mapped_role(self):
        response = self._code(FakeRegxMfa.GOOD_CODE)
        self.assertRedirects(response, "/ratools/", fetch_redirect_response=False)
        user = CustomUser.objects.get(username="vp@smoke.invalid")
        self.assertEqual(user.role, "company_checker")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertNotIn("regx_mfa_pending", self.client.session)
        # The code went to REGX on the pending REGX session, then that session was ended.
        self.assertEqual(self._mfa_posts()[0][2].get("sessionid"), "fake-pending-session")
        self.assertIn(f"{REGX}/api/regx/v1/auth/logout/", [c[1] for c in self.fake.calls])

    def test_wrong_code_is_refused_and_sent_to_regx_to_count(self):
        response = self._code("000000")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid code.")
        self.assertContains(response, 'name="code"')  # still on the code page
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.fake.failures, 1)  # REGX counted it
        self.assertEqual(len(self._mfa_posts()), 1)

    def test_lockout_is_respected(self):
        for _ in range(self.fake.lock_after):
            self._code("000000")
        self.assertEqual(self.fake.failures, self.fake.lock_after)
        response = self._code(FakeRegxMfa.GOOD_CODE)  # even the right code, once locked
        self.assertContains(response, "Too many failed attempts")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("regx_mfa_pending", self.client.session)
        self.assertFalse(CustomUser.objects.filter(username="vp@smoke.invalid").exists())

    def test_expired_pending_sign_in_starts_over(self):
        self.fake.pending = False
        response = self._code(FakeRegxMfa.GOOD_CODE)
        self.assertContains(response, "Your sign-in timed out")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_page_without_a_password_step_opens_nothing(self):
        other = self.client_class()
        response = other.post("/adminmaster/login/mfa/", {"code": FakeRegxMfa.GOOD_CODE})
        self.assertContains(response, "Your sign-in timed out")
        self.assertNotIn("_auth_user_id", other.session)
        self.assertEqual(len(self._mfa_posts()), 0)

    def test_recovery_code_is_passed_through_to_regx(self):
        """A user who lost the authenticator types a recovery code on the same page;
        company_site sends it to REGX as `recovery_code`, and signs in only if REGX accepts."""
        response = self._code(FakeRegxMfa.GOOD_RECOVERY)
        self.assertRedirects(response, "/ratools/", fetch_redirect_response=False)
        self.assertEqual(self.fake.last_payload, {"recovery_code": FakeRegxMfa.GOOD_RECOVERY})
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_recovery_code_is_refused(self):
        response = self._code("ffffffffffffffffffff")
        self.assertContains(response, "Invalid code.")
        self.assertEqual(self.fake.last_payload, {"recovery_code": "ffffffffffffffffffff"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_totp_secret_is_never_stored(self):
        pending = self.client.session["regx_mfa_pending"]
        self.assertEqual(set(pending), {"email", "cookies", "at"})
        self.assertEqual(set(pending["cookies"]), {"sessionid", "csrftoken"})


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
    """Point the FDA-483 cache at a synthetic workbook in a temp directory and
    send every file the refresh writes to that directory too."""

    #: Pages tests use a workbook whose blocks already have summaries; the
    #: no-OpenAI tests set this to False so every block would need one.
    with_summaries = True

    def setUp(self):
        super().setUp()
        from AIDatabase import observation_summary, views

        self.tmp = Path(tempfile.mkdtemp(prefix="cs-smoke-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.xlsx = self.tmp / "observations.xlsx"
        build_synthetic_483(self.xlsx, summaries=self.with_summaries)
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

    with_summaries = False

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

    def test_home_and_dashboards_make_no_openai_call(self):
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
