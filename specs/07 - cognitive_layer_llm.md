# Spec 07 — Cognitive Layer: LLM Execution Nodes

## Status: Draft — Decisions Consolidated

---

## 1. Overview

The **Cognitive Layer** is the topmost layer of the `rh_cognitv_lite` architecture. It defines what an agent *can do* (capabilities) and how those capabilities map to structured LLM interactions. The lower layers — **Execution Platform** (runs things) and **Orchestrators/Graphs** (orders things) — are already built. The Cognitive Layer ties them together by producing `Execution` objects that the platform can run, arranged in `Graph` topologies that the orchestrator can walk.

This spec covers the foundational building blocks:

1. **Execution Nodes** — typed LLM interaction units (`TextNode`, `ObjectNode`, `FunctionNode`)
2. **Base Capability hierarchy** — `BaseCapability`, `BaseSkill`, `BaseTool`, `BaseWorkflow`
3. **ExecutionGraph** — the bridge that converts cognitive definitions into runnable `Graph` + `Execution` pairs
4. **Orchestrator (v1)** — the controller that owns state, walks the graph, and delegates to `ExecutionPlatform`

```
┌─────────────────────────────────────────────────────────────┐
│                     COGNITIVE LAYER                         │
│                                                             │
│  BaseCapability                                             │
│    ├── BaseSkill  (LLM + instructions)                      │
│    ├── BaseTool   (deterministic handler fn)                 │
│    └── BaseWorkflow (sub-graph of capabilities)             │
│                                                             │
│  ExecutionNodes                                             │
│    ├── TextNode     (LLM → text/stream)                     │
│    ├── ObjectNode   (LLM → structured object via tool call) │
│    └── FunctionNode (plain function execution)              │
│                                                             │
│  ExecutionGraph                                             │
│    Converts ExecutionNodes → Graph nodes + Execution map    │
│    Serializable. No execution state.                        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    ORCHESTRATOR                              │
│                                                             │
│  Orchestrator                                               │
│    Owns: State, ExecutionGraph, ExecutionPlatform            │
│    Does: walk graph, inject context, run executions,         │
│          store results, snapshot/restore                     │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                  ORCHESTRATION LAYER (exists)                │
│  Graph, GraphBuilder, GraphEngine                           │
├─────────────────────────────────────────────────────────────┤
│                 EXECUTION PLATFORM (exists)                  │
│  ExecutionPlatform, Execution, EventBus, Runners            │
├─────────────────────────────────────────────────────────────┤
│                    MEMORY (exists)                           │
│  MemoryStore, Adapters, EpisodeTriage, SessionMemory        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Execution Nodes

Execution Nodes are the atomic cognitive units. Each one declares *what* an LLM interaction (or function call) should do, *how* it should be configured, and *what shape* its output has. They carry no execution logic — they are declarative blueprints that the `ExecutionGraph` converts into `Execution` objects.

### 2.1 `BaseExecutionNode`

```python
class BaseExecutionNode(BaseModel):
    id: str                                     # unique within an ExecutionGraph
    name: str                                   # human-readable label
    description: str                            # what this node does
    input_schema: dict[str, Any] | None = None  # JSON Schema for expected input
    output_schema: dict[str, Any] | None = None # JSON Schema for expected output
    metadata: dict[str, Any] = {}               # open-ended extension
```

All three node types inherit from this.

### 2.2 `TextNode`

Represents an LLM call that produces **text or a text stream**.

```python
class TextNode(BaseExecutionNode):
    kind: Literal["text"] = "text"
    instruction: str                            # the system/user prompt template
    llm_config: LLMConfig                       # model, temperature, max_tokens, etc.
    streaming: bool = False                     # whether to stream the response
    context_refs: list[str] = []                # ContextRef keys to inject (memory, artifacts, etc.)
```

### 2.3 `ObjectNode`

Represents an LLM call that produces a **structured object** via tool-calling / function-calling. If validation of the output against `output_schema` fails, it should trigger the retry mechanism in the execution platform.

```python
class ObjectNode(BaseExecutionNode):
    kind: Literal["object"] = "object"
    instruction: str
    llm_config: LLMConfig
    output_model: type[BaseModel] | None = None # Pydantic model for structured output
    retry_on_validation_failure: bool = True    # auto-retry if output doesn't validate
    context_refs: list[str] = []
```

### 2.4 `FunctionNode`

Represents a **deterministic function** — no LLM involved. Used for data transformations, API calls, tool executions, etc.

```python
class FunctionNode(BaseExecutionNode):
    kind: Literal["function"] = "function"
    handler: Callable[..., Any]                 # the actual function to invoke
```

### 2.5 `LLMConfig`

```python
class LLMConfig(BaseModel):
    model: str                                  # e.g. "gpt-4", "claude-3-opus"
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stop_sequences: list[str] = []
    tool_definitions: list[dict[str, Any]] = [] # function/tool schemas for ObjectNode
    extra: dict[str, Any] = {}                  # provider-specific params
```

---

## 3. Base Capability Hierarchy

Capabilities define *what an agent can do*. Each capability registers one or more `ExecutionGraph`s that define *how* it's done. The orchestrator reads capabilities and builds the overall execution plan.

### 3.1 `BaseCapability`

```python
class BaseCapability(BaseModel):
    id: str                                     # namespaced capability ID (e.g. "skills.summarizer")
    name: str                                   # friendly name
    description: str                            # what the capability does — exposed to LLM for decision-making
    when_to_use: str                            # guidance for LLM on when to invoke this capability
    input_schema: dict[str, Any]                # JSON Schema for capability input
    output_schema: dict[str, Any]               # JSON Schema for capability output

    def register_execution_graph(self) -> ExecutionGraph:
        """Build and return the ExecutionGraph for this capability."""
        raise NotImplementedError
```

**Output semantics:** Every capability produces one of:
- `Response[T]` — success with structured data
- `Escalate` — the capability cannot handle this; delegate to parent/user
- `Fail` — unrecoverable error

### 3.2 `BaseSkill`

```python
class BaseSkill(BaseCapability):
    instruction: str                            # system prompt / behavioral guidance
    llm_config: LLMConfig                       # default LLM config for this skill
    capabilities: list[BaseCapability] = []     # nested sub-capabilities (tools, sub-skills)
    constraints: list[str] = []                 # behavioral constraints
```

A skill's `register_execution_graph()` produces a graph where nodes are `TextNode` or `ObjectNode` instances configured with the skill's `instruction` and `llm_config`.

### 3.3 `BaseTool`

```python
class BaseTool(BaseCapability):
    handler: Callable[..., Any]                 # the deterministic function to call
```

A tool's `register_execution_graph()` produces a trivial single-node graph with one `FunctionNode`.

### 3.4 `BaseWorkflow`

```python
class BaseWorkflow(BaseCapability):
    steps: list[BaseCapability]                 # ordered capabilities in the workflow
