"""Phase 3 unit tests — SequenceRunner."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from rh_cognitv_lite.execution_platform.errors import PermanentError, TransientError
from rh_cognitv_lite.execution_platform.event_bus import EventBus
from rh_cognitv_lite.execution_platform.events import ExecutionEvent
from rh_cognitv_lite.execution_platform.execution import CheckSchema, Execution, ExecutionPlatform
from rh_cognitv_lite.execution_platform.models import (
    EventStatus,
    RetryConfig,
    TimeoutConfig,
)

# ──────────────────────────────────────────────
# Fixtures & helpers
# ──────────────────────────────────────────────


def _exec(
    handler,
    *,
    name: str = "step",
    input_data=None,
    preconditions=None,
    postconditions=None,
) -> Execution:
    return Execution(
        name=name,
        handler=handler,
        input_data=input_data,
        preconditions=preconditions,
        postconditions=postconditions,
    )


def _ok_handler(ret: dict | None = None):
    def handler(_input):
        return ret

    return handler


def _platform(*, checker=None) -> tuple[EventBus, ExecutionPlatform]:
    bus = EventBus()
    platform = ExecutionPlatform(event_bus=bus, interrupt_checker=checker)
    return bus, platform


def _seq_events(bus: EventBus) -> list[str]:
    """Return 'execution.sequence.<status>' strings for all sequence-scoped events."""
    return [
        f"{e.kind}.{e.status.value}"
        for e in bus.events
        if isinstance(e, ExecutionEvent) and e.kind == "execution.sequence"
    ]


# ──────────────────────────────────────────────
# Happy-path tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_step_happy_path():
    bus, platform = _platform()
    async with platform.sequence() as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        results = await seq.run()
    assert len(results) == 1
    assert results[0].ok is True


@pytest.mark.asyncio
async def test_multi_step_happy_path():
    order: list[str] = []
    bus, platform = _platform()

    def make_handler(name):
        def h(_):
            order.append(name)
            return None

        return h

    async with platform.sequence() as seq:
        for i in range(3):
            seq.add(_exec(make_handler(f"s{i}"), name=f"s{i}"))
        results = await seq.run()

    assert len(results) == 3
    assert all(r.ok for r in results)
    assert order == ["s0", "s1", "s2"]


@pytest.mark.asyncio
async def test_results_in_insertion_order():
    values: list[int] = []
    bus, platform = _platform()

    def make_handler(n):
        def h(_):
            values.append(n)
            return None

        return h

    async with platform.sequence() as seq:
        for i in range(3):
            seq.add(_exec(make_handler(i), name=f"s{i}"))
        results = await seq.run()

    assert len(results) == 3
    # Each result corresponds to the execution at that index.
    assert values == [0, 1, 2]


@pytest.mark.asyncio
async def test_empty_sequence_returns_empty_list():
    bus, platform = _platform()
    async with platform.sequence() as seq:
        results = await seq.run()
    assert results == []


# ──────────────────────────────────────────────
# Output chaining
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_output_chaining():
    """Step 1 output dict is injected as step 2's input_data."""
    received: list = []
    bus, platform = _platform()

    def step1_handler(_):
        return {"result": 42}

    def step2_handler(inp):
        received.append(inp)
        return None

    async with platform.sequence() as seq:
        seq.add(_exec(step1_handler, name="s1"))
        seq.add(_exec(step2_handler, name="s2"))
        results = await seq.run()

    assert all(r.ok for r in results)
    assert len(received) == 1
    assert received[0] == {"result": 42}


@pytest.mark.asyncio
async def test_output_chaining_with_schema_check():
    """CheckSchema in precondition rejects incompatible output passed as next input."""
    bus, platform = _platform()

    step2_schema = {"type": "object", "properties": {"data": {"type": "string"}}, "required": ["data"]}

    def step1_handler(_):
        return {"result": 99}  # does not match step2_schema

    def step2_handler(inp):
        return None

    async with platform.sequence() as seq:
        seq.add(_exec(step1_handler, name="s1"))
        seq.add(_exec(step2_handler, name="s2", preconditions=[CheckSchema(step2_schema)]))
        results = await seq.run()

    assert results[0].ok is True
    assert results[1].ok is False
    assert results[1].error_details["type"] == "PreconditionError"


