"""Checklist definition-governance models -- Milestone 4D-1.
Execution, response and outcome models -- Milestone 4D-2.

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

import json

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import PublicIDModel, TimeStampedModel

from .enums import (
    AnswerType,
    ApplicabilityOutcome,
    ApplicabilityRuleStatus,
    CalculationStatus,
    ChecklistScopeType,
    ChecklistVersionStatus,
    Criticality,
    DataSourceClassification,
    EvidenceRequirement,
    ExecutionStatus,
)
from .execution_constants import (
    MAX_NOT_APPLICABLE_REASON_CHARS,
    MAX_RAW_VALUE_BYTES,
    MAX_RETURN_REASON_CHARS,
    MAX_REVIEWER_CONCLUSION_CHARS,
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
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

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
        if (
            self.applicability_rule_id
            and self.applicability_rule.checklist_version_id != self.checklist_version_id
        ):
            raise ValidationError("applicability_rule must belong to the same checklist_version.")
        if not self.checklist_version.is_editable() and self.pk:
            raise ValidationError(
                "Cannot modify a ChecklistSection once its ChecklistVersion leaves draft/returned."
            )


class ChecklistQuestion(PublicIDModel, TimeStampedModel):
    section = models.ForeignKey(
        ChecklistSection, on_delete=models.CASCADE, related_name="questions"
    )
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
                "Cannot modify a ChecklistQuestion once its ChecklistVersion leaves draft/returned."
            )


# ---------------------------------------------------------------------------
# Milestone 4D-2 -- Execution, Response and Outcome models
# ---------------------------------------------------------------------------

_CALCULATION_NAMES = frozenset(
    {
        "calculate_percentage_w_w",
        "calculate_daily_exposure",
        "calculate_percentage_of_potency",
        "calculate_difference_from_potency",
        "calculate_percentage_of_mde",
        "calculate_difference_from_mde",
    }
)

_GOVERNED_VERSION_PARTS = 3


def _is_governed_version(value) -> bool:
    """A three-part numeric version, matching the registry's own rule."""
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return len(parts) == _GOVERNED_VERSION_PARTS and all(p.isdigit() for p in parts)


def _is_canonical_uuid(value) -> bool:
    """Canonical lowercase hyphenated rendering only (M4D3-PRV-005)."""
    import uuid as uuid_module

    if not isinstance(value, str):
        return False
    try:
        parsed = uuid_module.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value


def _has_input_descriptor(provenance: dict) -> bool:
    """True when provenance carries something beyond the reserved keys.

    M4D3-PRV-002 requires the reserved binding version "alongside a per-input
    source descriptor", so a completed outcome whose provenance holds only
    reserved keys has recorded no inputs at all.
    """
    from .calculation_translation import RESERVED_PROVENANCE_KEYS

    return any(key not in RESERVED_PROVENANCE_KEYS for key in provenance)


def _registry_entry_for_calculation(calculation_name: str):
    """Resolve the approved entry by its calculation function name.

    The registry is keyed by binding identifier, and ``_validate_registry()``
    guarantees each entry's ``calculation_name`` is unique, so this reverse
    lookup is unambiguous. Server registry only -- nothing client-controlled.
    """
    from .calculation_registry import CALCULATION_BINDING_REGISTRY

    for entry in CALCULATION_BINDING_REGISTRY.values():
        if entry.calculation_name == calculation_name:
            return entry
    return None


def _entry_is_component_scoped(entry) -> bool:
    """M4D3-PRV-007 -- the entry declares a component selector."""
    return any(
        declaration.get("component_selector") is not None
        for declaration in entry.input_resolvers.values()
    )


def _entry_inherits_component(entry) -> bool:
    """Consumes an upstream outcome, so it inherits that component
    (M4D3-MAP-010) and may legitimately record one without a selector."""
    return bool(entry.calculation_dependencies)


class ChecklistExecutionManager(models.Manager):
    def visible_to(self, tenant):
        """Tenant-scoped -- executions are never platform-scoped."""
        return self.get_queryset().filter(tenant=tenant)


class ChecklistExecution(PublicIDModel, TimeStampedModel):
    """A tenant's execution of a specific ChecklistVersion against a
    specific FormulationVersion."""

    objects = ChecklistExecutionManager()

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    checklist_version = models.ForeignKey(ChecklistVersion, on_delete=models.PROTECT)
    formulation_version = models.ForeignKey(
        "formulations.FormulationVersion",
        on_delete=models.PROTECT,
        related_name="checklist_executions",
    )
    status = models.CharField(
        max_length=30,
        choices=ExecutionStatus.choices,
        default=ExecutionStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="+",
    )
    submitted_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    returned_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    returned_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.TextField(blank=True, max_length=MAX_RETURN_REASON_CHARS)
    approved_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
    )
    reviewer_conclusion_note = models.TextField(
        blank=True,
        max_length=MAX_REVIEWER_CONCLUSION_CHARS,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "checklist_version", "formulation_version"],
                condition=~Q(status__in=["rejected", "cancelled", "superseded"]),
                name="unique_active_execution_per_version_formulation",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["checklist_version"]),
        ]