```

A workflow's `register_execution_graph()` composes sub-graphs from its steps into a larger `Graph`, potentially using `NodeGroup` for each step's sub-graph.

---

## 4. ExecutionGraph

The `ExecutionGraph` is the bridge between the cognitive layer and the execution platform. It:

1. Accepts `BaseExecutionNode` definitions
2. Converts them into `Graph` `Node` objects for topology
3. Maintains a parallel map of `node_id → ExecutionNode` for metadata/config retrieval
4. Is fully serializable via Pydantic for snapshotting and recovery

```python
class ExecutionGraph(BaseModel):
    name: str
    graph: Graph                                        # topology (from orchestrators/graphs)
    _node_registry: dict[str, BaseExecutionNode] = {}   # id → full ExecutionNode with configs

    def get_execution_node(self, node_id: str) -> BaseExecutionNode:
        """Retrieve the full ExecutionNode by ID."""
        ...

    def get_execution(self, node_id: str) -> Execution:
        """Build an Execution object from the ExecutionNode, ready to pass to ExecutionPlatform."""
        ...

    def nodes(self) -> list[BaseExecutionNode]:
        """All execution nodes."""
        ...

    def entry_nodes(self) -> set[BaseExecutionNode]:
        """Execution nodes with no predecessors in the graph."""
        ...

    def next_from(self, node_id: str) -> set[BaseExecutionNode]:
        """Successor execution nodes."""
        ...
```

**Key contract:** The `ExecutionGraph` does NOT hold execution state. It's a map. The orchestrator holds cursor position, results, and progression state.

---

## 5. Orchestrator (v1)

The Orchestrator is the controller that ties everything together. It:

- Receives capabilities and builds the `ExecutionGraph`
- Owns the execution state (cursor, results, history)
- Walks the graph node-by-node
- For each node, builds an `Execution` from the `ExecutionNode` config
- Injects context (memory, previous results, artifacts) into each execution
- Delegates execution to `ExecutionPlatform`
- Stores results in state
- Supports snapshot/restore for recovery

### 5.1 Core Contract

```python
class Orchestrator:
    def __init__(
        self,
        execution_platform: ExecutionPlatform,
        memory_store: MemoryStore,
        state: OrchestratorState,
    ) -> None: ...

    async def register_capability(self, capability: BaseCapability) -> None:
        """Register a capability; builds and stores its ExecutionGraph."""
        ...

    async def execute(self, capability_id: str, input_data: dict[str, Any]) -> OrchestratorResult:
        """Execute a capability end-to-end: walk its ExecutionGraph, run each node, return final result."""
        ...

    async def snapshot(self) -> dict[str, Any]:
        """Serialize current state for persistence/recovery."""
        ...

    async def restore(self, snapshot: dict[str, Any]) -> None:
        """Restore from a snapshot."""
        ...
```

### 5.2 `OrchestratorState`

```python
class OrchestratorState(BaseModel):
    session_id: str
    snapshot_id: str | None = None
    cursor: str | None = None                           # current node ID in the ExecutionGraph
    results: dict[str, ExecutionResult] = {}             # node_id → result
    history: list[dict[str, Any]] = []                   # ordered execution log
    context_store: dict[str, Any] = {}                   # injected context (memory, artifacts, prior outputs)
```

### 5.3 Execution Loop (pseudo-code)

```
1. Load ExecutionGraph for the requested capability
2. Set cursor to entry node(s)
3. For each cursor position:
   a. Get ExecutionNode from ExecutionGraph
   b. Build Execution object (handler, input, pre/postconditions, policies)
   c. Inject context: memory, previous node results, artifacts
   d. Call ExecutionPlatform(execution) → ExecutionResult
   e. Store result in state
   f. Emit events via EventBus
   g. Advance cursor to next node(s) based on graph topology
   h. If fan-out → default sequential, parallel if configured
   i. If single successor → continue sequential
   j. If leaf node → collect final result
   k. Snapshot state
4. Return OrchestratorResult
```

---

## 6. Module Layout

```
rh_cognitv_lite/cognitive/
    __init__.py
    nodes.py                # BaseExecutionNode, TextNode, ObjectNode, FunctionNode, LLMConfig
    capabilities.py         # BaseCapability, BaseSkill, BaseTool, BaseWorkflow
    execution_graph.py      # ExecutionGraph
    orchestrator.py         # Orchestrator, OrchestratorState, OrchestratorResult
    adapters/
        __init__.py
        llm_adapter.py      # LLMAdapter protocol — actual LLM call abstraction
    py.typed
```

---

## 7. LLM Adapter — The Provider Boundary

The cognitive layer must call LLMs but must **not** depend on any specific provider. An `LLMAdapter` protocol defines the boundary.

```python
class LLMAdapter(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]: ...

class LLMRequest(BaseModel):
    model: str
    messages: list[dict[str, str]]
    config: LLMConfig
    tools: list[dict[str, Any]] = []

class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = []
    usage: dict[str, int] = {}
    raw: dict[str, Any] = {}

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]

class LLMChunk(BaseModel):
    delta: str
    done: bool = False
```

---

## 8. Integration Points

| From | To | Mechanism |
|---|---|---|
| `BaseCapability.register_execution_graph()` | `ExecutionGraph` | Capability builds its own graph of `ExecutionNode`s |
| `ExecutionGraph.get_execution()` | `Execution` (execution platform) | Converts node config → platform-runnable `Execution` |
| `ExecutionGraph.graph` | `Graph` (orchestrators/graphs) | Topology for traversal |
| `Orchestrator` | `ExecutionPlatform` | Calls `platform(execution)` for each node |
| `Orchestrator` | `MemoryStore` | Loads/saves agent identity, skill memory, episodes |
| `Orchestrator` | `EventBus` | Publishes cognitive-level events |
| `Orchestrator` | `OrchestratorState` | Owns and mutates state; snapshots for recovery |
| `TextNode` / `ObjectNode` handler | `LLMAdapter` | Actual LLM call — injected at build time |
| `FunctionNode` handler | Direct function call | No LLM involved |

---

## 9. Design Decisions

---

### DD-01 — LLM Adapter: Single Unified Protocol ✅

**Decision:** Single unified `LLMAdapter`.

One `LLMAdapter` protocol with `complete()` returning `LLMResponse` (which carries both `content` and `tool_calls`). The `LLMConfig.tool_definitions` field on each node signals whether tool-calling is expected. The caller, which is specific to each node type, knows how to handle each case.

| Pros | Cons |
|---|---|
| One abstraction to implement per provider | `complete()` return type must handle both text and tool-call responses |
| Simpler dependency injection — one adapter instance passed everywhere | Providers with very different APIs for chat vs. function-calling may have awkward unified implementations |
| Easier to swap providers wholesale | |

---

### DD-02 — Prompt Assembly: Hybrid (Nodes Declare, Orchestrator Resolves) ✅

**Decision:** Option C — Hybrid.

Nodes carry a template (instruction + `context_refs`). The orchestrator resolves `context_refs` to actual data and passes the resolved context to a node-level `build_messages(resolved_context)` method. The `TextNode` knows what it needs to run; the orchestrator owns the "whys" — context resolution, memory lookups, artifact fetches.

| Pros | Cons |
|---|---|
| Nodes control their prompt shape but don't fetch context themselves | Slightly more complex interface between orchestrator and node |
| Orchestrator handles resolution (memory lookups, artifact fetches) uniformly | Template + resolution is two layers of abstraction |
| Clean separation of concerns | |

---

### DD-03 — ExecutionGraph: Immutable with Rebuild via Continuation ✅

**Decision:** Option D — Rebuild via continuation (`GraphBuilder.from_graph(existing)` pattern).

The graph itself stays immutable. When the plan changes, the orchestrator creates a new graph using `GraphBuilder.from_graph(old_graph)`, applies modifications, rebuilds. The orchestrator swaps the graph reference but all graph instances are immutable. Consistent with existing graphs module design philosophy.

| Pros | Cons |
|---|---|
| Graphs are always immutable — simple model | Full graph rebuild on each plan change (acceptable for small-medium graphs) |
| Uses the existing `GraphBuilder.from_graph()` continuation pattern already built | Must map cursor position and accumulated results to the new graph |
| No concurrency issues — swap is atomic (single reference) | Rebuild overhead for very large graphs (unlikely in practice) |

---

### DD-04 — ExecutionNode → Execution Conversion: Adapter Factory Pattern ✅

**Decision:** Option C — Adapter factory pattern.

An `ExecutionNodeAdapter` (separate from `LLMAdapter`) knows how to convert each `BaseExecutionNode` type into an `Execution`. One adapter per node kind (`TextNodeAdapter`, `ObjectNodeAdapter`, `FunctionNodeAdapter`). Registered with the orchestrator. This keeps `ExecutionGraph` declarative and the orchestrator thin.

| Pros | Cons |
|---|---|
| Clean separation — each node type has a dedicated converter | More classes, more indirection |
| Easy to extend with new node types | Registration boilerplate |
| Testable in isolation | |

---

### DD-05 — Fan-Out Execution: Configurable, Default Sequential ✅

**Decision:** Option C with **sequence as default**.

An `execution_mode` flag on nodes or edges controls whether fan-out successors run in parallel or sequentially. Default is sequential because fan-out is not necessarily parallel — it depends on the node semantics (e.g. a decision node activates only one branch since the Graph is just a map). Parallel execution is available as an opt-in for cases where branches are truly independent.

| Pros | Cons |
|---|---|
| Flexibility — each fan-out chooses its strategy | More configuration surface, more decisions for capability authors |
| Sequential default keeps it simple and predictable | |

---

### DD-06 — Context Injection: Typed ContextRef + Resolver Registry ✅ *(Pending: ContextStore deep design)*

**Decision:** Option B (typed `ContextRef` model) + Option C (resolver registry).

```python
class ContextRef(BaseModel):
    scope: Literal["memory", "artifact", "skill_output", "escalate"]
    key: str
