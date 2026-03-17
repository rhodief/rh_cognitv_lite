"""
EventBus — Hybrid sync middleware pipeline + async subscriber fan-out.

DD-L3-01: Sync middleware runs in order (deterministic, required for replay).
Async subscribers receive events in real-time (fire-and-forget).

OQ-L3-01: Type-based dispatch only (V1).
OQ-L3-05: wait_for() for escalation round-trip.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, Callable, Union

from pydantic import BaseModel, Field

from rh_cognitv_lite.execution_platform.events import ExecutionEvent


class EventBus(BaseModel):
    subscribers: list[Callable] = Field(default_factory=list)
    events: list[Any] = Field(default_factory=list)  # ExecutionEvent at runtime
    queue: asyncio.Queue = Field(default_factory=asyncio.Queue)

    model_config = {"arbitrary_types_allowed": True}

    def subscribe(self, handler: Callable):
        self.subscribers.append(handler)

    async def publish(self, event: Union[ExecutionEvent, Any]):  # Accept ExecutionEvent or InterruptEvent
        self.events.append(event)

        for handler in self.subscribers:
            model_copy_fn = getattr(event, "model_copy", None)
            event_copy = (
                model_copy_fn()
                if model_copy_fn is not None
                else event
            )

            result = handler(event_copy)
            if asyncio.iscoroutine(result):
                await result
        
        # Yield control to allow other tasks (like stream generators) to process the event
        await asyncio.sleep(0)

    async def stream(self) -> AsyncGenerator[Union['ExecutionEvent', Any], None]:
        """
        Stream events from the queue.
        
        This generator yields execution events as they are published. It automatically
        terminates when an InterruptEvent is received, allowing for graceful shutdown
        of streaming endpoints (SSE, WebSocket, etc.).
        
        Yields:
            ExecutionEvent or InterruptEvent: Events from the queue
        
        Raises:
            asyncio.CancelledError: If the stream task is cancelled
        
        Example:
            ```python
            # In streaming API endpoint
            async def stream_events():
                async for event in state.event_bus.stream():
                    if isinstance(event, InterruptEvent):
                        # Interrupt received, stream will terminate
                        break
                    yield format_event(event)
            ```
        """
        from rh_cognitv_lite.execution_platform.events import InterruptEvent
        
        try:
            while True:
                event = await self.queue.get()
                
                # Check for interrupt event - terminate stream
                if isinstance(event, InterruptEvent):
                    yield event  # Yield the interrupt event so handlers can process it
                    break
                
                yield event
        except asyncio.CancelledError:
            raise

