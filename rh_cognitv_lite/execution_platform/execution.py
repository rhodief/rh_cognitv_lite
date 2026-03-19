

from __future__ import annotations

import asyncio
import inspect
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Protocol, runtime_checkable

import jsonschema
from pydantic import BaseModel

from rh_cognitv_lite.execution_platform.errors import ErrorCategory, InterruptError, TransientError, TransientError
from rh_cognitv_lite.execution_platform.event_bus import EventBus
from rh_cognitv_lite.execution_platform.events import (
    ExecutionEvent,
    InterruptEvent,
    InterruptReason,
    InterruptSignal,
)
from rh_cognitv_lite.execution_platform.models import EventStatus, ExecutionResult, ResultMetadata, RetryConfig, TimeoutConfig, ParallelConfig
from rh_cognitv_lite.execution_platform.types import now_timestamp


@runtime_checkable
class Serializable(Protocol):
    """Any object that can serialize itself to a plain dict."""

    def to_dict(self) -> dict[str, Any]: ...


# JSON-serializable data passed to/from handlers: a plain dict, any object
# with to_dict(), or None.
ExecutionData = dict[str, Any] | Serializable | None


def _to_dict(data: ExecutionData) -> dict[str, Any]:
    """Normalize ExecutionData to a plain dict for event payloads."""
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, Serializable):
        return data.to_dict()
    raise TypeError(f"Cannot serialize {type(data)!r} to dict — implement to_dict()")


def _safe_to_dict(data: Any) -> dict[str, Any]:
    """Like _to_dict but never raises — falls back to an error marker dict.

    Used exclusively for event payloads where observability must not crash execution.
    """
    try:
        return _to_dict(data)
    except (TypeError, Exception):
        return {"__unserializable__": repr(data)}


