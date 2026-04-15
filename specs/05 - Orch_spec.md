# 🧠 Agent Orchestration System — Development Spec (v1)

## Overview

This document specifies a minimal but robust architecture for building a **stateful agent orchestration system** with:

- Main Orchestrator Agent
- Plan/Review component
- Execution component
- Specialized Skills (e.g., Scheduler)
- Tool integration
- Snapshot-based recovery (stateless workers)

---

# 1. Core Architecture

## Flow

```text
User
  → MainAgent (orchestrator)
      → PlanReview (planner + reviewer)
      → Execution (step executor)
          → Skill (e.g., ScheduleSkill)
              → Tools
      → MainAgent
  → Final Response
```

---

# 2. Core Concepts

## 2.1 Plan vs Step

- **Plan** = strategy (slow-changing)
- **Step** = executable unit (fast-changing)

## 2.2 Execution Loop

```text
plan → execute → review → repeat
```

## 2.3 State Ownership

| Component      | Owns |
|----------------|------|
| MainAgent      | RunState, control flow |
| PlanReview     | Plan, step generation |
| Execution      | Step execution |
| Skill          | Domain logic |
| Tool           | External side effects |

---

# 3. Data Models

## 3.1 RunState

```json
{
  "run_id": "string",
  "status": "running | completed | failed",
  "lifecycle_state": "ready_for_plan_review | ready_for_execution | waiting_for_execution_result | waiting_for_user | completed | failed",
  "user_query": "string",
  "current_phase": "string",
  "current_step_id": "string | null",
  "plan_id": "string | null",
  "artifact_ids": ["string"],
  "last_event_id": "string",
  "final_response": "object | null"
}
```

---

## 3.2 Plan

```json
{
  "plan_id": "string",
  "goal": "string",
  "status": "pending | in_progress | completed | blocked | failed",
  "phases": [
    {
      "phase_id": "string",
      "name": "string",
      "status": "pending | in_progress | done | blocked | failed"
    }
  ],
  "steps": [],
  "success_criteria": ["string"],
  "assumptions": ["string"]
}
```

---

## 3.3 StepSpec

```json
{
  "step_id": "string",
  "phase_id": "string",
  "title": "string",
  "instruction": "string",
  "type": "string",
  "status": "pending | in_progress | done | blocked | failed",
  "depends_on": ["string"],
  "inputs": {},
  "expected_output_type": "string"
}
```

---

## 3.4 Artifact

```json
{
  "artifact_id": "string",
  "type": "string",
  "created_by": "string",
  "storage_ref": "string",
  "metadata": {}
}
```

---

## 3.5 MainAgentDecision

```json
{
  "action_type": "plan_review | execute | ask_user | final_response | fail",
  "target": "plan_review | execution | null",
  "reason": "string",
  "input_ref": "string | null",
  "message": "string | null",
  "should_continue": true
}
```

---

## 3.6 PlanReviewResult

```json
{
  "result_id": "string",
  "status": "success | blocked | failed",

  "plan": {},

  "plan_delta": {
    "updated_phase_statuses": [],
    "new_steps": [],
    "updated_steps": []
  },

  "review": {
    "progress_assessment": "on_track | blocked | completed | failed",
    "issues": ["string"],
    "missing_information": ["string"]
  },

  "recommended_next_action": {
    "action_type": "execute | ask_user | final_response | fail",
    "step_id": "string | null",
    "reason": "string"
  },

  "artifacts": []
}
```

---

## 3.7 ExecutionResult

```json
{
  "execution_id": "string",
  "status": "success | blocked | failed",
  "step_id": "string",
  "summary": "string",
  "produced_artifacts": [],
  "evidence_ids": ["string"],
  "needs_replan": true,
  "error": null
}
```

---

## 3.8 ScheduleSkillRequest

```json
{
  "request_id": "string",
  "operation": "list_availability | create_event | remove_event",
  "payload": {}
}
```

---

## 3.9 ScheduleSkillResult

```json
{
  "request_id": "string",
  "status": "success | blocked | failed",
  "summary": "string",
  "artifacts": [],
  "evidence_ids": ["string"],
  "tool_calls": [],
  "error": null
}
```

---

# 4. Plan Delta

## Definition

`plan_delta` = minimal diff applied to the plan

## Example

