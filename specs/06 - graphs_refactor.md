# Spec 06 — Graphs Module Refactor: Generic Execution Map

## Status: Draft

---

## 1. Background & Goal

The current `graphs` module is a **DAG-only** implementation. The acyclic constraint is baked in by default and the entire naming surface (`DAG`, `DAGBuilder`, `DAGBuilderConfig`) makes that assumption explicit.

The goal of this refactor is to replace the DAG with a **generic directed graph** that serves as a pure structural map — no execution logic, no scheduling, no state mutation. The graph knows topology only. Consumers (orchestrators, runners) read from it to decide where to go next.

The key insight: **the graph is a transition map**. For any known cursor position (a node), it can immediately answer "where did we come from?" and "where can we go?". This makes it trivially suitable for:

- **Snapshotting** — serialise the graph + cursor position to fully capture execution state.
- **Resuming** — deserialise and continue from any previously known node.
- **Replaying / rewinding** — navigate backwards using `prev_nodes_from`.
- **Branching execution** — fan-out edges, conditional transitions chosen at runtime.
- **Loop execution** — back-edges are legal; the cycle-detection tooling becomes advisory, not blocking.

Sub-graphs (`NodeGroup`) remain first-class and can each independently be cyclic or acyclic, enabling mixed topologies like:

```
[Plan] ──► [Execute] ──► [Review]
   ▲                         │
   └─────────────────────────┘   ← back-edge (cyclic outer loop)

[Execute] contains a NodeGroup whose inner graph is a linear DAG (acyclic workflow).
```

---

## 2. Design Principles

1. **Map, not runner.** The graph holds topology only. No execution state, no async, no side effects.
2. **Cursor-agnostic.** The graph does not track "current node" — that is the caller's responsibility. The graph just answers transition queries.
3. **Full serializability.** Every graph must round-trip to/from JSON losslessly via Pydantic.
4. **Opt-in validation.** Cycle detection, connectedness, self-loops, parallel edge checks are all flags in the builder config, none enabled by default except what the specific graph type requires.
5. **Topology is immutable after build.** The builder produces a frozen graph. Mutations go through a `GraphBuilder.from_graph(g)` continuation pattern.
6. **Subgraphs via NodeGroup.** Mixed topologies are expressed through nesting, not flags on individual edges.
7. **Visualizer is always topology-complete.** It always expands `NodeGroup` internals regardless of outer traversal mode.

---

## 3. Module Structure Rename

```
rh_cognitv_lite/orchestrators/graphs/
    __init__.py             ← public surface
    graph.py                ← replaces dag.py (Graph model)
    graph_engine.py         ← replaces dag_engine.py (_GraphEngine, unchanged logic)
    graph_builder.py        ← replaces dag_builder.py (GraphBuilder)
    graph_visualizer.py     ← replaces dag_visualizer.py (GraphVisualizer)
    models.py               ← Node, NodeGroup, Edge, GraphBuilderConfig (unchanged structure)
    py.typed
```

**Backward-compat aliases** (`dag.py`, `DAG`, `DAGBuilder`, `DAGBuilderConfig`) are kept but deprecated for one release cycle, then removed.

---

## 4. Data Models

### 4.1 `Node` — unchanged

```python
class Node(BaseModel):
    id: str
    name: str
    description: str
    metadata: dict[str, Any] = {}
```

### 4.2 `NodeGroup` — unchanged structure, relaxed constraint

```python
class NodeGroup(Node):
    inner: Graph   # was: inner: DAG — now accepts any Graph (cyclic or not)
```

The inner `Graph` is built independently and wrapped, same as today.

### 4.3 `Edge` — unchanged

```python
class Edge(BaseModel):
    source: str
    target: str
    label: str | None = None
```

No condition or routing metadata on edges. Transition decisions (which outgoing edge to follow at a fan-out node) are entirely the orchestrator's responsibility.

### 4.4 `GraphBuilderConfig` — replaces `DAGBuilderConfig`

```python
class GraphBuilderConfig(BaseModel):
    append_only: bool = False
    validate_acyclic: bool = False        # changed default: False (generic graph)
    validate_connected: bool = False
    allow_isolated_nodes: bool = True     # changed default: True (generic graph)
    allow_self_loops: bool = True         # changed default: True (loops are valid)
    allow_parallel_edges: bool = False
```

A strict `DAGBuilderConfig`-equivalent is now expressed as:

```python
GraphBuilderConfig(
    validate_acyclic=True,
    allow_isolated_nodes=False,
    allow_self_loops=False,
)
```

### 4.5 `Graph` — replaces `DAG`

```python
class Graph(BaseModel):
    nodes_data: list[NodeGroup | Node]
    edges_data: list[Edge]
    _engine: _GraphEngine | None   # not serialised
```