```

The `ContextRef` model makes node definitions explicit and type-safe. The `ContextResolverRegistry` makes the orchestrator extensible — resolvers registered by scope, each knows how to fetch data.

| Pros | Cons |
|---|---|
| Type-safe, validated at construction time | Slightly more verbose in node definitions |
| Fully extensible — new scopes don't touch core logic | More setup boilerplate |
| Clean inversion of control | |

> **⚠️ PENDING — ContextStore requires deeper design.** The following open issues must be addressed in a dedicated section before implementation:
>
> 1. **`ForEachNode` pattern** — A workflow node `ForEachNode(refs_list, NodeOrNodeGroup)` that runs a node or group for each element in a list. Context ref keys must support indexed/scoped naming to avoid collisions across iterations (e.g. `skill_output.step_1[0]` vs `skill_output.step_1[1]`).
>
> 2. **Cyclic graph context** — In plan-execute-review cycles, each iteration may produce different artifacts. Flat registry keys would overwrite previous iterations' data, which may be undesirable. Need a strategy for iteration-scoped context (e.g. `skill_output.step_1@iteration_2` or a stack-based approach).
>
> 3. **ContextStore overall design** — The store itself (storage, lifecycle, scoping rules, cleanup) is not yet specified. Needs its own design section.

---

### DD-07 — Orchestrator State Persistence: Snapshot After Every Node (v1) ✅

**Decision:** Option A for v1 — snapshot after every node execution.

Maximum durability, simple recovery model. For LLM nodes (which take seconds each), snapshot overhead is negligible. Performance optimization can be added later if snapshotting becomes a bottleneck.

| Pros | Cons |
|---|---|
| Maximum durability — can resume from any node | High I/O overhead for fast-executing nodes |
| Simple recovery — always restart from last completed node | May dominate execution time for `FunctionNode`s |

---

### DD-08 — Capability Result Model: Separate Cognitive Result Wrapper ✅

**Decision:** Option B — Separate `CognitiveResult` wrapper.

Escalation is a fundamentally different outcome from failure — it means "I can't handle this, but it's not broken." The `CognitiveResult` wraps `ExecutionResult` so no platform changes are needed.

```python
class CognitiveResult(BaseModel, Generic[T]):
    kind: Literal["response", "escalate", "fail"]
    value: T | None = None              # present when kind="response"
    escalation: EscalationInfo | None   # present when kind="escalate"
    error: FailInfo | None              # present when kind="fail"
    execution_result: ExecutionResult   # underlying platform result
