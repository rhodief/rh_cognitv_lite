"""Phase 3 — Graph/DAG traversal class tests.

Graph fixtures
--------------
SIMPLE      a → b → c (linear chain)
DIAMOND     a → b, a → c, b → d, c → d
FORK        a → b, a → c (b and c are both leaves)
SINGLE      a (isolated node)
GROUPED     outer: grp → c where grp.inner = (a → b)
NESTED_GRP  outer: outer_grp → z where outer_grp.inner = (inner_grp → y)
            and inner_grp.inner = (x1 → x2)
MULTI_ENTRY a → c, b → c (a and b are both entries)
DISCONNECTED a → b, c (c is isolated — used for connectedness tests)
CYCLIC_SIMPLE  a → b → c → a (back-edge: c→a)
"""

from __future__ import annotations

import json

import pytest

from rh_cognitv_lite.orchestrators.graphs.models import DAG, Graph, Edge, Node, NodeGroup


# ── helpers ───────────────────────────────────────────────────────────────────

def node(id: str) -> Node:
    return Node(id=id, name=id.upper(), description="")


def edge(src: str, tgt: str, label: str | None = None) -> Edge:
    return Edge(source=src, target=tgt, label=label)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def simple():
    """a → b → c"""
    a, b, c = node("a"), node("b"), node("c")
    return DAG._from_parts([a, b, c], [edge("a", "b"), edge("b", "c")])


