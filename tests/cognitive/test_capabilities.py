"""Phase 2 unit tests — Capabilities & CognitiveResult."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from rh_cognitv_lite.cognitive.capabilities import (
    BaseCapability,
    BaseSkill,
    BaseTool,
    BaseWorkflow,
)
from rh_cognitv_lite.cognitive.nodes import LLMConfig
from rh_cognitv_lite.cognitive.results import (
    CognitiveResult,
    EscalationInfo,
    FailInfo,
)
from rh_cognitv_lite.execution_platform.models import ExecutionResult, ResultMetadata


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


def _ok_result(value: Any = None) -> ExecutionResult[Any]:
    return ExecutionResult(ok=True, value=value)


def _fail_result(msg: str = "boom") -> ExecutionResult[Any]:
    return ExecutionResult(ok=False, error_message=msg, error_category="permanent")


def _llm_config() -> LLMConfig:
    return LLMConfig(model="gpt-4")


# ──────────────────────────────────────────────────────────────────────
# BaseCapability
# ──────────────────────────────────────────────────────────────────────


class TestBaseCapability:
    def test_creation(self):
        cap = BaseCapability(
            id="cap.test",
            name="Test",
            description="A test capability",
            when_to_use="Always",
        )
        assert cap.id == "cap.test"
        assert cap.name == "Test"
        assert cap.input_schema == {}
        assert cap.output_schema == {}

    def test_with_schemas(self):
        cap = BaseCapability(
            id="cap.typed",
            name="Typed",
            description="D",
            when_to_use="W",
            input_schema={"type": "object", "required": ["q"]},
            output_schema={"type": "object", "required": ["a"]},
        )
        assert "required" in cap.input_schema
        assert "required" in cap.output_schema

    def test_register_execution_graph_raises(self):
        cap = BaseCapability(
            id="cap.base", name="Base", description="D", when_to_use="W"
        )
        with pytest.raises(NotImplementedError):
            cap.register_execution_graph()

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            BaseCapability(id="c")  # type: ignore[call-arg]

    def test_serialization_round_trip(self):
        cap = BaseCapability(
            id="cap.rt",
            name="RT",
            description="D",
            when_to_use="W",
            input_schema={"type": "object"},
        )
        data = cap.model_dump()
        restored = BaseCapability(**data)
        assert restored == cap

    def test_json_round_trip(self):
        cap = BaseCapability(
            id="cap.json", name="J", description="D", when_to_use="W"
        )
        json_str = cap.model_dump_json()
        restored = BaseCapability.model_validate_json(json_str)
        assert restored == cap


# ──────────────────────────────────────────────────────────────────────
# BaseSkill
# ──────────────────────────────────────────────────────────────────────


class TestBaseSkill:
    def test_creation(self):
        skill = BaseSkill(
            id="skills.summarizer",
            name="Summarizer",
            description="Summarizes text",
            when_to_use="When asked to summarize",
            instruction="You are a summarizer.",
            llm_config=_llm_config(),
        )
        assert skill.id == "skills.summarizer"
        assert skill.instruction == "You are a summarizer."
        assert skill.capabilities == []
        assert skill.constraints == []

    def test_with_capabilities_and_constraints(self):
        sub_tool = BaseTool(
            id="tools.search",
            name="Search",
            description="Searches",
            when_to_use="When searching",
            handler=lambda d: d,
        )
        skill = BaseSkill(
            id="skills.researcher",
            name="Researcher",
            description="Researches topics",
            when_to_use="For research tasks",
            instruction="You are a researcher.",
            llm_config=_llm_config(),
            capabilities=[sub_tool],
            constraints=["Stay on topic", "Be concise"],
        )
        assert len(skill.capabilities) == 1
        assert skill.capabilities[0].id == "tools.search"
        assert len(skill.constraints) == 2

    def test_inherits_base_fields(self):
        skill = BaseSkill(
            id="s.1",
            name="S",
            description="D",
            when_to_use="W",
            instruction="I",
            llm_config=_llm_config(),
            input_schema={"type": "object"},
        )
        assert isinstance(skill, BaseCapability)
        assert skill.input_schema == {"type": "object"}

    def test_register_execution_graph_raises(self):
        skill = BaseSkill(
            id="s.1",
            name="S",
            description="D",
            when_to_use="W",
            instruction="I",
            llm_config=_llm_config(),
        )
        with pytest.raises(NotImplementedError):
            skill.register_execution_graph()

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            BaseSkill(
                id="s.1", name="S", description="D", when_to_use="W"
            )  # type: ignore[call-arg]

    def test_serialization_round_trip(self):
        skill = BaseSkill(
            id="s.rt",
            name="N",
            description="D",
            when_to_use="W",
            instruction="I",
            llm_config=LLMConfig(model="gpt-4", temperature=0.3),
            constraints=["C"],
        )
        data = skill.model_dump()
        restored = BaseSkill(**data)
        assert restored.llm_config.model == "gpt-4"
        assert restored.constraints == ["C"]

    def test_collection_field_isolation(self):
        a = BaseSkill(
            id="a", name="A", description="D", when_to_use="W",
            instruction="I", llm_config=_llm_config(),
        )
        b = BaseSkill(
            id="b", name="B", description="D", when_to_use="W",
            instruction="I", llm_config=_llm_config(),
        )
        a.constraints.append("X")
        assert b.constraints == []


# ──────────────────────────────────────────────────────────────────────
# BaseTool
# ──────────────────────────────────────────────────────────────────────


def _sample_tool_handler(data: dict[str, Any]) -> dict[str, Any]:
    return {"doubled": data.get("x", 0) * 2}


class TestBaseTool:
    def test_creation(self):
        tool = BaseTool(
            id="tools.calc",
            name="Calculator",
            description="Doubles numbers",
            when_to_use="For math",
            handler=_sample_tool_handler,
        )
        assert tool.id == "tools.calc"
        assert tool.handler is _sample_tool_handler

    def test_handler_callable(self):
        tool = BaseTool(
            id="tools.echo",
            name="Echo",
            description="Returns input",
            when_to_use="For echo",
            handler=lambda d: d,
        )
        assert tool.handler({"a": 1}) == {"a": 1}

    def test_inherits_base_fields(self):
        tool = BaseTool(
            id="t.1",
            name="T",
            description="D",
            when_to_use="W",
            handler=_sample_tool_handler,
        )
        assert isinstance(tool, BaseCapability)

    def test_register_execution_graph_raises(self):
        tool = BaseTool(
            id="t.1",
            name="T",
            description="D",
            when_to_use="W",
            handler=_sample_tool_handler,
        )
        with pytest.raises(NotImplementedError):
            tool.register_execution_graph()

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            BaseTool(id="t.1", name="T", description="D", when_to_use="W")  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────
# BaseWorkflow
# ──────────────────────────────────────────────────────────────────────


class TestBaseWorkflow:
    def test_creation(self):
        wf = BaseWorkflow(
            id="workflows.pipeline",
            name="Pipeline",
            description="A multi-step pipeline",
            when_to_use="For complex tasks",
        )
        assert wf.id == "workflows.pipeline"
        assert wf.steps == []

    def test_with_steps(self):
        tool = BaseTool(
            id="t.1", name="T1", description="D", when_to_use="W",
            handler=_sample_tool_handler,
        )
        skill = BaseSkill(
            id="s.1", name="S1", description="D", when_to_use="W",
            instruction="I", llm_config=_llm_config(),
        )
        wf = BaseWorkflow(
            id="wf.1",
            name="WF",
            description="D",
            when_to_use="W",
            steps=[tool, skill],
        )
        assert len(wf.steps) == 2
        assert isinstance(wf.steps[0], BaseTool)
        assert isinstance(wf.steps[1], BaseSkill)

    def test_nested_workflow(self):
        inner = BaseWorkflow(
            id="wf.inner",
            name="Inner",
            description="D",
            when_to_use="W",
            steps=[
                BaseTool(
                    id="t.1", name="T", description="D", when_to_use="W",
                    handler=_sample_tool_handler,
                ),
            ],
        )
        outer = BaseWorkflow(
            id="wf.outer",
            name="Outer",
            description="D",
            when_to_use="W",
            steps=[inner],
        )
        assert len(outer.steps) == 1
        assert isinstance(outer.steps[0], BaseWorkflow)

    def test_inherits_base_fields(self):
        wf = BaseWorkflow(
            id="wf.1", name="WF", description="D", when_to_use="W",
        )
        assert isinstance(wf, BaseCapability)

    def test_register_execution_graph_raises(self):
        wf = BaseWorkflow(
            id="wf.1", name="WF", description="D", when_to_use="W",
        )
        with pytest.raises(NotImplementedError):
            wf.register_execution_graph()

    def test_collection_field_isolation(self):
        a = BaseWorkflow(id="a", name="A", description="D", when_to_use="W")
        b = BaseWorkflow(id="b", name="B", description="D", when_to_use="W")
        a.steps.append(
            BaseTool(id="t.x", name="X", description="D", when_to_use="W",
                     handler=_sample_tool_handler)
        )
        assert b.steps == []


# ──────────────────────────────────────────────────────────────────────
# Cross-cutting: isinstance & polymorphism
# ──────────────────────────────────────────────────────────────────────


class TestCapabilityPolymorphism:
    def test_all_are_base_capability(self):
        caps: list[BaseCapability] = [
            BaseCapability(id="c", name="C", description="D", when_to_use="W"),
            BaseSkill(
                id="s", name="S", description="D", when_to_use="W",
                instruction="I", llm_config=_llm_config(),
            ),
            BaseTool(
                id="t", name="T", description="D", when_to_use="W",
                handler=_sample_tool_handler,
            ),
            BaseWorkflow(id="w", name="W", description="D", when_to_use="W"),
        ]
        for cap in caps:
            assert isinstance(cap, BaseCapability)

    def test_type_discrimination(self):
        """Can distinguish capability subtypes at runtime."""
        skill = BaseSkill(
            id="s", name="S", description="D", when_to_use="W",
            instruction="I", llm_config=_llm_config(),
        )
        tool = BaseTool(
            id="t", name="T", description="D", when_to_use="W",
            handler=_sample_tool_handler,
        )
        wf = BaseWorkflow(id="w", name="W", description="D", when_to_use="W")

        assert isinstance(skill, BaseSkill) and not isinstance(skill, BaseTool)
        assert isinstance(tool, BaseTool) and not isinstance(tool, BaseSkill)
        assert isinstance(wf, BaseWorkflow)


# ──────────────────────────────────────────────────────────────────────
# EscalationInfo & FailInfo
# ──────────────────────────────────────────────────────────────────────


class TestEscalationInfo:
    def test_creation(self):
        info = EscalationInfo(
            reason="Cannot handle math",
            capability_id="skills.summarizer",
        )
        assert info.reason == "Cannot handle math"
        assert info.capability_id == "skills.summarizer"
        assert info.context == {}

    def test_with_context(self):
        info = EscalationInfo(
            reason="Needs approval",
            capability_id="s.1",
            context={"user_input": "delete everything"},
        )
        assert info.context["user_input"] == "delete everything"

    def test_serialization_round_trip(self):
        info = EscalationInfo(
            reason="R", capability_id="c.1", context={"k": "v"}
        )
        restored = EscalationInfo(**info.model_dump())
        assert restored == info


class TestFailInfo:
    def test_creation(self):
        info = FailInfo(
            reason="LLM returned gibberish",
            error_type="OutputValidationError",
        )
        assert info.reason == "LLM returned gibberish"
        assert info.error_type == "OutputValidationError"
        assert info.details == {}

    def test_with_details(self):
        info = FailInfo(
            reason="Timeout",
            error_type="TimeoutError",
            details={"elapsed_ms": 30000},
        )
        assert info.details["elapsed_ms"] == 30000

    def test_serialization_round_trip(self):
        info = FailInfo(reason="R", error_type="E", details={"x": 1})
        restored = FailInfo(**info.model_dump())
        assert restored == info


# ──────────────────────────────────────────────────────────────────────
# CognitiveResult
# ──────────────────────────────────────────────────────────────────────


class TestCognitiveResult:
    def test_response_factory(self):
        er = _ok_result({"answer": "42"})
        cr = CognitiveResult.response(value={"answer": "42"}, execution_result=er)
        assert cr.kind == "response"
        assert cr.value == {"answer": "42"}
        assert cr.escalation is None
        assert cr.error is None
        assert cr.execution_result.ok is True

    def test_escalate_factory(self):
        er = _fail_result("cannot handle")
        info = EscalationInfo(reason="Too hard", capability_id="s.1")
        cr = CognitiveResult.escalate(info=info, execution_result=er)
        assert cr.kind == "escalate"
        assert cr.escalation is not None
        assert cr.escalation.reason == "Too hard"
        assert cr.value is None

    def test_fail_factory(self):
        er = _fail_result("boom")
        info = FailInfo(reason="Unrecoverable", error_type="PermanentError")
        cr = CognitiveResult.fail(info=info, execution_result=er)
        assert cr.kind == "fail"
        assert cr.error is not None
        assert cr.error.error_type == "PermanentError"
        assert cr.value is None

    def test_default_execution_result(self):
        cr = CognitiveResult(kind="fail")
        assert cr.execution_result.ok is False

    def test_serialization_round_trip_response(self):
        er = _ok_result({"v": 1})
        cr = CognitiveResult.response(value={"v": 1}, execution_result=er)
        data = cr.model_dump()
        restored = CognitiveResult(**data)
        assert restored.kind == "response"
        assert restored.value == {"v": 1}
        assert restored.execution_result.ok is True

    def test_serialization_round_trip_escalate(self):
        er = _fail_result("x")
        info = EscalationInfo(reason="R", capability_id="c.1")
        cr = CognitiveResult.escalate(info=info, execution_result=er)
        data = cr.model_dump()
        restored = CognitiveResult(**data)
        assert restored.kind == "escalate"
        assert restored.escalation is not None
        assert restored.escalation.reason == "R"

    def test_serialization_round_trip_fail(self):
        er = _fail_result("x")
        info = FailInfo(reason="R", error_type="E")
        cr = CognitiveResult.fail(info=info, execution_result=er)
        data = cr.model_dump()
        restored = CognitiveResult(**data)
        assert restored.kind == "fail"
        assert restored.error is not None

    def test_json_round_trip(self):
        er = _ok_result("text")
        cr = CognitiveResult.response(value="text", execution_result=er)
        json_str = cr.model_dump_json()
        restored = CognitiveResult.model_validate_json(json_str)
        assert restored.kind == "response"
        assert restored.value == "text"

    def test_wraps_execution_result(self):
        """CognitiveResult preserves the underlying platform result."""
        er = ExecutionResult(
            ok=True,
            value={"data": "payload"},
            metadata=ResultMetadata(attempt=2, duration_ms=150.0),
        )
        cr = CognitiveResult.response(value={"data": "payload"}, execution_result=er)
        assert cr.execution_result.metadata.attempt == 2
        assert cr.execution_result.metadata.duration_ms == 150.0


# ──────────────────────────────────────────────────────────────────────
# Package imports
# ──────────────────────────────────────────────────────────────────────


class TestImportsFromPackage:
    def test_capabilities_importable_from_cognitive(self):
        from rh_cognitv_lite.cognitive import (
            BaseCapability,
            BaseSkill,
            BaseTool,
            BaseWorkflow,
        )

        assert BaseCapability is not None
        assert BaseSkill is not None
        assert BaseTool is not None
        assert BaseWorkflow is not None

    def test_results_importable_from_cognitive(self):
        from rh_cognitv_lite.cognitive import (
            CognitiveResult,
            EscalationInfo,
            FailInfo,
        )

        assert CognitiveResult is not None
        assert EscalationInfo is not None
        assert FailInfo is not None