```

| Pros | Cons |
|---|---|
| Clean separation of cognitive semantics from platform mechanics | New model; orchestrator must unwrap two layers |
| `ExecutionResult` stays platform-only | More types to maintain |
| Escalation is a first-class concept, not a failure mode | |

---

### DD-09 — LLMConfig Inheritance: Merge with Node Overrides Winning ✅

**Decision:** Option B — Merge with node overrides winning.

The skill's `llm_config` provides defaults. Each node's `llm_config` overrides only the fields it explicitly sets (non-None). Use `None` as the "not set" sentinel for optional fields. For required fields like `model`, the skill must provide it and the node can override.

| Pros | Cons |
|---|---|
| DRY — skill sets defaults, nodes customize | Merge logic with partial override detection is tricky (how to distinguish "not set" from "set to default"?) |
| Common pattern (model, temperature set once per skill) | Debugging requires understanding the merge |

---

### DD-10 — Streaming Support: Stream via EventBus ✅

**Decision:** Option A — Stream via EventBus.

Tokens are emitted as `StreamChunkEvent` on the `EventBus`. `ExecutionResult` is returned at the end with the complete assembled text. This keeps the `ExecutionResult` contract intact, works with existing runners, and lets any number of consumers (UI, logging, monitoring) subscribe independently.

| Pros | Cons |
|---|---|
| Non-blocking — consumers subscribe to chunks as they arrive | Dual output path (EventBus for chunks, return value for complete text) |
| Existing infrastructure — EventBus is already wired everywhere | Stream consumers must subscribe before execution starts |
| `ExecutionResult` contract is unchanged | |

---

### DD-11 — ObjectNode Validation Retry: Platform-Owned, Orchestrator-Configured ✅ *(Reframed)*

**Issue:** When an `ObjectNode` produces output that fails schema validation, who handles the retry?

**Decision:** Retry logic stays entirely in the Execution Platform, configured by the orchestrator via `RetryConfig` and the error type system.

**Mechanism:** The `ObjectNode` handler raises a retryable error on validation failure. The existing error hierarchy in `execution_platform/errors.py` already supports this pattern — `CognitivError` has `retryable` and `category` fields that drive `PolicyChain` decisions. The platform's `RetryConfig` on the `Execution` handles the retry loop. The orchestrator configures the retry parameters when building the `Execution` from the node blueprint.

**Key insight:** The platform error types are flexible by design. If distinguishing validation retries from transient retries becomes necessary for budget tracking, a new error type (e.g. `OutputValidationError(TransientError)` — retryable, with its own category) can be added to the platform without changing the retry mechanism itself. The categorization is already there (`ErrorCategory`), the retry budget is already there (`RetryConfig.max_attempts`), and per-category budgeting can be layered on via `PolicyProtocol` if needed.

| Pros | Cons |
|---|---|
| Single retry mechanism — no duplicated logic between platform and handler | Validation retries share the same retry budget as transient errors (unless a new error type is introduced) |
| Consistent retry semantics across all error types | Cannot include the validation error in a re-prompt natively (the retry is opaque to the handler) |
| Uses existing infrastructure — `RetryConfig`, `CognitivError.retryable`, `PolicyChain` | Adding self-correction feedback to the re-prompt requires the handler to manage an internal prompt history across retries |
| Orchestrator controls retry behavior per node without owning retry logic | New error types may be needed to get fine-grained budget control |
| Error types are extensible — new categories don't break existing flows | |

**Implementation note — self-correction prompts:** For `ObjectNode` validation retries where including the validation error in the re-prompt is desirable (LLM self-correction), the handler itself can maintain an internal message history that appends the validation error. When the platform retries (calls the handler again with the same input + incremented `attempt`), the handler uses its accumulated history to build a better prompt. This keeps retry control in the platform while allowing the handler to be "retry-aware" for prompt quality.

**⬇ See DD-12 for the Execution Platform extension that formalises this.**

---

### DD-12 — Retry-Aware Execution: Platform-Level Self-Correction Support

**Issue:** DD-11 established that retry logic stays in the Execution Platform. The implementation note identified that a handler can maintain internal prompt history for self-correction. However, this puts the burden on every handler author to implement retry-awareness independently. The platform should offer first-class support so that:

1. A handler can flag `retry_aware=True` and automatically receive error context on retries.
2. An orchestrator needing more control can provide a `before_retry` callback to modify execution parameters (including prompt, model config, etc.) before the platform retries.

This is an **Execution Platform extension** — it modifies `Execution` and `ExecutionPlatform.__call__`.

#### 12.1 Proposed Models

```python
class RetryContext(BaseModel):
    """Injected into the handler on retry when retry_aware=True."""
    attempt: int                                # current attempt (2+)
    max_attempts: int                           # from RetryConfig
    error_message: str                          # what went wrong on the previous attempt
    error_category: str                         # ErrorCategory value
    error_type: str                             # exception class name
    previous_result: ExecutionResult | None      # full result from the previous attempt
    history: list[RetryAttemptRecord]            # all previous attempts

class RetryAttemptRecord(BaseModel):
    """Record of a single retry attempt."""
    attempt: int
    error_message: str
    error_category: str
    error_type: str
    duration_ms: float

# Callback type for advanced retry control
# Receives the execution + retry context, returns a modified execution (or None to keep as-is)
BeforeRetryCallback = Callable[[Execution, RetryContext], Execution | None]
```

#### 12.2 Changes to `Execution`

```python
class Execution(BaseModel):
    # ... existing fields ...
    retry_aware: bool = False                   # if True, handler receives RetryContext as second arg on retries
    before_retry: BeforeRetryCallback | None = None  # optional callback to modify execution before retry
```

#### 12.3 Platform Retry Loop Changes

The `ExecutionPlatform.__call__` retry loop (currently in `execution.py`) changes as follows:

```python
async def __call__(self, input_execution: Execution) -> ExecutionResult[Any]:
    retry_config = input_execution.retry_config
    max_attempts = retry_config.max_attempts if retry_config else 1
    result: ExecutionResult[Any] | None = None
    retry_history: list[RetryAttemptRecord] = []

    for attempt in range(1, max_attempts + 1):
        exec_item = input_execution
        retry_context: RetryContext | None = None

        if attempt > 1 and result is not None:
            # Build retry context from previous failure
            retry_context = RetryContext(
                attempt=attempt,
                max_attempts=max_attempts,
                error_message=result.error_message or "",
                error_category=result.error_category or "",
                error_type=(result.error_details or {}).get("type", "Unknown"),
                previous_result=result,
                history=list(retry_history),
            )

            # 1. Call before_retry callback if provided (advanced control)
            if exec_item.before_retry is not None:
                modified = exec_item.before_retry(exec_item, retry_context)
                if modified is not None:
                    exec_item = modified

            # 2. Set attempt number
            exec_item = exec_item.model_copy(update={"attempt": attempt})

        result = await self._execute_once(exec_item, retry_context=retry_context)

        if result.ok:
            return result

        # Record attempt in history
        retry_history.append(RetryAttemptRecord(
            attempt=attempt,
            error_message=result.error_message or "",
            error_category=result.error_category or "",
            error_type=(result.error_details or {}).get("type", "Unknown"),
            duration_ms=result.metadata.duration_ms,
        ))

        retryable = (
            result.error_details.get("retryable", False)
            if result.error_details else False
        )
        if not retryable or attempt >= max_attempts:
            return result

        delay = retry_config.delay_for(attempt) if retry_config else 0.0
        await asyncio.sleep(delay)

    return result  # type: ignore[return-value]
```

#### 12.4 Handler Invocation Change in `_execute_once`

```python
# In _execute_once, step 4 — Call handler:
if exec_item.retry_aware and retry_context is not None:
    # Inject retry context as second argument
    if inspect.iscoroutinefunction(exec_item.handler):
        result_data = await exec_item.handler(exec_item.input_data, retry_context)
    else:
        result_data = exec_item.handler(exec_item.input_data, retry_context)
else:
    # Normal invocation — no retry context
    if inspect.iscoroutinefunction(exec_item.handler):
        result_data = await exec_item.handler(exec_item.input_data)
    else:
        result_data = exec_item.handler(exec_item.input_data)
```

#### 12.5 Usage Patterns

**Simple case — `retry_aware=True` (ObjectNode default):**

The `ObjectNodeAdapter` builds a handler that accepts the optional `RetryContext`. On retry, it appends the validation error to the LLM messages for self-correction:

```python
async def object_node_handler(input_data, retry_context: RetryContext | None = None):
    messages = build_messages(node, resolved_context)
    if retry_context:
        messages.append({
            "role": "user",
            "content": f"Your previous output failed validation: {retry_context.error_message}. "
                       f"Please correct your response."
        })
    response = await llm_adapter.complete(LLMRequest(messages=messages, config=node.llm_config))
    validated = validate_output(response, node.output_model)
    return validated
```

**Advanced case — `before_retry` callback (orchestrator-level control):**

The orchestrator provides a callback that modifies execution parameters before retry — e.g. switching to a stronger model, adjusting temperature, or rewriting the full prompt:

```python
def my_before_retry(execution: Execution, ctx: RetryContext) -> Execution:
    if ctx.attempt >= 3:
        # Switch to a stronger model after 2 failures
        new_input = {**execution.input_data, "model_override": "gpt-4"}
        return execution.model_copy(update={"input_data": new_input})
    return execution  # no change

