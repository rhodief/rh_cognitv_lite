# Execution Platform

A lightweight, async-first execution engine for composing and running typed handler pipelines with retry, timeout, schema validation, observability, and interruption support.

---

## Core Concepts

### `Execution`

The atomic unit of work. Wraps a callable handler with its input data and optional lifecycle hooks.

```python
from rh_cognitv_lite.execution_platform import Execution

exec = Execution(
    name="greet",
    description="Greet the user",
    kind="greeting",          # optional tag surfaced in events
    group_id="my-pipeline",   # optional group for correlating events
    handler=my_handler,
    input_data={"name": "Alice"},
    preconditions=[...],      # called before handler
    postconditions=[...],     # called on handler output
)
```

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Identifies the execution in events |
| `description` | `str \| None` | Human-readable description |
| `kind` | `str \| None` | Event kind tag (defaults to `"default"`) |
| `group_id` | `str \| None` | Correlates events to a logical group |
| `handler` | `Callable` | Sync or async function — receives `input_data` |
| `input_data` | `ExecutionData` | `dict`, `Serializable`, or `None` |
| `preconditions` | `list[Callable]` | Run before handler; return `False` to abort |
| `postconditions` | `list[Callable]` | Run on handler output; return `False` to fail |

---

### `ExecutionData` and `Serializable`

Input and output data is typed as `dict[str, Any] | Serializable | None`.

**Plain dict:**
```python
input_data={"value": 42}
```

**`Serializable` Protocol** — any object with a `to_dict()` method:
```python
class MyData:
    def to_dict(self) -> dict:
        return {"value": self.value}
```

**Pydantic models** can be adapted:
```python
class MyModel(BaseModel):
    value: int

    def to_dict(self) -> dict:
        return self.model_dump()
```

---

### `ExecutionPlatform`

The runtime engine. Call it directly for a single execution, or use context managers for multi-step runs.

```python
from rh_cognitv_lite.execution_platform import ExecutionPlatform
from rh_cognitv_lite.execution_platform.event_bus import EventBus

platform = ExecutionPlatform(event_bus=EventBus())

result = await platform(exec)
print(result.ok, result.value)
```

#### `ExecutionResult`

```python
result.ok             # bool
result.value          # handler return value
result.error_message  # str | None
result.error_category # "transient" | "permanent" | "interrupt"
result.error_details  # dict with type, message, retryable, attempt
result.metadata       # duration_ms, attempt, started_at, completed_at
```

---

## Running Multiple Executions

### Sequence Runner

Runs steps in insertion order. The output of each step is automatically injected as `input_data` for the next step (output chaining).

```python
async with platform.sequence(
    group_name="my-pipeline",
    retry_config=RetryConfig(max_attempts=3),
    timeout_config=TimeoutConfig(each_execution_timeout=10.0),
) as seq:
    seq.add(step1)
    seq.add(step2)
    seq.add(step3)
    results = await seq.run()
```

- Each step receives the previous step's return value as its `input_data`.
- On retry, the entire sequence restarts from step 1.
- All events carry `group_id=group_name`.

**Lifecycle events emitted:** `sequence.started`, `sequence.completed`, `sequence.failed`, `sequence.retrying`

---

### Parallel Runner

Runs all steps concurrently, bounded by `max_concurrency`.

```python
async with platform.parallel(
    group_name="my-batch",
    parallel_config=ParallelConfig(max_concurrency=4, error_strategy="fail_slow"),
    retry_config=RetryConfig(max_attempts=2),
) as par:
    par.add(task1)
    par.add(task2)
    par.add(task3)
    results = await par.run()
```

Results are always returned in insertion order regardless of completion order.

**Error strategies:**
- `"fail_slow"` (default) — continue all tasks, retry only failed ones
- `"fail_fast"` — abort remaining tasks on first failure, retry the whole batch

**Lifecycle events emitted:** `parallel.started`, `parallel.completed`, `parallel.failed`, `parallel.retrying`

---

## Schema Validation with `CheckSchema`

