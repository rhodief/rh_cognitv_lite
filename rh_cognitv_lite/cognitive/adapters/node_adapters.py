from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from rh_cognitv_lite.execution_platform.execution import Execution
from rh_cognitv_lite.execution_platform.models import RetryConfig

from ..nodes import BaseExecutionNode, FunctionNode, ObjectNode, TextNode
from .llm_adapter import LLMAdapterProtocol, LLMRequest


# ──────────────────────────────────────────────────────────────────────
# Protocol
# ──────────────────────────────────────────────────────────────────────


class ExecutionNodeAdapterProtocol(ABC):
    """Converts a ``BaseExecutionNode`` into a platform-runnable ``Execution``."""

    @abstractmethod
    def to_execution(self, node: BaseExecutionNode) -> Execution:
        """Build an ``Execution`` from the node blueprint."""
        ...


# ──────────────────────────────────────────────────────────────────────
# Concrete adapters
# ──────────────────────────────────────────────────────────────────────


class TextNodeAdapter(ExecutionNodeAdapterProtocol):
    """Converts a ``TextNode`` into an ``Execution`` that calls the LLM adapter."""

    def __init__(self, llm_adapter: LLMAdapterProtocol) -> None:
        self._llm_adapter = llm_adapter

    def to_execution(self, node: BaseExecutionNode) -> Execution:
        if not isinstance(node, TextNode):
            raise TypeError(f"TextNodeAdapter expects TextNode, got {type(node).__name__}")

        llm_adapter = self._llm_adapter
        text_node = node

        async def handler(input_data: Any) -> str:
            messages = [{"role": "user", "content": text_node.instruction}]
            request = LLMRequest(
                model=text_node.llm_config.model,
                messages=messages,
                config=text_node.llm_config,
            )
            response = await llm_adapter.complete(request)
            return response.content or ""

        return Execution(
            name=text_node.name,
            description=text_node.description,
            kind="text",
            handler=handler,
            input_data=None,
        )


class ObjectNodeAdapter(ExecutionNodeAdapterProtocol):
    """Converts an ``ObjectNode`` into an ``Execution`` that calls the LLM adapter
    and validates the response against the output model."""

    def __init__(self, llm_adapter: LLMAdapterProtocol) -> None:
        self._llm_adapter = llm_adapter

    def to_execution(self, node: BaseExecutionNode) -> Execution:
        if not isinstance(node, ObjectNode):
            raise TypeError(f"ObjectNodeAdapter expects ObjectNode, got {type(node).__name__}")

        llm_adapter = self._llm_adapter
        object_node = node

        async def handler(input_data: Any) -> Any:
            messages = [{"role": "user", "content": object_node.instruction}]
            request = LLMRequest(
                model=object_node.llm_config.model,
                messages=messages,
                config=object_node.llm_config,
                tools=object_node.llm_config.tool_definitions,
            )
            response = await llm_adapter.complete(request)

            if object_node.output_model is not None and response.tool_calls:
                return object_node.output_model.model_validate(
                    response.tool_calls[0].arguments
                )
            return response.content or ""

        retry_config = (
            RetryConfig(max_attempts=3)
            if object_node.retry_on_validation_failure
            else None
        )

        return Execution(
            name=object_node.name,
            description=object_node.description,
            kind="object",
            handler=handler,
            input_data=None,
            retry_config=retry_config,
            retry_aware=object_node.retry_on_validation_failure,
        )


class FunctionNodeAdapter(ExecutionNodeAdapterProtocol):
    """Converts a ``FunctionNode`` into an ``Execution`` that calls the handler directly."""

    def to_execution(self, node: BaseExecutionNode) -> Execution:
        if not isinstance(node, FunctionNode):
            raise TypeError(f"FunctionNodeAdapter expects FunctionNode, got {type(node).__name__}")

        return Execution(
            name=node.name,
            description=node.description,
            kind="function",
            handler=node.handler,
            input_data=None,
        )