execution = Execution(
    name="structured_output",
    handler=my_handler,
    input_data=data,
    retry_config=RetryConfig(max_attempts=5),
    retry_aware=True,
    before_retry=my_before_retry,
)
```

#### 12.6 Design Rationale

| Aspect | Decision |
|---|---|
| **Where does retry live?** | Platform — unchanged from DD-11. The retry loop in `ExecutionPlatform.__call__` is the single point of retry control. |
| **How does the handler get error context?** | `retry_aware=True` → handler receives `RetryContext` as second arg on attempts 2+. First attempt is always normal (no context). |
| **How does the orchestrator customize retries?** | `before_retry` callback on `Execution`. Called before each retry. Can return a modified `Execution` or `None` (keep as-is). |
| **Backward compatibility** | `retry_aware` defaults to `False`. `before_retry` defaults to `None`. Existing handlers and executions are unaffected. |
| **Execution order on retry** | `before_retry` runs first (may modify the execution), then `_execute_once` invokes the handler with optional `RetryContext`. The callback modifies the "what", the handler uses the "why". |

#### 12.7 Affected Files

| File | Change |
|---|---|
| `execution_platform/models.py` | Add `RetryContext`, `RetryAttemptRecord` |
| `execution_platform/execution.py` | Add `retry_aware`, `before_retry` to `Execution`; modify `__call__` retry loop; modify `_execute_once` handler invocation |
| `execution_platform/errors.py` | Add `OutputValidationError(TransientError)` for LLM output validation failures |
| `tests/execution_platform/` | Tests for retry-aware handlers, before_retry callbacks, backward compat |

---

## 10. Pending Design Items

These items have been approved for v1 and require decisions before implementation.

---

### DD-13 — ContextStore Design *(from DD-06)*

**Issue:** The `ContextRef` model and `ContextResolverRegistry` pattern are decided (DD-06), but the underlying `ContextStore` — storage model, lifecycle, scoping rules, and iteration-aware naming — is not yet designed. Three concrete sub-problems drive this:

1. **ForEachNode iteration scoping** — `ForEachNode(refs_list, NodeOrNodeGroup)` runs a node/group for each element in a list. Context refs produced inside the loop must be namespaced per iteration to avoid collisions.
2. **Cyclic graph context** — In plan-execute-review cycles, each iteration may produce artifacts. Flat registry keys would overwrite previous iterations' data.
3. **Store lifecycle** — When context entries are created, when they're cleaned up, and what scoping applies (per-graph, per-capability, per-session).

---

**Option A: Flat key-value store with convention-based namespacing**

Keys are plain strings with a convention: `"{scope}.{key}"` for simple cases, `"{scope}.{key}[{index}]"` for iterations, `"{scope}.{key}@{iteration}"` for cycles.

```python
class ContextStore:
    _data: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None: ...
    def get(self, key: str) -> Any: ...
    def list_keys(self, prefix: str) -> list[str]: ...
    def clear(self, prefix: str | None = None) -> None: ...
```

| Pros | Cons |
|---|---|
| Simplest possible implementation | Convention-based — typos and collisions caught only at runtime |
| Easy to serialize (it's just a dict) | ForEach/cycle scoping relies on callers constructing keys correctly |
| No new abstractions | No structural enforcement of scoping rules |
| Familiar key-value semantics | Cleanup requires knowing all key prefixes |

---

**Option B: Hierarchical scoped store with frame stack**

A stack-based store where `ForEachNode` and cycle iterations push a new scope frame. Lookups walk up the stack (inner scope shadows outer). Each frame is a dict.

```python
class ScopeFrame(BaseModel):
    name: str                                   # e.g. "foreach.step_1[2]", "cycle.plan_review@3"
    data: dict[str, Any] = {}

class ContextStore(BaseModel):
    frames: list[ScopeFrame] = []               # stack — last is innermost

    def push_frame(self, name: str) -> None: ...
    def pop_frame(self) -> ScopeFrame: ...
    def put(self, key: str, value: Any) -> None:  # writes to topmost frame
        ...
    def get(self, key: str) -> Any:               # walks stack from top to bottom
        ...
    def get_scoped(self, frame_name: str, key: str) -> Any:  # explicit frame lookup
        ...
    def snapshot(self) -> dict[str, Any]: ...
    def restore(self, snapshot: dict[str, Any]) -> None: ...
```

| Pros | Cons |
|---|---|
| Structural scoping — ForEach/cycle iterations are first-class frames | More complex model — stack management adds cognitive load |
| Inner scopes naturally shadow outer without overwriting | Frame naming convention still needed |
| Previous iteration data is preserved (earlier frames remain) | Walking the stack on every `get()` adds overhead (negligible for typical sizes) |
| Clean cleanup — `pop_frame()` removes all iteration-local data | Serialization must capture full stack |
| Debugging is transparent — inspect the frame stack to see what's visible | |

---

**Option C: Namespaced registry with typed scopes and versioning**

Scopes are first-class objects. Each scope has a type (`graph`, `foreach_iteration`, `cycle_iteration`, `session`) and an auto-incrementing version for cycles.

```python
class ContextScope(BaseModel):
    scope_type: Literal["graph", "foreach", "cycle", "session"]
    scope_id: str                               # e.g. "plan_review", "step_1"
    version: int = 0                            # incremented per cycle iteration
    parent: ContextScope | None = None          # tree of scopes

class ContextStore(BaseModel):
    _scopes: dict[str, ContextScope] = {}
    _data: dict[tuple[str, int, str], Any] = {} # (scope_id, version, key) → value

    def create_scope(self, scope: ContextScope) -> None: ...
    def put(self, scope_id: str, key: str, value: Any) -> None: ...
    def get(self, scope_id: str, key: str, version: int | None = None) -> Any: ...
    def get_latest(self, scope_id: str, key: str) -> Any: ...
    def get_all_versions(self, scope_id: str, key: str) -> list[tuple[int, Any]]: ...
    def increment_version(self, scope_id: str) -> int: ...
```

| Pros | Cons |
|---|---|
| Explicit versioning — cycle iterations never collide | Most complex model — scope management is heavyweight |
| ForEach iterations are separate scopes with distinct IDs | Requires the orchestrator to manage scope lifecycle |
| Can retrieve any historical version (useful for review/comparison nodes) | Scope tree traversal adds complexity to resolution |
| Type-safe scope hierarchy | Over-engineered for simple capabilities with no iteration |
| Clean separation between scope management and data storage | |

---

**Option D: Hybrid — flat store with orchestrator-managed context namespacing**

The store itself is simple (flat key-value). The orchestrator (or a `ContextNamespacer` utility) manages key construction for ForEach/cycle scenarios. The `ContextRef` resolution layer (from DD-06) is the only consumer, so it controls the namespace.

```python
class ContextStore(BaseModel):
    _data: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None: ...
    def get(self, key: str) -> Any: ...
    def get_all(self, prefix: str) -> dict[str, Any]: ...
    def clear(self, prefix: str | None = None) -> None: ...

class ContextNamespacer:
    """Utility for constructing scoped context keys."""

    @staticmethod
    def for_iteration(base_key: str, index: int) -> str:
        return f"{base_key}[{index}]"

    @staticmethod
    def for_cycle(base_key: str, iteration: int) -> str:
        return f"{base_key}@iter_{iteration}"

    @staticmethod
    def latest(base_key: str) -> str:
        return f"{base_key}@latest"
