"""Milestone 4D-3 -- fail-closed registry binding validation at activation.

This is the ORM-backed control the pure foundation deliberately deferred: it
checks every calculation-registry binding referenced by a ``ChecklistVersion``
against that version's persisted, approved content before the version may become
executable.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-REG-018/019  activation-time validation and structured rejection
  - M4D3-DEP-005/006  graph validation at activation; form E target rules
  - M4D3-TRG-006/007  dependency and trigger set agreement
  - M4D3-FCR-012      registry_component_code selector disabled

Verified schema fact driving the duplicate check: question codes are unique per
**section** (``unique_iig_question_code_per_section``), not per version, so the
same code may legitimately appear in two sections of one version. Every lookup
therefore collects **all** matches and fails on anything other than exactly one.
No ``.first()`` and no arbitrary selection anywhere in this module.

Graph validation is **delegated** to ``calculation_graph.build_graph()``; no
graph logic is reimplemented here. This module only builds the node set from
persisted content and translates ``GraphConfigurationError`` into sanitized
findings.

This module reads only. It performs no write, opens no transaction and emits no
audit event; the caller owns the transaction and the lifecycle mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .calculation_graph import (
    ERROR_CASCADE_NODE_LIMIT_EXCEEDED,
    ERROR_DEPENDENCY_CYCLE,
    ERROR_DEPENDENCY_DEPTH_EXCEEDED,
    ERROR_DUPLICATE_NODE,
    ERROR_UNKNOWN_DEPENDENCY_CODE,
    CalculationNode,
    GraphConfigurationError,
    build_graph,
)
from .calculation_graph import (
    ERROR_UNKNOWN_REGISTRY_IDENTIFIER as GRAPH_ERROR_UNKNOWN_REGISTRY_IDENTIFIER,
)
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

#: M4D3-REG-018 -- a SYSTEM_CALCULATED question with no binding at all.
SYSTEM_CALCULATED_BINDING_MISSING = "SYSTEM_CALCULATED_BINDING_MISSING"

#: M4D3-DEP-011 -- the upstream producer of a form E dependency.
UPSTREAM_BINDING_IDENTIFIER_MISSING = "UPSTREAM_BINDING_IDENTIFIER_MISSING"
UPSTREAM_REGISTRY_IDENTIFIER_UNKNOWN = "UPSTREAM_REGISTRY_IDENTIFIER_UNKNOWN"
UPSTREAM_ANSWER_TYPE_MISMATCH = "UPSTREAM_ANSWER_TYPE_MISMATCH"
UPSTREAM_OUTPUT_UNIT_MISMATCH = "UPSTREAM_OUTPUT_UNIT_MISMATCH"
UPSTREAM_SOURCE_CLASSIFICATION_MISMATCH = "UPSTREAM_SOURCE_CLASSIFICATION_MISMATCH"

#: M4D3-DEP-005 -- graph failures surfaced from calculation_graph.build_graph().
CALCULATION_GRAPH_CYCLE = "CALCULATION_GRAPH_CYCLE"
UNKNOWN_DEPENDENCY_CODE = "UNKNOWN_DEPENDENCY_CODE"
DEPENDENCY_DEPTH_EXCEEDED = "DEPENDENCY_DEPTH_EXCEEDED"
CASCADE_NODE_LIMIT_EXCEEDED = "CASCADE_NODE_LIMIT_EXCEEDED"
DUPLICATE_GRAPH_NODE = "DUPLICATE_GRAPH_NODE"

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
        SYSTEM_CALCULATED_BINDING_MISSING,
        UPSTREAM_BINDING_IDENTIFIER_MISSING,
        UPSTREAM_REGISTRY_IDENTIFIER_UNKNOWN,
        UPSTREAM_ANSWER_TYPE_MISMATCH,
        UPSTREAM_OUTPUT_UNIT_MISMATCH,
        UPSTREAM_SOURCE_CLASSIFICATION_MISMATCH,
        CALCULATION_GRAPH_CYCLE,
        UNKNOWN_DEPENDENCY_CODE,
        DEPENDENCY_DEPTH_EXCEEDED,
        CASCADE_NODE_LIMIT_EXCEEDED,
        DUPLICATE_GRAPH_NODE,
    }
)

#: Translation of the pure graph module's error codes.  The graph module owns
#: the detection; this module owns only the sanitized presentation, so the raw
#: exception text never reaches a caller (M4D3-REG-019).
_GRAPH_ERROR_TO_VALIDATION_CODE: dict[str, str] = {
    ERROR_DEPENDENCY_CYCLE: CALCULATION_GRAPH_CYCLE,
    ERROR_UNKNOWN_DEPENDENCY_CODE: UNKNOWN_DEPENDENCY_CODE,
    ERROR_DEPENDENCY_DEPTH_EXCEEDED: DEPENDENCY_DEPTH_EXCEEDED,
    ERROR_CASCADE_NODE_LIMIT_EXCEEDED: CASCADE_NODE_LIMIT_EXCEEDED,
    ERROR_DUPLICATE_NODE: DUPLICATE_GRAPH_NODE,
    GRAPH_ERROR_UNKNOWN_REGISTRY_IDENTIFIER: UNKNOWN_REGISTRY_IDENTIFIER,
}

#: Authored, safe replacements for the graph module's internal messages.
_GRAPH_ERROR_MESSAGES: dict[str, str] = {
    CALCULATION_GRAPH_CYCLE: (
        "The calculated questions in this checklist version form a dependency "
        "cycle; no execution order exists."
    ),
    UNKNOWN_DEPENDENCY_CODE: (
        "A calculation depends on a question code that is not a calculated "
        "question in this checklist version."
    ),
    DEPENDENCY_DEPTH_EXCEEDED: (
        "The calculation dependency chain in this checklist version is deeper "
        "than the governed maximum."
    ),
    CASCADE_NODE_LIMIT_EXCEEDED: (
        "A single calculated question in this checklist version cascades to "
        "more calculated questions than the governed maximum."
    ),
    DUPLICATE_GRAPH_NODE: (
        "Two calculated questions in this checklist version share one question "
        "code; the calculation graph is ambiguous."
    ),
    UNKNOWN_REGISTRY_IDENTIFIER: (
        "A calculated question declares a calculation binding that is not an "
        "approved registry entry."
    ),
}


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """One sanitized activation-validation failure.

    Identity is the governed semantic key -- registry identifier, question code,
    validation code and public UUID.  ``message`` is presentation only and never
    participates in equality, deduplication or ordering, so one defect can never
    surface twice merely because two call sites worded it differently.

    Carries public identifiers and governed codes only -- never a database
    primary key, raw exception text, SQL or regulated answer content.
    """

    question_code: str
    registry_identifier: str
    validation_code: str
    message: str = field(compare=False)
    question_public_id: str | None = field(default=None, compare=False)

    @property
    def semantic_key(self) -> tuple[str, str, str, str]:
        """Stable governed identity used for dedup and ordering."""
        return (
            self.question_code,
            self.registry_identifier,
            self.validation_code,
            self.question_public_id or "",
        )


def _index_questions_by_code(version) -> dict[str, list]:
    """Collect every question in the version, grouped by code.

    A single query; grouping preserves duplicates so the caller can reject
    ambiguity rather than silently choose one.  Scoped to the target version
    through the persisted ownership chain, so no other version's -- and
    therefore no other tenant's -- question can ever appear here.
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
    """Return the single question for ``code`` or record a finding and None.

    This is the *only* place that emits missing/duplicate cardinality findings;
    downstream dependency and trigger validation reuses the resolved result and
    never re-reports the same defect (M4D3-REG-019).
    """
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


