# Orchestration Layer

# Skilled-Agents
    BaseSkill
        Capabilities (skills | Tools | Resposes)
        Orchestrators:
            Lean
                - AnalyserSkill (broader context [baseSkill + specificAnalyserSkill]) -> request Action
                - OrchestrationAction -> Analyse Skill 
            Standard (medim-complex tasks)
                - PlannerSkill -> ExecutionPlanWithSteps
                - ExecutorSkill -> IterateSteps -> Go to Planner.. 
            Pro
                - IntentParser (thinking)
                - Planner -> ExecutionSteps
                - ExecutorSkillStep -> results
                - Review (Q&A) -> Re-Plan or Respond
            Workflow:
                DAG_Execution
            CognitiveWorkflow: The workflow is just guidance, we can combine lean-strd-pro to really do the work

Memory
    Persistent
        Agent-scoped
            GeneralIdentity (definition)
            GeneralPreferences (memory)
        Skill-scoped
            Skill-Preference/precedure/beliefs-Memory - autoinjected per skill

    Retrieved:  by sim or tag (like a tool)
        episodes -> 
            **relevant** past events [time awarness is important here] - Something needs to triage that by relevance of summarize them. 
        records -> 
            mental node by the agent or user invoked - decides to fetch - Can be an Artifact like an (Notebook)

    Session-Scoped
        working-memory: current turn, current tool result
        recent exchenges: last n-turn or summary


---
```
You are an agent iada iada... 
Preferences: [permanent - guidelines]
    ...
Relevant Episodes Remebered: [permanent -  something learned about this topic]


History
    ToolsReuested: [state-scoped] [observed]
        ....

    Last Rounds (session history) [state-scoped] [observed]
        ...
        ...
        ...
    LastNotes - [permanent] [any-origin]
        ...


Current Task
    PLAN: [state-scoped] [observed]
        given the current input plan
        Last Plans -> results [state-scoped] [observed]
    
    current_input: ... 

    Outuput Options
        PlanWithSteps
        TODO
        Message()
        Capabilities()

    EXECUTION: step 2 / 3 | goal: do something...
        Last Execution
        Yet To Come
        TODO INFO

        current_input: ...

        Ouput Options:
            ExecutionResult
            Escalate()
            Capabilities()
 
```
---
Point: there's a lot of way to build this and the actual serialization depends on the Orchestrator, the way it handles the objects back and fouth. 

**Is there something in common?**
Everything that comes in should be a BaseEntry
```
class BaseEntry
{
    "ID": "entryID",
    "kind": "skill_preference | episode | mental_note ",
    "content": {
        format: "Any-text-format",
        text: "str",
        summary: opt
    } 
    "time_info" {},
    "tags": []
}
class Memory (BaseEntry)
{
    "origin": "observed | user_info | inferred | consolidate",

}
class Artifact(BaseEntry)
{
    version: number,
    "content": {
        format: "Any format",
        text: "serialized data (text-formated)
        summary: opt
        serializer(),
        data: real binary of any data format        
    }
    provenance: {
        source: "",
        "origin": "[MemoryOrigin]"
    }
}

SPLIT MEMORY AND ARTIFACT FROM BASE ENTRY
```
---

Artifacts: Anything produces that could leave outside the system. 


ExecutionState
    contextStore
        artifactStore
        MemoryStore
        snapshotStore
    session
        session_id
        snapshot_id
    state (snap_shoted)
        [autoinjected_stuff is not gonna lie here]
        episodes
        last_tool_request [Records, tool_call_results]
        last_exchanges[messages + executions (history)]
        current_running [working_memory]
            [currentPlan]
            [currentStep]
            current_turn
            last_data_produced


ContextRef
    IDS: list of ID's or names
    namespaced
        memory.name_of_memory
        artifact.name_of_artifact
        skill_ouput.object_name
        scalate.user_message


Skill ( Basic)
    ID
    name
    description
    whenToUse
    capabilities (tools)        
    InputSchema: schema, name, description [could be a list]
    OutputSchema: schema, name, description [could be a list]
    instructions
    contraints

    Execution
        the output is a object to be called [passed as function to the LLM]

Basic Cognitive Tools
    Notebook: for annotation, reminder, something like this...
    TODO: working todo in order to keed the plan streight

Productivity Tools
    GoogleCalendar
    GoogleDrive
    TextEditor

    


----


# => ORCH V. 01

**Memory**
Just what's needed to be permanet.. at the beggining, we might have just text..

- General Memory: User Memory, one day, cross-user memory too
- Skill Memory: kinda scoped memory for specific task. 
- Retrieved Memory: like a tool, record book... 
- Execution Memory: For now, just in the snapshot. Alterwards, the relevant part, just like how to do or solve some problem, might be stored. For now, you need to make them "record" in skill, user preference or in the notebook. 

**MemoryStore**: just record and retrieve Protocol for the Backend.

**Artifact**: Some defaults... available as tool

**State**: For now, snapshots. This is an object with the text passed and the reference in order to ask for the source and check it (as artifacts [capabilities that could be asked]): working memory (current and history), memories [injected] [passt executions and errors]. Here we need to design the state, it will depend on the "final prompt". This is a orchestration stuff.

**Orchs**
Analyze -> [ExecutionSteps] -> Act[Execution] -> Analyze (loop)
Each one is has its own prompts
Object desing... (gpt conversation... )

