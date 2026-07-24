"""
Import pipeline tests: registration/classification exclusion guards,
extraction idempotency, normalization correctness (mojibake, HTML,
embedded numbering), duplicate-candidate generation, and rerun safety.
"""

import pytest

from templates_registry import adapters, importer
from templates_registry.classification import ExclusionReason
from templates_registry.models import (
    MigrationRecordResult,
    MigrationRecordResultType,
    NormalizationMapping,
    TemplateDuplicateCandidate,
    TemplateItem,
    TemplateSourcePackage,
    TemplateSourceRecord,
)
from templates_registry.normalization import normalize_text_field


def _dmf_adapter(rows, source_name):
    return adapters.dmf_like_adapter(
        rows, source_name=source_name, table_hint="dmfreviewtablequestion"
    )


def _register_and_run(tenant, user, rows, adapter, source_name):
    neutral = adapter(rows, source_name=source_name)
    package = importer.register_source_package(
        tenant=tenant,
        source_name=source_name,
        source_type="anda_checklist",
        source_path_or_reference=f"synthetic://{source_name}.json",
        payload_for_checksum={"rows": rows},
        imported_by=user,
    )
    batch = importer.create_migration_batch(package, user)
    importer.run_migration_batch(batch, neutral, user)
    return package, batch


@pytest.mark.django_db
class TestSourcePackageExclusionGuards:
    def test_483_source_type_rejected(self, tenant_a, user_a):
        # PLANTED VIOLATION (detected): registering a package explicitly
        # typed as 483 content.
        with pytest.raises(importer.SourceExcluded):
            importer.register_source_package(
                tenant=tenant_a,
                source_name="form483-export",
                source_type="form483",
                source_path_or_reference="synthetic://form483.json",
                payload_for_checksum={"rows": []},
                imported_by=user_a,
            )
        assert not TemplateSourcePackage.objects.filter(source_name="form483-export").exists()

    def test_aidatabase_source_type_rejected(self, tenant_a, user_a):
        # PLANTED VIOLATION (detected): registering a package sourced from
        # AIDatabase must never succeed, regardless of declared name.
        with pytest.raises(importer.SourceExcluded):
            importer.register_source_package(
                tenant=tenant_a,
                source_name="legacy export",
                source_type="aidatabase",
                source_path_or_reference="synthetic://aid.json",
                payload_for_checksum={"rows": []},
                imported_by=user_a,
            )

    def test_aidatabase_named_source_rejected_even_with_neutral_type(self, tenant_a, user_a):
        # PLANTED VIOLATION (detected): source_type looks benign but the
        # name itself carries an AIDatabase marker.
        with pytest.raises(importer.SourceExcluded):
            importer.register_source_package(
                tenant=tenant_a,
                source_name="AIDatabase full export",
                source_type="generic_export",
                source_path_or_reference="synthetic://x.json",
                payload_for_checksum={"rows": []},
                imported_by=user_a,
            )

    def test_eligible_source_type_accepted(self, tenant_a, user_a):
        package = importer.register_source_package(
            tenant=tenant_a,
            source_name="anda-export",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://anda.json",
            payload_for_checksum={"rows": []},
            imported_by=user_a,
        )
        assert package.pk is not None


@pytest.mark.django_db
class TestRecordLevelExclusion:
    def test_483_row_excluded_during_classification(self, tenant_a, user_a, excluded_483_row):
        package, batch = _register_and_run(
            tenant_a, user_a, [excluded_483_row], adapters.anda_like_adapter, "mixed-483"
        )
        result = MigrationRecordResult.objects.get(batch=batch)
        # PLANTED VIOLATION (detected): a 483 observation row must never
        # reach IMPORTED status.
        assert result.result == MigrationRecordResultType.EXCLUDED
        assert result.reason_code == ExclusionReason.FORM_483_OR_WARNING_LETTER
        assert not TemplateItem.objects.filter(raw_text__icontains="483").exists()

    def test_aidatabase_identifier_row_excluded(self, tenant_a, user_a, excluded_aidatabase_row):
        package, batch = _register_and_run(
            tenant_a, user_a, [excluded_aidatabase_row], adapters.anda_like_adapter, "mixed-aid"
        )
        result = MigrationRecordResult.objects.get(batch=batch)
        assert result.result == MigrationRecordResultType.EXCLUDED
        assert result.reason_code == ExclusionReason.AIDATABASE_SOURCED

    def test_eligible_rows_are_imported(self, tenant_a, user_a, anda_like_rows):
        package, batch = _register_and_run(
            tenant_a, user_a, anda_like_rows, adapters.anda_like_adapter, "anda-clean"
        )
        results = list(MigrationRecordResult.objects.filter(batch=batch))
        assert len(results) == 2
        assert all(r.result == MigrationRecordResultType.IMPORTED for r in results)
        assert TemplateItem.objects.count() == 2


