"""DAGVisualizer — standalone rendering utility for DAG topology.

Supported formats
-----------------
terminal  ASCII/Unicode tree expanding all NodeGroup internals
json      Structured dict/JSON representation of the full topology
html      NotImplementedError (deferred)
image     NotImplementedError (deferred)
"""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from rh_cognitv_lite.orchestrators.graphs.models import DAG, Node, NodeGroup


class DAGVisualizer:
    """Renders a ``DAG`` in various formats.

    Parameters
    ----------
    dag:
        The DAG to visualize.  All ``NodeGroup`` internals are always
        expanded; the visualizer never uses the outer-only traversal.
    """

    def __init__(self, dag: DAG) -> None:
        # Import here to avoid a circular import at module load time.
        from rh_cognitv_lite.orchestrators.graphs.models import DAG as _DAG  # noqa: F401
        self._dag = dag

    # ── Public API ────────────────────────────────────────────────────────────

    def render(
        self,
        format: Literal["terminal", "html", "image", "json"] = "terminal",
        **options: Any,
    ) -> None:
        """Render the DAG.

        Parameters
        ----------
        format:
            ``"terminal"``  — prints an ASCII tree to stdout.
            ``"json"``      — prints a JSON document to stdout.
            ``"html"``  / ``"image"`` — raise ``NotImplementedError``.
        **options:
            Reserved for future use (e.g. ``indent`` for json format).

        Raises
        ------
        NotImplementedError
            For ``"html"`` and ``"image"`` formats.
        ValueError
            For unknown format strings.
        """
        if format == "terminal":
            print(self._render_terminal())
        elif format == "json":
            indent = options.get("indent", 2)
            print(_json.dumps(self._render_json(), indent=indent))
        elif format == "html":
            raise NotImplementedError(
                "HTML rendering is deferred. "
                "Strategy (pure Python layout vs. optional matplotlib) "
                "to be decided in a future sprint."
            )
        elif format == "image":
            raise NotImplementedError(
                "Image rendering is deferred. "
                "Strategy (pure Python layout vs. optional matplotlib) "
                "to be decided in a future sprint."
            )
        else:
            raise ValueError(
                f"Unknown format {format!r}. "
                "Valid choices: 'terminal', 'json', 'html', 'image'."
            )

    # ── JSON representation ───────────────────────────────────────────────────

    def _render_json(self) -> dict[str, Any]:
        """Return a structured dict of the full topology (groups expanded)."""
        return _dag_to_dict(self._dag)

    # ── Terminal representation ───────────────────────────────────────────────

    def _render_terminal(self) -> str:
        """Return an ASCII/Unicode adjacency tree as a string."""
        lines: list[str] = []
        _render_dag_terminal(self._dag, lines, indent=0)
        return "\n".join(lines)


# ── Helpers (module-private) ──────────────────────────────────────────────────

def _dag_to_dict(dag: DAG) -> dict[str, Any]:
    """Recursively convert a DAG (and any nested NodeGroups) to a plain dict."""
    from rh_cognitv_lite.orchestrators.graphs.models import NodeGroup

    nodes_out = []
    for node in dag.nodes_data:
        entry: dict[str, Any] = {
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "metadata": dict(node.metadata),
        }
        if isinstance(node, NodeGroup):
            entry["inner"] = _dag_to_dict(node.inner)
        nodes_out.append(entry)

    edges_out = [
        {
            "source": e.source,
            "target": e.target,
            **({"label": e.label} if e.label is not None else {}),
        }
        for e in dag.edges_data
    ]

    return {"nodes": nodes_out, "edges": edges_out}


def _render_dag_terminal(dag: DAG, lines: list[str], indent: int) -> None:
    """Append terminal-tree lines for *dag* and all nested groups."""
    from rh_cognitv_lite.orchestrators.graphs.models import NodeGroup, _GraphEngine

    prefix = "  " * indent

    # Build successor map for directed display.
    eng: _GraphEngine = dag._get_engine()  # type: ignore[attr-defined]

    # Display entry nodes first (topological breadth-first order).
    try:
        generations = eng.topological_generations()
    except Exception:
        # Fallback for graphs with cycles (shouldn't happen with valid DAGs,
        # but be defensive in a visualizer).
        generations = [{n.id for n in dag.nodes_data}]

    node_by_id = {n.id: n for n in dag.nodes_data}
    printed: set[str] = set()

    for gen_idx, generation in enumerate(generations):
        for node_id in sorted(generation):  # sort for deterministic output
            if node_id in printed:
                continue
            printed.add(node_id)

            node = node_by_id[node_id]
            successors = sorted(eng._succ.get(node_id, set()))
            succ_str = f"  →  [{', '.join(successors)}]" if successors else ""
            type_tag = "[Group]" if isinstance(node, NodeGroup) else "[Node]"
            lines.append(f"{prefix}{type_tag} {node.id} ({node.name}){succ_str}")

            if isinstance(node, NodeGroup):
                lines.append(f"{prefix}  └─ inner:")
                _render_dag_terminal(node.inner, lines, indent + 2)
