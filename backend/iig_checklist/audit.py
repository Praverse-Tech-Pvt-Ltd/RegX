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
    # 4D-3 governed calculation execution
    RESPONSE_CALCULATED = "iig_checklist.response.calculated"
    RESPONSE_REVIEWER_CONCLUSION_ENTERED = "checklist_response.reviewer_conclusion_entered"
    RESPONSE_REVIEWER_CONCLUSION_UPDATED = "checklist_response.reviewer_conclusion_updated"
    # 4D-4 controlled export (MILESTONE_4D_DISCOVERY.md §17) -- emitted with a
    # full decision-detail payload including the artifact checksum, so a later
    # dispute can verify a previously-issued export against the audit trail.
    EXECUTION_EXPORTED = "iig_checklist.execution.exported"
    #: MILESTONE_4D_DISCOVERY.md §12 L725 names this event exactly. Distinct from
    #: the plain response.entered/updated events so an override is never
    #: mistaken for an ordinary edit in the trail.
    ANSWER_OVERRIDDEN = "iig_checklist.answer.overridden"
    #: Gap analysis is computed on demand and never stored, so the audit row is
    #: the only record that a score was ever produced, for whom, and what it
    #: said at that moment. Emitted on the read path because that is where the
    #: analysis happens -- see the payload allow-list below for why the result
    #: detail does not travel with it.
    GAP_ANALYSIS_GENERATED = "iig_checklist.gap_analysis.generated"


#: Payload keys permitted for the event types introduced or corrected in P2.
#:
#: Scoped per event type rather than domain-wide on purpose. A single
#: domain-wide allow-list, as `workflows` uses, would silently drop keys that
#: this domain's twenty-odd existing events already record -- an unreviewed
#: change to the historical shape of the trail. New and corrected events start
#: constrained; the rest keep the payloads they were written with until each is
#: reviewed on its own.
#:
#: An allow-list, not a filter: a caller cannot add a key, so governed answer
#: content, narratives, credentials and request bodies are structurally
#: excluded rather than merely discouraged.
_PAYLOAD_ALLOW_LISTS: dict[str, frozenset[str]] = {
    # Counts and percentages only. `analyse_execution` also returns `gaps`,
    # which carries `question_text` and the answer itself, and `sections`,
    # which names each section. Neither may enter the audit row: the trail
    # records THAT a score was produced and what it totalled, never the
    # governed content behind it. `section_count` is derived here for that
    # reason instead of passing `sections` through.
    IigChecklistEvent.GAP_ANALYSIS_GENERATED: frozenset(
        {
            "execution_public_id",
            "checklist_version_public_id",
            "total_questions",
            "answered",
            "unanswered",
            "not_applicable",
            "gap_count",
            "score_percent",
            "completeness_percent",
            "section_count",
        }
    ),
    # Field NAMES only. The values are draft regulatory text -- change_summary
    # and regulatory_basis in particular -- and recording them would put the
    # content of an unapproved draft into an append-only table that cannot
    # later be redacted.
    IigChecklistEvent.VERSION_UPDATED: frozenset(
        {
            "version_public_id",
            "definition_public_id",
            "version_number",
            "status",
            "fields_changed",
        }
    ),
}


def _restrict(event_type: str, payload: dict | None) -> dict:
    """Drop anything the event type is not permitted to record.

    Events with no entry keep their payload untouched, so this narrows the
    events P2 touches without rewriting the domain's audit contract.
    """
    allowed = _PAYLOAD_ALLOW_LISTS.get(event_type)
    if allowed is None:
        return payload or {}
    return {k: v for k, v in (payload or {}).items() if k in allowed}


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
        payload=_restrict(event_type, payload),
    )
