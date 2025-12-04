from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.routers.user_testing as user_testing_router
from app.auth import Permission, Role, User, get_current_user
from app.main import app
from app.models_enhanced import (
    AgentOutput,
    AssertionResult,
    ContractViolation,
    ExecutionTrace,
    SafetyViolation,
    TestGraph,
    TestRun,
    metadata,
)
from app.runner.run_graph import ExecutionMode, ExecutionTrace as RunnerExecutionTrace
from app.services.user_testing import get_control_store


@pytest.fixture()
def user_testing_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    metadata.create_all(engine)

    monkeypatch.setattr(user_testing_router, "SessionLocal", TestingSession)

    async def fake_log_audit(**kwargs):
        return None

    monkeypatch.setattr(user_testing_router, "log_audit", fake_log_audit)

    base = datetime.now(UTC)
    dummy_trace = RunnerExecutionTrace(
        run_id="sim-1",
        graph_id="graph-1",
        graph_hash="hash123",
        mode=ExecutionMode.SIMULATION,
        seed=None,
        started_at=base.isoformat(),
        completed_at=(base + timedelta(seconds=1)).isoformat(),
        agent_outputs=[],
        assertion_results=[],
        contract_violations=[],
        total_latency_ms=0.0,
        total_cost_usd=0.0,
        status="passed",
    )

    def fake_execute_graph(graph, execution_config=None):
        return dummy_trace

    monkeypatch.setattr(user_testing_router, "execute_graph", fake_execute_graph)

    store = get_control_store()
    store.reset()

    user = User(
        id=1,
        email="qa@example.com",
        name="QA Engineer",
        role=Role.ADMIN,
        permissions=list(Permission),
        tenant_id="tenant-qa",
    )

    async def override_current_user():
        return user

    app.dependency_overrides[get_current_user] = override_current_user

    with engine.begin() as conn:
        graph_id = conn.execute(
            TestGraph.insert().values(
                name="QA Graph",
                description="",
                content={"nodes": []},
                tenant_id="tenant-qa",
            )
        ).inserted_primary_key[0]

        run_id = conn.execute(
            TestRun.insert().values(
                graph_id=graph_id,
                tenant_id="tenant-qa",
                status="passed",
                execution_mode="normal",
                latency_ms=123.0,
                cost_usd=0.45,
                created_at=base - timedelta(minutes=5),
                completed_at=base - timedelta(minutes=4),
                assertions_passed=2,
                assertions_failed=0,
                contract_violations=1,
            )
        ).inserted_primary_key[0]

        conn.execute(
            AgentOutput.insert().values(
                run_id=run_id,
                node_id="start",
                agent_type="llm",
                latency_ms=12.0,
                input_data={"prompt": "hi"},
                output_data={"response": "hello"},
                tokens_in=10,
                tokens_out=5,
                provider="mock",
                created_at=base - timedelta(minutes=4, seconds=30),
            )
        )

        conn.execute(
            AssertionResult.insert().values(
                run_id=run_id,
                assertion_id="assert-latency",
                assertion_type="threshold",
                target_node="start",
                passed=True,
                message="Latency within threshold",
                created_at=base - timedelta(minutes=4),
            )
        )

        conn.execute(
            ContractViolation.insert().values(
                run_id=run_id,
                contract_id="c1",
                contract_type="schema",
                source_node="start",
                target_node="end",
                field="payload",
                expected={"type": "object"},
                actual={"type": "string"},
                created_at=base - timedelta(minutes=4, seconds=45),
            )
        )

        conn.execute(
            SafetyViolation.insert().values(
                run_id=run_id,
                policy_id=None,
                violation_type="pii",
                details={"field": "email"},
                severity="high",
                tenant_id="tenant-qa",
                created_at=base - timedelta(minutes=4, seconds=15),
            )
        )

        conn.execute(
            ExecutionTrace.insert().values(
                run_id=run_id,
                trace_data={"run_id": run_id, "events": [{"type": "mock"}]},
                graph_hash="hash123",
            )
        )

    client = TestClient(app)
    yield {
        "client": client,
        "run_id": run_id,
        "engine": engine,
        "user": user,
    }

    app.dependency_overrides.clear()
    engine.dispose()


def test_run_history_endpoint(user_testing_env):
    client = user_testing_env["client"]
    response = client.get("/user-testing/runs/history")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["runs"][0]["status"] == "passed"


def test_run_timeline_endpoint(user_testing_env):
    client = user_testing_env["client"]
    run_id = user_testing_env["run_id"]

    response = client.get(f"/user-testing/runs/{run_id}/timeline")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["status"] == "passed"
    event_types = [event["type"] for event in data["timeline"]]
    assert "agent_output" in event_types
    assert "contract_violation" in event_types


def test_run_assertions_endpoint(user_testing_env):
    client = user_testing_env["client"]
    run_id = user_testing_env["run_id"]

    response = client.get(f"/user-testing/runs/{run_id}/assertions")
    assert response.status_code == 200
    data = response.json()
    assert data["assertions"][0]["assertion_id"] == "assert-latency"


def test_run_compliance_endpoint(user_testing_env):
    client = user_testing_env["client"]
    run_id = user_testing_env["run_id"]

    response = client.get(f"/user-testing/runs/{run_id}/compliance")
    assert response.status_code == 200
    data = response.json()
    assert data["violations"][0]["severity"] == "high"


def test_run_control_endpoint(user_testing_env):
    client = user_testing_env["client"]
    run_id = user_testing_env["run_id"]

    response = client.post(
        f"/user-testing/runs/{run_id}/control",
        json={"action": "pause", "note": "QA pause"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pause"
    assert data["note"] == "QA pause"


def test_simulation_endpoint(user_testing_env):
    client = user_testing_env["client"]
    response = client.post(
        "/user-testing/simulations",
        json={"graph": {"nodes": []}, "execution_config": {}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["trace"]["simulated"] is True
    assert data["trace"]["mode"] == "simulation"


def test_replay_endpoint(user_testing_env):
    client = user_testing_env["client"]
    run_id = user_testing_env["run_id"]

    response = client.get(f"/user-testing/runs/{run_id}/replay")
    assert response.status_code == 200
    assert response.json()["trace"]["events"][0]["type"] == "mock"

