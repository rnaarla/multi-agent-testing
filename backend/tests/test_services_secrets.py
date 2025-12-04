from types import SimpleNamespace

from app.services import secrets as secrets_module


class StaticBackend(secrets_module.SecretBackend):
    """Simple in-memory backend to introspect cache behaviour."""

    def __init__(self, values):
        self.values = values
        self.calls = 0

    def get_secret(self, name: str):  # pragma: no cover - interface requirement
        self.calls += 1
        return self.values.get(name)


def test_env_secret_backend_prefers_direct_env(monkeypatch):
    backend = secrets_module.EnvSecretBackend()
    monkeypatch.setenv("PLAIN_SECRET", "direct")
    assert backend.get_secret("PLAIN_SECRET") == "direct"

    monkeypatch.delenv("PLAIN_SECRET", raising=False)
    key = "providers/openai/api-key"
    normalized = key.upper().replace("/", "_").replace("-", "_")
    monkeypatch.setenv(normalized, "normalized")
    assert backend.get_secret(key) == "normalized"


def test_secret_manager_caching_and_json():
    backend = StaticBackend({"alpha": "value", "json": '{"k": 1}', "bad": "not-json"})
    manager = secrets_module.SecretManager(backend=backend, cache_ttl=60)

    assert manager.get_secret("alpha") == "value"
    assert manager.get_secret("alpha") == "value"  # cached hit should not bump calls
    assert backend.calls == 1

    cached_json = manager.get_secret_json("json")
    assert cached_json == {"k": 1}

    assert manager.get_secret_json("bad", default={}) == {}


def test_secret_manager_force_refresh_and_defaults():
    backend = StaticBackend({"alpha": "value1"})
    manager = secrets_module.SecretManager(backend=backend, cache_ttl=60)

    assert manager.get_secret("alpha") == "value1"
    backend.values["alpha"] = "value2"
    assert manager.get_secret("alpha", force_refresh=True) == "value2"

    # Empty name should return default without hitting backend
    backend.calls = 0
    assert manager.get_secret("", default="noop") == "noop"
    assert backend.calls == 0

    # Missing secret falls back to default and caches it
    backend.values.pop("missing", None)
    assert manager.get_secret("missing", default="fallback") == "fallback"
    assert backend.calls == 1


def test_build_backend_selects_configured_backend(monkeypatch):
    monkeypatch.setenv("SECRET_BACKEND", "aws")

    class FakeAWSBackend(secrets_module.SecretBackend):
        def get_secret(self, name: str):  # pragma: no cover - interface requirement
            return None

    monkeypatch.setattr(secrets_module, "AWSSecretBackend", lambda: FakeAWSBackend())
    backend = secrets_module._build_backend()
    assert isinstance(backend, FakeAWSBackend)


def test_build_backend_falls_back_to_env_on_error(monkeypatch, caplog):
    monkeypatch.setenv("SECRET_BACKEND", "aws")

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(secrets_module, "AWSSecretBackend", boom)
    backend = secrets_module._build_backend()
    assert isinstance(backend, secrets_module.EnvSecretBackend)
    assert any("Falling back to env backend" in record.message for record in caplog.records)


def test_resolve_provider_api_key_sources(monkeypatch):
    captured = {}

    def fake_get_secret(name, default=None):
        captured["name"] = name
        captured["default"] = default
        return "resolved"

    monkeypatch.setattr(secrets_module, "get_secret", fake_get_secret)
    value = secrets_module.resolve_provider_api_key("openai", "OPENAI_API_KEY")

    assert value == "resolved"
    assert captured["name"] == "providers/openai/api_key"

    # Explicit value bypasses secret lookup
    assert secrets_module.resolve_provider_api_key("openai", "OPENAI_API_KEY", explicit="abc") == "abc"

    # When secret lookup returns default, env var should flow through
    monkeypatch.setattr(secrets_module, "get_secret", lambda name, default=None: default)
    monkeypatch.setenv("OPENAI_API_KEY", "env-value")
    assert secrets_module.resolve_provider_api_key("openai", "OPENAI_API_KEY") == "env-value"


def test_get_secret_manager_singleton(monkeypatch):
    fake_manager = SimpleNamespace(get_secret=lambda name, default=None: "value")
    monkeypatch.setattr(secrets_module, "_secret_manager", fake_manager)
    assert secrets_module.get_secret("anything") == "value"

    monkeypatch.setattr(secrets_module, "_secret_manager", None)
    manager = secrets_module.get_secret_manager()
    assert isinstance(manager, secrets_module.SecretManager)
    # Subsequent calls reuse cached singleton
    assert secrets_module.get_secret_manager() is manager