@pytest.mark.asyncio
async def test_none_output_does_not_overwrite_next_input():
    """Step 1 returns None; step 2 keeps its own input_data."""
    received: list = []
    bus, platform = _platform()

    original_input = {"value": 7}

    def step1_handler(_):
        return None

    def step2_handler(inp):
        received.append(inp)
        return None

    async with platform.sequence() as seq:
        seq.add(_exec(step1_handler, name="s1"))
        seq.add(_exec(step2_handler, name="s2", input_data=original_input))
        results = await seq.run()

    assert all(r.ok for r in results)
    assert received[0] == original_input  # unchanged


# ──────────────────────────────────────────────
# Failure & retry
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failure_stops_sequence():
    """Step 2 of 3 fails permanently; step 3 is never called."""
    step3_calls: list[int] = []
    bus, platform = _platform()

    def step2_handler(_):
        raise PermanentError("boom")

    def step3_handler(_):
        step3_calls.append(1)
        return None

    async with platform.sequence() as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        seq.add(_exec(step2_handler, name="s2"))
        seq.add(_exec(step3_handler, name="s3"))
        results = await seq.run()

    assert len(results) == 2
    assert results[0].ok is True
    assert results[1].ok is False
    assert step3_calls == []


@pytest.mark.asyncio
async def test_transient_failure_triggers_full_retry():
    """Step 2 raises TransientError on the first attempt; full sequence retried."""
    s2_calls: list[int] = []
    bus, platform = _platform()

    def step2_handler(_):
        s2_calls.append(1)
        if len(s2_calls) == 1:
            raise TransientError("temporary")
        return None

    retry_cfg = RetryConfig(max_attempts=2, base_delay=0.0)
    async with platform.sequence(retry_config=retry_cfg) as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        seq.add(_exec(step2_handler, name="s2"))
        results = await seq.run()

    # Second attempt succeeds for all steps.
    assert all(r.ok for r in results)
    assert len(s2_calls) == 2  # called once per attempt


@pytest.mark.asyncio
async def test_retry_exhausted_returns_ok_false():
    """Step 2 always raises TransientError; after max_attempts, result is ok=False."""
    bus, platform = _platform()

    def always_transient(_):
        raise TransientError("always fails")

    retry_cfg = RetryConfig(max_attempts=3, base_delay=0.0)
    async with platform.sequence(retry_config=retry_cfg) as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        seq.add(_exec(always_transient, name="s2"))
        results = await seq.run()

    last = results[-1]
    assert last.ok is False
    assert last.error_category == "transient"


@pytest.mark.asyncio
async def test_retry_backoff_delays_applied():
    """asyncio.sleep is called with back-off values between attempts."""
    bus, platform = _platform()
    attempts: list[int] = []

    def flaky(_):
        attempts.append(1)
        raise TransientError("flaky")

    retry_cfg = RetryConfig(max_attempts=3, base_delay=1.0, multiplier=2.0, max_delay=30.0)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        async with platform.sequence(retry_config=retry_cfg) as seq:
            seq.add(_exec(flaky, name="s1"))
            await seq.run()

    # delay_for(1) = 1.0, delay_for(2) = 2.0; no sleep after last attempt
    # Filter out asyncio.sleep(0) yield calls from EventBus.publish().
    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list if call.args[0] > 0]
    assert sleep_calls == [1.0, 2.0]


@pytest.mark.asyncio
async def test_permanent_failure_not_retried():
    """PermanentError is not retried; run ends immediately."""
    handler_calls: list[int] = []
    bus, platform = _platform()

    def permanent_handler(_):
        handler_calls.append(1)
        raise PermanentError("fatal")

    retry_cfg = RetryConfig(max_attempts=3, base_delay=0.0)
    async with platform.sequence(retry_config=retry_cfg) as seq:
        seq.add(_exec(permanent_handler, name="s1"))
        results = await seq.run()

    assert results[0].ok is False
    assert handler_calls == [1]  # called exactly once


