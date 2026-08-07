"""Milestone 4D-3 ORM Phase 2 -- governed calculation input resolution.

``resolve_calculation_inputs()`` turns an approved registry entry's immutable
resolver declarations into concrete, unit-normalised kwargs read from persisted
rows.  It is the layer the activation gate exists to protect: activation proves
a version's bindings *can* resolve, and this service performs the resolution.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-INP-003..008  the six approved resolver forms
  - M4D3-FCR-002..014  subject-component selector; form B selector disabled
  - M4D3-MDU-001..024  conservative maximum-daily-units selection
  - M4D3-DEP-011       form E resolves the same subject component
  - M4D3-IFV-001..008  closed input-failure vocabulary, deterministic mapping
  - M4D3-PRV-005..008  subject-component outcome provenance contract
  - M4D3-PST-002/009   REVIEW_REQUIRED marker representation
  - M4D3-UNC-001..011  governed unit conversion

Resolution runs in four deterministic phases so that behaviour can never depend
on what a resolver kwarg happens to be called:

  A. validate the caller's objects and resolve the registry entry;
  B. establish the effective subject component **once**, from the selector and
     from every component-scoped upstream outcome, and fail if they disagree;
  C. resolve every declared input against that finalized component;
  D. build the immutable result.

An earlier revision established the component inside the single resolution loop,
so a form D snapshot whose kwarg sorted before its form E dependency was checked
against a component that had not been established yet.  Phase B exists to make
that class of defect structurally impossible.

Deliberate boundaries, all enforced by tests:

* **No writes.**  No ``save()``, ``create()``, ``update()`` or ``delete()``
  anywhere in this module.  Nothing is persisted, no audit event is emitted and
  no background task is queued.
* **No calculation.**  A registry entry's ``function`` is never called; this
  service only assembles its kwargs.
* **No transaction of its own.**  Every read joins whatever transaction the
  caller already owns, so a governed mutation can lock rows first and rely on
  repeatable reads.
* **No reflection.**  Every field a resolver may read is dispatched through a
  closed accessor table.  No ``getattr`` on a client- or registry-supplied
  name, no dotted traversal, no dynamic import.
* **No ``.first()``.**  Every lookup collects all matches and fails closed on
  anything other than exactly one.

Rows a future mutating caller must lock, in this order, before calling:

1. the ``ChecklistExecution``;
2. the involved ``ChecklistResponse`` rows, ordered by ``public_id``;
3. the involved ``CalculationOutcome`` rows, ordered by ``public_id``;
4. the ``AssessmentSnapshot`` the caller itself selected or created.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from .calculation_registry import (
    COMPONENT_TYPES,
    DISABLED_SELECTOR_TYPES,
    SELECTOR_RESPONSE_REFERENCE,
    SOURCE_ASSESSMENT_SNAPSHOT,
    SOURCE_CALCULATION_OUTCOME,
    SOURCE_CONSTANT,
    SOURCE_FORMULATION_FIELD,
    SOURCE_MAXIMUM_DAILY_UNITS,
    SOURCE_QUESTION_RESPONSE,
    SnapshotUnitRef,
    get_entry,
)
from .calculation_translation import (
    ALLOWED_INPUT_FAILURE_CODES,
    SUBJECT_COMPONENT_PROVENANCE_KEY,
)
from .enums import AnswerType, CalculationStatus, DataSourceClassification
from .unit_adapter import CONVERSION_RULE_VERSION, convert_for_calculation

# ---------------------------------------------------------------------------
# Governed failure codes actually emitted by this service.  Every one is drawn
# from ALLOWED_INPUT_FAILURE_CODES; nothing new is invented here.
# ---------------------------------------------------------------------------

F_RESPONSE_MISSING = "INPUT_RESPONSE_MISSING"
F_RESPONSE_NOT_APPLICABLE = "INPUT_RESPONSE_NOT_APPLICABLE"
F_REVIEW_REQUIRED = "INPUT_REVIEW_REQUIRED"
F_VALUE_INVALID = "INPUT_VALUE_INVALID"
F_UNIT_MISSING = "INPUT_UNIT_MISSING"
F_UNIT_UNSUPPORTED = "INPUT_UNIT_UNSUPPORTED"
F_UNIT_DIMENSION_MISMATCH = "INPUT_UNIT_DIMENSION_MISMATCH"
F_COMPONENT_MISSING = "FORMULATION_COMPONENT_MISSING"
F_COMPONENT_AMBIGUOUS = "FORMULATION_COMPONENT_AMBIGUOUS"
F_COMPONENT_TYPE_MISMATCH = "FORMULATION_COMPONENT_TYPE_MISMATCH"
F_COMPONENT_WRONG_FORMULATION = "FORMULATION_COMPONENT_WRONG_FORMULATION"
F_COMPONENT_TENANT_MISMATCH = "FORMULATION_COMPONENT_TENANT_MISMATCH"
F_COMPONENT_REFERENCE_INVALID = "FORMULATION_COMPONENT_REFERENCE_INVALID"
F_FORMULATION_FIELD_MISSING = "FORMULATION_FIELD_MISSING"
F_SNAPSHOT_MISSING = "ASSESSMENT_SNAPSHOT_MISSING"
F_SNAPSHOT_TENANT_MISMATCH = "ASSESSMENT_SNAPSHOT_TENANT_MISMATCH"
F_SNAPSHOT_COMPONENT_MISMATCH = "ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH"
F_SNAPSHOT_RELEASE_MISMATCH = "ASSESSMENT_SNAPSHOT_RELEASE_MISMATCH"
F_ASSESSMENT_FIELD_MISSING = "ASSESSMENT_FIELD_MISSING"
F_UPSTREAM_MISSING = "UPSTREAM_CALCULATION_MISSING"
F_UPSTREAM_INCOMPLETE = "UPSTREAM_CALCULATION_INCOMPLETE"
F_UPSTREAM_DUPLICATE = "UPSTREAM_CALCULATION_DUPLICATE"
F_UPSTREAM_COMPONENT_MISMATCH = "UPSTREAM_CALCULATION_COMPONENT_MISMATCH"
F_UPSTREAM_NAME_MISMATCH = "UPSTREAM_CALCULATION_NAME_MISMATCH"
F_TENANT_MISMATCH = "INPUT_TENANT_MISMATCH"
F_RESOLVER_UNKNOWN = "INPUT_RESOLVER_UNKNOWN"

#: M4D3-PST-002 -- reserved marker prefix in ``not_applicable_reason``.
REVIEW_REQUIRED_MARKER = "REVIEW_REQUIRED:"

SOURCE_KIND_QUESTION_RESPONSE = "question_response"
SOURCE_KIND_FORMULATION_VERSION = "formulation_version"
SOURCE_KIND_FORMULATION_COMPONENT = "formulation_component"
SOURCE_KIND_MAXIMUM_DAILY_UNITS = "maximum_daily_units"
SOURCE_KIND_ASSESSMENT_SNAPSHOT = "assessment_snapshot"
SOURCE_KIND_CALCULATION_OUTCOME = "calculation_outcome"
SOURCE_KIND_CONSTANT = "constant"

#: Where a component identity came from, for reconciliation and provenance.
COMPONENT_SOURCE_SELECTOR = "selector"
COMPONENT_SOURCE_INHERITED = "inherited"


class CalculationInputContractError(RuntimeError):
    """The caller passed objects that violate this service's contract.

    Reserved for server-side programming faults that no client input can
    reach -- a target question from another checklist version, or a target whose
    answer type disagrees with its registry entry.  Data conditions are never
    raised; they are returned as governed :class:`InputFailure` records.
    """


# ---------------------------------------------------------------------------
# Closed accessor tables.  A resolver may read exactly these fields and no
# others; an unlisted name is a configuration fault, never a dynamic lookup.
# ---------------------------------------------------------------------------

_FORMULATION_VERSION_VALUE_FIELDS: MappingProxyType[str, Any] = MappingProxyType(
    {
        "total_dosage_unit_weight": lambda fv: fv.total_dosage_unit_weight,
        "maximum_dosage_units_per_day": lambda fv: fv.maximum_dosage_units_per_day,
        "batch_size": lambda fv: fv.batch_size,
        "overage_percentage": lambda fv: fv.overage_percentage,
    }
)

_FORMULATION_VERSION_UNIT_FIELDS: MappingProxyType[str, Any] = MappingProxyType(
    {
        "total_dosage_unit_weight_unit": lambda fv: fv.total_dosage_unit_weight_unit,
        "batch_size_unit": lambda fv: fv.batch_size_unit,
    }
)

_FORMULATION_COMPONENT_VALUE_FIELDS: MappingProxyType[str, Any] = MappingProxyType(
    {
        "quantity_per_dosage_unit": lambda c: c.quantity_per_dosage_unit,
        "quantity_per_batch": lambda c: c.quantity_per_batch,
        "overage_amount": lambda c: c.overage_amount,
        "percentage_w_w_snapshot": lambda c: c.percentage_w_w_snapshot,
    }
)

_FORMULATION_COMPONENT_UNIT_FIELDS: MappingProxyType[str, Any] = MappingProxyType(
    {
        "quantity_unit": lambda c: c.quantity_unit,
        "batch_quantity_unit": lambda c: c.batch_quantity_unit,
    }
)

_SNAPSHOT_VALUE_FIELDS: MappingProxyType[str, Any] = MappingProxyType(
    {
        "iid_potency_amount": lambda s: s.iid_potency_amount,
        "iid_mde": lambda s: s.iid_mde,
    }
)

_SNAPSHOT_UNIT_FIELDS: MappingProxyType[str, Any] = MappingProxyType(
    {
        "iid_potency_unit": lambda s: s.iid_potency_unit,
        "iid_mde_unit": lambda s: s.iid_mde_unit,
    }
)


# ---------------------------------------------------------------------------
# Deep immutability
# ---------------------------------------------------------------------------


def freeze(value: Any) -> Any:
    """Return a recursively immutable view of ``value``.

    Mappings become ``MappingProxyType``, sequences tuples and sets frozensets,
    all the way down, so no nested structure inside provenance can be mutated
    after the fact.  Scalars -- including ``Decimal``, ``UUID`` and ``str`` --
    are returned unchanged, so structured provenance is never stringified.
    """
    if isinstance(value, str | bytes | bytearray):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, Set):
        return frozenset(freeze(item) for item in value)
    if isinstance(value, Sequence):
        return tuple(freeze(item) for item in value)
    return value


# ---------------------------------------------------------------------------
# Immutable result structures (M4D3-INP-009)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedInput:
    """One successfully resolved calculation kwarg with full provenance."""

    kwarg_name: str
    value: Any
    expected_type: str
    source_kind: str
    source_public_uuid: str | None = None
    source_question_code: str | None = None
    source_unit: str | None = None
    target_unit: str | None = None
    conversion_factor: str | None = None
    conversion_rule_version: str | None = None
    detail_code: str | None = None
    provenance: Mapping = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class InputFailure:
    """One governed input-resolution failure.

    Identity is the governed semantic key; ``message`` is presentation only and
    never participates in ordering or equality, so wording can neither create
    nor hide a failure.  Carries public UUIDs and governed codes only.
    """

    kwarg_name: str
    failure_code: str
    source_kind: str
    message: str = field(compare=False, default="")
    source_question_code: str | None = field(compare=False, default=None)
    source_public_uuid: str | None = field(compare=False, default=None)

    @property
    def semantic_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.kwarg_name,
            self.failure_code,
            self.source_kind,
            self.source_question_code or "",
            self.source_public_uuid or "",
        )


@dataclass(frozen=True, slots=True)
class ResolvedCalculationInputs:
    """The complete, all-or-nothing outcome of one resolution attempt."""

    registry_identifier: str
    calculation_name: str
    formula_version: str
    binding_version: str
    kwargs: Mapping
    inputs: tuple[ResolvedInput, ...]
    failures: tuple[InputFailure, ...]
    subject_component_public_id: str | None = None
    subject_component_sources: tuple[str, ...] = ()
    assessment_snapshot_public_id: str | None = None
    upstream_outcome_public_ids: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        """True only when every declared input resolved.

        There is deliberately no partial success: a caller can never reach a
        calculation with some kwargs filled and others missing.
        """
        return not self.failures

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(failure.failure_code for failure in self.failures)


@dataclass(frozen=True, slots=True)
class _ComponentResolution:
    """Phase B result: the one subject component every input must agree with."""

    state: str
    public_id: str | None = None
    component: Any = None
    sources: tuple[str, ...] = ()


STATE_NOT_REQUIRED = "not_required"
STATE_RESOLVED = "resolved"
STATE_FAILED = "failed"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _fail(
    failures: list[InputFailure],
    *,
    kwarg: str,
    code: str,
    source_kind: str,
    message: str,
    question_code: str | None = None,
    public_uuid: str | None = None,
) -> None:
    """Record one governed failure.  Codes are asserted against the vocabulary."""
    if code not in ALLOWED_INPUT_FAILURE_CODES:  # pragma: no cover - guard
        code = "UNKNOWN_INTERNAL_FAILURE"
    failures.append(
        InputFailure(
            kwarg_name=kwarg,
            failure_code=code,
            source_kind=source_kind,
            message=message,
            source_question_code=question_code,
            source_public_uuid=public_uuid,
        )
    )


def _decimal_from_string(raw: object) -> Decimal | None:
    """Governed decimal strings only -- never a float, never a bare int."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if value.is_nan() or value.is_infinite():
        return None
    return value


