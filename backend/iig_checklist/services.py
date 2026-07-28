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
        locked_definition = ChecklistDefinition.objects.select_for_update().get(
            pk=definition.pk
        )
        max_number = ChecklistVersion.objects.filter(
            definition=locked_definition
        ).aggregate(Max("version_number"))["version_number__max"]
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
            raise VersionAllocationConflict(
                "Version allocation conflict -- please retry."
            ) from exc

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
                    for source_question in source_section.questions.all().order_by(
                        "display_order"
                    ):
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
