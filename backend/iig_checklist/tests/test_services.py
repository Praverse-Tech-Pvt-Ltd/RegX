"""Version-allocation concurrency and clone-service tests."""

import threading

import pytest
from django.db import connection

from iig_checklist.enums import ChecklistVersionStatus
from iig_checklist.models import ChecklistSection, ChecklistVersion
from iig_checklist.services import (
    CloneRequest,
    CloneSourceNotEligible,
    DuplicateCodeError,
    clone_definition,
    create_next_version,
)


@pytest.mark.django_db(transaction=True)
class TestConcurrentVersionAllocation:
    def test_concurrent_creation_allocates_distinct_sequential_numbers(
        self, tenant_definition, user_a
    ):
        results = []

        def create_once():
            version = create_next_version(definition=tenant_definition, actor=user_a)
            results.append(version.version_number)
            connection.close()

        threads = [threading.Thread(target=create_once) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == [1, 2]
        assert (
            ChecklistVersion.objects.filter(definition=tenant_definition).count() == 2
        )

    def test_version_number_never_client_supplied(self):
        from iig_checklist.serializers import ChecklistVersionSerializer

        assert "version_number" in ChecklistVersionSerializer.Meta.read_only_fields


@pytest.mark.django_db
class TestCloneService:
    def _approved_source(self, tenant_definition, user_a):
        version = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=1,
            status=ChecklistVersionStatus.APPROVED,
            effective_date="2026-01-01",
            created_by=user_a,
        )
        ChecklistSection.objects.create(
            checklist_version=version,
            code="SEC-1",
            title="Section 1",
            display_order=1,
            criticality="medium",
        )
        return version

    def test_clone_creates_draft_version_one(self, tenant_definition, tenant_a, user_a):
        source = self._approved_source(tenant_definition, user_a)
        result = clone_definition(
            CloneRequest(
                source_version=source,
                target_scope_type="tenant",
                target_tenant=tenant_a,
                new_code="CLONED-DEF",
                new_title="Cloned",
                actor=user_a,
            )
        )
        assert result.version.version_number == 1
        assert result.version.status == ChecklistVersionStatus.DRAFT
        assert result.definition.pk != source.definition.pk
        assert result.version.cloned_from_version_public_id == source.public_id

    def test_clone_copies_sections_with_new_public_ids(self, tenant_definition, tenant_a, user_a):
        source = self._approved_source(tenant_definition, user_a)
        source_section_pid = source.sections.first().public_id
        result = clone_definition(
            CloneRequest(
                source_version=source,
                target_scope_type="tenant",
                target_tenant=tenant_a,
                new_code="CLONED-DEF-2",
                new_title="Cloned 2",
                actor=user_a,
            )
        )
        cloned_section = result.version.sections.first()
        assert cloned_section is not None
        assert cloned_section.public_id != source_section_pid
        assert cloned_section.code == "SEC-1"

    def test_clone_source_still_draft_rejected(self, draft_version, tenant_a, user_a):
        with pytest.raises(CloneSourceNotEligible):
            clone_definition(
                CloneRequest(
                    source_version=draft_version,
                    target_scope_type="tenant",
                    target_tenant=tenant_a,
                    new_code="SHOULD-FAIL",
                    new_title="x",
                    actor=user_a,
                )
            )

    def test_clone_duplicate_code_rejected(self, tenant_definition, tenant_a, user_a):
        source = self._approved_source(tenant_definition, user_a)
        from iig_checklist.models import ChecklistDefinition

        ChecklistDefinition.objects.create(
            code="EXISTING_CODE", title="t", scope_type="tenant", tenant=tenant_a, created_by=user_a
        )
        with pytest.raises(DuplicateCodeError):
            clone_definition(
                CloneRequest(
                    source_version=source,
                    target_scope_type="tenant",
                    target_tenant=tenant_a,
                    new_code="existing code",  # normalizes to EXISTING_CODE
                    new_title="t2",
                    actor=user_a,
                )
            )

    def test_clone_atomic_rollback_leaves_no_orphans(self, tenant_definition, tenant_a, user_a):
        from iig_checklist.models import ChecklistDefinition

        source = self._approved_source(tenant_definition, user_a)
        ChecklistDefinition.objects.create(
            code="ATOMIC-DUP", title="t", scope_type="tenant", tenant=tenant_a, created_by=user_a
        )
        definitions_before = ChecklistDefinition.objects.count()
        with pytest.raises(DuplicateCodeError):
            clone_definition(
                CloneRequest(
                    source_version=source,
                    target_scope_type="tenant",
                    target_tenant=tenant_a,
                    new_code="ATOMIC-DUP",
                    new_title="t2",
                    actor=user_a,
                )
            )
        assert ChecklistDefinition.objects.count() == definitions_before

    def test_clone_provenance_and_history_not_copied(self, tenant_definition, tenant_a, user_a):
        source = self._approved_source(tenant_definition, user_a)
        source.approved_by = user_a
        source.save()
        result = clone_definition(
            CloneRequest(
                source_version=source,
                target_scope_type="tenant",
                target_tenant=tenant_a,
                new_code="NO-PROVENANCE",
                new_title="t",
                actor=user_a,
            )
        )
        assert result.version.approved_by_id is None
        assert result.version.submitted_by_id is None