def _questions_with_code(execution, code: str) -> list:
    """Every question with ``code`` in the execution's own checklist version."""
    from .models import ChecklistQuestion

    return list(
        ChecklistQuestion.objects.filter(
            section__checklist_version_id=execution.checklist_version_id,
            code=code,
        ).order_by("section__display_order", "display_order")
    )


def _responses_for_question(execution, question) -> list:
    from .models import ChecklistResponse

    return list(
        ChecklistResponse.objects.filter(execution=execution, question=question).order_by(
            "public_id"
        )
    )


def _applicability_outcome(response) -> str:
    """M4D3-PST-009 -- derive applicability from persisted state only."""
    if response.is_not_applicable:
        return "not_applicable"
    if (response.not_applicable_reason or "").startswith(REVIEW_REQUIRED_MARKER):
        return "review_required"
    return "applicable"


def _resolve_response(
    execution,
    code: str,
    *,
    kwarg: str,
    source_kind: str,
    failures: list[InputFailure],
):
    """Resolve exactly one applicable response for ``code`` in ``execution``.

    Returns ``(response, question)`` or ``(None, None)`` having recorded one
    governed failure.  Never ``.first()``: zero and many are distinct faults,
    and many is a *configuration* fault rather than missing data, so it never
    reaches the DATA_REQUIRED category (M4D3-IFV-004).
    """
    questions = _questions_with_code(execution, code)
    if not questions:
        _fail(
            failures, kwarg=kwarg, code=F_RESPONSE_MISSING, source_kind=source_kind,
            message=f"No question with code {code!r} exists in this execution's version.",
            question_code=code,
        )
        return None, None
    if len(questions) > 1:
        _fail(
            failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=(
                f"Question code {code!r} resolves to {len(questions)} questions in this "
                "execution's version; the binding is ambiguous."
            ),
            question_code=code,
        )
        return None, None

    question = questions[0]
    responses = _responses_for_question(execution, question)
    if not responses:
        _fail(
            failures, kwarg=kwarg, code=F_RESPONSE_MISSING, source_kind=source_kind,
            message=f"No response exists for question {code!r} in this execution.",
            question_code=code,
        )
        return None, None
    if len(responses) > 1:  # pragma: no cover - unique constraint prevents this
        _fail(
            failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=f"Question {code!r} has more than one response in this execution.",
            question_code=code,
        )
        return None, None

    response = responses[0]
    outcome = _applicability_outcome(response)
    if outcome == "not_applicable":
        _fail(
            failures, kwarg=kwarg, code=F_RESPONSE_NOT_APPLICABLE, source_kind=source_kind,
            message=f"Response for {code!r} is marked not applicable.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None, None
    if outcome == "review_required":
        _fail(
            failures, kwarg=kwarg, code=F_REVIEW_REQUIRED, source_kind=source_kind,
            message=f"Response for {code!r} carries a REVIEW_REQUIRED marker.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None, None
    return response, question


# ---------------------------------------------------------------------------
# Unit handling (M4D3-UNC-001..011)
# ---------------------------------------------------------------------------


def _target_unit(
    declaration,
    snapshot,
    *,
    kwarg: str,
    source_kind: str,
    failures: list[InputFailure],
) -> tuple[str | None, bool]:
    """Resolve the declared target unit.

    ``SnapshotUnitRef`` is handled explicitly rather than compared as a string,
    so a reference unit is read from the snapshot field it names.  Returns
    ``(unit, ok)``; ``unit`` is None when the declaration requires no
    conversion.
    """
    required = declaration.get("required_unit")
    if required is None:
        return None, True

    if isinstance(required, SnapshotUnitRef):
        if snapshot is None:
            _fail(
                failures, kwarg=kwarg, code=F_SNAPSHOT_MISSING, source_kind=source_kind,
                message=(
                    f"Target unit for {kwarg!r} is the snapshot field "
                    f"{required.unit_field!r}, but no assessment snapshot was supplied."
                ),
            )
            return None, False
        accessor = _SNAPSHOT_UNIT_FIELDS.get(required.unit_field)
        if accessor is None:  # pragma: no cover - registry validates the name
            _fail(
                failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
                message=f"{required.unit_field!r} is not a readable snapshot unit field.",
            )
            return None, False
        unit = accessor(snapshot)
        if not unit:
            _fail(
                failures, kwarg=kwarg, code=F_UNIT_MISSING, source_kind=source_kind,
                message=(
                    f"Snapshot unit field {required.unit_field!r} is empty, so "
                    f"{kwarg!r} has no target unit."
                ),
                public_uuid=str(snapshot.public_id),
            )
            return None, False
        return str(unit), True

    if not isinstance(required, str) or not required.strip():
        _fail(
            failures, kwarg=kwarg, code=F_UNIT_MISSING, source_kind=source_kind,
            message=f"Declared target unit for {kwarg!r} is empty.",
        )
        return None, False
    return required, True


def _convert(
    value: Decimal,
    source_unit: str | None,
    target_unit: str | None,
    *,
    kwarg: str,
    source_kind: str,
    failures: list[InputFailure],
    question_code: str | None = None,
    public_uuid: str | None = None,
) -> tuple[Decimal | None, dict]:
    """Convert through the approved adapter, or record the governed failure."""
    if target_unit is None:
        return value, {}
    if not source_unit or not str(source_unit).strip():
        _fail(
            failures, kwarg=kwarg, code=F_UNIT_MISSING, source_kind=source_kind,
            message=f"{kwarg!r} requires {target_unit!r} but its source unit is absent.",
            question_code=question_code, public_uuid=public_uuid,
        )
        return None, {}

    outcome = convert_for_calculation(
        value=value, from_unit=str(source_unit), to_unit=target_unit
    )
    if not outcome.ok:
        code = outcome.failure_code or "UNKNOWN_INTERNAL_FAILURE"
        _fail(
            failures, kwarg=kwarg, code=code, source_kind=source_kind,
            message=(
                f"{kwarg!r} could not be expressed in {target_unit!r} from "
                f"{str(source_unit)!r}."
            ),
            question_code=question_code, public_uuid=public_uuid,
        )
        return None, {}
    return outcome.value, dict(outcome.provenance)


# ---------------------------------------------------------------------------
# Phase B -- subject component (M4D3-FCR-002..014, M4D3-DEP-011)
# ---------------------------------------------------------------------------


def _component_in_execution(execution, component_uuid):
    """Return the component with ``component_uuid`` inside this execution.

    Scoped to the execution's own formulation version, so a component belonging
    to another formulation -- and therefore possibly another tenant -- can never
    be returned, and its identity is never echoed back to the caller.
    """
    from formulations.models import FormulationComponent

    matches = list(
        FormulationComponent.objects.filter(
            public_id=component_uuid,
            formulation_version_id=execution.formulation_version_id,
        ).select_related("formulation_version__product")
    )
    if len(matches) != 1:
        return None
    return matches[0]


def _resolve_selector_component(
    execution, declaration, *, kwarg: str, failures: list[InputFailure]
):
    """Resolve the subject component through the enabled selector only.

    No ingredient-name match, no UNII fallback, no display-order or primary-key
    inference: the component is whatever the selector response explicitly
    references, or nothing.
    """
    selector = declaration.get("component_selector")
    source_kind = SOURCE_KIND_FORMULATION_COMPONENT

    if selector is None:  # pragma: no cover - caller only passes selector decls
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
            message=f"{kwarg!r} reads a component but declares no selector.",
        )
        return None
    selector_type = selector.get("type")
    if selector_type in DISABLED_SELECTOR_TYPES or selector_type != SELECTOR_RESPONSE_REFERENCE:
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
            message=f"Component selector form {selector_type!r} is not enabled.",
        )
        return None

    code = selector["question_code"]
    response, question = _resolve_response(
        execution, code, kwarg=kwarg, source_kind=source_kind, failures=failures
    )
    if response is None:
        return None

    if question.answer_type != AnswerType.FORMULATION_COMPONENT_REFERENCE:
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_REFERENCE_INVALID, source_kind=source_kind,
            message=(
                f"Selector question {code!r} has answer type {question.answer_type!r}; "
                "formulation_component_reference is required."
            ),
            question_code=code, public_uuid=str(response.public_id),
        )
        return None

    payload = response.raw_value
    if not isinstance(payload, dict) or set(payload) != {"public_id"}:
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_REFERENCE_INVALID, source_kind=source_kind,
            message=f"Selector response {code!r} does not hold exactly {{'public_id'}}.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None
    try:
        component_uuid = uuid.UUID(str(payload["public_id"]))
    except (ValueError, AttributeError, TypeError):
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_REFERENCE_INVALID, source_kind=source_kind,
            message=f"Selector response {code!r} does not hold a valid UUID.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None

    from formulations.models import FormulationComponent

    matches = list(
        FormulationComponent.objects.filter(public_id=component_uuid).select_related(
            "formulation_version__product"
        )
    )
    if not matches:
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_MISSING, source_kind=source_kind,
            message=f"Selector response {code!r} references no existing component.",
            question_code=code,
        )
        return None
    if len(matches) > 1:  # pragma: no cover - public_id is unique
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_AMBIGUOUS, source_kind=source_kind,
            message=f"Selector response {code!r} resolves to more than one component.",
            question_code=code,
        )
        return None

    component = matches[0]
    if component.formulation_version_id != execution.formulation_version_id:
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_WRONG_FORMULATION, source_kind=source_kind,
            message=(
                f"Selector response {code!r} references a component outside this "
                "execution's formulation version."
            ),
            question_code=code,
        )
        return None
    if component.formulation_version.product.tenant_id != execution.tenant_id:
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_TENANT_MISMATCH, source_kind=source_kind,
            message=f"Selector response {code!r} references another tenant's component.",
            question_code=code,
        )
        return None

    required_type = declaration.get("required_component_type")
    if required_type in COMPONENT_TYPES and component.component_type != required_type:
        _fail(
            failures, kwarg=kwarg, code=F_COMPONENT_TYPE_MISMATCH, source_kind=source_kind,
            message=(
                f"Subject component is {component.component_type!r}; this calculation "
                f"requires {required_type!r}."
            ),
            question_code=code, public_uuid=str(component.public_id),
        )
        return None
    return component


