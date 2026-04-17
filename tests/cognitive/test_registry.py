"""Phase 6 unit tests — CapabilityRegistry (DD-16)."""
from __future__ import annotations

import pytest

from rh_cognitv_lite.cognitive.capabilities import (
    BaseCapability,
    BaseSkill,
    BaseTool,
    BaseWorkflow,
)
from rh_cognitv_lite.cognitive.nodes import LLMConfig
from rh_cognitv_lite.cognitive.registry import CapabilityRegistry


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _cap(id: str = "cap.1", name: str = "cap1") -> BaseCapability:
    return BaseCapability(
        id=id, name=name, description="d", when_to_use="w",
    )


def _skill(id: str = "skills.summarizer") -> BaseSkill:
    return BaseSkill(
        id=id, name="summarizer", description="d", when_to_use="w",
        instruction="Summarize.", llm_config=LLMConfig(model="gpt-4"),
    )


def _tool(id: str = "tools.calendar") -> BaseTool:
    return BaseTool(
        id=id, name="calendar", description="d", when_to_use="w",
        handler=lambda x: x,
    )


def _workflow(id: str = "workflows.plan") -> BaseWorkflow:
    return BaseWorkflow(
        id=id, name="plan", description="d", when_to_use="w",
    )


# ══════════════════════════════════════════════════════════════════════
# Registration
# ══════════════════════════════════════════════════════════════════════


class TestRegistration:
    def test_register_and_get(self) -> None:
        reg = CapabilityRegistry()
        cap = _cap()
        reg.register(cap)
        assert reg.get("cap.1") is cap

    def test_register_duplicate_raises(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_cap())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_cap())

    def test_has_registered(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_cap())
        assert reg.has("cap.1") is True

    def test_has_missing(self) -> None:
        reg = CapabilityRegistry()
        assert reg.has("nope") is False

    def test_count(self) -> None:
        reg = CapabilityRegistry()
        assert reg.count == 0
        reg.register(_cap("a"))
        reg.register(_cap("b"))
        assert reg.count == 2


# ══════════════════════════════════════════════════════════════════════
# Get / KeyError
# ══════════════════════════════════════════════════════════════════════


class TestGet:
    def test_get_missing_raises(self) -> None:
        reg = CapabilityRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.get("missing")

    def test_get_returns_correct_instance(self) -> None:
        reg = CapabilityRegistry()
        s = _skill()
        t = _tool()
        reg.register(s)
        reg.register(t)
        assert reg.get("skills.summarizer") is s
        assert reg.get("tools.calendar") is t


# ══════════════════════════════════════════════════════════════════════
# Unregister
# ══════════════════════════════════════════════════════════════════════


class TestUnregister:
    def test_unregister(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_cap())
        reg.unregister("cap.1")
        assert reg.has("cap.1") is False
        assert reg.count == 0

    def test_unregister_missing_raises(self) -> None:
        reg = CapabilityRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.unregister("missing")

    def test_unregister_allows_re_register(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_cap())
        reg.unregister("cap.1")
        new = _cap()
        reg.register(new)
        assert reg.get("cap.1") is new


# ══════════════════════════════════════════════════════════════════════
# Listing
# ══════════════════════════════════════════════════════════════════════


class TestListing:
    def test_list_all_empty(self) -> None:
        reg = CapabilityRegistry()
        assert reg.list_all() == []

    def test_list_all(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_skill())
        reg.register(_tool())
        reg.register(_workflow())
        assert len(reg.list_all()) == 3

    def test_list_by_type_skill(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_skill())
        reg.register(_tool())
        reg.register(_workflow())
        skills = reg.list_by_type(BaseSkill)
        assert len(skills) == 1
        assert isinstance(skills[0], BaseSkill)

    def test_list_by_type_tool(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_skill())
        reg.register(_tool())
        tools = reg.list_by_type(BaseTool)
        assert len(tools) == 1
        assert isinstance(tools[0], BaseTool)

    def test_list_by_type_workflow(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_workflow())
        workflows = reg.list_by_type(BaseWorkflow)
        assert len(workflows) == 1

    def test_list_by_type_base_returns_all(self) -> None:
        """All subclasses are instances of BaseCapability."""
        reg = CapabilityRegistry()
        reg.register(_skill())
        reg.register(_tool())
        reg.register(_workflow())
        all_caps = reg.list_by_type(BaseCapability)
        assert len(all_caps) == 3

    def test_list_by_type_none_matching(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_cap())
        assert reg.list_by_type(BaseSkill) == []

    def test_list_all_preserves_order(self) -> None:
        reg = CapabilityRegistry()
        ids = ["a", "b", "c", "d"]
        for cid in ids:
            reg.register(_cap(cid))
        assert [c.id for c in reg.list_all()] == ids


# ══════════════════════════════════════════════════════════════════════
# Multiple types
# ══════════════════════════════════════════════════════════════════════


class TestMultipleTypes:
    def test_mixed_registry(self) -> None:
        reg = CapabilityRegistry()
        reg.register(_skill("s1"))
        reg.register(_skill("s2"))
        reg.register(_tool("t1"))
        reg.register(_workflow("w1"))
        assert reg.count == 4
        assert len(reg.list_by_type(BaseSkill)) == 2
        assert len(reg.list_by_type(BaseTool)) == 1
        assert len(reg.list_by_type(BaseWorkflow)) == 1
