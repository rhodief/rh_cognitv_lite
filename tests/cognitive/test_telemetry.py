"""Phase 6 unit tests — CognitiveEventAdapter (DD-15)."""
from __future__ import annotations

from typing import Any

import pytest

from rh_cognitv_lite.cognitive.nodes import (
    BaseExecutionNode,
    FunctionNode,
    LLMConfig,
    ObjectNode,
    TextNode,
)
from rh_cognitv_lite.cognitive.telemetry import CognitiveEventAdapter
from rh_cognitv_lite.execution_platform.models import (
    EventStatus,
    ExecutionResult,
    ResultMetadata,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _llm_config() -> LLMConfig:
    return LLMConfig(model="gpt-4", temperature=0.3)


def _text_node() -> TextNode:
    return TextNode(
        id="t1", name="summarize", description="Summarize input",
        instruction="Please summarize the following text.",
        llm_config=_llm_config(),
    )


def _object_node() -> ObjectNode:
    return ObjectNode(
        id="o1", name="extract", description="Extract entities",
        instruction="Extract entities from the text.",
        llm_config=_llm_config(),
    )


def _function_node() -> FunctionNode:
    return FunctionNode(
        id="f1", name="transform", description="Transform data",
        handler=lambda x: x,
    )


def _ok_result(duration_ms: float = 42.0) -> ExecutionResult[Any]:
    return ExecutionResult(
        ok=True, value="done",
        metadata=ResultMetadata(duration_ms=duration_ms),
    )


def _fail_result() -> ExecutionResult[Any]:
    return ExecutionResult(
        ok=False,
        error_message="validation failed",
        error_category="permanent",
        metadata=ResultMetadata(duration_ms=10.0),
    )


# ══════════════════════════════════════════════════════════════════════
# node_started
# ══════════════════════════════════════════════════════════════════════


class TestNodeStarted:
    def test_text_node_started(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_started(
            _text_node(), graph_event_id="g1", group_id="grp1",
        )
        assert event.kind == "cognitive.node.text"
        assert event.status == EventStatus.STARTED
        assert event.payload["node_id"] == "t1"
        assert event.payload["node_kind"] == "text"
        assert event.payload["category"] == "action"
        assert "Please summarize" in event.payload["prompt_preview"]
        assert event.ext["model"] == "gpt-4"
        assert event.ext["temperature"] == 0.3
        assert event.parent_id == "g1"
        assert event.group_id == "grp1"

    def test_function_node_started_no_llm_fields(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_started(_function_node())
        assert event.kind == "cognitive.node.function"
        assert event.status == EventStatus.STARTED
        assert "prompt_preview" not in event.payload
        assert "model" not in event.ext

    def test_object_node_started(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_started(_object_node())
        assert event.kind == "cognitive.node.object"
        assert event.payload["node_kind"] == "object"
        assert event.ext["model"] == "gpt-4"

    def test_prompt_preview_truncated(self) -> None:
        long_instruction = "x" * 500
        node = TextNode(
            id="t", name="t", description="d",
            instruction=long_instruction, llm_config=_llm_config(),
        )
        adapter = CognitiveEventAdapter()
        event = adapter.node_started(node)
        assert len(event.payload["prompt_preview"]) == 200

    def test_default_ids_are_none(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_started(_text_node())
        assert event.parent_id is None
        assert event.group_id is None

    def test_name_and_description(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_started(_text_node())
        assert event.name == "summarize"
        assert event.description == "Summarize input"


# ══════════════════════════════════════════════════════════════════════
# node_completed
# ══════════════════════════════════════════════════════════════════════


class TestNodeCompleted:
    def test_completed_ok(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_completed(
            _text_node(), _ok_result(),
            graph_event_id="g1", group_id="grp1",
        )
        assert event.kind == "cognitive.node.text"
        assert event.status == EventStatus.COMPLETED
        assert event.payload["ok"] is True
        assert event.payload["duration_ms"] == 42.0
        assert "error_message" not in event.payload
        assert event.parent_id == "g1"

    def test_completed_failed(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_completed(_object_node(), _fail_result())
        assert event.status == EventStatus.FAILED
        assert event.payload["ok"] is False
        assert event.payload["error_message"] == "validation failed"
        assert event.payload["error_category"] == "permanent"

    def test_token_usage_included(self) -> None:
        adapter = CognitiveEventAdapter()
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        event = adapter.node_completed(
            _text_node(), _ok_result(), token_usage=usage,
        )
        assert event.payload["token_usage"] == usage

    def test_token_usage_omitted_when_none(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_completed(_text_node(), _ok_result())
        assert "token_usage" not in event.payload

    def test_function_node_completed(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_completed(_function_node(), _ok_result())
        assert event.kind == "cognitive.node.function"
        assert "model" not in event.ext

    def test_ext_includes_model(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_completed(_object_node(), _ok_result())
        assert event.ext["model"] == "gpt-4"


# ══════════════════════════════════════════════════════════════════════
# graph_started
# ══════════════════════════════════════════════════════════════════════


class TestGraphStarted:
    def test_graph_started(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.graph_started(
            "my_graph", ["n1", "n2"], group_id="grp1",
        )
        assert event.kind == "cognitive.graph"
        assert event.status == EventStatus.STARTED
        assert event.name == "my_graph"
        assert event.payload["entry_nodes"] == ["n1", "n2"]
        assert event.payload["node_count"] == 2
        assert event.group_id == "grp1"

    def test_graph_started_no_group(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.graph_started("g", [])
        assert event.group_id is None
        assert event.payload["entry_nodes"] == []


# ══════════════════════════════════════════════════════════════════════
# graph_completed
# ══════════════════════════════════════════════════════════════════════


class TestGraphCompleted:
    def test_graph_completed(self) -> None:
        adapter = CognitiveEventAdapter()
        summary = {"nodes_executed": 3, "total_duration_ms": 120.0}
        event = adapter.graph_completed(
            "my_graph", summary, group_id="grp1",
        )
        assert event.kind == "cognitive.graph"
        assert event.status == EventStatus.COMPLETED
        assert event.name == "my_graph"
        assert event.payload == summary
        assert event.group_id == "grp1"

    def test_graph_completed_empty_summary(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.graph_completed("g", {})
        assert event.payload == {}


# ══════════════════════════════════════════════════════════════════════
# Event identity
# ══════════════════════════════════════════════════════════════════════


class TestEventIdentity:
    def test_each_event_has_unique_id(self) -> None:
        adapter = CognitiveEventAdapter()
        e1 = adapter.node_started(_text_node())
        e2 = adapter.node_started(_text_node())
        assert e1.id != e2.id

    def test_events_have_created_at(self) -> None:
        adapter = CognitiveEventAdapter()
        event = adapter.node_started(_text_node())
        assert event.created_at is not None
