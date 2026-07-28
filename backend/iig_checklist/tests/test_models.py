"""Model/constraint tests for iig_checklist definition governance."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from iig_checklist.enums import (
    AnswerType,
    ChecklistVersionStatus,
    Criticality,
    DataSourceClassification,
    EvidenceRequirement,
)
from iig_checklist.models import (
    ChecklistDefinition,
    ChecklistQuestion,
    ChecklistSection,
    ChecklistVersion,
)


@pytest.mark.django_db
class TestChecklistDefinitionScope:
    def test_platform_master_requires_null_tenant(self, user_a):
        definition = ChecklistDefinition(
            code="PLATFORM-1", title="t", scope_type="platform_master", created_by=user_a
        )
        definition.full_clean()  # should not raise
        definition.save()
        assert definition.tenant_id is None

    def test_platform_master_with_tenant_rejected(self, user_a, tenant_a):
        definition = ChecklistDefinition(
            code="PLATFORM-2",
            title="t",
            scope_type="platform_master",
            tenant=tenant_a,
            created_by=user_a,
        )
        with pytest.raises(ValidationError):
            definition.full_clean()

    def test_tenant_scope_requires_tenant(self, user_a):
        definition = ChecklistDefinition(
            code="TENANT-1", title="t", scope_type="tenant", created_by=user_a
        )
        with pytest.raises(ValidationError):
            definition.full_clean()

    def test_same_code_across_scopes_does_not_conflict(self, user_a, tenant_a):
        ChecklistDefinition.objects.create(
            code="SHARED-CODE", title="platform", scope_type="platform_master", created_by=user_a
        )
        # Same literal code, tenant scope -- must not conflict.
        tenant_def = ChecklistDefinition(
            code="SHARED-CODE",
            title="tenant",
            scope_type="tenant",
            tenant=tenant_a,
            created_by=user_a,
        )
        tenant_def.full_clean()
        tenant_def.save()
        assert ChecklistDefinition.objects.filter(code="SHARED-CODE").count() == 2

    def test_duplicate_platform_master_code_rejected(self, user_a):
        ChecklistDefinition.objects.create(
            code="DUP-PLATFORM", title="a", scope_type="platform_master", created_by=user_a
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistDefinition.objects.create(
                code="DUP-PLATFORM", title="b", scope_type="platform_master", created_by=user_a
            )

    def test_duplicate_tenant_code_rejected(self, user_a, tenant_a):
        ChecklistDefinition.objects.create(
            code="DUP-TENANT", title="a", scope_type="tenant", tenant=tenant_a, created_by=user_a
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistDefinition.objects.create(
                code="DUP-TENANT",
                title="b",
                scope_type="tenant",
                tenant=tenant_a,
                created_by=user_a,
            )

    def test_same_code_different_tenants_does_not_conflict(self, user_a, tenant_a, tenant_b):
        ChecklistDefinition.objects.create(
            code="CROSS-TENANT", title="a", scope_type="tenant", tenant=tenant_a, created_by=user_a
        )
        other = ChecklistDefinition(
            code="CROSS-TENANT", title="b", scope_type="tenant", tenant=tenant_b, created_by=user_a
        )
        other.full_clean()
        other.save()


@pytest.mark.django_db
class TestChecklistVersionConstraints:
    def test_unique_version_number_per_definition(self, tenant_definition, user_a):
        ChecklistVersion.objects.create(
            definition=tenant_definition, version_number=1, created_by=user_a
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistVersion.objects.create(
                definition=tenant_definition, version_number=1, created_by=user_a
            )

    def test_one_active_version_per_definition(self, tenant_definition, user_a):
        ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=1,
            status=ChecklistVersionStatus.ACTIVE,
            created_by=user_a,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistVersion.objects.create(
                definition=tenant_definition,
                version_number=2,
                status=ChecklistVersionStatus.ACTIVE,
                created_by=user_a,
            )

    def test_expiry_must_be_after_effective(self, tenant_definition, user_a):
        version = ChecklistVersion(
            definition=tenant_definition,
            version_number=1,
            created_by=user_a,
            effective_date=date(2026, 6, 1),
            expiry_date=date(2026, 1, 1),
        )
        with pytest.raises(ValidationError):
            version.full_clean()

    def test_approved_version_content_immutable(self, draft_version, user_a):
        draft_version.status = ChecklistVersionStatus.APPROVED
        draft_version.save()
        draft_version.regulatory_basis = "changed after approval"
        with pytest.raises(ValidationError):
            draft_version.full_clean()

    def test_draft_version_content_mutable(self, draft_version, user_a):
        draft_version.regulatory_basis = "IIG guidance v3"
        draft_version.full_clean()
        draft_version.save()
        draft_version.refresh_from_db()
        assert draft_version.regulatory_basis == "IIG guidance v3"


@pytest.mark.django_db
class TestSectionQuestionScope:
    def test_section_code_unique_per_version(self, draft_version):
        ChecklistSection.objects.create(
            checklist_version=draft_version,
            code="SEC-1",
            title="s",
            display_order=1,
            criticality=Criticality.MEDIUM,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistSection.objects.create(
                checklist_version=draft_version,
                code="SEC-1",
                title="s2",
                display_order=2,
                criticality=Criticality.MEDIUM,
            )

    def test_section_display_order_unique_per_version(self, draft_version):
        ChecklistSection.objects.create(
            checklist_version=draft_version,
            code="SEC-A",
            title="s",
            display_order=1,
            criticality=Criticality.MEDIUM,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistSection.objects.create(
                checklist_version=draft_version,
                code="SEC-B",
                title="s2",
                display_order=1,
                criticality=Criticality.MEDIUM,
            )

    def test_question_code_unique_per_section(self, draft_version):
        section = ChecklistSection.objects.create(
            checklist_version=draft_version,
            code="SEC-Q",
            title="s",
            display_order=1,
            criticality=Criticality.MEDIUM,
        )
        ChecklistQuestion.objects.create(
            section=section,
            code="Q1",
            question_text="?",
            display_order=1,
            answer_type=AnswerType.SHORT_TEXT,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            criticality=Criticality.LOW,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistQuestion.objects.create(
                section=section,
                code="Q1",
                question_text="? 2",
                display_order=2,
                answer_type=AnswerType.SHORT_TEXT,
                data_source_classification=DataSourceClassification.USER_REQUIRED,
                criticality=Criticality.LOW,
            )

    def test_question_binding_rules(self, draft_version):
        section = ChecklistSection.objects.create(
            checklist_version=draft_version,
            code="SEC-B",
            title="s",
            display_order=1,
            criticality=Criticality.MEDIUM,
        )
        # SYSTEM_CALCULATED without a binding identifier is rejected.
        question = ChecklistQuestion(
            section=section,
            code="Q-CALC",
            question_text="calc",
            display_order=1,
            answer_type=AnswerType.CALCULATED_VALUE,
            data_source_classification=DataSourceClassification.SYSTEM_CALCULATED,
            criticality=Criticality.LOW,
        )
        with pytest.raises(ValidationError):
            question.full_clean()

        question.calculation_binding_identifier = "percentage_w_w"
        question.full_clean()

        # EVIDENCE_DERIVED must require evidence.
        evidence_question = ChecklistQuestion(
            section=section,
            code="Q-EVID",
            question_text="evidence",
            display_order=2,
            answer_type=AnswerType.SHORT_TEXT,
            data_source_classification=DataSourceClassification.EVIDENCE_DERIVED,
            evidence_requirement=EvidenceRequirement.NONE,
            criticality=Criticality.LOW,
        )
        with pytest.raises(ValidationError):
            evidence_question.full_clean()
        evidence_question.evidence_requirement = EvidenceRequirement.REQUIRED
        evidence_question.full_clean()

    def test_approval_metadata_cannot_be_user_authored(self, draft_version):
        section = ChecklistSection.objects.create(
            checklist_version=draft_version,
            code="SEC-C",
            title="s",
            display_order=1,
            criticality=Criticality.MEDIUM,
        )
        question = ChecklistQuestion(
            section=section,
            code="Q-APPROVAL",
            question_text="approval",
            display_order=1,
            answer_type=AnswerType.APPROVAL_METADATA,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            criticality=Criticality.LOW,
        )
        with pytest.raises(ValidationError):
            question.full_clean()

    def test_question_immutable_after_version_approved(self, draft_version):
        section = ChecklistSection.objects.create(
            checklist_version=draft_version,
            code="SEC-D",
            title="s",
            display_order=1,
            criticality=Criticality.MEDIUM,
        )
        question = ChecklistQuestion.objects.create(
            section=section,
            code="Q-IMMUT",
            question_text="q",
            display_order=1,
            answer_type=AnswerType.SHORT_TEXT,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            criticality=Criticality.LOW,
        )
        draft_version.status = ChecklistVersionStatus.APPROVED
        draft_version.save()
        question.question_text = "changed"
        with pytest.raises(ValidationError):
            question.full_clean()
