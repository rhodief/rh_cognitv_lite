# Spec 02 — Orchestration: DAG

## Status: Draft

---

## 1. Background & Goal

The **DAG** (Directed Acyclic Graph) module is the structural backbone of the orchestration layer. Its sole responsibility is to represent *what runs and in what order* — it carries no execution logic itself.

The DAG is intentionally **standalone**. It will be used by both a future `PlanDAG` layer (which carries execution metadata on top of the topology) and an `ExecutionDAG` layer (which tracks live run state). A future Orchestrator spec will define how those layers connect to the `ExecutionPlatform`. This spec defines only the base DAG and its builder.

The DAG must answer questions like:
- Which nodes are entry points?
- Which nodes follow a given node?
- Are two nodes in the same connected component?
- Would adding an edge create a cycle?

A companion `DAGBuilder` exposes a fluent, chainable API for constructing DAGs with configurable validation rules. Sub-DAGs can be embedded as first-class `NodeGroup` nodes, enabling hierarchical plans.

---

## 2. Defined Contracts

### 2.1 `Node`

```python
class Node(BaseModel):
    id: str              # canonical key — unique within the DAG
    name: str            # human-readable label
    description: str     # human-readable description
    metadata: dict = {}  # arbitrary extra data for upstream layers
```

No execution logic lives here. A node is an identified, described placeholder. Upstream layers (e.g. `PlanDAG`) resolve what "runs" for a given node based on its `id`.

`NodeGroup` is a first-class subtype that embeds a nested `DAG`:

```python
class NodeGroup(Node):
    inner: DAG
```

The outer DAG's traversal stops at the group boundary by default. Traversal methods that support `cross_groups=True` recurse into group internals.

### 2.2 `Edge`

```python
class Edge(BaseModel):
    source: str           # source node ID
    target: str           # target node ID
    label: str | None = None  # optional metadata; no effect on traversal or direction
```

`label` is purely informational — useful for visualization and will be set by execution adapters when integrating with the executor layer. It does not influence traversal.

### 2.3 `DAG` — read-only traversal API

`DAG` is **immutable after construction**. All construction and mutation is done through `DAGBuilder`. `DAG` is fully serialisable to/from JSON via Pydantic to support state persistence and recovery.

| Method | Signature | Notes |
|---|---|---|
| `entry_nodes` | `() -> set[Node]` | Nodes with no predecessors |
| `is_entry_node` | `(Node) -> bool` | |
| `leaf_nodes` | `() -> set[Node]` | Nodes with no successors |
| `is_leaf_node` | `(Node) -> bool` | |
| `next_nodes_from` | `(Node \| None) -> set[Node]` | Fan-out; if `None`, returns entry nodes |
| `prev_nodes_from` | `(Node) -> set[Node]` | Fan-in |
| `descendants_of` | `(Node, *, cross_groups=False) -> set[Node]` | All reachable nodes downstream; `cross_groups=True` recurses into `NodeGroup` internals |
| `is_reachable` | `(Node, Node) -> bool` | |
| `path_between` | `(Node, Node) -> list[Node]` | Shortest path |
| `would_create_cycle` | `(Node, Node) -> bool` | Pre-flight check |
| `validate_acyclic` | `() -> None` | Raises on violation — public utility for external consumers |
| `validate_connectedness` | `() -> None` | Raises on violation — public utility for external consumers |
| `copy` | `(deep=False) -> DAG` | Shallow or deep clone |
| `visualize` | `(output_configs) -> None` | Delegates to `DAGVisualizer`; always renders the full topology including `NodeGroup` internals |

If post-build edits are needed, the continuation pattern is: `DAGBuilder.from_dag(existing).edge(...).build()`.

### 2.4 `DAGBuilder` — construction API

`DAGBuilder` is the sole mechanism for constructing a `DAG`. Configuration is a `BaseModel`:

