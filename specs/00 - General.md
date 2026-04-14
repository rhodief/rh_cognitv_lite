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

**Orchs**
Analyze -> [ExecutionSteps] -> Act[Execution] -> Analyze (loop)

**Skills**: cell of capabilitie. Request available actions. Some day, the orchestration will be declarative. For now, the skill as instrucution will be Instruction part. We gonna insect the orchestration stuff, which will be the capabilities and other inject (contextual), including how to gerate the execution steps. (final prompt). Initially, I'm gonna split manually. 





