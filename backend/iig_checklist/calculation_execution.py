"""Milestone 4D-3 ORM Phase 3 -- governed calculation execution.

``execute_calculation_response()`` is the one authoritative path from a
calculated ``ChecklistResponse`` to a persisted ``CalculationOutcome``. It
resolves inputs through the already-reviewed resolver, invokes exactly one
approved registry function, translates the engine result through the approved
deterministic mappings, and updates the single placeholder row created at
execution creation.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-MDL-006      SYSTEM_CALCULATED responses keep raw_value null; results
                      live exclusively in CalculationOutcome
  - M4D3-MDL-010      only the placeholder row is updated; never a second row
  - M4D3-TRL-001..006 engine-to-stored translation
  - M4D3-IFV-003/008  deterministic input-failure translation
  - M4D3-PRV-002/005..009  provenance contract
  - M4D3-SVC-006      system_derived_value / override_reason are not written

Deliberate scope, each grounded in an approved clause rather than convenience:

* **No response mutation.** M4D3-MDL-006 states a SYSTEM_CALCULATED response
  keeps ``raw_value = null`` at all times and results live exclusively in the
  outcome, and M4D3-SVC-006 forbids writing ``system_derived_value``. There is
  therefore no projection to maintain and no second source of truth.
* **No history row.** M4D3-HST-003 requires a history row when a governed
  persisted-state transition *changes an existing ChecklistResponse*. This
  service changes no response, so no transition occurs and no row is due.
* **No snapshot creation.** Snapshot rows are supplied by the caller as exact
  objects. See the module note below.
* **Single response only.** Cascade recalculation orchestration across a
  dependency graph is deliberately out of scope for this run.

Snapshot creation is *not* implemented here. M4D3-SNO-001 requires the governed
``iid_assessment`` service to create or reuse the snapshot, and no such callable
service exists -- ``AssessmentSnapshot`` rows are created only inside
``iid_assessment.views.SnapshotView.post``, coupled to a DRF request, serializer
and response. Rather than duplicate that logic or invent a lookup, this service
accepts the exact snapshot object through ``snapshot_context``, exactly as the
reviewed resolver does. Snapshot creation is reported as an open blocker.

Lock order, acquired before any validation that can mutate and before any write:

1. the ``ChecklistExecution``;
2. the target ``ChecklistResponse``;
3. every involved upstream/selector ``ChecklistResponse``, ordered by public_id;
4. every involved ``CalculationOutcome``, ordered by public_id;
5. the ``AssessmentSnapshot`` the caller supplied, if any.
"""

from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from .calculation_inputs import ResolutionContext, resolve_calculation_inputs
from .calculation_registry import (
    SOURCE_CALCULATION_OUTCOME,
    SOURCE_QUESTION_RESPONSE,
    get_entry,
)
from .calculation_translation import (
    REGISTRY_BINDING_VERSION_PROVENANCE_KEY,
    SUBJECT_COMPONENT_PROVENANCE_KEY,
    translate_engine_status,
    translate_input_failure,
)
from .enums import CalculationStatus, DataSourceClassification


class CalculationExecutionError(Exception):
    """Base class for governed pre-calculation service rejections.

    These never reach a ``CalculationOutcome``: they are caller-contract or
    configuration faults raised before any write, leaving the transaction to
    roll back untouched.
    """


class TargetNotCalculated(CalculationExecutionError):
    """The response's question is not SYSTEM_CALCULATED."""


class ResponseNotInExecution(CalculationExecutionError):
    """The response does not belong to the supplied execution."""


class BindingNotApproved(CalculationExecutionError):
    """The question's calculation binding is not an approved registry entry."""


class PlaceholderMissing(CalculationExecutionError):
    """No CalculationOutcome placeholder exists for the response."""


class PlaceholderAmbiguous(CalculationExecutionError):
    """More than one CalculationOutcome exists for the response."""


class StaleResponseVersion(CalculationExecutionError):
    """The caller's expected_version no longer matches the locked row."""


