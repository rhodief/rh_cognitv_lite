"""
DAG orchestration module.

Public surface for the orchestrator DAG layer.  Import all user-facing symbols
from here; internal sub-modules are not part of the public API.

Phase 1 — models only.
Phase 2 — in-house graph engine (_engine.py, private).
Phase 3 — full DAG traversal implementation.
Phase 4 — DAGBuilder fluent API.
Phase 5 — DAGVisualizer.
"""

from rh_cognitv_lite.orchestrators.graphs.dag_builder import DAGBuilder
from rh_cognitv_lite.orchestrators.graphs.dag_visualizer import DAGVisualizer
from rh_cognitv_lite.orchestrators.graphs.models import (
    DAG,
    DAGBuilderConfig,
    Edge,
    Node,
    NodeGroup,
)

__all__ = [
    "DAG",
    "DAGBuilder",
    "DAGBuilderConfig",
    "DAGVisualizer",
    "Edge",
    "Node",
    "NodeGroup",
]
