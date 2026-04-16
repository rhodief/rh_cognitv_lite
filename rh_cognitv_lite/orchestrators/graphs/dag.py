"""
Backward-compat shim for the graphs orchestration layer.

Deprecated: import from ``rh_cognitv_lite.orchestrators.graphs.graph`` instead.
This module re-exports all legacy DAG names alongside the new Graph names and
will be removed in a future release.
"""

from rh_cognitv_lite.orchestrators.graphs.dag_builder import DAGBuilder
from rh_cognitv_lite.orchestrators.graphs.dag_visualizer import DAGVisualizer
from rh_cognitv_lite.orchestrators.graphs.graph import (
    DAGBuilderConfig,
    Edge,
    Graph,
    GraphBuilder,
    GraphBuilderConfig,
    GraphRenderModel,
    GraphVisualizer,
    GraphVisualizerAdapter,
    HtmlAdapter,
    ImageAdapter,
    JsonAdapter,
    Node,
    NodeGroup,
    RenderEdge,
    RenderNode,
    TerminalAdapter,
)
from rh_cognitv_lite.orchestrators.graphs.models import DAG

__all__ = [
    # Deprecated aliases
    "DAG",
    "DAGBuilder",
    "DAGBuilderConfig",
    "DAGVisualizer",
    # New primary API
    "Graph",
    "GraphBuilder",
    "GraphBuilderConfig",
    "GraphVisualizer",
    "GraphVisualizerAdapter",
    "GraphRenderModel",
    "RenderNode",
    "RenderEdge",
    "TerminalAdapter",
    "JsonAdapter",
    "HtmlAdapter",
    "ImageAdapter",
    # Data models
    "Edge",
    "Node",
    "NodeGroup",
]
