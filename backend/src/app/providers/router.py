"""Provider routing utilities for multi-cloud fallbacks."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from app.providers import ProviderConfig, ProviderRegistry


class ProviderRouter:
    """Selects providers based on strategy configuration."""

    def __init__(self, registry: ProviderRegistry, strategy: Optional[Dict[str, any]] = None):
        self.registry = registry
        self.strategy = strategy or {}
        self.fallback_order: List[str] = list(self.strategy.get("fallback_order", []))
        self.per_region: Dict[str, List[str]] = {
            region.lower(): list(candidates)
            for region, candidates in (self.strategy.get("per_region") or {}).items()
        }

    def register_region(self, region: str, providers: Iterable[str]) -> None:
        """Register providers for a region dynamically."""

        normalized = region.lower()
        self.per_region.setdefault(normalized, [])
        for provider in providers:
            if provider and provider not in self.per_region[normalized]:
                self.per_region[normalized].append(provider)

    def register_fallback(self, provider: str) -> None:
        """Append a provider to the fallback chain."""

        if provider and provider not in self.fallback_order:
            self.fallback_order.append(provider)

    def _ensure_registered(self, provider_name: str) -> None:
        if provider_name not in self.registry.providers:
            # Register lazily with minimal configuration; useful for mock/testing scenarios.
            self.registry.register(provider_name, ProviderConfig(name=provider_name))

    def _first_available(self, candidates: Iterable[str]) -> Optional[str]:
        for candidate in candidates:
            if not candidate:
                continue
            self._ensure_registered(candidate)
            return candidate
        return None

    def resolve(self, *, node_config: Dict[str, any], agent_type: str = "") -> str:
        """Resolve provider name for a node execution."""

        if node_config.get("provider"):
            provider = node_config["provider"]
            self._ensure_registered(provider)
            return provider

        region = node_config.get("region")
        if region:
            provider = self._first_available(self.per_region.get(region.lower(), []))
            if provider:
                node_config.setdefault("provider", provider)
                return provider

        if node_config.get("provider_candidates"):
            provider = self._first_available(node_config["provider_candidates"])
            if provider:
                node_config.setdefault("provider", provider)
                return provider

        provider = self._first_available(self.fallback_order)
        if provider:
            node_config.setdefault("provider", provider)
            return provider

        default_provider = self.registry.default_provider or "mock"
        self._ensure_registered(default_provider)
        node_config.setdefault("provider", default_provider)
        return default_provider
