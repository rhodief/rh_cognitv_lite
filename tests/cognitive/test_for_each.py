"""Phase 5 unit tests — ForEachNode model & ForEachNodeAdapter."""
from __future__ import annotations

from typing import Any

import pytest

from rh_cognitv_lite.cognitive.adapters.for_each_adapter import (
    ForEachNodeAdapter,
)
from rh_cognitv_lite.cognitive.context import ContextStore
from rh_cognitv_lite.cognitive.nodes import (
    BaseExecutionNode,
    ForEachNode,
    FunctionNode,
    LLMConfig,
    ObjectNode,
    TextNode,
)
from rh_cognitv_lite.execution_platform.event_bus import EventBus
from rh_cognitv_lite.execution_platform.execution import Execution, ExecutionPlatform


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _platform() -> ExecutionPlatform:
    return ExecutionPlatform(event_bus=EventBus())


def _fn_node(
    id: str = "body1",
    name: str = "body_fn",
    handler: Any = None,
) -> FunctionNode:
    if handler is None:
        handler = lambda x: x  # noqa: E731
    return FunctionNode(
        id=id,
        name=name,
        description="body function node",
        handler=handler,
    )


def _foreach_node(
    body_nodes: list[BaseExecutionNode] | None = None,
    items_ref: str = "items",
    parallel: bool = False,
    max_workers: int | None = None,
    result_key: str | None = None,
    id: str = "fe1",
    name: str = "for_each",
) -> ForEachNode:
    if body_nodes is None:
        body_nodes = [_fn_node()]
    return ForEachNode(
        id=id,
        name=name,
        description="iterate over items",
        items_ref=items_ref,
        body_nodes=body_nodes,
        parallel=parallel,
        max_workers=max_workers,
        result_key=result_key,
    )


# ══════════════════════════════════════════════════════════════════════
# ForEachNode model
# ══════════════════════════════════════════════════════════════════════


class TestForEachNodeModel:
    def test_defaults(self) -> None:
        node = _foreach_node()
        assert node.kind == "for_each"
        assert node.category == "flow"
        assert node.parallel is False
        assert node.max_workers is None
        assert node.result_key is None

    def test_kind_literal(self) -> None:
        node = _foreach_node()
        assert node.kind == "for_each"

    def test_category_is_flow(self) -> None:
        node = _foreach_node()
        assert node.category == "flow"

    def test_items_ref(self) -> None:
        node = _foreach_node(items_ref="my_list")
        assert node.items_ref == "my_list"

    def test_body_nodes_list(self) -> None:
        b1 = _fn_node(id="b1")
        b2 = _fn_node(id="b2")
        node = _foreach_node(body_nodes=[b1, b2])
        assert len(node.body_nodes) == 2
        assert node.body_nodes[0].id == "b1"
        assert node.body_nodes[1].id == "b2"

    def test_parallel_flag(self) -> None:
        node = _foreach_node(parallel=True, max_workers=3)
        assert node.parallel is True
        assert node.max_workers == 3

    def test_result_key(self) -> None:
        node = _foreach_node(result_key="collected")
        assert node.result_key == "collected"

    def test_serialization_roundtrip(self) -> None:
        node = _foreach_node(result_key="out", parallel=True, max_workers=2)
        d = node.model_dump()
        assert d["kind"] == "for_each"
        assert d["category"] == "flow"
        assert d["items_ref"] == "items"
        assert d["parallel"] is True
        assert d["max_workers"] == 2
        assert d["result_key"] == "out"

    def test_inherits_base_fields(self) -> None:
        node = _foreach_node()
        assert node.id == "fe1"
        assert node.name == "for_each"
        assert node.description == "iterate over items"

    def test_metadata_default(self) -> None:
        node = _foreach_node()
        assert node.metadata == {}


# ══════════════════════════════════════════════════════════════════════
# BaseExecutionNode category field
# ══════════════════════════════════════════════════════════════════════


