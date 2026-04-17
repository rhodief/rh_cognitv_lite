from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────
# ContextRef
# ──────────────────────────────────────────────────────────────────────


class ContextRef(BaseModel):
    """Typed reference to a piece of context data.

    Nodes declare which context they need via a list of ``ContextRef``s.
    The orchestrator resolves each ref at runtime using the
    ``ContextResolverRegistry``.
    """

    scope: str
    key: str


# ──────────────────────────────────────────────────────────────────────
# ScopeFrame & ContextStore (DD-13 Option B — frame stack)
# ──────────────────────────────────────────────────────────────────────


class ScopeFrame(BaseModel):
    """A single frame in the context store's scope stack."""

    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class ContextStore(BaseModel):
    """Hierarchical scoped store with a frame stack.

    The store maintains an ordered list of ``ScopeFrame``s (stack — last is
    innermost).  ``put`` writes to the topmost frame.  ``get`` walks the
    stack from top to bottom, returning the first match (inner scopes
    shadow outer).

    The orchestrator pushes frames when entering a ``ForEachNode`` iteration
    or a new cycle iteration, and pops them when done.
    """

    frames: list[ScopeFrame] = Field(default_factory=lambda: [ScopeFrame(name="root")])

    # ── Frame management ──────────────────────────────────────────────

    def push_frame(self, name: str) -> None:
        """Push a new scope frame onto the stack."""
        self.frames.append(ScopeFrame(name=name))

    def pop_frame(self) -> ScopeFrame:
        """Pop and return the topmost scope frame.

        Raises ``IndexError`` if only the root frame remains.
        """
        if len(self.frames) <= 1:
            raise IndexError("Cannot pop the root frame")
        return self.frames.pop()

    @property
    def current_frame(self) -> ScopeFrame:
        """The topmost (innermost) frame."""
        return self.frames[-1]

    @property
    def depth(self) -> int:
        """Number of frames on the stack (including root)."""
        return len(self.frames)

    # ── Read / write ──────────────────────────────────────────────────

    def put(self, key: str, value: Any) -> None:
        """Write *value* under *key* in the topmost frame."""
        self.frames[-1].data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Look up *key* walking from the topmost frame downward.

        Returns the first match (inner scope shadows outer).
        Returns *default* if the key is not found in any frame.
        """
        for frame in reversed(self.frames):
            if key in frame.data:
                return frame.data[key]
        return default

    def get_scoped(self, frame_name: str, key: str, default: Any = None) -> Any:
        """Look up *key* in a specific frame identified by *frame_name*.

        Searches from the topmost frame downward and returns the first
        frame whose name matches.  Returns *default* if not found.
        """
        for frame in reversed(self.frames):
            if frame.name == frame_name and key in frame.data:
                return frame.data[key]
        return default

    def has(self, key: str) -> bool:
        """Return ``True`` if *key* exists in any frame."""
        for frame in reversed(self.frames):
            if key in frame.data:
                return True
        return False

    def keys(self) -> list[str]:
        """All visible keys (topmost shadow wins), deduplicated."""
        seen: set[str] = set()
        result: list[str] = []
        for frame in reversed(self.frames):
            for k in frame.data:
                if k not in seen:
                    seen.add(k)
                    result.append(k)
        return result

    # ── Snapshot / restore ────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Serialize the full frame stack for persistence."""
        return {"frames": [f.model_dump() for f in self.frames]}

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Restore the frame stack from a snapshot."""
        self.frames = [ScopeFrame.model_validate(f) for f in snapshot["frames"]]


# ──────────────────────────────────────────────────────────────────────
# ContextResolverRegistry (DD-06 Option C)
# ──────────────────────────────────────────────────────────────────────


class ContextResolverProtocol(ABC):
    """A resolver knows how to fetch data for a given scope."""

    @abstractmethod
    def resolve(self, key: str, store: ContextStore) -> Any:
        """Return the resolved value for *key*, or raise ``KeyError``."""
        ...


class ContextResolverRegistry:
    """Registry of resolvers keyed by scope.

    The orchestrator registers one resolver per scope (e.g. ``"memory"``,
    ``"artifact"``, ``"skill_output"``).  At resolution time, each
    ``ContextRef`` is dispatched to the resolver matching its ``scope``.
    """

    def __init__(self) -> None:
        self._resolvers: dict[str, ContextResolverProtocol] = {}

    def register(self, scope: str, resolver: ContextResolverProtocol) -> None:
        """Register a resolver for *scope*.  Overwrites any existing resolver."""
        self._resolvers[scope] = resolver

    def has(self, scope: str) -> bool:
        """Return ``True`` if a resolver is registered for *scope*."""
        return scope in self._resolvers

    def get_resolver(self, scope: str) -> ContextResolverProtocol:
        """Return the resolver for *scope*.

        Raises ``KeyError`` if no resolver is registered.
        """
        if scope not in self._resolvers:
            raise KeyError(f"No resolver registered for scope '{scope}'")
        return self._resolvers[scope]

    def resolve(self, ref: ContextRef, store: ContextStore) -> Any:
        """Resolve a single ``ContextRef`` using the registered resolver."""
        resolver = self.get_resolver(ref.scope)
        return resolver.resolve(ref.key, store)

    def resolve_all(
        self, refs: list[ContextRef], store: ContextStore
    ) -> dict[str, Any]:
        """Resolve a list of ``ContextRef``s, returning a ``{key: value}`` dict.

        Raises ``KeyError`` if any scope lacks a registered resolver.
        """
        result: dict[str, Any] = {}
        for ref in refs:
            result[ref.key] = self.resolve(ref, store)
        return result

    @property
    def scopes(self) -> list[str]:
        """All registered scope names."""
        return list(self._resolvers.keys())