@dataclass(frozen=True, slots=True)
class _Upstream:
    """A validated upstream calculated response and its single outcome."""

    kwarg: str
    code: str
    response: Any
    question: Any
    outcome: Any


def _locate_upstream(execution, kwarg, declaration, failures) -> _Upstream | None:
    """Find and validate the one current outcome for a form E dependency.

    ``create_execution()`` creates exactly one ``CalculationOutcome`` per
    calculated response and M4D3-MDL-010 forbids additional rows, so "current"
    is unambiguous: the single row for that response.  Anything else is a
    data-integrity fault, never an arbitrary choice.
    """
    from .models import CalculationOutcome

    source_kind = SOURCE_KIND_CALCULATION_OUTCOME
    code = declaration["question_code"]

    response, question = _resolve_response(
        execution, code, kwarg=kwarg, source_kind=source_kind, failures=failures
    )
    if response is None:
        return None

    if question.data_source_classification != DataSourceClassification.SYSTEM_CALCULATED:
        _fail(
            failures, kwarg=kwarg, code=F_UPSTREAM_MISSING, source_kind=source_kind,
            message=f"Upstream question {code!r} is not system_calculated.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None

    outcomes = list(
        CalculationOutcome.objects.filter(response=response).order_by("public_id")
    )
    if not outcomes:
        _fail(
            failures, kwarg=kwarg, code=F_UPSTREAM_MISSING, source_kind=source_kind,
            message=f"No calculation outcome exists for upstream question {code!r}.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None
    if len(outcomes) > 1:
        _fail(
            failures, kwarg=kwarg, code=F_UPSTREAM_DUPLICATE, source_kind=source_kind,
            message=(
                f"Upstream question {code!r} has {len(outcomes)} calculation outcomes; "
                "the current result is ambiguous."
            ),
            question_code=code, public_uuid=str(response.public_id),
        )
        return None

    outcome = outcomes[0]
    outcome_uuid = str(outcome.public_id)
    required_status = declaration.get("required_status", CalculationStatus.COMPLETE)
    if outcome.status != required_status:
        _fail(
            failures, kwarg=kwarg, code=F_UPSTREAM_INCOMPLETE, source_kind=source_kind,
            message=(
                f"Upstream outcome for {code!r} is {outcome.status!r}, not "
                f"{required_status!r}."
            ),
            question_code=code, public_uuid=outcome_uuid,
        )
        return None
    if outcome.value is None:
        _fail(
            failures, kwarg=kwarg, code=F_UPSTREAM_INCOMPLETE, source_kind=source_kind,
            message=f"Upstream outcome for {code!r} holds no value.",
            question_code=code, public_uuid=outcome_uuid,
        )
        return None

    # The stored result must have been produced by the calculation the registry
    # declares for that question -- an outcome carrying a different calculation
    # name is a different quantity, however complete it looks.
    upstream_entry = get_entry((question.calculation_binding_identifier or "").strip())
    if upstream_entry is None:
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
            message=(
                f"Upstream question {code!r} declares a calculation binding that is "
                "not an approved registry entry."
            ),
            question_code=code, public_uuid=outcome_uuid,
        )
        return None
    if outcome.calculation_name != upstream_entry.calculation_name:
        _fail(
            failures, kwarg=kwarg, code=F_UPSTREAM_NAME_MISMATCH, source_kind=source_kind,
            message=(
                f"Upstream outcome for {code!r} records calculation "
                f"{outcome.calculation_name!r}; its binding declares "
                f"{upstream_entry.calculation_name!r}."
            ),
            question_code=code, public_uuid=outcome_uuid,
        )
        return None

    return _Upstream(
        kwarg=kwarg, code=code, response=response, question=question, outcome=outcome
    )


def _upstream_component_id(execution, upstream, failures) -> tuple[str | None, bool]:
    """Read the subject component an upstream outcome was produced for.

    M4D3-PRV-005..008: a component-scoped calculation records its subject
    component under the reserved, server-controlled provenance key.  Absence is
    a fault, never an assumption of agreement, and there is deliberately no
    fallback to the current selector -- that would silently accept a stale
    result computed for a different component.

    Returns ``(public_id_or_None, ok)``.
    """
    source_kind = SOURCE_KIND_CALCULATION_OUTCOME
    outcome_uuid = str(upstream.outcome.public_id)
    entry = get_entry((upstream.question.calculation_binding_identifier or "").strip())
    component_scoped = entry is not None and any(
        declared.get("component_selector") is not None
        for declared in entry.input_resolvers.values()
    )

    provenance = upstream.outcome.input_provenance
    if not isinstance(provenance, dict):
        provenance = {}
    recorded = provenance.get(SUBJECT_COMPONENT_PROVENANCE_KEY)

    if recorded is None:
        if component_scoped:
            _fail(
                failures, kwarg=upstream.kwarg, code=F_UPSTREAM_COMPONENT_MISMATCH,
                source_kind=source_kind,
                message=(
                    f"Upstream outcome for {upstream.code!r} records no subject "
                    "component, so it cannot be proven to describe this component."
                ),
                question_code=upstream.code, public_uuid=outcome_uuid,
            )
            return None, False
        return None, True

    if not isinstance(recorded, str):
        _fail(
            failures, kwarg=upstream.kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=(
                f"Upstream outcome for {upstream.code!r} records a malformed subject "
                "component provenance value."
            ),
            question_code=upstream.code, public_uuid=outcome_uuid,
        )
        return None, False
    try:
        component_uuid = uuid.UUID(recorded)
    except (ValueError, AttributeError, TypeError):
        _fail(
            failures, kwarg=upstream.kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=(
                f"Upstream outcome for {upstream.code!r} records a subject component "
                "value that is not a valid UUID."
            ),
            question_code=upstream.code, public_uuid=outcome_uuid,
        )
        return None, False

    # M4D3-PRV-005 -- the canonical rendering is the stored form, so an
    # uppercase, braced, URN or compact UUID is rejected rather than silently
    # normalised.  Accepting a second spelling would let two provenance values
    # denote one component, which is exactly what a canonical form exists to
    # prevent in a regulated record.
    if recorded != str(component_uuid):
        _fail(
            failures, kwarg=upstream.kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=(
                f"Upstream outcome for {upstream.code!r} records a subject component "
                "UUID that is not in canonical lowercase hyphenated form."
            ),
            question_code=upstream.code, public_uuid=outcome_uuid,
        )
        return None, False

    if _component_in_execution(execution, component_uuid) is None:
        _fail(
            failures, kwarg=upstream.kwarg, code=F_UPSTREAM_COMPONENT_MISMATCH,
            source_kind=source_kind,
            message=(
                f"Upstream outcome for {upstream.code!r} names a subject component "
                "that is not part of this execution's formulation version."
            ),
            question_code=upstream.code, public_uuid=outcome_uuid,
        )
        return None, False
    return str(component_uuid), True


def _resolve_subject_component(
    execution, entry, upstreams: dict[str, _Upstream], failures: list[InputFailure]
) -> _ComponentResolution:
    """Phase B -- establish the one subject component, before any input uses it.

    Every candidate identity is collected first and reconciled once: the
    selector where the entry declares one, plus the component recorded by every
    component-scoped upstream outcome it consumes.  Disagreement fails closed;
    no source silently wins.  The result never depends on kwarg names, kwarg
    ordering or dictionary insertion order.
    """
    candidates: dict[str, set[str]] = {}
    failed = False

    selector_declarations = [
        (kwarg, declaration)
        for kwarg, declaration in sorted(entry.input_resolvers.items())
        if declaration.get("component_selector") is not None
    ]
    component_object = None
    if selector_declarations:
        first_kwarg, first_declaration = selector_declarations[0]
        component_object = _resolve_selector_component(
            execution, first_declaration, kwarg=first_kwarg, failures=failures
        )
        if component_object is None:
            failed = True
        else:
            candidates.setdefault(str(component_object.public_id), set()).add(
                COMPONENT_SOURCE_SELECTOR
            )

    for kwarg in sorted(upstreams):
        component_id, ok = _upstream_component_id(execution, upstreams[kwarg], failures)
        if not ok:
            failed = True
            continue
        if component_id is not None:
            candidates.setdefault(component_id, set()).add(COMPONENT_SOURCE_INHERITED)

    if failed:
        return _ComponentResolution(state=STATE_FAILED)
    if not candidates:
        return _ComponentResolution(state=STATE_NOT_REQUIRED)
    if len(candidates) > 1:
        # Every relevant source must agree; there is no precedence order that
        # could make one of two different components the right answer.
        _fail(
            failures, kwarg="", code=F_UPSTREAM_COMPONENT_MISMATCH,
            source_kind=SOURCE_KIND_FORMULATION_COMPONENT,
            message=(
                "The subject component identities implied by this calculation's "
                "selector and its upstream outcomes disagree."
            ),
        )
        return _ComponentResolution(state=STATE_FAILED)

    public_id, sources = next(iter(candidates.items()))
    if component_object is None:
        component_object = _component_in_execution(execution, uuid.UUID(public_id))
    return _ComponentResolution(
        state=STATE_RESOLVED,
        public_id=public_id,
        component=component_object,
        sources=tuple(sorted(sources)),
    )


# ---------------------------------------------------------------------------
# Phase C -- resolver forms
# ---------------------------------------------------------------------------


def _resolve_question_response(execution, kwarg, declaration, snapshot, failures):
    """Form A -- M4D3-INP-003."""
    source_kind = SOURCE_KIND_QUESTION_RESPONSE
    code = declaration["question_code"]
    response, question = _resolve_response(
        execution, code, kwarg=kwarg, source_kind=source_kind, failures=failures
    )
    if response is None:
        return None

    # M4D3-INP-003 -- a calculated response's raw_value is permanently null, so
    # form A may never be used to read one as a calculation result.
    if question.data_source_classification == DataSourceClassification.SYSTEM_CALCULATED:
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
            message=(
                f"Question {code!r} is system_calculated; form A cannot read a "
                "calculated result. Use a calculation_outcome resolver."
            ),
            question_code=code, public_uuid=str(response.public_id),
        )
        return None

    raw = response.raw_value
    if raw is None:
        _fail(
            failures, kwarg=kwarg, code=F_RESPONSE_MISSING, source_kind=source_kind,
            message=f"Response for {code!r} holds no value.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None

    from .response_validation import InvalidRawValueShape, validate_raw_value_shape

    try:
        validate_raw_value_shape(
            question.answer_type, raw, question=question, execution=execution,
            tenant=execution.tenant,
        )
    except InvalidRawValueShape:
        _fail(
            failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=f"Response for {code!r} does not match its declared answer shape.",
            question_code=code, public_uuid=str(response.public_id),
        )
        return None

    expected_type = declaration["expected_type"]
    if expected_type == "decimal":
        if not isinstance(raw, dict) or "value" not in raw:
            _fail(
                failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
                message=f"Response for {code!r} carries no decimal value.",
                question_code=code, public_uuid=str(response.public_id),
            )
            return None
        value = _decimal_from_string(raw.get("value"))
        if value is None:
            _fail(
                failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
                message=f"Response for {code!r} does not hold a valid decimal string.",
                question_code=code, public_uuid=str(response.public_id),
            )
            return None
        source_unit = raw.get("unit") or declaration.get("unit_source")
        target, ok = _target_unit(
            declaration, snapshot, kwarg=kwarg, source_kind=source_kind, failures=failures
        )
        if not ok:
            return None
        converted, conversion = _convert(
            value, source_unit, target, kwarg=kwarg, source_kind=source_kind,
            failures=failures, question_code=code, public_uuid=str(response.public_id),
        )
        if converted is None:
            return None
        return ResolvedInput(
            kwarg_name=kwarg,
            value=converted,
            expected_type=expected_type,
            source_kind=source_kind,
            source_public_uuid=str(response.public_id),
            source_question_code=code,
            source_unit=str(source_unit) if source_unit else None,
            target_unit=target,
            conversion_factor=conversion.get("conversion_factor"),
            conversion_rule_version=conversion.get("conversion_rule_version"),
            provenance=freeze(
                {
                    "response_public_id": str(response.public_id),
                    "question_code": code,
                    **conversion,
                }
            ),
        )

    if expected_type == "string":
        text = raw.get("value") if isinstance(raw, dict) else raw
        if not isinstance(text, str) or not text.strip():
            _fail(
                failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
                message=f"Response for {code!r} does not hold a non-empty string.",
                question_code=code, public_uuid=str(response.public_id),
            )
            return None
        return ResolvedInput(
            kwarg_name=kwarg, value=text, expected_type=expected_type,
            source_kind=source_kind, source_public_uuid=str(response.public_id),
            source_question_code=code,
            provenance=freeze(
                {"response_public_id": str(response.public_id), "question_code": code}
            ),
        )

    _fail(
        failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
        message=f"expected_type {expected_type!r} is not supported for form A.",
        question_code=code,
    )
    return None


def _resolve_formulation_field(
    execution, kwarg, declaration, subject_component, snapshot, failures
):
    """Form B -- M4D3-INP-004.

    ``snapshot`` is needed only because a declared ``required_unit`` may be a
    ``SnapshotUnitRef``: the component quantity is then converted into the IID
    reference unit so both sides of a comparison are like quantities
    (M4D3-UNC-006).

    The formulation version is read fresh from ``execution.formulation_version_id``
    rather than through ``execution.formulation_version``. That relation is a
    lazily-loaded FK which keeps whatever the row looked like when the caller
    first touched it, and the values read here -- ``total_dosage_unit_weight``
    and its unit -- are regulated inputs to ``percentage_w_w`` that a governed
    ``AssessmentSnapshot`` freezes from the *current* row in the same
    transaction. A cached copy could make the two disagree. Same correction, and
    the same shared helper, as Form C.
    """
    obj = declaration["object"]
    field_name = declaration["field"]
    unit_field = declaration.get("unit_field")

    if obj == "formulation_version":
        from formulations.dosing import current_formulation_version

        source_kind = SOURCE_KIND_FORMULATION_VERSION
        formulation_version = current_formulation_version(
            execution.formulation_version_id
        )
        if formulation_version.product.tenant_id != execution.tenant_id:
            _fail(
                failures, kwarg=kwarg, code=F_TENANT_MISMATCH, source_kind=source_kind,
                message=(
                    "This execution's formulation version belongs to another tenant."
                ),
                public_uuid=str(formulation_version.public_id),
            )
            return None
        target_object = formulation_version
        value_fields = _FORMULATION_VERSION_VALUE_FIELDS
        unit_fields = _FORMULATION_VERSION_UNIT_FIELDS
        public_uuid = str(target_object.public_id)
    elif obj == "formulation_component":
        source_kind = SOURCE_KIND_FORMULATION_COMPONENT
        if subject_component is None:
            # Phase B already recorded its own governed failure; this kwarg
            # cannot resolve without a subject component.
            _fail(
                failures, kwarg=kwarg, code=F_COMPONENT_MISSING, source_kind=source_kind,
                message=f"{kwarg!r} needs a subject component, which did not resolve.",
            )
            return None
        target_object = subject_component
        value_fields = _FORMULATION_COMPONENT_VALUE_FIELDS
        unit_fields = _FORMULATION_COMPONENT_UNIT_FIELDS
        public_uuid = str(target_object.public_id)
    else:  # pragma: no cover - registry validates the object name
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN,
            source_kind=SOURCE_KIND_FORMULATION_VERSION,
            message=f"{obj!r} is not a readable formulation object.",
        )
        return None

    accessor = value_fields.get(field_name)
    if accessor is None:
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
            message=f"{field_name!r} is not an approved readable field on {obj!r}.",
            public_uuid=public_uuid,
        )
        return None

    raw_value = accessor(target_object)
    if raw_value is None:
        _fail(
            failures, kwarg=kwarg, code=F_FORMULATION_FIELD_MISSING, source_kind=source_kind,
            message=f"{obj!r}.{field_name} holds no value.",
            public_uuid=public_uuid,
        )
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, Decimal):
        _fail(
            failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=f"{obj!r}.{field_name} is not a Decimal.",
            public_uuid=public_uuid,
        )
        return None

    source_unit = None
    if unit_field is not None:
        unit_accessor = unit_fields.get(unit_field)
        if unit_accessor is None:
            _fail(
                failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
                message=f"{unit_field!r} is not an approved unit field on {obj!r}.",
                public_uuid=public_uuid,
            )
            return None
        source_unit = unit_accessor(target_object)

    target, ok = _target_unit(
        declaration, snapshot, kwarg=kwarg, source_kind=source_kind, failures=failures
    )
    if not ok:
        return None
    converted, conversion = _convert(
        raw_value, source_unit, target, kwarg=kwarg, source_kind=source_kind,
        failures=failures, public_uuid=public_uuid,
    )
    if converted is None:
        return None

    return ResolvedInput(
        kwarg_name=kwarg,
        value=converted,
        expected_type=declaration["expected_type"],
        source_kind=source_kind,
        source_public_uuid=public_uuid,
        source_unit=str(source_unit) if source_unit else None,
        target_unit=target,
        conversion_factor=conversion.get("conversion_factor"),
        conversion_rule_version=conversion.get("conversion_rule_version"),
        provenance=freeze(
            {"object": obj, "field": field_name, "source_public_id": public_uuid, **conversion}
        ),
    )


