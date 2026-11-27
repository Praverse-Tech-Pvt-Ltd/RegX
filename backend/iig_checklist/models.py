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
    ChecklistExecutionScope,
    ChecklistScopeType,
    ChecklistVersionStatus,
    Criticality,
    DataSourceClassification,
    EvidenceRequirement,
    ExecutionStatus,
    Jurisdiction,
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
    #: OQ-8 (`5A-DEC-OQ8`) -- the governed regulatory scope of one execution of
    #: this checklist. See `ChecklistExecutionScope`. Blank means "not yet
    #: classified" and fails closed at execution creation; existing definitions
    #: are deliberately left unclassified rather than guessed at.
    execution_scope = models.CharField(
        max_length=32,
        choices=ChecklistExecutionScope.choices,
        blank=True,
    )
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="checklist_definitions",
    )
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    objects = ChecklistDefinitionManager()

    def clean(self):
        """`execution_scope` is governed configuration, not editable metadata.

        There is no PATCH/PUT on this model today -- `ChecklistDefinitionDetailView`
        exposes only GET and DELETE -- so in practice the value is set once at
        creation. This guard exists so that stays true for any future code path:
        classifying an unclassified definition (blank -> value) is permitted,
        because existing definitions must be able to become governed, but
        *changing* an already-governed classification is refused.

        Re-classifying would silently alter what every existing approved version
        and completed execution of this checklist was regulating, which no
        lifecycle state can make safe. Consistent with the existing rule that a
        definition whose version has been submitted or activated cannot be
        deleted.
        """
        super().clean()
        if not self.pk:
            return
        original = (
            type(self).objects.filter(pk=self.pk).values_list("execution_scope", flat=True).first()
        )
        if original and original != self.execution_scope:
            raise ValidationError(
                {
                    "execution_scope": (
                        "The governed execution scope cannot be changed once set. "
                        "Create a new checklist definition instead."
                    )
                }
            )

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
    #: `5A-DEC-005` -- structured, governed jurisdiction, version-scoped.
    #:
    #: Owned by the *version* rather than the definition because a version is
    #: what is approved against a defined regulatory basis and source set;
    #: `ChecklistDefinition` carries no lifecycle at all, so it cannot express
    #: "approved under this regulator as of this version". It sits beside
    #: `regulatory_basis` for exactly that reason.
    #:
    #: Blank is permitted and means **not stated** -- never "assume US_FDA".
    #: Pre-5A synthetic content predates the field and must not be retro-labelled
    #: with a regulator no one approved it under; the migration therefore
    #: backfills nothing. Production content is required to state it by the
    #: content package, not by a model default that would silently invent one.
    jurisdiction = models.CharField(
        max_length=20,
        choices=Jurisdiction.choices,
        blank=True,
        default="",
    )
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
                    # `5A-DEC-005` -- jurisdiction is lifecycle-governed exactly like
                    # the regulatory basis it qualifies: fixed once the version
                    # leaves draft/returned, so an approved version can never
                    # silently change which regulator it was approved under.
                    "jurisdiction",
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
        # `5A-DEC-001` -- an FDA-derived binding must name an approved resolver.
        # Checked here, at authoring time, so an unknown identifier is refused
        # while the version is still a draft rather than silently producing an
        # unresolvable answer on every execution built from it. A binding on a
        # question that is not FDA-derived is equally refused: nothing would
        # ever read it, so it could only mislead a reviewer of the content.
        from .answer_sources import is_known_resolver

        binding = (self.prefill_source or "").strip()
        if binding:
            if self.data_source_classification != DataSourceClassification.FDA_DERIVED_DEFAULT:
                raise ValidationError(
                    "prefill_source may only be set when data_source_classification "
                    "is FDA_DERIVED_DEFAULT."
                )
            if not is_known_resolver(binding):
                raise ValidationError(
                    f"prefill_source {binding!r} is not an approved answer-source "
                    "resolver identifier."
                )

        # `5A-DEC-002` -- the authored option vocabulary is content, so it is
        # validated where content is authored. Doing it at answer time instead
        # would report a content defect as if the reviewer's answer were wrong.
        from .question_options import OptionConfigurationError, validate_options

        try:
            validate_options(self.validation_rule)
        except OptionConfigurationError as exc:
            raise ValidationError(f"{exc.error_code}: {exc}") from exc
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
    #: OQ-8 (`5A-DEC-OQ8`) -- the one governed subject component this execution
    #: is about. The regulatory decision is that an IID/IIG execution is
    #: component-scoped: FDA IID evaluation is excipient-specific (inactive
    #: ingredient + route + dosage form, with potency/MDE on the individual
    #: excipient record), so there is no whole-formulation aggregate to compute.
    #:
    #: A live FK, not a frozen UUID: unlike `AssessmentSnapshot`, an execution is
    #: operational state, and PROTECT is what stops a component being deleted out
    #: from under a governed execution. `formulation_version` is already an FK
    #: with PROTECT, so this matches.
    #:
    #: Nullable only for executions created before this field existed. New
    #: executions whose checklist content is component-specific must supply it
    #: (see `services.create_execution`); a legacy NULL keeps the pre-OQ-8
    #: behaviour so an already-approved execution stays reproducible, and never
    #: silently acquires a component.
    subject_component = models.ForeignKey(
        "formulations.FormulationComponent",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
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
    #: Why an approved execution was superseded (required at supersede; owner 2026-11-26).
    supersede_reason = models.TextField(blank=True, max_length=MAX_RETURN_REASON_CHARS)
    reviewer_conclusion_note = models.TextField(
        blank=True,
        max_length=MAX_REVIEWER_CONCLUSION_CHARS,
    )

    class Meta:
        constraints = [
            # OQ-8: uniqueness is now per subject component, because the
            # regulatory decision explicitly allows "multiple component-specific
            # IID/IIG executions where required" for one formulation. Split in
            # two so the pre-OQ-8 guarantee is not silently weakened: SQL treats
            # NULLs as distinct, so a single constraint including the nullable
            # column would let unlimited subject-less executions coexist.
            models.UniqueConstraint(
                fields=[
                    "tenant",
                    "checklist_version",
                    "formulation_version",
                    "subject_component",
                ],
                condition=Q(subject_component__isnull=False)
                & ~Q(status__in=["rejected", "cancelled", "superseded"]),
                name="unique_active_execution_per_formulation_component",
            ),
            models.UniqueConstraint(
                fields=["tenant", "checklist_version", "formulation_version"],
                condition=Q(subject_component__isnull=True)
                & ~Q(status__in=["rejected", "cancelled", "superseded"]),
                name="unique_active_execution_per_version_formulation",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["checklist_version"]),
            models.Index(fields=["subject_component"]),
        ]

    def clean(self):
        """OQ-8 invariants on the governed subject component.

        Enforced on the model rather than only in the service so no code path --
        including a future one -- can attach a foreign component or swap it after
        the fact. `full_clean()` runs before every governed save (M4D3-PST-005).
        """
        super().clean()
        if self.subject_component_id is None:
            return

        # The component must belong to this execution's own formulation version.
        # That version is already tenant-guarded by the creation service, so this
        # single check also closes the cross-tenant case: a component from
        # another tenant necessarily belongs to another formulation version.
        if self.subject_component.formulation_version_id != self.formulation_version_id:
            raise ValidationError(
                {
                    "subject_component": (
                        "The subject component must belong to this execution's formulation version."
                    )
                }
            )

        if self.pk:
            original = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("subject_component_id", flat=True)
                .first()
            )
            # Immutable once governed. A correction requires a new execution, so
            # an approved execution can never be re-pointed at a different
            # excipient after the fact.
            if original is not None and original != self.subject_component_id:
                raise ValidationError(
                    {
                        "subject_component": (
                            "The governed subject component cannot be changed after "
                            "the execution has been created."
                        )
                    }
                )


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
    #: `5A-DEC-001` -- governed provenance for an FDA-derived answer.
    #:
    #: Written only by the governed population pass, never by a client. Records
    #: which approved resolver ran, which governed source release it read (by
    #: UUID and source checksum) and which field of it -- or, when nothing could
    #: be resolved, the explicit reason there is no value. That distinction is
    #: the point: an empty FDA-derived answer must be readable as "the source
    #: had nothing" rather than being indistinguishable from "never populated".
    #:
    #: Null for every response that is not FDA-derived, so the column says
    #: nothing about answers it does not govern.
    source_provenance = models.JSONField(null=True, blank=True)
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
            errors["input_provenance"] = "input_provenance must be a mapping on a complete outcome."
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