```json
{
  "plan_delta": {
    "updated_phase_statuses": [
      { "phase_id": "phase_2", "status": "done" }
    ],
    "new_steps": [
      {
        "step_id": "step_002",
        "instruction": "Create event",
        "status": "pending"
      }
    ],
    "updated_steps": [
      {
        "step_id": "step_001",
        "status": "done"
      }
    ]
  }
}
```

---

# 5. Progress Assessment

## Types

| Value        | Meaning |
|-------------|--------|
| on_track     | normal progression |
| blocked      | needs input or constraint |
| completed    | goal achieved |
| failed       | unrecoverable |

## Example

```json
{
  "progress_assessment": "blocked",
  "issues": ["No available slots"],
  "missing_information": ["new time preference"]
}
```

---

# 6. Snapshot System

## Purpose

- recovery
- stateless workers
- durability
- replay/debugging

---

## 6.1 Snapshot Schema

```json
{
  "snapshot_id": "string",
  "run_id": "string",
  "version": 1,
  "created_at": "ISO",
  "status": "running",

  "run_state": {},
  "plan": {},
  "artifact_refs": [],

  "pending_action": {
    "action_type": "execute",
    "request_id": "string",
    "dispatched": true,
    "idempotency_key": "string"
  },

  "recovery": {
    "retry_count": 0,
    "max_retries": 3,
    "last_error": null,
    "recovery_policy": "retry_pending_action"
  }
}
```

---

## 6.2 Snapshot Lifecycle

```text
1. Load snapshot
2. Decide next action
3. Save snapshot (pre-dispatch)
4. Dispatch action
5. Save snapshot (post-dispatch)
6. Receive result
7. Commit state
8. Save snapshot (post-commit)
```

---

## 6.3 Pending Action Example

```json
{
  "pending_action": {
    "action_type": "execute",
    "request_id": "exec_002",
    "dispatched": true,
    "idempotency_key": "run_001_step_002_try_1"
  }
}
```

---

# 7. Event Log

Append-only log of transitions.

```json
{
  "event_id": "string",
  "run_id": "string",
  "sequence": 12,
  "actor": "main_agent",
  "action_type": "execute",
  "status": "success",
  "input_ref": "string",
  "output_ref": "string",
  "created_at": "ISO"
}
```

---

# 8. Database Model

## runs
```text
run_id
status
current_snapshot_id
created_at
updated_at
```

## snapshots
```text
snapshot_id
run_id
version
payload_json
created_at
```

## events
```text
event_id
run_id
sequence
payload_json
created_at
```

## operations
```text
operation_id
run_id
step_id
type
idempotency_key
status
request_payload
response_payload
```

## artifacts
```text
artifact_id
run_id
type
storage_ref
metadata
```

---

# 9. Execution Rules

## MainAgent

- call plan_review if:
  - no plan
  - state changed
- call execution if:
  - step ready
- ask_user if:
  - blocked
- final_response if:
  - completed

---

## PlanReview

- build plan
- update statuses
- generate next step
- detect blockers

---

## Execution

- execute ONE step
- use skills/tools
- return result only
- do not replan

---

## ScheduleSkill

- map step → tool calls
- validate input
- return structured result

---

# 10. Recovery Logic

## Resume Algorithm

```text
1. load latest snapshot
2. check lifecycle_state

if pending_action.dispatched = false:
    dispatch

if pending_action.dispatched = true:
    reconcile or retry

if no pending_action:
    continue normal loop
```

---

# 11. Idempotency

Every external operation must include:

```text
idempotency_key = run_id + step_id + attempt
```

Used for:
- safe retries
- duplicate prevention
- reconciliation

---

# 12. Minimal Implementation Scope (v1)

## Required

- MainAgent loop
- PlanReview component
- Execution component
- ScheduleSkill
- Snapshot persistence
- Event log
- Basic retry logic

## Not required yet

- multi-agent concurrency
- DAG execution
- streaming reasoning
- delta snapshots
- complex policies

---

# 13. Mental Model

```text
MainAgent = control
PlanReview = thinking
Execution = doing
Skill = translating
Tool = acting
Snapshot = memory
```

---

# 14. Key Principles

- Separate planning from execution
- Keep steps small and executable
- Always snapshot before/after actions
- Never trust implicit state
- Use structured outputs everywhere
- Treat recovery as a first-class concern

---

# END