from types import SimpleNamespace

import app.services.executor as executor


def test_build_registry_registers_provider(monkeypatch):
    class DummyRegistry:
        def __init__(self):
            self.providers = {}
            self.default_provider = None

        def register(self, name, config):
            self.providers[name] = config

    class DummyConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(executor, "ProviderRegistry", DummyRegistry)
    monkeypatch.setattr(executor, "ProviderConfig", DummyConfig)

    config = {"provider": "openai", "api_key": "abc", "timeout": 10}
    registry = executor._build_registry(config)

    assert "openai" in registry.providers
    assert registry.default_provider == "openai"
    assert registry.providers["openai"].kwargs["api_key"] == "abc"


def test_build_governance_defaults_and_overrides(monkeypatch):
    class DummyGovernance(SimpleNamespace):
        redact_pii = True
        block_violations = False
        min_safety_score = 0.2

    monkeypatch.setattr(executor, "create_default_governance", lambda: DummyGovernance())

    middleware, enabled = executor._build_governance({"governance": {"min_safety_score": 0.9}})
    assert enabled is True
    assert middleware.min_safety_score == 0.9

    middleware, enabled = executor._build_governance({"governance": {"enabled": False}})
    assert middleware is None
    assert enabled is False


def test_execute_graph_invokes_runner(monkeypatch):
    class DummyMode:
        NORMAL = SimpleNamespace(value="normal")

        def __init__(self, value):
            self.value = value

    captured = {}

    class DummyRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, graph_dict):
            captured["graph"] = graph_dict
            return {"executed": True, "graph": graph_dict}

    monkeypatch.setattr(executor, "ExecutionMode", DummyMode)
    monkeypatch.setattr(executor, "GraphRunner", DummyRunner)
    monkeypatch.setattr(executor, "_build_registry", lambda cfg: {"provider": cfg.get("provider")})
    monkeypatch.setattr(executor, "_build_governance", lambda cfg: ("gov", True))

    result = executor.execute_graph({"nodes": []}, {"mode": "normal", "provider": "mock"})

    assert result["executed"] is True
    assert captured["provider_registry"] == {"provider": "mock"}
    assert captured["governance_enabled"] is True
    assert captured["graph"] == {"nodes": []}
