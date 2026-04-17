"""Phase 1 unit tests — LLM Adapter protocol and request/response models."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from rh_cognitv_lite.cognitive.adapters.llm_adapter import (
    LLMAdapterProtocol,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    ToolCall,
)
from rh_cognitv_lite.cognitive.nodes import LLMConfig


# ──────────────────────────────────────────────────────────────────────
# ToolCall
# ──────────────────────────────────────────────────────────────────────


class TestToolCall:
    def test_creation(self):
        tc = ToolCall(id="call_1", name="search", arguments={"query": "hello"})
        assert tc.id == "call_1"
        assert tc.name == "search"
        assert tc.arguments == {"query": "hello"}

    def test_defaults(self):
        tc = ToolCall(id="call_1", name="noop")
        assert tc.arguments == {}

    def test_serialization_round_trip(self):
        tc = ToolCall(id="c1", name="fn", arguments={"a": 1})
        restored = ToolCall(**tc.model_dump())
        assert restored == tc


# ──────────────────────────────────────────────────────────────────────
# LLMRequest
# ──────────────────────────────────────────────────────────────────────


class TestLLMRequest:
    def test_creation(self):
        req = LLMRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hi"}],
            config=LLMConfig(model="gpt-4"),
        )
        assert req.model == "gpt-4"
        assert len(req.messages) == 1
        assert req.tools == []

    def test_with_tools(self):
        tool_def = {"type": "function", "function": {"name": "search"}}
        req = LLMRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Search"}],
            config=LLMConfig(model="gpt-4"),
            tools=[tool_def],
        )
        assert len(req.tools) == 1

    def test_serialization_round_trip(self):
        req = LLMRequest(
            model="m",
            messages=[{"role": "system", "content": "You are helpful"}],
            config=LLMConfig(model="m", temperature=0.0),
        )
        data = req.model_dump()
        restored = LLMRequest(**data)
        assert restored == req

    def test_json_round_trip(self):
        req = LLMRequest(
            model="m",
            messages=[{"role": "user", "content": "Q"}],
            config=LLMConfig(model="m"),
        )
        json_str = req.model_dump_json()
        restored = LLMRequest.model_validate_json(json_str)
        assert restored == req


# ──────────────────────────────────────────────────────────────────────
# LLMResponse
# ──────────────────────────────────────────────────────────────────────


class TestLLMResponse:
    def test_defaults(self):
        resp = LLMResponse()
        assert resp.content is None
        assert resp.tool_calls == []
        assert resp.usage == {}
        assert resp.raw == {}

    def test_text_response(self):
        resp = LLMResponse(
            content="Hello!",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        assert resp.content == "Hello!"
        assert resp.usage["prompt_tokens"] == 10

    def test_tool_call_response(self):
        resp = LLMResponse(
            tool_calls=[
                ToolCall(id="c1", name="search", arguments={"q": "test"}),
                ToolCall(id="c2", name="calc", arguments={"expr": "1+1"}),
            ],
            usage={"total_tokens": 50},
        )
        assert len(resp.tool_calls) == 2
        assert resp.tool_calls[0].name == "search"

    def test_serialization_round_trip(self):
        resp = LLMResponse(
            content="answer",
            tool_calls=[ToolCall(id="c1", name="fn", arguments={"k": "v"})],
            usage={"total_tokens": 20},
            raw={"id": "chatcmpl-xxx"},
        )
        data = resp.model_dump()
        restored = LLMResponse(**data)
        assert restored == resp


# ──────────────────────────────────────────────────────────────────────
# LLMChunk
# ──────────────────────────────────────────────────────────────────────


class TestLLMChunk:
    def test_defaults(self):
        chunk = LLMChunk(delta="Hello")
        assert chunk.delta == "Hello"
        assert chunk.done is False

    def test_done_chunk(self):
        chunk = LLMChunk(delta="", done=True)
        assert chunk.done is True

    def test_serialization_round_trip(self):
        chunk = LLMChunk(delta="tok", done=False)
        restored = LLMChunk(**chunk.model_dump())
        assert restored == chunk


# ──────────────────────────────────────────────────────────────────────
# LLMAdapterProtocol — concrete implementation for testing
# ──────────────────────────────────────────────────────────────────────


class MockLLMAdapter(LLMAdapterProtocol):
    """Minimal concrete adapter to verify the protocol is implementable."""

    def __init__(self, response: LLMResponse | None = None):
        self._response = response or LLMResponse(content="mock")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return self._response

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        for word in (self._response.content or "").split():
            yield LLMChunk(delta=word + " ")
        yield LLMChunk(delta="", done=True)


class TestLLMAdapterProtocol:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_complete(self):
        adapter = MockLLMAdapter(LLMResponse(content="42"))
        req = LLMRequest(
            model="m",
            messages=[{"role": "user", "content": "Q"}],
            config=LLMConfig(model="m"),
        )
        resp = await adapter.complete(req)
        assert resp.content == "42"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stream(self):
        adapter = MockLLMAdapter(LLMResponse(content="hello world"))
        req = LLMRequest(
            model="m",
            messages=[{"role": "user", "content": "Q"}],
            config=LLMConfig(model="m"),
        )
        chunks: list[LLMChunk] = []
        async for chunk in adapter.stream(req):
            chunks.append(chunk)
        assert len(chunks) == 3  # "hello ", "world ", done
        assert chunks[-1].done is True

    def test_isinstance_check(self):
        adapter = MockLLMAdapter()
        assert isinstance(adapter, LLMAdapterProtocol)
