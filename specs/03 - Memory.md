# Spec 03 — Memory System

## Status: Ready for Development

---

## 1. Overview

The Memory system provides structured, multi-scope storage and retrieval for LLM-agent orchestration. It allows agents and skills to persist, recall, and reason over information across time — from the current turn all the way to long-term identity and episodic history.

The core abstraction is a generic `MemoryStore` protocol (no implementation). Concrete backends are swapped in via dependency inversion, enabling any number of storage targets (in-memory, file, database, S3, hybrid, etc.) without touching agent or skill logic.

---

## 2. Memory Taxonomy

```
Memory
├── Persistent                        # Survives across sessions
│   ├── Agent-Scoped
│   │   ├── AgentIdentity             # Name, role, persona
│   │   └── AgentPreferences          # Defaults, tone, behavioral settings
│   └── Skill-Scoped
│       └── SkillMemory               # Per-skill preferences, procedures, beliefs
│                                     # Injected via MemoryPolicy (opt-in per Execution)
│
├── Retrieved                         # On-demand recall, fetched like a tool call
│   └── Episodes                      # Relevant past events
│       └── Scored by recency decay + tag overlap; top-K returned
│           # TODO: Records — deferred to Artifact module
│
└── Session-Scoped                    # Lives for the duration of one session
    └── RecentExchanges               # Last N turns or a rolling summary
        └── Working memory is ephemeral; assembled+injected by the orchestrator only
```

---

## 3. Module Layout

```
rh_cognitv_lite/memory/
    __init__.py
    __protocols.py          # MemoryStore ABC — no implementation
    models.py               # All memory entity models (Pydantic)
    adapters/
        __init__.py
        memory_adapter.py   # InMemoryAdapter — dict-backed
        file_adapter.py     # FileAdapter — JSON on disk
    episode_triage.py       # EpisodeTriage — rule-based scoring
    session.py              # SessionMemoryManager — RecentExchanges lifecycle
    py.typed
    README.md
```

---

## 4. `MemoryStore` Protocol

Defined in `__protocols.py`. Follows the same ABC pattern as `EventBusProtocol` and `PolicyProtocol` in the execution platform. All async. No implementation here.

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from .models import MemoryEntry