```python
class DAGBuilderConfig(BaseModel):
    append_only: bool = False           # disables remove_node / remove_edge
    validate_acyclic: bool = True       # checks for cycles on every edge() call
    validate_connected: bool = False    # checks connectedness on every structural change
    allow_isolated_nodes: bool = False  # permits nodes with no edges
    allow_self_loops: bool = False      # permits a → a edges
    allow_parallel_edges: bool = False  # permits duplicate edges between the same pair
```

**Fluent API:**

```python
dag = (DAGBuilder(name="plan", config=DAGBuilderConfig())
    .node(FetchNode)
    .node(ParseNode)
    .edge(FetchNode, ParseNode)
    .group(
        "summarise",
        DAGBuilder("summarise-sub")
            .node(ChunkNode)
            .node(EmbedNode)
            .edge(ChunkNode, EmbedNode)
    )
    .edge(ParseNode, "summarise", label="parsed-output")
    .build()
)
```

`.node(NodeObj)` — registers a `Node` by its `.id`. Duplicate IDs raise.

`.edge()` — accepts Node objects or ID strings, with an optional label:
- `.edge(NodeA, NodeB)`
- `.edge("fetch", "parse")`
- `.edge(NodeA, NodeB, label="foo")`

`.visualize(output_configs)` — delegates to `DAGVisualizer`; can be called at any builder state before `.build()`.

### 2.5 `DAGVisualizer`

Standalone utility. Both `DAG` and `DAGBuilder` expose a `.visualize()` convenience pass-through that delegates here. Always renders the full topology, expanding `NodeGroup` internals.

```python
class DAGVisualizer:
    def __init__(self, dag: DAG): ...
    def render(self, format: Literal["terminal", "html", "image", "json"], **options) -> None: ...
```

---

## 3. Decision Log

| # | Topic | Decision |
|---|---|---|
| Q1 | `DAG` mutability | **Immutable after construction.** `DAG` exposes only traversal. `DAGBuilder` is the sole construction path. Post-build edits follow `DAGBuilder.from_dag(existing)...build()`. |
| Q2 | Node identity | **`id: str` is the canonical key.** `name` and `description` are human-readable. `metadata: dict` is available for upstream layers. Builder API is `.node(NodeObj)` — identity comes from the object. |
| Q3 | Edge metadata | **Plain edges with optional `label: str`.** Label is informational only — no effect on traversal or execution direction. Conditional routing is deferred to future `FlowNode` types. |
| Q4 | Sub-DAG nesting | **`NodeGroup` as a first-class node subtype.** Outer traversal stops at group boundaries by default. Traversal methods accept `cross_groups=True` to recurse. `visualize()` always renders the full topology. |
| Q5 | Validation ownership | **Builder validates; `DAG.validate_*` are public utilities.** Builder config flags drive construction-time checks. The builder may use `DAG` helpers internally or implement builder-exclusive logic. `DAG.validate_*` are available to all external consumers. |
| Q6 | `networkx` | **Removed as a dependency.** In-house engine. See Q10. |
| Q7 | Visualization location | **Standalone `DAGVisualizer`.** Both `DAG` and `DAGBuilder` provide `.visualize()` pass-throughs that delegate to it. |
| Q8 | `ExecutionPlatform` integration | **Deferred — standalone first.** The future Orchestrator will accept a `PlanDAG`, walk topology, manage state, inject inputs, store results, and delegate to `ExecutionPlatform`. |
| Q9 | `.edge()` auto-registration | **Explicit `.node()` required.** Nodes must be registered before appearing in `.edge()`. More verbose but explicit and predictable — important for human and machine readability alike. |
| Q10 | Graph engine | **In-house implementation; no `networkx`.** The following five textbook algorithms cover the full DAG API: |

