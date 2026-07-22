"""Tests for identity domain models."""

import pytest
from django.contrib.auth import get_user_model

from identity.models import MFADevice, RecoveryCode

User = get_user_model()


@pytest.mark.django_db
class TestUser:
    def test_create_user_email_login(self):
        user = User.objects.create_user(email="alice@example.com", password="Secure1234!")
        assert user.email == "alice@example.com"
        assert user.check_password("Secure1234!")
        assert not user.is_staff
        assert not user.is_superuser

    def test_email_is_normalized(self):
        user = User.objects.create_user(email="BOB@EXAMPLE.COM", password="Secure1234!")
        assert user.email == "bob@example.com"

    def test_create_user_missing_email_raises(self):
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_user(email="", password="Secure1234!")

    def test_create_superuser(self):
        user = User.objects.create_superuser(email="super@example.com", password="Secure1234!")
        assert user.is_staff
        assert user.is_superuser

    def test_public_id_is_uuid_not_pk(self):
        user = User.objects.create_user(email="carol@example.com", password="Secure1234!")
        assert user.public_id is not None
        assert str(user.public_id) != str(user.pk)

    def test_internal_pk_not_on_public_id_field(self):
        user = User.objects.create_user(email="dave@example.com", password="Secure1234!")
        # pk is a plain integer; public_id is a UUID
        assert isinstance(user.pk, int)
        import uuid

        assert isinstance(user.public_id, uuid.UUID)


@pytest.mark.django_db
class TestMFADevice:
    def test_encrypt_decrypt_secret(self, user):
        device = MFADevice(user=user)
        device.set_secret("JBSWY3DPEHPK3PXP")
        device.save()
        assert device.get_secret() == "JBSWY3DPEHPK3PXP"

    def test_encrypted_secret_not_plaintext(self, user):
        device = MFADevice(user=user)
        device.set_secret("JBSWY3DPEHPK3PXP")
        device.save()
        raw = bytes(device._encrypted_secret)
        assert b"JBSWY3DPEHPK3PXP" not in raw


@pytest.mark.django_db
class TestRecoveryCode:
    def test_generate_creates_10_codes(self, user):
        device = MFADevice.objects.create(user=user, _encrypted_secret=b"x" * 32)
        codes = RecoveryCode.generate(device)
        assert len(codes) == 10
        assert RecoveryCode.objects.filter(device=device).count() == 10

    def test_codes_stored_as_hashes(self, user):
        device = MFADevice.objects.create(user=user, _encrypted_secret=b"x" * 32)
        codes = RecoveryCode.generate(device)
        for code in codes:
            assert not RecoveryCode.objects.filter(code_hash=code).exists()

    def test_consume_valid_code(self, user):
        device = MFADevice.objects.create(user=user, _encrypted_secret=b"x" * 32)
        codes = RecoveryCode.generate(device)
        assert RecoveryCode.consume(device, codes[0]) is True

    def test_consume_same_code_twice_fails(self, user):
        device = MFADevice.objects.create(user=user, _encrypted_secret=b"x" * 32)
        codes = RecoveryCode.generate(device)
        RecoveryCode.consume(device, codes[0])
        assert RecoveryCode.consume(device, codes[0]) is False

    def test_consume_invalid_code_fails(self, user):
        device = MFADevice.objects.create(user=user, _encrypted_secret=b"x" * 32)
        RecoveryCode.generate(device)
        assert RecoveryCode.consume(device, "notavalidcode1234567") is False
