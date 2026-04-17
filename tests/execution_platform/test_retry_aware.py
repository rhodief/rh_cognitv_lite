"""Tests for DD-12: Retry-aware execution platform extension."""

import asyncio

import pytest

from rh_cognitv_lite.execution_platform import (
    EventBus,
    Execution,
    ExecutionPlatform,
    OutputValidationError,
    RetryAttemptRecord,
    RetryConfig,
    RetryContext,
    TransientError,
)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def platform(event_bus: EventBus) -> ExecutionPlatform:
    return ExecutionPlatform(event_bus=event_bus)


# ---------------------------------------------------------------------------
# Backward compatibility: existing handlers unaffected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_non_retry_aware_handler_receives_only_input(platform: ExecutionPlatform):
    """A handler without retry_aware=True receives only input_data, even on retries."""
    calls: list[tuple] = []
    attempt = 0

    def handler(data):
        nonlocal attempt
        attempt += 1
        calls.append((data,))
        if attempt < 2:
            raise TransientError("transient")
        return {"ok": True}

    exec_ = Execution(
        name="compat",
        handler=handler,
        input_data={"x": 1},
        retry_config=RetryConfig(max_attempts=3, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert len(calls) == 2
    # Each call received exactly one argument (input_data)
    for call in calls:
        assert len(call) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_non_retry_aware_async_handler(platform: ExecutionPlatform):
    """Async handler without retry_aware works as before."""
    attempt = 0

    async def handler(data):
        nonlocal attempt
        attempt += 1
        if attempt < 2:
            raise TransientError("fail")
        return {"done": True}

    exec_ = Execution(
        name="compat-async",
        handler=handler,
        input_data={},
        retry_config=RetryConfig(max_attempts=2, base_delay=0.0),
    )
    result = await platform(exec_)
    assert result.ok


# ---------------------------------------------------------------------------
# retry_aware=True: handler receives RetryContext on retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_retry_aware_first_attempt_no_context(platform: ExecutionPlatform):
    """On the first attempt, even retry_aware handlers receive only input_data."""
    received_args: list[tuple] = []

    def handler(*args):
        received_args.append(args)
        return {"v": 1}

    exec_ = Execution(
        name="first-attempt",
        handler=handler,
        input_data={"k": "v"},
        retry_aware=True,
    )
    result = await platform(exec_)

    assert result.ok
    assert len(received_args) == 1
    assert len(received_args[0]) == 1  # Only input_data, no RetryContext


@pytest.mark.asyncio(loop_scope="function")
async def test_retry_aware_sync_handler_receives_context(platform: ExecutionPlatform):
    """A sync retry_aware handler receives RetryContext on retry attempts."""
    received_contexts: list[RetryContext | None] = []
    attempt = 0

    def handler(data, retry_ctx: RetryContext | None = None):
        nonlocal attempt
        attempt += 1
        received_contexts.append(retry_ctx)
        if attempt < 2:
            raise TransientError("oops")
        return {"fixed": True}

    exec_ = Execution(
        name="retry-sync",
        handler=handler,
        input_data={"a": 1},
        retry_aware=True,
        retry_config=RetryConfig(max_attempts=3, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert len(received_contexts) == 2
    # First attempt: no context (only 1 arg passed)
    assert received_contexts[0] is None
    # Second attempt: has context
    ctx = received_contexts[1]
    assert isinstance(ctx, RetryContext)
    assert ctx.attempt == 2
    assert ctx.max_attempts == 3
    assert ctx.error_message == "oops"
    assert len(ctx.history) == 1
    assert ctx.history[0].attempt == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_retry_aware_async_handler_receives_context(platform: ExecutionPlatform):
    """An async retry_aware handler receives RetryContext on retry attempts."""
    received_contexts: list[RetryContext | None] = []
    attempt = 0

    async def handler(data, retry_ctx: RetryContext | None = None):
        nonlocal attempt
        attempt += 1
        received_contexts.append(retry_ctx)
        if attempt < 2:
            raise TransientError("async-oops")
        return {"async_fixed": True}

    exec_ = Execution(
        name="retry-async",
        handler=handler,
        input_data={},
        retry_aware=True,
        retry_config=RetryConfig(max_attempts=2, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert len(received_contexts) == 2
    assert received_contexts[0] is None
    ctx = received_contexts[1]
    assert isinstance(ctx, RetryContext)
    assert ctx.attempt == 2
    assert "async-oops" in ctx.error_message


# ---------------------------------------------------------------------------
# RetryContext.history accumulation across multiple retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_retry_context_history_accumulates(platform: ExecutionPlatform):
    """RetryContext.history grows with each failed attempt."""
    attempt = 0
    captured_histories: list[list[RetryAttemptRecord]] = []

    def handler(data, retry_ctx: RetryContext | None = None):
        nonlocal attempt
        attempt += 1
        if retry_ctx is not None:
            captured_histories.append(list(retry_ctx.history))
        if attempt < 4:
            raise TransientError(f"fail-{attempt}")
        return {"finally": True}

    exec_ = Execution(
        name="history",
        handler=handler,
        input_data={},
        retry_aware=True,
        retry_config=RetryConfig(max_attempts=5, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert attempt == 4
    # Attempt 2 sees 1 history entry, attempt 3 sees 2, attempt 4 sees 3
    assert len(captured_histories) == 3
    assert len(captured_histories[0]) == 1
    assert len(captured_histories[1]) == 2
    assert len(captured_histories[2]) == 3
    # Verify history entries have correct attempt numbers
    assert captured_histories[2][0].attempt == 1
    assert captured_histories[2][1].attempt == 2
    assert captured_histories[2][2].attempt == 3


# ---------------------------------------------------------------------------
# before_retry callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_before_retry_modifies_execution(platform: ExecutionPlatform):
    """before_retry can return a modified Execution for the next attempt."""
    attempt = 0

    def handler(data):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise TransientError("need different input")
        return data

    def before_retry(exec_: Execution, ctx: RetryContext) -> Execution:
        return exec_.model_copy(update={"input_data": {"adjusted": True}})

    exec_ = Execution(
        name="before-retry-mod",
        handler=handler,
        input_data={"original": True},
        before_retry=before_retry,
        retry_config=RetryConfig(max_attempts=2, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert result.value == {"adjusted": True}


@pytest.mark.asyncio(loop_scope="function")
async def test_before_retry_returns_none_keeps_original(platform: ExecutionPlatform):
    """before_retry returning None keeps the original Execution unchanged."""
    attempt = 0

    def handler(data):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise TransientError("try again")
        return data

    def before_retry(exec_: Execution, ctx: RetryContext) -> None:
        return None

    exec_ = Execution(
        name="before-retry-none",
        handler=handler,
        input_data={"keep": True},
        before_retry=before_retry,
        retry_config=RetryConfig(max_attempts=2, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert result.value == {"keep": True}


@pytest.mark.asyncio(loop_scope="function")
async def test_before_retry_receives_correct_context(platform: ExecutionPlatform):
    """before_retry callback receives a RetryContext with the right info."""
    captured: list[RetryContext] = []
    attempt = 0

    def handler(data):
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise TransientError(f"err-{attempt}")
        return {"ok": True}

    def before_retry(exec_: Execution, ctx: RetryContext) -> None:
        captured.append(ctx)
        return None

    exec_ = Execution(
        name="before-retry-ctx",
        handler=handler,
        input_data={},
        before_retry=before_retry,
        retry_config=RetryConfig(max_attempts=3, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert len(captured) == 2
    assert captured[0].attempt == 2
    assert captured[0].error_message == "err-1"
    assert len(captured[0].history) == 1
    assert captured[1].attempt == 3
    assert captured[1].error_message == "err-2"
    assert len(captured[1].history) == 2


# ---------------------------------------------------------------------------
# OutputValidationError triggers retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_output_validation_error_is_retryable(platform: ExecutionPlatform):
    """OutputValidationError (TransientError) triggers a retry."""
    attempt = 0

    def handler(data):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise OutputValidationError("bad output format")
        return {"valid": True}

    exec_ = Execution(
        name="output-val",
        handler=handler,
        input_data={},
        retry_config=RetryConfig(max_attempts=2, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert attempt == 2


@pytest.mark.asyncio(loop_scope="function")
async def test_output_validation_error_with_retry_aware(platform: ExecutionPlatform):
    """OutputValidationError with retry_aware=True provides context to handler."""
    contexts: list[RetryContext | None] = []
    attempt = 0

    def handler(data, retry_ctx: RetryContext | None = None):
        nonlocal attempt
        attempt += 1
        contexts.append(retry_ctx)
        if attempt == 1:
            raise OutputValidationError("schema mismatch")
        return {"valid": True}

    exec_ = Execution(
        name="output-val-aware",
        handler=handler,
        input_data={},
        retry_aware=True,
        retry_config=RetryConfig(max_attempts=2, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert contexts[0] is None
    ctx = contexts[1]
    assert isinstance(ctx, RetryContext)
    assert "schema mismatch" in ctx.error_message
    assert ctx.error_type == "OutputValidationError"


# ---------------------------------------------------------------------------
# RetryContext.previous_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_retry_context_has_previous_result(platform: ExecutionPlatform):
    """RetryContext.previous_result contains the failed ExecutionResult."""
    captured: list[RetryContext] = []
    attempt = 0

    def handler(data, retry_ctx: RetryContext | None = None):
        nonlocal attempt
        attempt += 1
        if retry_ctx is not None:
            captured.append(retry_ctx)
        if attempt == 1:
            raise TransientError("fail first")
        return {"success": True}

    exec_ = Execution(
        name="prev-result",
        handler=handler,
        input_data={},
        retry_aware=True,
        retry_config=RetryConfig(max_attempts=2, base_delay=0.0),
    )
    result = await platform(exec_)

    assert result.ok
    assert len(captured) == 1
    prev = captured[0].previous_result
    assert prev is not None
    assert not prev.ok
    assert prev.error_message == "fail first"


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_retry_attempt_record_fields():
    """RetryAttemptRecord stores attempt metadata."""
    record = RetryAttemptRecord(
        attempt=1,
        error_message="fail",
        error_category="TRANSIENT",
        error_type="TransientError",
        duration_ms=150.5,
    )
    assert record.attempt == 1
    assert record.error_message == "fail"
    assert record.duration_ms == 150.5


def test_retry_context_fields():
    """RetryContext captures full retry state."""
    ctx = RetryContext(
        attempt=3,
        max_attempts=5,
        error_message="err",
        error_category="TRANSIENT",
        error_type="TransientError",
        history=[
            RetryAttemptRecord(
                attempt=1, error_message="e1", error_category="TRANSIENT",
                error_type="TransientError", duration_ms=100.0,
            ),
            RetryAttemptRecord(
                attempt=2, error_message="e2", error_category="TRANSIENT",
                error_type="TransientError", duration_ms=200.0,
            ),
        ],
    )
    assert ctx.attempt == 3
    assert len(ctx.history) == 2
    assert ctx.previous_result is None