@pytest.mark.django_db
class TestImportedContentStartsInactive:
    def test_imported_version_is_never_active(self, tenant_a, user_a, anda_like_rows):
        _, batch = _register_and_run(
            tenant_a, user_a, anda_like_rows, adapters.anda_like_adapter, "anda-inactive"
        )
        item = TemplateItem.objects.first()
        version = item.template_section.template_version
        # PLANTED VIOLATION (detected): the import pipeline must never
        # auto-activate a version.
        assert version.status in ("draft", "imported")
        assert version.template.current_approved_version_id is None


@pytest.mark.django_db
class TestNormalization:
    def test_mojibake_repaired_without_losing_raw_category(self, tenant_a, user_a, mojibake_row):
        _, batch = _register_and_run(tenant_a, user_a, [mojibake_row], _dmf_adapter, "mojibake-src")
        record = TemplateSourceRecord.objects.get(source_package=batch.source_package)
        # PLANTED VIOLATION (detected): the raw mojibake-corrupted category
        # value ("DO�S") must be preserved verbatim in the source
        # record's payload even though the template's normalized category
        # is repaired.
        assert record.raw_payload["fields"]["template_category"] == mojibake_row["category"]
        assert "�" in record.raw_payload["fields"]["template_category"]

        template = TemplateItem.objects.get(
            template_section__template_version__source_package=batch.source_package
        ).template_section.template_version.template
        assert "�" not in template.category

        mapping = NormalizationMapping.objects.get(
            source_record=record, normalization_rule="mojibake_repair_and_whitespace_collapse"
        )
        assert mapping.raw_value == mojibake_row["category"]
        assert "�" not in mapping.normalized_value

    def test_html_stripped_and_numbering_split_out(self, tenant_a, user_a, html_and_numbering_row):
        _, batch = _register_and_run(
            tenant_a,
            user_a,
            [html_and_numbering_row],
            _dmf_adapter,
            "html-numbering-src",
        )
        item = TemplateItem.objects.get(
            template_section__template_version__source_package=batch.source_package
        )
        assert "<p>" not in item.normalized_text
        assert "<br" not in item.normalized_text
        assert not item.normalized_text.startswith("1.")
        assert item.metadata["numbering_prefix"] == "1"
        # Raw text is untouched.
        assert "<p>" in item.raw_text

    def test_normalize_text_field_is_pure_and_non_destructive(self):
        raw = "<p>1. Hello World<br />\r\nLine two</p>"
        result = normalize_text_field(raw)
        assert result["normalized_text"] == "Hello World\n\nLine two"
        assert result["numbering_prefix"] == "1"
        # Calling again with the same input yields the same output
        # (pure function -- required for idempotent reruns).
        assert normalize_text_field(raw) == result

    def test_category_typo_requires_explicit_reviewed_mapping(self, tenant_a, user_a):
        row = {
            "id": 500,
            "module": "General",
            "category": "Fromulation",  # typo, deliberately not auto-corrected
            "question": "<p>Some question.</p>",
        }
        _, batch = _register_and_run(tenant_a, user_a, [row], _dmf_adapter, "typo-src")
        template = TemplateItem.objects.get(
            template_section__template_version__source_package=batch.source_package
        ).template_section.template_version.template
        # PLANTED VIOLATION (detected): a category typo must not be
        # silently "fixed" by guesswork -- only a reviewed mapping table
        # entry may change it.
        assert template.category == "Fromulation"


