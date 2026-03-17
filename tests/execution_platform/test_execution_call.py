"""Phase 1 unit tests — ExecutionPlatform.__call__ hardening."""
from __future__ import annotations

import pytest
import jsonschema
from pydantic import BaseModel

from rh_cognitv_lite.execution_platform.errors import PermanentError, TransientError
from rh_cognitv_lite.execution_platform.event_bus import EventBus
from rh_cognitv_lite.execution_platform.events import (
    ExecutionEvent,
    InterruptEvent,
    InterruptReason,
    InterruptSignal,
)
from rh_cognitv_lite.execution_platform.execution import (
    CheckSchema,
    Execution,
    ExecutionPlatform,
    Serializable,
    _to_dict,
)
from rh_cognitv_lite.execution_platform.models import EventStatus


def _exec(
    handler,
    *,
    input_data=None,
    preconditions=None,
    postconditions=None,
    name: str = "test_exec",
) -> Execution:
    return Execution(
        name=name,
        handler=handler,
        input_data=input_data,
        preconditions=preconditions,
        postconditions=postconditions,
    )


def _platform(*, checker=None) -> tuple[EventBus, ExecutionPlatform]:
    bus = EventBus()
    return bus, ExecutionPlatform(event_bus=bus, interrupt_checker=checker)


def _failed_events(bus: EventBus) -> list[ExecutionEvent]:
    return [e for e in bus.events if isinstance(e, ExecutionEvent) and e.status == EventStatus.FAILED]


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_handler_called_with_input():
    received = []

    def handler(inp):
        received.append(inp)
        return {"result": 42}

    bus, platform = _platform()
    result = await platform(_exec(handler, input_data={"value": 7}))

    assert result.ok is True
    assert result.value == {"result": 42}
    assert received[0] == {"value": 7}


@pytest.mark.asyncio
async def test_async_handler_called_with_input():
    received = []

    async def handler(inp):
        received.append(inp)
        return {"result": 99}

    bus, platform = _platform()
    result = await platform(_exec(handler, input_data={"value": 3}))

    assert result.ok is True
    assert result.value == {"result": 99}
    assert received[0] == {"value": 3}


@pytest.mark.asyncio
async def test_metadata_populated_on_success():
    bus, platform = _platform()
    result = await platform(_exec(lambda _: {"result": 1}))

    assert result.ok is True
    assert result.metadata.duration_ms >= 0
    assert result.metadata.attempt == 1
    assert isinstance(result.metadata.started_at, str)
    assert isinstance(result.metadata.completed_at, str)


@pytest.mark.asyncio
async def test_metadata_populated_on_failure():
    def bad(_):
        raise RuntimeError("boom")

    bus, platform = _platform()
    result = await platform(_exec(bad))

    assert result.ok is False
    assert result.metadata.duration_ms >= 0
    assert isinstance(result.metadata.started_at, str)
    assert isinstance(result.metadata.completed_at, str)
    assert result.metadata.attempt >= 1


