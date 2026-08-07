"""Milestone 4D-3 -- governed cascade recalculation.

This module is the ORM half of the calculation dependency graph. The pure half
lives in ``calculation_graph`` and never touches the database; this one reads an
execution's persisted responses and hands them to it.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md

  - M4D3-DEP-007  two questions bound to the same function are distinct nodes
  - M4D3-DAG-005  Kahn's algorithm, iterative, no unbounded recursion
  - M4D3-DAG-006  equal precedence ordered by ascending ``ChecklistQuestion.code``
  - M4D3-DAG-009  a graph never spans checklist versions
  - M4D3-RBD-008  a dependency-graph failure rolls the whole operation back

**This is not a rules engine.** Dependencies come only from the immutable
approved registry -- ``calculation_dependencies`` for graph edges and
``recalculation_triggers`` for the directly affected set. Nothing is inferred
from question text, labels or formulas, nothing is evaluated, and no caller may
supply a dependency list.
"""

from __future__ import annotations

from .calculation_graph import (
    CalculationNode,
    GraphConfigurationError,
    build_graph,
)
from .enums import DataSourceClassification


class CascadeError(Exception):
    """Base class for governed cascade rejections, raised before any commit."""


class CascadeGraphInvalid(CascadeError):
    """M4D3-RBD-008 -- a dependency-graph failure rolls the whole operation back.

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
    included -- so a bad graph is rejected before a caller can act on it.
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


__all__ = [
    "CascadeError",
    "CascadeGraphInvalid",
    "build_execution_graph",
]