class ChecklistResponse(PublicIDModel, TimeStampedModel):
    """Pre-created response slot per applicable question per execution."""

    execution = models.ForeignKey(
        ChecklistExecution,
        on_delete=models.PROTECT,
        related_name="responses",
    )
    question = models.ForeignKey(
        ChecklistQuestion,
        on_delete=models.PROTECT,
        related_name="+",
    )
    data_source_type_snapshot = models.CharField(max_length=50)
    raw_value = models.JSONField(null=True, blank=True)
    is_not_applicable = models.BooleanField(default=False)
    not_applicable_reason = models.CharField(
        null=True,
        blank=True,
        max_length=MAX_NOT_APPLICABLE_REASON_CHARS,
    )
    entered_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    entered_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    override_reason = models.TextField(blank=True)
    system_derived_value = models.JSONField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "question"],
                name="unique_response_per_question_per_execution",
            )
        ]
        indexes = [
            models.Index(fields=["execution"]),
        ]

    def clean(self):
        # 1. Immutability when execution is not in a mutable state.
        if self.pk is not None and self.execution_id is not None:
            try:
                exec_status = self.execution.status
            except Exception:
                exec_status = None
            if exec_status not in {"draft", "returned"}:
                # reviewer_conclusion responses may be updated during
                # submitted_for_review via the dedicated
                # enter_reviewer_conclusion() service only.  All other
                # answer types and all other non-mutable statuses remain
                # unconditionally immutable here.
                _is_rc_under_review = False
                if exec_status == "submitted_for_review":
                    try:
                        _is_rc_under_review = (
                            self.question.answer_type == AnswerType.REVIEWER_CONCLUSION
                        )
                    except Exception:
                        _is_rc_under_review = False
                if not _is_rc_under_review:
                    raise ValidationError("response_immutable")

        # 2. is_not_applicable=True implies raw_value must be null.
        if self.is_not_applicable and self.raw_value is not None:
            raise ValidationError("raw_value must be null when is_not_applicable is True.")

        # 3. not_applicable_reason required when is_not_applicable=True.
        if self.is_not_applicable and not (self.not_applicable_reason or "").strip():
            raise ValidationError("not_applicable_requires_reason")

        # 4. override_reason required when system_derived_value is not null.
        if self.system_derived_value is not None and not (self.override_reason or "").strip():
            raise ValidationError(
                "override_reason must be non-empty when system_derived_value is set."
            )

        # 5. Payload byte limit on raw_value.
        if self.raw_value is not None:
            size = len(json.dumps(self.raw_value).encode("utf-8"))
            if size > MAX_RAW_VALUE_BYTES:
                raise ValidationError("payload_too_large")


class GovernedHistoryMutationForbidden(Exception):
    """Raised when any mutation (save, update, delete) is attempted on an
    existing ChecklistResponseHistory row."""


class _ImmutableHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be updated."
        )

    def delete(self):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be deleted."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be bulk-updated."
        )


class ChecklistResponseHistoryManager(models.Manager):
    def get_queryset(self):
        return _ImmutableHistoryQuerySet(self.model, using=self._db)


class ChecklistResponseHistory(PublicIDModel, TimeStampedModel):
    """Append-only governed amendment audit for reviewer-conclusion amendments.

    Created inside the same transaction as the response update; one row per
    amendment; never on first entry. Rows may never be mutated or deleted.
    """

    objects = ChecklistResponseHistoryManager()

    response = models.ForeignKey(
        ChecklistResponse,
        on_delete=models.PROTECT,
        related_name="history",
    )
    prior_raw_value = models.JSONField(null=True)
    new_raw_value = models.JSONField(null=True)
    prior_is_not_applicable = models.BooleanField()
    new_is_not_applicable = models.BooleanField()
    prior_not_applicable_reason = models.CharField(null=True, blank=True, max_length=200)
    new_not_applicable_reason = models.CharField(null=True, blank=True, max_length=200)
    prior_entered_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    prior_entered_at = models.DateTimeField(null=True, blank=True)
    prior_version = models.PositiveIntegerField()
    new_version = models.PositiveIntegerField()
    correction_reason = models.TextField()
    amended_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="+",
    )
    amended_at = models.DateTimeField(auto_now_add=True)
    source_classification_snapshot = models.CharField(max_length=50)

    class Meta:
        indexes = [
            models.Index(fields=["response"]),
        ]

    def delete(self, using=None, keep_parents=False):
        raise GovernedHistoryMutationForbidden(
            "ChecklistResponseHistory rows are append-only and cannot be deleted."
        )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise GovernedHistoryMutationForbidden(
                "ChecklistResponseHistory rows are append-only; "
                "save() on an existing row is forbidden."
            )
        super().save(*args, **kwargs)


