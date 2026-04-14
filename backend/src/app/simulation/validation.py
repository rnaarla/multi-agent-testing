"""Simulation launch validation (policy limits and consistency checks)."""

from __future__ import annotations

from typing import Any, Dict, List, Set

MAX_SIMULATION_STEPS = 5000
MAX_AGENTS = 64

ALLOWED_IMPLEMENTATIONS = frozenset({"rule", "rule_based", "llm", "provider"})


class SimulationValidationError(ValueError):
    """Raised when a simulation payload fails policy or consistency checks."""

    def __init__(self, message: str, *, code: str = "invalid_simulation_request") -> None:
        self.code = code
        super().__init__(message)


def validate_simulation_payload(payload: Dict[str, Any]) -> None:
    """Validate a simulation request dict before building a SimulationSpec."""

    agents = payload.get("agents")
    if agents is None:
        raise SimulationValidationError("agents is required", code="agents_required")
    if not isinstance(agents, list):
        raise SimulationValidationError("agents must be a list", code="invalid_agents_shape")

    if len(agents) < 1:
        raise SimulationValidationError("At least one agent is required", code="agents_required")

    if len(agents) > MAX_AGENTS:
        raise SimulationValidationError(
            f"Too many agents (max {MAX_AGENTS})",
            code="agents_limit_exceeded",
        )

    seen: Set[str] = set()
    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            raise SimulationValidationError(
                f"agents[{index}] must be an object",
                code="invalid_agent_shape",
            )
        raw_id = agent.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise SimulationValidationError(
                f"agents[{index}].id must be a non-empty string",
                code="invalid_agent_id",
            )
        aid = raw_id.strip()
        if aid in seen:
            raise SimulationValidationError(f"Duplicate agent id: {aid}", code="duplicate_agent_id")
        seen.add(aid)

        impl = str(agent.get("implementation", "rule")).lower()
        if impl not in ALLOWED_IMPLEMENTATIONS:
            raise SimulationValidationError(
                f"Unknown implementation for agent {aid}: {agent.get('implementation')!r}",
                code="unknown_implementation",
            )

    steps = payload.get("steps", 10)
    if type(steps) is not int:
        raise SimulationValidationError("steps must be an integer", code="invalid_steps_type")
    if steps < 1:
        raise SimulationValidationError("steps must be >= 1", code="invalid_steps_range")
    if steps > MAX_SIMULATION_STEPS:
        raise SimulationValidationError(
            f"steps exceeds maximum ({MAX_SIMULATION_STEPS})",
            code="steps_limit_exceeded",
        )
