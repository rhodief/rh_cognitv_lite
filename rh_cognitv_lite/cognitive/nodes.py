from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────
# LLMConfig
# ──────────────────────────────────────────────────────────────────────


class LLMConfig(BaseModel):
    """Configuration for an LLM call — model selection, sampling, and tool definitions."""

    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stop_sequences: list[str] = Field(default_factory=list)
    tool_definitions: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────
# Execution Nodes
# ──────────────────────────────────────────────────────────────────────


class BaseExecutionNode(BaseModel):
    """Base for all execution node types — a declarative blueprint for a unit of work."""

    id: str
    name: str
    description: str
    category: Literal["action", "flow"] = "action"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextNode(BaseExecutionNode):
    """LLM call that produces text or a text stream."""

    kind: Literal["text"] = "text"
    instruction: str
    llm_config: LLMConfig
    streaming: bool = False
    context_refs: list[str] = Field(default_factory=list)


class ObjectNode(BaseExecutionNode):
    """LLM call that produces a structured object via tool-calling / function-calling."""

    kind: Literal["object"] = "object"
    instruction: str
    llm_config: LLMConfig
    output_model: type[BaseModel] | None = None
    retry_on_validation_failure: bool = True
    context_refs: list[str] = Field(default_factory=list)


class FunctionNode(BaseExecutionNode):
    """Deterministic function execution — no LLM involved."""

    kind: Literal["function"] = "function"
    handler: Callable[..., Any]

    model_config = {"arbitrary_types_allowed": True}


class ForEachNode(BaseExecutionNode):
    """Flow-control node that iterates over a list and executes body nodes per element.

    The graph sees one node; the orchestrator expands it at runtime into
    N iterations over the list referenced by ``items_ref``.
    """

    kind: Literal["for_each"] = "for_each"
    category: Literal["action", "flow"] = "flow"
    items_ref: str
    body_nodes: list[BaseExecutionNode]
    parallel: bool = False
    max_workers: int | None = None
    result_key: str | None = None

    model_config = {"arbitrary_types_allowed": True}