def _resolve_maximum_daily_units(execution, kwarg, declaration, failures):
    """Form C -- M4D3-INP-005 / M4D3-MDU-001..024.

    Delegates to ``formulations.dosing``, the one helper every governed consumer
    of the maximum-daily-units rule uses -- this resolver, the checklist
    execution service's snapshot creation, and the persisted snapshot API. The
    candidate collection and the freshness policy live there rather than here,
    so a change to either cannot reach one consumer and not another.

    It resolves from ``execution.formulation_version_id`` rather than
    ``execution.formulation_version``: the latter is a lazily-loaded FK that
    keeps whatever the row looked like when the caller first touched it, and a
    stale copy would let this resolver disagree with the snapshot frozen in the
    same transaction.

    Read-only, as every resolver form is.
    """
    from formulations.dosing import resolve_current_maximum_daily_units

    source_kind = SOURCE_KIND_MAXIMUM_DAILY_UNITS

    selection = resolve_current_maximum_daily_units(
        formulation_version_id=execution.formulation_version_id
    )
    # The selector already carries the governed public identity; taking it from
    # the provenance avoids a second read purely to name the source.
    formulation_public_id = selection.provenance["formulation_version_public_id"]

    if not selection.resolved or selection.value is None:
        _fail(
            failures, kwarg=kwarg, code=F_FORMULATION_FIELD_MISSING, source_kind=source_kind,
            message=(
                "No valid maximum daily units candidate exists for this formulation "
                "version."
            ),
            public_uuid=formulation_public_id,
        )
        return None

    return ResolvedInput(
        kwarg_name=kwarg,
        value=selection.value,
        expected_type=declaration["expected_type"],
        source_kind=source_kind,
        source_public_uuid=formulation_public_id,
        detail_code=selection.detail_code,
        provenance=freeze(selection.provenance),
    )


