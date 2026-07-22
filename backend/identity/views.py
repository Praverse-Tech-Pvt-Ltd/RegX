"""Identity views: register, login, logout, MFA setup/verify/recovery."""

import pyotp
from django.contrib.auth import login, logout
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import MFADevice, RecoveryCode, User
from .serializers import (
    LoginSerializer,
    MFARecoverySerializer,
    MFASetupSerializer,
    MFAVerifySerializer,
    RegisterSerializer,
    UserPublicSerializer,
)

_MFA_LOCKOUT_THRESHOLD = 5
_MFA_LOCKOUT_MINUTES = 15


@extend_schema(tags=["auth"], request=RegisterSerializer, responses={201: UserPublicSerializer})
@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    s = RegisterSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    user = s.save()
    return Response(UserPublicSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["auth"], request=LoginSerializer, responses={200: UserPublicSerializer})
@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    s = LoginSerializer(data=request.data, context={"request": request})
    s.is_valid(raise_exception=True)
    user = s.validated_data["user"]
    login(request, user)
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
            device.locked_until = timezone.now() + timezone.timedelta(
                minutes=_MFA_LOCKOUT_MINUTES
            )
        device.save(update_fields=["failed_attempts", "locked_until"])
        return Response({"detail": "Invalid OTP."}, status=400)

    if device.last_used_counter == current_counter:
        return Response({"detail": "OTP already used (replay prevented)."}, status=400)

    device.is_verified = True
    device.last_used_counter = current_counter
    device.failed_attempts = 0
    device.locked_until = None
    device.save()
    request.user.mfa_required = True
    request.user.save(update_fields=["mfa_required"])
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

    if not RecoveryCode.consume(device, code):
        return Response({"detail": "Invalid or already-used recovery code."}, status=400)

    return Response({"detail": "Recovery code accepted."})


def _is_locked(device: MFADevice) -> bool:
    if device.locked_until and device.locked_until > timezone.now():
        return True
    return False


def _totp_counter() -> int:
    """Return the current 30-second TOTP window index (unix // 30)."""
    import time
    return int(time.time()) // 30
