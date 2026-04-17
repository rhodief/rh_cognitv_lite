from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from rh_cognitv_lite.execution_platform.execution import Execution
from rh_cognitv_lite.orchestrators.graphs.graph_builder import GraphBuilder
from rh_cognitv_lite.orchestrators.graphs.models import Edge, Graph, Node

from .adapters.node_adapters import ExecutionNodeAdapterProtocol
from .nodes import BaseExecutionNode


class ExecutionGraph(BaseModel):
    """Bridge between cognitive-layer node definitions and the execution platform.

    Maintains a ``Graph`` for topology and a parallel registry mapping
    ``node_id → BaseExecutionNode`` for config/metadata retrieval.

    Fully serializable via Pydantic for snapshotting.  Holds no execution
    state — the orchestrator owns cursor position, results, and progression.
    """

    name: str
    graph: Graph = Field(default_factory=lambda: Graph._from_parts([], []))
    node_registry: dict[str, BaseExecutionNode] = Field(default_factory=dict)

    # Adapters are runtime-only – not serialized.
    _adapters: dict[str, ExecutionNodeAdapterProtocol] = PrivateAttr(
        default_factory=dict,
    )

    model_config = {"arbitrary_types_allowed": True}

    # ── Adapter management ────────────────────────────────────────────

    def register_adapter(
        self, kind: str, adapter: ExecutionNodeAdapterProtocol
    ) -> None:
        """Register an adapter that converts nodes of *kind* into ``Execution`` objects."""
        self._adapters[kind] = adapter

    # ── Node retrieval ────────────────────────────────────────────────

    def get_execution_node(self, node_id: str) -> BaseExecutionNode:
        """Retrieve the full ``BaseExecutionNode`` by id.

        Raises ``KeyError`` if *node_id* is not in the registry.
        """
        if node_id not in self.node_registry:
            raise KeyError(f"Execution node '{node_id}' not found in graph '{self.name}'")
        return self.node_registry[node_id]

    def get_execution(self, node_id: str) -> Execution:
        """Build an ``Execution`` from the node's config using the registered adapter.

        Raises ``KeyError`` if the node is not registered, or if no adapter
        exists for the node's ``kind``.
        """
        exec_node = self.get_execution_node(node_id)
        kind = getattr(exec_node, "kind", None)
        if kind is None:
            raise KeyError(
                f"Node '{node_id}' has no 'kind' attribute — "
                "cannot resolve adapter"
            )
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise KeyError(
                f"No adapter registered for node kind '{kind}' "
                f"(node '{node_id}' in graph '{self.name}')"
            )
        return adapter.to_execution(exec_node)

    def nodes(self) -> list[BaseExecutionNode]:
        """All registered execution nodes, in insertion order."""
        return list(self.node_registry.values())

    def entry_nodes(self) -> list[BaseExecutionNode]:
        """Execution nodes whose graph counterparts have no predecessors."""
        graph_entries = self.graph.entry_nodes()
        entry_ids = {n.id for n in graph_entries}
        return [self.node_registry[nid] for nid in entry_ids if nid in self.node_registry]

    def next_from(self, node_id: str) -> list[BaseExecutionNode]:
        """Successor execution nodes for *node_id* in the graph topology."""
        graph_node = self.graph.node_by_id(node_id)
        successors = self.graph.next_nodes_from(graph_node)
        return [
            self.node_registry[s.id]
            for s in successors
            if s.id in self.node_registry
        ]


# ──────────────────────────────────────────────────────────────────────
# Builder
# ──────────────────────────────────────────────────────────────────────


class ExecutionGraphBuilder:
    """Fluent builder for ``ExecutionGraph``.

    Accepts ``BaseExecutionNode`` objects, builds the underlying ``Graph``
    topology automatically, and produces an immutable ``ExecutionGraph``.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._graph_builder = GraphBuilder(name=name)
        self._node_registry: dict[str, BaseExecutionNode] = {}
        self._adapters: dict[str, ExecutionNodeAdapterProtocol] = {}

    def add_node(self, exec_node: BaseExecutionNode) -> ExecutionGraphBuilder:
        """Register an execution node (also adds a topology ``Node`` to the graph)."""
        if exec_node.id in self._node_registry:
            raise ValueError(
                f"Node '{exec_node.id}' is already registered in graph '{self._name}'"
            )
        graph_node = Node(
            id=exec_node.id,
            name=exec_node.name,
            description=exec_node.description,
            metadata=exec_node.metadata,
        )
        self._graph_builder.node(graph_node)
        self._node_registry[exec_node.id] = exec_node
        return self

    def add_edge(
        self,
        source: str,
        target: str,
        label: str | None = None,
    ) -> ExecutionGraphBuilder:
        """Add a directed edge between two already-registered nodes."""
        if source not in self._node_registry:
            raise ValueError(
                f"Source node '{source}' is not registered. Call add_node() first."
            )
        if target not in self._node_registry:
            raise ValueError(
                f"Target node '{target}' is not registered. Call add_node() first."
            )
        self._graph_builder.edge(source, target, label=label)
        return self

    def adapter(
        self, kind: str, adapter: ExecutionNodeAdapterProtocol
    ) -> ExecutionGraphBuilder:
        """Register an adapter for a given node kind."""
        self._adapters[kind] = adapter
        return self

    def build(self) -> ExecutionGraph:
        """Produce an immutable ``ExecutionGraph``."""
        graph = self._graph_builder.build()
        eg = ExecutionGraph(
            name=self._name,
            graph=graph,
            node_registry=dict(self._node_registry),
        )
        for kind, adp in self._adapters.items():
            eg.register_adapter(kind, adp)
        return eg