@pytest.fixture()
def diamond():
    """a → b, a → c, b → d, c → d"""
    a, b, c, d = node("a"), node("b"), node("c"), node("d")
    return DAG._from_parts(
        [a, b, c, d],
        [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")],
    )


@pytest.fixture()
def fork():
    """a → b, a → c"""
    a, b, c = node("a"), node("b"), node("c")
    return DAG._from_parts([a, b, c], [edge("a", "b"), edge("a", "c")])


@pytest.fixture()
def single():
    """Single isolated node."""
    return DAG._from_parts([node("a")], [])


@pytest.fixture()
def grouped():
    """outer: grp → c;  grp.inner = a → b"""
    a, b = node("a"), node("b")
    inner = DAG._from_parts([a, b], [edge("a", "b")])
    grp = NodeGroup(id="g", name="G", description="", inner=inner)
    c = node("c")
    return DAG._from_parts([grp, c], [edge("g", "c")])


@pytest.fixture()
def grp_node(grouped):
    return next(n for n in grouped.nodes_data if isinstance(n, NodeGroup))


@pytest.fixture()
def nested_grp():
    """
    outer_grp.inner → y  (outer level)
    outer_grp.inner contains inner_grp → y
    inner_grp.inner contains x1 → x2
    """
    x1, x2 = node("x1"), node("x2")
    inner_inner = DAG._from_parts([x1, x2], [edge("x1", "x2")])
    inner_grp = NodeGroup(id="ig", name="IG", description="", inner=inner_inner)
    y = node("y")
    inner_dag = DAG._from_parts([inner_grp, y], [edge("ig", "y")])
    outer_grp = NodeGroup(id="og", name="OG", description="", inner=inner_dag)
    z = node("z")
    return DAG._from_parts([outer_grp, z], [edge("og", "z")])


@pytest.fixture()
def multi_entry():
    """a → c, b → c"""
    a, b, c = node("a"), node("b"), node("c")
    return DAG._from_parts([a, b, c], [edge("a", "c"), edge("b", "c")])


@pytest.fixture()
def disconnected():
    """a → b, c (c isolated)"""
    a, b, c = node("a"), node("b"), node("c")
    return DAG._from_parts([a, b, c], [edge("a", "b")])


# ═════════════════════════════════════════════════════════════════════════════
class TestEntryAndLeafNodes:
    def test_simple_entry(self, simple):
        assert {n.id for n in simple.entry_nodes()} == {"a"}

    def test_simple_leaf(self, simple):
        assert {n.id for n in simple.leaf_nodes()} == {"c"}

    def test_diamond_entry(self, diamond):
        assert {n.id for n in diamond.entry_nodes()} == {"a"}

    def test_diamond_leaf(self, diamond):
        assert {n.id for n in diamond.leaf_nodes()} == {"d"}

    def test_fork_entry(self, fork):
        assert {n.id for n in fork.entry_nodes()} == {"a"}

    def test_fork_leaves(self, fork):
        assert {n.id for n in fork.leaf_nodes()} == {"b", "c"}

    def test_multi_entry_entries(self, multi_entry):
        assert {n.id for n in multi_entry.entry_nodes()} == {"a", "b"}

    def test_multi_entry_leaf(self, multi_entry):
        assert {n.id for n in multi_entry.leaf_nodes()} == {"c"}

    def test_single_is_both_entry_and_leaf(self, single):
        a = next(iter(single.nodes_data))
        assert single.is_entry_node(a)
        assert single.is_leaf_node(a)

    def test_is_entry_true(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        assert simple.is_entry_node(a) is True

    def test_is_entry_false(self, simple):
        b = next(n for n in simple.nodes_data if n.id == "b")
        assert simple.is_entry_node(b) is False

    def test_is_leaf_true(self, simple):
        c = next(n for n in simple.nodes_data if n.id == "c")
        assert simple.is_leaf_node(c) is True

    def test_is_leaf_false(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        assert simple.is_leaf_node(a) is False


# ═════════════════════════════════════════════════════════════════════════════
class TestNextAndPrevNodes:
    def test_next_from_none_returns_entries(self, simple):
        assert {n.id for n in simple.next_nodes_from(None)} == {"a"}

    def test_next_from_a(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        assert {n.id for n in simple.next_nodes_from(a)} == {"b"}

    def test_next_from_leaf_empty(self, simple):
        c = next(n for n in simple.nodes_data if n.id == "c")
        assert simple.next_nodes_from(c) == set()

    def test_next_from_diamond_a(self, diamond):
        a = next(n for n in diamond.nodes_data if n.id == "a")
        assert {n.id for n in diamond.next_nodes_from(a)} == {"b", "c"}

    def test_prev_from_c(self, simple):
        c = next(n for n in simple.nodes_data if n.id == "c")
        assert {n.id for n in simple.prev_nodes_from(c)} == {"b"}

    def test_prev_from_entry_empty(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        assert simple.prev_nodes_from(a) == set()

    def test_prev_from_diamond_d(self, diamond):
        d = next(n for n in diamond.nodes_data if n.id == "d")
        assert {n.id for n in diamond.prev_nodes_from(d)} == {"b", "c"}


# ═════════════════════════════════════════════════════════════════════════════
class TestDescendantsOf:
    def test_simple_from_a(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        assert {n.id for n in simple.descendants_of(a)} == {"b", "c"}

    def test_simple_from_b(self, simple):
        b = next(n for n in simple.nodes_data if n.id == "b")
        assert {n.id for n in simple.descendants_of(b)} == {"c"}

    def test_simple_from_leaf_empty(self, simple):
        c = next(n for n in simple.nodes_data if n.id == "c")
        assert simple.descendants_of(c) == set()

    def test_diamond_from_a(self, diamond):
        a = next(n for n in diamond.nodes_data if n.id == "a")
        assert {n.id for n in diamond.descendants_of(a)} == {"b", "c", "d"}

    # ── NodeGroup boundary (cross_groups=False) ───────────────────────────────

    def test_group_stops_at_boundary_by_default(self, grouped, grp_node):
        # descendants_of(grp) in outer DAG = {c}; inner nodes are NOT included
        result_ids = {n.id for n in grouped.descendants_of(grp_node)}
        assert result_ids == {"c"}

    def test_group_cross_groups_includes_inner(self, grouped, grp_node):
        result_ids = {n.id for n in grouped.descendants_of(grp_node, cross_groups=True)}
        assert result_ids == {"a", "b", "c"}

    def test_group_cross_groups_false_explicit(self, grouped, grp_node):
        result_ids = {n.id for n in grouped.descendants_of(grp_node, cross_groups=False)}
        assert result_ids == {"c"}

    def test_nested_group_cross_groups(self, nested_grp):
        og = next(n for n in nested_grp.nodes_data if n.id == "og")
        result_ids = {n.id for n in nested_grp.descendants_of(og, cross_groups=True)}
        # outer desc = {z}; og.inner has inner_grp + y; inner_grp.inner has x1, x2
        assert "z" in result_ids
        assert "y" in result_ids
        assert "x1" in result_ids
        assert "x2" in result_ids

    def test_nested_group_without_cross_groups(self, nested_grp):
        og = next(n for n in nested_grp.nodes_data if n.id == "og")
        result_ids = {n.id for n in nested_grp.descendants_of(og, cross_groups=False)}
        # only outer DAG descendants
        assert result_ids == {"z"}


# ═════════════════════════════════════════════════════════════════════════════
class TestReachabilityAndPath:
    def test_is_reachable_direct(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        b = next(n for n in simple.nodes_data if n.id == "b")
        assert simple.is_reachable(a, b) is True

    def test_is_reachable_transitive(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        c = next(n for n in simple.nodes_data if n.id == "c")
        assert simple.is_reachable(a, c) is True

    def test_is_not_reachable_reverse(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        c = next(n for n in simple.nodes_data if n.id == "c")
        assert simple.is_reachable(c, a) is False

    def test_path_between_direct(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        b = next(n for n in simple.nodes_data if n.id == "b")
        path = simple.path_between(a, b)
        assert path is not None
        assert [n.id for n in path] == ["a", "b"]

    def test_path_between_transitive(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        c = next(n for n in simple.nodes_data if n.id == "c")
        path = simple.path_between(a, c)
        assert path is not None
        assert [n.id for n in path] == ["a", "b", "c"]

    def test_path_between_none_when_unreachable(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        c = next(n for n in simple.nodes_data if n.id == "c")
        assert simple.path_between(c, a) is None

    def test_path_across_diamond(self, diamond):
        a = next(n for n in diamond.nodes_data if n.id == "a")
        d = next(n for n in diamond.nodes_data if n.id == "d")
        path = diamond.path_between(a, d)
        assert path is not None
        # BFS returns shortest — a → b → d or a → c → d (length 3 either way)
        assert len(path) == 3
        assert path[0].id == "a"
        assert path[-1].id == "d"


# ═════════════════════════════════════════════════════════════════════════════
class TestWouldCreateCycle:
    def test_no_cycle_simple(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        c = next(n for n in simple.nodes_data if n.id == "c")
        # c → a would close a → b → c → a
        assert simple.would_create_cycle(c, a) is True

    def test_safe_edge(self, fork):
        # Adding b → c doesn't close a cycle in the fork graph
        b = next(n for n in fork.nodes_data if n.id == "b")
        c = next(n for n in fork.nodes_data if n.id == "c")
        assert fork.would_create_cycle(b, c) is False

    def test_self_loop_creates_cycle(self, simple):
        a = next(n for n in simple.nodes_data if n.id == "a")
        assert simple.would_create_cycle(a, a) is True


# ═════════════════════════════════════════════════════════════════════════════
class TestValidateAcyclic:
    def test_validates_acyclic_dag(self, simple):
        simple.validate_acyclic()  # must not raise

    def test_diamond_acyclic(self, diamond):
        diamond.validate_acyclic()  # must not raise

    def test_raises_on_cycle(self):
        # Manually force a cycle through _from_parts (bypasses builder guards)
        a, b = node("a"), node("b")
        cyclic = DAG._from_parts([a, b], [edge("a", "b"), edge("b", "a")])
        with pytest.raises(ValueError, match="cycle"):
            cyclic.validate_acyclic()


# ═════════════════════════════════════════════════════════════════════════════
class TestValidateConnectedness:
    def test_connected_dag_ok(self, simple):
        simple.validate_connectedness()  # must not raise

    def test_single_node_ok(self, single):
        single.validate_connectedness()  # must not raise (vacuously connected)

    def test_empty_dag_ok(self):
        DAG._from_parts([], []).validate_connectedness()  # must not raise

    def test_raises_on_disconnected(self, disconnected):
        with pytest.raises(ValueError, match="not connected"):
            disconnected.validate_connectedness()


# ═════════════════════════════════════════════════════════════════════════════
class TestCopy:
    def test_shallow_copy_has_same_node_objects(self, simple):
        copy = simple.copy()
        for orig, copied in zip(simple.nodes_data, copy.nodes_data):
            assert orig is copied  # same object

    def test_deep_copy_has_independent_node_objects(self, simple):
        deep = simple.copy(deep=True)
        for orig, copied in zip(simple.nodes_data, deep.nodes_data):
            assert orig is not copied  # distinct objects

    def test_shallow_copy_traversal_identical(self, diamond):
        copy = diamond.copy()
        a = next(n for n in diamond.nodes_data if n.id == "a")
        orig_desc = {n.id for n in diamond.descendants_of(a)}
        a_copy = next(n for n in copy.nodes_data if n.id == "a")
        copy_desc = {n.id for n in copy.descendants_of(a_copy)}
        assert orig_desc == copy_desc

    def test_deep_copy_traversal_identical(self, diamond):
        deep = diamond.copy(deep=True)
        a = next(n for n in diamond.nodes_data if n.id == "a")
        orig_desc = {n.id for n in diamond.descendants_of(a)}
        a_deep = next(n for n in deep.nodes_data if n.id == "a")
        deep_desc = {n.id for n in deep.descendants_of(a_deep)}
        assert orig_desc == deep_desc

    def test_copy_does_not_affect_original(self, simple):
        orig_node_ids = {n.id for n in simple.nodes_data}
        _ = simple.copy()
        assert {n.id for n in simple.nodes_data} == orig_node_ids


# ═════════════════════════════════════════════════════════════════════════════
class TestVisualize:
    def test_visualize_terminal_runs(self, simple, capsys):
        simple.visualize()  # default → terminal; must not raise
        captured = capsys.readouterr()
        assert "a" in captured.out

    def test_visualize_json_runs(self, simple, capsys):
        simple.visualize("json")
        captured = capsys.readouterr()
        import json
        parsed = json.loads(captured.out)
        assert "nodes" in parsed


# ═════════════════════════════════════════════════════════════════════════════
class TestJSONRoundTrip:
    def test_simple_dag_roundtrip(self, simple):
        data = simple.model_dump_json()
        restored = DAG.model_validate_json(data)
        assert {n.id for n in restored.nodes_data} == {n.id for n in simple.nodes_data}
        assert len(restored.edges_data) == len(simple.edges_data)

    def test_traversal_after_roundtrip(self, simple):
        restored = DAG.model_validate_json(simple.model_dump_json())
        a = next(n for n in restored.nodes_data if n.id == "a")
        assert {n.id for n in restored.descendants_of(a)} == {"b", "c"}

    def test_diamond_roundtrip_topology_preserved(self, diamond):
        restored = DAG.model_validate_json(diamond.model_dump_json())
        a = next(n for n in restored.nodes_data if n.id == "a")
        assert {n.id for n in restored.entry_nodes()} == {"a"}
        assert {n.id for n in restored.leaf_nodes()} == {"d"}
        assert {n.id for n in restored.descendants_of(a)} == {"b", "c", "d"}

    def test_nodegroup_roundtrip(self, grouped):
        data = grouped.model_dump_json()
        restored = DAG.model_validate_json(data)
        grp = next(n for n in restored.nodes_data if isinstance(n, NodeGroup))
        assert grp.id == "g"
        inner_ids = {n.id for n in grp.inner.nodes_data}
        assert inner_ids == {"a", "b"}

    def test_nodegroup_traversal_after_roundtrip(self, grouped):
        restored = DAG.model_validate_json(grouped.model_dump_json())
        grp = next(n for n in restored.nodes_data if isinstance(n, NodeGroup))
        # outer traversal stops at group boundary
        assert {n.id for n in restored.descendants_of(grp)} == {"c"}
        # cross_groups expands inner nodes
        assert {n.id for n in restored.descendants_of(grp, cross_groups=True)} == {"a", "b", "c"}

    def test_nested_nodegroup_roundtrip(self, nested_grp):
        data = nested_grp.model_dump_json()
        restored = DAG.model_validate_json(data)
        og = next(n for n in restored.nodes_data if n.id == "og")
        assert isinstance(og, NodeGroup)
        inner_ig = next(n for n in og.inner.nodes_data if n.id == "ig")
        assert isinstance(inner_ig, NodeGroup)
        assert {n.id for n in inner_ig.inner.nodes_data} == {"x1", "x2"}

    def test_edge_label_preserved(self):
        a, b = node("a"), node("b")
        dag = DAG._from_parts([a, b], [Edge(source="a", target="b", label="my-label")])
        restored = DAG.model_validate_json(dag.model_dump_json())
        assert restored.edges_data[0].label == "my-label"


# ═════════════════════════════════════════════════════════════════════════════
class TestIntegration:
    """End-to-end scenarios combining multiple traversal operations."""

    def test_pipeline_orchestration(self):
        """Simulate a multi-stage pipeline expressed as a DAG and walk it
        step by step using next_nodes_from."""
        ingest = Node(id="ingest", name="Ingest", description="")
        transform = Node(id="transform", name="Transform", description="")
        validate = Node(id="validate", name="Validate", description="")
        load = Node(id="load", name="Load", description="")
        dag = DAG._from_parts(
            [ingest, transform, validate, load],
            [
                edge("ingest", "transform"),
                edge("transform", "validate"),
                edge("validate", "load"),
            ],
        )
        dag.validate_acyclic()
        dag.validate_connectedness()

        visited = []
        current = dag.next_nodes_from(None)  # entry nodes
        while current:
            assert len(current) == 1  # linear pipeline
            n = next(iter(current))
            visited.append(n.id)
            current = dag.next_nodes_from(n)

        assert visited == ["ingest", "transform", "validate", "load"]

    def test_grouped_pipeline_roundtrip_and_traversal(self):
        """Build a DAG with a NodeGroup, serialise it, deserialise it, and
        assert that both outer and inner traversal results are correct."""
        pre = Node(id="pre", name="Pre", description="")
        step1 = Node(id="s1", name="Step1", description="")
        step2 = Node(id="s2", name="Step2", description="")
        inner = DAG._from_parts([step1, step2], [edge("s1", "s2")])
        grp = NodeGroup(id="grp", name="Group", description="", inner=inner)
        post = Node(id="post", name="Post", description="")

        outer = DAG._from_parts([pre, grp, post], [edge("pre", "grp"), edge("grp", "post")])

        # Verify before round-trip
        assert {n.id for n in outer.entry_nodes()} == {"pre"}
        assert {n.id for n in outer.leaf_nodes()} == {"post"}
        desc_outer = {n.id for n in outer.descendants_of(pre)}
        assert desc_outer == {"grp", "post"}
        desc_cross = {n.id for n in outer.descendants_of(pre, cross_groups=True)}
        assert "s1" in desc_cross and "s2" in desc_cross

        # Round-trip
        restored = DAG.model_validate_json(outer.model_dump_json())
        r_pre = next(n for n in restored.nodes_data if n.id == "pre")
        r_grp = next(n for n in restored.nodes_data if n.id == "grp")
        assert isinstance(r_grp, NodeGroup)
        assert {n.id for n in restored.descendants_of(r_pre)} == {"grp", "post"}
        r_cross = {n.id for n in restored.descendants_of(r_pre, cross_groups=True)}
        assert r_cross == {"grp", "post", "s1", "s2"}
        assert {n.id for n in restored.descendants_of(r_grp, cross_groups=True)} == {"post", "s1", "s2"}

    def test_would_create_cycle_prevents_back_edge(self):
        """Demonstrate that would_create_cycle can be used to gate edge additions."""
        a, b, c = node("a"), node("b"), node("c")
        dag = DAG._from_parts([a, b, c], [edge("a", "b"), edge("b", "c")])

        # c → a would cycle
        assert dag.would_create_cycle(c, a) is True
        # a → c is a long forward edge — no cycle
        assert dag.would_create_cycle(a, c) is False


# ═════════════════════════════════════════════════════════════════════════════
# New Graph API tests (cyclic support, node_by_id, edges_from/to, render model)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def cyclic_simple():
    """a → b → c → a  (back-edge: c→a creates a cycle)"""
    a, b, c = node("a"), node("b"), node("c")
    return Graph._from_parts([a, b, c], [edge("a", "b"), edge("b", "c"), edge("c", "a")])


@pytest.fixture()
def self_loop():
    """a → a"""
    a = node("a")
    return Graph._from_parts([a], [edge("a", "a")])


# ─────────────────────────────────────────────────────────────────────────────
class TestHasCycleIsAcyclic:
    def test_acyclic_graph_has_no_cycle(self, simple):
        assert simple.has_cycle() is False

    def test_acyclic_graph_is_acyclic(self, simple):
        assert simple.is_acyclic() is True

    def test_cyclic_graph_has_cycle(self, cyclic_simple):
        assert cyclic_simple.has_cycle() is True

    def test_cyclic_graph_is_not_acyclic(self, cyclic_simple):
        assert cyclic_simple.is_acyclic() is False

    def test_self_loop_has_cycle(self, self_loop):
        assert self_loop.has_cycle() is True

    def test_diamond_is_acyclic(self, diamond):
        assert diamond.is_acyclic() is True

    def test_empty_graph_is_acyclic(self):
        g = Graph._from_parts([], [])
        assert g.is_acyclic() is True


# ─────────────────────────────────────────────────────────────────────────────
class TestCyclicGraphTraversal:
    def test_cyclic_graph_has_no_entry_nodes(self, cyclic_simple):
        # every node has a predecessor → no entry nodes
        assert cyclic_simple.entry_nodes() == set()

    def test_cyclic_graph_has_no_leaf_nodes(self, cyclic_simple):
        # every node has a successor → no leaf nodes
        assert cyclic_simple.leaf_nodes() == set()

    def test_cyclic_next_nodes(self, cyclic_simple):
        a = next(n for n in cyclic_simple.nodes_data if n.id == "a")
        assert {n.id for n in cyclic_simple.next_nodes_from(a)} == {"b"}

    def test_cyclic_prev_nodes(self, cyclic_simple):
        a = next(n for n in cyclic_simple.nodes_data if n.id == "a")
        assert {n.id for n in cyclic_simple.prev_nodes_from(a)} == {"c"}

    def test_cyclic_descendants_of_terminates(self, cyclic_simple):
        """descendants_of must terminate even in a cyclic graph."""
        a = next(n for n in cyclic_simple.nodes_data if n.id == "a")
        desc = {n.id for n in cyclic_simple.descendants_of(a)}
        # In a → b → c → a, all nodes are reachable from a (including a via cycle)
        assert "b" in desc
        assert "c" in desc

    def test_cyclic_path_between_terminates(self, cyclic_simple):
        a = next(n for n in cyclic_simple.nodes_data if n.id == "a")
        c = next(n for n in cyclic_simple.nodes_data if n.id == "c")
        path = cyclic_simple.path_between(a, c)
        assert path is not None
        assert path[0].id == "a"
        assert path[-1].id == "c"


# ─────────────────────────────────────────────────────────────────────────────
class TestNodeById:
    def test_node_by_id_returns_correct_node(self, simple):
        n = simple.node_by_id("b")
        assert n.id == "b"

    def test_node_by_id_raises_on_missing(self, simple):
        with pytest.raises(KeyError):
            simple.node_by_id("z")

    def test_nodes_by_ids_returns_all(self, diamond):
        nodes = diamond.nodes_by_ids({"a", "d"})
        assert {n.id for n in nodes} == {"a", "d"}

    def test_nodes_by_ids_empty_set(self, simple):
        assert len(simple.nodes_by_ids(set())) == 0

    def test_nodes_by_ids_raises_on_missing(self, simple):
        with pytest.raises(KeyError):
            simple.nodes_by_ids({"a", "z"})


# ─────────────────────────────────────────────────────────────────────────────
class TestEdgesFromTo:
    def test_edges_from_returns_outgoing(self, simple):
        a = simple.node_by_id("a")
        edges = simple.edges_from(a)
        assert len(edges) == 1
        assert edges[0].source == "a"
        assert edges[0].target == "b"

    def test_edges_from_leaf_is_empty(self, simple):
        c = simple.node_by_id("c")
        assert simple.edges_from(c) == []

    def test_edges_to_returns_incoming(self, simple):
        b = simple.node_by_id("b")
        edges = simple.edges_to(b)
        assert len(edges) == 1
        assert edges[0].source == "a"
        assert edges[0].target == "b"

    def test_edges_to_entry_is_empty(self, simple):
        a = simple.node_by_id("a")
        assert simple.edges_to(a) == []

    def test_edges_from_diamond_fork(self, diamond):
        a = diamond.node_by_id("a")
        targets = {e.target for e in diamond.edges_from(a)}
        assert targets == {"b", "c"}

    def test_edges_to_diamond_join(self, diamond):
        d = diamond.node_by_id("d")
        sources = {e.source for e in diamond.edges_to(d)}
        assert sources == {"b", "c"}

    def test_edges_from_with_label(self):
        a, b = node("a"), node("b")
        g = Graph._from_parts([a, b], [Edge(source="a", target="b", label="lbl")])
        edges = g.edges_from(a)
        assert edges[0].label == "lbl"


# ─────────────────────────────────────────────────────────────────────────────
class TestToRenderModel:
    def test_acyclic_model_is_not_cyclic(self, simple):
        model = simple.to_render_model()
        assert model.is_cyclic is False

    def test_cyclic_model_is_cyclic(self, cyclic_simple):
        model = cyclic_simple.to_render_model()
        assert model.is_cyclic is True

    def test_render_model_node_count(self, simple):
        model = simple.to_render_model()
        assert len(model.nodes) == 3

    def test_render_model_edge_count(self, simple):
        model = simple.to_render_model()
        assert len(model.edges) == 2

    def test_render_nodes_have_correct_ids(self, simple):
        model = simple.to_render_model()
        assert {rn.id for rn in model.nodes} == {"a", "b", "c"}

    def test_acyclic_nodes_not_in_cycle(self, simple):
        model = simple.to_render_model()
        assert all(not rn.in_cycle for rn in model.nodes)

    def test_cyclic_nodes_in_cycle(self, cyclic_simple):
        model = cyclic_simple.to_render_model()
        assert all(rn.in_cycle for rn in model.nodes)

    def test_acyclic_edges_not_back_edges(self, simple):
        model = simple.to_render_model()
        assert all(not re.is_back_edge for re in model.edges)

    def test_cyclic_has_back_edge(self, cyclic_simple):
        model = cyclic_simple.to_render_model()
        back = [re for re in model.edges if re.is_back_edge]
        assert len(back) == 1
        # The back-edge endpoints must both be cycle members
        cycle_ids = {"a", "b", "c"}
        assert back[0].source_id in cycle_ids
        assert back[0].target_id in cycle_ids

    def test_grouped_node_has_inner_model(self, grouped):
        model = grouped.to_render_model()
        grp_render = next(rn for rn in model.nodes if rn.id == "g")
        assert grp_render.is_group is True
        assert grp_render.inner is not None
        inner_ids = {rn.id for rn in grp_render.inner.nodes}
        assert inner_ids == {"a", "b"}

    def test_plain_node_has_no_inner(self, simple):
        model = simple.to_render_model()
        for rn in model.nodes:
            assert rn.inner is None
            assert rn.is_group is False