Same Pydantic shape as `DAG`. Fully serialisable. Engine rebuilt on deserialisation via `model_validator`.

---

## 5. `_GraphEngine` — minimal changes

The engine logic is mostly correct and cycle-safe already. Required changes:

| Method | Change |
|---|---|
| `descendants_of` | Already cycle-safe (visited set). No change. |
| `has_cycle` / `would_create_cycle` | No change — promoted to advisory tools. |
| `topological_generations` | Scoped to acyclic subgraphs. Raises if cyclic — **this is now a caller responsibility**; the engine documents this clearly. Callers should guard with `has_cycle()` before calling. |
| `path_between` | No change — BFS with visited set, already cycle-safe. |
| `reachable_from` | New alias for `descendants_of` with clearer name. |
| `successors_of` | New: returns direct successors (single hop), replaces `_succ` direct access. |
| `predecessors_of` | New: returns direct predecessors (single hop), replaces `_pred` direct access. |

The engine remains private (`_GraphEngine`). No public access.

---

## 6. `Graph` Traversal API

The `Graph` model exposes these query methods. All are pure reads — no mutation.

### 6.1 Node navigation

| Method | Signature | Notes |
|---|---|---|
| `entry_nodes` | `() -> set[Node]` | Nodes with in-degree 0 |
| `leaf_nodes` | `() -> set[Node]` | Nodes with out-degree 0. In cyclic graphs may be empty. |
| `is_entry_node` | `(Node) -> bool` | |
| `is_leaf_node` | `(Node) -> bool` | |
| `next_nodes_from` | `(Node \| None) -> set[Node]` | Direct successors. `None` → entry nodes. Core of the cursor-step loop. |
| `prev_nodes_from` | `(Node) -> set[Node]` | Direct predecessors. Enables rewind. |
| `edges_from` | `(Node) -> list[Edge]` | All outgoing edges with their labels/conditions. |
| `edges_to` | `(Node) -> list[Edge]` | All incoming edges. |

### 6.2 Reachability

| Method | Signature | Notes |
|---|---|---|
| `descendants_of` | `(Node, *, cross_groups=False) -> set[Node]` | All reachable forward. Cycle-safe. |
| `is_reachable` | `(Node, Node) -> bool` | |
| `path_between` | `(Node, Node) -> list[Node] \| None` | Shortest directed path (BFS). |

### 6.3 Structural queries

| Method | Signature | Notes |
|---|---|---|
| `has_cycle` | `() -> bool` | Advisory. Does not raise. |
| `is_acyclic` | `() -> bool` | `not has_cycle()` |
| `validate_acyclic` | `() -> None` | Raises `ValueError` if cyclic. Caller-invoked. |
| `validate_connectedness` | `() -> None` | Raises `ValueError` if not weakly connected. |
| `would_create_cycle` | `(Node, Node) -> bool` | Pre-flight check for dynamic edge addition via builder continuation. |

### 6.4 Snapshot & copy

| Method | Signature | Notes |
|---|---|---|
| `copy` | `(*, deep: bool = False) -> Graph` | Shallow or deep clone. |
| `model_dump` | `() -> dict` | Pydantic — full JSON-serialisable snapshot. |
| `model_validate` | `(dict) -> Graph` | Pydantic — restore from snapshot. |

`model_dump` + `model_validate` give full snapshotting for free. The caller pairs these with a cursor node ID (a plain `str`) to fully capture and restore execution position.

**Snapshot pattern (caller side):**
```python
snapshot = {
    "graph": graph.model_dump(),
    "cursor": current_node.id,
    "step": step_index,
}

# restore
graph = Graph.model_validate(snapshot["graph"])
current_node = graph.node_by_id(snapshot["cursor"])
```

### 6.5 Utilities

| Method | Signature | Notes |
|---|---|---|
| `node_by_id` | `(str) -> Node` | O(1) lookup via internal index. Raises `KeyError` if not found. |
| `nodes_by_ids` | `(set[str]) -> set[Node]` | Batch lookup. |
| `to_render_model` | `() -> GraphRenderModel` | Produce the format-agnostic render data structure. |

---

## 7. `GraphBuilder` — replaces `DAGBuilder`

Fluent, chainable. Produces an immutable `Graph`.

```python
graph = (
    GraphBuilder(name="plan-execute-review")
    .node(plan_node)
    .node(execute_node)
    .node(review_node)
    .edge(plan_node, execute_node)
    .edge(execute_node, review_node)
    .edge(review_node, plan_node, label="needs_revision")   # back-edge
    .edge(review_node, end_node, label="approved")
    .build()
)
```

**Additional methods:**