**Skills**: cell of capabilitie. Request available actions. Some day, the orchestration will be declarative. For now, the skill as instrucution will be Instruction part. We gonna insect the orchestration stuff, which will be the capabilities and other inject (contextual), including how to gerate the execution steps. (final prompt). Initially, I'm gonna split manually. 

types
    - simple: added in the main prompt in the next route
    - called: call as tool (it can be, sequence, paralell... ) (Self scoped, just return the result compressed)

**PrettyLogger =D**: Let's gooo.... 



=> Let's Build, from generics skills all that orchestration, define the state then all other stuff will be derived from that. 

# Scheduler ORCH
------
Intructions: You are a helpful agent bla bla... 
You have the following cabapilities:
- schedulerSkill: call this if you need to schedule events, task and other stuff which depends on record things in time. 
Do this to that, don't do iada iada... 


Reponses
{'capability_call': 'schedulerSkill', query: str}
{'response': 'str', evidences: [ev_id]}

...
Response: {'capability_call': 'schedulerSkill', query: str}
...

SchedulerSkill_Instructions: You are a scheduler helper. YOu do this and that... 

Tools:
{tool_call: 'schedule.list_event', args: {start_date, start_time, end_date, end_time, windows: 5}}
{tool_call: 'schedule.create_event', args: {start_date, start_time, end_date, end_time, name, desc, boo}}
{tool_call: 'schedule.remove_event(schedule_id)}

Current Execution
    - general_user_query
    - TODO:
        General Goal
        phases:
            -
            -
            -
    - CurrentQuery: Check the availablitiy of iada ida ida... 
    - LastExecution

LastSteps Ascending[]:
    ....
    ....
    ....
    call_more... 

Response:
    - tool_calls..
    - Message
    - callMoreStory
    - CallTodo
   

-----


# NEXT STEPS

- Read the conversation and get the main object/system design and create the version 01 for each object. 
- Write the Objects and the main idea, cause the Opus is gonna do the hard work for us.
- The object placeing must be done manually case I need to undestand it step by step.

- The orchestration is gonna make the transition and prepere the executions.
- The cognitive layer is gonna request actions.
- The orchestration is gonna check everything and build the execution on top of ExecutionPlatform.

-----

Orchestrator
- Receive the input
- Check (recovering) the state
- Send to the due state. 


---- Claude Code Inspiratio...
Anything I said I have a intent parser streammed. 
Then I decide to act [Capabilities]
Then Analyse the result and decide to act again.
Till the final answer. 


==> For the first
- Use capabilities along the way. ... but I'm not sure if plan is a first class stuff or just a capability... 


- When it cast a cababilitie... it spawn another thing, what for the result..

    Ex: I need to plan... cast PLAN_CAPABILITY... return a plan as state... [but the orchestrator should know it???]
        - check availability
        - 


SingleAnalyzer
    - GeneralInstruction
    - See Capabilities
        - tools
        - plan -- If it enters here... I'm in the plan mode.. so I'm in the loop
        - record... 
        - skills... 
    - Results: Answare[Message] | Ask_Clarification | Fail (Undecovable - It's not possible to make something cognitivetly... )



MainAgent[Single Analyzer]
- Input: UserMessage[message, artifacts_ref: [namespaces]]
- Outpus: final_answer[Message] | deep_thinking (for execution) | ask_clarification | fail (undecoverable)

DeepThinkingState
  - It sees 

PLAN - Think State
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
  "steps": [
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
  ],
  "success_criteria": ["string"],
  "assumptions": ["string"]
}

DeepThinkingResult
```json
{
  "result_id": "string",
  "status": "success | blocked | failed",

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

  "artifacts": [
    {
    "artifact_id": "string",
    "type": "string",
    "created_by": "string",
    "storage_ref": "string",
    "metadata": {}
    }
  ]
}
```
===> High Level

AutoAgent(Orchestrator)
    - ReceiverSkill: role agent...
    - Capabilities: [capability]
        -> Skill | Tool.. | Workflow... (autocontido... )
            -> PlanReview is a Skill [firstClass Citizen...]... [Use it when the task envolves many steps...]
               [Intent] -> PlanReview [ExecutionPlan] ([ExecutionSteo]) -> PlanReview 
    - Review [Results...]

- If someone scalate: The orchestrator save the snapshot and the message goes to the requester.
- If user steer: Just in the PlanReviewMode -> works like a scalator (requested by the user then the orchestrator send it to the PlanReviewAgent)

BaseCapability[Protocol]
BaseSkillModel[BaseCapability]
Tool[BaseCapability] -> This is a regular function
Workflow[BaseCapability]
PlanReview[BaseCapability]
Recorder[BaseCapability]


It can be a capability for between them... 

BaseCapability
    - ID
    - name
    - description
    - when_to_use
    - Instructions
    - Input
    - Outputs | Escalate | Fail
    - register_execution_graph() -> ExecutionGraph
    - get_memory()
    - set_memory()


ExecutionGraph Examples:
    PlanReviewSkill
        add[PlanReview, END]
        add[PlanReview, Execute]
        add[Execute, PlanReview]

    Recorder
        add[RecorderAction, END]

ExeutionNodes
    TEXT_NODE (LLM_config) [str, stream[str]]
    OBJECT_NODE (LLM_config) [obj]
    FUNCTION [obj]
    WORKFLOW_ACTION[]



State:
    ...



ArtifactStore [Everything produces and that's ]
    ... control idempotent... check
    


        
The way it is, given I'm in a node, I know where to go. 
I can save the snapshot of the current State, I can Easily resume.
The execution Become Flat... I can Apply idempotent right the way... 



                    














