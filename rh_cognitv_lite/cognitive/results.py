from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from rh_cognitv_lite.execution_platform.models import ExecutionResult

T = TypeVar("T")


# ──────────────────────────────────────────────────────────────────────
# Result detail models
# ──────────────────────────────────────────────────────────────────────


class EscalationInfo(BaseModel):
    """Details about why a capability escalated."""

    reason: str
    capability_id: str
    context: dict[str, Any] = Field(default_factory=dict)


class FailInfo(BaseModel):
    """Details about an unrecoverable capability failure."""

    reason: str
    error_type: str
    details: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────
# CognitiveResult
# ──────────────────────────────────────────────────────────────────────


class CognitiveResult(BaseModel, Generic[T]):
    """Wraps an ExecutionResult with cognitive-level semantics.

    - ``response`` — success with structured data
    - ``escalate`` — the capability cannot handle this; delegate to parent/user
    - ``fail`` — unrecoverable error
    """

    kind: str  # "response" | "escalate" | "fail"
    value: T | None = None
    escalation: EscalationInfo | None = None
    error: FailInfo | None = None
    execution_result: ExecutionResult[Any] = Field(
        default_factory=lambda: ExecutionResult(ok=False)
    )

    # ── factory helpers ────────────────────────────────────────────

    @classmethod
    def response(
        cls,
        value: T,
        execution_result: ExecutionResult[Any],
    ) -> CognitiveResult[T]:
        return cls(kind="response", value=value, execution_result=execution_result)

    @classmethod
    def escalate(
        cls,
        info: EscalationInfo,
        execution_result: ExecutionResult[Any],
    ) -> CognitiveResult[Any]:
        return cls(kind="escalate", escalation=info, execution_result=execution_result)

    @classmethod
    def fail(
        cls,
        info: FailInfo,
        execution_result: ExecutionResult[Any],
    ) -> CognitiveResult[Any]:
        return cls(kind="fail", error=info, execution_result=execution_result)
