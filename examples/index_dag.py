"""
Graph module usage examples
===========================
Run with:  python examples/index_dag.py

Covers:
  1.  Linear chain           — basic GraphBuilder API
  2.  Diamond (fan-out/in)   — entry / leaf detection, edge labels
  3.  Fork                   — next_nodes_from / prev_nodes_from step-by-step
  4.  Traversal              — descendants_of, path_between, is_reachable
  5.  NodeGroup              — hierarchical sub-graphs
  6.  Cyclic graph           — building graphs with cycles
  7.  Cycle inspection       — has_cycle, is_acyclic, nodes_in_cycles
  8.  Node & edge lookup     — node_by_id, edges_from, edges_to
  9.  Render model           — to_render_model() introspection
  10. Adapter visualization  — GraphVisualizer + TerminalAdapter / JsonAdapter
  11. Custom adapter         — plug your own renderer
  12. Builder config         — validation flags (strict DAG vs permissive)
  13. Serialization          — JSON round-trip via Pydantic
  14. Backward compat        — DAG alias, DAGBuilder, DAGBuilderConfig
"""

from __future__ import annotations

import json

from rh_cognitv_lite.orchestrators.graphs.graph import (
    Edge,
    Graph,
    GraphBuilder,
    GraphBuilderConfig,
    GraphRenderModel,
    GraphVisualizer,
    JsonAdapter,
    Node,
    NodeGroup,
    TerminalAdapter,
)