A plug-and-play precondition/postcondition that validates data against a [JSON Schema](https://json-schema.org/).

```python
from rh_cognitv_lite.execution_platform import CheckSchema

schema = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
}

exec = Execution(
    name="validated-step",
    handler=my_handler,
    input_data={"value": 42},
    preconditions=[CheckSchema(schema)],
    postconditions=[CheckSchema(output_schema)],
)
```

Raises `jsonschema.ValidationError` on mismatch, which surfaces as a `PreconditionError` / `PostconditionError` with `ok=False`.

Pydantic models can provide their own schema:
```python
preconditions=[CheckSchema(MyModel.model_json_schema())]
```

---

## Retry

Configure retry behaviour with `RetryConfig`:

```python
from rh_cognitv_lite.execution_platform import RetryConfig

RetryConfig(
    max_attempts=3,      # total attempts (1 = no retry)
    base_delay=0.5,      # seconds before first retry
    max_delay=30.0,      # cap on back-off
    multiplier=2.0,      # exponential factor
)
```

Only errors with `retryable=True` trigger a retry. `TransientError` is retryable by default; `PermanentError` is not.

**Retry events** carry metadata in `ext`:
```python
event.retried              # number of retries so far
event.ext["max_retries"]   # retry ceiling (max_attempts - 1)
event.ext["retry_after"]   # seconds until next attempt
```

---

## Timeout

```python
from rh_cognitv_lite.execution_platform import TimeoutConfig

TimeoutConfig(
    each_execution_timeout=10.0,   # per-step timeout (seconds)
    total_timeout=60.0,            # total run timeout (seconds)
)
```

Timeout failures emit an `InterruptEvent` and return `ok=False` with `error_category="interrupt"`.

---

## Observability — `EventBus`

Every execution emits a stream of `ExecutionEvent` objects. Subscribe to handle them:

```python
from rh_cognitv_lite.execution_platform.event_bus import EventBus

bus = EventBus()
bus.subscribe(lambda e: print(e.kind, e.status, e.group_id))

platform = ExecutionPlatform(event_bus=bus)
```

Subscribers can be sync or async. Each event is also stored in `bus.events` for inspection.

### `ExecutionEvent` fields

| Field | Description |
|---|---|
| `id` | ULID — unique event identifier |
| `name` | Execution name |
| `kind` | Event type string (e.g. `"default"`, `"sequence.started"`) |
| `status` | `started` \| `completed` \| `failed` \| `retrying` \| `interrupted` \| … |
| `payload` | Serialized input or output data |
| `retried` | Number of retries that occurred before this event |
| `group_id` | Group name from the runner (for correlating a pipeline's events) |
| `parent_id` | Optional parent event ID |
| `ext` | Extra metadata (e.g. `max_retries`, `retry_after` on retrying events) |
| `created_at` | ISO 8601 timestamp |

---

## Error Hierarchy

```
CognitivError
├── TransientError    retryable=True,  category=transient
├── PermanentError    retryable=False, category=permanent
├── InterruptError    retryable=False, category=interrupt
├── EscalationError   retryable=False, category=escalation
└── BudgetError       retryable=False, category=permanent
```

Raise `TransientError` from a handler to engage retry machinery:

```python
from rh_cognitv_lite.execution_platform import TransientError

def handler(data):
    if not service.available():
        raise TransientError("Service unavailable, will retry")
    return service.call(data)
```

---

## Interrupt Support

Pass an `interrupt_checker` to the platform to support cooperative cancellation:

```python
cancelled = False

platform = ExecutionPlatform(
    event_bus=bus,
    interrupt_checker=lambda: not cancelled,
)

# From another coroutine:
cancelled = True
```

The checker is polled before each execution step. When it returns `False` or an `InterruptSignal`, an `InterruptEvent` is emitted and execution stops immediately.

---

## Quick Reference

```python
from rh_cognitv_lite.execution_platform import (
    ExecutionPlatform,
    Execution,
    ExecutionData,
    ExecutionResult,
    Serializable,
    CheckSchema,
    RetryConfig,
    TimeoutConfig,
    ParallelConfig,
    TransientError,
    PermanentError,
    InterruptError,
    ErrorCategory,
    EventStatus,
    ExecutionEvent,
    EventBus,
)
```
