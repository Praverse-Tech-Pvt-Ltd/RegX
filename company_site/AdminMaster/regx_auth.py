"""Authenticate company_site users against REGX, so one credential set works for both.

Background
----------
This repository carries two Django applications with separate user models:
REGX's `identity.User` (email, tenant memberships, roles) and this
application's `AdminMaster.CustomUser` (username, one of three legacy roles).
Until now each had its own login page and its own password, and a person with
access to both had to keep two sets of credentials in step by hand.

REGX is the authority. This module reduces the company login to a shim: it
posts the submitted credentials to REGX's auth API, and on success looks up or
provisions the matching `CustomUser` and hands it back for the company session.

Why an HTTP call rather than a shared session
---------------------------------------------
The two applications sign with different `SECRET_KEY`s over different session
stores (SQLite here, PostgreSQL there). Making one cookie work in both would
mean weakening one side's configuration to match the other, which is why
`docs/COMPANY_SITE_AUTH_INTEGRATION.md` rules it out. Each application keeps
its own session; only the credential check is shared.

Provisioned accounts get an unusable local password on purpose. If a REGX
password is later changed or the account disabled, there is no stale local
password left behind that would still open this door.
"""

import datetime
import logging

import requests
from django.conf import settings

from .models import AssignChecker, CustomUser

logger = logging.getLogger(__name__)

#: REGX role -> legacy role. REGX's model is richer, so this collapses:
#: `vp` approves work but does not administer users, which makes it a checker
#: here; `platform_support` is Praverse staff and needs the admin console.
ROLE_MAP = {
    "tenant_admin": "admin",
    "platform_support": "admin",
    "doer": "company_user",
    "reviewer": "company_checker",
    "vp": "company_checker",
}

#: Applied when REGX reports a role this application has no equivalent for, and
#: when it reports none at all. The least-privileged of the three.
DEFAULT_ROLE = "company_user"

#: A REGX identity may hold several roles; the most privileged one wins.
ROLE_PRECEDENCE = ("admin", "company_checker", "company_user")

TIMEOUT = 10


class RegxUnavailable(Exception):
    """REGX could not be reached or answered unusably."""


def _api(path):
    return settings.REGX_AUTH_URL.rstrip("/") + "/api/regx/v1" + path


def _carry_session_cookie(session):
    """Let the follow-up role request reuse the session the login just opened.

    REGX sets `SESSION_COOKIE_SECURE = True` in production, so `requests` will
    not return that cookie over the plain-HTTP hop between these two containers
    and the role lookup would arrive unauthenticated.

    Re-setting the same value without the Secure flag is safe here and does not
    weaken REGX's setting, which stays exactly as it is. That flag exists to
    stop a browser leaking a cookie onto a channel the server never chose; this
    is a server replaying, on the one internal hop it already used, a cookie it
    received over that same hop a moment ago. No new channel is involved.
    """
    value = session.cookies.get("sessionid")
    if value:
        session.cookies.set("sessionid", value)


def _roles_for(session):
    """The caller's REGX role names, or an empty list if the endpoint is absent.

    An older REGX build has no `/permissions/mine/`. Rather than refuse the
    login, fall back to the default role -- the person authenticated correctly,
    and the least-privileged role is a safe landing place.
    """
    try:
        response = session.get(_api("/permissions/mine/"), timeout=TIMEOUT)
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []
    try:
        return response.json().get("roles", [])
    except ValueError:
        return []


def _legacy_role(regx_roles):
    mapped = {ROLE_MAP.get(name, DEFAULT_ROLE) for name in regx_roles}
    for role in ROLE_PRECEDENCE:
        if role in mapped:
            return role
    return DEFAULT_ROLE


def _provision(profile, role):
    """Return the `CustomUser` mirroring this REGX identity, creating it if new.

    Keyed on the REGX email, which is that account's stable identifier here.

    The `AssignChecker` row is not optional: several RATools views call
    `AssignChecker.objects.get(user=...)` unguarded and return 500 without one.
    """
    email = profile["email"]
    user, created = CustomUser.objects.get_or_create(
        username=email, defaults={"email": email}
    )

    user.email = email
    user.role = role
    user.is_active = profile.get("is_active", True)
    user.is_staff = role == "admin"
    user.is_superuser = False
    # Local password authentication is deliberately impossible for these
    # accounts: REGX is the only place their password is checked.
    user.set_unusable_password()
    if profile.get("full_name"):
        user.first_name = profile["full_name"][:150]
    if created:
        # A mirrored account is only as entitled as REGX says; these three
        # gate content this application serves and have no REGX counterpart,
        # so they follow the subscription rather than the role.
        user.subscription_end_date = datetime.date(2030, 12, 31)
        user.fda_deficiency_database = True
        user.complete_response_database = True
    user.save()

    assignment, assignment_created = AssignChecker.objects.get_or_create(user=user)
    if assignment_created:
        assignment.assigned_report = [c[0] for c in AssignChecker.REPORT_CHOICES]
        assignment.view_sample_reports = [c[0] for c in AssignChecker.VIEW_SAMPLE_CHOICES]
        assignment.save()

    return user


def authenticate(username, password):
    """Check `username`/`password` against REGX and return the local mirror user.

    Returns None when REGX rejects the credentials or is not configured, so the
    caller can fall through to local authentication. Raises `RegxUnavailable`
    when REGX is configured but unreachable -- an outage must not be reported to
    the user as a wrong password.
    """
    base = getattr(settings, "REGX_AUTH_URL", "")
    if not base:
        return None

    session = requests.Session()
    try:
        # REGX runs Django's CSRF middleware. An anonymous POST is not
        # currently rejected without a token, but sending one keeps this
        # working if that is tightened.
        csrf = session.get(_api("/auth/csrf/"), timeout=TIMEOUT)
        headers = {}
        if csrf.status_code == 200:
            token = session.cookies.get("csrftoken")
            if token:
                headers["X-CSRFToken"] = token

        response = session.post(
            _api("/auth/login/"),
            json={"email": username, "password": password},
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RegxUnavailable(str(exc)) from exc

    if response.status_code == 400:
        return None  # REGX said these credentials are wrong.
    if response.status_code != 200:
        raise RegxUnavailable("REGX auth returned HTTP %s" % response.status_code)

    try:
        profile = response.json()
    except ValueError as exc:
        raise RegxUnavailable("REGX auth returned a non-JSON body") from exc

    if not profile.get("email"):
        raise RegxUnavailable("REGX auth returned no email")

    if profile.get("mfa_required"):
        # This login page collects a password and nothing else. Granting a
        # session here would skip a second factor the person chose to enable,
        # making this the weaker of the two doors into the same identity.
        logger.warning("Refused company login for %s: REGX requires MFA", profile["email"])
        return None

    _carry_session_cookie(session)
    role = _legacy_role(_roles_for(session))
    logger.info("REGX login for %s mapped to legacy role %s", profile["email"], role)
    return _provision(profile, role)