class TestCategoryField:
    def test_text_node_defaults_action(self) -> None:
        node = TextNode(
            id="t", name="t", description="t",
            instruction="hi", llm_config=LLMConfig(model="gpt-4"),
        )
        assert node.category == "action"

    def test_object_node_defaults_action(self) -> None:
        node = ObjectNode(
            id="o", name="o", description="o",
            instruction="extract", llm_config=LLMConfig(model="gpt-4"),
        )
        assert node.category == "action"

    def test_function_node_defaults_action(self) -> None:
        node = FunctionNode(
            id="f", name="f", description="f", handler=lambda x: x,
        )
        assert node.category == "action"

    def test_foreach_node_defaults_flow(self) -> None:
        node = _foreach_node()
        assert node.category == "flow"

    def test_category_is_settable(self) -> None:
        node = FunctionNode(
            id="f", name="f", description="f",
            handler=lambda x: x, category="flow",
        )
        assert node.category == "flow"


# ══════════════════════════════════════════════════════════════════════
# ForEachNodeAdapter — type checking
# ══════════════════════════════════════════════════════════════════════


class TestForEachNodeAdapterTypeCheck:
    def test_rejects_non_foreach_node(self) -> None:
        adapter = ForEachNodeAdapter(
            platform=_platform(), context_store=ContextStore(),
        )
        non_foreach = _fn_node()
        with pytest.raises(TypeError, match="ForEachNodeAdapter expects ForEachNode"):
            adapter.to_execution(non_foreach)

    def test_returns_execution(self) -> None:
        adapter = ForEachNodeAdapter(
            platform=_platform(), context_store=ContextStore(),
        )
        node = _foreach_node()
        execution = adapter.to_execution(node)
        assert isinstance(execution, Execution)
        assert execution.name == "for_each"
        assert execution.kind == "for_each"


# ══════════════════════════════════════════════════════════════════════
# ForEachNodeAdapter — sequential execution
# ══════════════════════════════════════════════════════════════════════


class TestForEachSequential:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_list(self) -> None:
        store = ContextStore()
        store.put("items", [])
        adapter = ForEachNodeAdapter(platform=_platform(), context_store=store)
        node = _foreach_node(result_key="out")
        execution = adapter.to_execution(node)
        platform = _platform()
        result = await platform(execution)
        assert result.ok
        assert result.value == []
        assert store.get("out") == []

    @pytest.mark.asyncio(loop_scope="function")
    async def test_missing_items_ref_treated_as_empty(self) -> None:
        store = ContextStore()
        adapter = ForEachNodeAdapter(platform=_platform(), context_store=store)
        node = _foreach_node(result_key="out")
        execution = adapter.to_execution(node)
        platform = _platform()
        result = await platform(execution)
        assert result.ok
        assert result.value == []

    @pytest.mark.asyncio(loop_scope="function")
    async def test_items_ref_not_list_raises(self) -> None:
        store = ContextStore()
        store.put("items", "not a list")
        adapter = ForEachNodeAdapter(platform=_platform(), context_store=store)
        node = _foreach_node()
        execution = adapter.to_execution(node)
        platform = _platform()
        result = await platform(execution)
        assert not result.ok

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sequential_iteration(self) -> None:
        """Body node doubles the item value; verify all results collected."""
        store = ContextStore()
        store.put("items", [1, 2, 3])

        def double(x: Any) -> int:
            return x * 2

        body = _fn_node(handler=double)

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function", handler=lambda data: double(store.get("item")),
                input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node(body_nodes=[body], result_key="results")
        execution = adapter.to_execution(node)
        result = await platform(execution)

        assert result.ok
        assert result.value == [2, 4, 6]
        assert store.get("results") == [2, 4, 6]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_context_frame_push_pop_per_iteration(self) -> None:
        """Verify frames are pushed and popped per iteration."""
        store = ContextStore()
        store.put("items", ["a", "b"])
        observed_depths: list[int] = []

        def capture_depth(x: Any) -> str:
            observed_depths.append(store.depth)
            return store.get("item")

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function", handler=capture_depth, input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node(result_key="out")
        execution = adapter.to_execution(node)
        result = await platform(execution)

        assert result.ok
        assert result.value == ["a", "b"]
        # During iteration, depth should be root + iteration frame = 2
        assert all(d == 2 for d in observed_depths)
        # After completion, only root frame remains
        assert store.depth == 1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_index_in_context(self) -> None:
        """Verify each iteration sees the correct index."""
        store = ContextStore()
        store.put("items", ["x", "y", "z"])
        observed_indices: list[int] = []

        def capture_index(x: Any) -> int:
            idx = store.get("index")
            observed_indices.append(idx)
            return idx

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function", handler=capture_index, input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node()
        execution = adapter.to_execution(node)
        await platform(execution)

        assert observed_indices == [0, 1, 2]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_multiple_body_nodes_sequential_chaining(self) -> None:
        """Multiple body nodes run sequentially within each iteration."""
        store = ContextStore()
        store.put("items", [10])
        call_order: list[str] = []

        def step_a(x: Any) -> int:
            call_order.append("a")
            return store.get("item") + 1

        def step_b(x: Any) -> int:
            call_order.append("b")
            return store.get("item") + 2

        body_a = _fn_node(id="a", name="step_a", handler=step_a)
        body_b = _fn_node(id="b", name="step_b", handler=step_b)

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function",
                handler=node.handler,  # type: ignore[union-attr]
                input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node(body_nodes=[body_a, body_b], result_key="out")
        execution = adapter.to_execution(node)
        result = await platform(execution)

        assert result.ok
        assert call_order == ["a", "b"]
        # Last body node's result is the iteration result
        assert result.value == [12]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_result_key_skips_store_write(self) -> None:
        store = ContextStore()
        store.put("items", [1])

        def identity(x: Any) -> Any:
            return store.get("item")

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function", handler=identity, input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node(result_key=None)
        execution = adapter.to_execution(node)
        result = await platform(execution)

        assert result.ok
        assert result.value == [1]
        assert store.has("results") is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_frame_popped_on_body_error(self) -> None:
        """Frame is popped even if a body node raises."""
        store = ContextStore()
        store.put("items", [1])

        def boom(x: Any) -> None:
            raise ValueError("body error")

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function", handler=boom, input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node()
        execution = adapter.to_execution(node)
        result = await platform(execution)

        # The body error is caught by the platform; frame must be cleaned up
        assert store.depth == 1