```

The orchestrator writes both the versioned key and `@latest` alias on every cycle iteration. Resolvers read `@latest` by default but can request specific iterations.

| Pros | Cons |
|---|---|
| Store stays trivially simple — easy to test, serialize, debug | Namespacing logic lives outside the store — scattered responsibility |
| Namespace rules are centralized in a single utility class | `@latest` alias must be kept in sync manually |
| No stack or scope management overhead | No structural enforcement — wrong key construction silently breaks |
| Easy to extend — add new naming strategies without changing the store | Cleanup requires knowing the namespace patterns |
| Familiar pattern — just a dict with smart keys | |

---

**Recommendation:** Option B. The frame stack gives structural guarantees that ForEach and cycle iterations need — push on entry, pop on exit, previous data preserved. It's more robust than convention-based flat keys (Option A/D) without the heavyweight scope management of Option C. The orchestrator's graph-walker naturally maps to push/pop semantics: entering a ForEachNode or a new cycle iteration pushes a frame; completing it pops. This means the store lifecycle is tied to graph traversal, which is already the orchestrator's job.

**Decision:** `B`
**Comments:** `No notes`

---

### DD-14 — Token Budget Tracking *(from S-01)*

**Issue:** LLM calls consume tokens. Over the course of an orchestrator run (potentially many nodes), total token usage can be significant. The orchestrator needs a mechanism to track and enforce token budgets. The `BudgetSnapshot` model and `InterruptReason.RESOURCE_LIMIT` already exist in the execution platform.

---

**Option A: Orchestrator-level budget counter (no policy)**

The orchestrator maintains a simple counter. After each node execution, it reads `LLMResponse.usage` from the result, accumulates, and checks against a configured limit. If exceeded, it stops graph traversal.

```python
class TokenBudget(BaseModel):
    max_prompt_tokens: int | None = None
    max_completion_tokens: int | None = None
    max_total_tokens: int | None = None
    used_prompt_tokens: int = 0
    used_completion_tokens: int = 0

    def record(self, usage: dict[str, int]) -> None: ...
    def exceeded(self) -> bool: ...
    def remaining(self) -> BudgetSnapshot: ...
```

| Pros | Cons |
|---|---|
| Simplest implementation — budget check is a few lines in the orchestrator loop | Tightly coupled to orchestrator — cannot reuse for non-orchestrator execution |
| No new protocols or abstractions | Does not integrate with the platform's policy/interrupt infrastructure |
| Easy to test | Cannot abort mid-execution (only between nodes) |

---

**Option B: `BudgetPolicy` implementing `PolicyProtocol`**

A composable policy that hooks into the execution platform's policy chain. Runs `after_execute` to accumulate usage. Raises `InterruptError(reason=RESOURCE_LIMIT)` when the budget is exceeded, which the platform's existing interrupt flow handles.

```python
class BudgetPolicy(PolicyProtocol):
    def __init__(self, budget: TokenBudget) -> None:
        self._budget = budget

    async def before_execute(self, event, data, configs) -> None:
        if self._budget.exceeded():
            raise InterruptError(
                "Token budget exceeded",
                signal=InterruptSignal(reason=InterruptReason.RESOURCE_LIMIT),
            )

    async def after_execute(self, event, result, configs) -> None:
        usage = self._extract_usage(result)
        self._budget.record(usage)
        if self._budget.exceeded():
            raise InterruptError(
                "Token budget exceeded",
                signal=InterruptSignal(reason=InterruptReason.RESOURCE_LIMIT),
            )

    async def on_error(self, event, error, configs) -> None:
        pass  # budget tracking ignores errors
```

| Pros | Cons |
|---|---|
| Uses existing infrastructure — `PolicyProtocol`, `InterruptError`, `InterruptSignal` | `PolicyProtocol` hooks receive generic `event`/`result` — extracting token usage requires convention on where usage lives in the result |
| Can abort even mid-execution (before_execute check) | Policy must be attached to each `Execution` — orchestrator must wire it |
| Composable — multiple policies (budget + rate-limit + timeout) stack naturally | Slightly more complex setup than a simple counter |
| Reusable outside the orchestrator (e.g. standalone execution platform usage) | |

---

**Option C: EventBus-based budget tracker (observer pattern)**

A subscriber on the `EventBus` listens for `ExecutionEvent(status=COMPLETED)` events. Extracts token usage from `event.ext` or `event.payload`. Accumulates and publishes a `BudgetExceededEvent` (or calls the orchestrator's interrupt checker) when the limit is hit.

```python
class BudgetTracker:
    def __init__(self, budget: TokenBudget, interrupt_fn: Callable[[], None]) -> None:
        self._budget = budget
        self._interrupt_fn = interrupt_fn

    async def on_event(self, event: ExecutionEvent) -> None:
        if event.status == EventStatus.COMPLETED:
            usage = event.ext.get("token_usage", {})
            self._budget.record(usage)
            if self._budget.exceeded():
                self._interrupt_fn()
```

| Pros | Cons |
|---|---|
| Fully decoupled — tracker doesn't know about orchestrator or platform internals | Asynchronous — there's a window between exceeding budget and interrupt taking effect |
| Easy to add/remove without changing execution flow | Requires events to carry token usage in `ext` (cognitive layer must ensure this) |
| Can track budget across multiple execution platforms | Interrupt is indirect — harder to reason about when it fires |

---

**Option D: Hybrid — `BudgetPolicy` for enforcement + `TokenBudget` model owned by orchestrator**

The orchestrator owns a `TokenBudget` model (budget accounting). It creates a `BudgetPolicy` from it and attaches it to each `Execution`. The policy enforces the budget at the platform level. The orchestrator reads `budget.remaining()` for reporting.

| Pros | Cons |
|---|---|
| Clean separation — orchestrator owns budget, platform enforces it | Two components to understand (model + policy) |
| Budget state is accessible outside execution (for reporting, snapshot) | Must wire the policy into each execution |
| Uses existing infrastructure but doesn't over-couple | |
| Budget survives snapshot/restore (it's a Pydantic model) | |

---

**Recommendation:** Option D. The `TokenBudget` model gives the orchestrator visibility and snapshot capability. The `BudgetPolicy` gives the platform enforcement without the orchestrator implementing retry/interrupt logic. This is consistent with DD-11's principle: the platform handles the mechanics (enforcement), the orchestrator handles the configuration (budget limits, which executions to track).

**Decision:** `D`
**Comments:** `No notes`

---

### DD-15 — Cognitive Telemetry via EventBus *(from S-02)*

**Issue:** For debugging and optimization, the cognitive layer needs to emit structured telemetry: which nodes ran, in what order, how long each took, token usage, prompt previews.

The `ExecutionEvent` is already a generic data object with `kind: str`, `payload: dict`, `ext: dict`, `status`, `retried`, `parent_id`, and `group_id`. It was designed to be customizable per scenario.

**Verified:** The existing `ExecutionEvent` model fields cover all cognitive telemetry needs:
- `kind` → `"cognitive.node.text"`, `"cognitive.node.object"`, `"cognitive.graph.started"`, etc.
- `payload` → node-specific data (prompt preview, result summary, token usage)
- `ext` → additional metadata (model name, temperature, context_refs resolved)
- `status` → `STARTED`, `COMPLETED`, `FAILED`
- `parent_id` → link node events to their graph event
- `group_id` → correlate all events in a single capability execution

No new event types are needed. The question is how to construct and emit these events.

---

**Option A: Direct emission in orchestrator**

The orchestrator loop directly constructs `ExecutionEvent` instances with cognitive-specific `kind` and `payload` values at each lifecycle point (node start, node complete, graph start, graph complete).

```python
# In orchestrator loop:
await event_bus.publish(ExecutionEvent(
    name=node.name,
    kind="cognitive.node.started",
    payload={"node_kind": node.kind, "prompt_preview": instruction[:200]},
    parent_id=graph_event_id,
    group_id=capability_execution_id,
    status=EventStatus.STARTED,
))
```

| Pros | Cons |
|---|---|
| Simplest — no new abstractions | Event construction logic mixed into orchestrator |
| Full control over what's emitted and when | If emit patterns change, must modify orchestrator |
| Easy to debug — all event creation is in one place | Duplication if other components need similar events |

---

**Option B: `CognitiveEventAdapter` — builder utility**

A dedicated adapter class that knows how to construct cognitive `ExecutionEvent` instances from cognitive-layer primitives (execution nodes, graph state, results). The orchestrator calls the adapter; the adapter builds the event.

```python
class CognitiveEventAdapter:
    """Builds ExecutionEvent instances for cognitive telemetry."""

    def node_started(self, node: BaseExecutionNode, graph_event_id: str,
                     group_id: str) -> ExecutionEvent: ...
    def node_completed(self, node: BaseExecutionNode, result: ExecutionResult,
                       token_usage: dict, graph_event_id: str,
                       group_id: str) -> ExecutionEvent: ...
    def graph_started(self, graph_name: str, entry_nodes: list[str],
                      group_id: str) -> ExecutionEvent: ...
    def graph_completed(self, graph_name: str, results_summary: dict,
                        group_id: str) -> ExecutionEvent: ...
