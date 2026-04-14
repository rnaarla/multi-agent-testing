"""Regression tests for tenant-scoped data access (simulation surface)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import metadata
from app.services import simulation_service
from app.simulation.storage import SimulationPersistence


def _sqlite_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_list_simulation_runs_scoped_to_tenant(monkeypatch):
    SessionLocal = _sqlite_session_factory()
    monkeypatch.setattr(simulation_service, "SessionLocal", SessionLocal)
    persistence = SimulationPersistence(session_factory=SessionLocal)

    persistence.create_run(
        name="a-run",
        scenario="s",
        tenant_id="tenant-east",
        created_by=1,
        config={},
    )
    persistence.create_run(
        name="b-run",
        scenario="s",
        tenant_id="tenant-west",
        created_by=1,
        config={},
    )

    east = simulation_service.list_simulation_runs("tenant-east", limit=20, offset=0)
    west = simulation_service.list_simulation_runs("tenant-west", limit=20, offset=0)

    assert len(east) == 1
    assert len(west) == 1
    assert east[0]["name"] == "a-run"
    assert west[0]["name"] == "b-run"


def test_get_simulation_run_isolation_between_tenants(monkeypatch):
    SessionLocal = _sqlite_session_factory()
    monkeypatch.setattr(simulation_service, "SessionLocal", SessionLocal)
    persistence = SimulationPersistence(session_factory=SessionLocal)
    rec = persistence.create_run(
        name="secret",
        scenario="s",
        tenant_id="tenant-a",
        created_by=1,
        config={},
    )
    persistence.complete_run(rec.run_id, "completed", steps=0)

    assert simulation_service.get_simulation_run(rec.run_id, "tenant-a") is not None
    assert simulation_service.get_simulation_run(rec.run_id, "tenant-b") is None


def test_evaluate_simulation_run_requires_tenant_match(monkeypatch):
    SessionLocal = _sqlite_session_factory()
    monkeypatch.setattr(simulation_service, "SessionLocal", SessionLocal)
    persistence = SimulationPersistence(session_factory=SessionLocal)
    rec = persistence.create_run(
        name="e",
        scenario="s",
        tenant_id="tenant-a",
        created_by=1,
        config={},
    )
    persistence.log_event(
        run_id=rec.run_id,
        step_index=0,
        agent_id="x",
        event_type="agent_action",
        payload={},
    )
    persistence.complete_run(rec.run_id, "completed", steps=1)

    assert (
        simulation_service.evaluate_simulation_run(
            rec.run_id,
            "tenant-other",
            [{"id": "k", "type": "equals", "target": "run", "field": "status", "expected": "completed"}],
        )
        is None
    )
