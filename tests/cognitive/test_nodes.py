"""Phase 1 unit tests — Execution Nodes & LLMConfig."""
from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from rh_cognitv_lite.cognitive.nodes import (
    BaseExecutionNode,
    FunctionNode,
    LLMConfig,
    ObjectNode,
    TextNode,
)


# ──────────────────────────────────────────────────────────────────────
# LLMConfig
# ──────────────────────────────────────────────────────────────────────


class TestLLMConfig:
    def test_defaults(self):
        cfg = LLMConfig(model="gpt-4")
        assert cfg.model == "gpt-4"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens is None
        assert cfg.top_p is None
        assert cfg.stop_sequences == []
        assert cfg.tool_definitions == []
        assert cfg.extra == {}

    def test_all_fields(self):
        cfg = LLMConfig(
            model="claude-3-opus",
            temperature=0.0,
            max_tokens=4096,
            top_p=0.9,
            stop_sequences=["END"],
            tool_definitions=[{"type": "function", "function": {"name": "search"}}],
            extra={"api_version": "2024-01"},
        )
        assert cfg.model == "claude-3-opus"
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 4096
        assert cfg.top_p == 0.9
        assert cfg.stop_sequences == ["END"]
        assert len(cfg.tool_definitions) == 1
        assert cfg.extra["api_version"] == "2024-01"

    def test_model_required(self):
        with pytest.raises(ValidationError):
            LLMConfig()  # type: ignore[call-arg]

    def test_serialization_round_trip(self):
        cfg = LLMConfig(model="gpt-4", temperature=0.3, max_tokens=1000)
        data = cfg.model_dump()
        restored = LLMConfig(**data)
        assert restored == cfg

    def test_json_round_trip(self):
        cfg = LLMConfig(model="gpt-4", extra={"key": "value"})
        json_str = cfg.model_dump_json()
        restored = LLMConfig.model_validate_json(json_str)
        assert restored == cfg

    def test_collection_field_isolation(self):
        """Default list/dict fields are independent across instances."""
        a = LLMConfig(model="m1")
        b = LLMConfig(model="m2")
        a.stop_sequences.append("X")
        assert b.stop_sequences == []


# ──────────────────────────────────────────────────────────────────────
# BaseExecutionNode
# ──────────────────────────────────────────────────────────────────────


class TestBaseExecutionNode:
    def test_creation(self):
        node = BaseExecutionNode(id="n1", name="Step 1", description="First step")
        assert node.id == "n1"
        assert node.name == "Step 1"
        assert node.description == "First step"
        assert node.input_schema is None
        assert node.output_schema is None
        assert node.metadata == {}

    def test_with_schemas(self):
        in_schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        out_schema = {"type": "object", "properties": {"y": {"type": "string"}}}
        node = BaseExecutionNode(
            id="n2",
            name="Validated",
            description="With schemas",
            input_schema=in_schema,
            output_schema=out_schema,
            metadata={"tier": "premium"},
        )
        assert node.input_schema == in_schema
        assert node.output_schema == out_schema
        assert node.metadata["tier"] == "premium"

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            BaseExecutionNode(id="n1")  # type: ignore[call-arg]

    def test_serialization_round_trip(self):
        node = BaseExecutionNode(
            id="n1", name="N", description="D", metadata={"k": "v"}
        )
        data = node.model_dump()
        restored = BaseExecutionNode(**data)
        assert restored == node


# ──────────────────────────────────────────────────────────────────────
# TextNode
# ──────────────────────────────────────────────────────────────────────


class TestTextNode:
    def test_defaults(self):
        node = TextNode(
            id="t1",
            name="Summarize",
            description="Summarize text",
            instruction="Summarize the following text:",
            llm_config=LLMConfig(model="gpt-4"),
        )
        assert node.kind == "text"
        assert node.streaming is False
        assert node.context_refs == []
        assert node.instruction == "Summarize the following text:"

    def test_kind_is_literal(self):
        """kind is always 'text' — cannot be overridden."""
        node = TextNode(
            id="t1",
            name="N",
            description="D",
            instruction="I",
            llm_config=LLMConfig(model="m"),
        )
        assert node.kind == "text"

    def test_streaming_and_context_refs(self):
        node = TextNode(
            id="t2",
            name="Stream",
            description="Streams",
            instruction="Do it",
            llm_config=LLMConfig(model="gpt-4"),
            streaming=True,
            context_refs=["memory.agent_identity", "artifact.report"],
        )
        assert node.streaming is True
        assert len(node.context_refs) == 2

    def test_inherits_base_fields(self):
        node = TextNode(
            id="t3",
            name="T",
            description="D",
            instruction="I",
            llm_config=LLMConfig(model="m"),
            input_schema={"type": "object"},
            metadata={"x": 1},
        )
        assert node.input_schema == {"type": "object"}
        assert node.metadata == {"x": 1}

    def test_serialization_round_trip(self):
        node = TextNode(
            id="t1",
            name="N",
            description="D",
            instruction="I",
            llm_config=LLMConfig(model="gpt-4", temperature=0.0),
            streaming=True,
            context_refs=["ref1"],
        )
        data = node.model_dump()
        restored = TextNode(**data)
        assert restored == node
        assert restored.llm_config.model == "gpt-4"

    def test_json_round_trip(self):
        node = TextNode(
            id="t1",
            name="N",
            description="D",
            instruction="I",
            llm_config=LLMConfig(model="m"),
        )
        json_str = node.model_dump_json()
        restored = TextNode.model_validate_json(json_str)
        assert restored == node

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            TextNode(id="t1", name="N", description="D")  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────
# ObjectNode
# ──────────────────────────────────────────────────────────────────────


