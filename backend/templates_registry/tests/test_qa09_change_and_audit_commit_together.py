"""QA-09 (templates_registry importer): each stage's writes and its audit events commit
together or not at all.

Fault injection: `audit.testing.audit_writes_fail()` makes every audit INSERT fail in
PostgreSQL. On the old code each stage wrote its rows outside any transaction and
emitted after, so the rows stayed with no audit record and these tests failed.

Covered: package registration, batch creation, and a full run (extract / classify /
import / completion; the run's FAILED marker is written in its own transaction, which
the injected failure also refuses, so the batch stays REGISTERED).
"""

from __future__ import annotations

import pytest

from audit.testing import attempt, audit_writes_fail
from templates_registry import adapters, importer
from templates_registry.models import (
    MigrationBatch,
    MigrationBatchStatus,
    TemplateSourcePackage,
    TemplateSourceRecord,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _register(tenant, user, name="qa09-package"):
    return importer.register_source_package(
        tenant=tenant,
        source_name=name,
        source_type="anda_checklist",
        source_path_or_reference=f"synthetic://{name}.json",
        payload_for_checksum={"rows": [name]},
        imported_by=user,
    )


def test_package_registration_rolls_back_without_its_audit(tenant_a, user_a):
    with audit_writes_fail():
        attempt(_register, tenant_a, user_a)
    assert not TemplateSourcePackage.objects.filter(source_name="qa09-package").exists()


def test_batch_creation_rolls_back_without_its_audit(tenant_a, user_a):
    package = _register(tenant_a, user_a)
    with audit_writes_fail():
        attempt(importer.create_migration_batch, package, user_a)
    assert not MigrationBatch.objects.filter(source_package=package).exists()


def test_a_run_rolls_back_without_its_audit(tenant_a, user_a, anda_like_rows):
    package = _register(tenant_a, user_a, name="qa09-run")
    batch = importer.create_migration_batch(package, user_a)
    neutral = adapters.anda_like_adapter(anda_like_rows, source_name="qa09-run")
    with audit_writes_fail():
        attempt(importer.run_migration_batch, batch, neutral, user_a)
    batch.refresh_from_db()
    assert not TemplateSourceRecord.objects.filter(source_package=package).exists()
    assert batch.status == MigrationBatchStatus.REGISTERED
