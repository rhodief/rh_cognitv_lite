# Orchestration Layer

Node
    CognitiveNodes = TextNode, DataNode, FunctionNode, ToolNode(DATA + function) # 
    FlowNodes = forEach
    NodeGroup = SubDag of (CognitiveNodes + FlowNodes)


DAG = PlanDag(
    nodes: [Nodes | PlanDag]
    edges: [Edges]
)

DAG = (PlanDAGBuilder(name, configs)
        .node(N)
        .node(S)
        .edge(N,S) # then edge is casted, the nodes must be added before.
        .group(
            subdag=(
                PlanDAGBuilder(subname, configs (optional, it could inhirit))
                    .node(L)
                    .node(V)
                    .edge(L, V)
            )

        )
)