class OutputModel(BaseModel):
    answer: str
    confidence: float


class TestObjectNode:
    def test_defaults(self):
        node = ObjectNode(
            id="o1",
            name="Extract",
            description="Extract data",
            instruction="Extract entities",
            llm_config=LLMConfig(model="gpt-4"),
        )
        assert node.kind == "object"
        assert node.output_model is None
        assert node.retry_on_validation_failure is True
        assert node.context_refs == []

    def test_with_output_model(self):
        node = ObjectNode(
            id="o2",
            name="Classify",
            description="Classify input",
            instruction="Classify",
            llm_config=LLMConfig(model="gpt-4"),
            output_model=OutputModel,
        )
        assert node.output_model is OutputModel

    def test_retry_on_validation_can_be_disabled(self):
        node = ObjectNode(
            id="o3",
            name="N",
            description="D",
            instruction="I",
            llm_config=LLMConfig(model="m"),
            retry_on_validation_failure=False,
        )
        assert node.retry_on_validation_failure is False

    def test_serialization_round_trip_without_output_model(self):
        node = ObjectNode(
            id="o1",
            name="N",
            description="D",
            instruction="I",
            llm_config=LLMConfig(model="m"),
            context_refs=["mem.x"],
        )
        data = node.model_dump()
        restored = ObjectNode(**data)
        assert restored.id == node.id
        assert restored.context_refs == ["mem.x"]

    def test_inherits_base_fields(self):
        node = ObjectNode(
            id="o1",
            name="N",
            description="D",
            instruction="I",
            llm_config=LLMConfig(model="m"),
            output_schema={"type": "object", "required": ["answer"]},
        )
        assert node.output_schema is not None

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ObjectNode(id="o1", name="N", description="D")  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────
# FunctionNode
# ──────────────────────────────────────────────────────────────────────


def sample_handler(data: dict[str, Any]) -> dict[str, Any]:
    return {"result": data.get("x", 0) * 2}


async def async_sample_handler(data: dict[str, Any]) -> dict[str, Any]:
    return {"result": data.get("x", 0) + 1}


class TestFunctionNode:
    def test_creation(self):
        node = FunctionNode(
            id="f1",
            name="Double",
            description="Doubles x",
            handler=sample_handler,
        )
        assert node.kind == "function"
        assert node.handler is sample_handler

    def test_handler_is_callable(self):
        node = FunctionNode(
            id="f2",
            name="N",
            description="D",
            handler=sample_handler,
        )
        result = node.handler({"x": 5})
        assert result == {"result": 10}

    def test_async_handler(self):
        node = FunctionNode(
            id="f3",
            name="Async",
            description="Async handler",
            handler=async_sample_handler,
        )
        assert node.handler is async_sample_handler

    def test_lambda_handler(self):
        node = FunctionNode(
            id="f4",
            name="Lambda",
            description="Lambda handler",
            handler=lambda d: {"v": 1},
        )
        assert node.handler(None) == {"v": 1}

    def test_inherits_base_fields(self):
        node = FunctionNode(
            id="f1",
            name="N",
            description="D",
            handler=sample_handler,
            metadata={"tag": "transform"},
        )
        assert node.metadata["tag"] == "transform"

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            FunctionNode(id="f1", name="N", description="D")  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────
# Cross-cutting
# ──────────────────────────────────────────────────────────────────────


class TestNodePolymorphism:
    def test_isinstance_checks(self):
        cfg = LLMConfig(model="m")
        text = TextNode(id="t", name="T", description="D", instruction="I", llm_config=cfg)
        obj = ObjectNode(id="o", name="O", description="D", instruction="I", llm_config=cfg)
        func = FunctionNode(id="f", name="F", description="D", handler=sample_handler)

        for node in [text, obj, func]:
            assert isinstance(node, BaseExecutionNode)

    def test_kind_discriminator(self):
        cfg = LLMConfig(model="m")
        text = TextNode(id="t", name="T", description="D", instruction="I", llm_config=cfg)
        obj = ObjectNode(id="o", name="O", description="D", instruction="I", llm_config=cfg)
        func = FunctionNode(id="f", name="F", description="D", handler=sample_handler)

        assert text.kind == "text"
        assert obj.kind == "object"
        assert func.kind == "function"


class TestImportsFromPackage:
    def test_nodes_importable_from_cognitive(self):
        from rh_cognitv_lite.cognitive import (
            BaseExecutionNode,
            FunctionNode,
            LLMConfig,
            ObjectNode,
            TextNode,
        )

        assert LLMConfig is not None
        assert BaseExecutionNode is not None
        assert TextNode is not None
        assert ObjectNode is not None
        assert FunctionNode is not None

    def test_adapter_types_importable_from_cognitive(self):
        from rh_cognitv_lite.cognitive import (
            LLMAdapterProtocol,
            LLMChunk,
            LLMRequest,
            LLMResponse,
            ToolCall,
        )

        assert LLMAdapterProtocol is not None
        assert LLMRequest is not None
        assert LLMResponse is not None
        assert ToolCall is not None
        assert LLMChunk is not None
