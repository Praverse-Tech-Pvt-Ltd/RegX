"""Fail-closed tenant-scoped managers for the formulations domain.

Unlike templates_registry, formulations are always tenant-owned (no
platform-master concept) -- tenant is never nullable here.
"""

from django.db import models


class TenantScopedManager(models.Manager):
    def for_tenant(self, tenant):
        return self.get_queryset().filter(tenant=tenant)


class RelatedTenantScopedManager(models.Manager):
    tenant_path = "product__tenant"

    def for_tenant(self, tenant):
        return self.get_queryset().filter(**{self.tenant_path: tenant})


class FormulationVersionRelatedManager(RelatedTenantScopedManager):
    tenant_path = "formulation_version__product__tenant"
