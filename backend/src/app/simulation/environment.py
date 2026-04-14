"""Environment representation consumed by the simulation runner."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass
class EnvironmentState:
    """Serialisable view of the shared environment."""

    data: Dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "EnvironmentState":
        return EnvironmentState(data=deepcopy(self.data))

    def apply_updates(self, updates: Dict[str, Any]) -> None:
        for key, value in updates.items():
            self.data[key] = value


class Environment:
    """Lightweight environment that evolves based on agent actions."""

    def __init__(self, initial_state: Dict[str, Any], config: Dict[str, Any]):
        self.state = EnvironmentState(data=initial_state or {})
        self.config = config or {}

    def step(self, timestep: int, agent_id: str, action: Any) -> Tuple[EnvironmentState, Dict[str, Any]]:
        """Apply an agent action and mutate the shared state."""

        result: Dict[str, Any] = {"status": "ack"}
        action_type = action.action_type

        if action_type == "set":
            updates = action.payload.get("values", {})
            self.state.apply_updates(updates)
            result["applied_updates"] = updates
        elif action_type == "increment":
            key = action.payload.get("key")
            amount = action.payload.get("amount", 1)
            if not key:
                result["status"] = "invalid_payload"
                result["reason"] = "increment requires payload.key"
            else:
                current = self.state.data.get(key, 0)
                new_value = current + amount
                self.state.apply_updates({key: new_value})
                result["applied_updates"] = {key: new_value}
        elif action_type == "noop":
            result["status"] = "noop"
        else:
            # Allow pluggable custom handlers via config
            handlers = self.config.get("custom_handlers", {})
            handler = handlers.get(action_type)
            if handler and callable(handler):
                handler(self.state, action)
            else:
                result["status"] = "unknown_action"
                result["reason"] = f"Unhandled action type: {action_type}"

        result["environment_snapshot"] = self.state.clone().data
        result["messages"] = [msg.__dict__ for msg in action.messages]
        result["metadata"] = action.metadata
        result["timestep"] = timestep
        result["agent_id"] = agent_id
        result["action"] = {"type": action.action_type, "payload": action.payload}

        return self.state.clone(), result

    def serialise(self) -> Dict[str, Any]:
        return self.state.clone().data

