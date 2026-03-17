# Spec 01 — ExecutionPlatform: Sequence & Parallel Execution

## Status: Complete ✓

---

## 1. Background & Current Behaviour

### 1.1 Core Primitives

| Type | Role |
|---|---|
| `Execution` | Declarative description of a unit of work: handler, input/output models, pre/postconditions, policies, metadata. |
| `ExecutionPlatform` | Async callable that runs a single `Execution` and returns `ExecutionResult[BaseModel]`. |
| `EventBus` | Hybrid sync-middleware + async subscriber bus. All platform activity is observable through it. |
| `ExecutionEvent` | Data-only record emitted at start and completion of each execution. |
| `ExecutionResult[T]` | Generic result envelope: `ok`, `value`, `error_message`, `error_category`, `metadata`. |

### 1.2 Single-Execution Flow (`ExecutionPlatform.__call__`)

```
caller
  │
  ▼
publish ExecutionEvent(status=STARTED)
  │
  ▼
run preconditions ──► fail ──► return ExecutionResult(ok=False)
  │ pass
  ▼
call handler(inputModel) ──► raw dict
  │
  ▼
validate output: outputModel.model_validate(raw) if outputModel
  │
  ▼
run postconditions ──► fail ──► return ExecutionResult(ok=False, value=result)
  │ pass
  ▼
publish ExecutionEvent(status=COMPLETED)
  │
  ▼
return ExecutionResult(ok=True, value=result)
```

**Current limitations:**
- The handler is typed `Callable[[Optional[Any]], Dict | None]` (synchronous only).
- There is no error handling: uncaught exceptions from the handler propagate to the caller with no `FAILED` event emitted.
- `ResultMetadata` fields (`duration_ms`, `attempt`, `started_at`, `completed_at`) exist but are never populated.
- `policies` field on `Execution` is declared but has no effect.
- No retry, timeout, or concurrency logic exists.

---

## 2. Goal

Extend `ExecutionPlatform` with two new context-manager-based orchestration modes:

| Mode | API | Semantics |
|---|---|---|
| **Sequence** | `execution_platform.sequence(retry_config, timeout_config)` | Run executions one after another; pipe output of each as input to the next. |
| **Parallel** | `execution_platform.parallel(parallel_config, retry_config, timeout_config)` | Run executions concurrently up to a maximum concurrency; collect results. |

Both modes produce a list of `ExecutionResult` and integrate with the existing `EventBus`, error hierarchy, and `InterruptSignal` infrastructure.

---

## 3. Configuration Models

### 3.1 `RetryConfig`

```python
class RetryConfig(BaseModel):
    max_attempts: int = 3         # total attempts (1 = no retry)
    base_delay: float = 0.1       # seconds before first retry
    max_delay: float = 30.0       # cap on exponential back-off
    multiplier: float = 2.0       # exponential growth factor
```

Back-off formula: `min(base_delay * multiplier^(attempt-1), max_delay)`.  
`RetryConfig = None` disables retries entirely.

Only `CognitivError` instances with `retryable=True` (i.e. `TransientError`) trigger a retry. `PermanentError` and other exceptions surface immediately.

### 3.2 `TimeoutConfig`

```python
class TimeoutConfig(BaseModel):
    each_execution_timeout: float = 60.0   # seconds per individual execution
    total_timeout: float = 300.0           # seconds for the entire run() call
```

`TimeoutConfig = None` disables all timeouts.

### 3.3 `ParallelConfig`

```python
class ParallelConfig(BaseModel):
    max_concurrency: int = 5
    error_strategy: Literal["fail_fast", "fail_slow"] = "fail_slow"
```

- **`fail_fast`**: the first failure cancels all in-flight tasks and triggers retry (if configured) for the entire batch.
- **`fail_slow`**: all tasks run to completion; failures are collected; retry (if configured) applies only to the failed tasks.

---

## 4. Sequence Execution

### 4.1 Usage

```python
async with execution_platform.sequence(retry_config, timeout_config) as seq:
    for execution in get_executions(...):
        seq.add(execution)
    results = await seq.run()
# results: list[ExecutionResult[BaseModel]]
```

