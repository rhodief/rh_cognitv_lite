"""
Execution runners for orchestrating multiple Execution objects.

SequenceRunner: runs executions in insertion order with output→input chaining.
ParallelRunner: runs executions concurrently bounded by max_concurrency (Phase 4).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Callable, cast

from rh_cognitv_lite.execution_platform.errors import ErrorCategory, InterruptError
from rh_cognitv_lite.execution_platform.events import (
    ExecutionEvent,
    InterruptEvent,
    InterruptReason,
    InterruptSignal,
)
from rh_cognitv_lite.execution_platform.models import (
    EventStatus,
    ExecutionResult,
    ParallelConfig,
    ResultMetadata,
    RetryConfig,
    TimeoutConfig,
)

if TYPE_CHECKING:
    from rh_cognitv_lite.execution_platform.execution import Execution, ExecutionPlatform


class SequenceRunner:
    """Runs a list of Execution objects one after another.

    Output of each step is injected as input to the next step (chaining).
    Supports retry (entire sequence from step 1), per-step timeout,
    total timeout, interrupt checking, and dynamic step injection via
    on_step_complete callback.
    """

    def __init__(
        self,
        platform: ExecutionPlatform,
        retry_config: RetryConfig | None,
        timeout_config: TimeoutConfig | None,
        group_name: str | None = None,
    ) -> None:
        self._platform = platform
        self._retry_config = retry_config
        self._timeout_config = timeout_config
        self._group_name = group_name
        self._executions: list[Execution] = []
        self._ran = False
        # Partial results accumulated during the current run, used to recover
        # completed steps when a total_timeout cancels the inner coroutine.
        self._current_results: list[ExecutionResult] = []
        self.on_step_complete: Callable | None = None

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def add(self, execution: Execution) -> None:
        """Append an execution to the sequence. Must be called before run()."""
        if self._ran:
            raise RuntimeError("Cannot add executions after run() has been called")
        self._executions.append(execution)

    async def run(self) -> list[ExecutionResult]:
        """Execute all steps in insertion order and return the results list."""
        self._ran = True

        # Emit sequence.started once, before any timeout wrapper.
        await self._platform.event_bus.publish(
            ExecutionEvent(
                name=self._group_name or "sequence",
                kind="execution.sequence",
                payload={},
                status=EventStatus.STARTED,
                group_id=self._group_name,
            )
        )

        max_attempts = self._retry_config.max_attempts if self._retry_config else 1

        async def _inner() -> list[ExecutionResult]:
            results: list[ExecutionResult] = []
            for attempt in range(1, max_attempts + 1):
                results = await self._run_once(attempt)

                if all(r.ok for r in results):
                    await self._platform.event_bus.publish(
                        ExecutionEvent(
                            name=self._group_name or "sequence",
                            kind="execution.sequence",
                            payload={},
                            status=EventStatus.COMPLETED,
                            retried=attempt - 1,
                            group_id=self._group_name,
                        )
                    )
                    return results

                # Determine whether the failure is retryable.
                failed = next((r for r in reversed(results) if not r.ok), None)
                retryable = (
                    failed.error_details.get("retryable", False)
                    if failed and failed.error_details
                    else False
                )

                if not retryable or attempt >= max_attempts:
                    await self._platform.event_bus.publish(
                        ExecutionEvent(
                            name=self._group_name or "sequence",
                            kind="execution.sequence",
                            payload={},
                            status=EventStatus.FAILED,
                            retried=attempt - 1,
                            group_id=self._group_name,
                        )
                    )
                    return results

                # Back-off before next attempt.
                delay = self._retry_config.delay_for(attempt) if self._retry_config else 0.0
                await self._platform.event_bus.publish(
                    ExecutionEvent(
                        name=self._group_name or "sequence",
                        kind="execution.sequence",
                        payload={},
                        status=EventStatus.RETRYING,
                        retried=attempt,
                        group_id=self._group_name,
                        ext={
                            "max_retries": max_attempts - 1,
                            "retry_after": delay,
                        },
                    )
                )
                if self._retry_config:
                    await asyncio.sleep(delay)

            return results  # unreachable; satisfies type checker

        if self._timeout_config:
            try:
                return await asyncio.wait_for(
                    _inner(), timeout=self._timeout_config.total_timeout
                )
            except asyncio.TimeoutError:
                signal = InterruptSignal(
                    reason=InterruptReason.TIMEOUT, message="Total timeout exceeded"
                )
                await self._platform.event_bus.publish(
                    InterruptEvent(signal=signal, state_id="sequence")
                )
                await self._platform.event_bus.publish(
                    ExecutionEvent(
                        name=self._group_name or "sequence",
                        kind="execution.sequence",
                        payload={},
                        status=EventStatus.FAILED,
                        group_id=self._group_name,
                    )
                )
                partial = list(self._current_results)
                partial.append(
                    ExecutionResult(
                        ok=False,
                        error_message="Total timeout exceeded",
                        error_category=ErrorCategory.INTERRUPT.value,
                        error_details={
                            "type": "TimeoutError",
                            "message": "Total timeout exceeded",
                            "retryable": False,
                            "category": ErrorCategory.INTERRUPT.value,
                            "attempt": 1,
                        },
                        metadata=ResultMetadata(attempt=1),
                    )
                )
                return partial
        else:
            return await _inner()

    # ──────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────

    async def _run_once(self, attempt: int) -> list[ExecutionResult]:
        """One complete pass through all steps (a single retry attempt)."""
        results: list[ExecutionResult] = []
        # Fresh copy per attempt so on_step_complete injections from previous
        # attempts do not carry over, and original input_data are preserved.
        executions: list[Execution] = list(self._executions)
        self._current_results = []

        idx = 0
        while idx < len(executions):
            exec_item = executions[idx]

            # ── 1. Poll interrupt checker before each step ────────────────
            try:
                self._platform._check_interrupt()
            except InterruptError as exc:
                sig: InterruptSignal = getattr(exc, "signal", None) or InterruptSignal(
                    reason=InterruptReason.USER_CANCELLED
                )
                await self._platform.event_bus.publish(
                    InterruptEvent(signal=sig, state_id=exec_item.name)
                )
                results.append(
                    ExecutionResult(
                        ok=False,
                        error_message=str(exc),
                        error_category=ErrorCategory.INTERRUPT.value,
                        error_details={
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "retryable": False,
                            "category": ErrorCategory.INTERRUPT.value,
                            "attempt": attempt,
                        },
                        metadata=ResultMetadata(attempt=attempt),
                    )
                )
                self._current_results = list(results)
                return results

            # ── 2. Output chaining + group_id/attempt propagation ─────────
            updates: dict = {}
            if self._group_name is not None:
                updates["group_id"] = self._group_name
            if attempt > 1:
                updates["attempt"] = attempt
            if idx > 0 and results:
                prev_value = results[-1].value
                if prev_value is not None:
                    updates["input_data"] = prev_value
                    if "attempt" not in updates:
                        updates["attempt"] = attempt
            if updates:
                exec_item = exec_item.model_copy(update=updates)

            # ── 3. Execute (with optional per-step timeout) ───────────────
            try:
                if self._timeout_config and self._timeout_config.each_execution_timeout:
                    result = await asyncio.wait_for(
                        self._platform(exec_item),
                        timeout=self._timeout_config.each_execution_timeout,
                    )
                else:
                    result = await self._platform(exec_item)
            except asyncio.TimeoutError:
                sig = InterruptSignal(
                    reason=InterruptReason.TIMEOUT,
                    message=f"Execution timed out: {exec_item.name}",
                )
                await self._platform.event_bus.publish(
                    InterruptEvent(signal=sig, state_id=exec_item.name)
                )
                result = ExecutionResult(
                    ok=False,
                    error_message=f"Execution timed out: {exec_item.name}",
                    error_category=ErrorCategory.INTERRUPT.value,
                    error_details={
                        "type": "TimeoutError",
                        "message": f"Execution timed out: {exec_item.name}",
                        "retryable": False,
                        "category": ErrorCategory.INTERRUPT.value,
                        "attempt": attempt,
                    },
                    metadata=ResultMetadata(attempt=attempt),
                )

            results.append(result)
            self._current_results = list(results)

            # ── 4. on_step_complete callback (dynamic injection) ──────────
            if self.on_step_complete is not None:
                if inspect.iscoroutinefunction(self.on_step_complete):
                    injected = cast(
                        "list[Execution] | None",
                        await self.on_step_complete(idx, result),
                    )
                else:
                    injected = cast(
                        "list[Execution] | None",
                        self.on_step_complete(idx, result),
                    )
                if injected:
                    executions[idx + 1:idx + 1] = injected

            # ── 5. Stop on failure ────────────────────────────────────────
            if not result.ok:
                return results

            idx += 1

        return results


class ParallelRunner:
    """Runs a list of Execution objects concurrently.

    Concurrency is bounded by asyncio.Semaphore(max_concurrency).
    Results are always returned in insertion order.
    Supports fail_fast / fail_slow error strategies, retry, per-task timeout,
    total timeout, and interrupt checking.
    """

    def __init__(
        self,
        platform: ExecutionPlatform,
        parallel_config: ParallelConfig,
        retry_config: RetryConfig | None,
        timeout_config: TimeoutConfig | None,
        group_name: str | None = None,
    ) -> None:
        self._platform = platform
        self._parallel_config = parallel_config
        self._retry_config = retry_config
        self._timeout_config = timeout_config
        self._group_name = group_name
        self._executions: list[Execution] = []
        self._ran = False

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def add(self, execution: Execution) -> None:
        """Append an execution to the batch. Must be called before run()."""
        if self._ran:
            raise RuntimeError("Cannot add executions after run() has been called")
        self._executions.append(execution)

    async def run(self) -> list[ExecutionResult]:
        """Dispatch all executions and return results in insertion order."""
        self._ran = True

        await self._platform.event_bus.publish(
            ExecutionEvent(
                name=self._group_name or "parallel",
                kind="execution.parallel",
                payload={},
                status=EventStatus.STARTED,
                group_id=self._group_name,
            )
        )

        max_attempts = self._retry_config.max_attempts if self._retry_config else 1

        async def _inner() -> list[ExecutionResult]:
            # Tracks which original indexes still need to run.
            pending_indexes: list[int] = list(range(len(self._executions)))
            results: list[ExecutionResult | None] = [None] * len(self._executions)

            for attempt in range(1, max_attempts + 1):
                batch_results = await self._run_batch(pending_indexes, attempt)

                for orig_idx, result in zip(pending_indexes, batch_results):
                    results[orig_idx] = result

                failed_indexes = [
                    pending_indexes[i]
                    for i, r in enumerate(batch_results)
                    if not r.ok
                ]

                if not failed_indexes:
                    break

                # Decide whether to retry.
                retryable_indexes = [
                    idx for idx in failed_indexes
                    if results[idx] is not None
                    and results[idx].error_details is not None  # type: ignore[union-attr]
                    and results[idx].error_details.get("retryable", False)  # type: ignore[union-attr]
                ]

                if not retryable_indexes or attempt >= max_attempts:
                    break

                if self._parallel_config.error_strategy == "fail_fast":
                    # fail_fast retries the whole batch.
                    pending_indexes = list(range(len(self._executions)))
                    results = [None] * len(self._executions)
                else:
                    # fail_slow retries only failed tasks.
                    pending_indexes = retryable_indexes

                delay = self._retry_config.delay_for(attempt) if self._retry_config else 0.0
                await self._platform.event_bus.publish(
                    ExecutionEvent(
                        name=self._group_name or "parallel",
                        kind="execution.parallel",
                        payload={},
                        status=EventStatus.RETRYING,
                        retried=attempt,
                        group_id=self._group_name,
                        ext={
                            "max_retries": max_attempts - 1,
                            "retry_after": delay,
                        },
                    )
                )
                if self._retry_config:
                    await asyncio.sleep(delay)

            # Fill any None slots (shouldn't happen) with a sentinel failure.
            final: list[ExecutionResult] = [
                r if r is not None else ExecutionResult(
                    ok=False,
                    error_message="Task did not complete",
                    error_category=ErrorCategory.PERMANENT.value,
                    metadata=ResultMetadata(attempt=1),
                )
                for r in results
            ]

            all_ok = all(r.ok for r in final)
            event_status = EventStatus.COMPLETED if all_ok else EventStatus.FAILED
            await self._platform.event_bus.publish(
                ExecutionEvent(
                    name=self._group_name or "parallel",
                    kind="execution.parallel",
                    payload={},
                    status=event_status,
                    retried=attempt - 1,
                    group_id=self._group_name,
                )
            )
            return final

        if self._timeout_config:
            try:
                return await asyncio.wait_for(
                    _inner(), timeout=self._timeout_config.total_timeout
                )
            except asyncio.TimeoutError:
                signal = InterruptSignal(
                    reason=InterruptReason.TIMEOUT, message="Total timeout exceeded"
                )
                await self._platform.event_bus.publish(
                    InterruptEvent(signal=signal, state_id="parallel")
                )
                await self._platform.event_bus.publish(
                    ExecutionEvent(
                        name=self._group_name or "parallel",
                        kind="execution.parallel",
                        payload={},
                        status=EventStatus.FAILED,
                        group_id=self._group_name,
                    )
                )
                return [
                    ExecutionResult(
                        ok=False,
                        error_message="Total timeout exceeded",
                        error_category=ErrorCategory.INTERRUPT.value,
                        error_details={
                            "type": "TimeoutError",
                            "message": "Total timeout exceeded",
                            "retryable": False,
                            "category": ErrorCategory.INTERRUPT.value,
                            "attempt": 1,
                        },
                        metadata=ResultMetadata(attempt=1),
                    )
                    for _ in self._executions
                ]
        else:
            return await _inner()

    # ──────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────

    async def _run_batch(
        self, indexes: list[int], attempt: int
    ) -> list[ExecutionResult]:
        """Run the executions at the given original indexes concurrently."""
        semaphore = asyncio.Semaphore(self._parallel_config.max_concurrency)
        fail_fast_event = asyncio.Event()

        # Placeholder list sized to the batch; filled by index.
        batch_results: list[ExecutionResult | None] = [None] * len(indexes)

        async def run_one(batch_pos: int, orig_idx: int) -> None:
            exec_item = self._executions[orig_idx]
            updates: dict = {}
            if self._group_name is not None:
                updates["group_id"] = self._group_name
            if attempt > 1:
                updates["attempt"] = attempt
            if updates:
                exec_item = exec_item.model_copy(update=updates)

            # ── Interrupt check before dispatching ────────────────────────
            try:
                self._platform._check_interrupt()
            except InterruptError as exc:
                sig: InterruptSignal = getattr(exc, "signal", None) or InterruptSignal(
                    reason=InterruptReason.USER_CANCELLED
                )
                await self._platform.event_bus.publish(
                    InterruptEvent(signal=sig, state_id=exec_item.name)
                )
                batch_results[batch_pos] = ExecutionResult(
                    ok=False,
                    error_message=str(exc),
                    error_category=ErrorCategory.INTERRUPT.value,
                    error_details={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "retryable": False,
                        "category": ErrorCategory.INTERRUPT.value,
                        "attempt": attempt,
                    },
                    metadata=ResultMetadata(attempt=attempt),
                )
                fail_fast_event.set()
                return

            # ── fail_fast: abort before acquiring semaphore ───────────────
            if (
                self._parallel_config.error_strategy == "fail_fast"
                and fail_fast_event.is_set()
            ):
                batch_results[batch_pos] = ExecutionResult(
                    ok=False,
                    error_message="Cancelled due to fail_fast",
                    error_category=ErrorCategory.INTERRUPT.value,
                    error_details={
                        "type": "CancelledError",
                        "message": "Cancelled due to fail_fast",
                        "retryable": False,
                        "category": ErrorCategory.INTERRUPT.value,
                        "attempt": attempt,
                    },
                    metadata=ResultMetadata(attempt=attempt),
                )
                return

            async with semaphore:
                # ── fail_fast: abort after acquiring semaphore ────────────
                if (
                    self._parallel_config.error_strategy == "fail_fast"
                    and fail_fast_event.is_set()
                ):
                    batch_results[batch_pos] = ExecutionResult(
                        ok=False,
                        error_message="Cancelled due to fail_fast",
                        error_category=ErrorCategory.INTERRUPT.value,
                        error_details={
                            "type": "CancelledError",
                            "message": "Cancelled due to fail_fast",
                            "retryable": False,
                            "category": ErrorCategory.INTERRUPT.value,
                            "attempt": attempt,
                        },
                        metadata=ResultMetadata(attempt=attempt),
                    )
                    return

                # ── Execute with optional per-task timeout ────────────────
                try:
                    if self._timeout_config and self._timeout_config.each_execution_timeout:
                        result = await asyncio.wait_for(
                            self._platform(exec_item),
                            timeout=self._timeout_config.each_execution_timeout,
                        )
                    else:
                        result = await self._platform(exec_item)
                except asyncio.CancelledError:
                    batch_results[batch_pos] = ExecutionResult(
                        ok=False,
                        error_message="Cancelled due to fail_fast",
                        error_category=ErrorCategory.INTERRUPT.value,
                        error_details={
                            "type": "CancelledError",
                            "message": "Cancelled due to fail_fast",
                            "retryable": False,
                            "category": ErrorCategory.INTERRUPT.value,
                            "attempt": attempt,
                        },
                        metadata=ResultMetadata(attempt=attempt),
                    )
                    return
                except asyncio.TimeoutError:
                    sig = InterruptSignal(
                        reason=InterruptReason.TIMEOUT,
                        message=f"Execution timed out: {exec_item.name}",
                    )
                    await self._platform.event_bus.publish(
                        InterruptEvent(signal=sig, state_id=exec_item.name)
                    )
                    result = ExecutionResult(
                        ok=False,
                        error_message=f"Execution timed out: {exec_item.name}",
                        error_category=ErrorCategory.INTERRUPT.value,
                        error_details={
                            "type": "TimeoutError",
                            "message": f"Execution timed out: {exec_item.name}",
                            "retryable": False,
                            "category": ErrorCategory.INTERRUPT.value,
                            "attempt": attempt,
                        },
                        metadata=ResultMetadata(attempt=attempt),
                    )

                batch_results[batch_pos] = result

                if not result.ok and self._parallel_config.error_strategy == "fail_fast":
                    fail_fast_event.set()

        tasks = [
            asyncio.create_task(run_one(pos, orig_idx))
            for pos, orig_idx in enumerate(indexes)
        ]

        # For fail_fast: watch for the event and cancel all sibling tasks.
        if self._parallel_config.error_strategy == "fail_fast":
            async def _cancel_on_fail_fast() -> None:
                await fail_fast_event.wait()
                for t in tasks:
                    if not t.done():
                        t.cancel()

            watcher = asyncio.create_task(_cancel_on_fail_fast())
            await asyncio.gather(*tasks, return_exceptions=True)
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        else:
            await asyncio.gather(*tasks)

        # Fill slots for tasks that were cancelled before they could write a result.
        for pos in range(len(batch_results)):
            if batch_results[pos] is None:
                batch_results[pos] = ExecutionResult(
                    ok=False,
                    error_message="Cancelled due to fail_fast",
                    error_category=ErrorCategory.INTERRUPT.value,
                    error_details={
                        "type": "CancelledError",
                        "message": "Cancelled due to fail_fast",
                        "retryable": False,
                        "category": ErrorCategory.INTERRUPT.value,
                        "attempt": attempt,
                    },
                    metadata=ResultMetadata(attempt=attempt),
                )

        return [
            r if r is not None else ExecutionResult(
                ok=False,
                error_message="Task did not complete",
                error_category=ErrorCategory.PERMANENT.value,
                metadata=ResultMetadata(attempt=attempt),
            )
            for r in batch_results
        ]

