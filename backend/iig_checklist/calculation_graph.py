"""Milestone 4D-3 -- pure calculation dependency graph.

Database-free by construction.  Callers build immutable node definitions from
whatever source they have (an ORM service later, a test fixture today) and this
module validates and orders them.  Nothing here queries the database.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-DEP-001..012  graph derived from resolver declarations
  - M4D3-DAG-003..010  depth, cascade, cycle, ordering and tie-break rules
  - M4D3-TRG-001/002   graph edges vs external recalculation triggers
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .calculation_registry import (
    CALCULATION_MAX_CASCADE_NODES,
    CALCULATION_MAX_DEPENDENCY_DEPTH,
    get_entry,
)


class GraphConfigurationError(RuntimeError):
    """Raised when a supplied node set forms an invalid calculation graph."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code


ERROR_DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
ERROR_UNKNOWN_DEPENDENCY_CODE = "UNKNOWN_DEPENDENCY_CODE"
ERROR_DEPENDENCY_DEPTH_EXCEEDED = "DEPENDENCY_DEPTH_EXCEEDED"
ERROR_CASCADE_NODE_LIMIT_EXCEEDED = "CASCADE_NODE_LIMIT_EXCEEDED"
ERROR_DUPLICATE_NODE = "DUPLICATE_NODE"
ERROR_UNKNOWN_REGISTRY_IDENTIFIER = "UNKNOWN_REGISTRY_IDENTIFIER"


@dataclass(frozen=True, slots=True, order=True)
class CalculationNode:
    """One SYSTEM_CALCULATED response in a checklist version.

    ``node_id`` is the governed response/question public identity -- **not** the
    calculation function name.  Two questions bound to the same function are two
    distinct nodes and never collapse (M4D3-DEP-007).
    """

    node_id: str
    question_code: str
    registry_identifier: str


@dataclass(frozen=True, slots=True)
class CalculationGraph:
    """Validated immutable graph over calculated response nodes."""

    nodes: MappingProxyType[str, CalculationNode]
    edges: MappingProxyType[str, tuple[str, ...]]
    order: tuple[str, ...]
    depth: int

    def dependants_of(self, node_id: str) -> tuple[str, ...]:
        """Node ids that consume ``node_id`` directly."""
        return tuple(
            sorted(n for n, ups in self.edges.items() if node_id in ups)
        )

    def downstream_closure(self, node_id: str) -> tuple[str, ...]:
        """All transitively affected nodes, in stable topological order."""
        reached: set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for dependant in self.dependants_of(current):
                if dependant not in reached:
                    reached.add(dependant)
                    frontier.append(dependant)
        return tuple(n for n in self.order if n in reached)


def _index_by_question_code(
    nodes: tuple[CalculationNode, ...],
) -> dict[str, CalculationNode]:
    by_code: dict[str, CalculationNode] = {}
    for node in nodes:
        if node.question_code in by_code:
            raise GraphConfigurationError(
                ERROR_DUPLICATE_NODE,
                f"question_code {node.question_code!r} appears more than once",
            )
        by_code[node.question_code] = node
    return by_code


