"""Agent abstractions used by the simulation engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

from .environment import EnvironmentState

if TYPE_CHECKING:
    from .llm import LLMDecisionEngine


@dataclass
class AgentMessage:
    """Represents a message exchanged between agents."""

    sender_id: str
    recipient_id: Optional[str]
    content: Dict[str, Any]
    channel: str = "default"


@dataclass
class AgentObservation:
    """Snapshot of the world presented to an agent."""

    state: EnvironmentState
    timestep: int
    incoming_messages: List[AgentMessage] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentAction:
    """Action emitted by an agent."""

    action_type: str
    payload: Dict[str, Any]
    messages: List[AgentMessage] = field(default_factory=list)
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Persistent state for agents between timesteps."""

    agent_id: str
    agent_type: str
    memory: Dict[str, Any] = field(default_factory=dict)
    personality: Dict[str, Any] = field(default_factory=dict)
    tags: Iterable[str] = field(default_factory=list)


class AgentBase(ABC):
    """Abstract agent definition used by the simulation runner."""

    def __init__(self, context: AgentContext, config: Dict[str, Any]):
        self.context = context
        self.config = config

    @abstractmethod
    def observe(self, state: EnvironmentState, timestep: int, messages: List[AgentMessage]) -> AgentObservation:
        """Transform the environment state into an observation."""

    @abstractmethod
    def decide(self, observation: AgentObservation) -> AgentAction:
        """Produce an action from a given observation."""

    def receive_message(self, message: AgentMessage) -> None:
        """Hook for asynchronous messages injected outside the main loop."""

    def update_state(self, observation: AgentObservation, outcome: Dict[str, Any]) -> None:
        """Update agent memory after the environment applies an action."""
        self.context.memory.setdefault("history", []).append(
            {
                "timestep": observation.timestep,
                "action": outcome.get("action"),
                "result": outcome.get("result"),
            }
        )

    def serialize_state(self) -> Dict[str, Any]:
        """Return the serialisable agent state for persistence."""
        return {
            "memory": self.context.memory,
            "personality": self.context.personality,
            "tags": list(self.context.tags),
            "config": self.config,
        }


class RuleBasedAgent(AgentBase):
    """Simple rule-based agent driven by decision tables."""

    def observe(self, state: EnvironmentState, timestep: int, messages: List[AgentMessage]) -> AgentObservation:
        return AgentObservation(
            state=state.clone(),
            timestep=timestep,
            incoming_messages=messages,
            context={"agent_memory": self.context.memory},
        )

    def decide(self, observation: AgentObservation) -> AgentAction:
        rules = self.config.get("rules", [])
        for rule in rules:
            conditions = rule.get("when", {})
            if all(observation.state.data.get(k) == v for k, v in conditions.items()):
                action = rule.get("action", {})
                messages = [
                    AgentMessage(
                        sender_id=self.context.agent_id,
                        recipient_id=msg.get("to"),
                        content=msg.get("content", {}),
                        channel=msg.get("channel", "default"),
                    )
                    for msg in rule.get("messages", [])
                ]
                return AgentAction(
                    action_type=action.get("type", "noop"),
                    payload=action.get("payload", {}),
                    messages=messages,
                    confidence=1.0,
                    metadata={"rule": rule.get("name")},
                )

        # Default fallback
        return AgentAction(action_type="noop", payload={}, messages=[])


class LLMAgent(AgentBase):
    """Agent that delegates decision making to an LLM provider."""

    def __init__(self, context: AgentContext, config: Dict[str, Any], decision_engine: LLMDecisionEngine):
        super().__init__(context, config)
        self.decision_engine = decision_engine

    def observe(self, state: EnvironmentState, timestep: int, messages: List[AgentMessage]) -> AgentObservation:
        return AgentObservation(
            state=state.clone(),
            timestep=timestep,
            incoming_messages=messages,
            context={
                "agent_memory": self.context.memory,
                "personality": self.context.personality,
                "instructions": self.config.get("system_prompt"),
            },
        )

    def decide(self, observation: AgentObservation) -> AgentAction:
        response = self.decision_engine.decide(self.context, observation, self.config)
        messages = [
            AgentMessage(
                sender_id=self.context.agent_id,
                recipient_id=m.get("recipient_id"),
                content=m.get("content", {}),
                channel=m.get("channel", "default"),
            )
            for m in response.get("messages", [])
        ]

        metadata = {
            "provider": response.get("_provider"),
            "model": response.get("_model"),
            "latency_ms": response.get("_latency_ms"),
            "tokens_in": response.get("_tokens_in"),
            "tokens_out": response.get("_tokens_out"),
            "cost_usd": response.get("_cost_usd"),
        }

        action_payload = response.get("action") or {}

        return AgentAction(
            action_type=action_payload.get("type", "noop"),
            payload=action_payload.get("payload", {}),
            messages=messages,
            confidence=response.get("confidence", 0.75),
            metadata=metadata,
        )

