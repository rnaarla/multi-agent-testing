"""Utilities for executing behavioral graphs and returning traces."""

import os
from typing import Any, Dict, Optional, Tuple

from app.runner.run_graph import GraphRunner, ExecutionMode
from app.providers import ProviderRegistry, ProviderConfig
from app.providers.router import ProviderRouter
from app.governance import create_default_governance, GovernanceMiddleware


def _build_registry(config: Dict[str, Any]) -> ProviderRegistry:
    registry = ProviderRegistry()
    providers_cfg = config.get("providers")

    if providers_cfg:
        for alias, provider_cfg in providers_cfg.items():
            provider_type = provider_cfg.get("type", alias)
            registry.register(
                alias,
                ProviderConfig(
                    name=provider_type,
                    api_key=provider_cfg.get("api_key"),
                    base_url=provider_cfg.get("base_url"),
                    default_model=provider_cfg.get("model", ""),
                    timeout=provider_cfg.get("timeout", config.get("timeout", 60)),
                    max_retries=provider_cfg.get("max_retries", config.get("max_retries", 3)),
                    extra=provider_cfg.get("extra", {}),
                ),
            )
        default_alias = config.get("provider") or config.get("default_provider")
        if default_alias:
            registry.default_provider = default_alias
        elif registry.providers:
            registry.default_provider = next(iter(registry.providers))
        return registry

    provider_type = config.get("provider", "mock")

    # Avoid duplicate registration when multiple executions happen in the same process
    if provider_type not in registry.providers:
        registry.register(
            provider_type,
            ProviderConfig(
                name=provider_type,
                api_key=config.get("api_key"),
                base_url=config.get("base_url"),
                default_model=config.get("model", ""),
                timeout=config.get("timeout", 60),
                max_retries=config.get("max_retries", 3),
                extra=config.get("provider_config", {}),
            ),
        )
    registry.default_provider = provider_type
    return registry


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


DEFAULT_GOVERNANCE_ENABLED = _env_bool("GOVERNANCE_ENABLED", "true")
DEFAULT_GOVERNANCE_BLOCK = _env_bool("GOVERNANCE_BLOCK_POLICY_VIOLATIONS", "false")
DEFAULT_GOVERNANCE_MIN_SCORE = float(os.getenv("GOVERNANCE_DEFAULT_MIN_SCORE", "0.3"))


def _build_governance(config: Dict[str, Any]) -> Tuple[Optional[GovernanceMiddleware], bool]:
    governance_cfg = config.get("governance") or {}
    enabled = governance_cfg.get("enabled")
    if enabled is None:
        enabled = DEFAULT_GOVERNANCE_ENABLED

    if not enabled:
        return None, False

    middleware = create_default_governance()
    middleware.redact_pii = governance_cfg.get("redact_pii", middleware.redact_pii)
    middleware.block_violations = governance_cfg.get("block_violations", DEFAULT_GOVERNANCE_BLOCK)
    middleware.min_safety_score = governance_cfg.get("min_safety_score", DEFAULT_GOVERNANCE_MIN_SCORE)
    return middleware, True


def execute_graph(
    graph_dict: Dict[str, Any],
    execution_config: Optional[Dict[str, Any]] = None,
):
    """Execute a graph definition and return the resulting execution trace."""

    config = execution_config or {}
    registry = _build_registry(config)
    provider_router = None
    strategy_cfg = config.get("provider_strategy")
    if strategy_cfg:
        provider_router = ProviderRouter(registry, strategy_cfg)
    governance_middleware, governance_enabled = _build_governance(config)

    mode = ExecutionMode(config.get("mode", ExecutionMode.NORMAL.value))
    runner = GraphRunner(
        provider_registry=registry,
        seed=config.get("seed"),
        mode=mode,
        chaos_config=config.get("chaos_config"),
        timeout_seconds=config.get("timeout_seconds"),
        governance=governance_middleware,
        governance_enabled=governance_enabled,
        provider_router=provider_router,
    )

    trace = runner.run(graph_dict)
    return trace
