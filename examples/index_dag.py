"""
DAG usage examples
==================
Run with:  python examples/index_dag.py

Covers:
  1. Linear chain          — basic builder API
  2. Diamond (fan-out/in)  — entry / leaf detection
  3. Fork                  — next_nodes_from / prev_nodes_from
  4. Traversal             — descendants_of, path_between, is_reachable
  5. NodeGroup             — hierarchical sub-DAGs
  6. Visualization         — terminal + JSON rendering
  7. Builder config        — validation flags
  8. Serialization         — JSON round-trip via Pydantic
"""

from __future__ import annotations

import json

from rh_cognitv_lite.orchestrator.dag import (
    DAG,
    DAGBuilder,
    DAGBuilderConfig,
    DAGVisualizer,
    Node,
    NodeGroup,
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

linear_dag = (
    DAGBuilder("linear-pipeline")
    .node(ingest)
    .node(transform)
    .node(export)
    .edge(ingest, transform)
    .edge(transform, export)
    .build()
)

print("Nodes:", [n.id for n in linear_dag.nodes_data])
print("Edges:", [(e.source, e.target) for e in linear_dag.edges_data])
print("Entry:", {n.id for n in linear_dag.entry_nodes()})
print("Leaf: ", {n.id for n in linear_dag.leaf_nodes()})


# ─────────────────────────────────────────────────────────────────────────────
# 2. Diamond (fan-out / fan-in):  source → [branch_a, branch_b] → sink
# ─────────────────────────────────────────────────────────────────────────────
sep("2. Diamond — source → [branch_a, branch_b] → sink")

source   = node("source",   "Source")
branch_a = node("branch_a", "Branch A")
branch_b = node("branch_b", "Branch B")
sink     = node("sink",     "Sink")

diamond_dag = (
    DAGBuilder("diamond")
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

print("Entry nodes:", {n.id for n in diamond_dag.entry_nodes()})
print("Leaf  nodes:", {n.id for n in diamond_dag.leaf_nodes()})
print("Successors of 'source':", {n.id for n in diamond_dag.next_nodes_from(source)})
print("Predecessors of 'sink':", {n.id for n in diamond_dag.prev_nodes_from(sink)})


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fork:  root → [left, right]  (both are leaves)
# ─────────────────────────────────────────────────────────────────────────────
sep("3. Fork — traversal step by step")

root  = node("root",  "Root")
left  = node("left",  "Left")
right = node("right", "Right")

fork_dag = (
    DAGBuilder("fork")
    .node(root)
    .node(left)
    .node(right)
    .edge(root, left)
    .edge(root, right)
    .build()
)

current = fork_dag.next_nodes_from()          # entry nodes (node=None)
print("Step 0 — entry:", {n.id for n in current})

for step, n_obj in enumerate(sorted(current, key=lambda x: x.id), start=1):
    nxt = fork_dag.next_nodes_from(n_obj)
    print(f"Step {step} from '{n_obj.id}':", {n.id for n in nxt} or "(leaf)")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Traversal — descendants, path, reachability
# ─────────────────────────────────────────────────────────────────────────────
sep("4. Traversal — descendants_of, path_between, is_reachable")

a = node("a"); b = node("b"); c = node("c"); d = node("d")

chain = (
    DAGBuilder("chain")
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
# 5. NodeGroup — hierarchical sub-DAGs
# ─────────────────────────────────────────────────────────────────────────────
sep("5. NodeGroup — nested / hierarchical DAGs")

# Inner sub-DAG:  parse → validate
parse    = node("parse",    "Parse")
validate = node("validate", "Validate")
inner_dag = (
    DAGBuilder("inner")
    .node(parse)
    .node(validate)
    .edge(parse, validate)
    .build()
)

# Outer DAG:  [parse→validate] → publish
preprocess = NodeGroup(
    id="preprocess",
    name="Preprocess",
    description="Parse then validate",
    inner=inner_dag,
)
publish = node("publish", "Publish")

outer_dag = (
    DAGBuilder("outer")
    .node(preprocess)
    .node(publish)
    .edge(preprocess, publish)
    .build()
)

print("Outer nodes:", [n.id for n in outer_dag.nodes_data])
print("Descendants of 'preprocess' (opaque):",
      {n.id for n in outer_dag.descendants_of(preprocess)})
print("Descendants of 'preprocess' (cross_groups=True):",
      {n.id for n in outer_dag.descendants_of(preprocess, cross_groups=True)})
print("Inner nodes of the group:", [n.id for n in preprocess.inner.nodes_data])


# ─────────────────────────────────────────────────────────────────────────────
# 6. Visualization — terminal + JSON
# ─────────────────────────────────────────────────────────────────────────────
sep("6. Visualization — terminal render")
outer_dag.visualize()                          # default: terminal

sep("6b. Visualization — JSON render")
outer_dag.visualize("json")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Builder config — custom validation flags
# ─────────────────────────────────────────────────────────────────────────────
sep("7. Builder config — allow_parallel_edges")

cfg = DAGBuilderConfig(allow_parallel_edges=True)
p = node("p"); q = node("q")
parallel_dag = (
    DAGBuilder(config=cfg)
    .node(p).node(q)
    .edge("p", "q", label="first")
    .edge("p", "q", label="second")   # allowed because of config
    .build()
)
print("Parallel edges:", [(e.source, e.target, e.label) for e in parallel_dag.edges_data])

sep("7b. Builder config — cycle detection (ValueError expected)")
try:
    (
        DAGBuilder()
        .node(node("x")).node(node("y")).node(node("z"))
        .edge("x", "y").edge("y", "z")
        .edge("z", "x")   # would create a cycle — raises immediately
        .build()
    )
except ValueError as exc:
    print(f"Caught expected error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Serialization — JSON round-trip via Pydantic
# ─────────────────────────────────────────────────────────────────────────────
sep("8. Serialization — JSON round-trip")

payload = linear_dag.model_dump_json(indent=2)
print("Serialised (first 300 chars):")
print(payload[:300], "...")

restored = DAG.model_validate_json(payload)
print("\nRestored entry nodes:", {n.id for n in restored.entry_nodes()})
print("Restored leaf  nodes:", {n.id for n in restored.leaf_nodes()})
assert {n.id for n in restored.entry_nodes()} == {n.id for n in linear_dag.entry_nodes()}
print("Round-trip OK")
