"""
Tenancy models.

Users may belong to multiple tenants (many-to-many via TenantMembership).
No tenant FK is placed directly on the User model.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class Tenant(PublicIDModel, TimeStampedModel):
    """An isolated organizational unit within REGX."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DEPROVISIONED = "deprovisioned", "Deprovisioned"

    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TenantMembership(TimeStampedModel):
    """Links a user to a tenant. Roles are granted via authorization.MembershipRole."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("identity.User", on_delete=models.CASCADE, related_name="memberships")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("tenant", "user")]
        ordering = ["tenant", "user"]

    def __str__(self):
        return f"{self.user} @ {self.tenant}"
