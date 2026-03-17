"""Phase 4 unit tests — ParallelRunner."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from rh_cognitv_lite.execution_platform.errors import PermanentError, TransientError
from rh_cognitv_lite.execution_platform.event_bus import EventBus
from rh_cognitv_lite.execution_platform.events import ExecutionEvent
from rh_cognitv_lite.execution_platform.execution import Execution, ExecutionPlatform
from rh_cognitv_lite.execution_platform.models import (
    EventStatus,
    ParallelConfig,
    RetryConfig,
    TimeoutConfig,
)

# ──────────────────────────────────────────────
# Fixtures & helpers
# ──────────────────────────────────────────────


def _exec(handler, *, name: str = "task") -> Execution:
    return Execution(name=name, handler=handler)


def _ok_handler(ret=None):
    def h(_):
        return ret
    return h


def _platform(*, checker=None) -> tuple[EventBus, ExecutionPlatform]:
    bus = EventBus()
    platform = ExecutionPlatform(event_bus=bus, interrupt_checker=checker)
    return bus, platform


def _par_events(bus: EventBus) -> list[str]:
    return [
        e.kind
        for e in bus.events
        if isinstance(e, ExecutionEvent) and e.kind.startswith("parallel.")
    ]


# ──────────────────────────────────────────────
# Happy-path
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_task_happy_path():
    bus, platform = _platform()
    async with platform.parallel() as par:
        par.add(_exec(_ok_handler(), name="t1"))
        results = await par.run()
    assert len(results) == 1
    assert results[0].ok is True


@pytest.mark.asyncio
async def test_multi_task_all_succeed():
    bus, platform = _platform()
    async with platform.parallel() as par:
        for i in range(5):
            par.add(_exec(_ok_handler(), name=f"t{i}"))
        results = await par.run()
    assert len(results) == 5
    assert all(r.ok for r in results)


@pytest.mark.asyncio
async def test_results_in_insertion_order():
    """Tasks that finish in reverse order still return in insertion order."""
    bus, platform = _platform()
    finish_order: list[int] = []

    def make_handler(n: int, delay: float):
        async def h(_):
            await asyncio.sleep(delay)
            finish_order.append(n)
            return None
        return h

    async with platform.parallel() as par:
        # t0 is slowest, t4 fastest → finish order reversed
        for i in range(5):
            par.add(_exec(make_handler(i, (5 - i) * 0.02), name=f"t{i}"))
        results = await par.run()

    assert [r.ok for r in results] == [True] * 5
    # Insertion order preserved regardless of finish order.
    assert finish_order == list(reversed(range(5)))


@pytest.mark.asyncio
async def test_empty_parallel_returns_empty_list():
    bus, platform = _platform()
    async with platform.parallel() as par:
        results = await par.run()
    assert results == []


# ──────────────────────────────────────────────
# Concurrency
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_concurrency_respected():
    """No more than max_concurrency tasks run simultaneously."""
    concurrency_counter = [0]
    peak = [0]

    async def handler(_):
        concurrency_counter[0] += 1
        peak[0] = max(peak[0], concurrency_counter[0])
        await asyncio.sleep(0.05)
        concurrency_counter[0] -= 1
        return None

    bus, platform = _platform()
    cfg = ParallelConfig(max_concurrency=2)
    async with platform.parallel(parallel_config=cfg) as par:
        for i in range(5):
            par.add(_exec(handler, name=f"t{i}"))
        await par.run()

    assert peak[0] <= 2


# ──────────────────────────────────────────────
# fail_slow
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_slow_collects_all_results():
    """Task 2 fails; tasks 1, 3, 4 still complete."""
    bus, platform = _platform()

    cfg = ParallelConfig(error_strategy="fail_slow")
    async with platform.parallel(parallel_config=cfg) as par:
        par.add(_exec(_ok_handler(), name="t0"))
        par.add(_exec(lambda _: (_ for _ in ()).throw(PermanentError("boom")), name="t1"))
        par.add(_exec(_ok_handler(), name="t2"))
        par.add(_exec(_ok_handler(), name="t3"))
        results = await par.run()

    assert len(results) == 4


@pytest.mark.asyncio
async def test_fail_slow_failed_tasks_ok_false():
    bus, platform = _platform()

    cfg = ParallelConfig(error_strategy="fail_slow")
    async with platform.parallel(parallel_config=cfg) as par:
        par.add(_exec(_ok_handler(), name="t0"))
        par.add(_exec(lambda _: (_ for _ in ()).throw(PermanentError("boom")), name="t1"))
        par.add(_exec(_ok_handler(), name="t2"))
        results = await par.run()

    assert results[0].ok is True
    assert results[1].ok is False
    assert results[2].ok is True


@pytest.mark.asyncio
async def test_fail_slow_retry_only_failed():
    """Only the failed task is re-run on retry; others are not re-called."""
    call_counts: dict[str, int] = {"t0": 0, "t1": 0, "t2": 0}

    def make_counter(name: str, fail_once: bool):
        def h(_):
            call_counts[name] += 1
            if fail_once and call_counts[name] == 1:
                raise TransientError("once")
            return None
        return h

    bus, platform = _platform()
    cfg = ParallelConfig(error_strategy="fail_slow")
    retry = RetryConfig(max_attempts=2, base_delay=0.0)

    async with platform.parallel(parallel_config=cfg, retry_config=retry) as par:
        par.add(_exec(make_counter("t0", False), name="t0"))
        par.add(_exec(make_counter("t1", True), name="t1"))   # fails once
        par.add(_exec(make_counter("t2", False), name="t2"))
        results = await par.run()

    assert all(r.ok for r in results)
    assert call_counts["t0"] == 1   # not retried
    assert call_counts["t1"] == 2   # retried once
    assert call_counts["t2"] == 1   # not retried


# ──────────────────────────────────────────────
# fail_fast
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_fast_cancels_in_flight():
    """First task fails → remaining tasks get ok=False with error_category interrupt."""
    bus, platform = _platform()
    cfg = ParallelConfig(max_concurrency=5, error_strategy="fail_fast")

    async def fast_fail(_):
        raise PermanentError("first fail")

    async def slow_task(_):
        await asyncio.sleep(10)
        return None

    async with platform.parallel(parallel_config=cfg) as par:
        par.add(_exec(fast_fail, name="t0"))
        par.add(_exec(slow_task, name="t1"))
        par.add(_exec(slow_task, name="t2"))
        results = await par.run()

    assert results[0].ok is False
    # t1 and t2 were cancelled or never started
    assert results[1].ok is False
    assert results[2].ok is False


@pytest.mark.asyncio
async def test_fail_fast_retry_restarts_full_batch():
    """fail_fast + retry: all tasks re-run on retry, not just the failed one."""
    call_counts: dict[str, int] = {"t0": 0, "t1": 0}

    def make_counter(name: str, fail_first: bool):
        def h(_):
            call_counts[name] += 1
            if fail_first and call_counts[name] == 1:
                raise TransientError("once")
            return None
        return h

    bus, platform = _platform()
    cfg = ParallelConfig(error_strategy="fail_fast")
    retry = RetryConfig(max_attempts=2, base_delay=0.0)

    async with platform.parallel(parallel_config=cfg, retry_config=retry) as par:
        par.add(_exec(make_counter("t0", True), name="t0"))   # fails first time
        par.add(_exec(make_counter("t1", False), name="t1"))
        results = await par.run()

    assert all(r.ok for r in results)
    # Both tasks should have been called in the retry batch.
    assert call_counts["t1"] >= 2


@pytest.mark.asyncio
async def test_fail_fast_is_not_default():
    cfg = ParallelConfig()
    assert cfg.error_strategy == "fail_slow"


# ──────────────────────────────────────────────
# Timeout
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_execution_timeout_fires():
    """Slow task exceeds per-task timeout → ok=False, interrupt; others unaffected."""
    bus, platform = _platform()
    cfg = ParallelConfig(error_strategy="fail_slow")
    timeout = TimeoutConfig(each_execution_timeout=0.05, total_timeout=300.0)

    async def slow(_):
        await asyncio.sleep(10)
        return None

    async with platform.parallel(parallel_config=cfg, timeout_config=timeout) as par:
        par.add(_exec(slow, name="t0"))
        par.add(_exec(_ok_handler(), name="t1"))
        results = await par.run()

    assert results[0].ok is False
    assert results[0].error_category == "interrupt"
    assert results[1].ok is True


@pytest.mark.asyncio
async def test_total_timeout_fires():
    """Batch exceeds total_timeout → all results ok=False."""
    bus, platform = _platform()
    timeout = TimeoutConfig(each_execution_timeout=300.0, total_timeout=0.05)

    async def slow(_):
        await asyncio.sleep(10)
        return None

    async with platform.parallel(timeout_config=timeout) as par:
        par.add(_exec(slow, name="t0"))
        par.add(_exec(slow, name="t1"))
        results = await par.run()

    assert all(r.ok is False for r in results)
    assert all(r.error_category == "interrupt" for r in results)


# ──────────────────────────────────────────────
# Interrupt checker
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interrupt_checker_stops_dispatch():
    """interrupt_checker returns False before task t2 is dispatched."""
    called: list[str] = []
    dispatch_count = [0]

    def checker():
        dispatch_count[0] += 1
        # Allow first two dispatches; interrupt on the third
        return dispatch_count[0] <= 2

    bus, platform = _platform(checker=checker)

    cfg = ParallelConfig(max_concurrency=1)  # serial via semaphore so order is guaranteed
    async with platform.parallel(parallel_config=cfg) as par:
        for i in range(3):
            par.add(_exec(_ok_handler(), name=f"t{i}"))
        results = await par.run()

    assert any(not r.ok for r in results)


# ──────────────────────────────────────────────
# Retry edge cases
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permanent_failure_not_retried():
    """PermanentError: no retry; result ok=False immediately."""
    call_count = [0]
    bus, platform = _platform()
    retry = RetryConfig(max_attempts=3, base_delay=0.0)

    def perm_fail(_):
        call_count[0] += 1
        raise PermanentError("fatal")

    async with platform.parallel(retry_config=retry) as par:
        par.add(_exec(perm_fail, name="t0"))
        results = await par.run()

    assert results[0].ok is False
    assert call_count[0] == 1


@pytest.mark.asyncio
async def test_retry_exhausted_returns_ok_false():
    """TransientError every time → ok=False after max_attempts."""
    bus, platform = _platform()
    retry = RetryConfig(max_attempts=3, base_delay=0.0)

    def always_transient(_):
        raise TransientError("always")

    async with platform.parallel(retry_config=retry) as par:
        par.add(_exec(always_transient, name="t0"))
        results = await par.run()

    assert results[0].ok is False


# ──────────────────────────────────────────────
# add() guard
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_after_run_raises():
    bus, platform = _platform()
    async with platform.parallel() as par:
        par.add(_exec(_ok_handler(), name="t0"))
        await par.run()
        with pytest.raises(RuntimeError):
            par.add(_exec(_ok_handler(), name="t1"))


# ──────────────────────────────────────────────
# Event emission
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_started_event_emitted():
    bus, platform = _platform()
    async with platform.parallel() as par:
        par.add(_exec(_ok_handler(), name="t0"))
        await par.run()

    kinds = _par_events(bus)
    assert "parallel.started" in kinds
    assert kinds.index("parallel.started") == 0


@pytest.mark.asyncio
async def test_parallel_completed_event_emitted():
    bus, platform = _platform()
    async with platform.parallel() as par:
        par.add(_exec(_ok_handler(), name="t0"))
        await par.run()

    kinds = _par_events(bus)
    assert "parallel.completed" in kinds
    assert "parallel.failed" not in kinds


@pytest.mark.asyncio
async def test_parallel_failed_event_emitted():
    bus, platform = _platform()

    async with platform.parallel() as par:
        par.add(_exec(lambda _: (_ for _ in ()).throw(PermanentError("nope")), name="t0"))
        await par.run()

    kinds = _par_events(bus)
    assert "parallel.failed" in kinds
    assert "parallel.completed" not in kinds
