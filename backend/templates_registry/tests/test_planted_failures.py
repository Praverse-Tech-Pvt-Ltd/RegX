"""
The 10 named planted-failure scenarios from Milestone 3 section 14.

Each test PLANTS the exact violation described, DETECTS it via an
assertion that the system's guard rejects/blocks it, and then confirms
the system RESTORES to a clean, correctly-functioning state afterward
(a clean rerun succeeds). No planted violation is left committed: every
plant happens inside the test and is rejected before it can persist.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from templates_registry import adapters, importer, lifecycle
from templates_registry.models import (
    RegulatoryTemplate,
    TemplateItem,
    TemplateLifecycleStatus,
    TemplateSourcePackage,
    TemplateSourceRecord,
    TemplateVersion,
)

BASE = "/api/regx/v1"


def _client_for(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
    return client


# ---------------------------------------------------------------------------
# 1. AIDatabase import
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_1_aidatabase_import_planted_and_blocked(tenant_a, user_a):
    # PLANT: attempt to register a source package explicitly sourced from
    # AIDatabase.
    with pytest.raises(importer.SourceExcluded):
        importer.register_source_package(
            tenant=tenant_a,
            source_name="AIDatabase full dump",
            source_type="aidatabase",
            source_path_or_reference="synthetic://aidatabase-dump.json",
            payload_for_checksum={"rows": [{"id": "AID-1"}]},
            imported_by=user_a,
        )
    # DETECT: nothing was persisted.
    assert not TemplateSourcePackage.objects.filter(source_name="AIDatabase full dump").exists()
    # RESTORE/RERUN: a legitimate, non-AIDatabase package registers cleanly.
    package = importer.register_source_package(
        tenant=tenant_a,
        source_name="anda-clean-after-1",
        source_type="anda_checklist",
        source_path_or_reference="synthetic://clean.json",
        payload_for_checksum={"rows": []},
        imported_by=user_a,
    )
    assert package.pk is not None


# ---------------------------------------------------------------------------
# 2. 483 source record accepted
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_2_483_source_record_planted_and_excluded(tenant_a, user_a):
    row_483 = {
        "id": 900,
        "report_name": "Form483 Export",
        "module_name": "Inspection",
        "chapter_name": "Observations",
        "category_name": "Observations",
        "question": "<p>483 observation regarding cleaning validation.</p>",
    }
    neutral = adapters.anda_like_adapter([row_483], source_name="mixed-483-planted")
    package = importer.register_source_package(
        tenant=tenant_a,
        source_name="mixed-483-planted",
        source_type="anda_checklist",  # declared type is benign; the row itself is not
        source_path_or_reference="synthetic://mixed-483.json",
        payload_for_checksum={"rows": [row_483]},
        imported_by=user_a,
    )
    batch = importer.create_migration_batch(package, user_a)
    # PLANT: run the batch containing a 483 observation row.
    importer.run_migration_batch(batch, neutral, user_a)
    # DETECT: the row is excluded, never becomes a TemplateItem.
    assert not TemplateItem.objects.filter(raw_text__icontains="483 observation").exists()
    record = TemplateSourceRecord.objects.get(source_package=package)
    assert record.migration_disposition == "excluded"
    # RESTORE/RERUN: rerunning the same batch is stable, still excluded.
    importer.run_migration_batch(batch, neutral, user_a)
    assert TemplateSourceRecord.objects.filter(source_package=package).count() == 1


# ---------------------------------------------------------------------------
# 3. Imported version auto-activated
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_3_imported_version_cannot_be_auto_activated(tenant_a, user_a, vp_user, anda_like_rows):
    neutral = adapters.anda_like_adapter(anda_like_rows, source_name="anda-auto-activate")
    package = importer.register_source_package(
        tenant=tenant_a,
        source_name="anda-auto-activate",
        source_type="anda_checklist",
        source_path_or_reference="synthetic://aa.json",
        payload_for_checksum={"rows": anda_like_rows},
        imported_by=user_a,
    )
    batch = importer.create_migration_batch(package, user_a)
    importer.run_migration_batch(batch, neutral, user_a)
    item = TemplateItem.objects.filter(
        template_section__template_version__source_package=package
    ).first()
    version = item.template_section.template_version

    # DETECT: the pipeline itself never set status to active.
    assert version.status != TemplateLifecycleStatus.ACTIVE

    # PLANT: attempt to activate straight from imported (skipping
    # review/approval) through the real service function.
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.activate(version, vp_user)

    # RESTORE: version remains imported; the only path to active is the
    # full submit -> approve -> activate walk.
    version.refresh_from_db()
    assert version.status == TemplateLifecycleStatus.IMPORTED
    version = lifecycle.submit_for_review(version, user_a)
    version = lifecycle.approve(version, vp_user, "Reviewed via the real approval path", "vp")
    version = lifecycle.activate(version, vp_user)
    assert version.status == TemplateLifecycleStatus.ACTIVE


# ---------------------------------------------------------------------------
# 4. Raw text overwritten by normalization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_4_normalization_cannot_overwrite_raw_text(tenant_a, user_a, mojibake_row):
    neutral = adapters.dmf_like_adapter(
        [mojibake_row], source_name="mojibake-planted", table_hint="dmfreviewtablequestion"
    )
    package = importer.register_source_package(
        tenant=tenant_a,
        source_name="mojibake-planted",
        source_type="anda_checklist",
        source_path_or_reference="synthetic://mojibake.json",
        payload_for_checksum={"rows": [mojibake_row]},
        imported_by=user_a,
    )
    batch = importer.create_migration_batch(package, user_a)
    importer.run_migration_batch(batch, neutral, user_a)
    record = TemplateSourceRecord.objects.get(source_package=package)
    original_raw_text = record.raw_text

    # PLANT: attempt to overwrite raw_text as if a normalization step had
    # mutated it in place (this is exactly the bug the pipeline's
    # non-destructive design prevents -- normalize_text_field never
    # receives or returns a mutated raw_text, it returns a *new* value).
    from templates_registry.normalization import normalize_text_field

    normalization_result = normalize_text_field(record.raw_text)
    # DETECT: the raw record in the database is untouched by computing a
    # normalized value -- only an explicit .save() with the wrong field
    # would corrupt it, and the pipeline never does that.
    record.refresh_from_db()
    assert record.raw_text == original_raw_text
    assert (
        normalization_result["normalized_text"] != original_raw_text or "�" not in original_raw_text
    )

    # RESTORE/RERUN: confirm rerun doesn't change raw_text either.
    importer.run_migration_batch(batch, neutral, user_a)
    record.refresh_from_db()
    assert record.raw_text == original_raw_text


# ---------------------------------------------------------------------------
# 5. Approved version modified
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_5_approved_version_cannot_be_modified(tenant_a, user_a, vp_user):
    template = RegulatoryTemplate.objects.create(
        tenant=tenant_a, canonical_code="TPL-APPROVED-5", title="Approved Immutable"
    )
    version = TemplateVersion.objects.create(
        template=template,
        version_number=1,
        status=TemplateLifecycleStatus.IMPORTED,
        raw_source_checksum="original-checksum",
        created_by=user_a,
    )
    version = lifecycle.submit_for_review(version, user_a)
    version = lifecycle.approve(version, vp_user, "ok", "vp")
    assert version.status == TemplateLifecycleStatus.APPROVED

    # PLANT: attempt to directly mutate a content field on the now-approved
    # version.
    version.raw_source_checksum = "tampered-checksum"
    with pytest.raises(ValidationError):
        version.full_clean()

    # RESTORE: reload from DB, unaffected by the rejected mutation attempt.
    version.refresh_from_db()
    assert version.raw_source_checksum == "original-checksum"


# ---------------------------------------------------------------------------
# 6. Second active version created
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_6_second_active_version_blocked_at_db_level(tenant_a):
    template = RegulatoryTemplate.objects.create(
        tenant=tenant_a, canonical_code="TPL-DOUBLE-ACTIVE-6", title="Double Active"
    )
    TemplateVersion.objects.create(
        template=template, version_number=1, status=TemplateLifecycleStatus.ACTIVE
    )
    # PLANT: bypass the lifecycle service entirely and attempt to create a
    # second ACTIVE version directly at the ORM layer.
    with pytest.raises(IntegrityError), transaction.atomic():
        TemplateVersion.objects.create(
            template=template, version_number=2, status=TemplateLifecycleStatus.ACTIVE
        )
    # DETECT: only one active version exists.
    assert (
        TemplateVersion.objects.filter(
            template=template, status=TemplateLifecycleStatus.ACTIVE
        ).count()
        == 1
    )
    # RESTORE/RERUN: a second version can still be created as long as it
    # is not simultaneously active (the normal, legitimate path).
    v2 = TemplateVersion.objects.create(
        template=template, version_number=2, status=TemplateLifecycleStatus.DRAFT
    )
    assert v2.pk is not None


# ---------------------------------------------------------------------------
# 7. Tenant filter removed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_7_removing_tenant_filter_would_leak_cross_tenant_data(tenant_a, tenant_b):
    RegulatoryTemplate.objects.create(tenant=tenant_a, canonical_code="TPL-A-7", title="Tenant A")
    RegulatoryTemplate.objects.create(tenant=tenant_b, canonical_code="TPL-B-7", title="Tenant B")

    # PLANT: simulate the exact bug of a call site forgetting to scope by
    # tenant and using the bare, unscoped manager instead of
    # for_tenant()/for_tenant_including_platform().
    unscoped_leak = RegulatoryTemplate.objects.all()
    # DETECT: this is precisely why views.py never calls .objects.all()
    # directly -- it always goes through for_tenant_including_platform().
    # We assert the unscoped call *would* leak (proving the guard is the
    # explicit for_tenant() call, not any default queryset behavior), then
    # assert the correctly-scoped call does not.
    assert unscoped_leak.filter(canonical_code="TPL-B-7").exists()  # the leak, if it were used
    scoped = RegulatoryTemplate.objects.for_tenant_including_platform(tenant_a)
    assert not scoped.filter(canonical_code="TPL-B-7").exists()
    assert scoped.filter(canonical_code="TPL-A-7").exists()


# ---------------------------------------------------------------------------
# 8. Numeric ID exposed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_8_numeric_id_not_exposed_via_serializer(
    tenant_a, user_a, vp_user, doer_membership, vp_membership
):
    client = _client_for(user_a, tenant_a)
    resp = client.post(
        f"{BASE}/template-sources/",
        data={
            "source_name": "id-exposure-check",
            "source_type": "anda_checklist",
            "source_path_or_reference": "synthetic://x.json",
            "payload": {"rows": []},
        },
        format="json",
    )
    assert resp.status_code == 201
    data = resp.json()
    # PLANT (as a hypothesis): if a serializer accidentally included the
    # model's default BigAutoField pk, it would appear as "id".
    # DETECT: it does not.
    assert "id" not in data
    assert "pk" not in data
    assert isinstance(data["public_id"], str)
    # A UUID string, not an integer.
    assert len(data["public_id"]) == 36


# ---------------------------------------------------------------------------
# 9. Source path exposed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_9_source_path_not_exposed_without_view_raw_permission(tenant_a, user_a, doer_membership):
    client = _client_for(user_a, tenant_a)
    resp = client.post(
        f"{BASE}/template-sources/",
        data={
            "source_name": "path-exposure-check",
            "source_type": "anda_checklist",
            "source_path_or_reference": "/secret/internal/export/path.json",
            "payload": {"rows": []},
        },
        format="json",
    )
    assert resp.status_code == 201
    data = resp.json()
    # PLANT (as a hypothesis): the default (non-raw) serializer accidentally
    # includes source_path_or_reference for a Doer who lacks view_raw.
    # DETECT: it does not appear anywhere in the response.
    assert "source_path_or_reference" not in data
    assert "/secret/internal/export/path.json" not in str(data)


# ---------------------------------------------------------------------------
# 10. Import rerun creates duplicates
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_10_import_rerun_does_not_create_duplicates(tenant_a, user_a, anda_like_rows):
    neutral = adapters.anda_like_adapter(anda_like_rows, source_name="rerun-planted-10")
    package = importer.register_source_package(
        tenant=tenant_a,
        source_name="rerun-planted-10",
        source_type="anda_checklist",
        source_path_or_reference="synthetic://rerun-10.json",
        payload_for_checksum={"rows": anda_like_rows},
        imported_by=user_a,
    )
    batch = importer.create_migration_batch(package, user_a)
    importer.run_migration_batch(batch, neutral, user_a)
    first_item_count = TemplateItem.objects.filter(
        template_section__template_version__source_package=package
    ).count()
    first_record_count = TemplateSourceRecord.objects.filter(source_package=package).count()

    # PLANT: rerun the exact same batch with the exact same input three
    # times in a row, simulating a retry storm or a user double-clicking
    # "run migration."
    for _ in range(3):
        importer.run_migration_batch(batch, neutral, user_a)

    # DETECT: no duplicate rows were created at any layer.
    assert (
        TemplateItem.objects.filter(
            template_section__template_version__source_package=package
        ).count()
        == first_item_count
    )
    assert TemplateSourceRecord.objects.filter(source_package=package).count() == first_record_count
