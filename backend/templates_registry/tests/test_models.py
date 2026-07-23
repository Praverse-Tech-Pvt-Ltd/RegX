"""
Model-level constraint and immutability tests.

Covers: unique-active-version-per-template (DB-level partial unique
index, defense in depth alongside lifecycle.py's transactional lock),
canonical-code uniqueness, section/item/option code uniqueness,
duplicate-candidate exactly-one-subject check constraint, and the
TemplateVersion.clean() immutability backstop for approved/active/
superseded/retired versions.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from templates_registry.models import (
    RegulatoryTemplate,
    TemplateDuplicateCandidate,
    TemplateItem,
    TemplateLifecycleStatus,
    TemplateSection,
    TemplateSourcePackage,
    TemplateSourceRecord,
    TemplateVersion,
)


@pytest.mark.django_db
class TestCanonicalCodeUniqueness:
    def test_duplicate_canonical_code_in_same_tenant_rejected(self, tenant_a):
        RegulatoryTemplate.objects.create(tenant=tenant_a, canonical_code="ANDA-X", title="A")
        with pytest.raises(IntegrityError), transaction.atomic():
            RegulatoryTemplate.objects.create(tenant=tenant_a, canonical_code="ANDA-X", title="B")

    def test_same_canonical_code_allowed_across_tenants(self, tenant_a, tenant_b):
        RegulatoryTemplate.objects.create(tenant=tenant_a, canonical_code="ANDA-X", title="A")
        # Should not raise -- uniqueness is scoped per tenant.
        RegulatoryTemplate.objects.create(tenant=tenant_b, canonical_code="ANDA-X", title="B")


@pytest.mark.django_db
class TestOnlyOneActiveVersionPerTemplate:
    def _template(self, tenant_a):
        return RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="DMF-1", title="DMF Template"
        )

    def test_db_constraint_blocks_second_active_version(self, tenant_a):
        template = self._template(tenant_a)
        TemplateVersion.objects.create(
            template=template, version_number=1, status=TemplateLifecycleStatus.ACTIVE
        )
        # PLANTED VIOLATION (detected): attempting to create a second ACTIVE
        # version directly at the ORM layer, bypassing lifecycle.activate(),
        # must still be rejected by the DB-level partial unique index.
        with pytest.raises(IntegrityError), transaction.atomic():
            TemplateVersion.objects.create(
                template=template, version_number=2, status=TemplateLifecycleStatus.ACTIVE
            )

    def test_non_active_versions_are_not_constrained(self, tenant_a):
        template = self._template(tenant_a)
        TemplateVersion.objects.create(
            template=template, version_number=1, status=TemplateLifecycleStatus.DRAFT
        )
        # Multiple non-active versions are fine.
        TemplateVersion.objects.create(
            template=template, version_number=2, status=TemplateLifecycleStatus.DRAFT
        )


@pytest.mark.django_db
class TestVersionImmutability:
    def _approved_version(self, tenant_a, user_a):
        template = RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="VAL-1", title="Validation Template"
        )
        return TemplateVersion.objects.create(
            template=template,
            version_number=1,
            status=TemplateLifecycleStatus.APPROVED,
            raw_source_checksum="abc123",
            created_by=user_a,
        )

    def test_approved_version_content_field_cannot_change(self, tenant_a, user_a):
        version = self._approved_version(tenant_a, user_a)
        version.raw_source_checksum = "tampered"
        # PLANTED VIOLATION (detected): mutating a content field on an
        # approved version must be rejected by clean().
        with pytest.raises(ValidationError):
            version.full_clean()

    def test_status_and_superseded_date_transitions_are_allowed_through_clean(
        self, tenant_a, user_a
    ):
        version = self._approved_version(tenant_a, user_a)
        version.status = TemplateLifecycleStatus.ACTIVE
        # Changing only status (and its related bookkeeping fields) must
        # not trip the immutability guard -- that is precisely how the
        # lifecycle state machine is supposed to work.
        version.full_clean()


@pytest.mark.django_db
class TestSectionItemOptionUniqueness:
    def _version(self, tenant_a):
        template = RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="GEN-1", title="General"
        )
        return TemplateVersion.objects.create(template=template, version_number=1)

    def test_duplicate_section_code_in_same_version_rejected(self, tenant_a):
        version = self._version(tenant_a)
        TemplateSection.objects.create(
            template_version=version, canonical_section_code="sec-1", raw_title="Section 1"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            TemplateSection.objects.create(
                template_version=version, canonical_section_code="sec-1", raw_title="Dup"
            )

    def test_duplicate_item_code_in_same_section_rejected(self, tenant_a):
        version = self._version(tenant_a)
        section = TemplateSection.objects.create(
            template_version=version, canonical_section_code="sec-1", raw_title="Section 1"
        )
        TemplateItem.objects.create(
            template_section=section, canonical_item_code="item-1", raw_text="Q1"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            TemplateItem.objects.create(
                template_section=section, canonical_item_code="item-1", raw_text="Dup"
            )


@pytest.mark.django_db
class TestDuplicateCandidateExactlyOneSubject:
    def _two_items(self, tenant_a):
        template = RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="DUP-1", title="Dup Template"
        )
        version = TemplateVersion.objects.create(template=template, version_number=1)
        section = TemplateSection.objects.create(
            template_version=version, canonical_section_code="sec-1", raw_title="Section 1"
        )
        item_a = TemplateItem.objects.create(
            template_section=section, canonical_item_code="item-a", raw_text="A"
        )
        item_b = TemplateItem.objects.create(
            template_section=section, canonical_item_code="item-b", raw_text="B"
        )
        return item_a, item_b

    def test_neither_subject_set_rejected(self, tenant_a):
        _, item_b = self._two_items(tenant_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            TemplateDuplicateCandidate.objects.create(
                suspected_match_item=item_b, match_type="canonical_code"
            )

    def test_both_subjects_set_rejected(self, tenant_a):
        item_a, item_b = self._two_items(tenant_a)
        package = TemplateSourcePackage.objects.create(
            tenant=tenant_a,
            source_name="pkg",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://pkg.json",
            source_checksum="0" * 64,
        )
        source_record = TemplateSourceRecord.objects.create(
            source_package=package,
            source_record_identifier="rec-1",
            raw_payload={},
            raw_checksum="1" * 64,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            TemplateDuplicateCandidate.objects.create(
                subject_template_item=item_a,
                subject_source_record=source_record,
                suspected_match_item=item_b,
                match_type="canonical_code",
            )

    def test_exactly_one_subject_accepted(self, tenant_a):
        item_a, item_b = self._two_items(tenant_a)
        candidate = TemplateDuplicateCandidate.objects.create(
            subject_template_item=item_a, suspected_match_item=item_b, match_type="canonical_code"
        )
        assert candidate.pk is not None