def _validate_upstream_producer(
    *,
    upstream,
    upstream_code: str,
    identifier: str,
    declaration,
    context: str,
    findings: list[ValidationFinding],
) -> None:
    """M4D3-DEP-011 -- the form E producer must be structurally compatible.

    Being ``SYSTEM_CALCULATED`` is necessary but not sufficient: the upstream
    question must actually be bound to a registry entry whose declared output is
    what this resolver expects to consume.  Without this, a question named as a
    dependency could be bound to a completely different calculation and the
    downstream consumer would silently read the wrong quantity.

    Units are compared for **exact equality** against the producer's declared
    ``output_unit``.  No conversion is attempted here: the approved
    specification authorises unit conversion only inside the deferred runtime
    resolver, never as an activation-time inference.
    """
    producer_identifier = (upstream.calculation_binding_identifier or "").strip()
    public_id = str(upstream.public_id)

    if not producer_identifier:
        findings.append(
            ValidationFinding(
                question_code=upstream_code,
                registry_identifier=identifier,
                validation_code=UPSTREAM_BINDING_IDENTIFIER_MISSING,
                message=(
                    f"{context} depends on question {upstream_code!r}, which declares "
                    "no calculation binding and therefore produces no outcome."
                ),
                question_public_id=public_id,
            )
        )
        return

    producer = get_entry(producer_identifier)
    if producer is None:
        findings.append(
            ValidationFinding(
                question_code=upstream_code,
                registry_identifier=identifier,
                validation_code=UPSTREAM_REGISTRY_IDENTIFIER_UNKNOWN,
                message=(
                    f"{context} depends on question {upstream_code!r}, whose binding "
                    f"{producer_identifier!r} is not an approved registry entry."
                ),
                question_public_id=public_id,
            )
        )
        return

    if producer.allowed_data_source != DataSourceClassification.SYSTEM_CALCULATED:
        findings.append(
            ValidationFinding(
                question_code=upstream_code,
                registry_identifier=identifier,
                validation_code=UPSTREAM_SOURCE_CLASSIFICATION_MISMATCH,
                message=(
                    f"{context} depends on question {upstream_code!r}, whose binding "
                    f"{producer_identifier!r} produces "
                    f"{producer.allowed_data_source!r} rather than system_calculated."
                ),
                question_public_id=public_id,
            )
        )

    if upstream.answer_type != producer.allowed_answer_type:
        findings.append(
            ValidationFinding(
                question_code=upstream_code,
                registry_identifier=identifier,
                validation_code=UPSTREAM_ANSWER_TYPE_MISMATCH,
                message=(
                    f"{context} depends on question {upstream_code!r} with answer type "
                    f"{upstream.answer_type!r}; its binding {producer_identifier!r} "
                    f"produces {producer.allowed_answer_type!r}."
                ),
                question_public_id=public_id,
            )
        )

    expected_unit = declaration.get("unit_source")
    if expected_unit is not None and producer.output_unit != expected_unit:
        findings.append(
            ValidationFinding(
                question_code=upstream_code,
                registry_identifier=identifier,
                validation_code=UPSTREAM_OUTPUT_UNIT_MISMATCH,
                message=(
                    f"{context} expects upstream question {upstream_code!r} to be "
                    f"expressed in {expected_unit!r}; its binding "
                    f"{producer_identifier!r} produces "
                    f"{producer.output_unit or 'no declared unit'!r}."
                ),
                question_public_id=public_id,
            )
        )


