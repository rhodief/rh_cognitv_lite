"""
Data models for the graphs orchestration layer.

Node, NodeGroup, Edge, GraphBuilderConfig, Graph.

Backward-compat aliases (deprecated):
  DAGBuilderConfig = kept with original strict defaults
  DAG              = Graph
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field, model_validator

from rh_cognitv_lite.orchestrators.graphs.graph_engine import _GraphEngine


class Node(BaseModel):
    """Named, identified placeholder in a graph. Carries no execution logic.

    Upstream layers resolve what runs for a given node based on its id.
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


class GraphBuilderConfig(BaseModel):
    """Construction-time validation flags for GraphBuilder.

    Defaults are permissive — suitable for generic directed graphs that may
    be cyclic.  Use explicit flags to enforce stricter constraints (e.g. for
    workflow DAGs).
    """

    append_only: bool = False
    """If True, remove_node / remove_edge are disabled."""

    validate_acyclic: bool = False
    """If True, checks for cycles on every edge() call."""

    validate_connected: bool = False
    """If True, checks connectedness on every structural change."""

    allow_isolated_nodes: bool = True
    """If True, permits nodes that have no edges at build time."""

    allow_self_loops: bool = True
    """If True, permits edges from a node to itself (a → a)."""

    allow_parallel_edges: bool = False
    """If True, permits more than one edge between the same ordered pair."""


class DAGBuilderConfig(BaseModel):
    """Strict construction-time validation flags for DAGBuilder.

    Deprecated: use GraphBuilderConfig with explicit flags instead.
    Kept with original defaults for backward compatibility.
    """

    append_only: bool = False
    validate_acyclic: bool = True
    validate_connected: bool = False
    allow_isolated_nodes: bool = False
    allow_self_loops: bool = False
    allow_parallel_edges: bool = False


