"""DAGVisualizer — backward-compat shim over the new adapter-based visualizer.

Deprecated: use GraphVisualizer with TerminalAdapter / JsonAdapter instead.
Kept for one release cycle then removed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from rh_cognitv_lite.orchestrators.graphs.models import Graph


class DAGVisualizer:
    """Backward-compat wrapper. Delegates to GraphVisualizer adapters.

    Deprecated: use GraphVisualizer directly.
    """

    def __init__(self, dag: Graph) -> None:
        self._dag = dag

    def render(
        self,
        format: Literal["terminal", "html", "image", "json"] = "terminal",
        **options: Any,
    ) -> None:
        self._dag.visualize(format, **options)

