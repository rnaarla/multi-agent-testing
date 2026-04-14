from fastapi.testclient import TestClient

from app.main import app
from app.auth import User, Role, Permission, get_current_user


def build_test_user():
    return User(
        id=1,
        email="test@example.com",
        name="Tester",
        role=Role.ADMIN,
        permissions=list(Permission),
        tenant_id="tenant-test",
    )


def override_user():
    return build_test_user()


def test_simulation_router_endpoints(monkeypatch):
    app.dependency_overrides[get_current_user] = override_user

    monkeypatch.setattr(
        "app.services.simulation_service.start_simulation_run",
        lambda payload, user: {"run_id": 42, "status": "completed", "steps": 3},
    )
    monkeypatch.setattr(
        "app.services.simulation_service.list_simulation_runs",
        lambda tenant_id, limit=20, offset=0: [
            {"id": 42, "name": "sim", "scenario": "demo", "status": "completed", "steps": 3}
        ],
    )
    monkeypatch.setattr(
        "app.services.simulation_service.get_simulation_run",
        lambda run_id, tenant_id: {
            "id": run_id,
            "name": "sim",
            "scenario": "demo",
            "status": "completed",
            "steps": 3,
            "agents": [],
        },
    )
    monkeypatch.setattr(
        "app.services.simulation_service.fetch_run_events",
        lambda run_id, last_event_id=None, limit=100: [
            {"id": 1, "step_index": 0, "event_type": "agent_action", "agent_id": "a1", "payload": {}}
        ],
    )
    monkeypatch.setattr(
        "app.services.simulation_service.read_event_stream",
        lambda run_id, last_id="0-0", count=100: [{"id": "1-0", "payload": {"step": 0}}],
    )

    client = TestClient(app)

    launch = client.post(
        "/simulation/run",
        json={
            "name": "sim",
            "scenario": "demo",
            "steps": 2,
            "environment": {"state": {}, "config": {}},
            "agents": [{"id": "agent", "type": "rule", "implementation": "rule", "config": {"rules": []}}],
        },
    )
    assert launch.status_code == 202
    assert launch.json()["run_id"] == 42

    runs = client.get("/simulation/runs")
    assert runs.status_code == 200
    assert runs.json()[0]["id"] == 42

    detail = client.get("/simulation/runs/42")
    assert detail.status_code == 200
    assert detail.json()["id"] == 42

    events = client.get("/simulation/runs/42/events")
    assert events.status_code == 200
    assert events.json()[0]["step_index"] == 0

    stream = client.get("/simulation/runs/42/stream")
    assert stream.status_code == 200
    assert stream.json()[0]["id"] == "1-0"

    app.dependency_overrides.pop(get_current_user, None)

