from fastapi.testclient import TestClient

import app.main as main
import app.providers as providers_module


def test_root_health_and_providers(monkeypatch):
    init_calls = []
    monkeypatch.setattr(main, "init_db", lambda: init_calls.append("called"))

    class DummyRegistry:
        def __init__(self):
            self.available = ["openai"]
            self.configured = ["openai"]

        def list_available_providers(self):
            return self.available

        def list_providers(self):
            return self.configured

    monkeypatch.setattr(providers_module, "ProviderRegistry", DummyRegistry)

    @main.app.get("/__test_error__")
    def _boom():
        raise RuntimeError("boom")

    with TestClient(main.app, raise_server_exceptions=False) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["status"] == "running"

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["components"]["api"] == "up"

        providers_resp = client.get("/providers")
        assert providers_resp.status_code == 200
        assert providers_resp.json()["available"] == ["openai"]
        assert init_calls  # lifespan called init_db

        error_response = client.get("/__test_error__")
        assert error_response.status_code == 500
        payload = error_response.json()
        assert payload["detail"] == "Internal server error"
        assert payload["type"] == "RuntimeError"
