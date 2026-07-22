"""
RBAC models: Role, Permission, RolePermission, MembershipRole.

Roles are scoped to a tenant.  Built-in system roles (doer, reviewer, vp,
tenant_admin, platform_support) are seeded at startup.
"""

from django.db import models
from common.models import TimeStampedModel


class Role(TimeStampedModel):
    """A named role within a tenant.  System roles have is_system=True."""

    class BuiltIn(models.TextChoices):
        DOER = "doer", "Doer"
        REVIEWER = "reviewer", "Reviewer"
        VP = "vp", "VP"
        TENANT_ADMIN = "tenant_admin", "Tenant Admin"
        PLATFORM_SUPPORT = "platform_support", "Platform Support"

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="roles",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    is_system = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = [("tenant", "name")]
        ordering = ["name"]

    def __str__(self):
        tenant_label = self.tenant.slug if self.tenant else "system"
        return f"{self.name}@{tenant_label}"


class Permission(TimeStampedModel):
    """A granular action code, e.g. 'workflow:submit', 'workflow:approve'."""

    codename = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["codename"]

    def __str__(self):
        return self.codename


class RolePermission(TimeStampedModel):
    """Maps a role to a permission."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(
        Permission, on_delete=models.CASCADE, related_name="role_permissions"
    )

    class Meta:
        unique_together = [("role", "permission")]


class MembershipRole(TimeStampedModel):
    """Grants a role to a user within a specific tenant membership."""

    membership = models.ForeignKey(
        "tenancy.TenantMembership",
        on_delete=models.CASCADE,
        related_name="membership_roles",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="membership_roles")

    class Meta:
        unique_together = [("membership", "role")]

    def __str__(self):
        return f"{self.membership} → {self.role.name}"
