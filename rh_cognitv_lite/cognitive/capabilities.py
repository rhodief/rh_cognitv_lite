from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from .nodes import LLMConfig


# ──────────────────────────────────────────────────────────────────────
# BaseCapability
# ──────────────────────────────────────────────────────────────────────


class BaseCapability(BaseModel):
    """Declares what an agent can do — the identity of a cognitive unit."""

    id: str
    name: str
    description: str
    when_to_use: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    def register_execution_graph(self) -> Any:
        """Build and return the ExecutionGraph for this capability.

        Concrete subclasses override this. Returns ``ExecutionGraph``
        (defined in Phase 3).
        """
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────
# BaseSkill
# ──────────────────────────────────────────────────────────────────────


class BaseSkill(BaseCapability):
    """LLM-powered capability with instructions, config, and optional sub-capabilities."""

    instruction: str
    llm_config: LLMConfig
    capabilities: list[BaseCapability] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# BaseTool
# ──────────────────────────────────────────────────────────────────────


class BaseTool(BaseCapability):
    """Deterministic function wrapped as a capability."""

    handler: Callable[..., Any]

    model_config = {"arbitrary_types_allowed": True}


# ──────────────────────────────────────────────────────────────────────
# BaseWorkflow
# ──────────────────────────────────────────────────────────────────────


class BaseWorkflow(BaseCapability):
    """Composite capability — an ordered list of sub-capabilities."""

    steps: list[BaseCapability] = Field(default_factory=list)
