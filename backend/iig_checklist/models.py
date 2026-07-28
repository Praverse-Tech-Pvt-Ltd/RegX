"""Checklist definition-governance models -- Milestone 4D-1.

Scope: authoring and governing checklist *content* (definitions,
versions, sections, questions, applicability rules). No execution
model exists here (ChecklistExecution/ChecklistResponse/
CalculationOutcome are later Milestone 4D stages, see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §1).

ChecklistDefinition is a stable identity (code + scope); ChecklistVersion
carries the reviewed/approved/active lifecycle. This split, and the
lifecycle's RETURNED/REJECTED refinement over the originally-approved
design, are both disclosed and approved -- see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §3a/§6a and
docs/MILESTONE_4D_1_SPEC_REMEDIATION.md (SR-01).
"""

from django.core.exceptions import ValidationError
from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .enums import (
    AnswerType,
    ApplicabilityOutcome,
    ApplicabilityRuleStatus,
    ChecklistScopeType,
    ChecklistVersionStatus,
    Criticality,
    DataSourceClassification,
    EvidenceRequirement,
)
from .managers import (
    ChecklistDefinitionManager,
    ChecklistQuestionManager,
    ChecklistSectionManager,
    ChecklistVersionManager,
)


class ChecklistDefinition(PublicIDModel, TimeStampedModel):
    """Stable identity a version attaches to. Never itself carries a
    lifecycle status -- only its versions do (see module docstring)."""

    code = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    scope_type = models.CharField(max_length=20, choices=ChecklistScopeType.choices)
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="checklist_definitions",
    )
    created_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="+"
    )

    objects = ChecklistDefinitionManager()

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type=ChecklistScopeType.PLATFORM_MASTER, tenant__isnull=True)
                    | models.Q(scope_type=ChecklistScopeType.TENANT, tenant__isnull=False)
                ),
                name="checklist_definition_scope_tenant_consistency",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(scope_type=ChecklistScopeType.PLATFORM_MASTER),
                name="unique_platform_master_checklist_code",
            ),
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=models.Q(scope_type=ChecklistScopeType.TENANT),
                name="unique_tenant_checklist_code",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.scope_type})"


class ChecklistVersion(PublicIDModel, TimeStampedModel):
    definition = models.ForeignKey(
        ChecklistDefinition, on_delete=models.PROTECT, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=ChecklistVersionStatus.choices,
        default=ChecklistVersionStatus.DRAFT,
        db_index=True,
    )
    effective_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    regulatory_basis = models.CharField(max_length=500, blank=True)
    change_summary = models.TextField(blank=True)
    # Audit-trail readability only -- deliberately NOT a ForeignKey, so
    # retiring/deleting the source version years later can never cascade
    # into or block operations on a clone. See §8a of the spec.
    cloned_from_version_public_id = models.UUIDField(null=True, blank=True)

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    submitted_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    returned_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.TextField(blank=True)
    rejected_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes"
    )

    objects = ChecklistVersionManager()

    class Meta:
        ordering = ["definition", "version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "version_number"],
                name="unique_version_number_per_definition",
            ),
            models.UniqueConstraint(
                fields=["definition"],
                condition=models.Q(status=ChecklistVersionStatus.ACTIVE),
                name="unique_active_version_per_definition",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(expiry_date__isnull=True)
                    | models.Q(effective_date__isnull=True)
                    | models.Q(expiry_date__gt=models.F("effective_date"))
                ),
                name="checklist_version_expiry_after_effective",
            ),
        ]

    def __str__(self):
        return f"{self.definition.code} v{self.version_number} [{self.status}]"

    def is_editable(self) -> bool:
        return self.status in (
            ChecklistVersionStatus.DRAFT,
            ChecklistVersionStatus.RETURNED,
        )

    def clean(self):
        super().clean()
        if self.pk:
            try:
                original = ChecklistVersion.objects.get(pk=self.pk)
            except ChecklistVersion.DoesNotExist:
                original = None
            if original and not original.is_editable():
                # Only the lifecycle-transition service may mutate a
                # non-editable version, and only its own governed fields
                # (status + provenance) -- never content-adjacent fields.
                immutable_fields = [
                    "definition_id",
                    "version_number",
                    "effective_date",
                    "expiry_date",
                    "regulatory_basis",
                    "change_summary",
                    "cloned_from_version_public_id",
                ]
                for field_name in immutable_fields:
                    if getattr(self, field_name) != getattr(original, field_name):
                        raise ValidationError(
                            f"Cannot modify {field_name!r} once a ChecklistVersion "
                            f"leaves draft/returned (current status: {original.status!r})."
                        )


