"""DAGBuilder — fluent, chainable construction API for DAG.

This is the sole legitimate way to construct a DAG instance.
"""

from __future__ import annotations

from rh_cognitv_lite.orchestrators.graphs.dag_engine import _GraphEngine
from rh_cognitv_lite.orchestrators.graphs.models import (
    DAG,
    DAGBuilderConfig,
    Edge,
    Node,
    NodeGroup,
)


class DAGBuilder:
    """Fluent builder that produces an immutable ``DAG``.

    Parameters
    ----------
    name:
        Human-readable label for this builder / the DAG being constructed.
        Not persisted on the resulting ``DAG`` object (DAG is anonymous).
    config:
        Construction-time validation flags.  Defaults to
        ``DAGBuilderConfig()`` (acyclic validation on, everything else off).
    """

    def __init__(
        self,
        name: str = "",
        config: DAGBuilderConfig | None = None,
    ) -> None:
        self._name = name
        self._config = config if config is not None else DAGBuilderConfig()
        # Ordered list of nodes; preserves insertion order.
        self._nodes: list[Node] = []
        # id → node index for O(1) lookup.
        self._node_index: dict[str, int] = {}
        # Ordered list of edges.
        self._edges: list[Edge] = []
        # (source_id, target_id) → True — fast duplicate detection.
        self._edge_set: set[tuple[str, str]] = set()

    # ── Node registration ─────────────────────────────────────────────────────

    def node(self, node_obj: Node) -> DAGBuilder:
        """Register a node.

        Parameters
        ----------
        node_obj:
            Any ``Node`` instance (including ``NodeGroup``).
            The node's ``.id`` must be unique within this builder.

        Raises
        ------
        ValueError
            If a node with the same ``id`` is already registered.
        """
        if node_obj.id in self._node_index:
            raise ValueError(
                f"A node with id {node_obj.id!r} is already registered."
            )
        self._node_index[node_obj.id] = len(self._nodes)
        self._nodes.append(node_obj)
        return self

    # ── Edge registration ─────────────────────────────────────────────────────

    def edge(
        self,
        source: Node | str,
        target: Node | str,
        label: str | None = None,
    ) -> DAGBuilder:
        """Add a directed edge from *source* to *target*.

        Parameters
        ----------
        source, target:
            Either a ``Node`` object (already registered) or a node-ID string.
        label:
            Optional informational label; does not affect traversal.

        Raises
        ------
        ValueError
            - If *source* or *target* is not registered.
            - If self-loops are disallowed and ``source == target``.
            - If parallel edges are disallowed and the edge already exists.
            - If acyclic validation is enabled and adding the edge would
              create a cycle.
        """
        src_id = source if isinstance(source, str) else source.id
        tgt_id = target if isinstance(target, str) else target.id

        if src_id not in self._node_index:
            raise ValueError(
                f"Source node {src_id!r} is not registered. "
                "Call .node() before .edge()."
            )
        if tgt_id not in self._node_index:
            raise ValueError(
                f"Target node {tgt_id!r} is not registered. "
                "Call .node() before .edge()."
            )

        if not self._config.allow_self_loops and src_id == tgt_id:
            raise ValueError(
                f"Self-loop on node {src_id!r} is not allowed. "
                "Set allow_self_loops=True in DAGBuilderConfig to permit this."
            )

        if not self._config.allow_parallel_edges and (src_id, tgt_id) in self._edge_set:
            raise ValueError(
                f"Parallel edge {src_id!r} → {tgt_id!r} already exists. "
                "Set allow_parallel_edges=True in DAGBuilderConfig to permit this."
            )

        if self._config.validate_acyclic:
            engine = self._current_engine()
            if engine.would_create_cycle(src_id, tgt_id):
                raise ValueError(
                    f"Adding edge {src_id!r} → {tgt_id!r} would create a cycle. "
                    "Set validate_acyclic=False in DAGBuilderConfig to skip this check."
                )

        self._edges.append(Edge(source=src_id, target=tgt_id, label=label))
        self._edge_set.add((src_id, tgt_id))
        return self

    # ── Group registration ────────────────────────────────────────────────────

    def group(self, group_node: NodeGroup) -> DAGBuilder:
        """Register a ``NodeGroup`` (shorthand for ``node(group_node)``).

        The inner ``DAG`` must already be built (use a nested ``DAGBuilder``
        and call ``.build()`` to produce the inner ``DAG`` first, then wrap
        it in a ``NodeGroup``).

        Raises
        ------
        ValueError
            If a node with the same ``id`` is already registered.
        TypeError
            If *group_node* is not a ``NodeGroup`` instance.
        """
        if not isinstance(group_node, NodeGroup):
            raise TypeError(
                f"group() expects a NodeGroup instance, got {type(group_node).__name__!r}."
            )
        return self.node(group_node)

    # ── Removal ───────────────────────────────────────────────────────────────

    def remove_node(self, node_id: str) -> DAGBuilder:
        """Remove a registered node and all edges that reference it.

        Raises
        ------
        ValueError
            - If ``append_only=True`` in the config.
            - If no node with *node_id* is registered.
        """
        if self._config.append_only:
            raise ValueError(
                "remove_node() is disabled when append_only=True."
            )
        if node_id not in self._node_index:
            raise ValueError(f"No node with id {node_id!r} is registered.")

        # Remove node from list and rebuild index.
        self._nodes = [n for n in self._nodes if n.id != node_id]
        self._node_index = {n.id: i for i, n in enumerate(self._nodes)}

        # Drop all edges that reference the removed node.
        self._edges = [
            e for e in self._edges
            if e.source != node_id and e.target != node_id
        ]
        self._edge_set = {(e.source, e.target) for e in self._edges}
        return self

    def remove_edge(self, source: Node | str, target: Node | str) -> DAGBuilder:
        """Remove a specific directed edge.

        Raises
        ------
        ValueError
            - If ``append_only=True`` in the config.
            - If the edge does not exist.
        """
        if self._config.append_only:
            raise ValueError(
                "remove_edge() is disabled when append_only=True."
            )
        src_id = source if isinstance(source, str) else source.id
        tgt_id = target if isinstance(target, str) else target.id

        if (src_id, tgt_id) not in self._edge_set:
            raise ValueError(
                f"Edge {src_id!r} → {tgt_id!r} does not exist."
            )
        self._edges = [
            e for e in self._edges
            if not (e.source == src_id and e.target == tgt_id)
        ]
        self._edge_set.discard((src_id, tgt_id))
        return self

    # ── Continuation pattern ──────────────────────────────────────────────────

    @classmethod
    def from_dag(cls, dag: DAG, name: str = "", config: DAGBuilderConfig | None = None) -> DAGBuilder:
        """Seed a new builder with all nodes and edges from an existing ``DAG``.

        This is the continuation pattern for post-build modifications:
        ``DAGBuilder.from_dag(dag).edge(...).build()``.

        Parameters
        ----------
        dag:
            The source DAG to copy from.
        name:
            Label for the new builder.
        config:
            Validation config for the new builder.  Defaults to
            ``DAGBuilderConfig()`` (same as a fresh builder).
        """
        builder = cls(name=name, config=config)
        for node_obj in dag.nodes_data:
            builder.node(node_obj)
        for edge_obj in dag.edges_data:
            builder._edges.append(edge_obj)
            builder._edge_set.add((edge_obj.source, edge_obj.target))
        return builder

    # ── Visualize pass-through ────────────────────────────────────────────────

    def visualize(self, output_configs=None) -> None:
        """Build a snapshot of the current builder state and render it.

        Accepts the same *output_configs* argument as ``DAG.visualize()``.
        """
        snapshot = DAG._from_parts(list(self._nodes), list(self._edges))
        snapshot.visualize(output_configs)

    # ── Build ─────────────────────────────────────────────────────────────────

    def build(self) -> DAG:
        """Apply all enabled validation flags and return an immutable ``DAG``.

        Raises
        ------
        ValueError
            If any enabled validation flag is violated.
        """
        self._apply_build_validations()
        return DAG._from_parts(list(self._nodes), list(self._edges))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _current_engine(self) -> _GraphEngine:
        """Snapshot engine over the current builder state."""
        node_ids = {n.id for n in self._nodes}
        edge_pairs = {(e.source, e.target) for e in self._edges}
        return _GraphEngine(node_ids, edge_pairs)

    def _apply_build_validations(self) -> None:
        """Run all validations that are gated at build time."""
        cfg = self._config

        if not cfg.allow_isolated_nodes:
            referenced = set()
            for e in self._edges:
                referenced.add(e.source)
                referenced.add(e.target)
            # An isolated node is registered but not referenced by any edge,
            # unless the graph itself is a single-node graph with no edges.
            if self._edges or len(self._nodes) > 1:
                for n in self._nodes:
                    if n.id not in referenced:
                        raise ValueError(
                            f"Node {n.id!r} is isolated (no edges). "
                            "Set allow_isolated_nodes=True in DAGBuilderConfig "
                            "to permit isolated nodes."
                        )

        if cfg.validate_connected and len(self._nodes) > 1:
            dag = DAG._from_parts(list(self._nodes), list(self._edges))
            dag.validate_connectedness()

        # Acyclic validation on .edge() should have caught any cycles already,
        # but run a final check if the flag is enabled (covers edge removal,
        # force-added edges via from_dag, etc.).
        if cfg.validate_acyclic:
            engine = self._current_engine()
            if engine.has_cycle():
                raise ValueError(
                    "The graph contains a cycle. "
                    "Set validate_acyclic=False in DAGBuilderConfig to skip "
                    "this check."
                )
