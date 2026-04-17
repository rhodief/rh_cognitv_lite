from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from ..nodes import LLMConfig


# ──────────────────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────────────────


class ToolCall(BaseModel):
    """A single tool/function call returned by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMRequest(BaseModel):
    """Input to an LLMAdapter call."""

    model: str
    messages: list[dict[str, str]]
    config: LLMConfig
    tools: list[dict[str, Any]] = Field(default_factory=list)


class LLMResponse(BaseModel):
    """Complete response from an LLM call."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMChunk(BaseModel):
    """A single chunk in a streaming LLM response."""

    delta: str
    done: bool = False


# ──────────────────────────────────────────────────────────────────────
# LLMAdapter protocol
# ──────────────────────────────────────────────────────────────────────


class LLMAdapterProtocol(ABC):
    """Provider boundary for LLM calls — one implementation per provider."""

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the full response."""
        ...

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        """Send a completion request and yield response chunks."""
        ...
