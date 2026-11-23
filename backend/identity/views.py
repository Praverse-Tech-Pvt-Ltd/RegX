"""Identity views: login, logout, csrf, MFA setup/verify/recovery; registration refused.

Login is two steps for a user with a verified MFA device: the password step
(`login_view`) only records a short-lived "pending" marker in the session and
answers `mfa_required: true`; the full session is granted by
`login_mfa_view` after a valid TOTP code. Users without a verified device log
in with the password alone, as before. Both steps count failures against the
same per-account lockout (`login_lockout`).
"""

import time

import pyotp
from django.contrib.auth import login, logout
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from audit.middleware import log_event

from . import login_lockout
from .models import MFADevice, RecoveryCode, User
from .serializers import (
    LoginSerializer,
    MFARecoverySerializer,
    MFAVerifySerializer,
    UserPublicSerializer,
)

_MFA_LOCKOUT_THRESHOLD = 5
_MFA_LOCKOUT_MINUTES = 15

#: Session key holding the user who passed the password step but not yet MFA.
_MFA_PENDING_KEY = "identity_mfa_pending"
#: How long the password step stays valid while waiting for the TOTP code.
_MFA_PENDING_SECONDS = 5 * 60


@extend_schema(
    tags=["auth"],
    responses={200: {"type": "object", "properties": {"csrfToken": {"type": "string"}}}},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_view(request):
    """Return a CSRF token. Frontend must call this before any state-mutating request."""
    return Response({"csrfToken": get_token(request)})


@extend_schema(tags=["auth"], responses={403: None})
@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    """Public self-registration is disabled: accounts are created by an administrator.

    The route stays so an old client gets a clear answer instead of a 404.
    Platform operators create accounts with `manage.py create_tenant_user`.
    """
    return Response(
        {
            "detail": "Self-registration is disabled. Ask your organisation's "
            "administrator for an account.",
            "error_code": "self_registration_disabled",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


@extend_schema(tags=["auth"], request=LoginSerializer, responses={200: UserPublicSerializer})
@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    email = str(request.data.get("email", ""))
    login_lockout.check(email)
    s = LoginSerializer(data=request.data, context={"request": request})
    if not s.is_valid():
        login_lockout.record_failure(email)
        raise ValidationError(s.errors)
    user = s.validated_data["user"]
    if _verified_device(user) is not None:
        # The password alone is not enough for an enrolled user: no session.
        # Any session already on this browser ends here too, so a pending
        # login never rides on someone else's. The lockout counter is NOT
        # cleared: it is cleared only once the code is accepted, so wrong
        # codes and wrong passwords add up on the same counter.
        logout(request)
        request.session[_MFA_PENDING_KEY] = {
            "user": str(user.public_id),
            "at": time.time(),
        }
        # `email` + `mfa_required` keep company_site's shared login
        # (AdminMaster/regx_auth.py) on its "refuse MFA accounts" branch.
        return Response({"mfa_required": True, "mfa_pending": True, "email": user.email})
    login_lockout.clear(email)
    login(request, user)
    return Response(UserPublicSerializer(user).data)


@extend_schema(tags=["auth"], request=MFAVerifySerializer, responses={200: UserPublicSerializer})
@api_view(["POST"])
@permission_classes([AllowAny])
def login_mfa_view(request):
    """Second login step: a valid TOTP code turns a pending login into a session."""
    pending = request.session.get(_MFA_PENDING_KEY)
    user = None
    if pending and time.time() - pending.get("at", 0) <= _MFA_PENDING_SECONDS:
        user = User.objects.filter(public_id=pending.get("user"), is_active=True).first()
    device = _verified_device(user) if user is not None else None
    if device is None:
        request.session.pop(_MFA_PENDING_KEY, None)
        return Response(
            {
                "detail": "No sign-in is waiting for a code. Sign in with your password again.",
                "error_code": "mfa_not_pending",
            },
            status=400,
        )

    login_lockout.check(user.email)

    if "recovery_code" in request.data:
        return _login_with_recovery_code(request, user, device)

    s = MFAVerifySerializer(data=request.data)
    counter = _matching_counter(device, s.validated_data["code"]) if s.is_valid() else None
    if counter is None or (
        device.last_used_counter is not None and counter <= device.last_used_counter
    ):
        # Wrong, malformed or replayed code: counts toward the lockout.
        login_lockout.record_failure(user.email)
        return Response({"detail": "Invalid code.", "error_code": "mfa_invalid_code"}, status=400)

    device.last_used_counter = counter
    device.save(update_fields=["last_used_counter"])
    login_lockout.clear(user.email)
    request.session.pop(_MFA_PENDING_KEY, None)
    login(request, user)  # rotates the session key
    return Response(UserPublicSerializer(user).data)


@extend_schema(tags=["auth"], responses={204: None})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"], responses={200: UserPublicSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    return Response(UserPublicSerializer(request.user).data)


# ---------------------------------------------------------------------------
# MFA
# ---------------------------------------------------------------------------


@extend_schema(tags=["mfa"])
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_setup_view(request):
    """Provision a TOTP device. Returns a provisioning URI and 10 recovery codes."""
    user = request.user
    with transaction.atomic():
        device, _ = MFADevice.objects.get_or_create(user=user)
        if device.is_verified:
            return Response(
                {"detail": "MFA already active. Disable first to re-enroll."},
                status=status.HTTP_409_CONFLICT,
            )
        secret = pyotp.random_base32()
        device.set_secret(secret)
        device.is_verified = False
        device.save()
        recovery_codes = RecoveryCode.generate(device)
        # Same transaction as the new secret and codes. Counts only: never the
        # secret, the provisioning URI or a recovery code.
        log_event(
            "identity.mfa.enrolment_started",
            resource_type="user",
            resource_id=str(user.public_id),
            payload={"recovery_codes_issued": len(recovery_codes)},
            user=user,
        )
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="RegX")
    return Response({"totp_uri": uri, "recovery_codes": recovery_codes})


@extend_schema(tags=["mfa"], request=MFAVerifySerializer)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_verify_view(request):
    """Confirm TOTP code and activate the device."""
    s = MFAVerifySerializer(data=request.data)
    s.is_valid(raise_exception=True)
    code = s.validated_data["code"]

    try:
        device = request.user.mfa_device
    except MFADevice.DoesNotExist:
        return Response({"detail": "No MFA device provisioned."}, status=400)

    if _is_locked(device):
        return Response({"detail": "MFA locked. Try again later."}, status=429)

    secret = device.get_secret()
    totp = pyotp.TOTP(secret)
    current_counter = _totp_counter()

    if not totp.verify(code, valid_window=1):
        device.failed_attempts += 1
        if device.failed_attempts >= _MFA_LOCKOUT_THRESHOLD:
            device.locked_until = timezone.now() + timezone.timedelta(minutes=_MFA_LOCKOUT_MINUTES)
        device.save(update_fields=["failed_attempts", "locked_until"])
        return Response({"detail": "Invalid OTP."}, status=400)

    if device.last_used_counter == current_counter:
        return Response({"detail": "OTP already used (replay prevented)."}, status=400)

    with transaction.atomic():
        device.is_verified = True
        device.last_used_counter = current_counter
        device.failed_attempts = 0
        device.locked_until = None
        device.save()
        request.user.mfa_required = True
        request.user.save(update_fields=["mfa_required"])
        # Same transaction as the activation. Never the code.
        log_event(
            "identity.mfa.activated",
            resource_type="user",
            resource_id=str(request.user.public_id),
            payload={"mfa_required": True},
            user=request.user,
        )
    return Response({"detail": "MFA activated."})


@extend_schema(tags=["mfa"], request=MFARecoverySerializer)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_recovery_view(request):
    """Consume a single-use recovery code to authenticate past MFA."""
    s = MFARecoverySerializer(data=request.data)
    s.is_valid(raise_exception=True)
    code = s.validated_data["recovery_code"]

    try:
        device = request.user.mfa_device
    except MFADevice.DoesNotExist:
        return Response({"detail": "No MFA device."}, status=400)

    with transaction.atomic():
        if not RecoveryCode.consume(device, code):
            return Response({"detail": "Invalid or already-used recovery code."}, status=400)
        # Same transaction as spending the code. Never the code itself.
        log_event(
            "identity.mfa.recovery_code_used",
            resource_type="user",
            resource_id=str(request.user.public_id),
            payload={
                "recovery_codes_remaining": device.recovery_codes.filter(
                    used_at__isnull=True
                ).count(),
                "via": "mfa_recovery_endpoint",
            },
            user=request.user,
        )
    return Response({"detail": "Recovery code accepted."})


def _login_with_recovery_code(request, user, device):
    """Second login step with a single-use recovery code instead of the TOTP code.

    For a user who has lost their authenticator. Same lockout as wrong codes;
    every use is audited. The code is spent whether or not the user then enrols
    a new device.
    """
    s = MFARecoverySerializer(data=request.data)
    consumed = False
    if s.is_valid():
        # QA-09: spending the code and its audit record commit together or not at
        # all. A refused code writes nothing, so it stays outside (lockout below).
        with transaction.atomic():
            consumed = RecoveryCode.consume(device, s.validated_data["recovery_code"])
            if consumed:
                remaining = device.recovery_codes.filter(used_at__isnull=True).count()
                log_event(
                    "identity.mfa.recovery_code_used",
                    resource_type="user",
                    resource_id=str(user.public_id),
                    payload={"recovery_codes_remaining": remaining},
                    user=user,
                )
    if not consumed:
        login_lockout.record_failure(user.email)
        return Response(
            {"detail": "Invalid or already-used recovery code.", "error_code": "mfa_invalid_code"},
            status=400,
        )
    login_lockout.clear(user.email)
    request.session.pop(_MFA_PENDING_KEY, None)
    login(request, user)
    data = dict(UserPublicSerializer(user).data)
    data["recovery_codes_remaining"] = remaining
    return Response(data)


def _verified_device(user) -> MFADevice | None:
    """The user's MFA device if enrolment was completed, else None."""
    return MFADevice.objects.filter(user=user, is_verified=True).first()


def _matching_counter(device: MFADevice, code: str) -> int | None:
    """The TOTP time-step the code belongs to (current one +/- 1), or None."""
    totp = pyotp.TOTP(device.get_secret())
    now = _totp_counter()
    for counter in (now, now - 1, now + 1):
        if pyotp.utils.strings_equal(totp.at(counter * totp.interval), code):
            return counter
    return None


def _is_locked(device: MFADevice) -> bool:
    if device.locked_until and device.locked_until > timezone.now():
        return True
    return False


def _totp_counter() -> int:
    """Return the current 30-second TOTP window index (unix // 30)."""
    return int(time.time()) // 30
