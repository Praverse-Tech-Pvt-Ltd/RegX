"""
REGX identity models.

No AIDatabase, no legacy booking-demo imports, no SQLite dependency.
"""

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .managers import UserManager

# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(AbstractBaseUser, PermissionsMixin, PublicIDModel, TimeStampedModel):
    """
    Custom user model with email-based login and no tenant FK.
    Users may belong to multiple tenants via TenantMembership.
    Internal integer PK is never exposed in API responses; use public_id.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    mfa_required = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]
        indexes = [models.Index(fields=["email"])]

    def __str__(self):
        return self.email


# ---------------------------------------------------------------------------
# MFA Device (TOTP)
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    """Return a Fernet instance using the configured MFA encryption key."""
    raw = settings.MFA_ENCRYPTION_KEY
    # Normalise: accept raw 32-byte string or base64-encoded key
    try:
        key = base64.urlsafe_b64decode(raw + "==")
        if len(key) != 32:
            raise ValueError
        key = base64.urlsafe_b64encode(key)
    except Exception:
        key = base64.urlsafe_b64encode(raw.encode()[:32].ljust(32, b"\x00"))
    return Fernet(key)


class MFADevice(TimeStampedModel):
    """
    TOTP device.  The TOTP secret is stored encrypted (Fernet symmetric).
    Never log or expose the plaintext secret.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mfa_device")
    # Encrypted TOTP secret (base32 string, Fernet-encrypted, stored as bytes)
    _encrypted_secret = models.BinaryField(db_column="encrypted_secret")
    is_verified = models.BooleanField(default=False)

    # Replay prevention: track the last successfully used OTP timestamp
    last_used_counter = models.BigIntegerField(null=True, blank=True)

    # Lockout
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "MFA Device"

    def set_secret(self, totp_secret: str) -> None:
        """Encrypt and store the TOTP secret."""
        self._encrypted_secret = _fernet().encrypt(totp_secret.encode())

    def get_secret(self) -> str:
        """Decrypt and return the TOTP secret. Never log the return value."""
        try:
            return _fernet().decrypt(bytes(self._encrypted_secret)).decode()
        except InvalidToken as exc:
            raise ValueError("MFA secret decryption failed.") from exc

    def __str__(self):
        return f"MFADevice({self.user.email}, verified={self.is_verified})"


# ---------------------------------------------------------------------------
# Recovery Codes
# ---------------------------------------------------------------------------


class RecoveryCode(TimeStampedModel):
    """
    Single-use MFA recovery code stored as a SHA-256 hash.
    The plaintext is only available at generation time and must not be
    stored or logged.
    """

    HASH_ALGORITHM = "sha256"
    CODE_BYTES = 10  # 80-bit entropy, displayed as hex

    device = models.ForeignKey(MFADevice, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Recovery Code"

    @classmethod
    def _hash(cls, plaintext: str) -> str:
        return hashlib.sha256(plaintext.encode()).hexdigest()

    @classmethod
    def generate(cls, device: "MFADevice") -> list[str]:
        """
        Generate 10 recovery codes for a device.
        Returns the list of plaintext codes (shown once to the user).
        Stores only hashes.
        """
        device.recovery_codes.all().delete()
        codes = []
        for _ in range(10):
            plaintext = secrets.token_hex(cls.CODE_BYTES)
            cls.objects.create(device=device, code_hash=cls._hash(plaintext))
            codes.append(plaintext)
        return codes

    @classmethod
    def consume(cls, device: "MFADevice", plaintext: str) -> bool:
        """
        Attempt to consume a recovery code.
        Returns True if the code was valid and unused; False otherwise.
        """
        from django.utils import timezone

        h = cls._hash(plaintext)
        # One UPDATE, so two simultaneous uses of the same code cannot both succeed.
        used = cls.objects.filter(device=device, code_hash=h, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        return used == 1

    @property
    def is_used(self) -> bool:
        return self.used_at is not None
