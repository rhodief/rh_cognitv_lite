"""
Data models for the orchestrator DAG layer.

Node, NodeGroup, Edge, DAGBuilderConfig, DAG.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field, model_validator

from rh_cognitv_lite.orchestrator.dag_engine import _GraphEngine


class Node(BaseModel):
    """Named, identified placeholder in a DAG. Carries no execution logic.

    Upstream layers (e.g. PlanDAG) resolve what runs for a given node
    based on its id.
    """

    id: str
    name: str
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Node):
            return self.id == other.id
        return NotImplemented


class Edge(BaseModel):
    """A directed connection between two nodes, referenced by their IDs.

    ``label`` is purely informational metadata — it has no effect on
    traversal direction or execution ordering.
    """

    source: str
    target: str
    label: str | None = None


class DAGBuilderConfig(BaseModel):
    """Construction-time validation flags for DAGBuilder."""

    append_only: bool = False
    """If True, remove_node / remove_edge are disabled."""

    validate_acyclic: bool = True
    """If True, checks for cycles on every edge() call."""

    validate_connected: bool = False
    """If True, checks connectedness on every structural change."""

    allow_isolated_nodes: bool = False
    """If True, permits nodes that have no edges at build time."""

    allow_self_loops: bool = False
    """If True, permits edges from a node to itself (a → a)."""

    allow_parallel_edges: bool = False
    """If True, permits more than one edge between the same ordered pair."""


class DAG(BaseModel):
    """Immutable, read-only directed acyclic graph.

    Constructed exclusively by DAGBuilder — do not instantiate directly.
    Fully serialisable to/from JSON via Pydantic for state persistence.

    Traversal methods operate on the outer graph only by default.
    Pass cross_groups=True where supported to recurse into NodeGroup internals.
    """

    # ── Serialisable state ────────────────────────────────────────────────────
    # NodeGroup (subclass) must appear first: Pydantic's smart-union tries the
    # most constrained type first, so NodeGroup (which requires `inner`) wins
    # when the data has that field; plain dicts fall back to Node.
    nodes_data: list[NodeGroup | Node] = Field(default_factory=list)
    edges_data: list[Edge] = Field(default_factory=list)

    # ── Engine cache (not serialised) ─────────────────────────────────────────
    _engine: _GraphEngine | None = None

    @model_validator(mode="after")
    def _build_engine(self) -> DAG:
        self._engine = self._make_engine()
        return self

    def _make_engine(self) -> _GraphEngine:
        node_ids = {n.id for n in self.nodes_data}
        edge_pairs = {(e.source, e.target) for e in self.edges_data}
        return _GraphEngine(node_ids, edge_pairs)

    def _get_engine(self) -> _GraphEngine:
        if self._engine is None:  # defensive: after deserialization
            self._engine = self._make_engine()
        return self._engine

    # ── Internal factory used exclusively by DAGBuilder ───────────────────────
    @classmethod
    def _from_parts(cls, nodes: list[Node], edges: list[Edge]) -> DAG:
        return cls(nodes_data=nodes, edges_data=edges)

    # ── Node lookup helpers ───────────────────────────────────────────────────
    def _node_by_id(self, node_id: str) -> Node:
        for n in self.nodes_data:
            if n.id == node_id:
                return n
        raise KeyError(f"No node with id {node_id!r}")

    def _nodes_by_ids(self, ids: set[str]) -> set[Node]:
        return {self._node_by_id(i) for i in ids}

    # ── Traversal API ─────────────────────────────────────────────────────────

    def entry_nodes(self) -> set[Node]:
        """Return nodes with no predecessors."""
        return self._nodes_by_ids(self._get_engine().entry_nodes())

    def is_entry_node(self, node: Node) -> bool:
        return node.id in self._get_engine().entry_nodes()

    def leaf_nodes(self) -> set[Node]:
        """Return nodes with no successors."""
        return self._nodes_by_ids(self._get_engine().leaf_nodes())

    def is_leaf_node(self, node: Node) -> bool:
        return node.id in self._get_engine().leaf_nodes()

    def next_nodes_from(self, node: Node | None = None) -> set[Node]:
        """Fan-out: successors of node. If node is None, returns entry nodes."""
        if node is None:
            return self.entry_nodes()
        eng = self._get_engine()
        return self._nodes_by_ids(eng._succ.get(node.id, set()))

    def prev_nodes_from(self, node: Node) -> set[Node]:
        """Fan-in: predecessors of node."""
        eng = self._get_engine()
        return self._nodes_by_ids(eng._pred.get(node.id, set()))

    def descendants_of(self, node: Node, *, cross_groups: bool = False) -> set[Node]:
        """All nodes reachable downstream from node.

        When cross_groups=False (default), NodeGroup internals are opaque —
        the group node itself is included in results but its inner nodes are not.
        When cross_groups=True, also expands every NodeGroup encountered,
        including the starting node itself if it is a NodeGroup.
        """
        raw_desc_ids = self._get_engine().descendants_of(node.id)

        if not cross_groups:
            return self._nodes_by_ids(raw_desc_ids)

        # cross_groups=True: for every NodeGroup in the outer descendants (and
        # the starting node itself if it is a NodeGroup), recurse into inner DAGs.
        result: set[Node] = self._nodes_by_ids(raw_desc_ids)

        def _expand(group: NodeGroup) -> None:
            for inner in group.inner.nodes_data:
                result.add(inner)
                if isinstance(inner, NodeGroup):
                    _expand(inner)

        if isinstance(node, NodeGroup):
            _expand(node)

        for outer_node in list(result):
            if isinstance(outer_node, NodeGroup):
                _expand(outer_node)

        return result

    def is_reachable(self, source: Node, target: Node) -> bool:
        return self._get_engine().is_reachable(source.id, target.id)

    def path_between(self, source: Node, target: Node) -> list[Node] | None:
        ids = self._get_engine().path_between(source.id, target.id)
        if ids is None:
            return None
        return [self._node_by_id(i) for i in ids]

    def would_create_cycle(self, source: Node, target: Node) -> bool:
        return self._get_engine().would_create_cycle(source.id, target.id)

    def validate_acyclic(self) -> None:
        """Raise ValueError if the graph contains a cycle."""
        if self._get_engine().has_cycle():
            raise ValueError("DAG contains a cycle.")

    def validate_connectedness(self) -> None:
        """Raise ValueError if the graph is not weakly connected.

        An empty DAG is considered connected (vacuously true).
        """
        nodes = list(self.nodes_data)
        if len(nodes) <= 1:
            return
        eng = self._get_engine()
        # Weak connectivity: reachable from first entry ignoring edge direction.
        # Build undirected adjacency from the engine's directed edges.
        undirected: dict[str, set[str]] = {n.id: set() for n in nodes}
        for src, tgts in eng._succ.items():
            for tgt in tgts:
                undirected[src].add(tgt)
                undirected[tgt].add(src)
        start = nodes[0].id
        visited: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur not in visited:
                visited.add(cur)
                stack.extend(undirected[cur] - visited)
        if visited != {n.id for n in nodes}:
            raise ValueError("DAG is not connected.")

    def copy(self, *, deep: bool = False) -> DAG:
        """Return a copy of this DAG.

        shallow copy (deep=False): node and edge objects are shared.
        deep copy (deep=True): node and edge objects are fully independent.
        """
        if deep:
            return DAG._from_parts(
                nodes=copy.deepcopy(self.nodes_data),
                edges=copy.deepcopy(self.edges_data),
            )
        return DAG._from_parts(
            nodes=list(self.nodes_data),
            edges=list(self.edges_data),
        )

    def visualize(self, output_configs: Any = None) -> None:
        """Render this DAG via DAGVisualizer.

        Parameters
        ----------
        output_configs:
            Passed directly to ``DAGVisualizer.render()``.  May be a format
            string (e.g. ``"terminal"``, ``"json"``) or a dict with a
            ``"format"`` key and optional extra keys.  Defaults to
            ``"terminal"`` when ``None``.
        """
        # Import deferred to avoid circular imports at module load time.
        from rh_cognitv_lite.orchestrator.dag_visualizer import DAGVisualizer
        viz = DAGVisualizer(self)
        if output_configs is None:
            viz.render("terminal")
        elif isinstance(output_configs, str):
            viz.render(output_configs)  # type: ignore[arg-type]
        else:
            fmt = output_configs.get("format", "terminal")
            opts = {k: v for k, v in output_configs.items() if k != "format"}
            viz.render(fmt, **opts)


class NodeGroup(Node):
    """A Node that embeds a nested DAG, forming a hierarchical sub-plan.

    The outer DAG's traversal stops at the group boundary by default.
    Pass cross_groups=True to traversal methods to recurse into the inner DAG.
    """

    inner: DAG


# Allow Pydantic to resolve the forward references created by `from __future__
# import annotations` (all annotations become strings at parse time).
DAG.model_rebuild()
NodeGroup.model_rebuild()
