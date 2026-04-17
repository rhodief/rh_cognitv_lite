from __future__ import annotations

from typing import Any

import pytest

from rh_cognitv_lite.cognitive.context import (
    ContextRef,
    ContextResolverProtocol,
    ContextResolverRegistry,
    ContextStore,
    ScopeFrame,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────


class _StubResolver(ContextResolverProtocol):
    """Resolver that reads from the context store."""

    def resolve(self, key: str, store: ContextStore) -> Any:
        val = store.get(key)
        if val is None:
            raise KeyError(key)
        return val


class _StaticResolver(ContextResolverProtocol):
    """Resolver that returns from a fixed dict."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def resolve(self, key: str, store: ContextStore) -> Any:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]


# ══════════════════════════════════════════════════════════════════════
# ContextRef
# ══════════════════════════════════════════════════════════════════════


class TestContextRef:
    def test_create_ref(self) -> None:
        ref = ContextRef(scope="memory", key="user_name")
        assert ref.scope == "memory"
        assert ref.key == "user_name"

    def test_ref_equality(self) -> None:
        a = ContextRef(scope="memory", key="x")
        b = ContextRef(scope="memory", key="x")
        assert a == b

    def test_ref_different_scope(self) -> None:
        a = ContextRef(scope="memory", key="x")
        b = ContextRef(scope="artifact", key="x")
        assert a != b

    def test_ref_serialization(self) -> None:
        ref = ContextRef(scope="skill_output", key="result")
        d = ref.model_dump()
        assert d == {"scope": "skill_output", "key": "result"}
        assert ContextRef.model_validate(d) == ref


# ══════════════════════════════════════════════════════════════════════
# ScopeFrame
# ══════════════════════════════════════════════════════════════════════


class TestScopeFrame:
    def test_create_empty_frame(self) -> None:
        f = ScopeFrame(name="test")
        assert f.name == "test"
        assert f.data == {}

    def test_create_frame_with_data(self) -> None:
        f = ScopeFrame(name="f1", data={"a": 1, "b": 2})
        assert f.data["a"] == 1
        assert f.data["b"] == 2

    def test_frame_serialization(self) -> None:
        f = ScopeFrame(name="f1", data={"x": 42})
        d = f.model_dump()
        assert d == {"name": "f1", "data": {"x": 42}}
        assert ScopeFrame.model_validate(d) == f


# ══════════════════════════════════════════════════════════════════════
# ContextStore — frame management
# ══════════════════════════════════════════════════════════════════════


class TestContextStoreFrames:
    def test_default_has_root_frame(self) -> None:
        store = ContextStore()
        assert store.depth == 1
        assert store.current_frame.name == "root"

    def test_push_frame(self) -> None:
        store = ContextStore()
        store.push_frame("iter_0")
        assert store.depth == 2
        assert store.current_frame.name == "iter_0"

    def test_pop_frame(self) -> None:
        store = ContextStore()
        store.push_frame("child")
        store.put("x", 1)
        popped = store.pop_frame()
        assert popped.name == "child"
        assert popped.data == {"x": 1}
        assert store.depth == 1

    def test_pop_root_raises(self) -> None:
        store = ContextStore()
        with pytest.raises(IndexError, match="Cannot pop the root frame"):
            store.pop_frame()

    def test_push_multiple_frames(self) -> None:
        store = ContextStore()
        store.push_frame("a")
        store.push_frame("b")
        store.push_frame("c")
        assert store.depth == 4
        assert store.current_frame.name == "c"


# ══════════════════════════════════════════════════════════════════════
# ContextStore — read / write
# ══════════════════════════════════════════════════════════════════════


class TestContextStoreReadWrite:
    def test_put_and_get(self) -> None:
        store = ContextStore()
        store.put("name", "Alice")
        assert store.get("name") == "Alice"

    def test_get_missing_returns_default(self) -> None:
        store = ContextStore()
        assert store.get("missing") is None
        assert store.get("missing", 42) == 42

    def test_put_writes_to_topmost(self) -> None:
        store = ContextStore()
        store.put("x", "root_val")
        store.push_frame("child")
        store.put("x", "child_val")
        assert store.current_frame.data["x"] == "child_val"
        assert store.frames[0].data["x"] == "root_val"

    def test_get_shadows_inner_over_outer(self) -> None:
        store = ContextStore()
        store.put("x", "root")
        store.push_frame("child")
        store.put("x", "child")
        assert store.get("x") == "child"

    def test_get_falls_through_to_outer(self) -> None:
        store = ContextStore()
        store.put("x", "root_val")
        store.push_frame("child")
        assert store.get("x") == "root_val"

    def test_shadow_removed_after_pop(self) -> None:
        store = ContextStore()
        store.put("x", "root")
        store.push_frame("child")
        store.put("x", "child")
        store.pop_frame()
        assert store.get("x") == "root"

    def test_has_key(self) -> None:
        store = ContextStore()
        store.put("a", 1)
        assert store.has("a") is True
        assert store.has("b") is False

    def test_has_key_in_outer_frame(self) -> None:
        store = ContextStore()
        store.put("a", 1)
        store.push_frame("child")
        assert store.has("a") is True

    def test_keys_deduplicates_and_shows_visible(self) -> None:
        store = ContextStore()
        store.put("a", 1)
        store.put("b", 2)
        store.push_frame("child")
        store.put("b", 3)
        store.put("c", 4)
        keys = store.keys()
        assert "a" in keys
        assert "b" in keys
        assert "c" in keys
        assert len(keys) == 3

    def test_get_scoped(self) -> None:
        store = ContextStore()
        store.put("x", "root_val")
        store.push_frame("child")
        store.put("x", "child_val")
        assert store.get_scoped("root", "x") == "root_val"
        assert store.get_scoped("child", "x") == "child_val"

    def test_get_scoped_missing(self) -> None:
        store = ContextStore()
        assert store.get_scoped("nonexistent", "key") is None
        assert store.get_scoped("nonexistent", "key", "fallback") == "fallback"

    def test_get_scoped_picks_topmost_matching_name(self) -> None:
        store = ContextStore()
        store.push_frame("iter")
        store.put("i", 0)
        store.push_frame("iter")
        store.put("i", 1)
        assert store.get_scoped("iter", "i") == 1


# ══════════════════════════════════════════════════════════════════════
# ContextStore — snapshot / restore
# ══════════════════════════════════════════════════════════════════════


class TestContextStoreSnapshot:
    def test_snapshot_roundtrip(self) -> None:
        store = ContextStore()
        store.put("a", 1)
        store.push_frame("child")
        store.put("b", 2)
        snap = store.snapshot()

        store2 = ContextStore()
        store2.restore(snap)
        assert store2.depth == 2
        assert store2.get("a") == 1
        assert store2.get("b") == 2

    def test_snapshot_is_independent(self) -> None:
        store = ContextStore()
        store.put("x", "before")
        snap = store.snapshot()
        store.put("x", "after")
        store2 = ContextStore()
        store2.restore(snap)
        assert store2.get("x") == "before"

    def test_restore_replaces_entirely(self) -> None:
        store = ContextStore()
        store.put("old", 1)
        snap = {"frames": [{"name": "root", "data": {"new": 2}}]}
        store.restore(snap)
        assert store.get("old") is None
        assert store.get("new") == 2
        assert store.depth == 1

    def test_snapshot_structure(self) -> None:
        store = ContextStore()
        store.put("k", "v")
        snap = store.snapshot()
        assert "frames" in snap
        assert len(snap["frames"]) == 1
        assert snap["frames"][0]["name"] == "root"
        assert snap["frames"][0]["data"] == {"k": "v"}


# ══════════════════════════════════════════════════════════════════════
# ContextResolverRegistry
# ══════════════════════════════════════════════════════════════════════


class TestContextResolverRegistry:
    def test_register_and_has(self) -> None:
        reg = ContextResolverRegistry()
        reg.register("memory", _StubResolver())
        assert reg.has("memory") is True
        assert reg.has("artifact") is False

    def test_get_resolver(self) -> None:
        resolver = _StubResolver()
        reg = ContextResolverRegistry()
        reg.register("memory", resolver)
        assert reg.get_resolver("memory") is resolver

    def test_get_resolver_missing_raises(self) -> None:
        reg = ContextResolverRegistry()
        with pytest.raises(KeyError, match="No resolver registered for scope 'x'"):
            reg.get_resolver("x")

    def test_resolve_single(self) -> None:
        reg = ContextResolverRegistry()
        reg.register("memory", _StaticResolver({"name": "Alice"}))
        store = ContextStore()
        ref = ContextRef(scope="memory", key="name")
        assert reg.resolve(ref, store) == "Alice"

    def test_resolve_raises_for_unknown_scope(self) -> None:
        reg = ContextResolverRegistry()
        store = ContextStore()
        ref = ContextRef(scope="unknown", key="k")
        with pytest.raises(KeyError):
            reg.resolve(ref, store)

    def test_resolve_all(self) -> None:
        reg = ContextResolverRegistry()
        reg.register("memory", _StaticResolver({"user": "Bob", "lang": "en"}))
        reg.register("artifact", _StaticResolver({"doc": "report.pdf"}))
        store = ContextStore()
        refs = [
            ContextRef(scope="memory", key="user"),
            ContextRef(scope="memory", key="lang"),
            ContextRef(scope="artifact", key="doc"),
        ]
        result = reg.resolve_all(refs, store)
        assert result == {"user": "Bob", "lang": "en", "doc": "report.pdf"}

    def test_resolve_all_empty(self) -> None:
        reg = ContextResolverRegistry()
        store = ContextStore()
        assert reg.resolve_all([], store) == {}

    def test_resolve_all_raises_on_missing_scope(self) -> None:
        reg = ContextResolverRegistry()
        store = ContextStore()
        refs = [ContextRef(scope="missing", key="k")]
        with pytest.raises(KeyError):
            reg.resolve_all(refs, store)

    def test_scopes_property(self) -> None:
        reg = ContextResolverRegistry()
        reg.register("memory", _StubResolver())
        reg.register("artifact", _StubResolver())
        assert sorted(reg.scopes) == ["artifact", "memory"]

    def test_register_overwrites(self) -> None:
        reg = ContextResolverRegistry()
        r1 = _StaticResolver({"x": 1})
        r2 = _StaticResolver({"x": 2})
        reg.register("s", r1)
        reg.register("s", r2)
        store = ContextStore()
        assert reg.resolve(ContextRef(scope="s", key="x"), store) == 2

    def test_resolver_uses_store(self) -> None:
        """Resolver can read from the store (e.g. skill_output resolver)."""
        reg = ContextResolverRegistry()
        reg.register("skill_output", _StubResolver())
        store = ContextStore()
        store.put("result", {"score": 0.95})
        ref = ContextRef(scope="skill_output", key="result")
        assert reg.resolve(ref, store) == {"score": 0.95}


# ══════════════════════════════════════════════════════════════════════
# Integration — ContextStore + Registry together
# ══════════════════════════════════════════════════════════════════════


class TestContextIntegration:
    def test_nested_frames_with_resolver(self) -> None:
        store = ContextStore()
        store.put("x", "root")
        store.push_frame("iter_0")
        store.put("x", "iter_val")

        reg = ContextResolverRegistry()
        reg.register("skill_output", _StubResolver())
        ref = ContextRef(scope="skill_output", key="x")
        assert reg.resolve(ref, store) == "iter_val"

        store.pop_frame()
        assert reg.resolve(ref, store) == "root"

    def test_snapshot_restore_with_resolver(self) -> None:
        store = ContextStore()
        store.put("key", "value")
        snap = store.snapshot()

        store2 = ContextStore()
        store2.restore(snap)
        reg = ContextResolverRegistry()
        reg.register("skill_output", _StubResolver())
        ref = ContextRef(scope="skill_output", key="key")
        assert reg.resolve(ref, store2) == "value"

    def test_resolve_all_picks_shadowed_values(self) -> None:
        store = ContextStore()
        store.put("a", "outer")
        store.push_frame("inner")
        store.put("a", "inner")
        store.put("b", "only_inner")

        reg = ContextResolverRegistry()
        reg.register("ctx", _StubResolver())
        refs = [
            ContextRef(scope="ctx", key="a"),
            ContextRef(scope="ctx", key="b"),
        ]
        result = reg.resolve_all(refs, store)
        assert result == {"a": "inner", "b": "only_inner"}
