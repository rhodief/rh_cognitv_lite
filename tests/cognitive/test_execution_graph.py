"""Phase 3 unit tests — ExecutionGraph, ExecutionGraphBuilder, and Node Adapters."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from rh_cognitv_lite.cognitive.adapters.llm_adapter import (
    LLMAdapterProtocol,
    LLMRequest,
    LLMResponse,
    ToolCall,
)
from rh_cognitv_lite.cognitive.adapters.node_adapters import (
    ExecutionNodeAdapterProtocol,
    FunctionNodeAdapter,
    ObjectNodeAdapter,
    TextNodeAdapter,
)
from rh_cognitv_lite.cognitive.execution_graph import (
    ExecutionGraph,
    ExecutionGraphBuilder,
)
from rh_cognitv_lite.cognitive.nodes import (
    BaseExecutionNode,
    FunctionNode,
    LLMConfig,
    ObjectNode,
    TextNode,
)
from rh_cognitv_lite.execution_platform.execution import Execution


# ──────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────


def _llm_config() -> LLMConfig:
    return LLMConfig(model="gpt-4")


def _text_node(id: str = "t1", name: str = "text_node") -> TextNode:
    return TextNode(
        id=id, name=name, description="A text node",
        instruction="Say hello", llm_config=_llm_config(),
    )


def _object_node(id: str = "o1", name: str = "object_node") -> ObjectNode:
    return ObjectNode(
        id=id, name=name, description="An object node",
        instruction="Extract data", llm_config=_llm_config(),
    )


def _function_node(id: str = "f1", name: str = "func_node") -> FunctionNode:
    return FunctionNode(
        id=id, name=name, description="A function node",
        handler=lambda x: x,
    )


class _MockLLMAdapter(LLMAdapterProtocol):
    """Minimal mock LLM adapter for testing."""

    def __init__(self, response_content: str = "hello") -> None:
        self._content = response_content

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content=self._content)

    async def stream(self, request):
        yield  # pragma: no cover


# ══════════════════════════════════════════════════════════════════════
# ExecutionGraphBuilder
# ══════════════════════════════════════════════════════════════════════


class TestExecutionGraphBuilder:
    def test_build_empty_graph(self):
        eg = ExecutionGraphBuilder("empty").build()
        assert eg.name == "empty"
        assert eg.nodes() == []

    def test_add_single_node(self):
        node = _text_node()
        eg = ExecutionGraphBuilder("g").add_node(node).build()
        assert len(eg.nodes()) == 1
        assert eg.get_execution_node("t1") is node

    def test_add_multiple_nodes_with_edges(self):
        t = _text_node("t1")
        o = _object_node("o1")
        f = _function_node("f1")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(t)
            .add_node(o)
            .add_node(f)
            .add_edge("t1", "o1")
            .add_edge("o1", "f1")
            .build()
        )
        assert len(eg.nodes()) == 3
        assert eg.entry_nodes() == [t]
        assert eg.next_from("t1") == [o]
        assert eg.next_from("o1") == [f]
        assert eg.next_from("f1") == []

    def test_duplicate_node_raises(self):
        builder = ExecutionGraphBuilder("g").add_node(_text_node("x"))
        with pytest.raises(ValueError, match="already registered"):
            builder.add_node(_text_node("x"))

    def test_edge_unknown_source_raises(self):
        builder = ExecutionGraphBuilder("g").add_node(_text_node("t1"))
        with pytest.raises(ValueError, match="Source node 'unknown'"):
            builder.add_edge("unknown", "t1")

    def test_edge_unknown_target_raises(self):
        builder = ExecutionGraphBuilder("g").add_node(_text_node("t1"))
        with pytest.raises(ValueError, match="Target node 'unknown'"):
            builder.add_edge("t1", "unknown")

    def test_fluent_chaining(self):
        builder = ExecutionGraphBuilder("g")
        result = builder.add_node(_text_node("a"))
        assert result is builder

    def test_adapter_registration_via_builder(self):
        adapter = FunctionNodeAdapter()
        node = _function_node("f1")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(node)
            .adapter("function", adapter)
            .build()
        )
        exe = eg.get_execution("f1")
        assert isinstance(exe, Execution)
        assert exe.name == "func_node"


# ══════════════════════════════════════════════════════════════════════
# ExecutionGraph
# ══════════════════════════════════════════════════════════════════════


class TestExecutionGraph:
    def test_get_execution_node_found(self):
        node = _text_node()
        eg = ExecutionGraphBuilder("g").add_node(node).build()
        assert eg.get_execution_node("t1") is node

    def test_get_execution_node_not_found(self):
        eg = ExecutionGraphBuilder("g").build()
        with pytest.raises(KeyError, match="not found"):
            eg.get_execution_node("missing")

    def test_nodes_returns_all(self):
        t = _text_node("a")
        f = _function_node("b")
        eg = ExecutionGraphBuilder("g").add_node(t).add_node(f).build()
        assert eg.nodes() == [t, f]

    def test_entry_nodes_linear(self):
        """In a linear chain a→b→c, only 'a' is an entry node."""
        a = _text_node("a", "node_a")
        b = _text_node("b", "node_b")
        c = _text_node("c", "node_c")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(a).add_node(b).add_node(c)
            .add_edge("a", "b").add_edge("b", "c")
            .build()
        )
        entries = eg.entry_nodes()
        assert len(entries) == 1
        assert entries[0].id == "a"

    def test_entry_nodes_multiple_roots(self):
        """Two roots merging into one sink."""
        a = _text_node("a", "root_a")
        b = _text_node("b", "root_b")
        c = _text_node("c", "sink")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(a).add_node(b).add_node(c)
            .add_edge("a", "c").add_edge("b", "c")
            .build()
        )
        entries = eg.entry_nodes()
        assert len(entries) == 2
        entry_ids = {n.id for n in entries}
        assert entry_ids == {"a", "b"}

    def test_next_from_returns_successors(self):
        a = _text_node("a", "A")
        b = _text_node("b", "B")
        c = _function_node("c")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(a).add_node(b).add_node(c)
            .add_edge("a", "b").add_edge("a", "c")
            .build()
        )
        successors = eg.next_from("a")
        succ_ids = {n.id for n in successors}
        assert succ_ids == {"b", "c"}

    def test_next_from_leaf_returns_empty(self):
        a = _text_node("a", "A")
        eg = ExecutionGraphBuilder("g").add_node(a).build()
        assert eg.next_from("a") == []

    def test_next_from_unknown_node_raises(self):
        eg = ExecutionGraphBuilder("g").build()
        with pytest.raises(KeyError):
            eg.next_from("missing")

    def test_get_execution_no_adapter_raises(self):
        node = _text_node()
        eg = ExecutionGraphBuilder("g").add_node(node).build()
        with pytest.raises(KeyError, match="No adapter registered"):
            eg.get_execution("t1")

    def test_register_adapter_at_runtime(self):
        adapter = FunctionNodeAdapter()
        node = _function_node("f1")
        eg = ExecutionGraphBuilder("g").add_node(node).build()
        eg.register_adapter("function", adapter)
        exe = eg.get_execution("f1")
        assert exe.name == "func_node"

    def test_serialization_round_trip(self):
        """Serialize → deserialize preserves topology and node registry."""
        a = _text_node("a", "node_a")
        b = _function_node("b")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(a).add_node(b)
            .add_edge("a", "b")
            .build()
        )
        data = eg.model_dump()
        restored = ExecutionGraph.model_validate(data)

        assert restored.name == "g"
        assert len(restored.nodes()) == 2
        assert restored.get_execution_node("a").id == "a"
        assert restored.get_execution_node("b").id == "b"
        entries = restored.entry_nodes()
        assert len(entries) == 1
        assert entries[0].id == "a"
        assert len(restored.next_from("a")) == 1
        assert restored.next_from("a")[0].id == "b"

    def test_isolated_node_is_entry_and_has_no_successors(self):
        node = _text_node("iso")
        eg = ExecutionGraphBuilder("g").add_node(node).build()
        assert eg.entry_nodes() == [node]
        assert eg.next_from("iso") == []


# ══════════════════════════════════════════════════════════════════════
# ExecutionNodeAdapterProtocol
# ══════════════════════════════════════════════════════════════════════


class TestExecutionNodeAdapterProtocol:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            ExecutionNodeAdapterProtocol()

    def test_concrete_subclass_works(self):
        class MyAdapter(ExecutionNodeAdapterProtocol):
            def to_execution(self, node):
                return Execution(name="x", handler=lambda: None)

        adapter = MyAdapter()
        exe = adapter.to_execution(_text_node())
        assert exe.name == "x"


# ══════════════════════════════════════════════════════════════════════
# FunctionNodeAdapter
# ══════════════════════════════════════════════════════════════════════


class TestFunctionNodeAdapter:
    def test_converts_function_node(self):
        called = []

        def my_handler(data):
            called.append(data)
            return "done"

        node = FunctionNode(
            id="f1", name="my_func", description="test",
            handler=my_handler,
        )
        adapter = FunctionNodeAdapter()
        exe = adapter.to_execution(node)

        assert exe.name == "my_func"
        assert exe.description == "test"
        assert exe.kind == "function"
        assert exe.handler is my_handler

    def test_wrong_node_type_raises(self):
        adapter = FunctionNodeAdapter()
        with pytest.raises(TypeError, match="expects FunctionNode"):
            adapter.to_execution(_text_node())


# ══════════════════════════════════════════════════════════════════════
# TextNodeAdapter
# ══════════════════════════════════════════════════════════════════════


class TestTextNodeAdapter:
    def test_converts_text_node(self):
        mock = _MockLLMAdapter()
        node = _text_node()
        adapter = TextNodeAdapter(mock)
        exe = adapter.to_execution(node)

        assert exe.name == "text_node"
        assert exe.kind == "text"
        assert exe.handler is not None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_handler_calls_llm(self):
        mock = _MockLLMAdapter(response_content="world")
        node = _text_node()
        adapter = TextNodeAdapter(mock)
        exe = adapter.to_execution(node)

        result = await exe.handler(None)
        assert result == "world"

    def test_wrong_node_type_raises(self):
        adapter = TextNodeAdapter(_MockLLMAdapter())
        with pytest.raises(TypeError, match="expects TextNode"):
            adapter.to_execution(_function_node())


# ══════════════════════════════════════════════════════════════════════
# ObjectNodeAdapter
# ══════════════════════════════════════════════════════════════════════


class _ExtractModel(BaseModel):
    name: str
    age: int


class TestObjectNodeAdapter:
    def test_converts_object_node(self):
        mock = _MockLLMAdapter()
        node = _object_node()
        adapter = ObjectNodeAdapter(mock)
        exe = adapter.to_execution(node)

        assert exe.name == "object_node"
        assert exe.kind == "object"
        assert exe.retry_aware is True
        assert exe.retry_config is not None
        assert exe.retry_config.max_attempts == 3

    def test_no_retry_when_disabled(self):
        mock = _MockLLMAdapter()
        node = ObjectNode(
            id="o1", name="no_retry", description="test",
            instruction="Extract", llm_config=_llm_config(),
            retry_on_validation_failure=False,
        )
        adapter = ObjectNodeAdapter(mock)
        exe = adapter.to_execution(node)

        assert exe.retry_config is None
        assert exe.retry_aware is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_handler_returns_content_when_no_output_model(self):
        mock = _MockLLMAdapter(response_content="raw text")
        node = _object_node()
        adapter = ObjectNodeAdapter(mock)
        exe = adapter.to_execution(node)

        result = await exe.handler(None)
        assert result == "raw text"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_handler_validates_tool_call_against_output_model(self):
        class MockWithToolCalls(LLMAdapterProtocol):
            async def complete(self, request):
                return LLMResponse(
                    tool_calls=[
                        ToolCall(id="1", name="extract", arguments={"name": "Alice", "age": 30})
                    ]
                )

            async def stream(self, request):
                yield  # pragma: no cover

        node = ObjectNode(
            id="o1", name="structured", description="test",
            instruction="Extract person", llm_config=_llm_config(),
            output_model=_ExtractModel,
        )
        adapter = ObjectNodeAdapter(MockWithToolCalls())
        exe = adapter.to_execution(node)

        result = await exe.handler(None)
        assert isinstance(result, _ExtractModel)
        assert result.name == "Alice"
        assert result.age == 30

    def test_wrong_node_type_raises(self):
        adapter = ObjectNodeAdapter(_MockLLMAdapter())
        with pytest.raises(TypeError, match="expects ObjectNode"):
            adapter.to_execution(_function_node())


# ══════════════════════════════════════════════════════════════════════
# End-to-end: builder + adapters + get_execution
# ══════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    def test_full_graph_with_all_adapters(self):
        mock_llm = _MockLLMAdapter()
        t = _text_node("t1")
        o = _object_node("o1")
        f = _function_node("f1")

        eg = (
            ExecutionGraphBuilder("pipeline")
            .add_node(t)
            .add_node(o)
            .add_node(f)
            .add_edge("t1", "o1")
            .add_edge("o1", "f1")
            .adapter("text", TextNodeAdapter(mock_llm))
            .adapter("object", ObjectNodeAdapter(mock_llm))
            .adapter("function", FunctionNodeAdapter())
            .build()
        )

        assert eg.get_execution("t1").kind == "text"
        assert eg.get_execution("o1").kind == "object"
        assert eg.get_execution("f1").kind == "function"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_execute_text_node_through_graph(self):
        mock_llm = _MockLLMAdapter(response_content="Hi there!")
        node = _text_node("t1")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(node)
            .adapter("text", TextNodeAdapter(mock_llm))
            .build()
        )
        exe = eg.get_execution("t1")
        result = await exe.handler(None)
        assert result == "Hi there!"

    def test_diamond_topology(self):
        """Diamond: a → b, a → c, b → d, c → d."""
        a = _text_node("a", "A")
        b = _text_node("b", "B")
        c = _text_node("c", "C")
        d = _text_node("d", "D")
        eg = (
            ExecutionGraphBuilder("diamond")
            .add_node(a).add_node(b).add_node(c).add_node(d)
            .add_edge("a", "b").add_edge("a", "c")
            .add_edge("b", "d").add_edge("c", "d")
            .build()
        )
        assert len(eg.entry_nodes()) == 1
        assert eg.entry_nodes()[0].id == "a"

        succ_a = {n.id for n in eg.next_from("a")}
        assert succ_a == {"b", "c"}

        succ_b = {n.id for n in eg.next_from("b")}
        assert succ_b == {"d"}

        succ_d = eg.next_from("d")
        assert succ_d == []

    def test_serialization_preserves_node_types(self):
        """After round-trip, node types are preserved (TextNode stays TextNode, etc.)."""
        t = _text_node("t1")
        f = _function_node("f1")
        eg = (
            ExecutionGraphBuilder("g")
            .add_node(t).add_node(f)
            .add_edge("t1", "f1")
            .build()
        )
        data = eg.model_dump()
        restored = ExecutionGraph.model_validate(data)

        # TextNode should round-trip as a dict but still be retrievable
        t_restored = restored.get_execution_node("t1")
        assert t_restored.id == "t1"
        assert t_restored.name == "text_node"

        f_restored = restored.get_execution_node("f1")
        assert f_restored.id == "f1"
        assert f_restored.name == "func_node"