def _resolve_assessment_snapshot(
    execution, kwarg, declaration, snapshot, component_public_id, expected_release,
    failures,
):
    """Form D -- M4D3-INP-006.

    The snapshot is supplied by the caller as an exact object.  This service
    performs **no** lookup: there is no query by tenant, component or release
    that could return "a" snapshot, so no client-supplied identifier can ever
    steer the selection.  The component it is checked against is the one Phase B
    finalized, so this check cannot be skipped by kwarg ordering.
    """
    source_kind = SOURCE_KIND_ASSESSMENT_SNAPSHOT
    field_name = declaration["field"]

    if snapshot is None:
        _fail(
            failures, kwarg=kwarg, code=F_SNAPSHOT_MISSING, source_kind=source_kind,
            message=f"{kwarg!r} requires an assessment snapshot, which was not supplied.",
        )
        return None

    public_uuid = str(snapshot.public_id)
    if snapshot.tenant_id != execution.tenant_id:
        _fail(
            failures, kwarg=kwarg, code=F_SNAPSHOT_TENANT_MISMATCH, source_kind=source_kind,
            message="The supplied assessment snapshot belongs to another tenant.",
            public_uuid=public_uuid,
        )
        return None
    if component_public_id is not None and str(
        snapshot.formulation_component_public_id
    ) != str(component_public_id):
        _fail(
            failures, kwarg=kwarg, code=F_SNAPSHOT_COMPONENT_MISMATCH, source_kind=source_kind,
            message="The supplied snapshot describes a different subject component.",
            public_uuid=public_uuid,
        )
        return None
    if expected_release is not None and str(snapshot.iid_release_public_id) != str(
        expected_release
    ):
        _fail(
            failures, kwarg=kwarg, code=F_SNAPSHOT_RELEASE_MISMATCH, source_kind=source_kind,
            message="The supplied snapshot was frozen from a different FDA release.",
            public_uuid=public_uuid,
        )
        return None

    accessor = _SNAPSHOT_VALUE_FIELDS.get(field_name)
    if accessor is None:
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
            message=f"{field_name!r} is not an approved readable snapshot value field.",
            public_uuid=public_uuid,
        )
        return None

    value = accessor(snapshot)
    if value is None:
        _fail(
            failures, kwarg=kwarg, code=F_ASSESSMENT_FIELD_MISSING, source_kind=source_kind,
            message=f"Snapshot field {field_name!r} holds no value.",
            public_uuid=public_uuid,
        )
        return None

    source_unit = None
    unit_field = declaration.get("unit_field")
    if unit_field is not None:
        unit_accessor = _SNAPSHOT_UNIT_FIELDS.get(unit_field)
        if unit_accessor is None:
            _fail(
                failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
                message=f"{unit_field!r} is not an approved snapshot unit field.",
                public_uuid=public_uuid,
            )
            return None
        source_unit = unit_accessor(snapshot)

    target, ok = _target_unit(
        declaration, snapshot, kwarg=kwarg, source_kind=source_kind, failures=failures
    )
    if not ok:
        return None
    converted, conversion = _convert(
        value, source_unit, target, kwarg=kwarg, source_kind=source_kind,
        failures=failures, public_uuid=public_uuid,
    )
    if converted is None:
        return None

    return ResolvedInput(
        kwarg_name=kwarg,
        value=converted,
        expected_type=declaration["expected_type"],
        source_kind=source_kind,
        source_public_uuid=public_uuid,
        source_unit=str(source_unit) if source_unit else None,
        target_unit=target,
        conversion_factor=conversion.get("conversion_factor"),
        conversion_rule_version=conversion.get("conversion_rule_version"),
        provenance=freeze(
            {"snapshot_public_id": public_uuid, "field": field_name, **conversion}
        ),
    )