class CalculationOutcome(PublicIDModel, TimeStampedModel):
    """Calculation result placeholder created at execution creation.
    Populated with actual values in 4D-3."""

    response = models.ForeignKey(
        ChecklistResponse,
        on_delete=models.CASCADE,
        related_name="calculation_outcomes",
    )
    calculation_name = models.CharField(max_length=100)
    formula_version = models.CharField(max_length=50, blank=True)
    status = models.CharField(
        max_length=50,
        choices=CalculationStatus.choices,
        default=CalculationStatus.DATA_REQUIRED,
    )
    value = models.DecimalField(null=True, blank=True, max_digits=20, decimal_places=10)
    unit = models.CharField(blank=True, max_length=50)
    # blank=True because a placeholder legitimately holds {} until governed
    # calculation execution fills it, and Django counts {} among
    # Field.empty_values -- with blank=False a row holding its own defaults
    # could not pass full_clean(), so no placeholder could be created at all.
    # null stays False: the column is always a JSON object, never SQL NULL.
    # The completed-outcome provenance requirements are enforced in clean()
    # instead, where they can be applied only to the status that has them.
    inputs = models.JSONField(default=dict, blank=True)
    input_provenance = models.JSONField(default=dict, blank=True)
    rounding_rule = models.CharField(blank=True, max_length=100)
    reason_code = models.CharField(blank=True, max_length=100)
    generated_at = models.DateTimeField(null=True, blank=True)
    source_assessment_snapshot_public_id = models.UUIDField(null=True, blank=True)

    def clean(self):
        if self.calculation_name not in _CALCULATION_NAMES:
            raise ValidationError(
                f"calculation_name {self.calculation_name!r} is not one of the six "
                "approved iid_assessment calculation function names."
            )
        self._validate_completed_outcome()

    # -- completed-outcome invariant (M4D3-PRV-002/005/007) -----------------
    #
    # ``inputs`` and ``input_provenance`` are blank=True so a placeholder can
    # hold {}. That relaxation must not let a *completed* row -- one carrying a
    # real regulated number -- be saved without the provenance that makes the
    # number reproducible. These checks therefore apply to the COMPLETE status
    # only; data_required, calculating and error rows carry no value and are
    # left alone.

    def _validate_completed_outcome(self):
        from .calculation_translation import (
            REGISTRY_BINDING_VERSION_PROVENANCE_KEY,
            SUBJECT_COMPONENT_PROVENANCE_KEY,
        )

        if self.status != CalculationStatus.COMPLETE:
            return

        errors: dict[str, str] = {}

        if self.value is None:
            errors["value"] = "A complete calculation outcome must carry a value."

        provenance = self.input_provenance
        if not isinstance(provenance, dict):
            errors["input_provenance"] = (
                "input_provenance must be a mapping on a complete outcome."
            )
            raise ValidationError(errors)

        binding_version = provenance.get(REGISTRY_BINDING_VERSION_PROVENANCE_KEY)
        if binding_version is None:
            errors["input_provenance"] = (
                "A complete outcome must record "
                f"{REGISTRY_BINDING_VERSION_PROVENANCE_KEY!r} (M4D3-PRV-002)."
            )
        elif not _is_governed_version(binding_version):
            # The recorded version is historical evidence: it is the binding
            # the result was produced under, which may legitimately predate the
            # registry's current value. The format is enforced; equality with
            # today's registry deliberately is not.
            errors["input_provenance"] = (
                f"{REGISTRY_BINDING_VERSION_PROVENANCE_KEY!r} must be a governed "
                "three-part numeric version."
            )
        elif not _has_input_descriptor(provenance):
            errors["input_provenance"] = (
                "A complete outcome must record at least one per-input source "
                "descriptor alongside the reserved keys (M4D3-PRV-002)."
            )

        entry = _registry_entry_for_calculation(self.calculation_name)
        if entry is None:
            errors["calculation_name"] = (
                f"calculation_name {self.calculation_name!r} does not resolve to an "
                "approved registry entry."
            )
        else:
            component = provenance.get(SUBJECT_COMPONENT_PROVENANCE_KEY)
            if _entry_is_component_scoped(entry):
                if component is None:
                    errors[SUBJECT_COMPONENT_PROVENANCE_KEY] = (
                        "A component-scoped calculation must record "
                        f"{SUBJECT_COMPONENT_PROVENANCE_KEY!r} (M4D3-PRV-005/007)."
                    )
            elif not _entry_inherits_component(entry) and component is not None:
                errors[SUBJECT_COMPONENT_PROVENANCE_KEY] = (
                    f"{SUBJECT_COMPONENT_PROVENANCE_KEY!r} is not permitted on a "
                    "calculation that neither selects nor inherits a component "
                    "(M4D3-PRV-007)."
                )
            if component is not None and not _is_canonical_uuid(component):
                errors[SUBJECT_COMPONENT_PROVENANCE_KEY] = (
                    f"{SUBJECT_COMPONENT_PROVENANCE_KEY!r} must be a canonical "
                    "lowercase hyphenated public UUID string."
                )

        if errors:
            raise ValidationError(errors)