```

| Pros | Cons |
|---|---|
| Event construction is centralized and testable | New class — more code to maintain |
| Orchestrator stays thin — calls `adapter.node_started(...)`, publishes result | Adapter must know about cognitive-layer types (nodes, results) |
| Easy to change event shape without touching orchestrator logic | Slight indirection |
| Consistent event structure — all cognitive events go through one builder | |

---

**Option C: EventBus middleware that auto-enriches events**

A middleware registered in the `EventBus` pipeline that intercepts platform-level `ExecutionEvent` instances and enriches them with cognitive metadata (node kind, prompt preview, token usage) based on a metadata registry.

| Pros | Cons |
|---|---|
| Zero changes to orchestrator or platform — middleware is transparent | Middleware must have access to a metadata registry (coupling) |
| Existing events are enriched, not duplicated | Implicit behavior — debugging requires knowing the middleware is there |
| Composable — add/remove without code changes | Hard to emit events that don't originate from platform execution (e.g. graph-level events) |

---

**Recommendation:** Option B. The `CognitiveEventAdapter` is a clean separation: the orchestrator knows *when* to emit; the adapter knows *what shape* the event should have. This follows the same adapter pattern used in DD-04 (ExecutionNodeAdapter). The adapter is a simple stateless builder — not a heavy abstraction.

**Decision:** `B`
**Comments:** `No notes`

---

### DD-16 — Capability Registry *(from S-03)*

**Issue:** The orchestrator needs to know which capabilities are available. For v1 this is a simple lookup; for later versions it may support dynamic discovery, plugin loading, and hot-reloading. The `BaseCapability.id` namespace convention (e.g. `"skills.summarizer"`, `"tools.calendar"`) already supports registry-style lookups.

---

**Option A: Plain `dict[str, BaseCapability]` on the orchestrator**

No separate registry class. The orchestrator stores capabilities in an internal dict keyed by `id`. Registration is `self._capabilities[cap.id] = cap`.

```python
class Orchestrator:
    _capabilities: dict[str, BaseCapability] = {}

    async def register_capability(self, cap: BaseCapability) -> None:
        self._capabilities[cap.id] = cap

    def get_capability(self, cap_id: str) -> BaseCapability:
        return self._capabilities[cap_id]
```

| Pros | Cons |
|---|---|
| Zero new classes — minimal code | No separation of concerns — registry logic embedded in orchestrator |
| Works for v1 | Cannot reuse the registry outside the orchestrator |
| Trivial to understand | No validation, no events, no lifecycle hooks |
| | Hard to extend to dynamic discovery later without refactoring |

---

**Option B: Standalone `CapabilityRegistry` class**

A separate class that owns registration, lookup, listing, and validation. Injected into the orchestrator.

```python
class CapabilityRegistry:
    _capabilities: dict[str, BaseCapability] = {}

    def register(self, capability: BaseCapability) -> None:
        if capability.id in self._capabilities:
            raise ValueError(f"Capability '{capability.id}' already registered")
        self._capabilities[capability.id] = capability

    def get(self, capability_id: str) -> BaseCapability:
        if capability_id not in self._capabilities:
            raise KeyError(f"Capability '{capability_id}' not found")
        return self._capabilities[capability_id]

    def list_all(self) -> list[BaseCapability]:
        return list(self._capabilities.values())

    def list_by_type(self, cap_type: type) -> list[BaseCapability]:
        return [c for c in self._capabilities.values() if isinstance(c, cap_type)]

    def has(self, capability_id: str) -> bool:
        return capability_id in self._capabilities

    def unregister(self, capability_id: str) -> None:
        del self._capabilities[capability_id]
```

| Pros | Cons |
|---|---|
| Reusable — can be shared across orchestrators | New class, slightly more code |
| Validation on registration (duplicate ID check) | Must be injected into orchestrator |
| `list_by_type` enables LLM-facing capability descriptions (e.g. list all tools) | |
| Clean extension point for future versions (events on register, plugin loading) | |
| Testable in isolation | |

---

**Option C: Protocol-based registry with in-memory default**

Define a `CapabilityRegistryProtocol` and provide a default in-memory implementation. Later versions can swap in a persistent or distributed registry.

```python
class CapabilityRegistryProtocol(Protocol):
    def register(self, capability: BaseCapability) -> None: ...
    def get(self, capability_id: str) -> BaseCapability: ...
    def list_all(self) -> list[BaseCapability]: ...
    def has(self, capability_id: str) -> bool: ...

class InMemoryCapabilityRegistry:
    """Default v1 implementation."""
    ...
