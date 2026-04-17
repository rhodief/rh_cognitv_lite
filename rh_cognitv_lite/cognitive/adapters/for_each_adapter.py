from __future__ import annotations

from typing import Any, Callable

from rh_cognitv_lite.execution_platform.execution import Execution, ExecutionPlatform
from rh_cognitv_lite.execution_platform.execution_runners import ParallelRunner
from rh_cognitv_lite.execution_platform.models import ExecutionResult, ParallelConfig

from ..context import ContextStore
from ..nodes import BaseExecutionNode, ForEachNode
from .node_adapters import ExecutionNodeAdapterProtocol

# Type alias: given a body node, return a platform Execution.
BodyAdapterFn = Callable[[BaseExecutionNode], Execution]


class ForEachNodeAdapter(ExecutionNodeAdapterProtocol):
    """Converts a ``ForEachNode`` into an ``Execution`` whose handler
    expands iterations at runtime.

    Each iteration pushes a context frame, runs the body nodes sequentially,
    collects results, and pops the frame.  If ``parallel=True``, iterations
    are dispatched via ``ParallelRunner``.
    """

    def __init__(
        self,
        platform: ExecutionPlatform,
        context_store: ContextStore,
        body_adapter_fn: BodyAdapterFn | None = None,
    ) -> None:
        self._platform = platform
        self._context_store = context_store
        self._body_adapter_fn = body_adapter_fn

    def to_execution(self, node: BaseExecutionNode) -> Execution:
        if not isinstance(node, ForEachNode):
            raise TypeError(
                f"ForEachNodeAdapter expects ForEachNode, got {type(node).__name__}"
            )

        foreach_node = node
        platform = self._platform
        context_store = self._context_store
        body_adapter_fn = self._body_adapter_fn

        async def handler(input_data: Any) -> list[Any]:
            items = context_store.get(foreach_node.items_ref)
            if items is None:
                items = []
            if not isinstance(items, list):
                raise TypeError(
                    f"items_ref '{foreach_node.items_ref}' resolved to "
                    f"{type(items).__name__}, expected list"
                )

            if not items:
                result: list[Any] = []
                if foreach_node.result_key is not None:
                    context_store.put(foreach_node.result_key, result)
                return result

            if foreach_node.parallel:
                return await _run_parallel(
                    foreach_node,
                    items,
                    platform,
                    context_store,
                    body_adapter_fn,
                )
            return await _run_sequential(
                foreach_node,
                items,
                platform,
                context_store,
                body_adapter_fn,
            )

        return Execution(
            name=foreach_node.name,
            description=foreach_node.description,
            kind="for_each",
            handler=handler,
            input_data=None,
        )


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


async def _run_single_iteration(
    foreach_node: ForEachNode,
    index: int,
    item: Any,
    platform: ExecutionPlatform,
    context_store: ContextStore,
    body_adapter_fn: BodyAdapterFn | None,
) -> Any:
    """Execute the body nodes for a single iteration, returning the last result value."""
    frame_name = f"foreach.{foreach_node.id}[{index}]"
    context_store.push_frame(frame_name)
    context_store.put("item", item)
    context_store.put("index", index)

    last_value: Any = None
    try:
        for body_node in foreach_node.body_nodes:
            if body_adapter_fn is not None:
                execution = body_adapter_fn(body_node)
            else:
                execution = Execution(
                    name=body_node.name,
                    description=body_node.description,
                    kind=getattr(body_node, "kind", "unknown"),
                    handler=getattr(body_node, "handler", _noop_handler),
                    input_data=last_value,
                )
            result: ExecutionResult[Any] = await platform(execution)
            last_value = result.value
    finally:
        context_store.pop_frame()

    return last_value


async def _run_sequential(
    foreach_node: ForEachNode,
    items: list[Any],
    platform: ExecutionPlatform,
    context_store: ContextStore,
    body_adapter_fn: BodyAdapterFn | None,
) -> list[Any]:
    """Run iterations one-by-one and collect results."""
    collected: list[Any] = []
    for index, item in enumerate(items):
        value = await _run_single_iteration(
            foreach_node, index, item, platform, context_store, body_adapter_fn
        )
        collected.append(value)

    if foreach_node.result_key is not None:
        context_store.put(foreach_node.result_key, collected)
    return collected


async def _run_parallel(
    foreach_node: ForEachNode,
    items: list[Any],
    platform: ExecutionPlatform,
    context_store: ContextStore,
    body_adapter_fn: BodyAdapterFn | None,
) -> list[Any]:
    """Run iterations via ``ParallelRunner`` and collect results in order.

    Each iteration receives its item through ``input_data`` (as a dict)
    rather than through shared context-store frames, avoiding interleaving
    issues when iterations execute concurrently.
    """
    max_workers = foreach_node.max_workers or len(items)
    config = ParallelConfig(max_concurrency=max_workers, error_strategy="fail_slow")
    runner = ParallelRunner(
        platform=platform,
        parallel_config=config,
        retry_config=None,
        timeout_config=None,
        group_name=f"foreach.{foreach_node.id}",
    )

    for index, item in enumerate(items):
        iter_input: dict[str, Any] = {"item": item, "index": index}

        async def _iter_handler(
            input_data: Any, *, _input: dict[str, Any] = iter_input
        ) -> Any:
            last_value: Any = _input
            for body_node in foreach_node.body_nodes:
                if body_adapter_fn is not None:
                    execution = body_adapter_fn(body_node)
                    execution = execution.model_copy(update={"input_data": last_value})
                else:
                    execution = Execution(
                        name=body_node.name,
                        description=body_node.description,
                        kind=getattr(body_node, "kind", "unknown"),
                        handler=getattr(body_node, "handler", _noop_handler),
                        input_data=last_value,
                    )
                result: ExecutionResult[Any] = await platform(execution)
                last_value = result.value
            return last_value

        runner.add(
            Execution(
                name=f"{foreach_node.name}[{index}]",
                description=f"Iteration {index} of {foreach_node.name}",
                kind="for_each_iteration",
                handler=_iter_handler,
                input_data=iter_input,
            )
        )

    results = await runner.run()
    collected = [r.value for r in results]

    if foreach_node.result_key is not None:
        context_store.put(foreach_node.result_key, collected)
    return collected


async def _noop_handler(input_data: Any) -> Any:
    return input_data
