from __future__ import annotations

from app.providers import ProviderConfig, ProviderRegistry, configure_providers


def test_registry_mock_strategy_forces_mock_provider(monkeypatch):
    registry = ProviderRegistry(strategy="mock")
    provider = registry.register("openai", ProviderConfig(name="openai"))
    assert provider.__class__.__name__ == "MockProvider"
    assert registry.get_provider("openai") is provider


def test_configure_providers_with_mock_strategy():
    registry = configure_providers(
        {
            "strategy": "mock",
            "providers": {
                "primary": {"type": "openai"}
            },
            "default": "primary",
        }
    )
    provider = registry.get_provider("primary")
    assert provider.__class__.__name__ == "MockProvider"
    assert registry.strategy == "mock"