| Algorithm | Method(s) | Technique | Complexity |
|---|---|---|---|
| **Entry/leaf by degree** | `entry_nodes`, `leaf_nodes`, `is_entry_node`, `is_leaf_node` | Single pass over adjacency: in-degree = 0 → entry; out-degree = 0 → leaf | O(V+E) |
| **DFS cycle detection** | `validate_acyclic`, `would_create_cycle` | DFS with three-colour marking (unvisited / in-stack / done); back-edge = cycle | O(V+E) |
| **Kahn's topological sort** | Internal ordering used by `next_nodes_from` and execution stage batching | BFS over in-degree counts; processes nodes with in-degree 0 first | O(V+E) |
| **DFS reachability / descendants** | `is_reachable`, `descendants_of` | Iterative DFS from source; optionally crosses `NodeGroup` boundaries when `cross_groups=True` | O(V+E) |
| **BFS shortest path** | `path_between` | Standard unweighted BFS; returns first path found | O(V+E) |

All five are stable, well-understood, and have no ambiguous edge cases for DAGs. The complete engine is expected to be ~150–200 lines.

---

## 4. Development Phases

The spec is complete and all design decisions are resolved. The following phases define the implementation order, each with its tests.

---

### Phase 1 — Data Models

**Scope:** `Node`, `NodeGroup`, `Edge`, `DAGBuilderConfig` — all as Pydantic `BaseModel` subclasses. No graph logic yet.

**Deliverables:**
- `Node(id, name, description, metadata)`
- `NodeGroup(Node)` with `inner: DAG` (forward reference; `DAG` is a stub at this stage)
- `Edge(source, target, label=None)`
- `DAGBuilderConfig` with all six flags

