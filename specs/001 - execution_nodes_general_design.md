# Cognitive Layer

BaseCapability(BaseModel)
    - ID: (str, capability ID. It might be namespaced)
    - name: Friendly Name
    - description: what the capability does, used to be exposed for LLM in order for it to take decisions
    - when_to_use: Also exposed to the main LLM in order for it to take decisons
    - Input: JsonSchema for the input
    - Outputs: Response[JsonSchema] | Escalate[When the capability information from the parenbt] | Fail[Unrecoverable Error]
    - register_execution_graph() -> ExecutionGraph

BaseSkill[BaseCapability]
    - instructon
    - LMM Configs
    

BaseTool[BaseCapability]
    - handler: actual function to be called

BaseWorkflow[BaseCapability]
    ... the register gets a subgraph, which the Nodes for the workflow

PlanReview[BaseSkill]
    ... The graphs are
        PlanReviewGraph[Skill.ObjectNode] -> LoopGraph.forEach(ExecutionStep, ExecutionGraph[Skill.ObjectNode]) -> PlanReviewGraph [Cyclic]



# Orchestration Layer

ExecutionGraph
    '''
    This is handle the actual cognitive execution for the nodes, works like execution map, and holds all the configs need for the execution, using the exectuion_platform
    In the beginning there are 3 Execution Nodes types
        - TextNode: represent the LLM execution (carry the LLM request params) for text of text streaming
        - ObjectNode: represent the LLM execution (carry the LLM request params) for tool calling in order to have fullfilled. If the validation fails, it should trigger the retry (see execution plataform consideration below)
        - FunctionNode: represent a predefined function available in the orchestration

    - In the future we might other types, but for now it might be enough for the most executions. 
    - The ExecutionGraph must convert the ExecutionNodes into graph nodes and build them and store the rest of metadata and configs in a separeted structure which is should be retrieved by ID (I must be able to retrive the complete ExecutionNode from the ExecutionGraph based on state)
    - The ExecutionGraph should be serializable (using pydantic) and restorable. 
    - The ExecutinGraph will not hold the execution state other than roles for the graph itself, the owner of the execution graph will hold this. 
    - The Execution Graph will not validate conditions for transition, the holder of it will do. The owner will just required a execution node based on ID or navigate through them, and maybe write metadata on some nodes, or adding or remove nodes (I'm not sure about remove, it might be userful a append only, in this case a copy for some parts of the graph should be userful)

Orchestrator
    - It will tie everything together.
    - It's gonna receive as paramter the State[interface which holds a specific StateBackend], ExecutionPlatform
    - It will have a receiver (a skill receiver, it's the Agent itself which gonna have capabilities)
    - It will build the executionGraph based on available Capabilities
    - It will hold the state
    - It will write and recover snapshots (User State Object)
    - It will get Execution Nodes from ExecutionGraph based on the execution state progression
    - It will validate the execution (permissions, policies etc...)
    - It will create the execution using the ExecutionPlatform [It's gonna have a adapter do build the Execution]
    - It will execute that, get the result, store it in the state
    - Get all requirements for injection for each Execution
    - Set the execution configs based on the ExecutionNodes

    In other words, it's gonna connect the cognitive layer (Capabilities stuff: skills, tools, PlanReviewSkill, Workflows, Recorder(I notebook for annotations) etc...) to execution_plataform based on serializable state control

    The events used on Execution Platform Event Bus is, for now, just for log and register, not for distributed execution, in the future it will be but now worries about it for now. The results of the execution (the execution history) will be held by the orchestrator


General Design Guides
- Everything should be built upon dependency inversion, all specific implementation should come as param through a contract.
- Orchestrator owns the execution. it ties together all the application contracts, but external implementation should be outside as adapter (the real backend)
- The orchestrator, based on cognitive definitions (capabilities), is gonna create the ExecutionGraph and control its state. The executionGraph is gonna create the respective execution based on ExecutionPlatform.
- The main layers which is cognitive, execution_platform and orchestrators should be separated, with adapter that ties them together. 

    
    
    