# Backward-compat imports (still work, will be deprecated)
from rh_cognitv_lite.orchestrators.graphs.dag import (
    DAG,
    DAGBuilder,
    DAGBuilderConfig,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def node(id: str, name: str = "", description: str = "") -> Node:
    return Node(id=id, name=name or id.upper(), description=description)


def sep(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Linear chain:  ingest → transform → export
# ─────────────────────────────────────────────────────────────────────────────
sep("1. Linear chain — ingest → transform → export")

ingest    = node("ingest",    "Ingest",    "Load raw data")
transform = node("transform", "Transform", "Clean and normalise")
export    = node("export",    "Export",    "Write to destination")

linear = (
    GraphBuilder("linear-pipeline")
    .node(ingest)
    .node(transform)
    .node(export)
    .edge(ingest, transform)
    .edge(transform, export)
    .build()
)

print("Nodes:", [n.id for n in linear.nodes_data])
print("Edges:", [(e.source, e.target) for e in linear.edges_data])
print("Entry:", {n.id for n in linear.entry_nodes()})
print("Leaf: ", {n.id for n in linear.leaf_nodes()})
print("is_acyclic:", linear.is_acyclic())


# ─────────────────────────────────────────────────────────────────────────────
# 2. Diamond (fan-out / fan-in):  source → [branch_a, branch_b] → sink
# ─────────────────────────────────────────────────────────────────────────────
sep("2. Diamond — source → [branch_a, branch_b] → sink")

source   = node("source",   "Source")
branch_a = node("branch_a", "Branch A")
branch_b = node("branch_b", "Branch B")
sink     = node("sink",     "Sink")

diamond = (
    GraphBuilder("diamond")
    .node(source)
    .node(branch_a)
    .node(branch_b)
    .node(sink)
    .edge(source, branch_a, label="to-a")
    .edge(source, branch_b, label="to-b")
    .edge(branch_a, sink)
    .edge(branch_b, sink)
    .build()
)

print("Entry nodes:", {n.id for n in diamond.entry_nodes()})
print("Leaf  nodes:", {n.id for n in diamond.leaf_nodes()})
print("Successors of 'source':", {n.id for n in diamond.next_nodes_from(source)})
print("Predecessors of 'sink':", {n.id for n in diamond.prev_nodes_from(sink)})


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fork:  root → [left, right]  (both are leaves)
# ─────────────────────────────────────────────────────────────────────────────
sep("3. Fork — traversal step by step")

root  = node("root",  "Root")
left  = node("left",  "Left")
right = node("right", "Right")

fork = (
    GraphBuilder("fork")
    .node(root)
    .node(left)
    .node(right)
    .edge(root, left)
    .edge(root, right)
    .build()
)

current = fork.next_nodes_from()               # entry nodes (node=None)
print("Step 0 — entry:", {n.id for n in current})

for step, n_obj in enumerate(sorted(current, key=lambda x: x.id), start=1):
    nxt = fork.next_nodes_from(n_obj)
    print(f"Step {step} from '{n_obj.id}':", {n.id for n in nxt} or "(leaf)")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Traversal — descendants, path, reachability
# ─────────────────────────────────────────────────────────────────────────────
sep("4. Traversal — descendants_of, path_between, is_reachable")

a = node("a"); b = node("b"); c = node("c"); d = node("d")

chain = (
    GraphBuilder("chain")
    .node(a).node(b).node(c).node(d)
    .edge(a, b).edge(b, c).edge(c, d)
    .build()
)

print("All descendants of 'a':", {n.id for n in chain.descendants_of(a)})
print("Path a → d:", [n.id for n in (chain.path_between(a, d) or [])])
print("Path d → a:", chain.path_between(d, a))          # None (unreachable)
print("Is 'a' reachable from 'a' itself?", chain.is_reachable(a, a))
print("Is 'd' reachable from 'a'?", chain.is_reachable(a, d))
print("Would adding d→a create a cycle?", chain.would_create_cycle(d, a))


# ─────────────────────────────────────────────────────────────────────────────
# 5. NodeGroup — hierarchical sub-graphs
# ─────────────────────────────────────────────────────────────────────────────
sep("5. NodeGroup — nested / hierarchical graphs")

# Inner sub-graph:  parse → validate
parse    = node("parse",    "Parse")
validate = node("validate", "Validate")
inner = (
    GraphBuilder("inner")
    .node(parse)
    .node(validate)
    .edge(parse, validate)
    .build()
)

# Outer graph:  preprocess[parse→validate] → publish
preprocess = NodeGroup(
    id="preprocess",
    name="Preprocess",
    description="Parse then validate",
    inner=inner,
)
publish = node("publish", "Publish")

outer = (
    GraphBuilder("outer")
    .node(preprocess)
    .node(publish)
    .edge(preprocess, publish)
    .build()
)

print("Outer nodes:", [n.id for n in outer.nodes_data])
print("Descendants of 'preprocess' (opaque):",
      {n.id for n in outer.descendants_of(preprocess)})
print("Descendants of 'preprocess' (cross_groups=True):",
      {n.id for n in outer.descendants_of(preprocess, cross_groups=True)})
print("Inner nodes of the group:", [n.id for n in preprocess.inner.nodes_data])


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cyclic graph — graphs that contain cycles
# ─────────────────────────────────────────────────────────────────────────────
sep("6. Cyclic graph — retry loops, feedback edges")

# GraphBuilder defaults are permissive: cycles allowed, self-loops allowed,
# isolated nodes allowed.
fetch   = node("fetch",   "Fetch",   "Fetch data from API")
process = node("process", "Process", "Process the response")
decide  = node("decide",  "Decide",  "Success or retry?")

cyclic = (
    GraphBuilder("retry-loop")
    .node(fetch)
    .node(process)
    .node(decide)
    .edge(fetch, process)
    .edge(process, decide)
    .edge(decide, fetch, label="retry")     # back-edge creating a cycle
    .build()
)

print("Nodes:", [n.id for n in cyclic.nodes_data])
print("Edges:", [(e.source, e.target, e.label) for e in cyclic.edges_data])
print("has_cycle:", cyclic.has_cycle())
print("is_acyclic:", cyclic.is_acyclic())
print("Entry nodes:", {n.id for n in cyclic.entry_nodes()})   # empty — all have predecessors
print("Leaf  nodes:", {n.id for n in cyclic.leaf_nodes()})     # empty — all have successors

# Self-loop example
self_loop = (
    GraphBuilder("self-loop")
    .node(node("agent", "Agent"))
    .edge("agent", "agent", label="reflect")
    .build()
)
print("\nSelf-loop graph has_cycle:", self_loop.has_cycle())


# ─────────────────────────────────────────────────────────────────────────────
# 7. Cycle inspection — which nodes are in cycles?
# ─────────────────────────────────────────────────────────────────────────────
sep("7. Cycle inspection — render model cycle metadata")

model = cyclic.to_render_model()
print("is_cyclic:", model.is_cyclic)
for rn in model.nodes:
    print(f"  {rn.id}: in_cycle={rn.in_cycle}")
for re in model.edges:
    marker = " ← back-edge!" if re.is_back_edge else ""
    print(f"  {re.source_id} → {re.target_id}{marker}")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Node & edge lookup — node_by_id, edges_from, edges_to
# ─────────────────────────────────────────────────────────────────────────────
sep("8. Node & edge lookup")

src = diamond.node_by_id("source")
print(f"node_by_id('source'): {src.id} ({src.name})")

batch = diamond.nodes_by_ids({"branch_a", "branch_b"})
print(f"nodes_by_ids: {[n.id for n in batch]}")

out_edges = diamond.edges_from(src)
print(f"edges_from('source'): {[(e.target, e.label) for e in out_edges]}")

snk = diamond.node_by_id("sink")
in_edges = diamond.edges_to(snk)
print(f"edges_to('sink'): {[(e.source, e.label) for e in in_edges]}")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Render model — introspect the format-agnostic topology snapshot
# ─────────────────────────────────────────────────────────────────────────────
sep("9. Render model — to_render_model()")

model = outer.to_render_model()
print(f"is_cyclic: {model.is_cyclic}")
print(f"Nodes ({len(model.nodes)}):")
for rn in model.nodes:
    inner_info = f", inner={len(rn.inner.nodes)} nodes" if rn.inner else ""
    print(f"  {rn.id}: is_group={rn.is_group}{inner_info}")
print(f"Edges ({len(model.edges)}):")
for re in model.edges:
    print(f"  {re.source_id} → {re.target_id}")


# ─────────────────────────────────────────────────────────────────────────────
# 10. Adapter visualization — GraphVisualizer + TerminalAdapter / JsonAdapter
# ─────────────────────────────────────────────────────────────────────────────
sep("10a. Visualization — TerminalAdapter (acyclic graph)")
GraphVisualizer(TerminalAdapter()).render(outer)

sep("10b. Visualization — TerminalAdapter (cyclic graph — note [↺] markers)")
GraphVisualizer(TerminalAdapter()).render(cyclic)

sep("10c. Visualization — JsonAdapter")
GraphVisualizer(JsonAdapter(indent=2)).render(diamond)

# Convenience shorthand via Graph.visualize()
sep("10d. Convenience — graph.visualize('terminal')")
cyclic.visualize()

sep("10e. Convenience — graph.visualize('json')")
outer.visualize("json")


# ─────────────────────────────────────────────────────────────────────────────
# 11. Custom adapter — plug your own renderer
# ─────────────────────────────────────────────────────────────────────────────
sep("11. Custom adapter — no inheritance required")


class MarkdownAdapter:
    """Minimal example: renders a graph as a Markdown bullet list."""

    def render(self, model: GraphRenderModel) -> None:
        print("## Graph")
        print(f"- Cyclic: {model.is_cyclic}")
        print("### Nodes")
        for rn in model.nodes:
            tag = " **[cycle]**" if rn.in_cycle else ""
            print(f"- `{rn.id}` — {rn.name}{tag}")
        print("### Edges")
        for re in model.edges:
            label = f" ({re.label})" if re.label else ""
            back = " ↺" if re.is_back_edge else ""
            print(f"- `{re.source_id}` → `{re.target_id}`{label}{back}")


GraphVisualizer(MarkdownAdapter()).render(cyclic)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Builder config — validation flags (strict DAG vs permissive)
# ─────────────────────────────────────────────────────────────────────────────
sep("12a. Default GraphBuilderConfig — permissive")

cfg = GraphBuilderConfig()
print(f"  validate_acyclic  = {cfg.validate_acyclic}")
print(f"  allow_self_loops  = {cfg.allow_self_loops}")
print(f"  allow_isolated    = {cfg.allow_isolated_nodes}")
print(f"  allow_parallel    = {cfg.allow_parallel_edges}")

sep("12b. Strict config — enforce DAG constraints")
strict = GraphBuilderConfig(
    validate_acyclic=True,
    allow_self_loops=False,
    allow_isolated_nodes=False,
)
try:
    (
        GraphBuilder(config=strict)
        .node(node("x")).node(node("y")).node(node("z"))
        .edge("x", "y").edge("y", "z")
        .edge("z", "x")                 # back-edge → ValueError
    )
except ValueError as exc:
    print(f"Caught expected error: {exc}")

sep("12c. Parallel edges")
par_cfg = GraphBuilderConfig(allow_parallel_edges=True)
par = (
    GraphBuilder(config=par_cfg)
    .node(node("p")).node(node("q"))
    .edge("p", "q", label="first")
    .edge("p", "q", label="second")
    .build()
)
print("Parallel edges:", [(e.source, e.target, e.label) for e in par.edges_data])


# ─────────────────────────────────────────────────────────────────────────────
# 13. Serialization — JSON round-trip via Pydantic
# ─────────────────────────────────────────────────────────────────────────────
sep("13. Serialization — JSON round-trip")

payload = linear.model_dump_json(indent=2)
print("Serialised (first 300 chars):")
print(payload[:300], "...")

restored = Graph.model_validate_json(payload)
print("\nRestored entry nodes:", {n.id for n in restored.entry_nodes()})
print("Restored leaf  nodes:", {n.id for n in restored.leaf_nodes()})
assert {n.id for n in restored.entry_nodes()} == {n.id for n in linear.entry_nodes()}
print("Round-trip OK ✓")

# Cyclic graph round-trip
cyclic_payload = cyclic.model_dump_json()
cyclic_restored = Graph.model_validate_json(cyclic_payload)
assert cyclic_restored.has_cycle() is True
print("Cyclic round-trip OK ✓")


# ─────────────────────────────────────────────────────────────────────────────
# 14. Backward compat — DAG alias, DAGBuilder, DAGBuilderConfig
# ─────────────────────────────────────────────────────────────────────────────
sep("14. Backward compatibility — DAG / DAGBuilder still work")

dag = (
    DAGBuilder("compat-example")
    .node(node("s1"))
    .node(node("s2"))
    .edge("s1", "s2")
    .build()
)
print(f"isinstance(dag, DAG): {isinstance(dag, DAG)}")
print(f"isinstance(dag, Graph): {isinstance(dag, Graph)}")
print(f"DAG is Graph: {DAG is Graph}")

dag_cfg = DAGBuilderConfig()
print(f"\nDAGBuilderConfig defaults (strict):")
print(f"  validate_acyclic  = {dag_cfg.validate_acyclic}")
print(f"  allow_self_loops  = {dag_cfg.allow_self_loops}")
print(f"  allow_isolated    = {dag_cfg.allow_isolated_nodes}")

print("\n── All examples completed ──")
