"""Phase 4 — DAGBuilder tests.

All tests import exclusively from the public API (dag.py).
"""

from __future__ import annotations

import pytest

from rh_cognitv_lite.orchestrators.graphs.dag import (
    DAG,
    DAGBuilder,
    DAGBuilderConfig,
    Edge,
    Node,
    NodeGroup,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def n(id: str) -> Node:
    return Node(id=id, name=id.upper(), description="")


def grp(id: str, inner: DAG) -> NodeGroup:
    return NodeGroup(id=id, name=id.upper(), description="", inner=inner)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def linear_dag():
    """a → b → c built with DAGBuilder."""
    return (
        DAGBuilder("linear")
        .node(n("a"))
        .node(n("b"))
        .node(n("c"))
        .edge("a", "b")
        .edge("b", "c")
        .build()
    )


@pytest.fixture()
def diamond_dag():
    """a → b, a → c, b → d, c → d"""
    return (
        DAGBuilder("diamond")
        .node(n("a"))
        .node(n("b"))
        .node(n("c"))
        .node(n("d"))
        .edge("a", "b")
        .edge("a", "c")
        .edge("b", "d")
        .edge("c", "d")
        .build()
    )


# ═════════════════════════════════════════════════════════════════════════════
class TestHappyPath:
    def test_linear_node_ids(self, linear_dag):
        assert {n.id for n in linear_dag.nodes_data} == {"a", "b", "c"}

    def test_linear_edge_count(self, linear_dag):
        assert len(linear_dag.edges_data) == 2

    def test_linear_traversal(self, linear_dag):
        a = next(x for x in linear_dag.nodes_data if x.id == "a")
        assert {x.id for x in linear_dag.descendants_of(a)} == {"b", "c"}

    def test_diamond_topology(self, diamond_dag):
        assert {n.id for n in diamond_dag.entry_nodes()} == {"a"}
        assert {n.id for n in diamond_dag.leaf_nodes()} == {"d"}

    def test_node_objects_accepted(self):
        a, b = n("a"), n("b")
        dag = DAGBuilder().node(a).node(b).edge(a, b).build()
        assert {nd.id for nd in dag.nodes_data} == {"a", "b"}

    def test_edge_mixed_forms(self):
        """edge() accepts Node object as source and str as target."""
        a, b = n("a"), n("b")
        dag = DAGBuilder().node(a).node(b).edge(a, "b").build()
        assert len(dag.edges_data) == 1

    def test_edge_with_label(self):
        dag = (
            DAGBuilder()
            .node(n("x"))
            .node(n("y"))
            .edge("x", "y", label="step-output")
            .build()
        )
        assert dag.edges_data[0].label == "step-output"

    def test_default_config_is_applied(self):
        b = DAGBuilder()
        assert b._config == DAGBuilderConfig()

    def test_custom_config_stored(self):
        cfg = DAGBuilderConfig(append_only=True)
        b = DAGBuilder(config=cfg)
        assert b._config.append_only is True

    def test_returns_dag_instance(self, linear_dag):
        assert isinstance(linear_dag, DAG)


# ═════════════════════════════════════════════════════════════════════════════
class TestDuplicateNode:
    def test_duplicate_id_raises(self):
        b = DAGBuilder().node(n("a"))
        with pytest.raises(ValueError, match="already registered"):
            b.node(n("a"))

    def test_different_ids_ok(self):
        DAGBuilder().node(n("a")).node(n("b"))  # no raise


# ═════════════════════════════════════════════════════════════════════════════
class TestUnregisteredEdge:
    def test_unregistered_source_raises(self):
        b = DAGBuilder().node(n("b"))
        with pytest.raises(ValueError, match="not registered"):
            b.edge("a", "b")

    def test_unregistered_target_raises(self):
        b = DAGBuilder().node(n("a"))
        with pytest.raises(ValueError, match="not registered"):
            b.edge("a", "b")

    def test_unregistered_source_as_node_raises(self):
        a, b = n("a"), n("b")
        builder = DAGBuilder().node(b)
        with pytest.raises(ValueError, match="not registered"):
            builder.edge(a, b)

    def test_unregistered_target_as_node_raises(self):
        a, b = n("a"), n("b")
        builder = DAGBuilder().node(a)
        with pytest.raises(ValueError, match="not registered"):
            builder.edge(a, b)


# ═════════════════════════════════════════════════════════════════════════════
class TestSelfLoops:
    def test_self_loop_raises_by_default(self):
        b = DAGBuilder().node(n("a"))
        with pytest.raises(ValueError, match="Self-loop"):
            b.edge("a", "a")

    def test_self_loop_allowed_when_configured(self):
        cfg = DAGBuilderConfig(allow_self_loops=True, validate_acyclic=False)
        b = DAGBuilder(config=cfg).node(n("a"))
        b.edge("a", "a")  # no raise


# ═════════════════════════════════════════════════════════════════════════════
class TestParallelEdges:
    def test_parallel_edge_raises_by_default(self):
        b = DAGBuilder().node(n("a")).node(n("b")).edge("a", "b")
        with pytest.raises(ValueError, match="Parallel edge"):
            b.edge("a", "b")

    def test_parallel_edge_allowed_when_configured(self):
        cfg = DAGBuilderConfig(allow_parallel_edges=True)
        b = DAGBuilder(config=cfg).node(n("a")).node(n("b"))
        b.edge("a", "b").edge("a", "b")  # no raise


# ═════════════════════════════════════════════════════════════════════════════
class TestAcyclicValidation:
    def test_cycle_raises_on_edge(self):
        b = (
            DAGBuilder()
            .node(n("a"))
            .node(n("b"))
            .node(n("c"))
            .edge("a", "b")
            .edge("b", "c")
        )
        with pytest.raises(ValueError, match="cycle"):
            b.edge("c", "a")

    def test_cycle_disabled(self):
        cfg = DAGBuilderConfig(validate_acyclic=False)
        b = (
            DAGBuilder(config=cfg)
            .node(n("a"))
            .node(n("b"))
            .edge("a", "b")
            .edge("b", "a")  # cycle — but flag is off
        )
        # build() final acyclic check is also skipped
        dag = b.build()
        assert len(dag.edges_data) == 2

    def test_forward_edge_no_cycle(self):
        """Adding a → c in a → b → c is a forward edge, not a cycle."""
        b = (
            DAGBuilder()
            .node(n("a"))
            .node(n("b"))
            .node(n("c"))
            .edge("a", "b")
            .edge("b", "c")
            .edge("a", "c")  # forward edge — no raise
        )
        dag = b.build()
        assert len(dag.edges_data) == 3


# ═════════════════════════════════════════════════════════════════════════════
class TestIsolatedNodes:
    def test_isolated_node_raises_at_build(self):
        b = DAGBuilder().node(n("a")).node(n("b")).edge("a", "b").node(n("isolated"))
        with pytest.raises(ValueError, match="isolated"):
            b.build()

    def test_isolated_node_allowed_when_configured(self):
        cfg = DAGBuilderConfig(allow_isolated_nodes=True)
        dag = (
            DAGBuilder(config=cfg)
            .node(n("a"))
            .node(n("b"))
            .edge("a", "b")
            .node(n("orphan"))
            .build()
        )
        assert {x.id for x in dag.nodes_data} == {"a", "b", "orphan"}

    def test_single_node_no_edges_ok(self):
        """A single-node graph with no edges is not isolated by the spec rule."""
        dag = DAGBuilder().node(n("solo")).build()
        assert len(dag.nodes_data) == 1


# ═════════════════════════════════════════════════════════════════════════════
class TestAppendOnly:
    def test_remove_node_raises_when_append_only(self):
        cfg = DAGBuilderConfig(append_only=True)
        b = DAGBuilder(config=cfg).node(n("a"))
        with pytest.raises(ValueError, match="append_only"):
            b.remove_node("a")

    def test_remove_edge_raises_when_append_only(self):
        cfg = DAGBuilderConfig(append_only=True)
        b = DAGBuilder(config=cfg).node(n("a")).node(n("b")).edge("a", "b")
        with pytest.raises(ValueError, match="append_only"):
            b.remove_edge("a", "b")

    def test_node_and_edge_still_allowed_when_append_only(self):
        cfg = DAGBuilderConfig(append_only=True)
        dag = DAGBuilder(config=cfg).node(n("a")).node(n("b")).edge("a", "b").build()
        assert len(dag.nodes_data) == 2


# ═════════════════════════════════════════════════════════════════════════════
class TestRemoveNode:
    def test_remove_node_removes_from_result(self):
        b = (
            DAGBuilder()
            .node(n("a"))
            .node(n("b"))
            .node(n("c"))
            .edge("a", "b")
            .edge("b", "c")
            .remove_node("b")
        )
        # allow_isolated_nodes needed because a and c become isolated
        cfg = DAGBuilderConfig(allow_isolated_nodes=True)
        b._config = cfg
        dag = b.build()
        assert {x.id for x in dag.nodes_data} == {"a", "c"}

    def test_remove_node_also_removes_incident_edges(self):
        cfg = DAGBuilderConfig(allow_isolated_nodes=True)
        b = (
            DAGBuilder(config=cfg)
            .node(n("a"))
            .node(n("b"))
            .node(n("c"))
            .edge("a", "b")
            .edge("b", "c")
            .remove_node("b")
        )
        dag = b.build()
        assert dag.edges_data == []

    def test_remove_nonexistent_node_raises(self):
        b = DAGBuilder().node(n("a"))
        with pytest.raises(ValueError, match="No node"):
            b.remove_node("z")


# ═════════════════════════════════════════════════════════════════════════════
class TestRemoveEdge:
    def test_remove_edge_removes_from_result(self):
        cfg = DAGBuilderConfig(allow_isolated_nodes=True)
        dag = (
            DAGBuilder(config=cfg)
            .node(n("a"))
            .node(n("b"))
            .edge("a", "b")
            .remove_edge("a", "b")
            .build()
        )
        assert dag.edges_data == []

    def test_remove_edge_accepts_node_objects(self):
        a, b = n("a"), n("b")
        cfg = DAGBuilderConfig(allow_isolated_nodes=True)
        dag = (
            DAGBuilder(config=cfg)
            .node(a)
            .node(b)
            .edge(a, b)
            .remove_edge(a, b)
            .build()
        )
        assert dag.edges_data == []

    def test_remove_nonexistent_edge_raises(self):
        b = DAGBuilder().node(n("a")).node(n("b"))
        with pytest.raises(ValueError, match="does not exist"):
            b.remove_edge("a", "b")


# ═════════════════════════════════════════════════════════════════════════════
class TestGroup:
    def test_group_registers_as_node_group(self):
        inner_dag = DAGBuilder().node(n("x")).node(n("y")).edge("x", "y").build()
        g = grp("g", inner_dag)
        outer = DAGBuilder().node(g).node(n("z")).edge("g", "z").build()
        grp_node = next(nd for nd in outer.nodes_data if nd.id == "g")
        assert isinstance(grp_node, NodeGroup)

    def test_group_inner_dag_preserved(self):
        inner_dag = DAGBuilder().node(n("x")).node(n("y")).edge("x", "y").build()
        g = grp("g", inner_dag)
        outer = DAGBuilder().node(g).node(n("z")).edge("g", "z").build()
        grp_node = next(nd for nd in outer.nodes_data if nd.id == "g")
        assert {i.id for i in grp_node.inner.nodes_data} == {"x", "y"}

    def test_group_method_requires_nodegroup(self):
        b = DAGBuilder()
        with pytest.raises(TypeError, match="NodeGroup"):
            b.group(n("not-a-group"))  # type: ignore[arg-type]

    def test_group_duplicate_id_raises(self):
        inner_dag = DAGBuilder().node(n("x")).node(n("y")).edge("x", "y").build()
        g = grp("g", inner_dag)
        b = DAGBuilder().node(g)
        with pytest.raises(ValueError, match="already registered"):
            b.group(g)

    def test_cross_groups_traversal_via_builder(self):
        inner_dag = DAGBuilder().node(n("a")).node(n("b")).edge("a", "b").build()
        g = grp("g", inner_dag)
        outer = DAGBuilder().node(g).node(n("c")).edge("g", "c").build()
        grp_node = next(nd for nd in outer.nodes_data if nd.id == "g")
        result = {x.id for x in outer.descendants_of(grp_node, cross_groups=True)}
        assert result == {"a", "b", "c"}


# ═════════════════════════════════════════════════════════════════════════════
class TestFromDag:
    def test_seeds_nodes_from_existing_dag(self, linear_dag):
        b = DAGBuilder.from_dag(linear_dag)
        assert {n.id for n in b._nodes} == {"a", "b", "c"}

    def test_seeds_edges_from_existing_dag(self, linear_dag):
        b = DAGBuilder.from_dag(linear_dag)
        assert len(b._edges) == 2

    def test_add_node_and_edge_after_seeding(self, linear_dag):
        # c → d: extend the linear chain
        dag = (
            DAGBuilder.from_dag(linear_dag)
            .node(n("d"))
            .edge("c", "d")
            .build()
        )
        assert {x.id for x in dag.nodes_data} == {"a", "b", "c", "d"}
        a = next(x for x in dag.nodes_data if x.id == "a")
        assert {x.id for x in dag.descendants_of(a)} == {"b", "c", "d"}

    def test_from_dag_does_not_mutate_original(self, linear_dag):
        original_node_count = len(linear_dag.nodes_data)
        DAGBuilder.from_dag(linear_dag).node(n("d")).edge("c", "d").build()
        assert len(linear_dag.nodes_data) == original_node_count

    def test_from_dag_with_custom_config(self, linear_dag):
        cfg = DAGBuilderConfig(allow_isolated_nodes=True)
        b = DAGBuilder.from_dag(linear_dag, name="extended", config=cfg)
        assert b._config.allow_isolated_nodes is True

    def test_from_dag_cycle_still_detected(self, linear_dag):
        """Adding a back edge via from_dag should still be caught."""
        b = DAGBuilder.from_dag(linear_dag)
        with pytest.raises(ValueError, match="cycle"):
            b.edge("c", "a")


# ═════════════════════════════════════════════════════════════════════════════
class TestVisualize:
    def test_visualize_terminal_runs(self, linear_dag, capsys):
        b = DAGBuilder.from_dag(linear_dag)
        b.visualize()  # default → terminal; must not raise
        captured = capsys.readouterr()
        assert "a" in captured.out

    def test_visualize_json_runs(self, linear_dag, capsys):
        b = DAGBuilder.from_dag(linear_dag)
        b.visualize("json")
        captured = capsys.readouterr()
        import json
        parsed = json.loads(captured.out)
        assert "nodes" in parsed


# ═════════════════════════════════════════════════════════════════════════════
class TestValidateConnected:
    def test_connected_flag_raises_on_disconnected_build(self):
        cfg = DAGBuilderConfig(validate_connected=True, allow_isolated_nodes=True)
        b = (
            DAGBuilder(config=cfg)
            .node(n("a"))
            .node(n("b"))
            .node(n("orphan"))
            .edge("a", "b")
        )
        with pytest.raises(ValueError, match="not connected"):
            b.build()

    def test_connected_flag_passes_for_connected_dag(self):
        cfg = DAGBuilderConfig(validate_connected=True)
        dag = (
            DAGBuilder(config=cfg)
            .node(n("a"))
            .node(n("b"))
            .node(n("c"))
            .edge("a", "b")
            .edge("b", "c")
            .build()
        )
        assert {x.id for x in dag.nodes_data} == {"a", "b", "c"}


# ═════════════════════════════════════════════════════════════════════════════
class TestIntegration:
    def test_full_chain_with_nested_group(self):
        """Full builder chain with a nested .group(); assert outer and inner
        topologies are correct on the result."""
        fetch = Node(id="fetch", name="Fetch", description="")
        parse = Node(id="parse", name="Parse", description="")
        chunk = Node(id="chunk", name="Chunk", description="")
        embed = Node(id="embed", name="Embed", description="")
        output = Node(id="output", name="Output", description="")

        inner_dag = (
            DAGBuilder("summarise-sub")
            .node(chunk)
            .node(embed)
            .edge(chunk, embed)
            .build()
        )
        summarise_grp = NodeGroup(
            id="summarise", name="Summarise", description="", inner=inner_dag
        )

        dag = (
            DAGBuilder("plan")
            .node(fetch)
            .node(parse)
            .group(summarise_grp)
            .node(output)
            .edge(fetch, parse)
            .edge(parse, "summarise", label="parsed-output")
            .edge("summarise", output)
            .build()
        )

        # Outer topology
        assert {x.id for x in dag.entry_nodes()} == {"fetch"}
        assert {x.id for x in dag.leaf_nodes()} == {"output"}

        fetch_node = next(x for x in dag.nodes_data if x.id == "fetch")
        outer_desc = {x.id for x in dag.descendants_of(fetch_node)}
        assert outer_desc == {"parse", "summarise", "output"}

        # cross_groups includes inner nodes
        cross_desc = {x.id for x in dag.descendants_of(fetch_node, cross_groups=True)}
        assert "chunk" in cross_desc and "embed" in cross_desc

        # Inner topology of the group
        grp_node = next(x for x in dag.nodes_data if x.id == "summarise")
        assert isinstance(grp_node, NodeGroup)
        assert {x.id for x in grp_node.inner.entry_nodes()} == {"chunk"}
        assert {x.id for x in grp_node.inner.leaf_nodes()} == {"embed"}

        # Edge labels preserved
        parse_to_grp = next(
            e for e in dag.edges_data
            if e.source == "parse" and e.target == "summarise"
        )
        assert parse_to_grp.label == "parsed-output"

    def test_from_dag_round_trip_topology(self, diamond_dag):
        """Seed from a diamond DAG, add an extra node, verify full topology."""
        e_node = Node(id="e", name="E", description="")
        extended = (
            DAGBuilder.from_dag(diamond_dag)
            .node(e_node)
            .edge("d", "e")
            .build()
        )
        assert {x.id for x in extended.entry_nodes()} == {"a"}
        assert {x.id for x in extended.leaf_nodes()} == {"e"}
        a = next(x for x in extended.nodes_data if x.id == "a")
        assert {x.id for x in extended.descendants_of(a)} == {"b", "c", "d", "e"}
