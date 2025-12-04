"""
Core graph execution engine for multi-agent behavioral testing.

Supports:
- Deterministic seed-controlled execution
- Contract validation between agent nodes
- Latency tracking and cost accounting
- Behavior replay capability
- State machine visualization export
"""

import json
import yaml
import time
import uuid
import hashlib
import random
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime
from enum import Enum

from .assertions import AssertionEngine, AssertionResult
from .contracts import ContractValidator, ContractViolation
from .state_machine import ExecutionStateMachine, NodeState
from app.governance import GovernanceMiddleware, SafetyScore
from app.providers.router import ProviderRouter


class ExecutionMode(Enum):
    NORMAL = "normal"
    REPLAY = "replay"
    CHAOS = "chaos"
    DEBUG = "debug"
    SIMULATION = "simulation"


@dataclass
class AgentOutput:
    """Captured output from an agent node execution."""
    node_id: str
    agent_type: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    latency_ms: float
    cost_usd: float
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str = "mock"
    model: str = "mock-model"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ExecutionTrace:
    """Full execution trace for a graph run."""
    run_id: str
    graph_id: str
    graph_hash: str
    mode: ExecutionMode
    seed: Optional[int]
    started_at: str
    completed_at: Optional[str]
    agent_outputs: List[AgentOutput] = field(default_factory=list)
    assertion_results: List[AssertionResult] = field(default_factory=list)
    contract_violations: List[ContractViolation] = field(default_factory=list)
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    status: str = "pending"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace to serializable dictionary."""
        return {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_hash": self.graph_hash,
            "mode": self.mode.value,
            "seed": self.seed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "agent_outputs": [asdict(o) for o in self.agent_outputs],
            "assertion_results": [asdict(r) for r in self.assertion_results],
            "contract_violations": [asdict(v) for v in self.contract_violations],
            "total_latency_ms": self.total_latency_ms,
            "total_cost_usd": self.total_cost_usd,
            "status": self.status,
            "error": self.error
        }


class GraphRunner:
    """
    Core execution engine for behavioral test graphs.
    
    Features:
    - Topological execution ordering
    - Contract enforcement between nodes
    - Behavioral assertion evaluation
    - Metrics collection (latency, cost, tokens)
    - Determinism through seed control
    - Full execution tracing for replay
    """
    
    def __init__(
        self,
        provider_registry=None,
        provider_router: Optional[ProviderRouter] = None,
        assertion_engine: Optional[AssertionEngine] = None,
        contract_validator: Optional[ContractValidator] = None,
        seed: Optional[int] = None,
        mode: ExecutionMode = ExecutionMode.NORMAL,
        chaos_config: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
        governance: Optional[GovernanceMiddleware] = None,
        governance_enabled: bool = True,
    ):
        self.provider_registry = provider_registry
        self.provider_router = provider_router
        self.assertion_engine = assertion_engine or AssertionEngine()
        self.contract_validator = contract_validator or ContractValidator()
        self.seed = seed
        self.mode = mode
        self.chaos_config = chaos_config or {}
        self.state_machine = ExecutionStateMachine()
        self.timeout_seconds = timeout_seconds
        self.governance = governance
        self.governance_enabled = governance_enabled
        self._random = random.Random(seed) if seed is not None else random.Random()
        if seed is not None:
            random.seed(seed)

    def _governance_active(self) -> bool:
        return bool(self.governance and self.governance_enabled)

    @staticmethod
    def _score_to_dict(score: SafetyScore) -> Dict[str, Any]:
        return {
            "overall": round(score.overall_score, 3),
            "pii": round(score.pii_score, 3),
            "policy": round(score.policy_score, 3),
            "toxicity": round(score.toxicity_score, 3),
            "detections": len(score.detections),
            "violations": len(score.violations),
        }

    def _govern_input(self, node_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self._governance_active():
            return {}
        payload = json.dumps({"node": node_id, "input": input_data})
        try:
            processed, score = self.governance.process_input(payload)
        except ValueError as exc:
            raise RuntimeError(f"Governance blocked input for node {node_id}: {exc}") from exc
        metadata = {"input_score": self._score_to_dict(score)}
        if processed != payload:
            metadata["input_preview"] = processed[:256]
        return metadata

    def _govern_output(self, node_id: str, output_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self._governance_active():
            return {}
        response_text = output_data.get("response")
        if not isinstance(response_text, str):
            return {}
        try:
            sanitized, score = self.governance.process_output(response_text)
        except ValueError as exc:
            raise RuntimeError(f"Governance blocked output for node {node_id}: {exc}") from exc
        output_data["response"] = sanitized
        metadata = {"output_score": self._score_to_dict(score)}
        if sanitized != response_text:
            metadata["output_preview"] = sanitized[:256]
        return metadata
        
    def _compute_graph_hash(self, graph: Dict[str, Any]) -> str:
        """Compute deterministic hash for graph versioning."""
        content = yaml.dump(graph, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _topological_sort(self, nodes: List[Dict], edges: List[Dict]) -> List[str]:
        """Sort nodes in execution order respecting dependencies."""
        from collections import defaultdict, deque
        
        # Build adjacency list and in-degree count
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        node_ids = {n["id"] for n in nodes}
        
        for node_id in node_ids:
            in_degree[node_id] = 0
            
        for edge in edges:
            src, dst = edge["from"], edge["to"]
            graph[src].append(dst)
            in_degree[dst] += 1
        
        # Kahn's algorithm
        queue = deque([n for n in node_ids if in_degree[n] == 0])
        result = []
        
        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        if len(result) != len(node_ids):
            raise ValueError("Graph contains cycles - cannot execute")
            
        return result
    
    def _execute_node(
        self,
        node: Dict[str, Any],
        context: Dict[str, Any],
        trace: ExecutionTrace
    ) -> AgentOutput:
        """Execute a single agent node."""
        node_id = node["id"]
        agent_type = node.get("type", "mock")
        config = node.get("config", {})
        
        self.state_machine.transition(node_id, NodeState.RUNNING)
        
        start_time = time.perf_counter()
        
        governance_meta = {}
        try:
            # Get input from context (outputs of predecessor nodes)
            input_data = {}
            for dep in node.get("inputs", []):
                if dep in context:
                    input_data[dep] = context[dep]

            governance_meta.update(self._govern_input(node_id, input_data))
            
            # Inject chaos if in chaos mode
            if self.mode == ExecutionMode.CHAOS:
                input_data = self._inject_chaos(input_data)
            
            # Execute through provider (mock for now)
            output_data = self._execute_agent(
                agent_type=agent_type,
                config=config,
                input_data=input_data
            )

            governance_meta.update(self._govern_output(node_id, output_data))
            if governance_meta:
                output_data.setdefault("_governance", {}).update(governance_meta)
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            # Create output record
            agent_output = AgentOutput(
                node_id=node_id,
                agent_type=agent_type,
                input_data=input_data,
                output_data=output_data,
                latency_ms=elapsed_ms,
                cost_usd=self._estimate_cost(agent_type, output_data),
                tokens_in=output_data.get("_tokens_in", 0),
                tokens_out=output_data.get("_tokens_out", 0),
                provider=config.get("provider", "mock"),
                model=config.get("model", "mock-model")
            )
            
            self.state_machine.transition(node_id, NodeState.COMPLETED)
            return agent_output
            
        except Exception as e:
            self.state_machine.transition(node_id, NodeState.FAILED)
            raise
    
    def _execute_agent(
        self,
        agent_type: str,
        config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute agent through provider registry or mock."""
        if self.provider_registry:
            provider_name = config.get("provider")
            if self.provider_router:
                provider_name = self.provider_router.resolve(node_config=config, agent_type=agent_type)
            if not provider_name:
                provider_name = "openai"
            provider = self.provider_registry.get_provider(provider_name)
            return provider.execute(agent_type, config, input_data)
        
        # Mock execution for testing
        return {
            "response": f"Mock response for {agent_type}",
            "confidence": 0.95,
            "_tokens_in": len(str(input_data)) // 4,
            "_tokens_out": 50,
            "_seed": self.seed,
        }
    
    def _inject_chaos(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Inject chaos for testing resilience."""
        rng = self._random
        
        if rng.random() < self.chaos_config.get("drop_rate", 0.1):
            keys = list(input_data.keys())
            if keys:
                del input_data[rng.choice(keys)]
        
        if rng.random() < self.chaos_config.get("corrupt_rate", 0.05):
            keys = list(input_data.keys())
            if keys:
                key = rng.choice(keys)
                input_data[key] = "CORRUPTED_VALUE"
        
        return input_data
    
    def _estimate_cost(self, agent_type: str, output: Dict[str, Any]) -> float:
        """Estimate execution cost based on token usage."""
        tokens_in = output.get("_tokens_in", 0)
        tokens_out = output.get("_tokens_out", 0)
        
        # Default pricing (can be configured per provider)
        cost_per_1k_in = 0.001
        cost_per_1k_out = 0.002
        
        return (tokens_in * cost_per_1k_in + tokens_out * cost_per_1k_out) / 1000
    
    def run(self, graph: Dict[str, Any]) -> ExecutionTrace:
        """
        Execute a behavioral test graph.
        
        Args:
            graph: Graph definition with nodes, edges, assertions, contracts
            
        Returns:
            ExecutionTrace with full results and metrics
        """
        run_id = str(uuid.uuid4())
        graph_id = graph.get("id", "unknown")
        graph_hash = self._compute_graph_hash(graph)
        
        trace = ExecutionTrace(
            run_id=run_id,
            graph_id=graph_id,
            graph_hash=graph_hash,
            mode=self.mode,
            seed=self.seed,
            started_at=datetime.now(UTC).isoformat()
        )
        
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        assertions = graph.get("assertions", [])
        contracts = graph.get("contracts", [])
        
        # Initialize state machine
        for node in nodes:
            self.state_machine.add_node(node["id"])
        
        try:
            # Get execution order
            execution_order = self._topological_sort(nodes, edges)
            node_map = {n["id"]: n for n in nodes}
            
            # Execute nodes in order
            context = {}
            total_start = time.perf_counter()
            
            for node_id in execution_order:
                if (
                    self.timeout_seconds
                    and (time.perf_counter() - total_start) > self.timeout_seconds
                ):
                    raise TimeoutError(
                        f"Execution exceeded timeout of {self.timeout_seconds} seconds"
                    )
                node = node_map[node_id]
                
                # Validate input contracts
                for contract in contracts:
                    if contract.get("target") == node_id:
                        violations = self.contract_validator.validate_input(
                            contract, context
                        )
                        trace.contract_violations.extend(violations)
                
                # Execute node
                output = self._execute_node(node, context, trace)
                trace.agent_outputs.append(output)
                context[node_id] = output.output_data
                
                # Validate output contracts
                for contract in contracts:
                    if contract.get("source") == node_id:
                        violations = self.contract_validator.validate_output(
                            contract, output.output_data
                        )
                        trace.contract_violations.extend(violations)
            
            # Calculate totals
            trace.total_latency_ms = (time.perf_counter() - total_start) * 1000
            trace.total_cost_usd = sum(o.cost_usd for o in trace.agent_outputs)
            
            # Run assertions
            trace.assertion_results = self.assertion_engine.evaluate(
                assertions, context, trace.agent_outputs
            )
            
            # Determine final status
            all_passed = all(r.passed for r in trace.assertion_results)
            no_violations = len(trace.contract_violations) == 0
            
            trace.status = "passed" if (all_passed and no_violations) else "failed"
            trace.completed_at = datetime.now(UTC).isoformat()
            
        except Exception as e:
            trace.status = "error"
            trace.error = str(e)
            trace.completed_at = datetime.now(UTC).isoformat()
        
        return trace


def run_graph(graph_path: str, **kwargs) -> Dict[str, Any]:
    """
    Execute a graph from a YAML file path.
    
    Args:
        graph_path: Path to YAML graph definition
        **kwargs: Additional arguments for GraphRunner
        
    Returns:
        Dictionary with execution results
    """
    with open(graph_path, "r") as f:
        graph = yaml.safe_load(f)
    
    runner = GraphRunner(**kwargs)
    trace = runner.run(graph)
    
    # Return summary for backward compatibility
    return {
        "run_id": trace.run_id,
        "status": trace.status,
        "assertions": [asdict(r) for r in trace.assertion_results],
        "contract_violations": [asdict(v) for v in trace.contract_violations],
        "latency_p95": trace.total_latency_ms,
        "cost_total": trace.total_cost_usd,
        "agent_outputs": [asdict(o) for o in trace.agent_outputs],
        "trace": trace.to_dict()
    }