class Graph(BaseModel):
    """Immutable, read-only directed graph — a pure topology map.

    May be acyclic (DAG) or cyclic.  Constructed exclusively by GraphBuilder.
    Fully serialisable to/from JSON via Pydantic for state persistence and
    snapshot/resume workflows.

    The graph is a transition map: for any cursor node it immediately answers
    ``next_nodes_from`` and ``prev_nodes_from``, enabling forward traversal,
    rewind, and branching without any execution logic living here.

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
    def _build_engine(self) -> Graph:
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

    # ── Internal factory used exclusively by GraphBuilder ─────────────────────
    @classmethod
    def _from_parts(cls, nodes: list[Node], edges: list[Edge]) -> Graph:
        return cls(nodes_data=nodes, edges_data=edges)

    # ── Node lookup ───────────────────────────────────────────────────────────

    def node_by_id(self, node_id: str) -> Node:
        """Return the node with the given id.  Raises KeyError if not found."""
        for n in self.nodes_data:
            if n.id == node_id:
                return n
        raise KeyError(f"No node with id {node_id!r}")

    def nodes_by_ids(self, ids: set[str]) -> set[Node]:
        """Return the set of nodes whose ids are in *ids*."""
        return {self.node_by_id(i) for i in ids}

    # Keep private aliases for internal callers and backward compat.
    def _node_by_id(self, node_id: str) -> Node:
        return self.node_by_id(node_id)

    def _nodes_by_ids(self, ids: set[str]) -> set[Node]:
        return self.nodes_by_ids(ids)

    # ── Node navigation ───────────────────────────────────────────────────────

    def entry_nodes(self) -> set[Node]:
        """Return nodes with no predecessors (in-degree 0)."""
        return self.nodes_by_ids(self._get_engine().entry_nodes())

    def is_entry_node(self, node: Node) -> bool:
        return node.id in self._get_engine().entry_nodes()

    def leaf_nodes(self) -> set[Node]:
        """Return nodes with no successors (out-degree 0).

        In a fully cyclic graph this may return an empty set.
        """
        return self.nodes_by_ids(self._get_engine().leaf_nodes())

    def is_leaf_node(self, node: Node) -> bool:
        return node.id in self._get_engine().leaf_nodes()

    def next_nodes_from(self, node: Node | None = None) -> set[Node]:
        """Direct successors of *node* (single hop).

        If *node* is None, returns entry nodes — useful for starting
        a cursor-based traversal loop.
        """
        if node is None:
            return self.entry_nodes()
        return self.nodes_by_ids(self._get_engine().successors_of(node.id))

    def prev_nodes_from(self, node: Node) -> set[Node]:
        """Direct predecessors of *node* (single hop).  Enables rewind."""
        return self.nodes_by_ids(self._get_engine().predecessors_of(node.id))

    def edges_from(self, node: Node) -> list[Edge]:
        """All outgoing edges from *node*, including label."""
        return [e for e in self.edges_data if e.source == node.id]

    def edges_to(self, node: Node) -> list[Edge]:
        """All incoming edges to *node*, including label."""
        return [e for e in self.edges_data if e.target == node.id]

    # ── Reachability ──────────────────────────────────────────────────────────

    def descendants_of(self, node: Node, *, cross_groups: bool = False) -> set[Node]:
        """All nodes reachable downstream from *node*.

        When cross_groups=False (default), NodeGroup internals are opaque —
        the group node itself is included in results but its inner nodes are not.
        When cross_groups=True, also expands every NodeGroup encountered,
        including the starting node itself if it is a NodeGroup.

        Cycle-safe on cyclic graphs.
        """
        raw_desc_ids = self._get_engine().descendants_of(node.id)

        if not cross_groups:
            return self.nodes_by_ids(raw_desc_ids)

        result: set[Node] = self.nodes_by_ids(raw_desc_ids)

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
        """Shortest directed path from *source* to *target*, or None."""
        ids = self._get_engine().path_between(source.id, target.id)
        if ids is None:
            return None
        return [self.node_by_id(i) for i in ids]

    # ── Structural queries ────────────────────────────────────────────────────

    def has_cycle(self) -> bool:
        """Return True if the graph contains at least one directed cycle."""
        return self._get_engine().has_cycle()

    def is_acyclic(self) -> bool:
        """Return True if the graph contains no directed cycles."""
        return not self._get_engine().has_cycle()

    def would_create_cycle(self, source: Node, target: Node) -> bool:
        """Pre-flight check: True if adding source→target would form a cycle."""
        return self._get_engine().would_create_cycle(source.id, target.id)

    def validate_acyclic(self) -> None:
        """Raise ValueError if the graph contains a cycle."""
        if self._get_engine().has_cycle():
            raise ValueError("Graph contains a cycle.")

    def validate_connectedness(self) -> None:
        """Raise ValueError if the graph is not weakly connected.

        An empty graph is considered connected (vacuously true).
        """
        nodes = list(self.nodes_data)
        if len(nodes) <= 1:
            return
        eng = self._get_engine()
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
            raise ValueError("Graph is not connected.")

    # ── Snapshot & copy ───────────────────────────────────────────────────────

    def copy(self, *, deep: bool = False) -> Graph:
        """Return a copy of this graph.

        shallow (deep=False): node and edge objects are shared.
        deep (deep=True): node and edge objects are fully independent.
        """
        if deep:
            return Graph._from_parts(
                nodes=copy.deepcopy(self.nodes_data),
                edges=copy.deepcopy(self.edges_data),
            )
        return Graph._from_parts(
            nodes=list(self.nodes_data),
            edges=list(self.edges_data),
        )

    # ── Render model ──────────────────────────────────────────────────────────

    def to_render_model(self) -> Any:
        """Produce a format-agnostic GraphRenderModel for visualizer adapters.

        Returns a ``GraphRenderModel`` (imported lazily to avoid circular
        imports).  Pass the result to any ``GraphVisualizerAdapter``.
        """
        from rh_cognitv_lite.orchestrators.graphs.graph_visualizer import (
            GraphRenderModel,
            RenderEdge,
            RenderNode,
        )
        eng = self._get_engine()
        be = eng.back_edges()
        in_cycle_ids = eng.nodes_in_cycles()

        render_nodes = []
        for n in self.nodes_data:
            render_nodes.append(
                RenderNode(
                    id=n.id,
                    name=n.name,
                    description=n.description,
                    is_group=isinstance(n, NodeGroup),
                    in_cycle=n.id in in_cycle_ids,
                    metadata=dict(n.metadata) if n.metadata else {},
                    inner=n.inner.to_render_model() if isinstance(n, NodeGroup) else None,
                )
            )

        render_edges = []
        for e in self.edges_data:
            render_edges.append(
                RenderEdge(
                    source_id=e.source,
                    target_id=e.target,
                    label=e.label,
                    is_back_edge=(e.source, e.target) in be,
                )
            )

        return GraphRenderModel(
            nodes=render_nodes,
            edges=render_edges,
            is_cyclic=eng.has_cycle(),
        )

    # ── Visualize convenience ─────────────────────────────────────────────────

    def visualize(self, format: str = "terminal", **options: Any) -> None:
        """Render this graph using the built-in adapters.

        Parameters
        ----------
        format:
            ``"terminal"`` (default), ``"json"``, ``"html"`` (deferred),
            ``"image"`` (deferred).
        **options:
            ``indent`` — integer indent for json format (default 2).
        """
        from rh_cognitv_lite.orchestrators.graphs.graph_visualizer import (
            GraphVisualizer,
            JsonAdapter,
            TerminalAdapter,
        )
        if format == "terminal":
            adapter = TerminalAdapter()
        elif format == "json":
            adapter = JsonAdapter(indent=options.get("indent", 2))
        elif format in ("html", "image"):
            raise NotImplementedError(
                f"{format!r} rendering is deferred."
            )
        else:
            raise ValueError(
                f"Unknown format {format!r}. "
                "Valid choices: 'terminal', 'json', 'html', 'image'."
            )
        GraphVisualizer(adapter).render(self)


class NodeGroup(Node):
    """A Node that embeds a nested Graph, forming a hierarchical sub-graph.

    The outer graph's traversal stops at the group boundary by default.
    Pass cross_groups=True to traversal methods to recurse into the inner graph.
    The inner graph may itself be cyclic or acyclic.
    """

    inner: Graph


# ── Backward-compat alias ─────────────────────────────────────────────────────
# DAG is kept as a deprecated alias for Graph.  New code should use Graph.
DAG = Graph

# Allow Pydantic to resolve the forward references created by `from __future__
# import annotations` (all annotations become strings at parse time).
Graph.model_rebuild()
NodeGroup.model_rebuild()
