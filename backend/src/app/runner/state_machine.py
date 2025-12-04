"""
Execution state machine for tracking and visualizing graph execution.

Supports:
- Node state tracking
- Transition logging
- Export to visualization formats (Mermaid, Graphviz, D3)
- Replay capability
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class NodeState(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StateTransition:
    """Record of a state transition."""
    node_id: str
    from_state: NodeState
    to_state: NodeState
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExecutionStateMachine:
    """
    Tracks execution state of graph nodes.
    
    Provides:
    - State management for each node
    - Transition history
    - Export to visualization formats
    """
    
    def __init__(self):
        self.nodes: Dict[str, NodeState] = {}
        self.transitions: List[StateTransition] = []
        self.edges: List[tuple] = []
    
    def add_node(self, node_id: str, initial_state: NodeState = NodeState.PENDING):
        """Add a node to the state machine."""
        self.nodes[node_id] = initial_state
        self.transitions.append(StateTransition(
            node_id=node_id,
            from_state=NodeState.PENDING,
            to_state=initial_state,
            metadata={"event": "initialized"}
        ))
    
    def add_edge(self, from_node: str, to_node: str):
        """Add an edge between nodes."""
        self.edges.append((from_node, to_node))
    
    def transition(
        self, 
        node_id: str, 
        new_state: NodeState, 
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Transition a node to a new state."""
        if node_id not in self.nodes:
            self.add_node(node_id)
        
        old_state = self.nodes[node_id]
        self.nodes[node_id] = new_state
        
        self.transitions.append(StateTransition(
            node_id=node_id,
            from_state=old_state,
            to_state=new_state,
            metadata=metadata or {}
        ))
    
    def get_state(self, node_id: str) -> Optional[NodeState]:
        """Get current state of a node."""
        return self.nodes.get(node_id)
    
    def get_all_states(self) -> Dict[str, str]:
        """Get current state of all nodes."""
        return {k: v.value for k, v in self.nodes.items()}
    
    def get_transitions(self, node_id: Optional[str] = None) -> List[StateTransition]:
        """Get transition history, optionally filtered by node."""
        if node_id:
            return [t for t in self.transitions if t.node_id == node_id]
        return self.transitions
    
    def to_mermaid(self, title: str = "Execution Graph") -> str:
        """
        Export to Mermaid diagram format.
        
        Returns:
            Mermaid diagram string
        """
        lines = [f"flowchart TD"]
        lines.append(f"    subgraph {title}")
        
        # Add nodes with state-based styling
        state_styles = {
            NodeState.PENDING: "fill:#gray",
            NodeState.READY: "fill:#yellow",
            NodeState.RUNNING: "fill:#blue",
            NodeState.COMPLETED: "fill:#green",
            NodeState.FAILED: "fill:#red",
            NodeState.SKIPPED: "fill:#orange",
        }
        
        for node_id, state in self.nodes.items():
            safe_id = node_id.replace("-", "_")
            style_class = state.value
            lines.append(f"    {safe_id}[{node_id}]:::{style_class}")
        
        # Add edges
        for from_node, to_node in self.edges:
            safe_from = from_node.replace("-", "_")
            safe_to = to_node.replace("-", "_")
            lines.append(f"    {safe_from} --> {safe_to}")
        
        lines.append("    end")
        
        # Add style definitions
        lines.append("")
        lines.append("    classDef pending fill:#9e9e9e,stroke:#757575")
        lines.append("    classDef ready fill:#ffeb3b,stroke:#fbc02d")
        lines.append("    classDef running fill:#2196f3,stroke:#1976d2,color:#fff")
        lines.append("    classDef completed fill:#4caf50,stroke:#388e3c,color:#fff")
        lines.append("    classDef failed fill:#f44336,stroke:#d32f2f,color:#fff")
        lines.append("    classDef skipped fill:#ff9800,stroke:#f57c00")
        
        return "\n".join(lines)
    
    def to_graphviz(self, title: str = "Execution Graph") -> str:
        """
        Export to Graphviz DOT format.
        
        Returns:
            DOT format string
        """
        lines = [f'digraph "{title}" {{']
        lines.append("    rankdir=TB;")
        lines.append("    node [shape=box, style=filled];")
        
        state_colors = {
            NodeState.PENDING: "#9e9e9e",
            NodeState.READY: "#ffeb3b",
            NodeState.RUNNING: "#2196f3",
            NodeState.COMPLETED: "#4caf50",
            NodeState.FAILED: "#f44336",
            NodeState.SKIPPED: "#ff9800",
        }
        
        # Add nodes
        for node_id, state in self.nodes.items():
            color = state_colors.get(state, "#gray")
            lines.append(f'    "{node_id}" [fillcolor="{color}", label="{node_id}\\n({state.value})"];')
        
        # Add edges
        for from_node, to_node in self.edges:
            lines.append(f'    "{from_node}" -> "{to_node}";')
        
        lines.append("}")
        
        return "\n".join(lines)
    
    def to_d3_json(self) -> Dict[str, Any]:
        """
        Export to D3.js compatible JSON format.
        
        Returns:
            Dictionary with nodes and links arrays
        """
        state_colors = {
            NodeState.PENDING: "#9e9e9e",
            NodeState.READY: "#ffeb3b",
            NodeState.RUNNING: "#2196f3",
            NodeState.COMPLETED: "#4caf50",
            NodeState.FAILED: "#f44336",
            NodeState.SKIPPED: "#ff9800",
        }
        
        nodes = []
        node_index = {}
        
        for i, (node_id, state) in enumerate(self.nodes.items()):
            node_index[node_id] = i
            nodes.append({
                "id": node_id,
                "index": i,
                "state": state.value,
                "color": state_colors.get(state, "#gray")
            })
        
        links = []
        for from_node, to_node in self.edges:
            if from_node in node_index and to_node in node_index:
                links.append({
                    "source": node_index[from_node],
                    "target": node_index[to_node]
                })
        
        return {
            "nodes": nodes,
            "links": links,
            "transitions": [
                {
                    "node_id": t.node_id,
                    "from_state": t.from_state.value,
                    "to_state": t.to_state.value,
                    "timestamp": t.timestamp,
                    "metadata": t.metadata
                }
                for t in self.transitions
            ]
        }
    
    def replay(self) -> List[Dict[str, Any]]:
        """
        Generate replay sequence for visualization.
        
        Returns:
            List of snapshots showing state at each transition
        """
        snapshots = []
        current_state = {}
        
        for transition in self.transitions:
            current_state[transition.node_id] = transition.to_state.value
            snapshots.append({
                "timestamp": transition.timestamp,
                "transition": {
                    "node_id": transition.node_id,
                    "from": transition.from_state.value,
                    "to": transition.to_state.value
                },
                "state": dict(current_state)
            })
        
        return snapshots
