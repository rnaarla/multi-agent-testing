from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.main as main
import app.routers.graphs as graphs_router
import app.routers.metrics as metrics_router
import app.routers.runs as runs_router
from app.auth import Permission, Role, User, get_current_user
from app.models_enhanced import (
    TestGraph,
    TestGraphVersion,
    TestRun,
    metadata,
)


@pytest.fixture
def phase6_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    metadata.create_all(engine)

    monkeypatch.setattr(database, "SessionLocal", TestingSession)
    monkeypatch.setattr(graphs_router, "SessionLocal", TestingSession)
    monkeypatch.setattr(runs_router, "SessionLocal", TestingSession)
    monkeypatch.setattr(metrics_router, "SessionLocal", TestingSession)

    user = User(
        id=42,
        email="phase6@example.com",
        name="Phase6 Admin",
        role=Role.ADMIN,
        permissions=list(Permission),
        tenant_id="tenant-phase6",
    )

    main.app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(main.app)

    now = datetime.now(UTC)
    with engine.begin() as conn:
        graph_id = conn.execute(
            TestGraph.insert().values(
                name="Execution Graph",
                description="Demo graph",
                content={
                    "nodes": [{"id": "agent-1", "type": "agent"}],
                    "edges": [],
                },
                tenant_id=user.tenant_id,
                version=1,
                created_by=user.id,
                created_at=now,
                updated_at=now,
            )
        ).inserted_primary_key[0]

        conn.execute(
            TestGraphVersion.insert().values(
                graph_id=graph_id,
                version=1,
                content={
                    "nodes": [{"id": "agent-1", "type": "agent"}],
                    "edges": [],
                },
                tenant_id=user.tenant_id,
            )
        )

        primary_run = conn.execute(
            TestRun.insert().values(
                graph_id=graph_id,
                graph_version=1,
                tenant_id=user.tenant_id,
                status="passed",
                latency_ms=120.0,
                cost_usd=1.25,
                results={
                    "logs": [
                        {"level": "info", "message": "Run started"},
                        {"level": "info", "message": "Node executed"},
                    ],
                    "agent_outputs": [{"node_id": "agent-1", "response": "ok"}],
                    "contract_violations": [],
                },
                created_at=now,
                completed_at=now,
            )
        ).inserted_primary_key[0]

        secondary_run = conn.execute(
            TestRun.insert().values(
                graph_id=graph_id,
                graph_version=1,
                tenant_id=user.tenant_id,
                status="failed",
                latency_ms=250.0,
                cost_usd=1.55,
                results={
                    "logs": [{"level": "error", "message": "Assertion failure"}],
                    "agent_outputs": [{"node_id": "agent-1", "response": "timeout"}],
                    "contract_violations": [{"id": "safety-check"}],
                },
                created_at=now,
                completed_at=now,
            )
        ).inserted_primary_key[0]

    yield {
        "client": client,
        "user": user,
        "graph_id": graph_id,
        "primary_run": primary_run,
        "secondary_run": secondary_run,
        "engine": engine,
    }

    main.app.dependency_overrides.clear()
    engine.dispose()


def test_builder_validate_and_generate(phase6_env):
    client = phase6_env["client"]

    valid_yaml = """
    nodes:
      - id: agent-1
        type: agent
      - id: agent-2
        type: tool
    edges:
      - from: agent-1
        to: agent-2
    """
    response = client.post("/graphs/builder/validate", json={"yaml": valid_yaml})
    payload = response.json()
    assert response.status_code == 200
    assert payload["valid"]
    assert payload["summary"]["node_count"] == 2

    generate = client.post(
        "/graphs/builder/generate",
        json={
            "nodes": [{"id": "agent-1", "type": "agent"}],
            "edges": [{"from": "agent-1", "to": "agent-1"}],
            "assertions": [{"id": "assert-1", "type": "equals"}],
        },
    )
    assert generate.status_code == 200
    generated_yaml = generate.json()["yaml"]
    assert "assert-1" in generated_yaml


def test_graph_library_and_versioning(phase6_env):
    client = phase6_env["client"]
    graph_id = phase6_env["graph_id"]
    admin_user = phase6_env["user"]

    library = client.get("/graphs/library")
    assert library.status_code == 200
    graphs = library.json()["graphs"]
    assert any(entry["id"] == graph_id for entry in graphs)

    viewer = User(
        id=99,
        email="viewer@example.com",
        name="Viewer",
        role=Role.VIEWER,
        permissions=[Permission.GRAPH_READ],
        tenant_id=admin_user.tenant_id,
    )

    main.app.dependency_overrides[get_current_user] = lambda: viewer
    forbidden = client.get("/graphs/library")
    assert forbidden.status_code == 403
    main.app.dependency_overrides[get_current_user] = lambda: admin_user

    new_version = client.post(
        f"/graphs/{graph_id}/versions",
        json={
            "content": {
                "nodes": [
                    {"id": "agent-1", "type": "agent"},
                    {"id": "agent-2", "type": "tool"},
                ],
                "edges": [{"from": "agent-1", "to": "agent-2"}],
            },
            "description": "Add tool node",
        },
    )
    assert new_version.status_code == 200
    assert new_version.json()["version"] == 2


def test_run_diff_and_stream(phase6_env):
    client = phase6_env["client"]
    primary = phase6_env["primary_run"]
    secondary = phase6_env["secondary_run"]

    diff_response = client.get(f"/runs/{primary}/diff/{secondary}")
    assert diff_response.status_code == 200
    diff_payload = diff_response.json()
    assert diff_payload["primary"] == primary
    assert any(item["field"] == "status" for item in diff_payload["diff"]), diff_payload["diff"]

    with client.websocket_connect(f"/runs/stream/{primary}") as websocket:
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "complete":
                break
    assert any(evt["event"] == "log" for evt in events)
    assert any(evt["event"] == "node_output" for evt in events)


def test_analytics_dashboard_endpoint(phase6_env):
    client = phase6_env["client"]
    response = client.get("/metrics/analytics/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["cost"]["total"] > 0
    assert payload["safety"]["violations"] >= 0