**Unit tests:**
- `Node` creation, field validation, default `metadata`
- Duplicate `id` detection is not needed here (that's builder logic), but confirm `id` is required
- `Edge` with and without `label`
- `DAGBuilderConfig` defaults match the spec table
- `Node` and `Edge` round-trip to/from JSON (Pydantic `.model_dump()` / `.model_validate()`)

---

### Phase 2 — In-house Graph Engine

**Scope:** Internal `_GraphEngine` (private module) implementing the five algorithms over a plain `dict[str, set[str]]` adjacency representation. No Pydantic, no public API.

**Deliverables:**
- `_GraphEngine(nodes: set[str], edges: set[tuple[str, str]])`
- `entry_nodes() -> set[str]`
- `leaf_nodes() -> set[str]`
- `has_cycle() -> bool`
- `would_create_cycle(source, target) -> bool`
- `topological_generations() -> list[set[str]]` — returns nodes grouped by execution stage
- `descendants_of(node_id) -> set[str]`
- `is_reachable(source, target) -> bool`
- `path_between(source, target) -> list[str] | None`

**Unit tests** (test against known graphs):
- Empty graph — entry/leaf both return empty set
- Linear chain `A → B → C` — entry = {A}, leaf = {C}, topological generations = [{A}, {B}, {C}]
- Diamond `A → B, A → C, B → D, C → D` — entry = {A}, leaf = {D}, two middle generations
- Graph with cycle — `has_cycle()` returns `True`; acyclic one returns `False`
- `would_create_cycle` — adding back-edge returns `True`; adding forward edge returns `False`
- `descendants_of` — full reachability from various nodes
- `is_reachable` — positive and negative cases
- `path_between` — connected and disconnected pairs

---

### Phase 3 — `DAG`

**Scope:** The immutable, read-only `DAG` class wrapping the graph engine. Full traversal API. JSON serialisation.

**Deliverables:**
- `DAG` constructed via internal factory (not public `__init__`); only `DAGBuilder` calls the factory
- All traversal methods from section 2.3
- `cross_groups=True` support on `descendants_of`
- `copy(deep=False)`
- Full Pydantic JSON round-trip for persistence/recovery
- `.visualize()` pass-through stub (raises `NotImplementedError` until Phase 5)

**Unit tests:**
- All traversal methods against a fixed test DAG
- `NodeGroup` boundary: `descendants_of` with `cross_groups=False` stops at group; `cross_groups=True` recurses
- `validate_acyclic` and `validate_connectedness` raise on violations
- `would_create_cycle` pre-flight
- `copy()` — shallow copy shares node objects; `copy(deep=True)` does not
- JSON round-trip: `dag.model_dump_json()` → reconstruct → traversal results identical
- `DAG` with nested `NodeGroup` survives JSON round-trip

**Integration test:**
- Build a multi-node DAG with a `NodeGroup`, serialise to JSON, deserialise, assert full topology is preserved

---

### Phase 4 — `DAGBuilder`

**Scope:** The fluent builder with config enforcement, duplicate-ID detection, and the `from_dag` continuation pattern.

**Deliverables:**
- `DAGBuilder(name, config=DAGBuilderConfig())`
- `.node(NodeObj)` — raises on duplicate `id`
- `.edge(a, b, label=None)` — both `Node` object and `str` ID forms; raises if either node is not registered
- `.group(group_node_id, inner_builder)` — registers a `NodeGroup`
- `.remove_node(id)` and `.remove_edge(a, b)` — raise when `append_only=True`
- `.build()` — applies all enabled validation flags, returns a `DAG`
- `DAGBuilder.from_dag(dag)` — seeds the builder with an existing DAG's nodes and edges
- `.visualize()` pass-through stub

**Unit tests:**
- Happy-path fluent chain produces expected `DAG`
- Duplicate `.node()` raises
- `.edge()` with unregistered ID raises
- `.edge()` with `Node` object that was not registered raises
- `append_only=True` blocks `.remove_node` / `.remove_edge`
- `validate_acyclic=True` (default) raises on `.edge()` that would create a cycle
- `allow_isolated_nodes=False` (default) raises at `.build()` if isolated node present
- `allow_self_loops=False` (default) raises on `.edge(A, A)`
- `allow_parallel_edges=False` (default) raises on duplicate `.edge(A, B)`
- `from_dag` round-trip: seed from existing DAG, add one node and edge, build, assert full topology

**Integration test:**
- Full builder chain with a nested `.group()`: assert outer and inner topologies are correct on the result

---

### Phase 5 — `DAGVisualizer`

**Scope:** Standalone visualizer with `terminal` and `json` formats. `html` and `image` formats are stubbed.

**Deliverables:**
- `DAGVisualizer(dag: DAG)`
- `.render(format, **options)` with `format: Literal["terminal", "html", "image", "json"]`
- `terminal` — ASCII/Unicode adjacency tree expanding `NodeGroup` internals
- `json` — structured dict representation of the full topology
- `html` and `image` — raise `NotImplementedError` with a clear message (deferred)
- `.visualize()` on `DAG` and `DAGBuilder` now fully wired (no longer stubs)

**Unit tests:**
- `json` format output contains all expected node IDs, edges, labels, and nested group topology
- `terminal` format output is a non-empty string containing all node IDs
- `html` and `image` raise `NotImplementedError`
- Visualizing a DAG with a `NodeGroup` expands the group's inner topology in both formats

---

## 5. Deferred

The following are confirmed future concerns, not in scope for the current implementation sprint:

- **Error types:** Validation failures should align with `errors.py` in the execution platform. To be specified when the first integration with the executor is built.
- **Node subtype hierarchy:** `TextNode`, `DataNode`, `FunctionNode`, `ToolNode`, `ForEachNode` live in the `cognitive/` layer and subclass `Node`. The DAG layer treats all nodes as opaque `Node` instances — the orchestrator resolves the concrete type at execution time.
- **`PlanDAG` layer:** A higher-level `PlanDAG` wraps a `DAG` and carries execution metadata (handler mappings, input/output schemas, policies). That is a separate spec.
- **`html` and `image` visualization:** Deferred to after Phase 5. Strategy (pure Python layout vs. optional `matplotlib`) to be decided then.

