"""Fail-closed tenant-scoped managers for the template registry domain."""

from django.db import models


class TenantOrPlatformScopedManager(models.Manager):
    """Manager for models with a nullable tenant (platform-level master
    templates are tenant=None by design).

    .all() returns everything unscoped -- callers in views MUST use
    .for_tenant(tenant) (tenant-owned rows only) or
    .for_tenant_including_platform(tenant) (tenant-owned + platform-level
    master rows) so cross-tenant leakage is a conscious choice, never a
    default.
    """

    def for_tenant(self, tenant):
        return self.get_queryset().filter(tenant=tenant)

    def for_tenant_including_platform(self, tenant):
        return self.get_queryset().filter(models.Q(tenant=tenant) | models.Q(tenant__isnull=True))


class RelatedTenantScopedManager(models.Manager):
    """Manager for child models scoped via a FK chain to RegulatoryTemplate.tenant."""

    tenant_path = "template__tenant"

    def for_tenant(self, tenant):
        return self.get_queryset().filter(**{self.tenant_path: tenant})

    def for_tenant_including_platform(self, tenant):
        return self.get_queryset().filter(
            models.Q(**{self.tenant_path: tenant})
            | models.Q(**{f"{self.tenant_path}__isnull": True})
        )


class VersionRelatedTenantScopedManager(RelatedTenantScopedManager):
    tenant_path = "template_version__template__tenant"


class SectionRelatedTenantScopedManager(RelatedTenantScopedManager):
    tenant_path = "template_section__template_version__template__tenant"


class SourcePackageRelatedTenantScopedManager(RelatedTenantScopedManager):
    tenant_path = "source_package__tenant"


class ApprovalTenantScopedManager(RelatedTenantScopedManager):
    tenant_path = "template_version__template__tenant"