| Method | Signature | Notes |
|---|---|---|
| `node` | `(Node) -> GraphBuilder` | Register a node. |
| `edge` | `(Node \| str, Node \| str, label=None) -> GraphBuilder` | Add a directed edge. |
| `group` | `(NodeGroup) -> GraphBuilder` | Shorthand for `.node()` on a `NodeGroup`. |
| `remove_node` | `(Node \| str) -> GraphBuilder` | Disabled if `append_only=True`. |
| `remove_edge` | `(Node \| str, Node \| str) -> GraphBuilder` | Disabled if `append_only=True`. |
| `build` | `() -> Graph` | Validate and produce the immutable graph. |
| `from_graph` | `(Graph) -> GraphBuilder` | Class method. Re-open an existing graph for modification. |

---

## 8. `GraphVisualizer` — adapter-based rendering

The visualizer is split into two layers:

### 8.1 `GraphRenderModel` — the render data structure

`GraphRenderModel` is the single intermediate representation produced by the graph. It is format-agnostic — a plain, serialisable data structure that captures the full topology ready for rendering. Any adapter consumes it.

```python
@dataclass
class RenderNode:
    id: str
    name: str
    description: str
    is_group: bool
    in_cycle: bool          # True if this node participates in a cycle
    inner: GraphRenderModel | None  # populated for NodeGroup nodes

@dataclass
class RenderEdge:
    source_id: str
    target_id: str
    label: str | None
    is_back_edge: bool      # True if this edge creates a cycle (back-edge in DFS)

@dataclass
class GraphRenderModel:
    nodes: list[RenderNode]
    edges: list[RenderEdge]
    is_cyclic: bool
```

Produced by:

```python
graph.to_render_model() -> GraphRenderModel
```

This is the only method `Graph` exposes for visualization. The graph itself has no knowledge of output formats.

### 8.2 `GraphVisualizerAdapter` — pluggable renderer protocol

```python
class GraphVisualizerAdapter(Protocol):
    def render(self, model: GraphRenderModel) -> None: ...
```

Any object implementing `render(GraphRenderModel) -> None` is a valid adapter. No base class required.

### 8.3 `GraphVisualizer` — coordinator

```python
class GraphVisualizer:
    def __init__(self, adapter: GraphVisualizerAdapter) -> None: ...
    def render(self, graph: Graph) -> None: ...
```

Calls `graph.to_render_model()` then forwards to the adapter. The visualizer holds no rendering logic itself.

### 8.4 Built-in adapters

| Adapter | Format | Status |
|---|---|---|
| `TerminalAdapter` | ASCII/Unicode tree to stdout. Cycle nodes marked `[↺]`, back-edges marked `[↺─]`. | Implemented |
| `JsonAdapter` | Prints `GraphRenderModel` as JSON to stdout. | Implemented |
| `HtmlAdapter` | Interactive HTML graph. | Deferred |
| `ImageAdapter` | Static image export. | Deferred |

**Usage:**

```python
visualizer = GraphVisualizer(adapter=TerminalAdapter())
visualizer.render(graph)

# swap adapter, same graph
visualizer = GraphVisualizer(adapter=JsonAdapter())
visualizer.render(graph)
```

---

## 9. Mixed Topology Example

```
Outer graph (cyclic):

  [Start] → [Plan] → [Execute] → [Review]
                                     │ label="needs_revision"
                                     ▼
                               [Plan] (back-edge)
                                     │ label="approved"
                                     ▼
                               [End]

Inner graph of [Execute] NodeGroup (acyclic DAG):

  [Fetch] → [Parse] → [Transform] → [WriteOutput]
```

The outer `GraphBuilder` uses default config (`validate_acyclic=False`).
The inner `GraphBuilder` for `[Execute]`'s inner graph uses `GraphBuilderConfig(validate_acyclic=True)` to enforce the workflow DAG contract.

---

## 10. What Is Removed / Not Carried Forward

| Current | Disposition |
|---|---|
| `DAGBuilderConfig.validate_acyclic=True` default | Changed to `False` in `GraphBuilderConfig`. Opt-in per use case. |
| `DAGBuilderConfig.allow_isolated_nodes=False` default | Changed to `True`. |
| `DAGBuilderConfig.allow_self_loops=False` default | Changed to `True`. |
| `topological_generations()` on `DAG` | Moved to engine only, not exposed on `Graph`. Call `graph._get_engine().topological_generations()` explicitly, guarded by `is_acyclic()`. |
| `DAG` / `DAGBuilder` / `DAGBuilderConfig` names | Deprecated aliases kept for one release, then removed. |

---

## 11. Out of Scope for This Refactor

- Execution cursors, run state, step tracking — caller responsibility.
- Conditional edge evaluation — caller responsibility.
- Async traversal — caller responsibility.
- `PlanDAG` / `ExecutionDAG` overlay layers — separate spec.
- Loop termination / max-iteration guards — separate spec (orchestrator layer).
