"""Milestone 4D-3 -- governed cascade recalculation orchestration.

When a governed response changes, the calculated outcomes that consume it must be
recalculated. This module discovers which ones, in what order, and drives each
through the already-reviewed ``execute_calculation_response()``. It computes
nothing itself.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md

  - M4D3-RCL-001  cascade is keyed on ``recalculation_triggers``, never on
                  ``calculation_dependencies``: a Form A user input creates no
                  graph edge, yet changing it must still recalculate the
                  outcomes that consume it
  - M4D3-RCL-006  the required sequence, implemented literally below
  - M4D3-RCL-007  a question in no trigger set recalculates nothing, changes no
                  version and emits no audit
  - M4D3-RCL-002  stable topological order of M4D3-DAG-006
  - M4D3-RCL-003  outcome rows updated in place with ``full_clean()``
  - M4D3-RCL-004  no audit and no version change when ``status``, ``value``,
                  ``reason_code`` and ``generated_at`` are all unchanged
  - M4D3-RCL-005  terminal and submitted executions are never recalculated
  - M4D3-DEP-007  two questions bound to the same function are distinct nodes
  - M4D3-DAG-005  Kahn's algorithm, iterative, no unbounded recursion
  - M4D3-DAG-006  equal precedence ordered by ascending ``ChecklistQuestion.code``
  - M4D3-DAG-009  a graph never spans checklist versions
  - M4D3-DAG-010  a visited set; each node runs at most once per event
  - M4D3-TXN-001  the Part 17 lock order, ascending primary key
  - M4D3-RBD-008  a dependency-graph failure or a stale ``expected_version``
                  rolls the whole operation back

**This module is not a rules engine.** Dependencies come only from the immutable
approved registry -- ``recalculation_triggers`` for the directly affected set and
``calculation_dependencies`` for the downstream expansion. Nothing is inferred
from text, labels or formulas, nothing is evaluated, and no caller may supply a
dependency list.

**It is not a second calculation writer either.** Every target is executed
through ``execute_calculation_response()``, which remains the sole owner of
function invocation, engine translation, outcome persistence, provenance,
snapshot creation and calculation audit.

Atomicity is all-or-nothing. M4D3-RCL-006 requires the recalculation to happen
"inside the same transaction" and M4D3-RBD-008 lists dependency-graph failure and
stale ``expected_version`` among the structural failures that "roll back the
entire" operation, so one blocking failure discards every outcome, snapshot and
audit of the cascade. That policy is read from those clauses, not chosen.

There is no cascade-level audit event. M4D3-RCL-006 requires the per-calculation
success audit after commit and no approved clause or event constant defines a
cascade summary, so inventing one would be adding governed vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_execution import execute_calculation_response
from .calculation_graph import (
    CalculationNode,
    GraphConfigurationError,
    affected_nodes_for_trigger,
    build_graph,
)
from .enums import DataSourceClassification, ExecutionStatus

#: M4D3-RCL-005 -- only these statuses may be recalculated automatically.
#: Every terminal status and ``SUBMITTED_FOR_REVIEW`` is excluded, and the set is
#: an allow-list so a status added later is excluded until it is considered.
RECALCULABLE_EXECUTION_STATUSES: frozenset[str] = frozenset(
    {ExecutionStatus.DRAFT, ExecutionStatus.RETURNED}
)


class CascadeError(Exception):
    """Base class for governed cascade rejections, raised before any commit."""


class CascadeExecutionNotRecalculable(CascadeError):
    """M4D3-RCL-005 -- terminal and submitted executions are never recalculated."""


class CascadeResponseNotInExecution(CascadeError):
    """The changed response does not belong to the supplied execution or tenant."""


class CascadeGraphInvalid(CascadeError):
    """M4D3-RBD-008 -- a dependency-graph failure rolls the whole cascade back.

    Carries the graph layer's governed ``error_code`` (``DEPENDENCY_CYCLE``,
    ``DEPENDENCY_DEPTH_EXCEEDED``, ``CASCADE_NODE_LIMIT_EXCEEDED``,
    ``UNKNOWN_DEPENDENCY_CODE``, ``DUPLICATE_NODE``,
    ``UNKNOWN_REGISTRY_IDENTIFIER``) and the question codes involved -- never a
    database id and never a raw exception.
    """

    def __init__(self, error_code: str, question_codes: tuple[str, ...] = ()) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.question_codes = question_codes


@dataclass(frozen=True, slots=True)
class CascadeTarget:
    """One recalculated response, as it stood after the cascade."""

    question_code: str
    registry_identifier: str
    response_public_id: str
    outcome_public_id: str
    status: str
    reason_code: str
    executed: bool
    #: M4D3-RCL-004 -- the recalculation left every governed field unchanged, so
    #: the writer withheld the audit event.
    audit_suppressed: bool = False


@dataclass(frozen=True, slots=True)
class CascadeRecalculationResult:
    """Immutable summary of one cascade event.

    Public UUIDs and governed codes only; no model instance, no QuerySet and no
    database id. ``targets`` is a tuple in the executed order, which is the
    stable topological order of M4D3-DAG-006.
    """

    execution_public_id: str
    origin_response_public_id: str
    origin_question_code: str
    triggered: bool
    targets: tuple[CascadeTarget, ...] = ()

    @property
    def recalculated_count(self) -> int:
        return len(self.targets)

    @property
    def recalculated_response_public_ids(self) -> tuple[str, ...]:
        return tuple(target.response_public_id for target in self.targets)

    @property
    def question_codes(self) -> tuple[str, ...]:
        return tuple(target.question_code for target in self.targets)

    @property
    def audited_count(self) -> int:
        """Targets that emitted a governed audit event (M4D3-RCL-004)."""
        return sum(1 for target in self.targets if not target.audit_suppressed)


# ---------------------------------------------------------------------------
# Dependency discovery (read-only)
# ---------------------------------------------------------------------------


def _calculated_responses(execution) -> list:
    """Every SYSTEM_CALCULATED response of this exact execution.

    Scoped to the execution, and therefore to one ``ChecklistVersion`` and one
    tenant: a question from another version can never enter the graph
    (M4D3-DAG-009). Ordered by question code so node construction is
    deterministic before the graph applies its own ordering.
    """
    from .models import ChecklistResponse

    return list(
        ChecklistResponse.objects.filter(
            execution=execution,
            question__data_source_classification=(
                DataSourceClassification.SYSTEM_CALCULATED
            ),
        )
        .select_related("question")
        .order_by("question__code")
    )


def build_execution_graph(execution):
    """The validated dependency graph for one execution's calculated responses.

    Read-only: opens no transaction, takes no lock and writes nothing. Node
    identity is the governed **response** public UUID, so two questions bound to
    the same calculation function stay distinct nodes (M4D3-DEP-007).

    Every ``SYSTEM_CALCULATED`` response of the execution becomes a node, with no
    filtering. A response whose binding does not resolve to an approved registry
    entry therefore raises ``UNKNOWN_REGISTRY_IDENTIFIER`` rather than being
    quietly dropped: skipping it would recalculate part of the graph and silently
    leave the rest stale, which is exactly what M4D3-RBD-008 forbids.

    Raises :class:`CascadeGraphInvalid` for any governed graph fault -- a cycle
    included -- **before** anything is locked or written, so a bad graph can
    never leave a partial cascade behind.
    """
    nodes = tuple(
        CalculationNode(
            node_id=str(response.public_id),
            question_code=response.question.code,
            registry_identifier=(
                response.question.calculation_binding_identifier or ""
            ).strip(),
        )
        for response in _calculated_responses(execution)
    )
    try:
        return build_graph(nodes)
    except GraphConfigurationError as exc:
        raise CascadeGraphInvalid(
            exc.error_code,
            tuple(sorted(node.question_code for node in nodes)),
        ) from None


# ---------------------------------------------------------------------------
# The governed cascade service
# ---------------------------------------------------------------------------


def recalculate_dependents(
    *,
    tenant,
    execution,
    changed_response,
    actor,
    expected_version: int,
) -> CascadeRecalculationResult:
    """Recalculate every outcome affected by one governed response change.

    Implements M4D3-RCL-006 in order: resolve the changed response's question
    identity; locate every ``SYSTEM_CALCULATED`` response listing that identity
    in ``recalculation_triggers``; expand through ``calculation_dependencies``;
    process the union in stable topological order; lock every affected response
    and ``CalculationOutcome`` in the Part 17 order; and recalculate inside one
    transaction.

    ``expected_version`` is the caller's expected version of the **changed**
    response and is checked against the locked row. Each recalculated target
    supplies its own current version, read under the lock this service already
    holds, because a calculated response is never mutated by recalculation
    (M4D3-MDL-006) and so has no independent version to conflict on.

    Returns an immutable :class:`CascadeRecalculationResult`. A response that
    triggers nothing returns ``triggered=False`` with no targets, no writes and
    no audit (M4D3-RCL-007).
    """
    from django.db import transaction as db_transaction

    from .models import CalculationOutcome, ChecklistExecution, ChecklistResponse

    # -- Phase A: caller contract, no locks, no writes ---------------------
    if changed_response.execution_id != execution.pk:
        raise CascadeResponseNotInExecution()
    if execution.tenant_id != getattr(tenant, "id", None):
        raise CascadeResponseNotInExecution()

    with db_transaction.atomic():
        # 1. the execution -- the serialization barrier every governed
        #    operation on this execution shares (M4D3-TXN-006).
        locked_execution = ChecklistExecution.objects.select_for_update().get(
            pk=execution.pk
        )
        if locked_execution.status not in RECALCULABLE_EXECUTION_STATUSES:
            # M4D3-RCL-005 -- checked under the lock so the state examined is
            # the committed state.
            raise CascadeExecutionNotRecalculable()

        # 2. the changed response, and its optimistic-concurrency check.
        locked_origin = (
            ChecklistResponse.objects.select_for_update()
            .select_related("question")
            .get(pk=changed_response.pk)
        )
        if locked_origin.version != expected_version:
            from .calculation_execution import StaleResponseVersion

            raise StaleResponseVersion()

        origin_code = locked_origin.question.code

        # 3. the graph, and the affected set. Both read-only, and a graph
        #    fault raises here -- before any further lock or write.
        graph = build_execution_graph(execution)
        affected_node_ids = affected_nodes_for_trigger(graph, origin_code)

        result_base = {
            "execution_public_id": str(execution.public_id),
            "origin_response_public_id": str(locked_origin.public_id),
            "origin_question_code": origin_code,
        }
        if not affected_node_ids:
            # M4D3-RCL-007 -- nothing to do, and nothing written.
            return CascadeRecalculationResult(**result_base, triggered=False)

        # 4. every affected response and outcome, in the Part 17 order, taken
        #    as one set before any recalculation so no later step can invert it.
        #
        #    Neither lock uses ``select_related``: on PostgreSQL a joined
        #    ``SELECT ... FOR UPDATE`` would also lock ``checklistquestion``,
        #    adding a table the Part 17 order does not contain.
        pk_by_node = {
            str(row.public_id): row.pk for row in _calculated_responses(execution)
        }
        affected_pks = sorted(pk_by_node[node_id] for node_id in affected_node_ids)
        list(
            ChecklistResponse.objects.filter(pk__in=affected_pks)
            .select_for_update()
            .order_by("pk")
        )
        list(
            CalculationOutcome.objects.filter(response_id__in=affected_pks)
            .select_for_update()
            .order_by("pk")
        )

        # Re-read the locked rows -- a plain SELECT inside this transaction, so
        # the ``version`` handed to the writer below is the value under our own
        # lock and not whatever the pre-lock scan happened to see.
        locked_by_node = {
            str(row.public_id): row
            for row in ChecklistResponse.objects.filter(
                pk__in=affected_pks
            ).select_related("question")
        }

        # 5. recalculate in stable topological order (M4D3-RCL-002), each node
        #    at most once (M4D3-DAG-010 -- the graph order is already unique, so
        #    this is the guard the clause requires, not a filter that does work).
        targets: list[CascadeTarget] = []
        for node_id in dict.fromkeys(affected_node_ids):
            response = locked_by_node[node_id]
            outcome = execute_calculation_response(
                tenant=tenant,
                execution=execution,
                response=response,
                actor=actor,
                expected_version=response.version,
                _suppress_unchanged_audit=True,
            )
            node = graph.nodes[node_id]
            targets.append(
                CascadeTarget(
                    question_code=node.question_code,
                    registry_identifier=node.registry_identifier,
                    response_public_id=node_id,
                    outcome_public_id=outcome.outcome_public_id,
                    status=outcome.status,
                    reason_code=outcome.reason_code,
                    executed=outcome.executed,
                    audit_suppressed=outcome.audit_suppressed,
                )
            )

    return CascadeRecalculationResult(
        **result_base, triggered=True, targets=tuple(targets)
    )


__all__ = [
    "RECALCULABLE_EXECUTION_STATUSES",
    "CascadeError",
    "CascadeExecutionNotRecalculable",
    "CascadeGraphInvalid",
    "CascadeRecalculationResult",
    "CascadeResponseNotInExecution",
    "CascadeTarget",
    "build_execution_graph",
    "recalculate_dependents",
]