class CalculationEngineFailure(CalculationExecutionError):
    """The approved calculation function raised instead of returning a result.

    The engine returns a governed ``CalculationResult`` for every scientific
    condition, so an exception is an implementation fault. It aborts the
    transaction; the raw exception is never serialized into a stored outcome.
    """


@dataclass(frozen=True, slots=True)
class CalculationExecutionResult:
    """Immutable summary of one governed execution."""

    executed: bool
    outcome_public_id: str
    status: str
    reason_code: str
    value: Decimal | None
    unit: str
    failure_codes: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.status == CalculationStatus.COMPLETE


# ---------------------------------------------------------------------------
# JSON-safe persistence helpers
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    """Render a resolved value as JSON-storable evidence without losing it.

    ``Decimal`` becomes its exact string form -- never a float, which would
    silently change a regulated number. Mappings and sequences are converted
    structurally rather than stringified whole.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid_module.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, MappingProxyType | dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | bool | type(None)):
        return value
    return str(value)


def _input_descriptor(resolved) -> dict:
    """One per-input source descriptor (M4D3-PRV-002).

    Public identifiers, governed codes and unit evidence only -- never a
    database primary key, model repr or regulated answer body beyond the exact
    governed input value.
    """
    descriptor = {
        "source_kind": resolved.source_kind,
        "expected_type": resolved.expected_type,
        "value": _json_safe(resolved.value),
    }
    optional = {
        "source_public_id": resolved.source_public_uuid,
        "source_question_code": resolved.source_question_code,
        "source_unit": resolved.source_unit,
        "target_unit": resolved.target_unit,
        "conversion_factor": resolved.conversion_factor,
        "conversion_rule_version": resolved.conversion_rule_version,
        "detail_code": resolved.detail_code,
    }
    descriptor.update({key: item for key, item in optional.items() if item is not None})
    if resolved.provenance:
        descriptor["resolver_provenance"] = _json_safe(resolved.provenance)
    return descriptor


def _build_provenance(entry, resolved_inputs, snapshot) -> dict:
    """The complete governed provenance written alongside a result."""
    provenance: dict[str, Any] = {
        REGISTRY_BINDING_VERSION_PROVENANCE_KEY: entry.binding_version,
        "calculation_name": entry.calculation_name,
        "formula_version": entry.formula_version,
    }

    # M4D3-PRV-005/009 -- write the subject component whenever resolution
    # established one, whether it came from this entry's own selector or was
    # inherited from an upstream outcome. Restricting this to entries that
    # declare a selector would drop the component at the first inherited link
    # and break component provenance through deeper dependency chains.
    if resolved_inputs.subject_component_public_id is not None:
        provenance[SUBJECT_COMPONENT_PROVENANCE_KEY] = (
            resolved_inputs.subject_component_public_id
        )
    if resolved_inputs.subject_component_sources:
        provenance["subject_component_sources"] = list(
            resolved_inputs.subject_component_sources
        )
    if snapshot is not None:
        provenance["assessment_snapshot_public_id"] = str(snapshot.public_id)
    if resolved_inputs.upstream_outcome_public_ids:
        provenance["upstream_outcome_public_ids"] = list(
            resolved_inputs.upstream_outcome_public_ids
        )

    for resolved in resolved_inputs.inputs:
        provenance[resolved.kwarg_name] = _input_descriptor(resolved)
    return provenance


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def _declared_question_codes(entry) -> set[str]:
    """Every question code this entry reads, so its rows can be locked."""
    codes: set[str] = set()
    for declaration in entry.input_resolvers.values():
        source = declaration.get("source")
        if source in (SOURCE_QUESTION_RESPONSE, SOURCE_CALCULATION_OUTCOME):
            codes.add(declaration["question_code"])
        selector = declaration.get("component_selector")
        if selector is not None and "question_code" in selector:
            codes.add(selector["question_code"])
    return codes


def _lock_related_rows(execution, entry) -> None:
    """Lock every involved response and outcome in stable public_id order.

    Deterministic ordering is what keeps two concurrent executions from
    deadlocking against each other.
    """
    from .models import CalculationOutcome, ChecklistResponse

    codes = _declared_question_codes(entry)
    if not codes:
        return

    response_ids = list(
        ChecklistResponse.objects.filter(
            execution=execution, question__code__in=sorted(codes)
        )
        .order_by("public_id")
        .values_list("pk", flat=True)
    )
    if response_ids:
        list(
            ChecklistResponse.objects.filter(pk__in=response_ids)
            .select_for_update()
            .order_by("public_id")
        )
        list(
            CalculationOutcome.objects.filter(response_id__in=response_ids)
            .select_for_update()
            .order_by("public_id")
        )


# ---------------------------------------------------------------------------
# The governed service
# ---------------------------------------------------------------------------


def execute_calculation_response(
    *,
    tenant,
    execution,
    response,
    actor,
    expected_version,
    snapshot_context: ResolutionContext | None = None,
) -> CalculationExecutionResult:
    """Resolve, calculate and persist one calculated response's outcome.

    The caller owns nothing: this service opens the transaction, takes every
    lock in the documented order, validates ``expected_version`` while locked,
    and either persists a governed outcome or leaves the database untouched.

    ``snapshot_context`` carries the exact ``AssessmentSnapshot`` the caller
    selected. No snapshot is looked up or created here.
    """
    from django.db import transaction as db_transaction

    from .audit import IigChecklistEvent, emit
    from .models import CalculationOutcome, ChecklistExecution, ChecklistResponse

    # -- Phase A: caller contract, no writes, no locks --------------------
    if response.execution_id != execution.pk:
        raise ResponseNotInExecution()
    if execution.tenant_id != getattr(tenant, "id", None):
        raise ResponseNotInExecution()

    question = response.question
    if question.data_source_classification != DataSourceClassification.SYSTEM_CALCULATED:
        raise TargetNotCalculated()

    identifier = (question.calculation_binding_identifier or "").strip()
    entry = get_entry(identifier)
    if entry is None:
        raise BindingNotApproved(question.code)

    snapshot = getattr(snapshot_context, "assessment_snapshot", None)

    # -- Phase B: one transaction, locks in the documented order ----------
    with db_transaction.atomic():
        list(
            ChecklistExecution.objects.filter(pk=execution.pk).select_for_update()
        )
        locked_response = (
            ChecklistResponse.objects.select_for_update()
            .select_related("question")
            .get(pk=response.pk)
        )
        _lock_related_rows(execution, entry)
        if snapshot is not None:
            from iid_assessment.models import AssessmentSnapshot

            list(
                AssessmentSnapshot.objects.filter(pk=snapshot.pk).select_for_update()
            )

        # Optimistic concurrency, checked while locked and before any write.
        if expected_version is not None and locked_response.version != expected_version:
            raise StaleResponseVersion()

        outcomes = list(
            CalculationOutcome.objects.select_for_update()
            .filter(response=locked_response)
            .order_by("public_id")
        )
        if not outcomes:
            raise PlaceholderMissing(question.code)
        if len(outcomes) > 1:
            raise PlaceholderAmbiguous(question.code)
        outcome = outcomes[0]

        resolved_inputs = resolve_calculation_inputs(
            execution=execution,
            target_question=question,
            registry_identifier=identifier,
            actor=actor,
            locked_context=snapshot_context,
        )

        if not resolved_inputs.resolved:
            result = _persist_input_failure(outcome, entry, resolved_inputs)
        else:
            engine_result = _invoke(entry, resolved_inputs)
            result = _persist_engine_result(
                outcome, entry, resolved_inputs, engine_result, snapshot
            )

        # -- Phase C: audit, only after the transaction commits ----------
        payload = {
            "execution_public_id": str(execution.public_id),
            "response_public_id": str(locked_response.public_id),
            "outcome_public_id": result.outcome_public_id,
            "question_code": question.code,
            "registry_identifier": identifier,
            "calculation_name": entry.calculation_name,
            "status": result.status,
            "reason_code": result.reason_code,
        }
        db_transaction.on_commit(
            lambda: emit(
                event_type=IigChecklistEvent.RESPONSE_CALCULATED,
                resource_id=str(locked_response.public_id),
                actor_id=getattr(actor, "id", None),
                actor_email=getattr(actor, "email", ""),
                tenant_id=getattr(tenant, "id", None),
                payload=payload,
            )
        )
    return result


def _invoke(entry, resolved_inputs):
    """Invoke exactly one approved registry function with the resolved kwargs.

    The callable comes from the immutable server registry; no name is taken
    from a request, nothing is imported dynamically and the kwargs are exactly
    what the resolver produced.
    """
    try:
        return entry.function(**dict(resolved_inputs.kwargs))
    except Exception as exc:
        # The engine returns a CalculationResult for every scientific
        # condition, so an exception here is an implementation fault. It must
        # abort the transaction rather than be translated into a stored result.
        raise CalculationEngineFailure(entry.calculation_name) from exc


def _persist_input_failure(outcome, entry, resolved_inputs):
    """Persist the governed outcome for a resolver failure (M4D3-IFV-003).

    Failures are already deterministically ordered, so the first one decides
    the stored status -- there is no scoring or implementer choice. Tenant and
    configuration faults keep their own categories and never become scientific
    results.
    """
    first = resolved_inputs.failures[0]
    mapping = translate_input_failure(first.failure_code)

    outcome.calculation_name = entry.calculation_name
    outcome.formula_version = entry.formula_version
    outcome.status = mapping.status
    outcome.value = None
    outcome.unit = ""
    outcome.rounding_rule = entry.rounding_rule
    outcome.reason_code = mapping.reason_code
    outcome.generated_at = None
    outcome.inputs = {}
    outcome.input_provenance = {
        REGISTRY_BINDING_VERSION_PROVENANCE_KEY: entry.binding_version,
        "calculation_name": entry.calculation_name,
        "formula_version": entry.formula_version,
        "input_failures": [
            {
                "kwarg_name": failure.kwarg_name,
                "failure_code": failure.failure_code,
                "source_kind": failure.source_kind,
                "source_question_code": failure.source_question_code,
                "source_public_id": failure.source_public_uuid,
            }
            for failure in resolved_inputs.failures
        ],
    }
    outcome.source_assessment_snapshot_public_id = None
    outcome.full_clean()
    outcome.save()

    return CalculationExecutionResult(
        executed=False,
        outcome_public_id=str(outcome.public_id),
        status=outcome.status,
        reason_code=outcome.reason_code,
        value=None,
        unit="",
        failure_codes=resolved_inputs.failure_codes,
    )


def _persist_engine_result(outcome, entry, resolved_inputs, engine_result, snapshot):
    """Translate and persist a governed engine result (M4D3-TRL-001..006)."""
    translated = translate_engine_status(engine_result)

    outcome.calculation_name = entry.calculation_name
    outcome.formula_version = entry.formula_version
    outcome.status = translated.status
    outcome.value = translated.value
    outcome.rounding_rule = entry.rounding_rule
    outcome.reason_code = translated.reason_code
    outcome.generated_at = translated.generated_at
    outcome.unit = (
        (engine_result.unit or entry.output_unit or "")
        if translated.status == CalculationStatus.COMPLETE
        else ""
    )
    outcome.inputs = {
        resolved.kwarg_name: _json_safe(resolved.value)
        for resolved in resolved_inputs.inputs
    }
    outcome.input_provenance = _build_provenance(entry, resolved_inputs, snapshot)
    outcome.source_assessment_snapshot_public_id = (
        snapshot.public_id if snapshot is not None else None
    )
    outcome.full_clean()
    outcome.save()

    return CalculationExecutionResult(
        executed=True,
        outcome_public_id=str(outcome.public_id),
        status=outcome.status,
        reason_code=outcome.reason_code,
        value=outcome.value,
        unit=outcome.unit,
    )


__all__ = [
    "BindingNotApproved",
    "CalculationEngineFailure",
    "CalculationExecutionError",
    "CalculationExecutionResult",
    "PlaceholderAmbiguous",
    "PlaceholderMissing",
    "ResponseNotInExecution",
    "StaleResponseVersion",
    "TargetNotCalculated",
    "execute_calculation_response",
]
