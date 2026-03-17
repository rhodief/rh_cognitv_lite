"""
Protocol definitions (ABCs) for the Execution Platform.

These are the contracts that upper layers depend on.
All concrete implementations live in their own modules.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from .models import (
    BudgetSnapshot,
    EventStatus,
)
from .types import ID, Timestamp

T = TypeVar("T")

# ──────────────────────────────────────────────
# EventBus Protocol
# ──────────────────────────────────────────────


class EventBusProtocol(ABC):
    """Hybrid sync middleware + async subscriber event bus."""

    @abstractmethod
    def use(self, middleware: MiddlewareProtocol) -> None:
        """Register a synchronous middleware in the pipeline."""
        ...

    @abstractmethod
    def on(self, event_type: type, handler: Any) -> None:
        """Register a synchronous handler for an event type."""
        ...

    @abstractmethod
    def on_async(self, event_type: type, handler: Any) -> None:
        """Register an async subscriber for an event type."""
        ...

    @abstractmethod
    async def emit(self, event: Any) -> None:
        """Emit an event: run sync middleware, then fan out to async subscribers."""
        ...

    @abstractmethod
    async def wait_for(
        self, event_type: type, *, filter: Any | None = None, timeout: float | None = None
    ) -> Any:
        """Block until an event of the given type (matching optional filter) is emitted."""
        ...


class MiddlewareProtocol(ABC):
    """Synchronous middleware that runs in the EventBus pipeline."""

    @abstractmethod
    def handle(self, event: Any, next_fn: Any) -> Any:
        """Process the event, optionally calling next_fn to continue the chain."""
        ...
        
        
# ──────────────────────────────────────────────
# Policy Protocols
# ──────────────────────────────────────────────


class PolicyProtocol(ABC):
    """A single policy in the middleware chain."""

    @abstractmethod
    async def before_execute(self, event: Any, data: Any, configs: Any) -> None:
        """Hook before handler execution. May raise to abort."""
        ...

    @abstractmethod
    async def after_execute(
        self, event: Any, result: Any, configs: Any
    ) -> None:
        """Hook after handler execution."""
        ...

    @abstractmethod
    async def on_error(self, event: Any, error: Exception, configs: Any) -> None:
        """Hook when handler raises an exception."""
        ...


class PolicyChainProtocol(ABC):
    """Composable chain of policies wrapping handler execution."""

    #@abstractmethod
    #async def __call__(
    #    self,
    #    handler: EventHandlerProtocol[Any],
    #    event: Any,
    #    data: Any,
    #    configs: Any,
    #) -> ExecutionResult[Any]:
    #    """Run the handler wrapped by all policies in the chain."""
    #    ...


# ──────────────────────────────────────────────
# Budget Tracker Protocol
# ──────────────────────────────────────────────


class BudgetTrackerProtocol(ABC):
    """First-class standalone resource for budget management."""

    @abstractmethod
    def can_proceed(self) -> bool:
        """Check if there is remaining budget to continue."""
        ...

    @abstractmethod
    def consume(self, *, tokens: int = 0, calls: int = 0) -> None:
        """Record consumption of budget resources."""
        ...

    @abstractmethod
    def remaining(self) -> BudgetSnapshot:
        """Get a snapshot of remaining budget."""
        ...

    @abstractmethod
    def is_exceeded(self) -> bool:
        """Check if any budget dimension is exceeded."""
        ...

