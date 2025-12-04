from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.routers.metrics as metrics
from app.auth import Permission, Role, User
from app.models_enhanced import TestGraph, TestRun, metadata


@pytest.fixture
def metrics_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    metadata.create_all(engine)

    monkeypatch.setattr(metrics, "SessionLocal", TestingSession)

    user = User(
        id=7,
        email="metrics@example.com",
        name="Metrics User",
        role=Role.ADMIN,
        permissions=list(Permission),
        tenant_id="tenantA",
    )

    now = datetime.now(UTC)
    with engine.begin() as conn:
        graph_id = conn.execute(
            TestGraph.insert().values(
                name="Graph Alpha",
                description="",
                content={},
                tenant_id="tenantA",
            )
        ).inserted_primary_key[0]
        graph_beta = conn.execute(
            TestGraph.insert().values(
                name="Graph Beta",
                description="",
                content={},
                tenant_id="tenantA",
            )
        ).inserted_primary_key[0]

        for idx in range(12):
            status = "passed" if idx < 7 else "failed"
            completed = now - timedelta(days=idx // 3)
            conn.execute(
                TestRun.insert().values(
                    graph_id=graph_id,
                    tenant_id="tenantA",
                    status=status,
                    latency_ms=100 + idx * 5,
                    cost_usd=1.0 + idx * 0.1,
                    results=[
                        {"assertion_id": "assert_latency", "passed": status == "passed"},
                        {"assertion_id": "assert_cost", "passed": idx % 2 == 0},
                    ],
                    completed_at=completed,
                    created_at=completed,
                )
            )

        for idx in range(3):
            completed = now - timedelta(days=idx)
            conn.execute(
                TestRun.insert().values(
                    graph_id=graph_beta,
                    tenant_id="tenantA",
                    status="passed",
                    latency_ms=80 + idx * 2,
                    cost_usd=0.5 + idx * 0.05,
                    results=[{"assertion_id": "assert_latency", "passed": True}],
                    completed_at=completed,
                    created_at=completed,
                )
            )

    yield {
        "user": user,
        "graph_alpha": graph_id,
        "graph_beta": graph_beta,
        "session_factory": TestingSession,
        "engine": engine,
    }

    engine.dispose()


def test_metrics_summary(metrics_env):
    summary = metrics.get_metrics_summary(user=metrics_env["user"])
    assert summary["total_runs"] == 15
    assert summary["passed"] == 10
    assert summary["failed"] == 5
    assert summary["latency_p95"] >= summary["latency_p50"]


def test_metrics_by_graph_and_assertions(metrics_env):
    graph_id = metrics_env["graph_alpha"]
    user = metrics_env["user"]

    by_graph = metrics.get_metrics_by_graph(graph_id, user=user)
    assert by_graph["graph_id"] == graph_id
    assert by_graph["trend"] in {"degrading", "stable", "improving"}

    assertions = metrics.get_assertion_metrics(graph_id=graph_id, user=user)
    entries = {item["id"]: item for item in assertions["assertions"]}
    assert "assert_latency" in entries
    assert entries["assert_latency"]["passed"] > 0


def test_trends_and_latency_distribution(metrics_env):
    user = metrics_env["user"]
    graph_id = metrics_env["graph_alpha"]

    trends = metrics.get_trends(days=5, graph_id=graph_id, user=user)
    assert len(trends["trends"]) <= 5
    assert all("avg_latency_ms" in day for day in trends["trends"])

    distribution = metrics.get_latency_distribution(graph_id=graph_id, user=user)
    assert distribution["buckets"]
    assert distribution["counts"]
    assert distribution["mean"] > 0


def test_cost_breakdown(metrics_env):
    user = metrics_env["user"]
    breakdown = metrics.get_cost_breakdown(user=user)
    assert breakdown["total_cost_usd"] > 0
    assert len(breakdown["by_graph"]) == 2


def test_drift_detection(metrics_env):
    user = metrics_env["user"]
    graph_id = metrics_env["graph_alpha"]
    drift = metrics.detect_drift(graph_id=graph_id, threshold=0.05, user=user)
    assert drift["runs_analyzed"] >= 10
    assert drift["drift_detected"] is True
    assert drift["threshold"] == 0.05
    assert drift["metrics"]["pass_rate"]["drift"] > 0


def test_drift_detection_high_threshold(metrics_env):
    user = metrics_env["user"]
    graph_id = metrics_env["graph_alpha"]
    drift = metrics.detect_drift(graph_id=graph_id, threshold=1.0, user=user)
    assert drift["runs_analyzed"] >= 10
    assert drift["drift_detected"] is False
    assert drift["threshold"] == 1.0


def test_drift_detection_insufficient_data(metrics_env):
    user = metrics_env["user"]
    graph_id = metrics_env["graph_beta"]
    drift = metrics.detect_drift(graph_id=graph_id, user=user)
    assert drift["runs_analyzed"] < 10
    assert drift["drift_detected"] is False
    assert "Insufficient data" in drift["message"]


def test_metrics_handles_empty_dataset(metrics_env):
    engine = metrics_env["engine"]
    tenant_id = "tenantEmpty"
    with engine.begin() as conn:
        empty_graph_id = conn.execute(
            TestGraph.insert().values(
                name="Graph Empty",
                description="",
                content={},
                tenant_id=tenant_id,
            )
        ).inserted_primary_key[0]

    empty_user = User(
        id=99,
        email="empty@example.com",
        name="Empty User",
        role=Role.ADMIN,
        permissions=list(Permission),
        tenant_id=tenant_id,
    )

    summary = metrics.get_metrics_summary(user=empty_user)
    assert summary["total_runs"] == 0
    assert summary["passed"] == 0

    cost = metrics.get_cost_breakdown(user=empty_user)
    assert cost["total_cost_usd"] == 0
    assert cost["by_graph"] == []

    drift = metrics.detect_drift(graph_id=empty_graph_id, user=empty_user)
    assert drift["runs_analyzed"] == 0
    assert drift["drift_detected"] is False
    assert "Insufficient data" in drift["message"]
