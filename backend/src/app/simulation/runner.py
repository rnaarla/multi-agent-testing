"""High-level simulation runner that coordinates agents and environment."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

from app.database import SessionLocal
from app.providers import ProviderRegistry, ProviderConfig, provider_registry
from app.providers.router import ProviderRouter

from .agents import (
    AgentBase,
    AgentContext,
    AgentObservation,
    AgentAction,
    AgentMessage,
    RuleBasedAgent,
    LLMAgent,
)
from .environment import Environment
from .llm import LLMDecisionEngine
from .storage import SimulationEventStream, SimulationPersistence


@dataclass
class AgentSpec:
    agent_id: str
    agent_type: str
    implementation: str
    config: Dict[str, Any] = field(default_factory=dict)
    personality: Dict[str, Any] = field(default_factory=dict)
    tags: Sequence[str] = field(default_factory=list)


@dataclass
class SimulationSpec:
    name: str
    scenario: str
    tenant_id: str
    created_by: Optional[int]
    environment: Dict[str, Any]
    agents: Sequence[AgentSpec]
    steps: int = 10
    metadata: Dict[str, Any] = field(default_factory=dict)


class SimulationRunner:
    """Coordinates agents, environment, Redis stream, and persistence."""

    def __init__(
        self,
        *,
        redis_url: str,
        registry: Optional[ProviderRegistry] = None,
        router: Optional[ProviderRouter] = None,
        persistence: Optional[SimulationPersistence] = None,
    ):
        self.redis_stream = SimulationEventStream(redis_url=redis_url)
        self.persistence = persistence or SimulationPersistence()
        self.registry = registry or provider_registry
        self.router = router
        self.decision_engine = LLMDecisionEngine(self.registry, router=self.router)
        if not self.registry.providers:
            self.registry.register("mock", ProviderConfig(name="mock"))

    def run(self, spec: SimulationSpec) -> Dict[str, Any]:
        run_record = self.persistence.create_run(
            name=spec.name,
            scenario=spec.scenario,
            tenant_id=spec.tenant_id,
            created_by=spec.created_by,
            config={
                "agents": [agent.__dict__ for agent in spec.agents],
                "environment": spec.environment,
                "metadata": spec.metadata,
                "steps": spec.steps,
            },
        )

        env_config = spec.environment.get("config", {})
        env_initial_state = spec.environment.get("state", {})
        environment = Environment(initial_state=env_initial_state, config=env_config)

        agents = self._instantiate_agents(spec.agents)
        inboxes: Dict[str, List[AgentMessage]] = defaultdict(list)

        last_completed_timestep = -1
        try:
            with SessionLocal() as session:
                for step in range(spec.steps):
                    for agent_id, agent in agents.items():
                        observation = agent.observe(
                            state=environment.state,
                            timestep=step,
                            messages=inboxes.pop(agent_id, []),
                        )
                        action = agent.decide(observation)
                        new_state, outcome = environment.step(step, agent_id, action)

                        event_id = self.persistence.log_event_with_session(
                            session=session,
                            run_id=run_record.run_id,
                            step_index=step,
                            agent_id=agent_id,
                            event_type="agent_action",
                            payload=outcome,
                        )

                        # Queue messages for recipients
                        for message in action.messages:
                            if message.recipient_id:
                                inboxes[message.recipient_id].append(message)
                            else:
                                # Broadcast to all except sender
                                for target_id in agents.keys():
                                    if target_id != agent_id:
                                        inboxes[target_id].append(message)

                        # Persist agent state & publish to Redis
                        agent.update_state(observation, outcome)
                        session.flush()
                        self.persistence.upsert_agent_state(
                            session=session,
                            run_id=run_record.run_id,
                            agent_id=agent_id,
                            agent_type=agent.context.agent_type,
                            state=agent.serialize_state(),
                            last_event_id=event_id,
                        )
                        session.commit()

                        redis_event = {
                            "run_id": run_record.run_id,
                            "step_index": step,
                            "agent_id": agent_id,
                            "event": outcome,
                        }
                        self.redis_stream.append(run_record.run_id, redis_event)

                    last_completed_timestep = step

                self.persistence.complete_run(run_record.run_id, status="completed", steps=spec.steps)

            return {
                "run_id": run_record.run_id,
                "redis_stream": run_record.redis_stream_key,
                "status": "completed",
                "steps": spec.steps,
            }
        except Exception:
            partial_steps = max(0, last_completed_timestep + 1)
            self.persistence.complete_run(run_record.run_id, status="failed", steps=partial_steps)
            raise

    def _instantiate_agents(self, agent_specs: Sequence[AgentSpec]) -> Dict[str, AgentBase]:
        agents: Dict[str, AgentBase] = {}
        for spec in agent_specs:
            context = AgentContext(
                agent_id=spec.agent_id,
                agent_type=spec.agent_type,
                memory={},
                personality=spec.personality,
                tags=spec.tags,
            )

            implementation = spec.implementation.lower()
            if implementation in {"rule", "rule_based"}:
                agents[spec.agent_id] = RuleBasedAgent(context, spec.config)
            elif implementation in {"llm", "provider"}:
                agents[spec.agent_id] = LLMAgent(context, spec.config, self.decision_engine)
            else:
                raise ValueError(f"Unknown agent implementation: {spec.implementation}")

        return agents

