"""Phase 1 unit tests — Node, NodeGroup, Edge, DAGBuilderConfig."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rh_cognitv_lite.orchestrator.models import (
    DAG,
    DAGBuilderConfig,
    Edge,
    Node,
    NodeGroup,
)


# ─────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────

class TestNode:
    def test_basic_creation(self):
        n = Node(id="n1", name="Fetch", description="Fetches the data")
        assert n.id == "n1"
        assert n.name == "Fetch"
        assert n.description == "Fetches the data"

    def test_metadata_defaults_to_empty_dict(self):
        n = Node(id="n1", name="Fetch", description="Fetches the data")
        assert n.metadata == {}

    def test_metadata_instances_are_independent(self):
        a = Node(id="a", name="A", description="")
        b = Node(id="b", name="B", description="")
        a.metadata["key"] = "value"
        assert "key" not in b.metadata

    def test_metadata_accepts_arbitrary_values(self):
        n = Node(id="n1", name="N", description="", metadata={"k": 1, "nested": {"x": True}})
        assert n.metadata["k"] == 1
        assert n.metadata["nested"]["x"] is True

    def test_id_is_required(self):
        with pytest.raises(ValidationError):
            Node(name="N", description="desc")  # type: ignore[call-arg]

    def test_name_is_required(self):
        with pytest.raises(ValidationError):
            Node(id="n1", description="desc")  # type: ignore[call-arg]

    def test_description_is_required(self):
        with pytest.raises(ValidationError):
            Node(id="n1", name="N")  # type: ignore[call-arg]

    def test_json_round_trip(self):
        n = Node(id="n1", name="Fetch", description="Fetches data", metadata={"tag": "io"})
        restored = Node.model_validate_json(n.model_dump_json())
        assert restored == n

    def test_dict_round_trip(self):
        n = Node(id="x", name="X", description="test")
        assert Node.model_validate(n.model_dump()) == n


# ─────────────────────────────────────────────
# Edge
# ─────────────────────────────────────────────

class TestEdge:
    def test_basic_creation(self):
        e = Edge(source="a", target="b")
        assert e.source == "a"
        assert e.target == "b"
        assert e.label is None

    def test_with_label(self):
        e = Edge(source="a", target="b", label="parsed-output")
        assert e.label == "parsed-output"

    def test_source_is_required(self):
        with pytest.raises(ValidationError):
            Edge(target="b")  # type: ignore[call-arg]

    def test_target_is_required(self):
        with pytest.raises(ValidationError):
            Edge(source="a")  # type: ignore[call-arg]

    def test_json_round_trip_without_label(self):
        e = Edge(source="a", target="b")
        restored = Edge.model_validate_json(e.model_dump_json())
        assert restored == e

    def test_json_round_trip_with_label(self):
        e = Edge(source="a", target="b", label="success")
        restored = Edge.model_validate_json(e.model_dump_json())
        assert restored == e

    def test_dict_round_trip(self):
        e = Edge(source="x", target="y", label="foo")
        assert Edge.model_validate(e.model_dump()) == e


# ─────────────────────────────────────────────
# DAGBuilderConfig
# ─────────────────────────────────────────────

class TestDAGBuilderConfig:
    def test_all_defaults(self):
        cfg = DAGBuilderConfig()
        assert cfg.append_only is False
        assert cfg.validate_acyclic is True
        assert cfg.validate_connected is False
        assert cfg.allow_isolated_nodes is False
        assert cfg.allow_self_loops is False
        assert cfg.allow_parallel_edges is False

    def test_all_flags_can_be_overridden(self):
        cfg = DAGBuilderConfig(
            append_only=True,
            validate_acyclic=False,
            validate_connected=True,
            allow_isolated_nodes=True,
            allow_self_loops=True,
            allow_parallel_edges=True,
        )
        assert cfg.append_only is True
        assert cfg.validate_acyclic is False
        assert cfg.validate_connected is True
        assert cfg.allow_isolated_nodes is True
        assert cfg.allow_self_loops is True
        assert cfg.allow_parallel_edges is True

    def test_json_round_trip(self):
        cfg = DAGBuilderConfig(append_only=True, allow_self_loops=True)
        restored = DAGBuilderConfig.model_validate_json(cfg.model_dump_json())
        assert restored == cfg


# ─────────────────────────────────────────────
# NodeGroup
# ─────────────────────────────────────────────

class TestNodeGroup:
    def test_is_a_node(self):
        group = NodeGroup(id="g1", name="Summarise", description="Sub-plan", inner=DAG())
        assert isinstance(group, Node)

    def test_inner_dag_is_accessible(self):
        dag = DAG()
        group = NodeGroup(id="g1", name="Group", description="", inner=dag)
        assert isinstance(group.inner, DAG)

    def test_id_name_description_inherited(self):
        group = NodeGroup(id="g1", name="G", description="desc", inner=DAG())
        assert group.id == "g1"
        assert group.name == "G"
        assert group.description == "desc"

    def test_metadata_defaults_to_empty_dict(self):
        group = NodeGroup(id="g1", name="G", description="", inner=DAG())
        assert group.metadata == {}

    def test_inner_is_required(self):
        with pytest.raises(ValidationError):
            NodeGroup(id="g1", name="G", description="")  # type: ignore[call-arg]

    def test_json_round_trip(self):
        group = NodeGroup(id="g1", name="Group", description="A sub-plan", inner=DAG())
        restored = NodeGroup.model_validate_json(group.model_dump_json())
        assert restored.id == group.id
        assert restored.name == group.name
        assert isinstance(restored.inner, DAG)
