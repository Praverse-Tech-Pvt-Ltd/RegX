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
* **Single response only.** Cascade recalculation orchestration across a
  dependency graph is deliberately out of scope for this run.

Snapshots are **created, not supplied**. M4D3-SNO-001 requires the governed
``iid_assessment`` service to create the snapshot, and
``create_assessment_snapshot()`` now provides exactly that, so this service
resolves the subject component, resolves the active FDA release server-side and
calls it inside this transaction (M4D3-SNO-009). The governed Part 14.1
maximum-daily-units selection is injected through
``formulations.dosing.governed_maximum_daily_units_value()`` -- the same helper
the persisted snapshot API uses, so neither caller can drift from the other
(M4D3-SRC-004, M4D3-MDU-006/010).

Lock order (M4D3-TXN-001, M4D3-OUT-004), acquired before any write:

1. the ``ChecklistExecution``;
2. the target ``ChecklistResponse``;
3. every other involved ``ChecklistResponse``, ordered by **ascending primary
   key**;
4. every involved ``CalculationOutcome`` -- upstream rows *and* the target
   placeholder -- in **one** query ordered by **ascending primary key**, then
   classified in memory;
5. the ``AssessmentSnapshot``, when one was supplied through the private hook --
   a snapshot this transaction creates needs no lock, because it does not exist
   yet.

**Ordering is by database primary key, never by ``public_id``.** M4D3-TXN-001
requires ascending primary-key order "without exception", M4D3-OUT-004 repeats it
for ``CalculationOutcome`` and M4D3-RBD-004 pins the future component-rebinding
transaction to the same order. ``public_id`` is a random UUID, so ordering by it
is uncorrelated with primary-key order and would invert against any specification-
conformant service. Public UUIDs remain the right identity for external
representation and for deterministic error/provenance ordering; they are not a
row-lock acquisition order.

Two properties make this order deadlock-free:

* every ``CalculationOutcome`` this service touches is acquired in one
  pk-ordered statement, so upstream rows and the target placeholder can never be
  taken in two conflicting stages;
* the target response is locked before the remaining responses, which is not
  itself pk-ordered -- but step 1 already holds the ``ChecklistExecution`` row,
  and every response and outcome involved belongs to that one execution. No two
  governed operations on the same execution can therefore be inside steps 2-5 at
  the same time, and operations on different executions share no rows.