@pytest.mark.asyncio
async def test_handler_exception_returns_ok_false():
    def bad(_):
        raise RuntimeError("unexpected failure")

    bus, platform = _platform()
    result = await platform(_exec(bad))

    assert result.ok is False
    assert result.error_details is not None
    assert result.error_details["type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_handler_exception_emits_failed_event():
    def bad(_):
        raise RuntimeError("boom")

    bus, platform = _platform()
    await platform(_exec(bad))

    assert len(_failed_events(bus)) == 1


@pytest.mark.asyncio
async def test_error_details_fields_present():
    def bad(_):
        raise RuntimeError("details test")

    bus, platform = _platform()
    result = await platform(_exec(bad))

    details = result.error_details
    assert details is not None
    for key in ("type", "message", "retryable", "category", "attempt"):
        assert key in details, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_precondition_failure_returns_ok_false():
    called = []

    def handler(_):
        called.append(True)
        return {}

    bus, platform = _platform()
    result = await platform(_exec(handler, preconditions=[lambda _: False]))

    assert result.ok is False
    assert len(called) == 0  # handler never reached


@pytest.mark.asyncio
async def test_postcondition_failure_returns_ok_false():
    bus, platform = _platform()
    result = await platform(
        _exec(
            lambda _: {"result": 5},
            postconditions=[lambda _: False],
        )
    )

    assert result.ok is False
    assert result.value == {"result": 5}  # value still set


@pytest.mark.asyncio
async def test_interrupt_checker_false_stops_execution():
    called = []

    def handler(_):
        called.append(True)
        return {}

    bus, platform = _platform(checker=lambda: False)
    result = await platform(_exec(handler))

    assert result.ok is False
    assert result.error_category == "interrupt"
    assert len(called) == 0  # handler never reached


@pytest.mark.asyncio
async def test_interrupt_checker_interrupt_signal_stops_execution():
    signal = InterruptSignal(reason=InterruptReason.USER_CANCELLED, message="cancelled by test")
    bus, platform = _platform(checker=lambda: signal)
    result = await platform(_exec(lambda _: {}))

    assert result.ok is False
    assert result.error_category == "interrupt"


@pytest.mark.asyncio
async def test_interrupt_checker_true_allows_execution():
    bus, platform = _platform(checker=lambda: True)
    result = await platform(_exec(lambda _: {"result": 7}))

    assert result.ok is True


@pytest.mark.asyncio
async def test_interrupt_checker_none_allows_execution():
    bus, platform = _platform(checker=lambda: None)
    result = await platform(_exec(lambda _: {"result": 7}))

    assert result.ok is True


@pytest.mark.asyncio
async def test_interrupt_emits_interrupt_event_on_bus():
    bus, platform = _platform(checker=lambda: False)
    await platform(_exec(lambda _: {}))

    interrupt_events = [e for e in bus.events if isinstance(e, InterruptEvent)]
    assert len(interrupt_events) == 1


@pytest.mark.asyncio
async def test_no_interrupt_checker_runs_normally():
    bus, platform = _platform()  # no checker at all
    result = await platform(_exec(lambda _: {"result": 1}))

    assert result.ok is True


# ──────────────────────────────────────────────
# Serializable protocol
# ──────────────────────────────────────────────


class _Point:
    """Plain class implementing Serializable via to_dict()."""

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}


class _PydanticPoint(BaseModel):
    """Pydantic model adapted to the Serializable protocol."""

    x: int
    y: int

    def to_dict(self) -> dict:
        return self.model_dump()


def test_serializable_protocol_satisfied_by_plain_class():
    assert isinstance(_Point(1, 2), Serializable)


def test_serializable_protocol_satisfied_by_adapted_pydantic():
    assert isinstance(_PydanticPoint(x=1, y=2), Serializable)


def test_plain_dict_not_serializable_instance():
    # dict is NOT a Serializable (no to_dict method), but _to_dict handles it separately
    assert not isinstance({"a": 1}, Serializable)


def test_to_dict_with_none():
    assert _to_dict(None) == {}


def test_to_dict_with_plain_dict():
    d = {"key": "value"}
    assert _to_dict(d) is d  # same object, no copy


def test_to_dict_with_serializable_plain_class():
    assert _to_dict(_Point(3, 4)) == {"x": 3, "y": 4}


def test_to_dict_with_adapted_pydantic():
    assert _to_dict(_PydanticPoint(x=5, y=6)) == {"x": 5, "y": 6}


def test_to_dict_raises_for_unadapted_pydantic():
    """A Pydantic model without to_dict() is not Serializable and not a dict → TypeError."""

    class _Bare(BaseModel):
        value: int

    with pytest.raises(TypeError):
        _to_dict(_Bare(value=1))


def test_to_dict_raises_for_arbitrary_object():
    with pytest.raises(TypeError):
        _to_dict(object())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_serializable_object_as_input_data():
    received = []

    def handler(inp):
        received.append(inp)
        return {"ok": True}

    bus, platform = _platform()
    result = await platform(_exec(handler, input_data=_Point(10, 20)))

    assert result.ok is True
    assert received[0] is _Point(10, 20) or received[0].x == 10


