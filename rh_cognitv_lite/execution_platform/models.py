"""
Pydantic models for the Execution Platform.

BaseEntry, Memory, Artifact, and all supporting types.
ExecutionResult and kind-specific result payloads.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator

from .types import ID, Ext, Timestamp, generate_ulid, now_timestamp


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class EventStatus(str, Enum):
    STARTED = 'started'
    COMPLETED = 'completed'
    FAILED = 'failed'
    AWAITING = 'awaiting'
    ESCALATED = "escalated"  # human-in-the-loop: awaiting user decision
    RECOVERED = 'recovered'
    INTERRUPTED = 'interrupted'  # NEW: Execution was interrupted
    INTERRUPTING = 'interrupting'    # NEW: Transitional state during cancellation
    RETRYING = 'retrying'        # NEW: Event is being retried after failure
    

class InterruptReason(str, Enum):
    """Reason for execution interruption."""
    USER_CANCELLED = "user_cancelled"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    ERROR_THRESHOLD = "error_threshold"
    PRIORITY_OVERRIDE = "priority_override"
    SYSTEM_SHUTDOWN = "system_shutdown"
    CUSTOM = "custom"
    
    
class ResultMetadata(BaseModel):
    """Metadata about an execution result."""

    duration_ms: float = 0.0
    attempt: int = 1
    started_at: Timestamp | None = None
    completed_at: Timestamp | None = None



T = TypeVar("T")


class ExecutionResult(BaseModel, Generic[T]):
    """Generic result of executing an event."""

    ok: bool
    value: T | None = None
    error_message: str | None = None
    error_category: str | None = None
    error_details: dict[str, Any] | None = None
    metadata: ResultMetadata = Field(default_factory=ResultMetadata)


# ──────────────────────────────────────────────
# Retry-Aware Models (DD-12)
# ──────────────────────────────────────────────


class RetryAttemptRecord(BaseModel):
    """Record of a single failed retry attempt."""

    attempt: int
    error_message: str
    error_category: str
    error_type: str
    duration_ms: float


class RetryContext(BaseModel):
    """Injected into the handler on retry when retry_aware=True.

    Only present on attempt 2+.  First attempt always receives no context.
    """

    attempt: int                                        # current attempt (2+)
    max_attempts: int                                   # from RetryConfig
    error_message: str                                  # what went wrong on the previous attempt
    error_category: str                                 # ErrorCategory value
    error_type: str                                     # exception class name
    previous_result: ExecutionResult | None = None      # full result from the previous attempt
    history: list[RetryAttemptRecord] = Field(default_factory=list)  # all previous attempts


# ──────────────────────────────────────────────
# Budget Snapshot
# ──────────────────────────────────────────────


class BudgetSnapshot(BaseModel):
    """Point-in-time snapshot of budget remaining."""

    tokens_remaining: int
    calls_remaining: int
    time_remaining_seconds: float


# ──────────────────────────────────────────────
# Runner Configuration Models
# ──────────────────────────────────────────────


class RetryConfig(BaseModel):
    """Exponential back-off retry configuration.

    Set max_attempts=1 to disable retries.
    Only CognitivError instances with retryable=True trigger a retry.
    Back-off formula: min(base_delay * multiplier^(attempt-1), max_delay)
    """

    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 30.0
    multiplier: float = 2.0

    def delay_for(self, attempt: int) -> float:
        """Return the sleep duration before the given attempt (1-indexed)."""
        return min(self.base_delay * (self.multiplier ** (attempt - 1)), self.max_delay)


class TimeoutConfig(BaseModel):
    """Per-execution and total-run timeout configuration.

    Set to None at call site to disable all timeouts.
    """

    each_execution_timeout: float = 60.0
    total_timeout: float = 300.0


class ParallelConfig(BaseModel):
    """Configuration for parallel execution mode."""

    max_concurrency: int = 5
    error_strategy: Literal["fail_fast", "fail_slow"] = "fail_slow"

    @field_validator("error_strategy")
    @classmethod
    def _validate_error_strategy(cls, v: str) -> str:
        if v not in ("fail_fast", "fail_slow"):
            raise ValueError(f"error_strategy must be 'fail_fast' or 'fail_slow', got {v!r}")
        return v