"""

from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from common.immutable import immutable_value_object
from formulations.dosing import governed_maximum_daily_units_value

from .calculation_inputs import (
    ResolutionContext,
    resolve_calculation_inputs,
    resolve_subject_component,
)
from .calculation_registry import (
    SOURCE_ASSESSMENT_SNAPSHOT,
    SOURCE_CALCULATION_OUTCOME,
    SOURCE_QUESTION_RESPONSE,
    get_entry,
)
from .calculation_translation import (
    REGISTRY_BINDING_VERSION_PROVENANCE_KEY,
    SUBJECT_COMPONENT_PROVENANCE_KEY,
    format_decimal_plain,
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


class InvalidExpectedVersion(CalculationExecutionError):
    """``expected_version`` is absent or not a usable response version.

    Optimistic concurrency is mandatory (M4D3-TXN-003): there is deliberately no
    value -- ``None`` least of all -- that disables the check. ``bool`` is
    rejected even though it is an ``int`` subclass, because ``True`` would
    silently mean version 1.
    """


class CalculationEngineFailure(CalculationExecutionError):
    """The approved calculation function raised instead of returning a result.

    The engine returns a governed ``CalculationResult`` for every scientific
    condition, so an exception is an implementation fault. It aborts the
    transaction; the raw exception is never serialized into a stored outcome.
    """


@immutable_value_object
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
    #: M4D3-RCL-004 -- set only when a recalculation left ``status``, ``value``,
    #: ``reason_code`` and ``generated_at`` all unchanged and the governed audit
    #: event was therefore withheld. Always ``False`` for a direct execution.
    audit_suppressed: bool = False

    @property
    def complete(self) -> bool:
        return self.status == CalculationStatus.COMPLETE


# ---------------------------------------------------------------------------
# JSON-safe persistence helpers
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    """Render a resolved value as JSON-storable evidence without losing it.

    ``Decimal`` becomes its exact **plain-notation** string -- never a float,
    which would silently change a regulated number, and never ``1E-7``, which a
    reader of a regulated record should not have to decode. Mappings and
    sequences are converted structurally rather than stringified whole.
    """
    if isinstance(value, Decimal):
        return format_decimal_plain(value)
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
        provenance[SUBJECT_COMPONENT_PROVENANCE_KEY] = resolved_inputs.subject_component_public_id
    if resolved_inputs.subject_component_sources:
        provenance["subject_component_sources"] = list(resolved_inputs.subject_component_sources)
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


def _related_response_ids(execution, entry, target_pk) -> list[int]:
    """Primary keys of every other response this entry reads, ascending.

    The target is excluded because step 2 already holds it; re-acquiring it here
    would be a no-op but would blur the documented order.
    """
    from .models import ChecklistResponse

    codes = _declared_question_codes(entry)
    if not codes:
        return []
    return list(
        ChecklistResponse.objects.filter(execution=execution, question__code__in=sorted(codes))
        .exclude(pk=target_pk)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _lock_responses(response_ids) -> None:
    """M4D3-TXN-001 -- lock the given responses in ascending primary-key order."""
    from .models import ChecklistResponse

    if not response_ids:
        return
    list(ChecklistResponse.objects.filter(pk__in=response_ids).select_for_update().order_by("pk"))


def _lock_outcomes(response_ids) -> list:
    """M4D3-OUT-004 -- lock every involved outcome as one pk-ordered set.

    Upstream outcomes and the target placeholder are acquired by a single
    statement, so there is no window in which the two could be taken in
    conflicting orders. The caller classifies the returned rows in memory.
    """
    from .models import CalculationOutcome

    if not response_ids:
        return []
    return list(
        CalculationOutcome.objects.filter(response_id__in=response_ids)
        .select_for_update()
        .order_by("pk")
    )


def _entry_needs_snapshot(entry) -> bool:
    """True when any declared input is read from an ``AssessmentSnapshot``."""
    return any(
        declaration.get("source") == SOURCE_ASSESSMENT_SNAPSHOT
        for declaration in entry.input_resolvers.values()
    )


def _worst_case_daily_units(formulation_version):
    """M4D3-SRC-004 -- the Part 14.1 conservative worst-case selection.

    Delegates to the one shared helper every governed snapshot caller uses
    (``formulations.dosing``), so this service and the persisted snapshot API
    endpoint cannot reach different answers for the same formulation. Both
    governed sources are considered and the higher wins (M4D3-MDU-010).

    Returns the selected ``Decimal``, or ``None`` when the selection fails closed
    (M4D3-MDU-013), which leaves the kwarg unresolved so the engine canonicalises
    to ``DATA_REQUIRED`` (M4D3-MDU-014).
    """
    return governed_maximum_daily_units_value(formulation_version=formulation_version)


def _create_governed_snapshot(*, tenant, execution, question, identifier, actor):
    """M4D3-SNO-009 -- component, then release, then exactly one new snapshot.

    Returns ``(resolution_context, snapshot_result)``. Both are ``None`` when the
    subject component cannot be resolved: that is already a governed resolver
    failure, and the resolver reports it -- with every other failure alongside it
    -- a moment later. Creating a snapshot for an unknown component would be
    creating a regulated record that describes nothing.

    The snapshot is created inside the caller's transaction, so any later
    failure discards it (M4D3-SNO-003/012).
    """
    from iid_assessment.services import create_assessment_snapshot

    component = resolve_subject_component(
        execution=execution,
        target_question=question,
        registry_identifier=identifier,
    )
    if not component.resolved or component.component is None:
        return None, None

    # Read the formulation version fresh inside the transaction rather than
    # trusting whatever the caller's ``execution`` happens to have cached on its
    # FK descriptor: the worst-case selection and every frozen value derive from
    # it, so a snapshot must never be built from a stale in-memory copy.
    from formulations.models import FormulationVersion

    formulation_version = FormulationVersion.objects.select_related("product").get(
        pk=execution.formulation_version_id
    )
    result = create_assessment_snapshot(
        tenant=tenant,
        formulation_version=formulation_version,
        formulation_component=component.component,
        actor=actor,
        # M4D3-SRC-001/003 -- resolved server-side, never named by a caller.
        selected_release=None,
        # M4D3-SRC-004 -- the governed Part 14.1 worst case, injected. The
        # snapshot service applies no source rule of its own.
        maximum_dosage_units_per_day=_worst_case_daily_units(formulation_version),
    )
    return ResolutionContext(assessment_snapshot=result.snapshot), result


def _persist_source_unavailable(outcome, entry):
    """M4D3-SRC-002 -- no active FDA release is a governed error, not a crash."""
    outcome.calculation_name = entry.calculation_name
    outcome.formula_version = entry.formula_version
    outcome.status = CalculationStatus.ERROR
    outcome.value = None
    outcome.unit = ""
    outcome.rounding_rule = entry.rounding_rule
    outcome.reason_code = "FDA_VALUE_UNAVAILABLE"
    outcome.generated_at = None
    outcome.inputs = {}
    outcome.input_provenance = {
        REGISTRY_BINDING_VERSION_PROVENANCE_KEY: entry.binding_version,
        "calculation_name": entry.calculation_name,
        "formula_version": entry.formula_version,
        "source_failure": "ACTIVE_IID_RELEASE_UNAVAILABLE",
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
    )


def _outcome_signature(outcome):
    """M4D3-RCL-004 -- the four governed fields the clause names, and only those.

    ``updated_at`` and ``input_provenance`` move on every write and are
    deliberately excluded: the clause defines "unchanged" as ``status``,
    ``value``, ``reason_code`` and ``generated_at``, so widening the comparison
    would suppress audit for a recalculation that did change a governed value,
    and narrowing it would emit an event the clause forbids.
    """
    return (outcome.status, outcome.value, outcome.reason_code, outcome.generated_at)


def validate_expected_version(expected_version) -> int:
    """M4D3-TXN-003 -- optimistic concurrency is mandatory, not opt-in.

    ``ChecklistResponse.version`` is a ``PositiveIntegerField(default=1)`` that
    only ever increments, so 1 is the lowest version any real row can hold.

    This is the single governed structural gate for ``expected_version``. Every
    governed writer that accepts one -- ``execute_calculation_response()`` and
    the 4D-3 cascade -- routes through this function rather than comparing the
    supplied value to a row directly: ``True == 1`` and ``1.0 == 1`` under Python
    equality, so a direct comparison would silently accept a malformed value at
    version 1, and would misreport every other malformed value as a stale
    version. Structural rejection is ``InvalidExpectedVersion``; only a valid
    integer that differs from the locked row is ``StaleResponseVersion``.

    It is internal to ``iig_checklist`` and is not exposed through the API.
    """
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise InvalidExpectedVersion()
    if expected_version < 1:
        raise InvalidExpectedVersion()
    return expected_version


# ---------------------------------------------------------------------------
# The governed service
# ---------------------------------------------------------------------------


def execute_calculation_response(
    *,
    tenant,
    execution,
    response,
    actor,
    expected_version: int,
    _internal_snapshot_context: ResolutionContext | None = None,
    _suppress_unchanged_audit: bool = False,
) -> CalculationExecutionResult:
    """Resolve, calculate and persist one calculated response's outcome.

    The caller owns nothing: this service opens the transaction, takes every
    lock in the documented order, validates ``expected_version`` against the
    locked row, and either persists a governed outcome or leaves the database
    untouched.

    ``expected_version`` is **mandatory** and must be the ``int`` version the
    caller believes the target response holds (M4D3-TXN-003). There is no value
    that skips the concurrency check: ``None``, ``bool`` and anything below 1 are
    rejected in Phase A, before a lock is taken or a calculation is invoked.

    **Snapshots are created, not supplied.** When the bound entry reads an
    ``AssessmentSnapshot``, this service resolves the subject component, resolves
    the active FDA release server-side (M4D3-SRC-001/003) and calls the governed
    ``create_assessment_snapshot()`` inside this transaction, then hands that
    exact object straight to the resolver (M4D3-SNO-007). Every governed
    execution and recalculation therefore gets its own new immutable snapshot
    (M4D3-SNO-006), and any later failure rolls it back with everything else.

    ``_internal_snapshot_context`` is a **private** hook for tests and for
    server-side callers that must pin an exact pre-resolved snapshot -- a
    reproducibility check against a superseded release, for instance. It is
    underscore-prefixed because no client-reachable path may steer a snapshot
    into a calculation (M4D3-SNO-011); no view, serializer or task calls this
    service at all, and a test asserts that.

    ``_suppress_unchanged_audit`` is the M4D3-RCL-004 hook, set only by the
    governed cascade service. When a recalculation leaves ``status``, ``value``,
    ``reason_code`` and ``generated_at`` all unchanged, no audit event is
    emitted. Only this service can make that judgement -- it alone sees the
    outcome row before and after the write, under the lock, and it alone owns
    the ``on_commit`` dispatch -- so the decision lives here rather than in the
    cascade. It defaults to ``False``, so a direct execution always audits and
    the reviewed single-response behaviour is untouched. The clause's companion
    requirement, "no version change", needs no code: recalculation never writes
    ``ChecklistResponse.version`` on a calculated response (M4D3-MDL-006).
    """
    from django.db import transaction as db_transaction

    from iid_assessment.services import ActiveReleaseUnavailable

    from .models import ChecklistExecution, ChecklistResponse

    # -- Phase A: caller contract, no writes, no locks --------------------
    expected_version = validate_expected_version(expected_version)

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

    supplied_snapshot = getattr(_internal_snapshot_context, "assessment_snapshot", None)

    # -- Phase B: one transaction, locks in the documented order ----------
    with db_transaction.atomic():
        # 1. the execution -- also the barrier that serializes every governed
        #    operation on this execution (M4D3-TXN-006).
        list(ChecklistExecution.objects.filter(pk=execution.pk).select_for_update())
        # 2. the target response.
        locked_response = (
            ChecklistResponse.objects.select_for_update()
            .select_related("question")
            .get(pk=response.pk)
        )

        # Optimistic concurrency, checked against the locked row and before any
        # further lock, any resolution and any write.
        if locked_response.version != expected_version:
            raise StaleResponseVersion()

        # 3. every other involved response, ascending primary key.
        related_ids = _related_response_ids(execution, entry, locked_response.pk)
        _lock_responses(related_ids)

        # 4. every involved outcome -- upstream and target together -- as one
        #    ascending primary-key set, then classified in memory.
        locked_outcomes = _lock_outcomes([*related_ids, locked_response.pk])
        outcomes = [row for row in locked_outcomes if row.response_id == locked_response.pk]
        if not outcomes:
            raise PlaceholderMissing(question.code)
        if len(outcomes) > 1:
            raise PlaceholderAmbiguous(question.code)
        outcome = outcomes[0]

        # M4D3-RCL-004 -- the governed comparison basis, read from the locked
        # row before anything writes to it.
        outcome_before = _outcome_signature(outcome)

        def audit_unless_unchanged(result, snapshot_public_id):
            """M4D3-RCL-004 -- withhold the event when nothing governed moved."""
            if _suppress_unchanged_audit and _outcome_signature(outcome) == (outcome_before):
                return replace(result, audit_suppressed=True)
            _schedule_audit(
                tenant=tenant,
                execution=execution,
                response=locked_response,
                question=question,
                identifier=identifier,
                entry=entry,
                actor=actor,
                result=result,
                snapshot_public_id=snapshot_public_id,
            )
            return result

        # 5. the snapshot, last.
        #
        #    A snapshot this transaction is about to create needs no lock: it
        #    does not exist yet, so no other transaction can hold or observe it.
        #    A pre-existing one supplied through the private hook is locked in
        #    the documented position.
        resolution_context = _internal_snapshot_context
        if supplied_snapshot is not None:
            from iid_assessment.models import AssessmentSnapshot

            list(AssessmentSnapshot.objects.filter(pk=supplied_snapshot.pk).select_for_update())
        elif _entry_needs_snapshot(entry):
            try:
                resolution_context, _ = _create_governed_snapshot(
                    tenant=tenant,
                    execution=execution,
                    question=question,
                    identifier=identifier,
                    actor=actor,
                )
            except ActiveReleaseUnavailable:
                # M4D3-SRC-002 -- a governed error outcome, not an exception.
                result = _persist_source_unavailable(outcome, entry)
                return audit_unless_unchanged(result, None)

        snapshot = getattr(resolution_context, "assessment_snapshot", None)

        resolved_inputs = resolve_calculation_inputs(
            execution=execution,
            target_question=question,
            registry_identifier=identifier,
            actor=actor,
            locked_context=resolution_context,
        )

        if not resolved_inputs.resolved:
            result = _persist_input_failure(outcome, entry, resolved_inputs)
        else:
            engine_result = _invoke(entry, resolved_inputs)
            result = _persist_engine_result(
                outcome, entry, resolved_inputs, engine_result, snapshot
            )

        # -- Phase C: audit, only after the transaction commits ----------
        result = audit_unless_unchanged(
            result,
            str(snapshot.public_id) if snapshot is not None else None,
        )
    return result


def _schedule_audit(
    *,
    tenant,
    execution,
    response,
    question,
    identifier,
    entry,
    actor,
    result,
    snapshot_public_id,
):
    """One governed audit event, dispatched only after the commit succeeds."""
    from django.db import transaction as db_transaction

    from .audit import IigChecklistEvent, emit

    payload = {
        "execution_public_id": str(execution.public_id),
        "response_public_id": str(response.public_id),
        "outcome_public_id": result.outcome_public_id,
        "question_code": question.code,
        "registry_identifier": identifier,
        "calculation_name": entry.calculation_name,
        "status": result.status,
        "reason_code": result.reason_code,
    }
    if snapshot_public_id is not None:
        payload["assessment_snapshot_public_id"] = snapshot_public_id

    db_transaction.on_commit(
        lambda: emit(
            event_type=IigChecklistEvent.RESPONSE_CALCULATED,
            resource_id=str(response.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload=payload,
        )
    )


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


def _without_trailing_zeros(value):
    """The same exact value without trailing zeros (never scientific for whole numbers).

    QA-02: 25 mg converts to 0.025000000 g; times 4.0000 units/day the exact
    0.1 g/day was carried as 0.1000000000000 (13 places), which the outcome
    field (10 places) refused with a 500. Only the exponent changes, never the
    value; recorded inputs keep their exact original form.
    """
    if not isinstance(value, Decimal) or not value.is_finite():
        return value
    if value == value.to_integral_value():
        return value.quantize(Decimal(1))
    return value.normalize()


def _persist_engine_result(outcome, entry, resolved_inputs, engine_result, snapshot):
    """Translate and persist a governed engine result (M4D3-TRL-001..006)."""
    translated = translate_engine_status(engine_result)

    outcome.calculation_name = entry.calculation_name
    outcome.formula_version = entry.formula_version
    outcome.status = translated.status
    outcome.value = _without_trailing_zeros(translated.value)
    outcome.rounding_rule = entry.rounding_rule
    outcome.reason_code = translated.reason_code
    outcome.generated_at = translated.generated_at
    outcome.unit = (
        (engine_result.unit or entry.output_unit or "")
        if translated.status == CalculationStatus.COMPLETE
        else ""
    )
    outcome.inputs = {
        resolved.kwarg_name: _json_safe(resolved.value) for resolved in resolved_inputs.inputs
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
    "InvalidExpectedVersion",
    "PlaceholderAmbiguous",
    "PlaceholderMissing",
    "ResponseNotInExecution",
    "StaleResponseVersion",
    "TargetNotCalculated",
    "execute_calculation_response",
    "validate_expected_version",
]
