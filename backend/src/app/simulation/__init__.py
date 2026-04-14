"""
Simulation engine for multi-agent behavioural experiments.

This module provides:
    - Agent abstractions (rule-based and LLM-backed)
    - Environment orchestration primitives
    - Persistence helpers for Redis/Postgres
    - A high-level SimulationRunner used by API/services
"""

from .agents import (
    AgentBase,
    AgentContext,
    AgentObservation,
    AgentAction,
    AgentMessage,
    RuleBasedAgent,
    LLMAgent,
)
from .runner import SimulationRunner, SimulationSpec, AgentSpec
from .environment import EnvironmentState, Environment

__all__ = [
    "AgentBase",
    "AgentContext",
    "AgentObservation",
    "AgentAction",
    "AgentMessage",
    "RuleBasedAgent",
    "LLMAgent",
    "SimulationRunner",
    "SimulationSpec",
    "AgentSpec",
    "EnvironmentState",
    "Environment",
]

