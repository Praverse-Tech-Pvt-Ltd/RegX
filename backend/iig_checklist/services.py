"""Version-creation and clone services -- the two places this domain
must not repeat known race/ambiguity defects (see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §6b, §8a)."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max

from .audit import IigChecklistEvent, emit
from .codes import normalize_code
from .enums import CLONABLE_SOURCE_VERSION_STATUSES, ChecklistVersionStatus
from .models import ChecklistDefinition, ChecklistQuestion, ChecklistSection, ChecklistVersion


def _create_validated(model_cls, **kwargs):
    """Every governed row in this app is created through this helper --
    full_clean() is always invoked before save(), never skipped, per the
    mutation-boundary lesson in spec §7/§18 (the AssessmentSnapshot
    finding: a clean() guard that is never actually called enforces
    nothing)."""
    instance = model_cls(**kwargs)
    instance.full_clean()
    instance.save()
    return instance


class VersionAllocationConflict(Exception):
    pass


class DuplicateCodeError(Exception):
    pass


class CloneSourceNotEligible(Exception):
    pass


def create_next_version(*, definition: ChecklistDefinition, actor) -> ChecklistVersion:
    """Authoritative version-creation service -- select_for_update() on
    the PARENT ChecklistDefinition row while computing the next
    version_number, mirroring the exact fix already proven in
    templates_registry/importer.py for this defect class."""
    with transaction.atomic():
        locked_definition = ChecklistDefinition.objects.select_for_update().get(pk=definition.pk)
        max_number = ChecklistVersion.objects.filter(definition=locked_definition).aggregate(
            Max("version_number")
        )["version_number__max"]
        next_number = (max_number or 0) + 1

        try:
            version = _create_validated(
                ChecklistVersion,
                definition=locked_definition,
                version_number=next_number,
                status=ChecklistVersionStatus.DRAFT,
                created_by=actor,
            )
        except IntegrityError as exc:
            raise VersionAllocationConflict("Version allocation conflict -- please retry.") from exc

        emit(
            event_type=IigChecklistEvent.VERSION_CREATED,
            resource_id=str(version.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(locked_definition.tenant, "id", None),
            payload={
                "definition_public_id": str(locked_definition.public_id),
                "version_number": next_number,
            },
        )
        return version


@dataclass
class CloneResult:
    definition: ChecklistDefinition
    version: ChecklistVersion


@dataclass
class CloneRequest:
    source_version: ChecklistVersion
    target_scope_type: str
    target_tenant: object | None
    new_code: str
    new_title: str
    actor: object
    clone_sections: bool = True
    clone_questions: bool = True
    clone_applicability_rules: bool = True
    reason: str = ""


def clone_definition(request: CloneRequest) -> CloneResult:
    """Clone semantics -- see spec §8a. Never produces approved/active
    content; no provenance/audit history copied; atomic; new public IDs
    on every copied row."""
    if request.source_version.status not in CLONABLE_SOURCE_VERSION_STATUSES:
        raise CloneSourceNotEligible(
            f"Source version status {request.source_version.status!r} is not "
            "eligible for cloning (must be approved/active/superseded)."
        )

    try:
        normalized_code = normalize_code(request.new_code)
    except Exception as exc:
        raise ValidationError(str(exc)) from exc

    with transaction.atomic():
        existing = ChecklistDefinition.objects.filter(
            scope_type=request.target_scope_type, code=normalized_code
        )
        if request.target_scope_type == "tenant":
            existing = existing.filter(tenant=request.target_tenant)
        if existing.exists():
            raise DuplicateCodeError(f"Code {normalized_code!r} already exists in this scope.")

        new_definition = _create_validated(
            ChecklistDefinition,
            code=normalized_code,
            title=request.new_title,
            scope_type=request.target_scope_type,
            tenant=request.target_tenant if request.target_scope_type == "tenant" else None,
            created_by=request.actor,
        )
        new_version = _create_validated(
            ChecklistVersion,
            definition=new_definition,
            version_number=1,
            status=ChecklistVersionStatus.DRAFT,
            created_by=request.actor,
            cloned_from_version_public_id=request.source_version.public_id,
        )

        if request.clone_sections:
            source_sections = request.source_version.sections.all().order_by("display_order")
            for source_section in source_sections:
                new_rule = None
                if request.clone_applicability_rules and source_section.applicability_rule_id:
                    new_rule = _clone_applicability_rule(
                        source_section.applicability_rule, new_version
                    )
                new_section = _create_validated(
                    ChecklistSection,
                    checklist_version=new_version,
                    code=source_section.code,
                    title=source_section.title,
                    description=source_section.description,
                    display_order=source_section.display_order,
                    applicability_rule=new_rule,
                    criticality=source_section.criticality,
                )
                if request.clone_questions:
                    for source_question in source_section.questions.all().order_by("display_order"):
                        question_rule = None
                        if (
                            request.clone_applicability_rules
                            and source_question.applicability_rule_id
                        ):
                            question_rule = _clone_applicability_rule(
                                source_question.applicability_rule, new_version
                            )
                        _create_validated(
                            ChecklistQuestion,
                            section=new_section,
                            code=source_question.code,
                            question_text=source_question.question_text,
                            help_text=source_question.help_text,
                            display_order=source_question.display_order,
                            answer_type=source_question.answer_type,
                            data_source_classification=source_question.data_source_classification,
                            applicability_rule=question_rule,
                            required=source_question.required,
                            allowed_units=source_question.allowed_units,
                            evidence_requirement=source_question.evidence_requirement,
                            calculation_binding_identifier=(
                                source_question.calculation_binding_identifier
                            ),
                            prefill_source=source_question.prefill_source,
                            reviewer_confirmation_required=(
                                source_question.reviewer_confirmation_required
                            ),
                            escalation_rule_identifier=source_question.escalation_rule_identifier,
                            criticality=source_question.criticality,
                            regulatory_reference=source_question.regulatory_reference,
                            default_value_binding=source_question.default_value_binding,
                            validation_rule=source_question.validation_rule,
                        )

        emit(
            event_type=IigChecklistEvent.DEFINITION_CLONED,
            resource_id=str(new_definition.public_id),
            actor_id=getattr(request.actor, "id", None),
            actor_email=getattr(request.actor, "email", ""),
            tenant_id=getattr(request.target_tenant, "id", None),
            payload={
                "source_definition_public_id": str(request.source_version.definition.public_id),
                "source_version_public_id": str(request.source_version.public_id),
                "destination_definition_public_id": str(new_definition.public_id),
                "destination_version_public_id": str(new_version.public_id),
                "reason": request.reason,
            },
        )
        return CloneResult(definition=new_definition, version=new_version)


# ---------------------------------------------------------------------------
# Milestone 4D-2 -- Execution services
# ---------------------------------------------------------------------------


class ExecutionAlreadyActive(Exception):
    pass


class ChecklistVersionNotActive(Exception):
    pass


class FormulationVersionTenantMismatch(Exception):
    pass


class FormulationVersionNotApproved(Exception):
    pass


class InvalidQuantityUnitConfig(Exception):
    pass


class IncompleteExecution(Exception):
    pass


class MissingReturnReason(Exception):
    pass


class ReviewerConclusionRequired(Exception):
    pass


class SelfApprovalForbidden(Exception):
    pass


class ResponseDeleteForbidden(Exception):
    pass


class ReviewerConclusionInvalidState(Exception):
    pass


class ReviewerConclusionPermissionDenied(Exception):
    pass


class ReviewerConclusionStaleVersion(Exception):
    pass


class ReviewerConclusionEmpty(Exception):
    pass


class ReviewerConclusionTooLong(Exception):
    pass


class ReviewerConclusionPayloadTooLarge(Exception):
    pass


class ReviewerConclusionCorrectionReasonRequired(Exception):
    pass


class ReviewerConclusionInvalidPayload(Exception):
    pass


class ReviewerConclusionWrongAnswerType(Exception):
    pass


def _get_applicable_questions(checklist_version, formulation_version):
    """Return all questions applicable to this formulation_version in the given
    checklist_version. 4D-2 scope: no dynamic applicability evaluation -- all
    questions in the version are considered applicable."""
    return list(
        checklist_version.sections.prefetch_related("questions").values_list(
            "questions", flat=True
        ).exclude(questions=None)
    )


def _questions_for_version(checklist_version):
    """All ChecklistQuestion objects in the version."""
    from .models import ChecklistQuestion

    return ChecklistQuestion.objects.filter(
        section__checklist_version=checklist_version
    ).select_related("section")


def create_execution(
    *,
    tenant,
    checklist_version_public_id,
    formulation_version_public_id,
    actor,
):
    """Create a ChecklistExecution with pre-created response slots.

    Step ordering matches §16 of the approved specification exactly.
    Tenant guard runs before status guard (DR-2-34, DR-2-03).
    """
    import json

    from django.db import transaction as db_transaction

    from .enums import AnswerType, CalculationStatus, DataSourceClassification, ExecutionStatus
    from .execution_constants import MAX_RAW_VALUE_BYTES
    from .models import (
        CalculationOutcome,
        ChecklistExecution,
        ChecklistResponse,
        ChecklistVersion,
    )
    from .permissions import PERM_CREATE_EXECUTION, has_iig_checklist_permission

    # Step 1: resolve ChecklistVersion.
    try:
        checklist_version = ChecklistVersion.objects.visible_to(tenant).get(
            public_id=checklist_version_public_id
        )
    except ChecklistVersion.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound()
    if checklist_version.status != "active":
        raise ChecklistVersionNotActive()

    # Step 2: resolve FormulationVersion; tenant guard BEFORE status guard.
    from formulations.models import FormulationVersion

    try:
        fv = FormulationVersion.objects.get(public_id=formulation_version_public_id)
    except FormulationVersion.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound()

    if fv.product.tenant_id != getattr(tenant, "id", None):
        raise FormulationVersionTenantMismatch()

    if fv.status != "approved":
        raise FormulationVersionNotApproved()

    # Step 3: permission check.
    if not has_iig_checklist_permission(actor, tenant, PERM_CREATE_EXECUTION):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()

    # Step 4: validate quantity_with_unit questions for non-empty allowed_units.
    questions = list(_questions_for_version(checklist_version))
    for q in questions:
        if q.answer_type == AnswerType.QUANTITY_WITH_UNIT and not q.allowed_units:
            raise InvalidQuantityUnitConfig(q.code)

    # Step 5: transactional creation.
    with db_transaction.atomic():
        locked_version = ChecklistVersion.objects.select_for_update().get(pk=checklist_version.pk)

        existing = ChecklistExecution.objects.select_for_update().filter(
            tenant=tenant,
            checklist_version=locked_version,
            formulation_version=fv,
        ).exclude(status__in=["rejected", "cancelled", "superseded"]).first()
        if existing:
            raise ExecutionAlreadyActive()

        try:
            execution = _create_validated(
                ChecklistExecution,
                tenant=tenant,
                checklist_version=locked_version,
                formulation_version=fv,
                status=ExecutionStatus.DRAFT,
                created_by=actor,
            )
        except IntegrityError as exc:
            raise ExecutionAlreadyActive() from exc

        for q in questions:
            response = _create_validated(
                ChecklistResponse,
                execution=execution,
                question=q,
                data_source_type_snapshot=q.data_source_classification,
                raw_value=None,
                is_not_applicable=False,
            )
            if q.data_source_classification == DataSourceClassification.SYSTEM_CALCULATED:
                _create_validated(
                    CalculationOutcome,
                    response=response,
                    status=CalculationStatus.DATA_REQUIRED,
                    calculation_name=q.calculation_binding_identifier or "",
                )

    # Step 6: post-commit audit.
    def _audit():
        emit(
            event_type=IigChecklistEvent.EXECUTION_CREATED,
            resource_id=str(execution.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload={
                "checklist_version_public_id": str(checklist_version.public_id),
                "formulation_version_public_id": str(fv.public_id),
            },
        )

    db_transaction.on_commit(_audit)
    return execution


def transition_execution(*, execution, action, actor, tenant, **kwargs):
    """Generic execution lifecycle transition service (§17)."""
    import json

    from django.db import transaction as db_transaction
    from django.utils import timezone

    from .enums import ExecutionStatus
    from .execution_transitions import IllegalExecutionTransition, validate_execution_transition
    from .models import ChecklistExecution
    from .permissions import (
        PERM_APPROVE_EXECUTION,
        PERM_CANCEL_EXECUTION,
        PERM_REVIEW_EXECUTION,
        PERM_SUBMIT_EXECUTION,
        PERM_SUPERSEDE_EXECUTION,
        has_iig_checklist_permission,
    )

    action_to_perm = {
        "submit_review": PERM_SUBMIT_EXECUTION,
        "approve": PERM_APPROVE_EXECUTION,
        "return": PERM_REVIEW_EXECUTION,
        "reject": PERM_APPROVE_EXECUTION,
        "cancel": PERM_CANCEL_EXECUTION,
        "supersede": PERM_SUPERSEDE_EXECUTION,
    }

    # Validate transition (no DB write on failure).
    new_status = validate_execution_transition(execution.status, action)

    # Permission check.
    perm = action_to_perm.get(action, "")
    if perm and not has_iig_checklist_permission(actor, tenant, perm):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()

    now = timezone.now()

    # Pre-condition checks.
    if action == "submit_review":
        _check_execution_completeness(execution, for_approve=False)
    elif action == "approve":
        # Self-approval guard.
        if execution.submitted_by_id == getattr(actor, "id", None):
            raise SelfApprovalForbidden()
        _check_execution_completeness(execution, for_approve=True)
        reviewer_conclusion_note = kwargs.get("reviewer_conclusion_note", "")
        if not (reviewer_conclusion_note or "").strip():
            raise ReviewerConclusionRequired()
    elif action == "return":
        return_reason = kwargs.get("return_reason", "")
        if not (return_reason or "").strip():
            raise MissingReturnReason()

    action_event_map = {
        "submit_review": IigChecklistEvent.EXECUTION_SUBMITTED,
        "approve": IigChecklistEvent.EXECUTION_APPROVED,
        "return": IigChecklistEvent.EXECUTION_RETURNED,
        "reject": IigChecklistEvent.EXECUTION_REJECTED,
        "cancel": IigChecklistEvent.EXECUTION_CANCELLED,
        "supersede": IigChecklistEvent.EXECUTION_SUPERSEDED,
    }

    with db_transaction.atomic():
        locked = ChecklistExecution.objects.select_for_update().get(pk=execution.pk)
        locked.status = new_status
        if action == "submit_review":
            locked.submitted_by = actor
            locked.submitted_at = now
        elif action == "approve":
            locked.approved_by = actor
            locked.approved_at = now
            locked.reviewer_conclusion_note = kwargs.get("reviewer_conclusion_note", "")
            locked.reviewed_by = actor
        elif action == "return":
            locked.returned_by = actor
            locked.returned_at = now
            locked.return_reason = kwargs.get("return_reason", "")
            locked.reviewed_by = actor
        elif action == "reject":
            locked.rejected_by = actor
            locked.rejected_at = now
        elif action == "cancel":
            locked.cancelled_by = actor
            locked.cancelled_at = now
        elif action == "supersede":
            locked.superseded_by = kwargs.get("superseded_by")
        locked.full_clean()
        locked.save()

    def _audit():
        emit(
            event_type=action_event_map[action],
            resource_id=str(locked.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload={
                "action": action,
                "before_status": execution.status,
                "after_status": new_status,
            },
        )

    db_transaction.on_commit(_audit)
    return locked


def _check_execution_completeness(execution, *, for_approve=False):
    """Raise IncompleteExecution if completeness gates are not satisfied."""
    from .enums import AnswerType, DataSourceClassification

    responses = execution.responses.select_related("question").all()
    for response in responses:
        q = response.question
        if not q.required:
            continue
        if q.answer_type == AnswerType.REVIEWER_CONCLUSION and not for_approve:
            continue
        if q.answer_type == AnswerType.REVIEWER_CONCLUSION and for_approve:
            if response.raw_value is None or response.is_not_applicable:
                raise IncompleteExecution(f"Reviewer conclusion required for question {q.code}.")
            continue
        if response.is_not_applicable:
            if not (response.not_applicable_reason or "").strip():
                raise IncompleteExecution(f"not_applicable_reason required for question {q.code}.")
        else:
            if response.raw_value is None:
                raise IncompleteExecution(f"Response required for question {q.code}.")
        if q.data_source_classification == DataSourceClassification.REVIEWER_CONFIRMED:
            if response.confirmed_by_id is None:
                raise IncompleteExecution(f"Reviewer confirmation required for question {q.code}.")


def enter_reviewer_conclusion(
    *,
    tenant,
    execution_public_id,
    response_public_id,
    actor,
    raw_value,
    expected_version,
    correction_reason=None,
):
    """Two-phase reviewer-conclusion entry (§19 of approved spec).

    Phase A: non-mutating validation.
    Phase B: all regulated writes inside one atomic transaction.
    Phase C: post-commit audit.
    """
    import json

    from django.db import transaction as db_transaction
    from django.utils import timezone

    from .enums import AnswerType, ExecutionStatus
    from .execution_constants import MAX_RAW_VALUE_BYTES, MAX_REVIEWER_CONCLUSION_CHARS
    from .models import ChecklistExecution, ChecklistResponse, ChecklistResponseHistory
    from .permissions import PERM_REVIEW_EXECUTION, has_iig_checklist_permission

    # Phase A -- non-mutating validation.

    try:
        execution = ChecklistExecution.objects.visible_to(tenant).get(
            public_id=execution_public_id
        )
    except ChecklistExecution.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound()

    if execution.status != ExecutionStatus.SUBMITTED_FOR_REVIEW:
        raise ReviewerConclusionInvalidState()

    if not has_iig_checklist_permission(actor, tenant, PERM_REVIEW_EXECUTION):
        raise ReviewerConclusionPermissionDenied()

    try:
        response = ChecklistResponse.objects.get(
            public_id=response_public_id,
            execution=execution,
        )
    except ChecklistResponse.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound()

    if response.question.answer_type != AnswerType.REVIEWER_CONCLUSION:
        raise ReviewerConclusionWrongAnswerType()

    # Validate raw_value structure.
    if not isinstance(raw_value, dict):
        raise ReviewerConclusionInvalidPayload()
    if set(raw_value.keys()) != {"value"}:
        raise ReviewerConclusionInvalidPayload()
    value_str = raw_value.get("value")
    if not isinstance(value_str, str):
        raise ReviewerConclusionInvalidPayload()
    if not value_str.strip():
        raise ReviewerConclusionEmpty()
    if len(value_str) > MAX_REVIEWER_CONCLUSION_CHARS:
        raise ReviewerConclusionTooLong()
    payload_bytes = len(json.dumps(raw_value).encode("utf-8"))
    if payload_bytes > MAX_RAW_VALUE_BYTES:
        raise ReviewerConclusionPayloadTooLarge()

    is_amendment = response.raw_value is not None
    if is_amendment and not (correction_reason or "").strip():
        raise ReviewerConclusionCorrectionReasonRequired()

    # Phase B -- all regulated writes inside one transaction.
    with db_transaction.atomic():
        locked_execution = ChecklistExecution.objects.select_for_update().get(pk=execution.pk)
        locked_response = ChecklistResponse.objects.select_for_update().get(pk=response.pk)

        if locked_execution.status != ExecutionStatus.SUBMITTED_FOR_REVIEW:
            raise ReviewerConclusionInvalidState()
        if locked_response.execution_id != locked_execution.pk:
            from rest_framework.exceptions import NotFound

            raise NotFound()
        if locked_response.question.answer_type != AnswerType.REVIEWER_CONCLUSION:
            raise ReviewerConclusionWrongAnswerType()
        if locked_response.version != expected_version:
            raise ReviewerConclusionStaleVersion()

        prior_raw_value = locked_response.raw_value
        prior_is_not_applicable = locked_response.is_not_applicable
        prior_not_applicable_reason = locked_response.not_applicable_reason
        prior_entered_by = locked_response.entered_by
        prior_entered_at = locked_response.entered_at
        prior_version = locked_response.version

        now = timezone.now()
        locked_response.raw_value = raw_value
        locked_response.entered_by = actor
        locked_response.entered_at = now
        locked_response.data_source_type_snapshot = (
            locked_response.data_source_type_snapshot
            or locked_response.question.data_source_classification
        )
        locked_response.version = prior_version + 1
        locked_response.full_clean()
        locked_response.save()

        is_amendment_confirmed = prior_raw_value is not None
        if is_amendment_confirmed:
            ChecklistResponseHistory(
                response=locked_response,
                prior_raw_value=prior_raw_value,
                new_raw_value=raw_value,
                prior_is_not_applicable=prior_is_not_applicable,
                new_is_not_applicable=locked_response.is_not_applicable,
                prior_not_applicable_reason=prior_not_applicable_reason,
                new_not_applicable_reason=locked_response.not_applicable_reason,
                prior_entered_by=prior_entered_by,
                prior_entered_at=prior_entered_at,
                prior_version=prior_version,
                new_version=locked_response.version,
                correction_reason=correction_reason or "",
                amended_by=actor,
                source_classification_snapshot=locked_response.data_source_type_snapshot,
            ).save()

    # Phase C -- post-commit audit.
    event_type = (
        IigChecklistEvent.RESPONSE_REVIEWER_CONCLUSION_UPDATED
        if is_amendment_confirmed
        else IigChecklistEvent.RESPONSE_REVIEWER_CONCLUSION_ENTERED
    )

    def _audit():
        emit(
            event_type=event_type,
            resource_id=str(locked_response.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload={
                "execution_public_id": str(locked_execution.public_id),
                "response_public_id": str(locked_response.public_id),
                "question_public_id": str(locked_response.question.public_id),
                "prior_response_version": prior_version,
                "new_response_version": locked_response.version,
                "execution_status": locked_execution.status,
                "correction_reason_present": bool(correction_reason),
            },
        )

    db_transaction.on_commit(_audit)
    return locked_response


def _clone_applicability_rule(source_rule, new_version):
    from .models import ApplicabilityRule

    return _create_validated(
        ApplicabilityRule,
        checklist_version=new_version,
        code=source_rule.code,
        rule_version=1,
        condition_json=source_rule.condition_json,
        outcome_if_true=source_rule.outcome_if_true,
        outcome_if_false=source_rule.outcome_if_false,
        reason_code=source_rule.reason_code,
        explanation_template=source_rule.explanation_template,
        field_registry_version=source_rule.field_registry_version,
    )
