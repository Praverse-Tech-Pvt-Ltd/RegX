"""Audit event type constants and helper for the IIG checklist
definition-governance domain -- same thin-wrapper-over-AuditEvent shape
as fda_data/audit_events.py."""

from audit.models import AuditEvent


class IigChecklistEvent:
    DEFINITION_CREATED = "iig_checklist.definition.created"
    DEFINITION_CLONED = "iig_checklist.definition.cloned"
    DEFINITION_DELETED = "iig_checklist.definition.deleted"
    VERSION_CREATED = "iig_checklist.version.created"
    VERSION_UPDATED = "iig_checklist.version.updated"
    VERSION_SUBMITTED = "iig_checklist.version.submitted_for_review"
    VERSION_RETURNED = "iig_checklist.version.returned"
    VERSION_APPROVED = "iig_checklist.version.approved"
    VERSION_REJECTED = "iig_checklist.version.rejected"
    VERSION_ACTIVATED = "iig_checklist.version.activated"
    VERSION_SUPERSEDED = "iig_checklist.version.superseded"
    VERSION_RETIRED = "iig_checklist.version.retired"
    SECTION_CREATED = "iig_checklist.section.created"
    SECTION_UPDATED = "iig_checklist.section.updated"
    SECTION_DELETED = "iig_checklist.section.deleted"
    QUESTION_CREATED = "iig_checklist.question.created"
    QUESTION_UPDATED = "iig_checklist.question.updated"
    QUESTION_DELETED = "iig_checklist.question.deleted"
    APPLICABILITY_RULE_CREATED = "iig_checklist.applicability_rule.created"
    APPLICABILITY_RULE_UPDATED = "iig_checklist.applicability_rule.updated"
    APPLICABILITY_RULE_VALIDATED = "iig_checklist.applicability_rule.validated"
    # 4D-2 execution events
    EXECUTION_CREATED = "iig_checklist.execution.created"
    EXECUTION_SUBMITTED = "iig_checklist.execution.submitted_for_review"
    EXECUTION_RETURNED = "iig_checklist.execution.returned"
    EXECUTION_APPROVED = "iig_checklist.execution.approved"
    EXECUTION_REJECTED = "iig_checklist.execution.rejected"
    EXECUTION_CANCELLED = "iig_checklist.execution.cancelled"
    EXECUTION_SUPERSEDED = "iig_checklist.execution.superseded"
    RESPONSE_ENTERED = "iig_checklist.response.entered"
    RESPONSE_UPDATED = "iig_checklist.response.updated"
    RESPONSE_REVIEWER_CONCLUSION_ENTERED = "checklist_response.reviewer_conclusion_entered"
    RESPONSE_REVIEWER_CONCLUSION_UPDATED = "checklist_response.reviewer_conclusion_updated"


def emit(
    *,
    event_type: str,
    resource_type: str = "iig_checklist",
    resource_id: str = "",
    actor_id: int | None = None,
    actor_email: str = "",
    tenant_id: int | None = None,
    payload: dict | None = None,
) -> None:
    AuditEvent.objects.create(
        actor_id=actor_id,
        actor_email=actor_email,
        tenant_id=tenant_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {},
    )
