from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.main as main
import app.routers.runs as runs_router
import app.workers.tasks as worker_tasks
from app.auth import Permission, Role, User, get_current_user
from app.models_enhanced import (
    metadata,
    User as UserTable,
    TestGraph,
    TestGraphVersion,
    TestRun,
)


@pytest.fixture
def integration_app(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    metadata.create_all(engine)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(runs_router, "SessionLocal", TestingSessionLocal)

    with engine.begin() as conn:
        user_id = conn.execute(
            UserTable.insert().values(
                email="integration@example.com",
                password_hash="x",
                name="Integration User",
                role="admin",
                tenant_id="tenantA",
                is_active=True,
            )
        ).inserted_primary_key[0]

        graph_id = conn.execute(
            TestGraph.insert().values(
                name="Smoke Graph",
                description="",
                content={"nodes": ["start"]},
                version=1,
                created_by=user_id,
                tenant_id="tenantA",
            )
        ).inserted_primary_key[0]

        conn.execute(
            TestGraphVersion.insert().values(
                graph_id=graph_id,
                version=1,
                content={"nodes": ["start"]},
                tenant_id="tenantA",
                created_by=user_id,
            )
        )

    test_user = User(
        id=1,
        email="integration@example.com",
        name="Integration User",
        role=Role.ADMIN,
        permissions=list(Permission),
        tenant_id="tenantA",
    )
    main.app.dependency_overrides[get_current_user] = lambda: test_user

    @contextmanager
    def fake_lock(*args, **kwargs):
        yield

    async def fake_log_audit(*args, **kwargs):
        return None

    persist_calls = []

    def fake_persist(connection, run_id, trace_dict):
        persist_calls.append((run_id, trace_dict))

    execute_calls = []

    class DummyTrace:
        def __init__(self):
            now = datetime.now(UTC).isoformat()
            self.status = "completed"
            self.total_latency_ms = 111
            self.total_cost_usd = 1.23
            self.mode = SimpleNamespace(value="normal")
            self.seed = 99
            self.started_at = now
            self.completed_at = now
            self._trace = {
                "graph_hash": "hash",
                "agent_outputs": [],
                "assertion_results": [],
                "contract_violations": [],
                "started_at": now,
                "completed_at": now,
            }

        def to_dict(self):
            return self._trace

    def fake_execute_graph(graph_dict, config):
        execute_calls.append({"graph": graph_dict, "config": config})
        return DummyTrace()

    class DummyAsyncTask:
        def __init__(self):
            self.calls = []

        def delay(self, **payload):
            self.calls.append(payload)

    async_task = DummyAsyncTask()
    cancelled_runs = []

    def fake_mark_cancelled(run_id):
        cancelled_runs.append(run_id)

    monkeypatch.setattr(runs_router, "redis_lock", fake_lock)
    monkeypatch.setattr(runs_router, "log_audit", fake_log_audit)
    monkeypatch.setattr(runs_router, "persist_trace", fake_persist)
    monkeypatch.setattr(runs_router, "execute_graph", fake_execute_graph)
    monkeypatch.setattr(runs_router, "_mark_cancelled", fake_mark_cancelled)
    monkeypatch.setattr(worker_tasks, "execute_graph_async", async_task)

    client = TestClient(main.app, raise_server_exceptions=False)

    try:
        yield {
            "client": client,
            "graph_id": graph_id,
            "session_factory": TestingSessionLocal,
            "persist_calls": persist_calls,
            "async_task": async_task,
            "cancelled_runs": cancelled_runs,
        }
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def _insert_run(session_factory, graph_id, tenant_id="tenantA", status="running", results=None):
    with session_factory() as session:
        run_id = session.execute(
            TestRun.insert().values(
                graph_id=graph_id,
                graph_version=1,
                tenant_id=tenant_id,
                status=status,
                results=results or {},
            )
        ).inserted_primary_key[0]
        session.commit()
        return run_id


def test_sync_execution_flow(integration_app):
    client = integration_app["client"]
    graph_id = integration_app["graph_id"]
    persist_calls = integration_app["persist_calls"]
    session_factory = integration_app["session_factory"]

    response = client.post(f"/runs/{graph_id}/execute", json={"provider": "mock"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["trace"]["graph_hash"] == "hash"
    assert persist_calls

    run_id = payload["run_id"]
    with session_factory() as session:
        row = session.execute(TestRun.select().where(TestRun.c.id == run_id)).fetchone()
        assert row is not None
        assert row.status == "completed"


def test_async_execution_queue_and_list(integration_app):
    client = integration_app["client"]
    graph_id = integration_app["graph_id"]
    async_task = integration_app["async_task"]

    response = client.post(f"/runs/{graph_id}/execute/async", json={"webhook_url": "https://example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert async_task.calls
    assert async_task.calls[0]["run_id"] == body["run_id"]

    listing = client.get("/runs")
    assert listing.status_code == 200
    assert any(run["status"] == "queued" for run in listing.json())


def test_run_trace_and_cancel(integration_app):
    client = integration_app["client"]
    session_factory = integration_app["session_factory"]
    cancelled_runs = integration_app["cancelled_runs"]

    trace_blob = {
        "trace": {
            "agent_outputs": [{"node_id": "n1"}],
            "assertion_results": [{"id": "a1"}],
            "contract_violations": [],
        }
    }
    graph_id = integration_app["graph_id"]
    run_id = _insert_run(session_factory, graph_id=graph_id, results=trace_blob)

    trace_response = client.get(f"/runs/{run_id}/trace")
    assert trace_response.status_code == 200
    trace_json = trace_response.json()
    assert trace_json["agent_outputs"] == [{"node_id": "n1"}]

    cancel_response = client.post(f"/runs/{run_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert str(run_id) in cancelled_runs

    with session_factory() as session:
        row = session.execute(TestRun.select().where(TestRun.c.id == run_id)).fetchone()
        assert row.status == "cancelled"
