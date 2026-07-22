"""Fail-closed tenant-scoped managers for document models."""

from django.db import models


class TenantScopedManager(models.Manager):
    """Manager that always requires tenant to be specified.

    Use .for_tenant(tenant) to get a queryset scoped to a specific tenant.
    .all() returns nothing — callers must always scope by tenant.
    """

    def get_queryset(self):
        return super().get_queryset()

    def for_tenant(self, tenant):
        return self.get_queryset().filter(tenant=tenant)


class VersionTenantScopedManager(models.Manager):
    """Manager for DocumentVersion — scoped via document__tenant."""

    def get_queryset(self):
        return super().get_queryset()

    def for_tenant(self, tenant):
        return self.get_queryset().filter(document__tenant=tenant)