def build_graph(nodes: tuple[CalculationNode, ...]) -> CalculationGraph:
    """Construct and fully validate a calculation graph.

    Edges come **only** from each entry's ``calculation_dependencies`` (form E
    prior-outcome resolvers).  Recalculation triggers are external nodes and
    never enter the graph (M4D3-DEP-002/012).
    """
    seen_ids: set[str] = set()
    for node in nodes:
        if node.node_id in seen_ids:
            raise GraphConfigurationError(
                ERROR_DUPLICATE_NODE, f"duplicate node id {node.node_id!r}"
            )
        seen_ids.add(node.node_id)
        if get_entry(node.registry_identifier) is None:
            raise GraphConfigurationError(
                ERROR_UNKNOWN_REGISTRY_IDENTIFIER,
                f"node {node.node_id!r} references unknown registry identifier "
                f"{node.registry_identifier!r}",
            )

    by_code = _index_by_question_code(nodes)

    edges: dict[str, tuple[str, ...]] = {}
    for node in nodes:
        entry = get_entry(node.registry_identifier)
        assert entry is not None  # guarded above
        upstream: list[str] = []
        for dep_code in entry.calculation_dependencies:
            dep_node = by_code.get(dep_code)
            if dep_node is None:
                raise GraphConfigurationError(
                    ERROR_UNKNOWN_DEPENDENCY_CODE,
                    f"node {node.node_id!r} depends on {dep_code!r}, which is not a "
                    "SYSTEM_CALCULATED node in this version",
                )
            upstream.append(dep_node.node_id)
        edges[node.node_id] = tuple(sorted(upstream))

    node_map = {node.node_id: node for node in nodes}
    order = _topological_order(node_map, edges)
    depth = _max_depth(order, edges)

    if depth > CALCULATION_MAX_DEPENDENCY_DEPTH:
        raise GraphConfigurationError(
            ERROR_DEPENDENCY_DEPTH_EXCEEDED,
            f"graph depth {depth} exceeds CALCULATION_MAX_DEPENDENCY_DEPTH "
            f"{CALCULATION_MAX_DEPENDENCY_DEPTH}",
        )

    graph = CalculationGraph(
        nodes=MappingProxyType(node_map),
        edges=MappingProxyType(edges),
        order=order,
        depth=depth,
    )

    for node_id in node_map:
        reachable = len(graph.downstream_closure(node_id)) + 1
        if reachable > CALCULATION_MAX_CASCADE_NODES:
            raise GraphConfigurationError(
                ERROR_CASCADE_NODE_LIMIT_EXCEEDED,
                f"{reachable} nodes reachable from {node_id!r} exceeds "
                f"CALCULATION_MAX_CASCADE_NODES {CALCULATION_MAX_CASCADE_NODES}",
            )

    return graph


def _topological_order(
    node_map: dict[str, CalculationNode], edges: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    """Kahn's algorithm with a stable alphabetical tie-break (M4D3-DAG-005/006).

    Iterative -- no recursion, so no unbounded stack growth.
    """
    indegree = {node_id: len(upstream) for node_id, upstream in edges.items()}
    ready = sorted(n for n, deg in indegree.items() if deg == 0)
    order: list[str] = []

    while ready:
        # Tie-break on the governed node identity, never the function name.
        current = ready.pop(0)
        order.append(current)
        for node_id, upstream in edges.items():
            if current in upstream:
                indegree[node_id] -= 1
                if indegree[node_id] == 0:
                    ready.append(node_id)
                    ready.sort()

    if len(order) != len(node_map):
        remaining = sorted(set(node_map) - set(order))
        raise GraphConfigurationError(
            ERROR_DEPENDENCY_CYCLE,
            f"cycle detected among nodes {remaining}",
        )
    return tuple(order)


def _max_depth(order: tuple[str, ...], edges: dict[str, tuple[str, ...]]) -> int:
    """Longest path length in nodes (a single independent node has depth 1)."""
    if not order:
        return 0
    depth: dict[str, int] = {}
    for node_id in order:
        upstream = edges[node_id]
        depth[node_id] = 1 + max((depth[u] for u in upstream), default=0)
    return max(depth.values())


def affected_nodes_for_trigger(
    graph: CalculationGraph, changed_question_code: str
) -> tuple[str, ...]:
    """M4D3-RCL-006 -- directly affected nodes, expanded downstream.

    A response whose question code appears in no ``recalculation_triggers`` set
    yields an empty tuple, so nothing is recalculated (M4D3-RCL-007).
    """
    directly_affected = []
    for node_id, node in graph.nodes.items():
        entry = get_entry(node.registry_identifier)
        if entry is not None and changed_question_code in entry.recalculation_triggers:
            directly_affected.append(node_id)

    reached: set[str] = set(directly_affected)
    for node_id in directly_affected:
        reached.update(graph.downstream_closure(node_id))
    return tuple(n for n in graph.order if n in reached)
