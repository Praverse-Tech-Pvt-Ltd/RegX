"""Fail-closed tenant-scoped managers for document models.

QuerySet-level delete() on both Document and DocumentVersion consults
DeletionProtectionRegistry before any row is removed -- this closes the
bypass where DocumentVersion.delete() (the instance-level override) is
skipped entirely by `SomeQuerySet.delete()` or bulk deletion (Milestone
4D-2, DR-2-06/DR-2-35 remediation, M4D2-F-3).
"""

from django.db import models


class _ProtectedDocumentVersionQuerySet(models.QuerySet):
    def delete(self):
        from .deletion_protection import (
            DeletionProtectionRegistry,
            DocumentVersionDeleteForbidden,
        )

        blocked = [dv for dv in self if DeletionProtectionRegistry.check(dv)]
        if blocked:
            raise DocumentVersionDeleteForbidden(
                "One or more document versions in this queryset are "
                "referenced by governed content and cannot be deleted."
            )
        return super().delete()


class _ProtectedDocumentQuerySet(models.QuerySet):
    def delete(self):
        from .deletion_protection import (
            DeletionProtectionRegistry,
            DocumentVersionDeleteForbidden,
        )

        blocked = [
            dv
            for doc in self
            for dv in doc.versions.all()
            if DeletionProtectionRegistry.check(dv)
        ]
        if blocked:
            raise DocumentVersionDeleteForbidden(
                "One or more documents in this queryset have versions "
                "referenced by governed content and cannot be deleted."
            )
        return super().delete()


class TenantScopedManager(models.Manager.from_queryset(_ProtectedDocumentQuerySet)):
    """Manager that always requires tenant to be specified.

    Use .for_tenant(tenant) to get a queryset scoped to a specific tenant.
    .all() returns nothing — callers must always scope by tenant.
    """

    def for_tenant(self, tenant):
        return self.get_queryset().filter(tenant=tenant)


class VersionTenantScopedManager(models.Manager.from_queryset(_ProtectedDocumentVersionQuerySet)):
    """Manager for DocumentVersion — scoped via document__tenant."""

    def for_tenant(self, tenant):
        return self.get_queryset().filter(document__tenant=tenant)
