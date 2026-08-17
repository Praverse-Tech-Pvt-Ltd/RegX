"""Version-creation and clone services -- the two places this domain
must not repeat known race/ambiguity defects (see
docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §6b, §8a)."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max

from .audit import IigChecklistEvent, emit
from .calculation_registry import get_entry
from .codes import normalize_code
from .enums import (
    CLONABLE_SOURCE_VERSION_STATUSES,
    ChecklistVersionStatus,
    DataSourceClassification,
    ExecutionStatus,
)
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


class SubjectComponentRequired(Exception):
    """OQ-8 -- component-specific content cannot be executed without a subject."""


class SubjectComponentNotInFormulationVersion(Exception):
    """OQ-8 -- the named component does not belong to this formulation version.

    Also the cross-tenant case: a component owned by another tenant necessarily
    belongs to another formulation version, so it fails here without the caller
    ever learning whether the UUID exists.
    """


class InvalidCalculationBinding(Exception):
    """A SYSTEM_CALCULATED question's binding cannot produce a placeholder.

    Raised when the identifier is blank, is not an approved registry entry, or
    declares an answer type or source classification the question does not
    match. Activation already proves these for an active version; this is
    defence in depth at the mutation boundary, and it fails the whole
    ``create_execution()`` transaction rather than writing a placeholder that
    could never be executed.
    """


class IncompleteExecution(Exception):
    pass


class MissingReturnReason(Exception):
    pass


class ReviewerConclusionRequired(Exception):
    pass


class ReviewerConclusionInvalidExpectedVersion(Exception):
    """`4D4-DEC-013` -- expected_version is structurally invalid.

    Distinct from ``ReviewerConclusionStaleVersion``: this is a malformed value
    (``1.0``, ``"1"``, ``0``, ``null``), not a correctly-shaped value that lost a
    race. Separate codes so a client can tell "fix your request" from "re-read
    and retry".
    """


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
        checklist_version.sections.prefetch_related("questions")
        .values_list("questions", flat=True)
        .exclude(questions=None)
    )


def _questions_for_version(checklist_version):
    """All ChecklistQuestion objects in the version."""
    from .models import ChecklistQuestion

    return ChecklistQuestion.objects.filter(
        section__checklist_version=checklist_version
    ).select_related("section")


def _iid_binding(question) -> str:
    """The `iid.*` FDA-derived binding this question declares, or ``""``."""
    binding = (question.prefill_source or "").strip()
    if not binding:
        return ""
    if question.data_source_classification != DataSourceClassification.FDA_DERIVED_DEFAULT:
        return ""
    return binding


def version_requires_subject_component(questions) -> bool:
    """OQ-8 -- does this checklist version read execution-level `iid.*`?

    True when a question declares an `iid.*` FDA-derived binding, or an
    applicability rule reads the `iid` field group. Those are exactly the two
    consumers OQ-8 is about, and neither can produce an answer without a
    governed subject component.

    Scoped deliberately, and this is the one mechanical judgement in this change:

    * A **component-scoped calculation** does *not* trigger the requirement. It
      already has an approved selector of its own (`Q_SUBJECT_COMPONENT`,
      M4D3-FCR-002..004), and the regulatory decision's constraint on it is one
      of *consistency* -- it must not select a different component from the
      execution's. That is enforced in
      ``calculation_inputs._resolve_subject_component`` whenever a governed
      subject exists, rather than by demanding one up front.
    * Demanding a subject regardless would make an execution impossible against
      a formulation version that has no components at all -- a real case, and one
      where a component-scoped calculation simply fails closed as before.

    If the regulatory owner intends *every* execution to carry a governed subject
    component irrespective of content, this predicate is the single place to
    widen; the invariants downstream do not change.
    """
    from .applicability_runtime import referenced_field_groups

    for question in questions:
        if _iid_binding(question):
            return True

        rule = question.applicability_rule
        if rule is not None and "iid" in referenced_field_groups(rule.condition_json):
            return True
    return False


def _resolve_fda_derived_default(question, precedent=None):
    """Resolve one FDA-derived question's default through the governed registry.

    Returns ``(raw_value, provenance)``. Both are ``None`` for a question that
    declares no binding, so nothing changes for content that does not use the
    mechanism.

    ``precedent`` is the governed ``IIDPrecedentRecord`` selected by the caller
    for this execution's subject component (OQ-8, `5A-DEC-OQ8`). The resolver
    stays pure: it receives an already-selected source and performs no lookup of
    its own.

    ``None`` is still a legitimate argument and still yields an explicit
    ``source_unavailable`` provenance record with no value -- for a legacy
    execution that has no governed subject component, for a subject component
    whose assessment matched no IID precedent, or when no active FDA release
    exists. No default is ever fabricated to paper over any of those.
    """
    from .answer_sources import resolve

    binding = _iid_binding(question)
    if not binding:
        return None, None

    outcome, resolver_version = resolve(binding, precedent)
    provenance = outcome.provenance(binding, resolver_version)
    return (outcome.value if outcome.resolved else None), provenance


def _resolve_creation_subject_component(formulation_version, subject_component_public_id):
    """OQ-8 -- validate a client-named subject component against the execution.

    Scoped to the execution's own formulation version, exactly as
    ``calculation_inputs._component_in_execution`` does, so a component from
    another formulation -- and therefore possibly another tenant -- can never be
    attached, and its existence is never disclosed. A UUID that exists is not
    sufficient grounds to trust it.
    """
    from formulations.models import FormulationComponent

    component = FormulationComponent.objects.filter(
        public_id=subject_component_public_id,
        formulation_version_id=formulation_version.pk,
    ).first()
    if component is None:
        raise SubjectComponentNotInFormulationVersion()
    return component


def _create_execution_iid_source(*, tenant, execution, formulation_version, actor):
    """OQ-8 -- the governed IID source for this execution's `iid.*` values.

    Creates the component-specific ``AssessmentSnapshot`` through the approved
    ``iid_assessment`` service and returns
    ``(snapshot, precedent_record_or_None)``.

    Reuses the approved snapshot semantics wholesale (M4D3-SNO-001/006/008,
    M4D3-SRC-001/003/004): the release is resolved server-side, the Part 14.1
    worst-case daily units come from the one shared helper every governed
    snapshot caller uses, and the snapshot is *created*, never selected -- no
    ``.first()``, no ``.latest()``, no reuse of a pre-existing row.

    Exactly one snapshot is created per creation pass and shared by every `iid.*`
    binding in it. That is not the forbidden kind of reuse: the row is new, made
    inside this transaction, for this execution's one subject component. Sharing
    it is what makes the bindings mutually consistent -- minting a separate
    snapshot per question could straddle a release change and leave one execution
    answering from two different sources.

    Returns ``(None, None)`` when the execution has no governed subject
    component, which keeps every binding at ``source_unavailable``.
    """
    if execution.subject_component_id is None:
        return None, None

    from formulations.dosing import governed_maximum_daily_units_value
    from iid_assessment.services import (
        ActiveReleaseUnavailable,
        ReleaseNotEligible,
        create_assessment_snapshot,
    )

    try:
        result = create_assessment_snapshot(
            tenant=tenant,
            formulation_version=formulation_version,
            formulation_component=execution.subject_component,
            actor=actor,
            # M4D3-SRC-001/003 -- resolved server-side, never named by a caller.
            selected_release=None,
            # M4D3-SRC-004 -- the governed Part 14.1 worst case, injected.
            maximum_dosage_units_per_day=governed_maximum_daily_units_value(
                formulation_version=formulation_version
            ),
        )
    except (ActiveReleaseUnavailable, ReleaseNotEligible):
        # A governed error, not a crash (M4D3-SRC-002). Every binding then
        # records source_unavailable rather than a fabricated value.
        return None, None

    snapshot = result.snapshot
    precedent = None
    if snapshot.iid_precedent_record_public_id is not None:
        from fda_data.models import IIDPrecedentRecord

        precedent = (
            IIDPrecedentRecord.objects.select_related("release")
            .filter(public_id=snapshot.iid_precedent_record_public_id)
            .first()
        )
    return snapshot, precedent


def create_execution(
    *,
    tenant,
    checklist_version_public_id,
    formulation_version_public_id,
    actor,
    subject_component_public_id=None,
):
    """Create a ChecklistExecution with pre-created response slots.

    Step ordering matches §16 of the approved specification exactly.
    Tenant guard runs before status guard (DR-2-34, DR-2-03).
    """

    from django.db import transaction as db_transaction

    from .enums import AnswerType, CalculationStatus, DataSourceClassification, ExecutionStatus
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

        raise NotFound() from None
    if checklist_version.status != "active":
        raise ChecklistVersionNotActive()

    # Step 2: resolve FormulationVersion; tenant guard BEFORE status guard.
    from formulations.models import FormulationVersion

    try:
        fv = FormulationVersion.objects.get(public_id=formulation_version_public_id)
    except FormulationVersion.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound() from None

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

    # Step 4b (OQ-8, `5A-DEC-OQ8`): establish the governed subject component
    # *before* the transaction, so it is already known when FDA-derived defaults
    # and applicability resolve inside it. This is the ordering fix: the previous
    # design had no subject at that point and could only fail closed.
    subject_component = None
    if subject_component_public_id is not None:
        subject_component = _resolve_creation_subject_component(fv, subject_component_public_id)
    elif version_requires_subject_component(questions):
        raise SubjectComponentRequired()

    # Step 5: transactional creation.
    with db_transaction.atomic():
        locked_version = ChecklistVersion.objects.select_for_update().get(pk=checklist_version.pk)

        # OQ-8: duplicate detection is per subject component, matching the
        # split uniqueness constraints. The regulatory decision explicitly
        # allows several component-specific executions for one formulation, so
        # filtering without the component would refuse a legitimate second one.
        existing = (
            ChecklistExecution.objects.select_for_update()
            .filter(
                tenant=tenant,
                checklist_version=locked_version,
                formulation_version=fv,
                subject_component=subject_component,
            )
            .exclude(status__in=["rejected", "cancelled", "superseded"])
            .first()
        )
        if existing:
            raise ExecutionAlreadyActive()

        try:
            execution = _create_validated(
                ChecklistExecution,
                tenant=tenant,
                checklist_version=locked_version,
                formulation_version=fv,
                subject_component=subject_component,
                status=ExecutionStatus.DRAFT,
                created_by=actor,
            )
        except IntegrityError as exc:
            raise ExecutionAlreadyActive() from exc

        # OQ-8: the governed IID source for this execution, created once before
        # any binding reads it. Inside this transaction, so a later failure
        # discards the snapshot with the execution (M4D3-SNO-003/012).
        iid_snapshot, iid_precedent = _create_execution_iid_source(
            tenant=tenant,
            execution=execution,
            formulation_version=fv,
            actor=actor,
        )

        for q in questions:
            # `5A-DEC-001` -- governed FDA-derived population, before any
            # calculation runs (M4D3-POP-002). A question with no approved
            # binding resolves to nothing and records nothing, exactly as
            # before; a bound one records either a value with its source
            # provenance or an explicit reason there is none. There is no third
            # outcome: a fabricated default is never written.
            fda_value, fda_provenance = _resolve_fda_derived_default(q, iid_precedent)
            if fda_provenance is not None and iid_snapshot is not None:
                # OQ-8 provenance: enough for a reviewer to reconstruct which
                # formulation version, which excipient and which snapshot the
                # value came from. The release identity is already recorded by
                # the resolver as `source_version`.
                fda_provenance = {
                    **fda_provenance,
                    "subject_component_public_id": str(execution.subject_component.public_id),
                    "formulation_version_public_id": str(fv.public_id),
                    "assessment_snapshot_public_id": str(iid_snapshot.public_id),
                }
            response = _create_validated(
                ChecklistResponse,
                execution=execution,
                question=q,
                data_source_type_snapshot=q.data_source_classification,
                raw_value=fda_value,
                is_not_applicable=False,
                source_provenance=fda_provenance,
            )
            if q.data_source_classification == DataSourceClassification.SYSTEM_CALCULATED:
                # The placeholder records the *calculation function name*, which
                # is what CalculationOutcome.clean() accepts -- not the registry
                # binding identifier, which it rejects. Resolve the identifier
                # through the immutable registry rather than trusting the stored
                # string; no second registry implementation is introduced.
                entry = get_entry((q.calculation_binding_identifier or "").strip())
                if entry is None:
                    raise InvalidCalculationBinding(q.code)
                if entry.allowed_answer_type != q.answer_type:
                    raise InvalidCalculationBinding(q.code)
                if entry.allowed_data_source != q.data_source_classification:
                    raise InvalidCalculationBinding(q.code)
                _create_validated(
                    CalculationOutcome,
                    response=response,
                    status=CalculationStatus.DATA_REQUIRED,
                    calculation_name=entry.calculation_name,
                )

        # `5A-DEC-004` -- evaluate governed applicability once the responses
        # exist, inside the same transaction, so an execution is never visible
        # in a state where a rule-governed question has not been assessed.
        # Rules are version-scoped and the context is assembled once, so every
        # question in this execution is judged against identical product state.
        from .applicability_runtime import evaluate_execution_applicability

        evaluate_execution_applicability(
            execution=execution, actor=actor, iid_snapshot=iid_snapshot
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
                # OQ-8: which excipient this execution governs, and the snapshot
                # its iid.* values came from. UUIDs only, never internal ids.
                # None is recorded truthfully rather than omitted -- "no governed
                # subject" is itself the fact an auditor needs.
                "subject_component_public_id": (
                    str(subject_component.public_id) if subject_component is not None else None
                ),
                "assessment_snapshot_public_id": (
                    str(iid_snapshot.public_id) if iid_snapshot is not None else None
                ),
            },
        )

    db_transaction.on_commit(_audit)
    return execution


def transition_execution(*, execution, action, actor, tenant, **kwargs):
    """Generic execution lifecycle transition service (§17)."""

    from django.db import transaction as db_transaction
    from django.utils import timezone

    from .execution_transitions import validate_execution_transition
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

        # `4D4-DEC-008` -- the governed approval_metadata projection is written
        # inside this same atomic block, so the metadata and the approved status
        # commit together or not at all. Zero written is normal: an execution
        # whose checklist defines no approval_metadata question approves exactly
        # as before.
        approval_metadata_written = 0
        if action == "approve":
            from .approval_metadata import populate_approval_metadata

            approval_metadata_written = populate_approval_metadata(
                execution=locked, actor=actor, approved_at=now
            )

    def _audit():
        payload = {
            "action": action,
            "before_status": execution.status,
            "after_status": new_status,
        }
        if action == "approve":
            payload["approval_metadata_written"] = approval_metadata_written
        emit(
            event_type=action_event_map[action],
            resource_id=str(locked.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload=payload,
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
        # `4D4-DEC-008` -- approval_metadata is generated *by* the approve
        # transition this gate guards, so a required approval_metadata question
        # could never be satisfied beforehand: the gate would be unsatisfiable by
        # construction, and its REVIEWER_CONFIRMED floor would additionally
        # demand a confirmation that no client may supply. Exempted for the same
        # reason REVIEWER_CONCLUSION is exempted before approval.
        if q.answer_type == AnswerType.APPROVAL_METADATA:
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
        execution = ChecklistExecution.objects.visible_to(tenant).get(public_id=execution_public_id)
    except ChecklistExecution.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound() from None

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

        raise NotFound() from None

    if response.question.answer_type != AnswerType.REVIEWER_CONCLUSION:
        raise ReviewerConclusionWrongAnswerType()

    # `4D4-DEC-013` -- the same governed structural validator the response-update
    # and override paths use, applied to the value the client actually submitted.
    # The serializer is a passthrough, so `1.0`, `"1"` and `"1.0"` arrive intact
    # and are refused here rather than silently becoming version 1. One
    # structural rule, three governed entry points.
    from .calculation_execution import InvalidExpectedVersion, validate_expected_version

    try:
        expected_version = validate_expected_version(expected_version)
    except InvalidExpectedVersion as exc:
        raise ReviewerConclusionInvalidExpectedVersion() from exc

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


# ---------------------------------------------------------------------------
# Milestone 4D-3 -- governed response-update service (Part 4)
# ---------------------------------------------------------------------------
#
# M4D3-SVC-001 recorded that the previous write path was
# ``ChecklistResponseUpdateView.patch()`` doing ``full_clean()`` and ``save()``
# with no transaction, no lock, no ``expected_version`` and no version
# increment. This service replaces that path; the view is now a thin adapter
# (M4D3-SVC-004).
#
# M4D3-SVC-003 fixes the responsibility order implemented below: tenant-scoped
# execution lookup; tenant-scoped response lookup; execution-state validation;
# permission validation; ``expected_version`` validation; execution lock;
# response lock; payload validation; dependent recalculation; version
# increment; every write inside one ``transaction.atomic()``; audit through
# ``transaction.on_commit()``.
#
# **No history row is written here, deliberately.** M4D3-HST-001 scopes
# ``ChecklistResponseHistory`` reuse to governed persisted-state transitions,
# which for this milestone are exactly persisted applicability transitions and
# component-reference rebinding, and M4D3-HST-005 closes
# ``correction_reason`` to ``APPLICABILITY_REEVALUATED`` and
# ``COMPONENT_REBOUND`` with the instruction that no code shall be applied to
# an event type it does not describe. An ordinary user response edit is
# neither transition, so there is no code that honestly describes it and
# writing one would fabricate governed vocabulary. Both transitions are out of
# scope for this change.


class ResponseUpdateError(Exception):
    """Base class for governed response-update rejections, raised before commit."""


class ResponseUpdateInvalidState(ResponseUpdateError):
    """The execution is not in a status that permits response edits."""


class ResponseUpdatePermissionDenied(ResponseUpdateError):
    """The actor lacks ``PERM_EDIT_EXECUTION`` for this tenant."""


class ResponseUpdateWrongAnswerType(ResponseUpdateError):
    """A ``reviewer_conclusion`` response has its own governed endpoint."""


class ResponseUpdateServerControlledValue(ResponseUpdateError):
    """M4D3-SVC-005 -- the value is server-owned, not client-writable.

    ``fda_derived_default`` and ``system_calculated`` responses are populated
    and recalculated by governed services. M4D3-SVC-006 defers the override
    path to 4D-4, so no override permission exists in this milestone and the
    rejection is therefore unconditional rather than permission-dependent.
    """


class ResponseUpdateStaleVersion(ResponseUpdateError):
    """M4D3-VER-005 -- ``expected_version`` does not match the locked row."""


class ResponseUpdateInvalidPayload(ResponseUpdateError):
    """The payload failed governed deserialization; carries the field errors."""

    def __init__(self, errors) -> None:
        super().__init__("invalid_payload")
        self.errors = errors


class ResponseUpdateReservedReasonPrefix(ResponseUpdateError):
    """M4D3-APP-011 -- the client supplied the reserved server-owned marker.

    ``REVIEW_REQUIRED:<reason_code>`` is written into ``not_applicable_reason``
    only by a governed server-side applicability determination (M4D3-PST-002).
    A client-supplied value beginning with that prefix is rejected **for any
    response, rule-governed or not**, so stored data can never impersonate a
    server determination.

    The clause fixes ``error_code = "reserved_reason_prefix"`` but states no
    HTTP status. The adapter maps it to 403, matching its sibling M4D3-APP-009
    (403 for client-supplied applicability on a rule-governed response) and the
    M4D3-SVC-005 server-controlled-value rejection already in this service.
    """


class ResponseUpdateApplicabilityServerControlled(ResponseUpdateError):
    """M4D3-APP-009 -- the client supplied applicability for a rule-governed response.

    M4D3-APP-008 makes ``is_not_applicable`` and ``not_applicable_reason``
    server-owned whenever ``question.applicability_rule`` is set: the governed
    applicability service is their only writer. A client-supplied value for
    either field on such a response is rejected, whether it sets, changes or
    clears the state.

    M4D3-APP-009 fixes ``error_code = "applicability_server_controlled"`` and
    HTTP 403 -- the same status as its siblings M4D3-SVC-005 (server-controlled
    stored value) and M4D3-APP-011 (reserved marker), because the objection is
    the same in kind: the value is owned by the server, not by the caller.

    Deliberately distinct from :class:`ResponseUpdateReservedReasonPrefix`. That
    one is about a *value* no client may write anywhere; this one is about
    *ownership* of two fields on a particular class of response. Collapsing them
    would report the wrong reason and would wrongly imply that a non-reserved
    applicability value is acceptable on a rule-governed response.
    """


class ResponseUpdateInvalidExpectedVersion(ResponseUpdateError):
    """M4D3-TXN-003 -- ``expected_version`` is structurally invalid.

    Raised when the governed ``validate_expected_version()`` refuses the value
    the client actually submitted. Distinct from
    :class:`ResponseUpdateStaleVersion`, which means a *valid* integer that
    disagrees with the locked row.
    """


#: M4D3-SVC-005 -- classifications whose stored value the client may not write.
SERVER_CONTROLLED_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        DataSourceClassification.FDA_DERIVED_DEFAULT,
        DataSourceClassification.SYSTEM_CALCULATED,
    }
)

#: M4D3-SVC-003 -- the execution statuses in which a response may be edited.
EDITABLE_EXECUTION_STATUSES: frozenset[str] = frozenset(
    {ExecutionStatus.DRAFT, ExecutionStatus.RETURNED}
)

#: The client-writable fields of a governed response update. ``system_derived_value``
#: and ``override_reason`` are deliberately absent: M4D3-SVC-006 defers the override
#: path to 4D-4.
_UPDATABLE_FIELDS = ("raw_value", "is_not_applicable", "not_applicable_reason")


@dataclass(frozen=True, slots=True)
class ResponseUpdateResult:
    """One governed response update and the cascade it drove.

    ``cascade`` is the immutable :class:`~iig_checklist.cascade.CascadeRecalculationResult`
    of the recalculation this update triggered. It is ``None`` only when the
    updated question appears in no ``recalculation_triggers`` set *and* the
    cascade was therefore never entered -- see ``triggered`` on the result
    itself for the M4D3-RCL-007 no-op case, which still returns a result.
    """

    response: object
    cascade: object = None


def update_checklist_response(
    *,
    tenant,
    execution_public_id,
    response_public_id,
    actor,
    payload,
) -> ResponseUpdateResult:
    """Update one governed response and recalculate everything it feeds.

    Three phases, matching the reviewer-conclusion service:

    - Phase A -- non-mutating validation. No lock, no write.
    - Phase B -- one ``transaction.atomic()`` holding the response write and
      every dependent outcome update (M4D3-TXN-002). An exception anywhere in
      it rolls back both (M4D3-TXN-004).
    - Phase C -- audit dispatched through ``transaction.on_commit()``
      (M4D3-TXN-005), so nothing is announced that did not commit.

    ``payload`` is the raw request body. Deserialization happens here rather
    than in the view because the governed shape rules depend on the question,
    which is only known after the tenant-scoped lookup.
    """
    from django.db import transaction as db_transaction
    from django.utils import timezone

    from .calculation_execution import (
        InvalidExpectedVersion,
        validate_expected_version,
    )
    from .cascade import recalculate_dependents
    from .enums import AnswerType
    from .governed_vocabularies import RESERVED_REASON_PREFIX
    from .models import ChecklistExecution, ChecklistResponse
    from .permissions import PERM_EDIT_EXECUTION, has_iig_checklist_permission
    from .serializers import ChecklistResponseUpdateSerializer

    # -- Phase A: non-mutating validation ---------------------------------

    # Object lookup first -- a cross-tenant id is a 404 through visible_to(),
    # never a 403, so existence is not disclosed to a foreign tenant.
    try:
        execution = ChecklistExecution.objects.visible_to(tenant).get(public_id=execution_public_id)
    except ChecklistExecution.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound() from None

    if not has_iig_checklist_permission(actor, tenant, PERM_EDIT_EXECUTION):
        raise ResponseUpdatePermissionDenied()

    if execution.status not in EDITABLE_EXECUTION_STATUSES:
        raise ResponseUpdateInvalidState()

    try:
        response = ChecklistResponse.objects.select_related("question").get(
            public_id=response_public_id,
            execution=execution,
        )
    except ChecklistResponse.DoesNotExist:
        from rest_framework.exceptions import NotFound

        raise NotFound() from None

    if response.question.answer_type == AnswerType.REVIEWER_CONCLUSION:
        raise ResponseUpdateWrongAnswerType()

    # M4D3-SVC-005 -- checked in the service, not only in the serializer.
    if response.data_source_type_snapshot in SERVER_CONTROLLED_CLASSIFICATIONS:
        raise ResponseUpdateServerControlledValue()

    serializer = ChecklistResponseUpdateSerializer(
        data=payload,
        context={
            "question": response.question,
            "execution": execution,
            "tenant": tenant,
        },
    )
    if not serializer.is_valid():
        raise ResponseUpdateInvalidPayload(serializer.errors)

    data = serializer.validated_data

    # M4D3-APP-009 -- applicability is server-owned wherever a rule governs it.
    #
    # M4D3-APP-008 makes ``is_not_applicable`` and ``not_applicable_reason``
    # server-owned for any response whose question carries an applicability rule;
    # the governed applicability service is their only writer. A client that
    # supplies either field for such a response is authoring state it does not
    # own, so the request is refused outright rather than partially applied --
    # setting *and* clearing are both authorship.
    #
    # Checked here, in the governed service, so a direct domain call is bound by
    # it exactly as an HTTP request is, and before the transaction opens so a
    # rejected attempt writes nothing, increments no version, runs no cascade and
    # emits no success audit.
    #
    # Presence is what matters, not value: a payload naming the field at all is
    # an attempt to author it. ``is_not_applicable=False`` on an already-N/A
    # response is a clear, and is refused for the same reason.
    #
    # Ordered before the M4D3-APP-011 marker check because ownership is the more
    # fundamental objection -- on a rule-governed response the client may not
    # author the field at all, so the value it carries is never reached.
    # M4D3-APP-010 keeps a client-declared N/A permitted where no rule governs
    # the question, so this guard is scoped strictly to rule-governed responses.
    if response.question.applicability_rule_id is not None and (
        "is_not_applicable" in data or "not_applicable_reason" in data
    ):
        raise ResponseUpdateApplicabilityServerControlled()

    # M4D3-APP-011 -- the reserved server-owned marker is never client-supplied,
    # for any response, rule-governed or not. Checked in the governed service so
    # a direct domain call is bound by it too, and before the transaction opens
    # so a rejected request touches nothing. The comparison is a plain
    # case-sensitive prefix test on the submitted string: M4D3-PST-002 fixes the
    # stored form as ``REVIEW_REQUIRED:<reason_code>`` and no clause defines any
    # trimming, folding or normalisation, so none is invented here.
    supplied_reason = data.get("not_applicable_reason")
    if isinstance(supplied_reason, str) and supplied_reason.startswith(RESERVED_REASON_PREFIX):
        raise ResponseUpdateReservedReasonPrefix()

    # M4D3-TXN-003 -- the same governed structural gate the calculation writer
    # and the cascade use, applied to the value the client actually submitted.
    # The serializer deliberately does not coerce, so ``1.0``, ``"1"`` and
    # ``"1.0"`` arrive intact and are refused here rather than silently becoming
    # version 1. One structural validator, three governed entry points.
    try:
        expected_version = validate_expected_version(data["expected_version"])
    except InvalidExpectedVersion as exc:
        raise ResponseUpdateInvalidExpectedVersion() from exc

    prior_entered_by = response.entered_by_id

    # -- Phase B: every governed write, one transaction --------------------
    with db_transaction.atomic():
        # M4D3-TXN-001 / M4D3-TXN-006 -- the execution first; it is the
        # serialization barrier every governed operation on this execution
        # shares, and the cascade re-enters it below on the same transaction.
        locked_execution = ChecklistExecution.objects.select_for_update().get(pk=execution.pk)
        # Re-read under the lock: the status examined must be committed state,
        # not what the Phase A scan happened to see.
        if locked_execution.status not in EDITABLE_EXECUTION_STATUSES:
            raise ResponseUpdateInvalidState()

        locked_response = (
            ChecklistResponse.objects.select_for_update()
            .select_related("question")
            .get(pk=response.pk)
        )

        # M4D3-TXN-003 -- validated against the locked row, after the lock and
        # before any write. M4D3-VER-005 -- no write, no version increment and
        # no success audit follow a mismatch.
        if locked_response.version != expected_version:
            raise ResponseUpdateStaleVersion()

        for field in _UPDATABLE_FIELDS:
            if field in data:
                setattr(locked_response, field, data[field])
        locked_response.entered_by = actor
        locked_response.entered_at = timezone.now()
        # M4D3-VER-006 -- exactly one.
        locked_response.version = expected_version + 1

        try:
            locked_response.full_clean()
            locked_response.save()
        except ValidationError as exc:
            raise ResponseUpdateInvalidPayload(
                {"error_code": "invalid_raw_value_shape", "detail": str(exc)}
            ) from exc

        # M4D3-RCL-001 -- the cascade is entered for every governed update, and
        # decides for itself whether this question triggers anything. Keying
        # that decision here would duplicate the trigger rules the registry
        # already owns. M4D3-TXN-002 -- it runs inside this transaction, so a
        # recalculation failure rolls the response write back with it.
        cascade_result = recalculate_dependents(
            tenant=tenant,
            execution=locked_execution,
            changed_response=locked_response,
            actor=actor,
            expected_version=locked_response.version,
        )

    # -- Phase C: post-commit audit ---------------------------------------
    event_type = (
        IigChecklistEvent.RESPONSE_UPDATED
        if prior_entered_by
        else IigChecklistEvent.RESPONSE_ENTERED
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
                "data_source_type_snapshot": locked_response.data_source_type_snapshot,
                "prior_response_version": expected_version,
                "new_response_version": locked_response.version,
                "recalculated_count": cascade_result.recalculated_count,
            },
        )

    db_transaction.on_commit(_audit)
    return ResponseUpdateResult(response=locked_response, cascade=cascade_result)
