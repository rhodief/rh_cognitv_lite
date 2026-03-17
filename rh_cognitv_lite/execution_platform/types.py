"""
Foundation types for the Execution Platform.

ID (ULID), Timestamp (ISO-8601), Ext (forward-compat bag), and type aliases.
"""

from __future__ import annotations

import os
import struct
import time
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field, PrivateAttr
import ulid
# ──────────────────────────────────────────────
# Primitive Type Aliases
# ──────────────────────────────────────────────

# Stable ULID string — e.g. "01HXYZ3K..."
ID = str

# ISO-8601 timestamp string — serializes cleanly to JSON
Timestamp = str

# Forward-compat escape hatch — unknown fields live here until promoted
Ext = dict[str, Any]


# ──────────────────────────────────────────────
# ULID Generation
# ──────────────────────────────────────────────


def generate_ulid() -> ID:
    return str(ulid.new())


# ──────────────────────────────────────────────
# Timestamp Helpers
# ──────────────────────────────────────────────


def now_timestamp() -> Timestamp:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(ts: Timestamp) -> datetime:
    """Parse an ISO-8601 timestamp string into a datetime."""
    return datetime.fromisoformat(ts)


# ──────────────────────────────────────────────
# EntryRef — Typed Lazy Reference (DD-L3-08)
# ──────────────────────────────────────────────

T = TypeVar("T")


class EntryRef(BaseModel, Generic[T]):
    """Typed lazy reference to a context store entry.

    Carries type information and resolves lazily via a ContextStore.
    V1: typed lazy ref. V2 evolution: add snapshot_version for time-travel.

    Attributes:
        id: Stable ULID of the referenced entry.
        entry_type: The expected type of the resolved entry.
    """

    id: ID
    entry_type: type[T]
    _resolved: T | None = PrivateAttr(default=None)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_resolved(self) -> bool:
        """Whether the reference has been resolved."""
        return self._resolved is not None

    @property
    def value(self) -> T | None:
        """The resolved value, or None if not yet resolved."""
        return self._resolved

    async def resolve(self, store: Any) -> T:
        """Resolve the reference via a ContextStore.

        Args:
            store: A ContextStoreProtocol instance — typed as Any to avoid
                   circular imports (types.py cannot import protocols.py).

        Returns:
            The resolved entry, cast to the expected type T.

        Raises:
            LookupError: If the entry is not found in the store.
            TypeError: If the resolved entry is not of the expected type.
        """
        if self._resolved is not None:
            return self._resolved

        entry = await store.get(self.id)
        if entry is None:
            raise LookupError(f"Entry not found: {self.id}")
        if not isinstance(entry, self.entry_type):
            raise TypeError(
                f"Expected {self.entry_type.__name__}, got {type(entry).__name__}"
            )
        self._resolved = entry
        return entry