def _build_outcome_input(
    upstream, declaration, snapshot, component_public_id, failures
):
    """Form E value assembly, using the outcome Phase B already validated."""
    source_kind = SOURCE_KIND_CALCULATION_OUTCOME
    outcome = upstream.outcome
    outcome_uuid = str(outcome.public_id)
    kwarg = upstream.kwarg
    code = upstream.code

    source_unit = outcome.unit or declaration.get("unit_source")
    target, ok = _target_unit(
        declaration, snapshot, kwarg=kwarg, source_kind=source_kind, failures=failures
    )
    if not ok:
        return None
    converted, conversion = _convert(
        outcome.value, source_unit, target, kwarg=kwarg, source_kind=source_kind,
        failures=failures, question_code=code, public_uuid=outcome_uuid,
    )
    if converted is None:
        return None

    return ResolvedInput(
        kwarg_name=kwarg,
        value=converted,
        expected_type=declaration["expected_type"],
        source_kind=source_kind,
        source_public_uuid=outcome_uuid,
        source_question_code=code,
        source_unit=str(source_unit) if source_unit else None,
        target_unit=target,
        conversion_factor=conversion.get("conversion_factor"),
        conversion_rule_version=conversion.get("conversion_rule_version"),
        provenance=freeze(
            {
                "upstream_response_public_id": str(upstream.response.public_id),
                "upstream_outcome_public_id": outcome_uuid,
                "question_code": code,
                SUBJECT_COMPONENT_PROVENANCE_KEY: component_public_id,
                **conversion,
            }
        ),
    )