def _validate_bound_question(question, grouped, findings: list[ValidationFinding]) -> None:
    """Validate one question that declares a calculation binding."""
    identifier = question.calculation_binding_identifier.strip()
    entry = get_entry(identifier)
    public_id = str(question.public_id)

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
                question_public_id=public_id,
            )
        )
        return

    # -- the bound question itself must match the registry declaration --------
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
                question_public_id=public_id,
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
                question_public_id=public_id,
            )
        )

    declared_form_e: set[str] = set()
    declared_triggers: set[str] = set()

    # -- every resolver declaration must bind inside this version -------------
    for kwarg, declaration in entry.input_resolvers.items():
        source = declaration.get("source")
        context = f"Resolver {kwarg!r} of {identifier!r}"

        if source == SOURCE_QUESTION_RESPONSE:
            code = declaration["question_code"]
            declared_triggers.add(code)
            _resolve_unique(
                grouped,
                code,
                identifier=identifier,
                findings=findings,
                context=context,
            )

        elif source == SOURCE_CALCULATION_OUTCOME:
            code = declaration["question_code"]
            declared_form_e.add(code)
            declared_triggers.add(code)
            upstream = _resolve_unique(
                grouped,
                code,
                identifier=identifier,
                findings=findings,
                context=context,
            )
            if upstream is None:
                continue
            if upstream.data_source_classification != DataSourceClassification.SYSTEM_CALCULATED:
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
                continue
            _validate_upstream_producer(
                upstream=upstream,
                upstream_code=code,
                identifier=identifier,
                declaration=declaration,
                context=context,
                findings=findings,
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
                        question_public_id=public_id,
                    )
                )
                continue
            code = selector["question_code"]
            declared_triggers.add(code)
            selector_question = _resolve_unique(
                grouped,
                code,
                identifier=identifier,
                findings=findings,
                context=f"{context} component selector",
            )
            if selector_question is not None and (
                selector_question.answer_type != AnswerType.FORMULATION_COMPONENT_REFERENCE
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

    # -- declared sets must agree with the resolver declarations --------------
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
                question_public_id=public_id,
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
                question_public_id=public_id,
            )
        )

    # Note: the trigger set is deliberately NOT re-swept for missing questions
    # here.  Every trigger code reaches the version through the resolver that
    # declared it, so ``_resolve_unique`` above has already reported any that is
    # absent or ambiguous, and a trigger the resolvers never declare is a
    # registry-level disagreement already reported as TRIGGER_MISMATCH.  The
    # removed second sweep is what produced two differently worded findings for
    # one absent code.


