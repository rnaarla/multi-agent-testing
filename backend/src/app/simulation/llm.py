"""Decision engine that delegates agent behaviour to LLM providers."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.providers import ProviderRegistry, ProviderConfig
from app.providers.router import ProviderRouter

from .agents import AgentContext, AgentObservation


class LLMDecisionEngine:
    """Utility that turns agent observations into provider prompts."""

    def __init__(self, registry: ProviderRegistry, router: Optional[ProviderRouter] = None):
        self.registry = registry
        self.router = router

    def _resolve_provider(self, agent_config: Dict[str, Any], agent_type: str) -> str:
        explicit = agent_config.get("provider")
        if explicit:
            return explicit
        if self.router:
            return self.router.resolve(node_config=agent_config, agent_type=agent_type) or "openai"
        return agent_config.get("default_provider", "openai")

    def decide(
        self,
        context: AgentContext,
        observation: AgentObservation,
        agent_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Invoke provider using structured prompt."""

        provider_name = self._resolve_provider(agent_config, context.agent_type)
        provider = self.registry.get_provider(provider_name)

        prompt_payload = {
            "agent_id": context.agent_id,
            "agent_type": context.agent_type,
            "timestep": observation.timestep,
            "environment_state": observation.state.data,
            "memory": context.memory,
            "incoming_messages": [msg.__dict__ for msg in observation.incoming_messages],
            "personality": context.personality,
            "instructions": agent_config.get("system_prompt"),
        }

        provider_response = provider.execute(
            agent_type=context.agent_type,
            agent_config=agent_config,
            input_data=prompt_payload,
        )

        structured = self._parse_response(provider_response)
        # Provider metadata first; normalized action/messages/confidence from parsing
        # must win so raw provider keys cannot clobber structured output.
        return {**provider_response, **structured}

    def _parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise the provider response into a structured dict."""

        raw = response.get("response", "")
        if isinstance(raw, dict):
            return raw

        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # Attempt to locate JSON block
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end != -1 and end > start:
                    snippet = raw[start : end + 1]
                    try:
                        return json.loads(snippet)
                    except json.JSONDecodeError:
                        pass

        # Fallback to default noop action (visible to traces / downstream oracles)
        return {
            "action": {"type": "noop", "payload": {}},
            "messages": [],
            "confidence": response.get("confidence", 0.5),
            "_parse_fallback": True,
            "_parse_fallback_reason": "invalid_or_non_json_response",
        }