def _resolve_constant(kwarg, declaration, failures):
    """Form F -- M4D3-INP-008.

    The value comes only from the immutable registry declaration.  No client
    input, no runtime expression, no callable and no dynamic import can reach
    this path.
    """
    source_kind = SOURCE_KIND_CONSTANT
    value = declaration["value"]
    declared_type = declaration["type"]

    if callable(value) or isinstance(value, list | dict | set):
        _fail(
            failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
            message=f"Constant {kwarg!r} is not an immutable scalar.",
        )
        return None

    if declared_type == "decimal":
        if isinstance(value, Decimal):
            resolved_value: Any = value
        else:
            resolved_value = _decimal_from_string(value)
        if resolved_value is None:
            _fail(
                failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
                message=f"Constant {kwarg!r} is not a valid decimal.",
            )
            return None
    elif declared_type == "string":
        if not isinstance(value, str):
            _fail(
                failures, kwarg=kwarg, code=F_VALUE_INVALID, source_kind=source_kind,
                message=f"Constant {kwarg!r} is not a string.",
            )
            return None
        resolved_value = value
    else:  # pragma: no cover - registry validates the type
        _fail(
            failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind=source_kind,
            message=f"Constant type {declared_type!r} is not approved.",
        )
        return None

    return ResolvedInput(
        kwarg_name=kwarg,
        value=resolved_value,
        expected_type=declared_type,
        source_kind=source_kind,
        provenance=freeze(
            {
                "constant_type": declared_type,
                "binding_version": declaration["binding_version"],
            }
        ),
    )


# ---------------------------------------------------------------------------
# The governed service
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubjectComponentResolution:
    """Phase B's answer, for a caller that must act before Phase C can run."""

    required: bool
    resolved: bool
    component: Any = None
    public_id: str | None = None
    sources: tuple[str, ...] = ()
    failures: tuple[InputFailure, ...] = ()

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(failure.failure_code for failure in self.failures)


def _validate_target_contract(execution, target_question, entry) -> None:
    """Phase A's structural guards -- server-side faults, never client input."""
    if target_question.section.checklist_version_id != execution.checklist_version_id:
        raise CalculationInputContractError(
            "target_question does not belong to the execution's checklist version"
        )
    if target_question.data_source_classification != DataSourceClassification.SYSTEM_CALCULATED:
        raise CalculationInputContractError(
            "target_question is not a system_calculated question"
        )
    if target_question.answer_type != entry.allowed_answer_type:
        raise CalculationInputContractError(
            "target_question answer type does not match the registry entry"
        )


def _locate_upstreams(execution, entry, failures) -> dict[str, _Upstream]:
    upstreams: dict[str, _Upstream] = {}
    for kwarg, declaration in sorted(entry.input_resolvers.items()):
        if declaration.get("source") != SOURCE_CALCULATION_OUTCOME:
            continue
        located = _locate_upstream(execution, kwarg, declaration, failures)
        if located is not None:
            upstreams[kwarg] = located
    return upstreams