@pytest.mark.django_db
class TestMissingLocatorAndMalformedRows:
    def test_missing_locator_row_still_imports_under_general_bucket(
        self, tenant_a, user_a, missing_locator_row
    ):
        _, batch = _register_and_run(
            tenant_a, user_a, [missing_locator_row], adapters.anda_like_adapter, "missing-locator"
        )
        result = MigrationRecordResult.objects.get(batch=batch)
        assert result.result in (
            MigrationRecordResultType.IMPORTED,
            MigrationRecordResultType.REQUIRES_REVIEW,
        )

    def test_malformed_row_records_failed_result_without_aborting_batch(
        self, tenant_a, user_a, anda_like_rows
    ):
        neutral = adapters.anda_like_adapter(anda_like_rows, source_name="mixed-malformed")
        neutral.append(
            {
                "identifier": "raw-malformed-1",
                "raw_text": "",
                "raw_payload": {},
                "locator": "",
                "extraction_method": "controlled_export_json",
                "encoding": "utf-8",
                "fields": {"required": "not-a-bool-but-truthy"},
            }
        )
        package = importer.register_source_package(
            tenant=tenant_a,
            source_name="mixed-malformed",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://mixed-malformed.json",
            payload_for_checksum={"rows": anda_like_rows},
            imported_by=user_a,
        )
        batch = importer.create_migration_batch(package, user_a)
        importer.run_migration_batch(batch, neutral, user_a)
        results = MigrationRecordResult.objects.filter(batch=batch)
        # Every record gets exactly one result; nothing is silently dropped.
        assert results.count() == len(neutral)


@pytest.mark.django_db
class TestDuplicateDetection:
    def test_duplicate_normalized_text_flagged_for_review_not_auto_collapsed(
        self, tenant_a, user_a, duplicate_rows
    ):
        _, batch = _register_and_run(
            tenant_a, user_a, duplicate_rows, adapters.anda_like_adapter, "dup-src"
        )
        results = list(MigrationRecordResult.objects.filter(batch=batch))
        assert any(r.result == MigrationRecordResultType.REQUIRES_REVIEW for r in results)
        candidates = TemplateDuplicateCandidate.objects.all()
        # PLANTED VIOLATION (detected): duplicate detection must never
        # silently merge/delete either item -- both rows still exist as
        # independent TemplateItem rows pending human review.
        assert candidates.count() >= 1
        assert TemplateItem.objects.count() == 2
        assert candidates.first().resolution == "pending"


@pytest.mark.django_db
class TestIdempotentRerun:
    def test_rerunning_same_batch_creates_no_duplicate_rows(self, tenant_a, user_a, anda_like_rows):
        neutral = adapters.anda_like_adapter(anda_like_rows, source_name="rerun-src")
        package = importer.register_source_package(
            tenant=tenant_a,
            source_name="rerun-src",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://rerun-src.json",
            payload_for_checksum={"rows": anda_like_rows},
            imported_by=user_a,
        )
        batch = importer.create_migration_batch(package, user_a)
        importer.run_migration_batch(batch, neutral, user_a)

        item_count_after_first_run = TemplateItem.objects.count()
        record_count_after_first_run = TemplateSourceRecord.objects.count()
        result_count_after_first_run = MigrationRecordResult.objects.filter(batch=batch).count()

        # PLANTED VIOLATION (detected): rerunning the exact same batch with
        # the exact same neutral records must not create duplicate
        # TemplateSourceRecord, MigrationRecordResult, or TemplateItem rows.
        importer.run_migration_batch(batch, neutral, user_a)

        assert TemplateItem.objects.count() == item_count_after_first_run
        assert TemplateSourceRecord.objects.count() == record_count_after_first_run
        assert (
            MigrationRecordResult.objects.filter(batch=batch).count()
            == result_count_after_first_run
        )

    def test_rerun_across_two_batches_for_same_package_does_not_duplicate_items(
        self, tenant_a, user_a, anda_like_rows
    ):
        neutral = adapters.anda_like_adapter(anda_like_rows, source_name="rerun-src-2")
        package = importer.register_source_package(
            tenant=tenant_a,
            source_name="rerun-src-2",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://rerun-src-2.json",
            payload_for_checksum={"rows": anda_like_rows},
            imported_by=user_a,
        )
        batch1 = importer.create_migration_batch(package, user_a)
        importer.run_migration_batch(batch1, neutral, user_a)
        item_count = TemplateItem.objects.count()

        batch2 = importer.create_migration_batch(package, user_a)
        importer.run_migration_batch(batch2, neutral, user_a)
        assert TemplateItem.objects.count() == item_count
