"""
Execution events — data-only event types with kind-specific payloads.

DD-L3-05: Events are data-only. External handlers are registered in a handler
registry (Strategy pattern). Each event carries a `kind` and a typed `payload`.

OQ-L3-05: EscalationRequested / EscalationResolved for human-in-the-loop.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from .models import EventStatus
from .types import ID, Ext, Timestamp, generate_ulid, now_timestamp

# ──────────────────────────────────────────────
# ExecutionEvent
# ──────────────────────────────────────────────


class ExecutionEvent(BaseModel):
    """Data-only execution event.
    """

    id: ID = Field(default_factory=generate_ulid)
    name: str
    description: str | None = None
    kind: str
    payload: dict[str, Any]
    status: EventStatus = EventStatus.STARTED
    retried: int = 0
    created_at: Timestamp = Field(default_factory=now_timestamp)
    parent_id: ID | None = None
    group_id: str | None = None  # for correlating related events (e.g. retries)
    ext: Ext = Field(default_factory=dict)


# ──────────────────────────────────────────────
# Escalation Events (OQ-L3-05)
# ──────────────────────────────────────────────


class EscalationRequested(BaseModel):
    """Emitted when a handler needs a human decision.

    Payload includes enough context for cloud-safe recovery:
    question, options, originating event_id, and resume data.
    """

    event_id: ID
    question: str
    options: list[str] = Field(default_factory=list)
    node_id: str | None = None
    resume_data: dict[str, Any] = Field(default_factory=dict)
    created_at: Timestamp = Field(default_factory=now_timestamp)


class EscalationResolved(BaseModel):
    """Emitted when a human decision arrives for a prior escalation."""

    event_id: ID
    decision: str
    resolved_at: Timestamp = Field(default_factory=now_timestamp)
    ext: Ext = Field(default_factory=dict)


class InterruptReason(str, Enum):
    """Reason for execution interruption."""
    USER_CANCELLED = "user_cancelled"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    ERROR_THRESHOLD = "error_threshold"
    PRIORITY_OVERRIDE = "priority_override"
    SYSTEM_SHUTDOWN = "system_shutdown"
    CUSTOM = "custom"



class InterruptSignal(BaseModel):
    """Signal model for execution interruption."""
    reason: InterruptReason = Field(description="Why execution was interrupted")
    message: Optional[str] = Field(default=None, description="Human-readable message")
    triggered_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    triggered_by: Optional[str] = Field(default=None, description="Who/what triggered interrupt")
    save_checkpoint: bool = Field(default=True, description="Save state before terminating")


class InterruptEvent(BaseModel):
    """Special event published when execution is interrupted."""
    signal: InterruptSignal
    state_id: str = Field(description="ID of the ExecutionState that was interrupted")
    
    model_config = {"arbitrary_types_allowed": True}



class LogSeverity(str, Enum):
    """Severity levels for log events."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogEvent(BaseModel):
    """
    Log event that can be published to the event bus.
    
    This allows structured logging within execution flows that integrates
    with the event stream and printers.
    """
    severity: LogSeverity = Field(description="Log severity level")
    message: str = Field(description="Log message")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    address: str = Field(default="", description="Event address in execution tree")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    model_config = {"arbitrary_types_allowed": True}
