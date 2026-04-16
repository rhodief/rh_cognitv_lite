"""Phase 5 — Visualizer tests.

Covers both the legacy DAGVisualizer shim and the new adapter-based
GraphVisualizer / TerminalAdapter / JsonAdapter API.
"""

from __future__ import annotations

import json

import pytest

from rh_cognitv_lite.orchestrators.graphs.dag import (
    DAG,
    DAGBuilder,
    DAGBuilderConfig,
    DAGVisualizer,
    Node,
    NodeGroup,
)
from rh_cognitv_lite.orchestrators.graphs.graph import (
    Graph,
    GraphBuilder,
    GraphBuilderConfig,
    GraphVisualizer,
    GraphRenderModel,
    HtmlAdapter,
    ImageAdapter,
    JsonAdapter,
    TerminalAdapter,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def n(id: str, name: str | None = None) -> Node:
    return Node(id=id, name=name or id.upper(), description="")


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def linear_dag():
    return (
        DAGBuilder()
        .node(n("a"))
        .node(n("b"))
        .node(n("c"))
        .edge("a", "b")
        .edge("b", "c")
        .build()
    )


@pytest.fixture()
def grouped_dag():
    """outer: start → grp → end;  grp.inner = p → q"""
    inner = DAGBuilder().node(n("p")).node(n("q")).edge("p", "q").build()
    grp = NodeGroup(id="grp", name="Group", description="", inner=inner)
    return (
        DAGBuilder()
        .node(n("start"))
        .node(grp)
        .node(n("end"))
        .edge("start", "grp")
        .edge("grp", "end")
        .build()
    )


@pytest.fixture()
def nested_dag():
    """Two levels of nesting: outer_grp.inner contains inner_grp."""
    inner_inner = DAGBuilder().node(n("x")).node(n("y")).edge("x", "y").build()
    inner_grp = NodeGroup(id="ig", name="IG", description="", inner=inner_inner)
    inner_dag = (
        DAGBuilder()
        .node(inner_grp)
        .node(n("z"))
        .edge("ig", "z")
        .build()
    )
    outer_grp = NodeGroup(id="og", name="OG", description="", inner=inner_dag)
    return (
        DAGBuilder()
        .node(outer_grp)
        .node(n("final"))
        .edge("og", "final")
        .build()
    )


# ═════════════════════════════════════════════════════════════════════════════
class TestConstructor:
    def test_accepts_dag(self, linear_dag):
        viz = DAGVisualizer(linear_dag)
        assert viz._dag is linear_dag


# ═════════════════════════════════════════════════════════════════════════════
class TestUnsupportedFormats:
    def test_html_raises_not_implemented(self, linear_dag):
        viz = DAGVisualizer(linear_dag)
        with pytest.raises(NotImplementedError):
            viz.render("html")

    def test_image_raises_not_implemented(self, linear_dag):
        viz = DAGVisualizer(linear_dag)
        with pytest.raises(NotImplementedError):
            viz.render("image")

    def test_unknown_format_raises_value_error(self, linear_dag):
        viz = DAGVisualizer(linear_dag)
        with pytest.raises(ValueError, match="Unknown format"):
            viz.render("svg")  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
class TestTerminalFormat:
    def test_returns_non_empty_string(self, linear_dag, capsys):
        DAGVisualizer(linear_dag).render("terminal")
        captured = capsys.readouterr()
        assert captured.out.strip()

    def test_contains_all_node_ids(self, linear_dag, capsys):
        DAGVisualizer(linear_dag).render("terminal")
        output = capsys.readouterr().out
        for id_ in ("a", "b", "c"):
            assert id_ in output

    def test_contains_group_node_id(self, grouped_dag, capsys):
        DAGVisualizer(grouped_dag).render("terminal")
        output = capsys.readouterr().out
        assert "grp" in output

    def test_expands_group_inner_nodes(self, grouped_dag, capsys):
        DAGVisualizer(grouped_dag).render("terminal")
        output = capsys.readouterr().out
        assert "p" in output
        assert "q" in output

    def test_deeply_nested_inner_nodes_present(self, nested_dag, capsys):
        DAGVisualizer(nested_dag).render("terminal")
        output = capsys.readouterr().out
        for id_ in ("og", "ig", "x", "y", "z", "final"):
            assert id_ in output

    def test_group_tag_appears(self, grouped_dag, capsys):
        DAGVisualizer(grouped_dag).render("terminal")
        output = capsys.readouterr().out
        assert "[Group]" in output

    def test_node_tag_appears(self, linear_dag, capsys):
        DAGVisualizer(linear_dag).render("terminal")
        output = capsys.readouterr().out
        assert "[Node]" in output

    def test_render_prints_to_stdout(self, linear_dag, capsys):
        DAGVisualizer(linear_dag).render("terminal")
        captured = capsys.readouterr()
        assert "a" in captured.out
        assert "b" in captured.out
        assert "c" in captured.out


# ═════════════════════════════════════════════════════════════════════════════
class TestJSONFormat:
    def _json(self, dag, capsys, **opts) -> dict:
        DAGVisualizer(dag).render("json", **opts)
        return json.loads(capsys.readouterr().out)

    def test_json_output_is_valid_dict(self, linear_dag, capsys):
        result = self._json(linear_dag, capsys)
        assert isinstance(result, dict)

    def test_json_has_nodes_and_edges_keys(self, linear_dag, capsys):
        result = self._json(linear_dag, capsys)
        assert "nodes" in result and "edges" in result

    def test_json_contains_all_node_ids(self, linear_dag, capsys):
        result = self._json(linear_dag, capsys)
        ids = {node["id"] for node in result["nodes"]}
        assert ids == {"a", "b", "c"}

    def test_json_contains_edges(self, linear_dag, capsys):
        result = self._json(linear_dag, capsys)
        pairs = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("a", "b") in pairs
        assert ("b", "c") in pairs

    def test_json_edge_label_included(self, capsys):
        a, b = n("a"), n("b")
        dag = DAGBuilder().node(a).node(b).edge("a", "b", label="my-label").build()
        result = self._json(dag, capsys)
        edge = next(e for e in result["edges"] if e["source"] == "a")
        assert edge["label"] == "my-label"

    def test_json_group_node_has_inner_key(self, grouped_dag, capsys):
        result = self._json(grouped_dag, capsys)
        grp_entry = next(node for node in result["nodes"] if node["id"] == "grp")
        assert "inner" in grp_entry

    def test_json_group_inner_contains_nodes(self, grouped_dag, capsys):
        result = self._json(grouped_dag, capsys)
        grp_entry = next(node for node in result["nodes"] if node["id"] == "grp")
        inner_ids = {nd["id"] for nd in grp_entry["inner"]["nodes"]}
        assert inner_ids == {"p", "q"}

    def test_json_group_inner_contains_edges(self, grouped_dag, capsys):
        result = self._json(grouped_dag, capsys)
        grp_entry = next(node for node in result["nodes"] if node["id"] == "grp")
        inner_pairs = {
            (e["source"], e["target"]) for e in grp_entry["inner"]["edges"]
        }
        assert ("p", "q") in inner_pairs

    def test_json_plain_node_has_no_inner_key(self, grouped_dag, capsys):
        result = self._json(grouped_dag, capsys)
        start = next(node for node in result["nodes"] if node["id"] == "start")
        assert "inner" not in start

    def test_json_nested_group_topology(self, nested_dag, capsys):
        result = self._json(nested_dag, capsys)
        og = next(node for node in result["nodes"] if node["id"] == "og")
        ig = next(node for node in og["inner"]["nodes"] if node["id"] == "ig")
        assert "inner" in ig
        inner_ids = {nd["id"] for nd in ig["inner"]["nodes"]}
        assert inner_ids == {"x", "y"}

    def test_json_render_prints_to_stdout(self, linear_dag, capsys):
        DAGVisualizer(linear_dag).render("json")
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "nodes" in parsed

    def test_json_render_with_indent_option(self, linear_dag, capsys):
        DAGVisualizer(linear_dag).render("json", indent=4)
        captured = capsys.readouterr()
        assert "    " in captured.out

    def test_json_metadata_included(self, capsys):
        node_with_meta = Node(
            id="m", name="M", description="",
            metadata={"key": "value", "num": 42}
        )
        dag = DAGBuilder(config=DAGBuilderConfig(allow_isolated_nodes=True)).node(node_with_meta).build()
        result = self._json(dag, capsys)
        m_entry = result["nodes"][0]
        assert m_entry["metadata"] == {"key": "value", "num": 42}


# ═════════════════════════════════════════════════════════════════════════════
class TestDAGVisualizPassthrough:
    def test_dag_visualize_terminal(self, linear_dag, capsys):
        linear_dag.visualize()          # default → terminal
        captured = capsys.readouterr()
        assert "a" in captured.out

    def test_dag_visualize_string_format(self, linear_dag, capsys):
        linear_dag.visualize("json")
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "nodes" in parsed

    def test_dag_visualize_json_with_indent(self, linear_dag, capsys):
        linear_dag.visualize("json", indent=2)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "nodes" in parsed

    def test_dag_visualize_html_raises(self, linear_dag):
        with pytest.raises(NotImplementedError):
            linear_dag.visualize("html")

    def test_dag_visualize_image_raises(self, linear_dag):
        with pytest.raises(NotImplementedError):
            linear_dag.visualize("image")


# ═════════════════════════════════════════════════════════════════════════════
class TestBuilderVisualizPassthrough:
    def test_builder_visualize_terminal(self, capsys):
        b = DAGBuilder().node(n("a")).node(n("b")).edge("a", "b")
        b.visualize()
        captured = capsys.readouterr()
        assert "a" in captured.out
        assert "b" in captured.out

    def test_builder_visualize_json(self, capsys):
        b = DAGBuilder().node(n("x")).node(n("y")).edge("x", "y")
        b.visualize("json")
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        ids = {nd["id"] for nd in parsed["nodes"]}
        assert ids == {"x", "y"}

    def test_builder_visualize_html_raises(self):
        b = DAGBuilder().node(n("a")).node(n("b")).edge("a", "b")
        with pytest.raises(NotImplementedError):
            b.visualize("html")


# =============================================================================
# GraphVisualizer adapter-pattern tests
# =============================================================================

def gn(id: str) -> Node:
    return Node(id=id, name=id.upper(), description="")


@pytest.fixture()
def acyclic_graph():
    return (
        GraphBuilder()
        .node(gn("a"))
        .node(gn("b"))
        .node(gn("c"))
        .edge("a", "b")
        .edge("b", "c")
        .build()
    )


@pytest.fixture()
def cyclic_graph():
    """a → b → c → a"""
    return (
        GraphBuilder()
        .node(gn("a"))
        .node(gn("b"))
        .node(gn("c"))
        .edge("a", "b")
        .edge("b", "c")
        .edge("c", "a")
        .build()
    )


@pytest.fixture()
def grouped_graph():
    inner = GraphBuilder().node(gn("p")).node(gn("q")).edge("p", "q").build()
    grp = NodeGroup(id="grp", name="Group", description="", inner=inner)
    return (
        GraphBuilder()
        .node(gn("start"))
        .node(grp)
        .node(gn("end"))
        .edge("start", "grp")
        .edge("grp", "end")
        .build()
    )


# ─────────────────────────────────────────────────────────────────────────────
class TestGraphVisualizerTerminalAdapter:
    def test_terminal_adapter_runs(self, acyclic_graph, capsys):
        viz = GraphVisualizer(TerminalAdapter())
        viz.render(acyclic_graph)
        captured = capsys.readouterr()
        assert "a" in captured.out

    def test_terminal_output_contains_all_nodes(self, acyclic_graph, capsys):
        GraphVisualizer(TerminalAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        for id_ in ("a", "b", "c"):
            assert id_ in captured.out

    def test_terminal_cyclic_shows_cycle_marker(self, cyclic_graph, capsys):
        GraphVisualizer(TerminalAdapter()).render(cyclic_graph)
        captured = capsys.readouterr()
        assert "↺" in captured.out

    def test_terminal_acyclic_no_cycle_marker(self, acyclic_graph, capsys):
        GraphVisualizer(TerminalAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        assert "↺" not in captured.out

    def test_terminal_grouped_shows_inner_nodes(self, grouped_graph, capsys):
        GraphVisualizer(TerminalAdapter()).render(grouped_graph)
        captured = capsys.readouterr()
        assert "p" in captured.out
        assert "q" in captured.out

    def test_terminal_node_tag_present(self, acyclic_graph, capsys):
        GraphVisualizer(TerminalAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        assert "[Node]" in captured.out

    def test_terminal_group_tag_present(self, grouped_graph, capsys):
        GraphVisualizer(TerminalAdapter()).render(grouped_graph)
        captured = capsys.readouterr()
        assert "[Group]" in captured.out


# ─────────────────────────────────────────────────────────────────────────────
class TestGraphVisualizerJsonAdapter:
    def test_json_adapter_runs(self, acyclic_graph, capsys):
        GraphVisualizer(JsonAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "nodes" in parsed

    def test_json_contains_edges(self, acyclic_graph, capsys):
        GraphVisualizer(JsonAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "edges" in parsed

    def test_json_node_ids(self, acyclic_graph, capsys):
        GraphVisualizer(JsonAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        ids = {nd["id"] for nd in parsed["nodes"]}
        assert ids == {"a", "b", "c"}

    def test_json_cyclic_flag(self, cyclic_graph, capsys):
        GraphVisualizer(JsonAdapter()).render(cyclic_graph)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["is_cyclic"] is True

    def test_json_acyclic_flag(self, acyclic_graph, capsys):
        GraphVisualizer(JsonAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["is_cyclic"] is False

    def test_json_custom_indent(self, acyclic_graph, capsys):
        GraphVisualizer(JsonAdapter(indent=4)).render(acyclic_graph)
        captured = capsys.readouterr()
        assert "    " in captured.out  # 4-space indent

    def test_json_default_indent_is_2(self, acyclic_graph, capsys):
        GraphVisualizer(JsonAdapter()).render(acyclic_graph)
        captured = capsys.readouterr()
        assert "  " in captured.out  # 2-space indent present

    def test_json_grouped_inner_present(self, grouped_graph, capsys):
        GraphVisualizer(JsonAdapter()).render(grouped_graph)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        grp_entry = next(nd for nd in parsed["nodes"] if nd["id"] == "grp")
        assert "inner" in grp_entry


# ─────────────────────────────────────────────────────────────────────────────
class TestDeferredAdapters:
    def test_html_adapter_raises_not_implemented(self, acyclic_graph):
        model = acyclic_graph.to_render_model()
        with pytest.raises(NotImplementedError):
            HtmlAdapter().render(model)

    def test_image_adapter_raises_not_implemented(self, acyclic_graph):
        model = acyclic_graph.to_render_model()
        with pytest.raises(NotImplementedError):
            ImageAdapter().render(model)


# ─────────────────────────────────────────────────────────────────────────────
class TestAdapterSwap:
    """The same graph can be rendered with different adapters."""

    def test_swap_from_terminal_to_json(self, acyclic_graph, capsys):
        graph = acyclic_graph
        GraphVisualizer(TerminalAdapter()).render(graph)
        capsys.readouterr()  # discard terminal output
        GraphVisualizer(JsonAdapter()).render(graph)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "nodes" in parsed

    def test_custom_adapter_is_called(self, acyclic_graph):
        """Custom adapter implementing render() works without inheriting."""
        called_with = []

        class MyAdapter:
            def render(self, model: GraphRenderModel) -> None:
                called_with.append(model)

        GraphVisualizer(MyAdapter()).render(acyclic_graph)  # type: ignore[arg-type]
        assert len(called_with) == 1
        assert isinstance(called_with[0], GraphRenderModel)
