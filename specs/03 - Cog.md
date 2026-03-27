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
        General
            GeneralIdentity
            GeneralPreferences
        Skill-scoped
            Skill-Preference/precedure/beliefs-Memory - autoinjected per skill

    Retrieved by sim or tag
        episodes -> **relevant** past events [time awarness is important here] - Something needs to triage that by relevance of summarize them. 
        records -> mental node by the agent or user invoked - decides to fetch - Can be an Artifact like an (Notebook)

    Session-Scoped
        working-memory: current turn, current tool result
        recent exchenges: last n-turn or summary

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

ContextRef
    IDS: list of ID's or names
    namespaced
        memory.name_of_memory
        artifact.name_of_artifact
        skill_ouput.object_name
        scalate.user_message


Basic Cognitive Tools
    Notebook: for annotation, reminder, something like this...
    TODO: working todo in order to keed the plan streight

Productivity Tools
    GoogleCalendar
    GoogleDrive
    TextEditor

    