class CheckSchema:
    """Pre/postcondition hook that validates ExecutionData against a JSON Schema.

    Usage::

        schema = {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]}
        execution = Execution(
            name="my_step",
            handler=my_handler,
            input_data={"value": 1},
            preconditions=[CheckSchema(schema)],
        )

    Raises ``jsonschema.ValidationError`` (which surfaces as a precondition
    failure with ok=False) when the data does not match the schema.
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def __call__(self, data: ExecutionData) -> bool:
        jsonschema.validate(instance=_to_dict(data), schema=self._schema)
        return True


class Execution(BaseModel):
    name: str
    description: str | None = None
    kind: str | None = None
    handler: Callable[..., Any]
    input_data: ExecutionData | Any = None
    preconditions: list[Callable[[ExecutionData], bool]] | None = None
    postconditions: list[Callable[[ExecutionData], bool]] | None = None
    group_id: str | None = None
    policies: list[Any] | None = None
    attempt: int = 1  # set by runners on retry; drives retried= in emitted events
    retry_config: RetryConfig | None = None
    model_config = {"arbitrary_types_allowed": True}

    

class ExecutionPlatform:
    def __init__(
        self,
        event_bus: EventBus,
        interrupt_checker: Callable[[], bool | InterruptSignal | None] | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.interrupt_checker = interrupt_checker

    def _check_interrupt(self) -> None:
        """Poll the interrupt checker and raise InterruptError if interrupted."""
        if self.interrupt_checker is None:
            return
        result = self.interrupt_checker()
        if result is True or result is None:
            return
        if isinstance(result, InterruptSignal):
            signal = result
        else:
            signal = InterruptSignal(
                reason=InterruptReason.USER_CANCELLED,
                message="Interrupt checker returned False",
            )
        raise InterruptError(signal.message or "Execution interrupted", signal=signal)

    async def __call__(self, input_execution: Execution) -> ExecutionResult[Any]:
        retry_config = input_execution.retry_config
        max_attempts = retry_config.max_attempts if retry_config else 1
        result: ExecutionResult[Any] | None = None

        for attempt in range(1, max_attempts + 1):
            exec_item = (
                input_execution
                if attempt == 1
                else input_execution.model_copy(update={"attempt": attempt})
            )
            result = await self._execute_once(exec_item)

            if result.ok:
                return result

            retryable = (
                result.error_details.get("retryable", False)
                if result.error_details
                else False
            )
            if not retryable or attempt >= max_attempts:
                return result

            delay = retry_config.delay_for(attempt) if retry_config else 0.0
            await asyncio.sleep(delay)

        return result  # type: ignore[return-value]

    async def _execute_once(self, input_execution: Execution) -> ExecutionResult[Any]:
        started_at = now_timestamp()
        t_start = time.monotonic()

        # 1. Check interrupt before doing any work
        try:
            self._check_interrupt()
        except InterruptError as exc:
            signal: InterruptSignal = getattr(exc, "signal", None) or InterruptSignal(
                reason=InterruptReason.USER_CANCELLED
            )
            await self.event_bus.publish(
                InterruptEvent(signal=signal, state_id=input_execution.name)
            )
            return ExecutionResult[Any](
                ok=False,
                error_message=str(exc),
                error_category=ErrorCategory.INTERRUPT.value,
                error_details={
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": False,
                    "category": ErrorCategory.INTERRUPT.value,
                    "attempt": input_execution.attempt,
                },
                metadata=ResultMetadata(
                    attempt=input_execution.attempt,
                    started_at=started_at,
                    completed_at=now_timestamp(),
                    duration_ms=(time.monotonic() - t_start) * 1000,
                ),
            )

        # 2. Emit STARTED event
        retried = max(0, input_execution.attempt - 1)
        await self.event_bus.publish(
            ExecutionEvent(
                name=input_execution.name,
                description=input_execution.description,
                kind=input_execution.kind or "default",
                payload=_safe_to_dict(input_execution.input_data),
                status=EventStatus.STARTED,
                retried=retried,
                group_id=input_execution.group_id,
            )
        )

        # 3. Preconditions
        if input_execution.preconditions:
            for precondition in input_execution.preconditions:
                precond_exc: Exception | None = None
                try:
                    passed = precondition(input_execution.input_data)
                except Exception as exc:
                    precond_exc = exc
                    passed = False
                if not passed:
                    completed_at = now_timestamp()
                    _retryable = getattr(precond_exc, "retryable", False) if precond_exc else False
                    _category = getattr(precond_exc, "category", ErrorCategory.PERMANENT) if precond_exc else ErrorCategory.PERMANENT
                    _cat_val = _category.value if isinstance(_category, ErrorCategory) else str(_category)
                    _error_msg = str(precond_exc) if precond_exc else "Precondition failed"
                    await self.event_bus.publish(
                        ExecutionEvent(
                            name=input_execution.name,
                            description=input_execution.description,
                            kind=input_execution.kind or "default",
                            payload={},
                            status=EventStatus.FAILED,
                            retried=retried,
                            group_id=input_execution.group_id,
                        )
                    )
                    return ExecutionResult[Any](
                        ok=False,
                        error_message=_error_msg,
                        error_category=_cat_val,
                        error_details={
                            "type": "PreconditionError",
                            "message": _error_msg,
                            "retryable": _retryable,
                            "category": _cat_val,
                            "attempt": input_execution.attempt,
                        },
                        metadata=ResultMetadata(
                            attempt=input_execution.attempt,
                            started_at=started_at,
                            completed_at=completed_at,
                            duration_ms=(time.monotonic() - t_start) * 1000,
                        ),
                    )

        # 4. Call handler (sync or async)
        try:
            if not (
                input_execution.input_data is None
                or isinstance(input_execution.input_data, dict)
                or isinstance(input_execution.input_data, Serializable)
            ):
                raise TransientError(
                    f"input_data must be a dict, Serializable, or None — got {type(input_execution.input_data).__name__!r}"
                )
            if inspect.iscoroutinefunction(input_execution.handler):
                result_data: ExecutionData = await input_execution.handler(input_execution.input_data)
            else:
                result_data = input_execution.handler(input_execution.input_data)
        except Exception as exc:
            completed_at = now_timestamp()
            duration_ms = (time.monotonic() - t_start) * 1000
            category = getattr(exc, "category", ErrorCategory.PERMANENT)
            retryable = getattr(exc, "retryable", False)
            attempt_num = input_execution.attempt
            cat_val = category.value if isinstance(category, ErrorCategory) else str(category)
            await self.event_bus.publish(
                ExecutionEvent(
                    name=input_execution.name,
                    description=input_execution.description,
                    kind=input_execution.kind or "default",
                    payload={"error": str(exc)},
                    status=EventStatus.FAILED,
                    retried=retried,
                    group_id=input_execution.group_id,
                )
            )
            return ExecutionResult[Any](
                ok=False,
                error_message=str(exc),
                error_category=cat_val,
                error_details={
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": retryable,
                    "category": cat_val,
                    "attempt": attempt_num,
                },
                metadata=ResultMetadata(
                    attempt=attempt_num,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                ),
            )

        # 5. Postconditions
        if input_execution.postconditions:
            for postcondition in input_execution.postconditions:
                postcond_exc: Exception | None = None
                try:
                    passed = postcondition(result_data)
                except Exception as exc:
                    postcond_exc = exc
                    passed = False
                if not passed:
                    completed_at = now_timestamp()
                    duration_ms = (time.monotonic() - t_start) * 1000
                    _retryable = getattr(postcond_exc, "retryable", False) if postcond_exc else False
                    _category = getattr(postcond_exc, "category", ErrorCategory.PERMANENT) if postcond_exc else ErrorCategory.PERMANENT
                    _cat_val = _category.value if isinstance(_category, ErrorCategory) else str(_category)
                    _error_msg = str(postcond_exc) if postcond_exc else "Postcondition failed"
                    await self.event_bus.publish(
                        ExecutionEvent(
                            name=input_execution.name,
                            description=input_execution.description,
                            kind=input_execution.kind or "default",
                            payload=_safe_to_dict(result_data),
                            status=EventStatus.FAILED,
                            retried=retried,
                            group_id=input_execution.group_id,
                        )
                    )
                    return ExecutionResult[Any](
                        ok=False,
                        value=result_data,
                        error_message=_error_msg,
                        error_category=_cat_val,
                        error_details={
                            "type": "PostconditionError",
                            "message": _error_msg,
                            "retryable": _retryable,
                            "category": _cat_val,
                            "attempt": input_execution.attempt,
                        },
                        metadata=ResultMetadata(
                            attempt=input_execution.attempt,
                            started_at=started_at,
                            completed_at=completed_at,
                            duration_ms=duration_ms,
                        ),
                    )

        # 6. Emit COMPLETED and return success
        completed_at = now_timestamp()
        duration_ms = (time.monotonic() - t_start) * 1000
        await self.event_bus.publish(
            ExecutionEvent(
                name=input_execution.name,
                description=input_execution.description,
                kind=input_execution.kind or "default",
                payload=_safe_to_dict(result_data),
                status=EventStatus.COMPLETED,
                retried=retried,
                group_id=input_execution.group_id,
            )
        )
        return ExecutionResult[Any](
            ok=True,
            value=result_data,
            metadata=ResultMetadata(
                attempt=input_execution.attempt,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            ),
        )

    @asynccontextmanager
    async def sequence(
        self,
        group_name: str | None = None,
        retry_config: RetryConfig | None = None,
        timeout_config: TimeoutConfig | None = None,
    ):
        """Async context manager that yields a SequenceRunner.

        Steps added via runner.add() execute in insertion order.
        Output of each step is injected as input to the next step.
        """
        from rh_cognitv_lite.execution_platform.execution_runners import SequenceRunner

        runner = SequenceRunner(self, retry_config, timeout_config, group_name=group_name)
        try:
            yield runner
        except Exception:
            raise

    @asynccontextmanager
    async def parallel(
        self,
        group_name: str | None = None, 
        parallel_config: ParallelConfig | None = None,
        retry_config: RetryConfig | None = None,
        timeout_config: TimeoutConfig | None = None,
    ):
        """Async context manager that yields a ParallelRunner.  

        Tasks added via runner.add() execute concurrently up to
        parallel_config.max_concurrency.
        """
        from rh_cognitv_lite.execution_platform.execution_runners import ParallelRunner

        runner = ParallelRunner(self, parallel_config or ParallelConfig(), retry_config, timeout_config, group_name=group_name)
        try:
            yield runner
        except Exception:
            raise