```

| Pros | Cons |
|---|---|
| Maximum flexibility — swap implementations without changing consumers | Over-engineered for v1 — only one implementation exists |
| Follows dependency inversion used elsewhere in the codebase | Protocol + implementation is more code than a simple class |
| Future-proof for distributed/persistent registries | |

---

**Recommendation:** Option B. A standalone `CapabilityRegistry` with duplicate-ID validation, type-based listing, and simple CRUD. Not wrapped in a protocol for v1 — that's a later refactor if/when multiple implementations are needed. The orchestrator receives it via constructor injection.

**Decision:** `B`
**Comments:** `No notes`

---

### DD-17 — Cycle Termination Strategy *(from S-04)*

**Issue:** Cyclic graphs (e.g. plan-execute-review) need a mechanism to stop. The graph itself doesn't know about iterations — it's just a topology map. The orchestrator's graph-walker follows `next_nodes_from` and will re-visit nodes indefinitely unless something stops it. This applies to any cyclic graph, not just PlanReview.

---

**Option A: Hard cap only — `max_iterations` on the orchestrator**

The orchestrator counts how many times it has visited each node (or how many times it has crossed a back-edge). When the count exceeds `max_iterations`, it stops and returns the last result.

```python
class CycleConfig(BaseModel):
    max_iterations: int = 10                    # hard cap per cycle
```

| Pros | Cons |
|---|---|
| Simplest implementation — counter + threshold | No early exit when convergence is reached — always runs up to max |
| Deterministic — always terminates | Wastes LLM calls if convergence happens early |
| Easy to configure and understand | Cannot express "stop when the output says done" |

---

**Option B: Convergence check only — exit node signals "done"**

The orchestrator inspects the result of designated "review" nodes. If the result contains a convergence signal (e.g. `{"done": true}` or a specific `CognitiveResult` kind), the cycle exits.

```python
class CycleConfig(BaseModel):
    convergence_key: str = "done"               # key in result to check
    convergence_value: Any = True               # value that signals exit
```

| Pros | Cons |
|---|---|
| Efficient — exits as soon as work is done | No safety net — a poorly designed node may never signal convergence |
| Semantically correct — the review node decides when quality is sufficient | Risk of infinite loops if LLM never produces the convergence signal |
| | Configuration is fragile — depends on result structure |

---

**Option C: Convergence + hard cap (safety net)**

Both mechanisms combined. The orchestrator exits the cycle when either:
1. A review node signals convergence, OR
2. `max_iterations` is reached (safety net).

```python
class CycleConfig(BaseModel):
    max_iterations: int = 10
    convergence_check: Callable[[ExecutionResult], bool] | None = None
```

The `convergence_check` is a callable that receives the result of the current node and returns `True` to exit. If `None`, only the hard cap applies. The callable is provided by the capability author (they know what "done" looks like for their review node).

| Pros | Cons |
|---|---|
| Always terminates (hard cap) | Two mechanisms — slightly more complex |
| Exits early when work is done (convergence) | Capability authors must define a convergence checker for optimal behavior |
| Hard cap catches buggy convergence checks | |
| Flexible — convergence is a callable, not a convention on result shape | |

---

**Option D: Edge-level cycle-breaking with TerminationCondition**

Cycles are broken at the edge level. Specific back-edges carry a `TerminationCondition` that is evaluated before traversal. If the condition returns `True`, the edge is not followed.

```python
class Edge(BaseModel):
    source: str
    target: str
    label: str | None = None
    termination_condition: Callable[[dict[str, ExecutionResult]], bool] | None = None
```

| Pros | Cons |
|---|---|
| Granular — different cycles in the same graph can have different exit conditions | Modifies the `Edge` model (graph layer), leaking execution semantics into topology |
| No global cycle tracking needed | Condition must be serializable for snapshot/restore (callables are not) |
| Explicit on the graph itself | More complex graph construction |

---

**Recommendation:** Option C. Convergence with a hard cap is the standard pattern for iterative refinement loops. The hard cap guarantees termination. The convergence callable is optional — simple cycles can rely on the cap alone. The callable is provided per-capability via `CycleConfig`, not baked into the graph topology (keeping the graph layer clean). The `max_iterations` default of 10 is a sensible safety net.

**Decision:** `C`
**Comments:** `No notes`

---

## 11. Development Phases

### Phase 0 — Execution Platform: Retry-Aware Extension (DD-12)

| Task | Where |
|---|---|
| `RetryContext`, `RetryAttemptRecord` models | `execution_platform/models.py` |
| `OutputValidationError(TransientError)` error type | `execution_platform/errors.py` |
| `retry_aware`, `before_retry` fields on `Execution` | `execution_platform/execution.py` |
| Retry loop refactor in `ExecutionPlatform.__call__` | `execution_platform/execution.py` |
| Handler invocation change in `_execute_once` | `execution_platform/execution.py` |
| Update `__init__.py` exports | `execution_platform/__init__.py` |
| **Tests:** retry-aware handlers, before_retry callbacks, backward compat, OutputValidationError | `tests/execution_platform/test_retry_aware.py` |

### Phase 1 — Execution Nodes & LLM Adapter Protocol

| Task | Where |
|---|---|
| `LLMConfig` | `cognitive/nodes.py` |
| `BaseExecutionNode`, `TextNode`, `ObjectNode`, `FunctionNode` | `cognitive/nodes.py` |
| `LLMAdapter`, `LLMRequest`, `LLMResponse`, `ToolCall`, `LLMChunk` protocols | `cognitive/adapters/llm_adapter.py` |
| **Tests:** model creation, serialization round-trip, validation | `tests/cognitive/test_nodes.py` |

### Phase 2 — Capabilities

| Task | Where |
|---|---|
| `BaseCapability`, `BaseSkill`, `BaseTool`, `BaseWorkflow` | `cognitive/capabilities.py` |
| `CognitiveResult`, `EscalationInfo`, `FailInfo` | `cognitive/results.py` |
| **Tests:** capability hierarchy, `register_execution_graph()` contract, result types | `tests/cognitive/test_capabilities.py` |

### Phase 3 — ExecutionGraph

| Task | Where |
|---|---|
| `ExecutionGraph` — node registration, graph construction, `get_execution()` | `cognitive/execution_graph.py` |
| `ExecutionNodeAdapter` protocol + concrete adapters for Text/Object/Function | `cognitive/adapters/` |
| **Tests:** graph construction from nodes, execution conversion, serialization round-trip | `tests/cognitive/test_execution_graph.py` |

### Phase 4 — Orchestrator (v1)

| Task | Where |
|---|---|
| `OrchestratorState`, `OrchestratorResult` | `cognitive/orchestrator.py` |
| `Orchestrator` — register capabilities, execute, snapshot/restore | `cognitive/orchestrator.py` |
| Context injection (`ContextRef` resolution) | `cognitive/orchestrator.py` |
| **Tests:** full execution loop with mock LLM adapter, fan-out parallel, snapshot/restore round-trip | `tests/cognitive/test_orchestrator.py` |

### Phase 5 — Integration Tests

| Task | Where |
|---|---|
| End-to-end: define a skill with TextNode + ObjectNode + FunctionNode, execute via orchestrator | `tests/cognitive/test_integration.py` |
| Workflow with sub-graph (`BaseWorkflow` + `NodeGroup`) | `tests/cognitive/test_integration.py` |
| Snapshot mid-execution, restore, resume | `tests/cognitive/test_integration.py` |

---

## 12. Deferred

- **Semantic memory / vector retrieval** — `SemanticMemoryStore` protocol, dependent on Artifact module
- **Multi-agent coordination** — multiple orchestrators sharing state
- **Conditional edge evaluation** — dynamic routing at fan-out nodes based on result content
- **Token-aware prompt truncation** — auto-truncating context when approaching token limits
- **`html`/`image` graph visualization** — deferred in Spec 06, still deferred here
