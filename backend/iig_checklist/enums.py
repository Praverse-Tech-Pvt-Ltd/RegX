"""Controlled vocabularies for the IIG checklist definition-governance domain.

Every enum here is the exact, complete set specified in
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md -- no additions, no omissions.
"""

from django.db import models


class ChecklistScopeType(models.TextChoices):
    PLATFORM_MASTER = "platform_master", "Platform master"
    TENANT = "tenant", "Tenant"


class ChecklistVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    UNDER_REVIEW = "under_review", "Under review"
    RETURNED = "returned", "Returned"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    REJECTED = "rejected", "Rejected"
    SUPERSEDED = "superseded", "Superseded"
    RETIRED = "retired", "Retired"


TERMINAL_VERSION_STATUSES = frozenset(
    {
        ChecklistVersionStatus.REJECTED,
        ChecklistVersionStatus.SUPERSEDED,
        ChecklistVersionStatus.RETIRED,
    }
)

# Content (sections/questions/rules) is mutable only in these two statuses.
EDITABLE_VERSION_STATUSES = frozenset(
    {ChecklistVersionStatus.DRAFT, ChecklistVersionStatus.RETURNED}
)

# A clone's source version must be in one of these statuses -- never an
# unreviewed draft, and never rejected/retired content.
CLONABLE_SOURCE_VERSION_STATUSES = frozenset(
    {
        ChecklistVersionStatus.APPROVED,
        ChecklistVersionStatus.ACTIVE,
        ChecklistVersionStatus.SUPERSEDED,
    }
)


class DataSourceClassification(models.TextChoices):
    FDA_DERIVED_DEFAULT = "fda_derived_default", "FDA-derived default"
    USER_REQUIRED = "user_required", "User required"
    SYSTEM_CALCULATED = "system_calculated", "System calculated"
    REVIEWER_CONFIRMED = "reviewer_confirmed", "Reviewer confirmed"
    EVIDENCE_DERIVED = "evidence_derived", "Evidence derived"


class AnswerType(models.TextChoices):
    SHORT_TEXT = "short_text", "Short text"
    LONG_NARRATIVE = "long_narrative", "Long narrative"
    INTEGER = "integer", "Integer"
    DECIMAL = "decimal", "Decimal"
    QUANTITY_WITH_UNIT = "quantity_with_unit", "Quantity with unit"
    PERCENTAGE = "percentage", "Percentage"
    DATE = "date", "Date"
    YES_NO = "yes_no", "Yes/No"
    YES_NO_NOT_APPLICABLE = "yes_no_na", "Yes/No/Not applicable"
    SINGLE_SELECT = "single_select", "Single select"
    MULTI_SELECT = "multi_select", "Multi select"
    FDA_RECORD_REFERENCE = "fda_record_reference", "FDA record reference"
    FORMULATION_COMPONENT_REFERENCE = (
        "formulation_component_reference",
        "Formulation component reference",
    )
    EVIDENCE_ATTACHMENT_REFERENCE = "attachment_reference", "Evidence attachment reference"
    CALCULATED_VALUE = "calculated_value", "Calculated value"
    CALCULATED_STATUS = "calculated_status", "Calculated status"
    REVIEWER_CONCLUSION = "reviewer_conclusion", "Reviewer conclusion"
    APPROVAL_METADATA = "approval_metadata", "Approval metadata"


class Criticality(models.TextChoices):
    INFORMATIONAL = "informational", "Informational"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class EvidenceRequirement(models.TextChoices):
    NONE = "none", "None"
    OPTIONAL = "optional", "Optional"
    REQUIRED = "required", "Required"
    REQUIRED_IF_OVERRIDDEN = "required_if_overridden", "Required if overridden"


class ApplicabilityOutcome(models.TextChoices):
    APPLICABLE = "applicable", "Applicable"
    NOT_APPLICABLE = "not_applicable", "Not applicable"
    REVIEW_REQUIRED = "review_required", "Review required"


class ApplicabilityRuleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"


class ExecutionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED_FOR_REVIEW = "submitted_for_review", "Submitted for review"
    RETURNED = "returned", "Returned"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    SUPERSEDED = "superseded", "Superseded"


TERMINAL_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.REJECTED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.SUPERSEDED,
    }
)


class CalculationStatus(models.TextChoices):
    DATA_REQUIRED = "data_required", "Data required"
    CALCULATING = "calculating", "Calculating"
    COMPLETE = "complete", "Complete"
    ERROR = "error", "Error"
