"""Milestone 4D-3 -- fail-closed registry binding validation at activation.

This is the ORM-backed control the pure foundation deliberately deferred: it
checks every calculation-registry binding referenced by a ``ChecklistVersion``
against that version's persisted, approved content before the version may become
executable.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-REG-018/019  activation-time validation and structured rejection
  - M4D3-TRG-006/007  dependency and trigger set agreement
  - M4D3-FCR-012      registry_component_code selector disabled
  - M4D3-DEP-006      form E targets must be SYSTEM_CALCULATED

Verified schema fact driving the duplicate check: question codes are unique per
**section** (``unique_iig_question_code_per_section``), not per version, so the
same code may legitimately appear in two sections of one version. Every lookup
therefore collects **all** matches and fails on anything other than exactly one.
No ``.first()`` and no arbitrary selection anywhere in this module.

This module reads only. It performs no write, opens no transaction and emits no
audit event; the caller owns the transaction and the lifecycle mutation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_registry import (
    DISABLED_SELECTOR_TYPES,
    SOURCE_CALCULATION_OUTCOME,
    SOURCE_FORMULATION_FIELD,
    SOURCE_QUESTION_RESPONSE,
    get_entry,
)
from .enums import AnswerType, DataSourceClassification

# ---------------------------------------------------------------------------
# Structured validation codes (M4D3-REG-019)
# ---------------------------------------------------------------------------

UNKNOWN_REGISTRY_IDENTIFIER = "UNKNOWN_REGISTRY_IDENTIFIER"
QUESTION_CODE_MISSING = "QUESTION_CODE_MISSING"
QUESTION_CODE_DUPLICATE = "QUESTION_CODE_DUPLICATE"
WRONG_ANSWER_TYPE = "WRONG_ANSWER_TYPE"
WRONG_SOURCE_CLASSIFICATION = "WRONG_SOURCE_CLASSIFICATION"
DEPENDENCY_NOT_CALCULATED = "DEPENDENCY_NOT_CALCULATED"
SELECTOR_WRONG_ANSWER_TYPE = "SELECTOR_WRONG_ANSWER_TYPE"
DISABLED_SELECTOR_FORM = "DISABLED_SELECTOR_FORM"
DEPENDENCY_MISMATCH = "DEPENDENCY_MISMATCH"
TRIGGER_MISMATCH = "TRIGGER_MISMATCH"

ALLOWED_VALIDATION_CODES: frozenset[str] = frozenset(
    {
        UNKNOWN_REGISTRY_IDENTIFIER,
        QUESTION_CODE_MISSING,
        QUESTION_CODE_DUPLICATE,
        WRONG_ANSWER_TYPE,
        WRONG_SOURCE_CLASSIFICATION,
        DEPENDENCY_NOT_CALCULATED,
        SELECTOR_WRONG_ANSWER_TYPE,
        DISABLED_SELECTOR_FORM,
        DEPENDENCY_MISMATCH,
        TRIGGER_MISMATCH,
    }
)


@dataclass(frozen=True, slots=True, order=True)
class ValidationFinding:
    """One sanitized activation-validation failure.

    Ordered so repeated validation of identical content yields byte-identical
    output. Carries public identifiers and governed codes only -- never a
    database primary key, raw exception text, SQL or regulated answer content.
    """

    question_code: str
    registry_identifier: str
    validation_code: str
    message: str
    question_public_id: str | None = None


def _index_questions_by_code(version) -> dict[str, list]:
    """Collect every question in the version, grouped by code.

    A single query; grouping preserves duplicates so the caller can reject
    ambiguity rather than silently choose one.
    """
    from .models import ChecklistQuestion

    questions = (
        ChecklistQuestion.objects.filter(section__checklist_version=version)
        .select_related("section")
        .order_by("section__display_order", "display_order")
    )
    grouped: dict[str, list] = {}
    for question in questions:
        grouped.setdefault(question.code, []).append(question)
    return grouped


def _resolve_unique(
    grouped: dict[str, list],
    code: str,
    *,
    identifier: str,
    findings: list[ValidationFinding],
    context: str,
):
    """Return the single question for ``code`` or record a finding and None."""
    matches = grouped.get(code, [])
    if not matches:
        findings.append(
            ValidationFinding(
                question_code=code,
                registry_identifier=identifier,
                validation_code=QUESTION_CODE_MISSING,
                message=(
                    f"{context} references question code {code!r}, which does not "
                    "exist in this checklist version."
                ),
            )
        )
        return None
    if len(matches) > 1:
        findings.append(
            ValidationFinding(
                question_code=code,
                registry_identifier=identifier,
                validation_code=QUESTION_CODE_DUPLICATE,
                message=(
                    f"{context} references question code {code!r}, which resolves to "
                    f"{len(matches)} questions in this checklist version; the binding "
                    "is ambiguous."
                ),
            )
        )
        return None
    return matches[0]


def validate_version_calculation_bindings(version) -> tuple[ValidationFinding, ...]:
    """Validate every registry binding referenced by ``version``.

    Only identifiers actually referenced by the version's questions are checked;
    unreferenced registry entries never block activation (M4D3-REG-018 applies
    per bound question, not to the global registry).

    Returns findings in a stable order. An empty tuple means the version's
    calculation bindings are internally consistent and safe to activate.
    """
    grouped = _index_questions_by_code(version)
    findings: list[ValidationFinding] = []

    bound_questions = [
        question
        for questions in grouped.values()
        for question in questions
        if (question.calculation_binding_identifier or "").strip()
    ]

    for question in bound_questions:
        identifier = question.calculation_binding_identifier.strip()
        entry = get_entry(identifier)

        if entry is None:
            findings.append(
                ValidationFinding(
                    question_code=question.code,
                    registry_identifier=identifier,
                    validation_code=UNKNOWN_REGISTRY_IDENTIFIER,
                    message=(
                        f"Question {question.code!r} declares calculation binding "
                        f"{identifier!r}, which is not an approved registry entry."
                    ),
                    question_public_id=str(question.public_id),
                )
            )
            continue

        # -- the bound question itself must match the registry declaration ----
        if question.data_source_classification != entry.allowed_data_source:
            findings.append(
                ValidationFinding(
                    question_code=question.code,
                    registry_identifier=identifier,
                    validation_code=WRONG_SOURCE_CLASSIFICATION,
                    message=(
                        f"Question {question.code!r} is "
                        f"{question.data_source_classification!r}; registry entry "
                        f"{identifier!r} requires {entry.allowed_data_source!r}."
                    ),
                    question_public_id=str(question.public_id),
                )
            )
        if question.answer_type != entry.allowed_answer_type:
            findings.append(
                ValidationFinding(
                    question_code=question.code,
                    registry_identifier=identifier,
                    validation_code=WRONG_ANSWER_TYPE,
                    message=(
                        f"Question {question.code!r} has answer type "
                        f"{question.answer_type!r}; registry entry {identifier!r} "
                        f"requires {entry.allowed_answer_type!r}."
                    ),
                    question_public_id=str(question.public_id),
                )
            )

        declared_form_e: set[str] = set()
        declared_triggers: set[str] = set()

        # -- every resolver declaration must bind inside this version ---------
        for kwarg, declaration in entry.input_resolvers.items():
            source = declaration.get("source")
            context = f"Resolver {kwarg!r} of {identifier!r}"

            if source == SOURCE_QUESTION_RESPONSE:
                code = declaration["question_code"]
                declared_triggers.add(code)
                _resolve_unique(
                    grouped, code, identifier=identifier, findings=findings,
                    context=context,
                )

            elif source == SOURCE_CALCULATION_OUTCOME:
                code = declaration["question_code"]
                declared_form_e.add(code)
                declared_triggers.add(code)
                upstream = _resolve_unique(
                    grouped, code, identifier=identifier, findings=findings,
                    context=context,
                )
                if upstream is not None and (
                    upstream.data_source_classification
                    != DataSourceClassification.SYSTEM_CALCULATED
                ):
                    findings.append(
                        ValidationFinding(
                            question_code=code,
                            registry_identifier=identifier,
                            validation_code=DEPENDENCY_NOT_CALCULATED,
                            message=(
                                f"{context} depends on question {code!r}, which is "
                                f"{upstream.data_source_classification!r} rather than "
                                "system_calculated."
                            ),
                            question_public_id=str(upstream.public_id),
                        )
                    )

            elif source == SOURCE_FORMULATION_FIELD:
                selector = declaration.get("component_selector")
                if selector is None:
                    continue
                if selector.get("type") in DISABLED_SELECTOR_TYPES:
                    findings.append(
                        ValidationFinding(
                            question_code=question.code,
                            registry_identifier=identifier,
                            validation_code=DISABLED_SELECTOR_FORM,
                            message=(
                                f"{context} uses component selector form "
                                f"{selector.get('type')!r}, which is disabled in "
                                "Milestone 4D-3."
                            ),
                            question_public_id=str(question.public_id),
                        )
                    )
                    continue
                code = selector["question_code"]
                declared_triggers.add(code)
                selector_question = _resolve_unique(
                    grouped, code, identifier=identifier, findings=findings,
                    context=f"{context} component selector",
                )
                if selector_question is not None and (
                    selector_question.answer_type
                    != AnswerType.FORMULATION_COMPONENT_REFERENCE
                ):
                    findings.append(
                        ValidationFinding(
                            question_code=code,
                            registry_identifier=identifier,
                            validation_code=SELECTOR_WRONG_ANSWER_TYPE,
                            message=(
                                f"{context} component selector points at question "
                                f"{code!r} with answer type "
                                f"{selector_question.answer_type!r}; "
                                "formulation_component_reference is required."
                            ),
                            question_public_id=str(selector_question.public_id),
                        )
                    )

        # -- declared sets must agree with the resolver declarations ----------
        if set(entry.calculation_dependencies) != declared_form_e:
            findings.append(
                ValidationFinding(
                    question_code=question.code,
                    registry_identifier=identifier,
                    validation_code=DEPENDENCY_MISMATCH,
                    message=(
                        f"Registry entry {identifier!r} declares calculation "
                        f"dependencies {sorted(entry.calculation_dependencies)} which "
                        f"do not match its prior-outcome resolvers "
                        f"{sorted(declared_form_e)}."
                    ),
                    question_public_id=str(question.public_id),
                )
            )
        if set(entry.recalculation_triggers) != declared_triggers:
            findings.append(
                ValidationFinding(
                    question_code=question.code,
                    registry_identifier=identifier,
                    validation_code=TRIGGER_MISMATCH,
                    message=(
                        f"Registry entry {identifier!r} declares recalculation "
                        f"triggers {sorted(entry.recalculation_triggers)} which do not "
                        f"match its resolver declarations {sorted(declared_triggers)}."
                    ),
                    question_public_id=str(question.public_id),
                )
            )

        # -- every declared trigger must also exist in this version -----------
        for code in sorted(declared_triggers):
            if code not in grouped:
                findings.append(
                    ValidationFinding(
                        question_code=code,
                        registry_identifier=identifier,
                        validation_code=QUESTION_CODE_MISSING,
                        message=(
                            f"Recalculation trigger {code!r} of {identifier!r} does "
                            "not exist in this checklist version."
                        ),
                    )
                )

    # Deterministic ordering, and duplicates collapsed so repeated validation of
    # identical content produces identical output.
    return tuple(sorted(set(findings)))


def format_activation_errors(findings: tuple[ValidationFinding, ...]) -> dict:
    """Shape findings into the structured API error body.

    Public identifiers and governed codes only.
    """
    return {
        "error_code": "REGISTRY_VALIDATION_FAILED",
        "detail": (
            "Calculation registry bindings are invalid for this checklist version; "
            "activation was refused and nothing was changed."
        ),
        "findings": [
            {
                "question_code": finding.question_code,
                "registry_identifier": finding.registry_identifier,
                "validation_code": finding.validation_code,
                "message": finding.message,
                "question_public_id": finding.question_public_id,
            }
            for finding in findings
        ],
    }
