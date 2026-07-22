from rest_framework import serializers
from .models import Tenant, TenantMembership


class TenantSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]


class TenantCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["name", "slug"]

    def validate_slug(self, value):
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Slug already taken.")
        return value


class MembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.public_id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = TenantMembership
        fields = ["user_id", "email", "is_active", "created_at"]
        read_only_fields = fields