def _validate_calculation_graph(bound_questions: list, findings: list[ValidationFinding]) -> None:
    """M4D3-DEP-005 -- delegate graph validation to the pure graph module.

    One node per bound calculated question, identified by the governed public
    response identity (never the calculation function name, so two questions
    bound to the same function stay distinct).  Edges come only from each
    entry's ``calculation_dependencies``; recalculation triggers are external
    and never become edges.

    Questions whose identifier does not resolve are excluded from the node set
    -- they already fail activation on their own -- so the graph is built from
    resolvable bindings only.  The resulting graph object is never used for
    anything except being proven valid.
    """
    nodes = tuple(
        CalculationNode(
            node_id=str(question.public_id),
            question_code=question.code,
            registry_identifier=question.calculation_binding_identifier.strip(),
        )
        for question in bound_questions
        if get_entry(question.calculation_binding_identifier.strip()) is not None
    )
    if not nodes:
        return

    try:
        build_graph(nodes)
    except GraphConfigurationError as exc:
        validation_code = _GRAPH_ERROR_TO_VALIDATION_CODE.get(
            exc.error_code, CALCULATION_GRAPH_CYCLE
        )
        findings.append(
            ValidationFinding(
                question_code="",
                registry_identifier="",
                validation_code=validation_code,
                message=_GRAPH_ERROR_MESSAGES[validation_code],
            )
        )


def validate_version_calculation_bindings(version) -> tuple[ValidationFinding, ...]:
    """Validate every calculation binding referenced by ``version``.

    Only identifiers actually referenced by the version's questions are checked;
    unreferenced registry entries never block activation (M4D3-REG-018 applies
    per bound question, not to the global registry).

    Every ``SYSTEM_CALCULATED`` question is validated whether or not it carries a
    binding: ``Model.clean()`` couples the two, but it is not a database
    constraint and rows can be created through paths that bypass
    ``full_clean()``, so activation re-establishes the invariant itself.

    Returns findings in a stable order keyed on governed fields only. An empty
    tuple means the version's calculation bindings are internally consistent and
    safe to activate.
    """
    grouped = _index_questions_by_code(version)
    findings: list[ValidationFinding] = []

    bound_questions: list = []
    for questions in grouped.values():
        for question in questions:
            identifier = (question.calculation_binding_identifier or "").strip()
            is_calculated = (
                question.data_source_classification == DataSourceClassification.SYSTEM_CALCULATED
            )
            if identifier:
                bound_questions.append(question)
            elif is_calculated:
                findings.append(
                    ValidationFinding(
                        question_code=question.code,
                        registry_identifier="",
                        validation_code=SYSTEM_CALCULATED_BINDING_MISSING,
                        message=(
                            f"Question {question.code!r} is system_calculated but "
                            "declares no calculation binding identifier, so no "
                            "approved calculation can produce its value."
                        ),
                        question_public_id=str(question.public_id),
                    )
                )

    for question in bound_questions:
        _validate_bound_question(question, grouped, findings)

    _validate_calculation_graph(bound_questions, findings)

    # Deterministic ordering with semantic (not message-based) deduplication, so
    # repeated validation of identical content produces identical output and one
    # defect yields exactly one finding.
    unique: dict[tuple[str, str, str, str], ValidationFinding] = {}
    for finding in findings:
        unique.setdefault(finding.semantic_key, finding)
    return tuple(unique[key] for key in sorted(unique))


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
