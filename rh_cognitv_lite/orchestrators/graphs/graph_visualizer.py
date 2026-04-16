"""Graph visualizer — adapter-based rendering system.

Architecture
------------
Graph.to_render_model()  →  GraphRenderModel  →  GraphVisualizerAdapter
                                                        │
                                             ┌──────────┴──────────┐
                                        TerminalAdapter        JsonAdapter
                                        (stdout ASCII)         (stdout JSON)
                                           [HtmlAdapter]       [ImageAdapter]
                                            (deferred)          (deferred)

Public surface
--------------
GraphRenderModel      — format-agnostic topology snapshot
RenderNode            — node data for rendering
RenderEdge            — edge data for rendering
GraphVisualizerAdapter — Protocol (structural typing — no base class needed)
GraphVisualizer       — coordinator: calls to_render_model then delegates
TerminalAdapter       — ASCII/Unicode tree, cycle nodes marked [↺]
JsonAdapter           — JSON to stdout
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rh_cognitv_lite.orchestrators.graphs.models import Graph


# ── Render data structures ────────────────────────────────────────────────────

@dataclass
class RenderNode:
    """Flattened node representation for rendering."""

    id: str
    name: str
    description: str
    is_group: bool
    in_cycle: bool
    """True if this node participates in at least one directed cycle."""
    metadata: dict = field(default_factory=dict)
    inner: GraphRenderModel | None = None
    """Populated for NodeGroup nodes; None for plain nodes."""


@dataclass
class RenderEdge:
    """Flattened edge representation for rendering."""

    source_id: str
    target_id: str
    label: str | None
    is_back_edge: bool
    """True if this edge is a DFS back-edge (creates a cycle)."""


@dataclass
class GraphRenderModel:
    """Format-agnostic topology snapshot produced by ``Graph.to_render_model()``.

    Passed to any ``GraphVisualizerAdapter`` for rendering.  Fully
    self-contained — no further graph queries are needed at render time.
    """

    nodes: list[RenderNode] = field(default_factory=list)
    edges: list[RenderEdge] = field(default_factory=list)
    is_cyclic: bool = False


# ── Adapter protocol ──────────────────────────────────────────────────────────

class GraphVisualizerAdapter:
    """Structural protocol for visualizer adapters.

    Any object that implements ``render(model: GraphRenderModel) -> None`` is a
    valid adapter — no inheritance required.
    """

    def render(self, model: GraphRenderModel) -> None:
        raise NotImplementedError


# ── Coordinator ───────────────────────────────────────────────────────────────

class GraphVisualizer:
    """Coordinator: calls ``graph.to_render_model()`` then delegates to adapter.

    The visualizer holds no rendering logic itself.

    Parameters
    ----------
    adapter:
        Any object implementing ``render(GraphRenderModel) -> None``.
    """

    def __init__(self, adapter: GraphVisualizerAdapter) -> None:
        self._adapter = adapter

    def render(self, graph: Graph) -> None:
        """Render *graph* using the configured adapter."""
        model = graph.to_render_model()
        self._adapter.render(model)


# ── Built-in adapters ─────────────────────────────────────────────────────────

class TerminalAdapter:
    """Renders a ``GraphRenderModel`` as an ASCII/Unicode tree to stdout.

    Cycle-aware: nodes in cycles are marked ``[↺]`` and back-edges are
    marked ``[↺─]`` in the successor list.
    """

    def render(self, model: GraphRenderModel) -> None:
        print(self._render_model(model, indent=0))

    def _render_model(self, model: GraphRenderModel, indent: int) -> str:
        lines: list[str] = []
        prefix = "  " * indent

        node_map = {rn.id: rn for rn in model.nodes}
        back_edge_set = {(e.source_id, e.target_id) for e in model.edges if e.is_back_edge}

        # Build successor map for display.
        succ: dict[str, list[tuple[str, str | None]]] = {rn.id: [] for rn in model.nodes}
        for e in model.edges:
            succ[e.source_id].append((e.target_id, e.label))

        # Order: entry nodes (no non-back-edge predecessors) first, rest after.
        non_back_incoming: dict[str, int] = {rn.id: 0 for rn in model.nodes}
        for e in model.edges:
            if not e.is_back_edge:
                non_back_incoming[e.target_id] += 1

        ordered = (
            [rn.id for rn in model.nodes if non_back_incoming[rn.id] == 0]
            + [rn.id for rn in model.nodes if non_back_incoming[rn.id] > 0]
        )

        printed: set[str] = set()
        for node_id in ordered:
            if node_id in printed:
                continue
            printed.add(node_id)
            rn = node_map[node_id]

            cycle_tag = " [↺]" if rn.in_cycle else ""
            type_tag = "[Group]" if rn.is_group else "[Node]"

            edges_out: list[str] = []
            for tgt_id, lbl in sorted(succ.get(node_id, []), key=lambda x: x[0]):
                back_tag = " [↺─]" if (node_id, tgt_id) in back_edge_set else ""
                label_tag = f":{lbl}" if lbl else ""
                edges_out.append(f"{tgt_id}{label_tag}{back_tag}")

            succ_str = f"  →  [{', '.join(edges_out)}]" if edges_out else ""
            lines.append(f"{prefix}{type_tag} {rn.id} ({rn.name}){cycle_tag}{succ_str}")

            if rn.inner is not None:
                lines.append(f"{prefix}  └─ inner:")
                lines.append(self._render_model(rn.inner, indent + 2))

        return "\n".join(lines)


class JsonAdapter:
    """Renders a ``GraphRenderModel`` as JSON to stdout.

    Parameters
    ----------
    indent:
        JSON indentation level (default 2).
    """

    def __init__(self, indent: int = 2) -> None:
        self._indent = indent

    def render(self, model: GraphRenderModel) -> None:
        print(_json.dumps(self._model_to_dict(model), indent=self._indent))

    def _model_to_dict(self, model: GraphRenderModel) -> dict[str, Any]:
        nodes_out: list[dict[str, Any]] = []
        for rn in model.nodes:
            entry: dict[str, Any] = {
                "id": rn.id,
                "name": rn.name,
                "description": rn.description,
                "is_group": rn.is_group,
                "in_cycle": rn.in_cycle,
            }
            if rn.metadata:
                entry["metadata"] = rn.metadata
            if rn.inner is not None:
                entry["inner"] = self._model_to_dict(rn.inner)
            nodes_out.append(entry)

        edges_out: list[dict[str, Any]] = []
        for re in model.edges:
            e: dict[str, Any] = {
                "source": re.source_id,
                "target": re.target_id,
                "is_back_edge": re.is_back_edge,
            }
            if re.label is not None:
                e["label"] = re.label
            edges_out.append(e)

        return {
            "nodes": nodes_out,
            "edges": edges_out,
            "is_cyclic": model.is_cyclic,
        }


class HtmlAdapter:
    """Deferred — interactive HTML graph rendering."""

    def render(self, model: GraphRenderModel) -> None:
        raise NotImplementedError(
            "HTML rendering is deferred. "
            "Strategy to be decided in a future sprint."
        )


class ImageAdapter:
    """Deferred — static image export."""

    def render(self, model: GraphRenderModel) -> None:
        raise NotImplementedError(
            "Image rendering is deferred. "
            "Strategy to be decided in a future sprint."
        )
