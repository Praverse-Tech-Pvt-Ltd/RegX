"""Identity serializers. Internal PKs are never returned; only public_id."""

from django.contrib.auth import authenticate
from rest_framework import serializers

from .models import User


class UserPublicSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "is_active", "mfa_required", "created_at"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"],
            password=attrs["password"],
        )
        if not user:
            raise serializers.ValidationError("Invalid credentials.")
        if not user.is_active:
            raise serializers.ValidationError("Account disabled.")
        attrs["user"] = user
        return attrs


class MFASetupSerializer(serializers.Serializer):
    """Returns provisioning URI; secret never leaves the server in plaintext."""

    totp_uri = serializers.CharField(read_only=True)
    recovery_codes = serializers.ListField(child=serializers.CharField(), read_only=True)


class MFAVerifySerializer(serializers.Serializer):
    code = serializers.CharField(min_length=6, max_length=6)

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be 6 digits.")
        return value


class MFARecoverySerializer(serializers.Serializer):
    recovery_code = serializers.CharField(min_length=20, max_length=20)