@pytest.mark.asyncio
async def test_adapted_pydantic_as_input_data():
    received = []

    def handler(inp):
        received.append(inp)
        return {"ok": True}

    bus, platform = _platform()
    point = _PydanticPoint(x=7, y=8)
    result = await platform(_exec(handler, input_data=point))

    assert result.ok is True
    assert received[0].x == 7
    assert received[0].y == 8


@pytest.mark.asyncio
async def test_serializable_handler_return_stored_as_value():
    """Handler can return a Serializable; it is stored as-is in result.value."""

    def handler(_):
        return _Point(1, 2)

    bus, platform = _platform()
    result = await platform(_exec(handler))

    assert result.ok is True
    assert isinstance(result.value, _Point)
    assert result.value.to_dict() == {"x": 1, "y": 2}


# ──────────────────────────────────────────────
# CheckSchema
# ──────────────────────────────────────────────

_POINT_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "integer"},
        "y": {"type": "integer"},
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}


def test_check_schema_passes_valid_dict():
    checker = CheckSchema(_POINT_SCHEMA)
    assert checker({"x": 1, "y": 2}) is True


def test_check_schema_passes_valid_serializable():
    checker = CheckSchema(_POINT_SCHEMA)
    assert checker(_Point(3, 4)) is True


def test_check_schema_passes_valid_adapted_pydantic():
    checker = CheckSchema(_POINT_SCHEMA)
    assert checker(_PydanticPoint(x=5, y=6)) is True


def test_check_schema_raises_on_missing_required_field():
    checker = CheckSchema(_POINT_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        checker({"x": 1})  # missing "y"


def test_check_schema_raises_on_wrong_type():
    checker = CheckSchema(_POINT_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        checker({"x": "not_an_int", "y": 2})


def test_check_schema_raises_on_additional_property():
    checker = CheckSchema(_POINT_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        checker({"x": 1, "y": 2, "z": 3})


def test_check_schema_passes_none_against_empty_schema():
    checker = CheckSchema({})  # accepts anything
    assert checker(None) is True


@pytest.mark.asyncio
async def test_check_schema_as_precondition_passes():
    bus, platform = _platform()
    result = await platform(
        _exec(
            lambda _: {"x": 9, "y": 0},
            input_data={"x": 1, "y": 2},
            preconditions=[CheckSchema(_POINT_SCHEMA)],
        )
    )
    assert result.ok is True


@pytest.mark.asyncio
async def test_check_schema_as_precondition_blocks_handler():
    called = []

    def handler(_):
        called.append(True)
        return {}

    bus, platform = _platform()
    result = await platform(
        _exec(
            handler,
            input_data={"x": "bad"},  # fails schema
            preconditions=[CheckSchema(_POINT_SCHEMA)],
        )
    )

    assert result.ok is False
    assert result.error_details["type"] == "PreconditionError"
    assert len(called) == 0  # handler never reached


@pytest.mark.asyncio
async def test_check_schema_as_postcondition_passes():
    bus, platform = _platform()
    result = await platform(
        _exec(
            lambda _: {"x": 3, "y": 4},
            postconditions=[CheckSchema(_POINT_SCHEMA)],
        )
    )
    assert result.ok is True
    assert result.value == {"x": 3, "y": 4}


@pytest.mark.asyncio
async def test_check_schema_as_postcondition_rejects_bad_output():
    bus, platform = _platform()
    result = await platform(
        _exec(
            lambda _: {"x": 1},  # missing "y"
            postconditions=[CheckSchema(_POINT_SCHEMA)],
        )
    )
    assert result.ok is False
    assert result.error_details["type"] == "PostconditionError"
    assert result.value == {"x": 1}  # value still captured


@pytest.mark.asyncio
async def test_check_schema_generated_from_pydantic_model():
    """JSON Schema generated from a Pydantic model works as a CheckSchema input."""

    class Coords(BaseModel):
        x: int
        y: int

    schema = Coords.model_json_schema()
    checker = CheckSchema(schema)

    assert checker({"x": 1, "y": 2}) is True

    with pytest.raises(jsonschema.ValidationError):
        checker({"x": "bad", "y": 2})
