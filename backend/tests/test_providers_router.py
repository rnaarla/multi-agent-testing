from app.providers import ProviderConfig, ProviderRegistry
from app.providers.router import ProviderRouter


def test_provider_router_region_resolution():
    registry = ProviderRegistry()
    registry.register("openai", ProviderConfig(name="openai"))
    registry.register("azure", ProviderConfig(name="azure"))
    registry.default_provider = "openai"

    router = ProviderRouter(
        registry,
        strategy={
            "per_region": {"us-east": ["azure"]},
            "fallback_order": ["openai"],
        },
    )

    node_config = {"region": "us-east"}
    provider = router.resolve(node_config=node_config)
    assert provider == "azure"
    assert node_config["provider"] == "azure"


def test_provider_router_fallback_order():
    registry = ProviderRegistry()
    registry.register("mock", ProviderConfig(name="mock"))
    registry.default_provider = "mock"
    router = ProviderRouter(registry)
    router.register_fallback("mock")

    node_config = {}
    provider = router.resolve(node_config=node_config)
    assert provider == "mock"
from app.providers import ProviderConfig, ProviderRegistry
from app.providers.router import ProviderRouter
from app.runner.run_graph import GraphRunner, ExecutionMode


def build_registry():
    registry = ProviderRegistry()
    registry.register("primary", ProviderConfig(name="mock"))
    registry.register("backup", ProviderConfig(name="mock"))
    registry.register("azure", ProviderConfig(name="azure_openai"))
    registry.default_provider = "primary"
    return registry


def test_provider_router_prefers_node_provider():
    registry = build_registry()
    router = ProviderRouter(registry, {"fallback_order": ["backup", "azure"]})
    node_config = {"provider": "azure"}
    selected = router.resolve(node_config=node_config, agent_type="planner")
    assert selected == "azure"


def test_provider_router_uses_region_fallback():
    registry = build_registry()
    router = ProviderRouter(
        registry,
        {
            "fallback_order": ["backup"],
            "per_region": {"eu": ["azure", "backup"]},
        },
    )
    node_config = {"region": "eu"}
    selected = router.resolve(node_config=node_config, agent_type="planner")
    assert selected == "azure"


def test_graph_runner_integration_with_router(monkeypatch):
    registry = build_registry()

    class DummyProvider:
        def __init__(self):
            self.called = False

        def execute(self, agent_type, agent_config, input_data):
            self.called = True
            return {"response": "ok", "_provider": agent_config.get("provider", ""), "_tokens_in": 0, "_tokens_out": 0}

    dummy = DummyProvider()
    registry.providers["backup"] = dummy  # type: ignore
    registry.default_provider = "backup"

    router = ProviderRouter(registry, {"fallback_order": ["backup"]})
    runner = GraphRunner(provider_registry=registry, provider_router=router, mode=ExecutionMode.NORMAL)

    node = {"id": "a", "type": "agent", "config": {"provider_candidates": ["backup"]}}
    monkeypatch.setattr(runner, "_estimate_cost", lambda *args, **kwargs: 0.0)
    output = runner._execute_agent("agent", node["config"], {})

    assert dummy.called
    assert output["response"] == "ok"