# ══════════════════════════════════════════════════════════════════════
# ForEachNodeAdapter — parallel execution
# ══════════════════════════════════════════════════════════════════════


class TestForEachParallel:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_parallel_iteration(self) -> None:
        store = ContextStore()
        store.put("items", [10, 20, 30])

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function",
                handler=lambda data: data["item"] * 3,
                input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node(parallel=True, max_workers=2, result_key="out")
        execution = adapter.to_execution(node)
        result = await platform(execution)

        assert result.ok
        assert result.value == [30, 60, 90]
        assert store.get("out") == [30, 60, 90]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_parallel_empty_list(self) -> None:
        store = ContextStore()
        store.put("items", [])
        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store,
        )
        node = _foreach_node(parallel=True, result_key="out")
        execution = adapter.to_execution(node)
        result = await platform(execution)
        assert result.ok
        assert result.value == []
        assert store.get("out") == []

    @pytest.mark.asyncio(loop_scope="function")
    async def test_parallel_max_workers_default(self) -> None:
        """When max_workers is None, defaults to len(items)."""
        store = ContextStore()
        store.put("items", [1, 2])

        def body_adapter(node: BaseExecutionNode) -> Execution:
            return Execution(
                name=node.name, description=node.description,
                kind="function",
                handler=lambda data: data["item"],
                input_data=None,
            )

        platform = _platform()
        adapter = ForEachNodeAdapter(
            platform=platform, context_store=store, body_adapter_fn=body_adapter,
        )
        node = _foreach_node(parallel=True, max_workers=None)
        execution = adapter.to_execution(node)
        result = await platform(execution)
        assert result.ok
        assert result.value == [1, 2]


# ══════════════════════════════════════════════════════════════════════
# ForEachNodeAdapter — without body_adapter_fn (default fallback)
# ══════════════════════════════════════════════════════════════════════


class TestForEachDefaultAdapter:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_default_adapter_uses_handler(self) -> None:
        """When no body_adapter_fn, the adapter falls back to calling the node's handler."""
        store = ContextStore()
        store.put("items", [5, 10])

        def add_one(x: Any) -> int:
            return (x or 0) + 1

        body = _fn_node(handler=add_one)
        platform = _platform()
        adapter = ForEachNodeAdapter(platform=platform, context_store=store)
        node = _foreach_node(body_nodes=[body], result_key="out")
        execution = adapter.to_execution(node)
        result = await platform(execution)

        assert result.ok
        # Default adapter passes last_value (None for first body node) as input_data
        assert result.value == [1, 1]
        assert store.get("out") == [1, 1]