class MemoryStore(ABC):
    """Abstract contract for all memory backends."""

    @abstractmethod
    async def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry. Overwrites if key already exists."""
        ...

    @abstractmethod
    async def get(self, key: str) -> MemoryEntry | None:
        """Fetch a single entry by its exact key. Returns None if not found."""
        ...

    @abstractmethod
    async def search(self, tags: list[str]) -> list[MemoryEntry]:
        """Return all entries whose tag set intersects with the given tags.
        Results ordered by updated_at descending."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove an entry. No-op if the key does not exist."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Remove all entries. Used for session teardown and testing."""
        ...
```

**Access patterns:**
- **By key** — `await store.get("agent_identity")` — direct named fetch
- **By tags** — `await store.search(["preference", "tone"])` — category recall

**Not in scope for this protocol:** similarity/vector search. That is an extension for a future `SemanticMemoryStore(MemoryStore)` protocol, introduced when the Artifact/Records module is built.

---

## 5. Memory Entities

All entities are **Pydantic `BaseModel`** classes, following the same pattern as the rest of the platform. They live in `models.py`. Imports re-use `ID`, `Timestamp`, `generate_ulid`, and `now_timestamp` from the execution platform types.

---

### 5.1 Storage Envelope — `MemoryEntry`

The universal container persisted by every `MemoryStore` adapter. The `value` field holds any serializable Pydantic model (stored as `dict` after `.model_dump()`).

```python
class MemoryEntry(BaseModel):
    key: str                        # Unique key within a store (namespaced by caller)
    tags: list[str] = []           # Searchable category labels
    value: dict[str, Any]          # Serialized payload (model_dump of the actual entity)
    updated_at: Timestamp = Field(default_factory=now_timestamp)
```

**Key conventions:**

| Memory type | Key pattern | Example |
|---|---|---|
| Agent identity | `agent_identity` | `agent_identity` |
| Agent preferences | `agent_preferences` | `agent_preferences` |
| Skill memory | `skill_memory:{skill_id}` | `skill_memory:summarizer` |
| Episode | `episode:{ulid}` | `episode:01JRK...` |
| Recent exchanges | `recent_exchanges` | `recent_exchanges` |

---

### 5.2 Persistent Memory — Agent-Scoped

#### `AgentIdentity`

Long-lived agent persona. Loaded once at agent startup and injected into every skill context.

```python
class AgentIdentity(BaseModel):
    agent_id: ID = Field(default_factory=generate_ulid)
    name: str                           # Display name
    role: str                           # e.g. "Research Assistant"
    persona: str                        # Natural language description of the agent's character
    created_at: Timestamp = Field(default_factory=now_timestamp)
    updated_at: Timestamp = Field(default_factory=now_timestamp)
```

**Stored as:** `MemoryEntry(key="agent_identity", tags=["agent", "identity"], value=AgentIdentity(...).model_dump())`

---

#### `AgentPreferences`

Behavioral defaults that apply across all skill executions for this agent.

```python
class AgentPreferences(BaseModel):
    language: str = "en"               # Output language
    verbosity: Literal["concise", "standard", "detailed"] = "standard"
    tone: Literal["formal", "neutral", "casual"] = "neutral"
    max_response_tokens: int | None = None
    custom: dict[str, Any] = {}        # Open-ended extension bag
    updated_at: Timestamp = Field(default_factory=now_timestamp)
```

**Stored as:** `MemoryEntry(key="agent_preferences", tags=["agent", "preference"], value=...)`

---

### 5.3 Persistent Memory — Skill-Scoped

#### `SkillMemory`

Per-skill persistent state. Injected at execution time via `MemoryPolicy` (opt-in). Designed as an open container so each skill defines its own `beliefs` structure.

```python
class SkillMemory(BaseModel):
    skill_id: str                       # Matches the Skill's ID field
    procedures: list[str] = []         # Step-by-step instructions the skill should follow
    beliefs: dict[str, Any] = {}       # Skill-specific key/value knowledge store
    preferences: dict[str, Any] = {}   # Skill-specific behavioral overrides
    updated_at: Timestamp = Field(default_factory=now_timestamp)
```

**Stored as:** `MemoryEntry(key=f"skill_memory:{skill_id}", tags=["skill", "memory", skill_id], value=...)`

**Injection:** A `MemoryPolicy` wrapping an `Execution` loads this entry in `before_execute` and makes it available to the handler via the execution context. Not all skills receive this — the policy is attached explicitly per `Execution`.

---

### 5.4 Retrieved Memory — Episodes

#### `Episode`

A discrete past event worth remembering. Saved by the orchestrator after significant interactions.

```python
class Episode(BaseModel):
    id: ID = Field(default_factory=generate_ulid)
    summary: str                        # Human-readable description of what happened
    tags: list[str] = []               # Thematic labels used for retrieval scoring
    outcome: Literal["success", "failure", "partial", "unknown"] = "unknown"
    occurred_at: Timestamp = Field(default_factory=now_timestamp)
    embedding: list[float] | None = None  # Reserved — vector retrieval not yet active
    ext: dict[str, Any] = {}           # Forward-compat bag for future fields
```

**Stored as:** `MemoryEntry(key=f"episode:{episode.id}", tags=["episode"] + episode.tags, value=...)`

**Notes:**
- `tags` are the primary retrieval signal for the current triage strategy (see §6).
- `embedding` is a schema placeholder. It is always `None` until a vector strategy is wired.
- `outcome` allows filtering out unsuccessful episodes or weighting them differently.

---

#### `TriageConfig`

Configuration for `EpisodeTriage`. Passed at triage time, not stored.

```python
class TriageConfig(BaseModel):
    query_tags: list[str]               # Tags representing the current context/goal
    top_k: int = 5                      # Maximum number of episodes to return
    recency_weight: float = 0.6         # Weight applied to the recency decay term
    tag_weight: float = 0.4             # Weight applied to the tag overlap term
    decay_lambda: float = 0.01          # Controls how fast recency decays (per hour)
```

**Scoring formula** applied per episode:

$$\text{score}_i = w_r \cdot e^{-\lambda \cdot \Delta t_i} + w_t \cdot \frac{|\text{tags}_i \cap \text{tags}_\text{query}|}{\max(|\text{tags}_\text{query}|,\ 1)}$$

Where $\Delta t_i$ is the age of the episode in hours at retrieval time. Top-K episodes by score are returned; ties broken by most recent `occurred_at`.

---

### 5.5 Session Memory — `RecentExchanges`

Tracks the conversation history for the current session. Stored inside a short-lived `InMemoryAdapter` (see §7). Not persisted to disk.

#### `Exchange`

A single turn in the conversation.

```python
class Exchange(BaseModel):
    id: ID = Field(default_factory=generate_ulid)
    role: Literal["user", "agent", "tool"]
    content: str                        # Raw text or serialized tool result
    occurred_at: Timestamp = Field(default_factory=now_timestamp)
```

#### `RecentExchanges`

The rolling window container.

```python
class RecentExchanges(BaseModel):
    exchanges: list[Exchange] = []
    max_turns: int = 20                 # Rolling window size; oldest are dropped when exceeded
    summary: str | None = None          # Optional condensed summary of older turns
    updated_at: Timestamp = Field(default_factory=now_timestamp)
```

**Stored as:** `MemoryEntry(key="recent_exchanges", tags=["session", "exchanges"], value=...)`

When `len(exchanges) > max_turns`: the oldest `exchange` is removed (FIFO). A future summarization mechanism may condense dropped turns into `summary` instead of discarding them.

---

## 6. `EpisodeTriage`

Implemented in `episode_triage.py`. Pure logic class — no persistence, no async.

```python
class EpisodeTriage:
    def score(self, episode: Episode, config: TriageConfig, now: datetime) -> float:
        """Compute the relevance score for a single episode."""
        ...

    def rank(
        self,
        episodes: list[Episode],
        config: TriageConfig,
        now: datetime | None = None,
    ) -> list[Episode]:
        """Return top-K episodes by score, highest first. Ties broken by occurred_at."""
        ...
```

**Algorithm:**
1. For each episode: compute $\Delta t$ in hours since `occurred_at`.
2. Compute tag overlap: `len(set(episode.tags) & set(config.query_tags))`.
3. Normalize tag overlap by `max(len(config.query_tags), 1)`.
4. Apply formula; clamp score to `[0.0, 1.0]`.
5. Sort descending by score; return first `config.top_k`.

---

## 7. Adapters

### 7.1 `InMemoryAdapter`

`adapters/memory_adapter.py`. Dict-backed. Used for: tests (all scopes), session memory (`RecentExchanges`).

```
Internal state:
    _store: dict[str, MemoryEntry]
    _tag_index: dict[str, set[str]]    # tag → set of keys

save(entry):   _store[entry.key] = entry; update _tag_index
get(key):      return _store.get(key)
search(tags):  union of keys across tags, hydrate from _store, sort by updated_at desc
delete(key):   remove from _store and _tag_index
clear():       reset both structures
```

Thread-safety: not required — this is async-only and single-loop.

---

### 7.2 `FileAdapter`

`adapters/file_adapter.py`. JSON on disk. Used for persistent memory (identity, preferences, skill memory, episodes).

**File layout:**
```
{base_dir}/
    agent_identity.json
    agent_preferences.json
    skill_memory:{skill_id}.json
    episode:{ulid}.json
    recent_exchanges.json       ← only if explicitly persisted; normally in-memory only
```

Each file is one `MemoryEntry` serialized as JSON:
```json
{
  "key": "skill_memory:summarizer",
  "tags": ["skill", "memory", "summarizer"],
  "value": { ... },
  "updated_at": "2026-03-27T10:00:00Z"
}
```

```
save(entry):   write {base_dir}/{entry.key}.json  (sanitize key for filesystem safety)
get(key):      read {base_dir}/{key}.json → MemoryEntry.model_validate(json.load(...))
search(tags):  glob all *.json; load each; filter by tag intersection; sort by updated_at desc
delete(key):   os.remove({base_dir}/{key}.json); no-op if missing
clear():       remove all *.json in base_dir
```

**Key sanitization:** replace `:` with `__` for filesystem safety (`skill_memory__summarizer.json`). The `MemoryEntry.key` field always stores the original unsanitized key.

**Async I/O:** use `aiofiles` for non-blocking reads and writes.

---

## 8. `SessionMemoryManager`

Implemented in `session.py`. Thin lifecycle wrapper for `RecentExchanges` inside a session-scoped `InMemoryAdapter`. One instance per active session.

```python
class SessionMemoryManager:
    def __init__(self, max_turns: int = 20) -> None: ...

    async def open(self) -> None:
        """Initialize the session store. Must be called before any access."""
        ...

    async def close(self) -> None:
        """Teardown: clear and discard the in-memory store."""
        ...

    async def add_exchange(self, exchange: Exchange) -> None:
        """Append a turn. Drops oldest if max_turns exceeded."""
        ...

    async def get_recent(self) -> RecentExchanges:
        """Return the current RecentExchanges snapshot."""
        ...

    async def __aenter__(self) -> SessionMemoryManager: ...
    async def __aexit__(self, *_: Any) -> None: ...
```

Used as an async context manager by orchestrators:

```python
async with SessionMemoryManager(max_turns=15) as session:
    await session.add_exchange(Exchange(role="user", content="Hello"))
    recent = await session.get_recent()
```

---

## 9. Integration Points

| Consumer | How memory is accessed |
|---|---|
| **Orchestrator (startup)** | Loads `AgentIdentity` and `AgentPreferences` from persistent store; injects into all skill contexts for the session |
| **`MemoryPolicy`** | Wraps an `Execution`; loads `SkillMemory(skill_id=...)` in `before_execute`; makes it available to the handler; cleans up in `after_execute` |
| **Orchestrator (post-turn)** | Saves new `Episode` to persistent store after a significant interaction |
| **Episode recall tool** | Agent calls `EpisodeTriage.rank(episodes, config)` to fetch relevant past context on demand |
| **`SessionMemoryManager`** | Opened by orchestrator at session start; `add_exchange()` called after each turn; closed at session end |
| **`ContextRef` namespacing** | Memory items referenced as `memory.agent_identity`, `memory.skill_memory:summarizer`, etc. |

---

## 10. Design Decisions

All decisions are closed. Rationale is preserved for context.

---

### DD-01 — `MemoryStore` Protocol Shape

**Decision: Minimal ABC; similarity as an optional future extension.**

The core protocol covers only `save`, `get`, `search` (by tags), `delete`, and `clear`. Similarity/semantic search is deferred — it will be an extended protocol (`SemanticMemoryStore`) introduced alongside the Artifact/Records module, where the LLM can be method-aware of retrieval strategies.

---

### DD-02 — File Adapter Storage Format

**Decision: JSON with one file per entry.**

Pydantic `.model_dump()` / `.model_validate()` round-trips cleanly. No extra dependencies beyond `aiofiles`. SQLite can be reconsidered when episode file counts become unwieldy.

---

### DD-03 — Episodic Memory Relevance Triage

**Decision: Rule-based scoring (recency decay + tag overlap), top-K selection.**

Zero LLM cost, deterministic, testable. The `Episode.embedding` field is a schema placeholder for future vector retrieval.

---

### DD-04 — Session Working Memory Lifecycle

**Decision: Working memory is orchestrator-managed and ephemeral; only `RecentExchanges` is stored.**

Working memory lives inside the execution context for the duration of a turn only. `ExecutionEvent` / `EventBus` remain strictly for execution observability — cognitive context is not mixed in. `RecentExchanges` is the sole session-scoped stored item.

---

### DD-05 — Records / Artifacts Boundary

**Decision: Defer Records entirely; implement only Episodes in the Retrieved tier.**

Records are out of scope for this module. The Artifact module takes full ownership of their design.

---

## 11. Implementation Phases

### Phase 1 — Protocol, Models & Adapters

| Task | Where |
|---|---|
| `MemoryStore` ABC | `memory/__protocols.py` |
| All entity models (`MemoryEntry`, `AgentIdentity`, `AgentPreferences`, `SkillMemory`, `Episode`, `TriageConfig`, `Exchange`, `RecentExchanges`) | `memory/models.py` |
| `InMemoryAdapter` | `memory/adapters/memory_adapter.py` |
| `FileAdapter` | `memory/adapters/file_adapter.py` |
| **Tests:** CRUD round-trips; tag search; file layout; adapter interchangeability via protocol | `tests/memory/` |

### Phase 2 — Episode Triage

| Task | Where |
|---|---|
| `EpisodeTriage.score()` and `.rank()` | `memory/episode_triage.py` |
| **Tests:** scoring formula; top-K selection; recency-dominant vs. tag-dominant configs; zero-episode edge case; tie-breaking by `occurred_at` | `tests/memory/test_episode_triage.py` |

### Phase 3 — `MemoryPolicy` Integration

> **Pre-requisite:** `PolicyProtocol` / `PolicyChainProtocol` declared in `execution_platform/__protocols.py` must be wired into `ExecutionPlatform` before this phase. Currently declared but not active.

| Task | Where |
|---|---|
| Activate policy chain in `ExecutionPlatform` (`before_execute` / `after_execute` / `on_error` hooks) | `execution_platform/execution.py` |
| `MemoryPolicy(skill_id, store)` implementing `PolicyProtocol` | `memory/policy.py` |
| **Tests:** policy injects correct `SkillMemory`; no-op when key absent; cross-execution isolation; policy composition | `tests/memory/test_policy.py` |

### Phase 4 — Session Memory

| Task | Where |
|---|---|
| `SessionMemoryManager` with async context manager support | `memory/session.py` |
| **Tests:** open/close lifecycle; exchange appended and retrieved; rolling window truncation; session isolation | `tests/memory/test_session.py` |

### Phase 5 — Documentation

| Task | Where |
|---|---|
| Module README (taxonomy, adapter swap guide, `MemoryPolicy` usage) | `memory/README.md` |
| Docstrings on protocol, adapters, triage, policy, session manager | inline |

### Phase 6 — Example

| Task | Where |
|---|---|
| `index_memory.py`: adapter basics → persistent memory → episode triage → `MemoryPolicy` on an `Execution` → session manager | `examples/index_memory.py` |