# ---------------------------------------------------------------------------
# P7 -- immutable gap-analysis snapshots
# ---------------------------------------------------------------------------
class GapAnalysis(PublicIDModel, TimeStampedModel):
    """One immutable gap-analysis snapshot of one execution.

    The point of persisting at all is history: a reviewer needs to be able to
    say what the checklist reported *at the moment somebody looked*, and the
    on-demand endpoint cannot answer that because it always recomputes from
    today's answers.

    **Immutable.** Nothing here is ever rewritten. If the answers move, the next
    generation is a new row; the old one keeps saying what it said. `save()`
    refuses a second write rather than relying on callers to remember.

    **Bound to its inputs.** `checklist_version` is a hard FK under PROTECT, so
    a later version cannot silently change what an older snapshot meant, and the
    version it was taken against cannot be deleted out from under it.
    `input_hash` fingerprints the exact state that produced it.

    **No question or answer text.** Items reference questions by FK. The
    checklist version is immutable once active, so the text is recoverable
    through that reference; copying it here would duplicate regulatory content
    into a second, unreviewed place.
    """

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    execution = models.ForeignKey(
        ChecklistExecution, on_delete=models.PROTECT, related_name="gap_analyses"
    )
    checklist_version = models.ForeignKey(ChecklistVersion, on_delete=models.PROTECT)
    #: SHA-256 over the canonical analysis inputs. See `gap_snapshots.input_hash`.
    input_hash = models.CharField(max_length=64)
    algorithm_version = models.PositiveIntegerField()
    generated_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True
    )
    generated_at = models.DateTimeField()

    #: Factual counts only. No score: no governed formula exists, and inventing
    #: one here would give it the authority of a persisted regulatory record.
    total_questions = models.PositiveIntegerField()
    applicable_count = models.PositiveIntegerField()
    gap_count = models.PositiveIntegerField()
    no_gap_count = models.PositiveIntegerField()
    unanswered_count = models.PositiveIntegerField()
    review_required_count = models.PositiveIntegerField()
    not_applicable_count = models.PositiveIntegerField()

    class Meta:
        ordering = ["-generated_at", "-id"]
        constraints = [
            # Idempotent regeneration: identical inputs under the same algorithm
            # produce one row, so two reviewers pressing the button at the same
            # moment cannot create two snapshots that say the same thing. The
            # database is what enforces it, because a check-then-insert in the
            # service would lose the race it exists to prevent.
            models.UniqueConstraint(
                fields=["tenant", "execution", "input_hash", "algorithm_version"],
                name="unique_iig_gap_analysis_per_input",
            )
        ]
        indexes = [models.Index(fields=["tenant", "execution", "-generated_at"])]

    def __str__(self):
        return f"GapAnalysis({self.public_id})"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("A gap analysis snapshot is immutable once written.")
        return super().save(*args, **kwargs)


class GapAnalysisItem(models.Model):
    """One question's classification within a snapshot.

    Not a `PublicIDModel`: an item has no independent identity outside its
    analysis and is never addressed on its own.
    """

    analysis = models.ForeignKey(GapAnalysis, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey(ChecklistQuestion, on_delete=models.PROTECT)
    #: Denormalised from the question's section so a snapshot keeps the grouping
    #: it was taken with. `code` is unique per version; the section's *title* is
    #: not, which is why identity is the code.
    section_code = models.CharField(max_length=100)
    section_display_order = models.PositiveIntegerField()
    display_order = models.PositiveIntegerField()
    status = models.CharField(max_length=32)
    reason_code = models.CharField(max_length=64)
    #: Exactly what the checklist definition configured, or blank for
    #: unconfigured. Never derived, never ranked.
    configured_criticality = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["section_display_order", "section_code", "display_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["analysis", "question"], name="unique_iig_gap_item_per_analysis"
            )
        ]
        indexes = [models.Index(fields=["analysis", "status"])]

    def __str__(self):
        return f"GapAnalysisItem({self.analysis_id}, {self.question_id}, {self.status})"