class ApplicabilityRule(PublicIDModel, TimeStampedModel):
    """Version-scoped and immutable once approved -- reuse across
    versions is via controlled cloning, never a shared mutable row.
    See spec §3e."""

    checklist_version = models.ForeignKey(
        ChecklistVersion, on_delete=models.CASCADE, related_name="applicability_rules"
    )
    code = models.CharField(max_length=100)
    rule_version = models.PositiveIntegerField(default=1)
    condition_json = models.JSONField()
    outcome_if_true = models.CharField(max_length=20, choices=ApplicabilityOutcome.choices)
    outcome_if_false = models.CharField(max_length=20, choices=ApplicabilityOutcome.choices)
    reason_code = models.CharField(max_length=100)
    explanation_template = models.CharField(max_length=500)
    field_registry_version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=ApplicabilityRuleStatus.choices,
        default=ApplicabilityRuleStatus.DRAFT,
    )
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["checklist_version", "code", "rule_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["checklist_version", "code", "rule_version"],
                name="unique_applicability_rule_code_version_per_checklist_version",
            ),
        ]

    def __str__(self):
        return f"{self.code} v{self.rule_version}"

    def clean(self):
        super().clean()
        if not self.checklist_version.is_editable() and self.pk:
            raise ValidationError(
                "Cannot modify an ApplicabilityRule once its ChecklistVersion "
                "leaves draft/returned."
            )
        from .applicability import ApplicabilityRuleValidationError, validate_condition_json
        from .field_registry import is_known_registry_version

        if not is_known_registry_version(self.field_registry_version):
            raise ValidationError(
                f"Unknown field_registry_version: {self.field_registry_version!r}."
            )
        try:
            validate_condition_json(self.condition_json, self.field_registry_version)
        except ApplicabilityRuleValidationError as exc:
            raise ValidationError(f"{exc.error_code}: {exc}") from exc


class ChecklistSection(PublicIDModel, TimeStampedModel):
    checklist_version = models.ForeignKey(
        ChecklistVersion, on_delete=models.CASCADE, related_name="sections"
    )
    code = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField()
    applicability_rule = models.ForeignKey(
        ApplicabilityRule, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    criticality = models.CharField(max_length=20, choices=Criticality.choices)

    objects = ChecklistSectionManager()

    class Meta:
        ordering = ["checklist_version", "display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["checklist_version", "code"], name="unique_iig_section_code_per_version"
            ),
            models.UniqueConstraint(
                fields=["checklist_version", "display_order"],
                name="unique_iig_section_display_order_per_version",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.checklist_version})"

    def clean(self):
        super().clean()
        if self.applicability_rule_id and self.applicability_rule.checklist_version_id != self.checklist_version_id:
            raise ValidationError("applicability_rule must belong to the same checklist_version.")
        if not self.checklist_version.is_editable() and self.pk:
            raise ValidationError(
                "Cannot modify a ChecklistSection once its ChecklistVersion "
                "leaves draft/returned."
            )


class ChecklistQuestion(PublicIDModel, TimeStampedModel):
    section = models.ForeignKey(ChecklistSection, on_delete=models.CASCADE, related_name="questions")
    code = models.CharField(max_length=100)
    question_text = models.TextField()
    help_text = models.TextField(blank=True)
    display_order = models.PositiveIntegerField()
    answer_type = models.CharField(max_length=40, choices=AnswerType.choices)
    data_source_classification = models.CharField(
        max_length=30, choices=DataSourceClassification.choices
    )
    applicability_rule = models.ForeignKey(
        ApplicabilityRule, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    required = models.BooleanField(default=False)
    allowed_units = models.JSONField(default=list, blank=True)
    evidence_requirement = models.CharField(
        max_length=30,
        choices=EvidenceRequirement.choices,
        default=EvidenceRequirement.NONE,
    )
    calculation_binding_identifier = models.CharField(max_length=100, blank=True)
    prefill_source = models.CharField(max_length=100, blank=True)
    reviewer_confirmation_required = models.BooleanField(default=False)
    escalation_rule_identifier = models.CharField(max_length=100, blank=True)
    criticality = models.CharField(max_length=20, choices=Criticality.choices)
    regulatory_reference = models.CharField(max_length=500, blank=True)
    default_value_binding = models.CharField(max_length=100, blank=True)
    validation_rule = models.JSONField(default=dict, blank=True)

    objects = ChecklistQuestionManager()

    class Meta:
        ordering = ["section", "display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"], name="unique_iig_question_code_per_section"
            ),
            models.UniqueConstraint(
                fields=["section", "display_order"],
                name="unique_iig_question_display_order_per_section",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.section})"

    def clean(self):
        super().clean()
        from .compatibility import is_allowed

        if not is_allowed(self.answer_type, self.data_source_classification):
            raise ValidationError(
                f"answer_type={self.answer_type!r} is not permitted with "
                f"data_source_classification={self.data_source_classification!r}."
            )
        if (
            self.calculation_binding_identifier
            and self.data_source_classification != DataSourceClassification.SYSTEM_CALCULATED
        ):
            raise ValidationError(
                "calculation_binding_identifier may only be set when "
                "data_source_classification is SYSTEM_CALCULATED."
            )
        if (
            self.data_source_classification == DataSourceClassification.SYSTEM_CALCULATED
            and not self.calculation_binding_identifier
        ):
            raise ValidationError(
                "SYSTEM_CALCULATED questions require a calculation_binding_identifier."
            )
        if (
            self.data_source_classification == DataSourceClassification.EVIDENCE_DERIVED
            and self.evidence_requirement != EvidenceRequirement.REQUIRED
        ):
            raise ValidationError(
                "EVIDENCE_DERIVED questions must have evidence_requirement=required."
            )
        if (
            self.data_source_classification == DataSourceClassification.REVIEWER_CONFIRMED
            and not self.reviewer_confirmation_required
        ):
            raise ValidationError(
                "REVIEWER_CONFIRMED questions must have reviewer_confirmation_required=True."
            )
        if (
            self.applicability_rule_id
            and self.applicability_rule.checklist_version_id != self.section.checklist_version_id
        ):
            raise ValidationError("applicability_rule must belong to the same checklist_version.")
        if not self.section.checklist_version.is_editable() and self.pk:
            raise ValidationError(
                "Cannot modify a ChecklistQuestion once its ChecklistVersion "
                "leaves draft/returned."
            )
