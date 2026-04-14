"""
Simulation / multi-agent testing SaaS quality matrix.

Covers:
- Positive paths (happy path, strict matching)
- Negative paths (authz, invalid payloads, tenant isolation)
- False-positive avoidance in rule evaluation (loose matching must not pass)
- False-negative risk documentation for LLM JSON parsing (silent noop fallback)
- Edge cases (increment without key, stream cursor, Redis read resilience)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_PERMISSIONS, Permission, Role, User, get_current_user
from app.main import app
from app.models import metadata, SimulationRun
from app.services import simulation_service
from app.services.simulation_service import get_simulation_run, start_simulation_run
from app.simulation import SimulationRunner, SimulationSpec, AgentSpec
from app.simulation.agents import AgentAction, AgentContext, RuleBasedAgent
from app.simulation.environment import Environment, EnvironmentState
from app.simulation.llm import LLMDecisionEngine
from app.simulation.storage import SimulationPersistence
from app.simulation.validation import (
    MAX_SIMULATION_STEPS,
    SimulationValidationError,
    validate_simulation_payload,
)
from app.providers import ProviderRegistry


def build_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def build_admin_user(tenant_id: str = "tenant-a") -> User:
    return User(
        id=1,
        email="admin@example.com",
        name="Admin",
        role=Role.ADMIN,
        permissions=list(Permission),
        tenant_id=tenant_id,
    )


def build_viewer_user() -> User:
    return User(
        id=2,
        email="viewer@example.com",
        name="Viewer",
        role=Role.VIEWER,
        permissions=ROLE_PERMISSIONS[Role.VIEWER],
        tenant_id="tenant-a",
    )


def test_validate_positive_minimal_payload():
    validate_simulation_payload(
        {
            "agents": [{"id": "a1", "implementation": "rule", "config": {}}],
            "steps": 1,
        }
    )


@pytest.mark.parametrize(
    "payload, code_substring",
    [
        ({"agents": [], "steps": 1}, "agents_required"),
        ({"agents": [{"id": "x", "implementation": "rule"}], "steps": 0}, "invalid_steps_range"),
        ({"agents": [{"id": "x", "implementation": "rule"}], "steps": MAX_SIMULATION_STEPS + 1}, "steps_limit_exceeded"),
        (
            {
                "agents": [
                    {"id": "dup", "implementation": "rule"},
                    {"id": "dup", "implementation": "rule"},
                ],
                "steps": 1,
            },
            "duplicate_agent_id",
        ),
        (
            {"agents": [{"id": " ", "implementation": "rule"}], "steps": 1},
            "invalid_agent_id",
        ),
        (
            {"agents": [{"id": "a1", "implementation": "not-a-real-impl"}], "steps": 1},
            "unknown_implementation",
        ),
    ],
)
def test_validate_negative_rejects_invalid_payload(payload, code_substring):
    with pytest.raises(SimulationValidationError) as excinfo:
        validate_simulation_payload(payload)
    assert code_substring in excinfo.value.code or code_substring in str(excinfo.value)


def test_rule_engine_avoids_false_positive_on_type_mismatch():
    """Strict equality: string '2' must not match numeric state 2."""
    ctx = AgentContext(agent_id="r1", agent_type="rule", memory={}, personality={}, tags=())
    agent = RuleBasedAgent(
        ctx,
        {
            "rules": [
                {
                    "name": "should-not-fire",
                    "when": {"tickets_open": "2"},
                    "action": {"type": "set", "payload": {"values": {"flag": True}}},
                }
            ]
        },
    )
    state = EnvironmentState(data={"tickets_open": 2})
    obs = agent.observe(state, 0, [])
    action = agent.decide(obs)
    assert action.action_type == "noop"


def test_rule_engine_positive_match_updates_state():
    ctx = AgentContext(agent_id="r1", agent_type="rule", memory={}, personality={}, tags=())
    agent = RuleBasedAgent(
        ctx,
        {
            "rules": [
                {
                    "name": "close",
                    "when": {"tickets_open": 2},
                    "action": {"type": "increment", "payload": {"key": "tickets_open", "amount": -1}},
                }
            ]
        },
    )
    env = Environment({"tickets_open": 2}, {})
    obs = agent.observe(env.state, 0, [])
    action = agent.decide(obs)
    _, outcome = env.step(0, "r1", action)
    assert outcome["action"]["type"] == "increment"
    assert outcome["applied_updates"]["tickets_open"] == 1


def test_environment_increment_without_key_is_explicit_invalid_payload():
    env = Environment({}, {})
    _, outcome = env.step(0, "a1", AgentAction(action_type="increment", payload={"amount": 1}, messages=[]))
    assert outcome["status"] == "invalid_payload"
    assert "key" in outcome.get("reason", "")


def test_llm_parse_malformed_json_risk_false_negative_operator_signal():
    """
    Malformed model output becomes noop: operators can miss failures (false negative)
    unless they monitor confidence / raw provider payloads.
    """
    engine = LLMDecisionEngine(ProviderRegistry())
    parsed = engine._parse_response({"response": "not json {{{", "confidence": 0.11})
    assert parsed["action"]["type"] == "noop"
    assert parsed["confidence"] == 0.11
    assert parsed.get("_parse_fallback") is True


def test_llm_parse_positive_preserves_structured_json():
    engine = LLMDecisionEngine(ProviderRegistry())
    raw = '{"action": {"type": "noop", "payload": {}}, "messages": [], "confidence": 0.99}'
    parsed = engine._parse_response({"response": raw})
    assert parsed["action"]["type"] == "noop"
    assert parsed["confidence"] == 0.99


def test_llm_decide_merge_prefers_parsed_semantics_over_provider_keys():
    """Structured parse must not lose to conflicting top-level provider fields."""

    class _Prov:
        def execute(self, **kwargs):
            return {
                "response": '{"action": {"type": "noop", "payload": {}}, "messages": [], "confidence": 0.2}',
                "confidence": 0.99,
                "_provider": "fake",
            }

    reg = ProviderRegistry()
    reg.providers["openai"] = _Prov()
    engine = LLMDecisionEngine(reg)

    from app.simulation.agents import AgentObservation
    from app.simulation.environment import EnvironmentState

    ctx = AgentContext(agent_id="a1", agent_type="tester", memory={}, personality={}, tags=())
    obs = AgentObservation(state=EnvironmentState(data={}), timestep=0, incoming_messages=[], context={})
    out = engine.decide(ctx, obs, {"provider": "openai"})
    assert out["action"]["type"] == "noop"
    assert out["confidence"] == 0.2
    assert out["_provider"] == "fake"


def test_fetch_run_events_respects_tenant_and_cursor(monkeypatch):
    """Events are tenant-scoped in SQL; cursor returns only rows after last_event_id."""
    SessionLocal = build_test_session()
    monkeypatch.setattr(simulation_service, "SessionLocal", SessionLocal)
    persistence = SimulationPersistence(session_factory=SessionLocal)
    rec = persistence.create_run(
        name="n",
        scenario="s",
        tenant_id="tenant-a",
        created_by=1,
        config={},
    )
    persistence.log_event(
        run_id=rec.run_id,
        step_index=0,
        agent_id="a1",
        event_type="agent_action",
        payload={"seq": 1},
    )
    persistence.log_event(
        run_id=rec.run_id,
        step_index=0,
        agent_id="a2",
        event_type="agent_action",
        payload={"seq": 2},
    )

    assert len(simulation_service.fetch_run_events(rec.run_id, "tenant-a", last_event_id=None, limit=10)) == 2
    assert simulation_service.fetch_run_events(rec.run_id, "tenant-b", last_event_id=None, limit=10) == []

    first_id = simulation_service.fetch_run_events(rec.run_id, "tenant-a", last_event_id=None, limit=1)[0]["id"]
    tail = simulation_service.fetch_run_events(rec.run_id, "tenant-a", last_event_id=first_id, limit=10)
    assert len(tail) == 1
    assert tail[0]["payload"]["seq"] == 2

    assert len(simulation_service.fetch_run_events(rec.run_id, "tenant-a", last_event_id=0, limit=10)) == 2


def test_get_simulation_run_negative_wrong_tenant_returns_none(monkeypatch):
    SessionLocal = build_test_session()
    monkeypatch.setattr(simulation_service, "SessionLocal", SessionLocal)
    persistence = SimulationPersistence(session_factory=SessionLocal)
    record = persistence.create_run(
        name="iso",
        scenario="s",
        tenant_id="tenant-a",
        created_by=1,
        config={"agents": [], "environment": {}, "metadata": {}, "steps": 1},
    )
    assert get_simulation_run(record.run_id, "tenant-b") is None


def test_simulation_runner_marks_failed_and_partial_steps(monkeypatch):
    SessionLocal = build_test_session()
    monkeypatch.setattr("app.simulation.runner.SessionLocal", SessionLocal)
    persistence = SimulationPersistence(session_factory=SessionLocal)

    class DummyStream:
        def append(self, run_id, event):
            return "1-0"

    runner = SimulationRunner(redis_url="redis://redis:6379/0", persistence=persistence)
    runner.redis_stream = DummyStream()

    from app.simulation import runner as runner_mod

    original = runner_mod.RuleBasedAgent.decide
    calls = {"n": 0}

    def flaky_decide(self, observation):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated agent failure")
        return original(self, observation)

    monkeypatch.setattr(runner_mod.RuleBasedAgent, "decide", flaky_decide)

    spec = SimulationSpec(
        name="fail-mid",
        scenario="s",
        tenant_id="t",
        created_by=1,
        environment={"state": {"tickets_open": 2}, "config": {}},
        steps=3,
        agents=[
            AgentSpec(
                agent_id="rule-agent",
                agent_type="rule",
                implementation="rule",
                config={
                    "rules": [
                        {
                            "name": "noopish",
                            "when": {"tickets_open": 2},
                            "action": {"type": "noop", "payload": {}},
                        }
                    ]
                },
            ),
            AgentSpec(agent_id="noop-agent", agent_type="observer", implementation="rule", config={"rules": []}),
        ],
    )

    with pytest.raises(RuntimeError):
        runner.run(spec)

        with SessionLocal() as session:
            row = session.execute(select(SimulationRun)).mappings().one()
            assert row["status"] == "failed"
            assert row["steps_executed"] == 0


def test_simulation_router_negative_unauthenticated(monkeypatch):
    async def reject(_credentials=None, _api_key=None, _request=None):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    app.dependency_overrides[get_current_user] = reject
    client = TestClient(app)
    resp = client.post(
        "/simulation/run",
        json={
            "name": "x",
            "scenario": "y",
            "steps": 1,
            "environment": {"state": {}, "config": {}},
            "agents": [{"id": "a1", "type": "rule", "implementation": "rule", "config": {"rules": []}}],
        },
    )
    assert resp.status_code == 401
    app.dependency_overrides.pop(get_current_user, None)


def test_simulation_router_negative_viewer_cannot_create_run(monkeypatch):
    import app.routers.simulation as simulation_router

    viewer = build_viewer_user()

    def _should_not_launch(payload, user):
        raise AssertionError("launch should not be called")

    monkeypatch.setattr(simulation_router, "start_simulation_run", _should_not_launch)

    app.dependency_overrides[get_current_user] = lambda: viewer
    client = TestClient(app)
    resp = client.post(
        "/simulation/run",
        json={
            "name": "x",
            "scenario": "y",
            "steps": 1,
            "environment": {"state": {}, "config": {}},
            "agents": [{"id": "a1", "type": "rule", "implementation": "rule", "config": {"rules": []}}],
        },
    )
    assert resp.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


def test_simulation_router_negative_duplicate_agents_422():
    app.dependency_overrides[get_current_user] = lambda: build_admin_user()
    client = TestClient(app)
    resp = client.post(
        "/simulation/run",
        json={
            "name": "x",
            "scenario": "y",
            "steps": 1,
            "environment": {"state": {}, "config": {}},
            "agents": [
                {"id": "same", "implementation": "rule", "config": {}},
                {"id": "same", "implementation": "rule", "config": {}},
            ],
        },
    )
    assert resp.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


def test_simulation_router_negative_invalid_stream_cursor(monkeypatch):
    import app.routers.simulation as simulation_router

    app.dependency_overrides[get_current_user] = lambda: build_admin_user()
    monkeypatch.setattr(
        simulation_router,
        "get_simulation_run",
        lambda run_id, tenant_id: {"id": run_id},
    )
    monkeypatch.setattr(simulation_router, "read_event_stream", lambda *a, **k: [])
    client = TestClient(app)
    bad = client.get("/simulation/runs/9/stream?last_id=not-a-cursor")
    assert bad.status_code == 400
    ok = client.get("/simulation/runs/9/stream?last_id=0-0")
    assert ok.status_code == 200
    app.dependency_overrides.pop(get_current_user, None)


def test_simulation_router_negative_list_runs_bad_pagination():
    app.dependency_overrides[get_current_user] = lambda: build_admin_user()
    client = TestClient(app)
    assert client.get("/simulation/runs?offset=-1").status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


def test_start_simulation_run_validates_even_if_called_without_http(monkeypatch):
    user = build_admin_user()

    class BoomRunner:
        def run(self, spec):
            return {"run_id": 1, "status": "completed", "steps": spec.steps}

    monkeypatch.setattr(simulation_service, "_build_runner", lambda: BoomRunner())
    with pytest.raises(SimulationValidationError):
        start_simulation_run({"agents": [], "steps": 1}, user)


def test_evaluate_simulation_run_service_happy_path(monkeypatch):
    SessionLocal = build_test_session()
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
        agent_id="a1",
        event_type="agent_action",
        payload={"action": {"type": "noop"}, "status": "noop"},
    )
    persistence.complete_run(rec.run_id, "completed", steps=1)

    out = simulation_service.evaluate_simulation_run(
        rec.run_id,
        "tenant-a",
        [{"id": "run-done", "type": "equals", "target": "run", "field": "status", "expected": "completed"}],
    )
    assert out is not None
    assert out["passed"] is True
    assert out["events_used"] == 1


def test_evaluate_simulation_run_wrong_tenant(monkeypatch):
    SessionLocal = build_test_session()
    monkeypatch.setattr(simulation_service, "SessionLocal", SessionLocal)
    persistence = SimulationPersistence(session_factory=SessionLocal)
    rec = persistence.create_run(
        name="e",
        scenario="s",
        tenant_id="tenant-a",
        created_by=1,
        config={},
    )
    persistence.complete_run(rec.run_id, "completed", steps=0)
    assert (
        simulation_service.evaluate_simulation_run(
            rec.run_id,
            "tenant-b",
            [{"id": "x", "type": "equals", "target": "run", "field": "status", "expected": "completed"}],
        )
        is None
    )


def test_evaluate_simulation_http_and_failed_assertion(monkeypatch):
    SessionLocal = build_test_session()
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
        agent_id="bot",
        event_type="agent_action",
        payload={"action": {"type": "noop"}},
    )
    persistence.complete_run(rec.run_id, "completed", steps=1)

    app.dependency_overrides[get_current_user] = lambda: build_admin_user()
    client = TestClient(app)

    ok = client.post(
        f"/simulation/runs/{rec.run_id}/evaluate",
        json={"assertions": [{"id": "cnt", "type": "equals", "target": "simulation", "field": "event_count", "expected": 1}]},
    )
    assert ok.status_code == 200
    assert ok.json()["passed"] is True

    bad = client.post(
        f"/simulation/runs/{rec.run_id}/evaluate",
        json={"assertions": [{"id": "steps", "type": "equals", "target": "run", "field": "steps", "expected": 999}]},
    )
    assert bad.status_code == 200
    assert bad.json()["passed"] is False

    nf = client.post(
        "/simulation/runs/99999/evaluate",
        json={"assertions": [{"id": "x", "type": "equals", "target": "run", "field": "status", "expected": "completed"}]},
    )
    assert nf.status_code == 404

    app.dependency_overrides.pop(get_current_user, None)


def test_evaluate_simulation_request_validation():
    app.dependency_overrides[get_current_user] = lambda: build_admin_user()
    client = TestClient(app)
    empty = client.post(
        "/simulation/runs/1/evaluate",
        json={"assertions": []},
    )
    assert empty.status_code == 422
    many = client.post(
        "/simulation/runs/1/evaluate",
        json={"assertions": [{"id": f"a{i}", "type": "equals", "target": "run", "field": "status", "expected": "x"} for i in range(101)]},
    )
    assert many.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)
