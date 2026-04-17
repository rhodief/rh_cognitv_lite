from __future__ import annotations

from typing import Any

from rh_cognitv_lite.execution_platform.events import ExecutionEvent
from rh_cognitv_lite.execution_platform.models import EventStatus, ExecutionResult

from .nodes import BaseExecutionNode


class CognitiveEventAdapter:
    """Builds ``ExecutionEvent`` instances for cognitive-layer telemetry (DD-15, Option B).

    The orchestrator knows *when* to emit; this adapter knows *what shape*
    the event should have.  All cognitive events use ``kind`` values prefixed
    with ``"cognitive."``.
    """

    # ── Node lifecycle ────────────────────────────────────────────────

    def node_started(
        self,
        node: BaseExecutionNode,
        *,
        graph_event_id: str | None = None,
        group_id: str | None = None,
    ) -> ExecutionEvent:
        """Build a *STARTED* event for a cognitive node execution."""
        kind = getattr(node, "kind", "unknown")
        payload: dict[str, Any] = {
            "node_id": node.id,
            "node_kind": kind,
            "category": node.category,
        }
        ext: dict[str, Any] = {}
        if hasattr(node, "instruction"):
            payload["prompt_preview"] = node.instruction[:200]  # type: ignore[union-attr]
        if hasattr(node, "llm_config"):
            ext["model"] = node.llm_config.model  # type: ignore[union-attr]
            ext["temperature"] = node.llm_config.temperature  # type: ignore[union-attr]

        return ExecutionEvent(
            name=node.name,
            description=node.description,
            kind=f"cognitive.node.{kind}",
            payload=payload,
            status=EventStatus.STARTED,
            parent_id=graph_event_id,
            group_id=group_id,
            ext=ext,
        )

    def node_completed(
        self,
        node: BaseExecutionNode,
        result: ExecutionResult[Any],
        *,
        token_usage: dict[str, int] | None = None,
        graph_event_id: str | None = None,
        group_id: str | None = None,
    ) -> ExecutionEvent:
        """Build a *COMPLETED* or *FAILED* event for a cognitive node execution."""
        kind = getattr(node, "kind", "unknown")
        status = EventStatus.COMPLETED if result.ok else EventStatus.FAILED
        payload: dict[str, Any] = {
            "node_id": node.id,
            "node_kind": kind,
            "ok": result.ok,
            "duration_ms": result.metadata.duration_ms,
        }
        if token_usage:
            payload["token_usage"] = token_usage
        if not result.ok:
            payload["error_message"] = result.error_message
            payload["error_category"] = result.error_category

        ext: dict[str, Any] = {}
        if hasattr(node, "llm_config"):
            ext["model"] = node.llm_config.model  # type: ignore[union-attr]

        return ExecutionEvent(
            name=node.name,
            description=node.description,
            kind=f"cognitive.node.{kind}",
            payload=payload,
            status=status,
            parent_id=graph_event_id,
            group_id=group_id,
            ext=ext,
        )

    # ── Graph lifecycle ───────────────────────────────────────────────

    def graph_started(
        self,
        graph_name: str,
        entry_nodes: list[str],
        *,
        group_id: str | None = None,
    ) -> ExecutionEvent:
        """Build a *STARTED* event for an ``ExecutionGraph`` traversal."""
        return ExecutionEvent(
            name=graph_name,
            kind="cognitive.graph",
            payload={
                "entry_nodes": entry_nodes,
                "node_count": len(entry_nodes),
            },
            status=EventStatus.STARTED,
            group_id=group_id,
        )

    def graph_completed(
        self,
        graph_name: str,
        results_summary: dict[str, Any],
        *,
        group_id: str | None = None,
    ) -> ExecutionEvent:
        """Build a *COMPLETED* event for an ``ExecutionGraph`` traversal."""
        return ExecutionEvent(
            name=graph_name,
            kind="cognitive.graph",
            payload=results_summary,
            status=EventStatus.COMPLETED,
            group_id=group_id,
        )