# ──────────────────────────────────────────────
# Timeout
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_execution_timeout_fires():
    """Handler that sleeps beyond each_execution_timeout → ok=False, interrupt category."""
    bus, platform = _platform()

    async def slow_handler(_):
        await asyncio.sleep(10)
        return None

    timeout_cfg = TimeoutConfig(each_execution_timeout=0.05, total_timeout=300.0)
    async with platform.sequence(timeout_config=timeout_cfg) as seq:
        seq.add(_exec(slow_handler, name="s1"))
        results = await seq.run()

    assert results[0].ok is False
    assert results[0].error_category == "interrupt"
    assert results[0].error_details is not None
    assert results[0].error_details["type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_total_timeout_fires():
    """Steps together exceed total_timeout; partial results are returned."""
    bus, platform = _platform()
    step1_done: list[int] = []

    async def slow_step(_):
        await asyncio.sleep(0.15)
        step1_done.append(1)
        return None

    # step1 takes 0.15s, total_timeout=0.2s; step2 would push it over
    timeout_cfg = TimeoutConfig(each_execution_timeout=300.0, total_timeout=0.2)
    async with platform.sequence(timeout_config=timeout_cfg) as seq:
        seq.add(_exec(slow_step, name="s1"))
        seq.add(_exec(slow_step, name="s2"))
        results = await seq.run()

    # At least one result; final entry signals timeout interrupt.
    assert len(results) >= 1
    assert results[-1].ok is False
    assert results[-1].error_category == "interrupt"


# ──────────────────────────────────────────────
# Interrupt checker
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interrupt_checker_stops_before_step():
    """interrupt_checker returns False before step 2; step 2 never starts."""
    step2_calls: list[int] = []
    step_count = [0]

    def checker():
        step_count[0] += 1
        # Allow step 1 (first check); interrupt before step 2 (second check)
        return step_count[0] <= 1

    bus, platform = _platform(checker=checker)

    def step2_handler(_):
        step2_calls.append(1)
        return None

    async with platform.sequence() as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        seq.add(_exec(step2_handler, name="s2"))
        results = await seq.run()

    assert step2_calls == []
    assert results[-1].error_category == "interrupt"


# ──────────────────────────────────────────────
# on_step_complete callback
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_step_complete_injects_execution():
    """Callback returning [new_exec] inserts it after the current step."""
    ran: list[str] = []
    bus, platform = _platform()

    def make_handler(name):
        def h(_):
            ran.append(name)
            return None

        return h

    injected_exec = _exec(make_handler("injected"), name="injected")

    async with platform.sequence() as seq:
        seq.add(_exec(make_handler("s1"), name="s1"))
        seq.add(_exec(make_handler("s2"), name="s2"))
        seq.on_step_complete = lambda idx, result: [injected_exec] if idx == 0 else None
        results = await seq.run()

    # s1 → injected (after s1) → s2
    assert ran == ["s1", "injected", "s2"]
    assert all(r.ok for r in results)


@pytest.mark.asyncio
async def test_on_step_complete_none_does_not_inject():
    """Callback returning None leaves execution list unchanged."""
    ran: list[str] = []
    bus, platform = _platform()

    async with platform.sequence() as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        seq.add(_exec(_ok_handler(), name="s2"))
        seq.on_step_complete = lambda idx, result: None
        results = await seq.run()

    assert len(results) == 2
    assert all(r.ok for r in results)


# ──────────────────────────────────────────────
# add() guard
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_after_run_raises():
    """Calling add() after run() raises RuntimeError."""
    bus, platform = _platform()
    async with platform.sequence() as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        await seq.run()
        with pytest.raises(RuntimeError):
            seq.add(_exec(_ok_handler(), name="s2"))


# ──────────────────────────────────────────────
# Event emission
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sequence_started_event_emitted():
    """sequence.started is published before the first step."""
    bus, platform = _platform()
    async with platform.sequence() as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        await seq.run()

    kinds = _seq_events(bus)
    assert "execution.sequence.started" in kinds
    assert kinds.index("execution.sequence.started") == 0


@pytest.mark.asyncio
async def test_sequence_completed_event_emitted():
    """sequence.completed is published when all steps succeed."""
    bus, platform = _platform()
    async with platform.sequence() as seq:
        seq.add(_exec(_ok_handler(), name="s1"))
        await seq.run()

    kinds = _seq_events(bus)
    assert "execution.sequence.completed" in kinds
    assert "execution.sequence.failed" not in kinds


@pytest.mark.asyncio
async def test_sequence_failed_event_emitted():
    """sequence.failed is published when a step fails."""
    bus, platform = _platform()

    def fail_handler(_):
        raise PermanentError("nope")

    async with platform.sequence() as seq:
        seq.add(_exec(fail_handler, name="s1"))
        await seq.run()

    kinds = _seq_events(bus)
    assert "execution.sequence.failed" in kinds
    assert "execution.sequence.completed" not in kinds
