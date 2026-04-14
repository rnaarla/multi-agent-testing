from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import metadata, SimulationEvent, SimulationRun, SimulationAgentState
from app.simulation import SimulationRunner, SimulationSpec, AgentSpec
from app.simulation.storage import SimulationPersistence


class DummyStream:
    def __init__(self):
        self.events = []

    def append(self, run_id, event):
        self.events.append((run_id, event))
        return str(len(self.events))


def build_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_simulation_runner_persists_events(monkeypatch):
    SessionLocal = build_test_session()
    persistence = SimulationPersistence(session_factory=SessionLocal)

    # Patch runner module to use the testing session factory
    monkeypatch.setattr("app.simulation.runner.SessionLocal", SessionLocal)

    runner = SimulationRunner(redis_url="redis://redis:6379/0", persistence=persistence)
    runner.redis_stream = DummyStream()

    spec = SimulationSpec(
        name="unit-test-sim",
        scenario="test-scenario",
        tenant_id="tenant-test",
        created_by=1,
        environment={
            "state": {"tickets_open": 2},
            "config": {},
        },
        steps=3,
        agents=[
            AgentSpec(
                agent_id="rule-agent",
                agent_type="rule",
                implementation="rule",
                config={
                    "rules": [
                        {
                            "name": "close-ticket",
                            "when": {"tickets_open": 2},
                            "action": {"type": "increment", "payload": {"key": "tickets_open", "amount": -1}},
                        }
                    ]
                },
            ),
            AgentSpec(
                agent_id="noop-agent",
                agent_type="observer",
                implementation="rule",
                config={"rules": []},
            ),
        ],
    )

    result = runner.run(spec)

    assert result["status"] == "completed"
    assert result["steps"] == spec.steps
    assert result["run_id"] > 0

    with SessionLocal() as session:
        events = session.execute(select(SimulationEvent)).fetchall()
        # 2 agents * steps
        assert len(events) == spec.steps * len(spec.agents)
        run_row = session.execute(select(SimulationRun)).mappings().one()
        assert run_row["status"] == "completed"
        states = session.execute(select(SimulationAgentState)).fetchall()
        assert len(states) == len(spec.agents)