### 4.2 Behaviour

1. Executions run in insertion order.
2. **Output chaining**: if execution N completes with `ok=True` and produces a `value`, that value is injected as `inputModel` into execution N+1. If N+1 already declares its own `inputModel`, it is overwritten.
3. **Failure handling**: if any execution fails (after exhausting retries), `run()` stops and returns results collected so far plus the failing result (with `ok=False`). Subsequent executions are not started.
4. **Retry scope**: retries apply to the entire sequence from the beginning (see [Decision D-02](#d-02-retry-scope-in-sequence)).
5. **Timeout**: `each_execution_timeout` guards each individual `__call__` invocation; `total_timeout` guards the sum of all steps including delays.
6. **Events emitted**:
   - `ExecutionEvent(kind="sequence.started")` — before the first step.
   - Per-step events from `ExecutionPlatform.__call__` (unchanged).
   - `ExecutionEvent(kind="sequence.completed" | "sequence.failed")` — after `run()` resolves.
7. **Interrupt & timeout**: both produce an `InterruptSignal` and go through the same abort path. `each_execution_timeout` wraps each `__call__` via `asyncio.wait_for()`; `total_timeout` wraps the full `run()`. An external `interrupt_checker` is polled before each step. On any interrupt, the current step result is marked `ok=False` with `error_category="interrupt"`, an `InterruptEvent` is published, and no further steps are started.

### 4.3 Return Value

`list[ExecutionResult[BaseModel]]` — one entry per execution that was started (partial on failure).

---

## 5. Parallel Execution

### 5.1 Usage

```python
async with execution_platform.parallel(parallel_config, retry_config, timeout_config) as par:
    for execution in get_executions(...):
        par.add(execution)
    results = await par.run()
# results: list[ExecutionResult[BaseModel]]
```

### 5.2 Behaviour

1. Up to `parallel_config.max_concurrency` executions run simultaneously using `asyncio.Semaphore`.
2. Results are returned in insertion order regardless of completion order.
3. **`fail_fast`**: on the first failure, all pending tasks receive a cancellation signal; in-progress tasks finish their current attempt. The entire batch is retried from scratch (if `retry_config` allows).
4. **`fail_slow`**: all tasks run to completion; after all finish, `run()` inspects failed tasks. If `retry_config` allows, only the failed tasks are retried (up to `max_attempts` total per task).
5. **Timeout**: `each_execution_timeout` wraps each individual task; `total_timeout` wraps the entire `run()` call.
6. **Events emitted**:
   - `ExecutionEvent(kind="parallel.started")` — before dispatching tasks.
   - Per-task events from `ExecutionPlatform.__call__` (unchanged).
   - `ExecutionEvent(kind="parallel.completed" | "parallel.failed")` — after `run()` resolves.
7. **Interrupt & timeout**: same unified path as sequence. `each_execution_timeout` wraps each individual task; `total_timeout` wraps the full `run()`. `interrupt_checker` is polled before each task is dispatched. On interrupt, in-flight tasks are cancelled (`fail_fast` semantics regardless of `error_strategy`); completed results are preserved; cancelled tasks return `ok=False` with `error_category="interrupt"`.

### 5.3 Return Value

`list[ExecutionResult[BaseModel]]` — one entry per execution, in insertion order; failed tasks carry `ok=False` and `error_message`.

---

## 6. Context Manager Contract

Both `sequence(...)` and `parallel(...)` return an async context manager. The `__aenter__` / `__aexit__` pair:

- `__aenter__`: constructs and returns the runner object (`SequenceRunner` / `ParallelRunner`).
- `__aexit__`: no-op under normal conditions; on an unhandled exception it may emit a terminal failure event before re-raising.

`add(execution)` is valid only between `__aenter__` and the first call to `run()`. Calling `add()` after `run()` raises `RuntimeError`.

---

## 7. `ResultMetadata` Population

After this work, `ResultMetadata` fields must be populated:

| Field | Source |
|---|---|
| `duration_ms` | wall-clock time from handler start to handler return |
| `attempt` | which retry attempt produced this result (1-indexed) |
| `started_at` | ISO-8601 timestamp just before handler call |
| `completed_at` | ISO-8601 timestamp just after handler return |

---

## 8. Implementation Decisions

> Decided items show only the chosen approach. Open items retain all options.

---

### D-01 — Handler Async Support ✓

**Decision:** Accept both sync and async handlers. Detect via `asyncio.iscoroutinefunction(handler)` and `await` when true; call directly when false.

**Rationale:** Zero breaking change; unlocks async handlers immediately with negligible overhead.

---

### D-02 — Retry Scope in Sequence ✓

**Decision:** Retry the entire sequence from step 1.

**Rationale:** Sequence semantics imply a transactional unit. If a caller wants per-execution independent retries, they wrap individual executions in their own `sequence()` calls.

---

### D-03 — Output Chaining: Type Safety ✓

**Decision:** Before injecting step N's `value` as step N+1's `inputModel`, validate using an `isinstance` check against the class of N+1's declared `inputModel`. On mismatch, surface a clear `TypeError`-based `ExecutionResult(ok=False)` rather than letting a cryptic `ValidationError` propagate.

---

### D-04 — Parallel Result Ordering ✓

**Decision:** Always return results in insertion order (`results[i]` corresponds to `executions[i]`).

---

### D-05 — `fail_fast` Cancellation Granularity ✓

**Decision:** Cancel in-flight tasks immediately via `asyncio.Task.cancel()`; mark all cancelled tasks `ok=False` with `error_category="interrupt"`.

**Note:** `fail_slow` is the default `error_strategy` in `ParallelConfig`. `fail_fast` is an opt-in for scenarios that require a completely clean, all-or-nothing batch.

---

### D-06 — `run()` Return on Full Failure ✓

**Decision:** Always return a list; never raise. Caller inspects `ok` flags and acts accordingly.

**Note:** `ExecutionResult` must carry sufficient structured error information for the caller to diagnose and act without re-running. See **S-04** for the enriched error model.

---

### D-07 — Interrupt Mechanism ✓

**Decision:** Unified interrupt path. Two trigger sources feed the same exit logic:

1. **Timeout** (`TimeoutConfig`) — enforced via `asyncio.wait_for()`. This is the first concrete interrupter.
2. **External callable** (`interrupt_checker`) — polled at the start of each step. The hook for all future interrupters (budget limits, priority overrides, etc.).

**`interrupt_checker` design:**

```python
platform = ExecutionPlatform(
    event_bus=bus,
    interrupt_checker=lambda: my_flag.is_set()  # False or InterruptSignal → interrupt
)
```

`interrupt_checker: Callable[[], bool | InterruptSignal | None]` is optional on `ExecutionPlatform.__init__`.

**Internal `_check_interrupt()` method:**
- Called at the start of every `__call__` invocation and at the top of every loop iteration in both runners.
- If no checker is set, returns immediately.
- Calls the checker; returns normally on `True` or `None`.
- Raises `InterruptError(signal)` on `False` or an `InterruptSignal` instance.

**Timeout enforcement:**
- `each_execution_timeout`: `asyncio.wait_for(self.__call__(exec), timeout=each_execution_timeout)` inside the runner loop. On `asyncio.TimeoutError`, construct `InterruptSignal(reason=InterruptReason.TIMEOUT)` and route through the same exit path as `_check_interrupt()`.
- `total_timeout`: `asyncio.wait_for(inner_run(), timeout=total_timeout)` wrapping the entire body of `run()`. Same conversion on `asyncio.TimeoutError`.

**Shared exit path** (both timeout and checker fire the same steps):
1. Catch interrupt condition.
2. Publish `InterruptEvent(signal=..., state_id=...)` to `EventBus`.
3. Cancel any in-flight tasks (parallel only).
4. Return/mark affected results as `ok=False`, `error_category="interrupt"`.

**EventBus role:** Notification only — the bus receives `InterruptEvent` so observers are informed, but it is never the trigger source.

**Rationale:** A single exit path means interrupt handling is tested once. Future interrupters (budget, priority) are wired by composing or replacing `interrupt_checker` — no changes to core runner logic.

---

### D-08 — Runner Class Location ✓

**Decision:** Create `execution_runners.py` for `SequenceRunner` and `ParallelRunner`; import them into `execution.py`. May migrate to separate `sequence.py` / `parallel.py` modules as complexity grows.

---

### S-01 — Populate `ResultMetadata` in `__call__` ✓

**Decision:** Populate all four fields (`duration_ms`, `attempt`, `started_at`, `completed_at`) inside `ExecutionPlatform.__call__` as part of this work.

---

### S-02 — Fix Unhandled Exceptions in `__call__` ✓

**Decision:** Wrap the handler call in `try/except`; on exception emit `ExecutionEvent(status=FAILED)` and return `ExecutionResult(ok=False)` with populated error fields. The context managers depend on this — exceptions must not escape `__call__` unhandled.

---

### S-03 — Sequence Input Passthrough When `outputModel` is Absent ✓

**Decision:** If step N produces `value=None` (valid when `outputModel` is `None`), do not overwrite step N+1's `inputModel`; leave it unchanged.

**Rationale:** A `None` output with a declared `outputModel` would already have failed validation; if `outputModel` is `None`, a `None` value is intentional and the next step's own input should be preserved.

---

### D-09 — Dynamic Injection of Executions During a Sequence Run ✓

**Decision:** `on_step_complete` callback on `SequenceRunner`.

```python
async with platform.sequence(retry_config, timeout_config) as seq:
    seq.on_step_complete = lambda idx, result: [next_exec] if result.ok else None
    seq.add(initial_execution)
    results = await seq.run()
```

After each step completes, the runner calls `on_step_complete(step_index, result)`. If it returns a non-empty list, those executions are inserted immediately after the current position before the next step starts. The callback may be sync or async (detected via `asyncio.iscoroutinefunction`).

**Rationale:** Consistent with the pre/postcondition callback style on `Execution`. No concurrency hazards. Trivially testable.

---

### S-04 — Enriched Error Information in `ExecutionResult` ✓

**Decision:** Add `error_details: dict[str, Any] | None` to `ExecutionResult` — a serialisable snapshot populated on failure:

```python
error_details = {
    "type": "TransientError",          # exception class name
    "message": "Connection reset",      # str(exception)
    "retryable": True,                  # CognitivError.retryable
    "category": "transient",            # ErrorCategory value
    "attempt": 3,                       # which attempt failed
}
```

**Rationale:** Structured and JSON-safe; covers all caller branching needs without coupling to live exception objects.

---

## 9. Out of Scope (This Spec)

- **DAG-based execution**: Fan-out/fan-in beyond flat parallel lives at a higher orchestration layer that uses `ExecutionPlatform` as a primitive.
- **Persistent checkpointing / resumption**: Checkpoints and context management are deferred to a future spec.
- **Per-step retry policies**: Policy control lives above this layer; `RetryConfig` applies uniformly to the whole sequence or to individual parallel tasks.
- **Priority queuing for parallel tasks**: Deferred.

---

## 10. Acceptance Criteria

**Models & config:**
- [ ] `RetryConfig`, `TimeoutConfig`, `ParallelConfig` are importable from `rh_cognitv_lite.execution_platform`.
- [ ] `ExecutionResult` carries `error_details: dict[str, Any] | None`.

**`ExecutionPlatform.__call__` hardening:**
- [ ] Supports sync and async handlers (detected via `asyncio.iscoroutinefunction`).
- [ ] Catches all handler exceptions; emits `ExecutionEvent(status=FAILED)`; returns `ExecutionResult(ok=False)` with `error_details` and `metadata` fully populated.
- [ ] Populates all `ResultMetadata` fields on every result (success and failure).
- [ ] Calls `_check_interrupt()` at entry; on interrupt publishes `InterruptEvent` and returns `ExecutionResult(ok=False, error_category="interrupt")`.

**Interrupt mechanism:**
- [ ] `ExecutionPlatform` accepts optional `interrupt_checker: Callable[[], bool | InterruptSignal | None]`.
- [ ] `_check_interrupt()` raises `InterruptError` for `False` / `InterruptSignal`; no-ops on `True` / `None`.
- [ ] `asyncio.TimeoutError` from `each_execution_timeout` and `total_timeout` is converted to `InterruptSignal(reason=TIMEOUT)` and routed through the same exit path.
- [ ] All interrupts publish `InterruptEvent` to `EventBus`.

**Sequence:**
- [ ] `ExecutionPlatform.sequence(retry_config, timeout_config)` returns an async context manager yielding `SequenceRunner`.
- [ ] Steps run in insertion order; output→input chaining with `isinstance` guard.
- [ ] If step N `value` is `None`, step N+1's `inputModel` is not overwritten.
- [ ] On transient failure, full sequence retried from step 1 up to `max_attempts`.
- [ ] `on_step_complete` callback inserts returned executions after the current position.
- [ ] `ExecutionEvent`s emitted: `sequence.started`, `sequence.completed`, `sequence.failed`.

**Parallel:**
- [ ] `ExecutionPlatform.parallel(parallel_config, retry_config, timeout_config)` returns an async context manager yielding `ParallelRunner`.
- [ ] Concurrency bounded by `asyncio.Semaphore(max_concurrency)`.
- [ ] Results in insertion order.
- [ ] `fail_fast`: first failure cancels all in-flight tasks immediately.
- [ ] `fail_slow`: all tasks run to completion; only failed tasks retried.
- [ ] `ExecutionEvent`s emitted: `parallel.started`, `parallel.completed`, `parallel.failed`.

**General:**
- [ ] `add()` after `run()` raises `RuntimeError`.
- [ ] All `ExecutionResult` objects have `metadata` fully populated.

---

## 11. Implementation Phases

### Phase 1 — `__call__` Hardening

**Files touched:** `models.py`, `execution.py`

**Tasks:**
1. Add `error_details: dict[str, Any] | None = None` to `ExecutionResult` in `models.py`.
2. Add `interrupt_checker: Callable[[], bool | InterruptSignal | None] | None = None` param to `ExecutionPlatform.__init__`.
3. Implement `_check_interrupt()` method.
4. Rewrite `ExecutionPlatform.__call__`:
   - Call `_check_interrupt()` at entry.
   - Record `started_at` before handler call.
   - Detect async handler via `asyncio.iscoroutinefunction`; await or call accordingly.
   - Wrap handler in `try/except`; on exception emit `FAILED` event and return `ExecutionResult(ok=False)` with `error_details`.
   - Populate all `ResultMetadata` fields on every exit path.

**Unit tests — `tests/execution_platform/test_execution_call.py`:**

```
test_sync_handler_called_with_input
    # sync handler receives inputModel; result.ok is True; value matches

test_async_handler_called_with_input
    # async handler awaited; result.ok is True; value matches

test_metadata_populated_on_success
    # result.metadata: duration_ms > 0, attempt == 1, started_at and completed_at are ISO strings

test_metadata_populated_on_failure
    # handler raises; result.metadata still has started_at, completed_at, attempt

test_handler_exception_returns_ok_false
    # handler raises RuntimeError; result.ok is False; result.error_details["type"] == "RuntimeError"

test_handler_exception_emits_failed_event
    # handler raises; EventBus receives ExecutionEvent(status=FAILED)

test_error_details_fields_present
    # error_details has keys: type, message, retryable, category, attempt

test_precondition_failure_returns_ok_false
    # precondition returns False; result.ok is False; handler never called

test_postcondition_failure_returns_ok_false
    # postcondition returns False; result.ok is False; value is set

test_interrupt_checker_false_stops_execution
    # interrupt_checker returns False; _check_interrupt raises; result.ok is False; error_category == "interrupt"

test_interrupt_checker_interrupt_signal_stops_execution
    # interrupt_checker returns InterruptSignal(reason=USER_CANCELLED); same outcome

test_interrupt_checker_true_allows_execution
    # interrupt_checker returns True; execution proceeds normally

test_interrupt_checker_none_allows_execution
    # interrupt_checker returns None; execution proceeds normally

test_interrupt_emits_interrupt_event_on_bus
    # interrupt_checker fires; EventBus receives InterruptEvent

test_no_interrupt_checker_runs_normally
    # platform constructed without interrupt_checker; no errors
```

---

### Phase 2 — Config Models

**Files touched:** `models.py`, `__init__.py`

**Tasks:**
1. Add `RetryConfig`, `TimeoutConfig`, `ParallelConfig` to `models.py`.
2. Export all three from the package `__init__.py`.

**Unit tests — `tests/execution_platform/test_configs.py`:**

```
test_retry_config_defaults
    # max_attempts=3, base_delay=0.1, max_delay=30.0, multiplier=2.0

test_retry_config_backoff_formula
    # validate min(base_delay * multiplier^(attempt-1), max_delay) for attempts 1..5

test_timeout_config_defaults
    # each_execution_timeout=60.0, total_timeout=300.0

test_parallel_config_defaults
    # max_concurrency=5, error_strategy="fail_slow"

test_parallel_config_invalid_error_strategy
    # error_strategy="unknown" raises ValidationError

test_configs_importable_from_package
    # from rh_cognitv_lite.execution_platform import RetryConfig, TimeoutConfig, ParallelConfig
```

---

### Phase 3 — `SequenceRunner`

**Files touched:** `execution_runners.py` (new), `execution.py`

**Tasks:**
1. Create `execution_runners.py` with `SequenceRunner`.
2. Add `sequence(retry_config, timeout_config)` context manager to `ExecutionPlatform`.
3. Implement step loop: insertion-order execution, output→input chaining with `isinstance` guard, `None`-output passthrough.
4. Implement retry: on `TransientError` result, reset results list and restart from step 0; sleep with back-off; count attempt against `max_attempts`.
5. Implement `each_execution_timeout`: wrap each `__call__` with `asyncio.wait_for()`; convert `TimeoutError` to `InterruptSignal(reason=TIMEOUT)` result.
6. Implement `total_timeout`: wrap the inner loop body with `asyncio.wait_for()`; same conversion.
7. Call `_check_interrupt()` at the top of each loop iteration.
8. Implement `on_step_complete` callback; insert returned executions after current index.
9. Emit `sequence.started`, `sequence.completed`/`sequence.failed` events.

**Unit tests — `tests/execution_platform/test_sequence_runner.py`:**

```
test_single_step_happy_path
    # one execution; result list has one ok=True entry

test_multi_step_happy_path
    # three executions run in order; all ok=True

test_output_chaining
    # step 1 output value injected as step 2 inputModel; step 2 handler receives it

test_output_chaining_type_mismatch
    # step 1 output type != step 2 inputModel type; result ok=False with clear error_details

test_none_output_does_not_overwrite_next_input
    # step 1 has no outputModel (value=None); step 2 inputModel unchanged

test_failure_stops_sequence
    # step 2 of 3 fails permanently; step 3 never called; results list has 2 entries

test_transient_failure_triggers_full_retry
    # step 2 raises TransientError once; full sequence restarted; second attempt succeeds

test_retry_exhausted_returns_ok_false
    # step 2 always raises TransientError; after max_attempts, result ok=False

test_retry_backoff_delays_applied
    # patch asyncio.sleep; verify sleep called with correct back-off values

test_permanent_failure_not_retried
    # handler raises PermanentError; run ends immediately without retry

test_each_execution_timeout_fires
    # handler sleeps longer than each_execution_timeout; result ok=False, error_category="interrupt", reason=TIMEOUT

test_total_timeout_fires
    # total of steps exceeds total_timeout; run aborts; partial results returned

test_interrupt_checker_stops_before_step
    # interrupt_checker returns False before step 2; step 2 never starts

test_on_step_complete_injects_execution
    # callback returns [new_exec] after step 1; new_exec runs as step 2

test_on_step_complete_none_does_not_inject
    # callback returns None; execution list unchanged

test_add_after_run_raises
    # call seq.add() after seq.run(); RuntimeError raised

test_sequence_started_event_emitted
    # EventBus receives ExecutionEvent(kind="sequence.started") before first step

test_sequence_completed_event_emitted
    # all steps succeed; EventBus receives ExecutionEvent(kind="sequence.completed")

test_sequence_failed_event_emitted
    # step fails; EventBus receives ExecutionEvent(kind="sequence.failed")

test_results_in_insertion_order
    # three steps; results[0], [1], [2] correspond to execution 0, 1, 2

test_empty_sequence_returns_empty_list
    # no executions added; run() returns []
```

---

### Phase 4 — `ParallelRunner`

**Files touched:** `execution_runners.py`, `execution.py`

**Tasks:**
1. Add `ParallelRunner` to `execution_runners.py`.
2. Add `parallel(parallel_config, retry_config, timeout_config)` context manager to `ExecutionPlatform`.
3. Implement `asyncio.Semaphore(max_concurrency)` bounded task dispatch; preserve insertion-order results via index tracking.
4. Implement `fail_fast`: register a shared `asyncio.Event`; on first failure set it; other tasks check it at semaphore acquire and cancel via `asyncio.Task.cancel()`.
5. Implement `fail_slow`: use `asyncio.gather(return_exceptions=True)`; collect all results; retry only failed tasks.
6. Implement per-task `each_execution_timeout` via `asyncio.wait_for()`.
7. Implement `total_timeout` wrapping the whole `run()` body.
8. Call `_check_interrupt()` before each task is dispatched.
9. Emit `parallel.started`, `parallel.completed`/`parallel.failed` events.

**Unit tests — `tests/execution_platform/test_parallel_runner.py`:**

```
test_single_task_happy_path
    # one execution; result list has one ok=True entry

test_multi_task_all_succeed
    # five executions; all ok=True; results in insertion order

test_results_in_insertion_order
    # tasks complete in reverse order (via sleep mocking); results still match insertion order

test_max_concurrency_respected
    # max_concurrency=2, three tasks; assert no more than 2 run simultaneously (semaphore count check)

test_fail_slow_collects_all_results
    # task 2 of 4 fails; tasks 1, 3, 4 still complete; results list has 4 entries

test_fail_slow_failed_tasks_ok_false
    # same scenario; results[1].ok is False

test_fail_slow_retry_only_failed
    # task 2 fails once (TransientError); on retry only task 2 re-runs; tasks 1,3,4 not re-called

test_fail_fast_cancels_in_flight
    # task 1 fails; tasks 2 and 3 (in-flight) are cancelled; results[1], [2] ok=False, error_category="interrupt"

test_fail_fast_retry_restarts_full_batch
    # task 1 fails (TransientError); fail_fast mode; retry runs all tasks from scratch

test_fail_fast_is_not_default
    # ParallelConfig() has error_strategy="fail_slow" by default

test_each_execution_timeout_fires
    # one task sleeps longer than each_execution_timeout; that task ok=False, reason=TIMEOUT; others unaffected (fail_slow)

test_total_timeout_fires
    # all tasks together exceed total_timeout; run aborts; partial results ok=False for unfinished tasks

test_interrupt_checker_stops_dispatch
    # interrupt_checker returns False before task 3 is dispatched; task 3 never starts

test_permanent_failure_not_retried
    # task raises PermanentError; no retry; result ok=False immediately

test_retry_exhausted_returns_ok_false
    # task always raises TransientError; after max_attempts, result ok=False

test_add_after_run_raises
    # call par.add() after par.run(); RuntimeError raised

test_parallel_started_event_emitted
    # EventBus receives ExecutionEvent(kind="parallel.started") before dispatch

test_parallel_completed_event_emitted
    # all tasks succeed; EventBus receives ExecutionEvent(kind="parallel.completed")

test_parallel_failed_event_emitted
    # a task fails; EventBus receives ExecutionEvent(kind="parallel.failed")

test_empty_parallel_returns_empty_list
    # no executions added; run() returns []
```

---

### Phase 5 — Packaging & Export

**Files touched:** `__init__.py`, `execution_runners.py`

**Tasks:**
1. Export `SequenceRunner`, `ParallelRunner`, `RetryConfig`, `TimeoutConfig`, `ParallelConfig` from `rh_cognitv_lite.execution_platform.__init__`.
2. Verify no circular imports.
3. Run full test suite; fix any integration issues between phases.

**Tests:** No new test file. Run all phases together and confirm 0 failures.