def resolve_subject_component(
    *, execution, target_question, registry_identifier: str
) -> SubjectComponentResolution:
    """M4D3-SNO-009 step one -- the subject component, before a snapshot exists.

    The governed calculation-execution service has to create the
    ``AssessmentSnapshot`` *before* Form D can read it, and a snapshot is scoped
    to one subject component (M4D3-SNO-010), so the component must be known
    first. This exposes exactly Phase A and Phase B of
    :func:`resolve_calculation_inputs` and duplicates neither: both call the same
    ``_resolve_subject_component()``, so the selector rule, the inheritance rule
    and the disagreement rule can never diverge between the two entry points.

    Read-only. Opens no transaction, takes no lock and writes nothing.
    """
    entry = get_entry(registry_identifier)
    if entry is None:
        return SubjectComponentResolution(
            required=False,
            resolved=False,
            failures=(
                InputFailure(
                    kwarg_name="",
                    failure_code=F_RESOLVER_UNKNOWN,
                    source_kind="registry",
                    message=f"{registry_identifier!r} is not an approved registry entry.",
                ),
            ),
        )

    _validate_target_contract(execution, target_question, entry)

    failures: list[InputFailure] = []
    upstreams = _locate_upstreams(execution, entry, failures)
    component = _resolve_subject_component(execution, entry, upstreams, failures)

    if component.state == STATE_NOT_REQUIRED:
        return SubjectComponentResolution(
            required=False, resolved=True, failures=tuple(failures)
        )
    if component.state == STATE_FAILED:
        return SubjectComponentResolution(
            required=True, resolved=False, failures=tuple(failures)
        )
    return SubjectComponentResolution(
        required=True,
        resolved=True,
        component=component.component,
        public_id=component.public_id,
        sources=component.sources,
        failures=tuple(failures),
    )


def resolve_calculation_inputs(
    *,
    execution,
    target_question,
    registry_identifier: str,
    actor=None,
    locked_context=None,
) -> ResolvedCalculationInputs:
    """Resolve every declared input for one calculated question.

    ``locked_context`` carries server-owned objects the caller has already
    selected and locked -- the exact ``AssessmentSnapshot`` and, optionally, the
    IID release the caller chose.  It is never populated from client input: this
    service performs no snapshot lookup at all, so an arbitrary snapshot UUID
    cannot be steered into a calculation.

    ``actor`` is accepted for provenance symmetry with the governed services
    and is deliberately unused: resolution reads no actor-dependent state and
    must produce the same result for every caller.

    Returns a :class:`ResolvedCalculationInputs`.  When any input fails, the
    kwargs mapping is empty -- there is no partial success.
    """
    del actor  # resolution is actor-independent by construction

    # -- Phase A: caller contract and registry entry -------------------------
    entry = get_entry(registry_identifier)
    failures: list[InputFailure] = []

    if entry is None:
        return ResolvedCalculationInputs(
            registry_identifier=registry_identifier,
            calculation_name="",
            formula_version="",
            binding_version="",
            kwargs=MappingProxyType({}),
            inputs=(),
            failures=(
                InputFailure(
                    kwarg_name="",
                    failure_code=F_RESOLVER_UNKNOWN,
                    source_kind="registry",
                    message=(
                        f"{registry_identifier!r} is not an approved registry entry."
                    ),
                ),
            ),
        )

    _validate_target_contract(execution, target_question, entry)

    snapshot = getattr(locked_context, "assessment_snapshot", None)
    expected_release = getattr(locked_context, "expected_iid_release_public_id", None)

    # -- Phase B: the subject component, established once ---------------------
    upstreams = _locate_upstreams(execution, entry, failures)
    component = _resolve_subject_component(execution, entry, upstreams, failures)
    component_public_id = component.public_id
    component_object = component.component

    # -- Phase C: every remaining input, against the finalized component ------
    inputs: list[ResolvedInput] = []
    upstream_outcome_ids: list[str] = []

    for kwarg, declaration in sorted(entry.input_resolvers.items()):
        source = declaration.get("source")

        if source == SOURCE_QUESTION_RESPONSE:
            resolved = _resolve_question_response(
                execution, kwarg, declaration, snapshot, failures
            )
        elif source == SOURCE_FORMULATION_FIELD:
            resolved = _resolve_formulation_field(
                execution, kwarg, declaration, component_object, snapshot, failures
            )
        elif source == SOURCE_MAXIMUM_DAILY_UNITS:
            resolved = _resolve_maximum_daily_units(execution, kwarg, declaration, failures)
        elif source == SOURCE_ASSESSMENT_SNAPSHOT:
            resolved = _resolve_assessment_snapshot(
                execution, kwarg, declaration, snapshot, component_public_id,
                expected_release, failures,
            )
        elif source == SOURCE_CALCULATION_OUTCOME:
            upstream = upstreams.get(kwarg)
            resolved = None
            if upstream is not None:
                resolved = _build_outcome_input(
                    upstream, declaration, snapshot, component_public_id, failures
                )
                if resolved is not None:
                    upstream_outcome_ids.append(str(resolved.source_public_uuid))
        elif source == SOURCE_CONSTANT:
            resolved = _resolve_constant(kwarg, declaration, failures)
        else:  # pragma: no cover - registry validates the source
            _fail(
                failures, kwarg=kwarg, code=F_RESOLVER_UNKNOWN, source_kind="unknown",
                message=f"Resolver source {source!r} is not approved.",
            )
            resolved = None

        if resolved is not None:
            inputs.append(resolved)

    # -- Phase D: the immutable result ---------------------------------------
    unique: dict[tuple[str, str, str, str, str], InputFailure] = {}
    for failure in failures:
        unique.setdefault(failure.semantic_key, failure)
    ordered_failures = tuple(unique[key] for key in sorted(unique))
    ordered_inputs = tuple(sorted(inputs, key=lambda item: item.kwarg_name))

    return ResolvedCalculationInputs(
        registry_identifier=registry_identifier,
        calculation_name=entry.calculation_name,
        formula_version=entry.formula_version,
        binding_version=entry.binding_version,
        kwargs=freeze(
            {} if ordered_failures else {item.kwarg_name: item.value for item in ordered_inputs}
        ),
        inputs=ordered_inputs,
        failures=ordered_failures,
        subject_component_public_id=component_public_id,
        subject_component_sources=component.sources,
        assessment_snapshot_public_id=(
            str(snapshot.public_id) if snapshot is not None else None
        ),
        upstream_outcome_public_ids=tuple(sorted(upstream_outcome_ids)),
    )


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """Server-owned objects a caller has already selected and locked.

    Deliberately minimal: an exact ``AssessmentSnapshot`` instance, never an
    identifier this service would look up, plus the IID release the caller
    selected so the snapshot can be proven to come from it.
    """

    assessment_snapshot: Any = None
    expected_iid_release_public_id: Any = None


__all__ = [
    "CONVERSION_RULE_VERSION",
    "REVIEW_REQUIRED_MARKER",
    "SUBJECT_COMPONENT_PROVENANCE_KEY",
    "CalculationInputContractError",
    "InputFailure",
    "ResolutionContext",
    "ResolvedCalculationInputs",
    "ResolvedInput",
    "freeze",
    "resolve_calculation_inputs",
]
