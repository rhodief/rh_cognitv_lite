from __future__ import annotations

from .capabilities import BaseCapability


class CapabilityRegistry:
    """Standalone registry for capabilities (DD-16, Option B).

    Owns registration, lookup, listing, and validation.
    Injected into the orchestrator.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, BaseCapability] = {}

    # ── Registration ──────────────────────────────────────────────────

    def register(self, capability: BaseCapability) -> None:
        """Register a capability.

        Raises ``ValueError`` if a capability with the same ``id``
        is already registered.
        """
        if capability.id in self._capabilities:
            raise ValueError(
                f"Capability '{capability.id}' already registered"
            )
        self._capabilities[capability.id] = capability

    def unregister(self, capability_id: str) -> None:
        """Remove a capability by *capability_id*.

        Raises ``KeyError`` if not found.
        """
        if capability_id not in self._capabilities:
            raise KeyError(f"Capability '{capability_id}' not found")
        del self._capabilities[capability_id]

    # ── Lookup ────────────────────────────────────────────────────────

    def get(self, capability_id: str) -> BaseCapability:
        """Return the capability for *capability_id*.

        Raises ``KeyError`` if not found.
        """
        if capability_id not in self._capabilities:
            raise KeyError(f"Capability '{capability_id}' not found")
        return self._capabilities[capability_id]

    def has(self, capability_id: str) -> bool:
        """Return ``True`` if *capability_id* is registered."""
        return capability_id in self._capabilities

    # ── Listing ───────────────────────────────────────────────────────

    def list_all(self) -> list[BaseCapability]:
        """Return all registered capabilities."""
        return list(self._capabilities.values())

    def list_by_type(self, cap_type: type) -> list[BaseCapability]:
        """Return all capabilities that are instances of *cap_type*."""
        return [
            c for c in self._capabilities.values() if isinstance(c, cap_type)
        ]

    @property
    def count(self) -> int:
        """Number of registered capabilities."""
        return len(self._capabilities)
