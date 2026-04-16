"""
Public surface for the graphs orchestration layer.

Import all user-facing symbols from here; internal sub-modules are not
part of the public API.

Generic directed graph (cyclic or acyclic):
  Graph, GraphBuilder, GraphBuilderConfig

Adapter-based visualization:
  GraphVisualizer, GraphVisualizerAdapter
  GraphRenderModel, RenderNode, RenderEdge
  TerminalAdapter, JsonAdapter, HtmlAdapter, ImageAdapter

Data models:
  Node, NodeGroup, Edge

Backward-compat aliases (deprecated — will be removed in a future release):
  DAG              → Graph
  DAGBuilderConfig → use GraphBuilderConfig instead
"""

from rh_cognitv_lite.orchestrators.graphs.graph_builder import GraphBuilder
from rh_cognitv_lite.orchestrators.graphs.graph_visualizer import (
    GraphRenderModel,
    GraphVisualizer,
    GraphVisualizerAdapter,
    HtmlAdapter,
    ImageAdapter,
    JsonAdapter,
    RenderEdge,
    RenderNode,
    TerminalAdapter,
)
from rh_cognitv_lite.orchestrators.graphs.models import (
    DAG,
    DAGBuilderConfig,
    Edge,
    Graph,
    GraphBuilderConfig,
    Node,
    NodeGroup,
)

__all__ = [
    # ── Primary API ────────────────────────────────────────────────────────
    "Graph",
    "GraphBuilder",
    "GraphBuilderConfig",
    # ── Visualizer ─────────────────────────────────────────────────────────
    "GraphVisualizer",
    "GraphVisualizerAdapter",
    "GraphRenderModel",
    "RenderNode",
    "RenderEdge",
    "TerminalAdapter",
    "JsonAdapter",
    "HtmlAdapter",
    "ImageAdapter",
    # ── Data models ────────────────────────────────────────────────────────
    "Edge",
    "Node",
    "NodeGroup",
    # ── Deprecated aliases ─────────────────────────────────────────────────
    "DAG",
    "DAGBuilderConfig",
]
