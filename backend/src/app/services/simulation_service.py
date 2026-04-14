"""Service layer for launching and querying agent simulations."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc

from app.auth import User
from app.database import SessionLocal
from app.models import SimulationRun, SimulationEvent, SimulationAgentState
from app.simulation import SimulationRunner, SimulationSpec, AgentSpec
from app.simulation.storage import SimulationEventStream
from app.simulation.evaluation import evaluate_simulation_assertions
from app.simulation.validation import validate_simulation_payload


DEFAULT_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def _build_runner() -> SimulationRunner:
    return SimulationRunner(redis_url=DEFAULT_REDIS_URL)


def start_simulation_run(payload: Dict[str, Any], user: User) -> Dict[str, Any]:
    """Kick off a simulation run based on request payload."""

    validate_simulation_payload(payload)
    spec = _build_spec(payload, user)
    runner = _build_runner()
    result = runner.run(spec)
    return result


def _build_spec(payload: Dict[str, Any], user: User) -> SimulationSpec:
    env_cfg = payload.get("environment", {})
    agents_cfg = payload.get("agents", [])

    agent_specs: List[AgentSpec] = []
    for agent in agents_cfg:
        agent_specs.append(
            AgentSpec(
                agent_id=str(agent["id"]).strip(),
                agent_type=agent.get("type", "generic"),
                implementation=agent.get("implementation", "rule"),
                config=agent.get("config", {}),
                personality=agent.get("personality", {}),
                tags=agent.get("tags", []),
            )
        )

    spec = SimulationSpec(
        name=payload.get("name", "simulation"),
        scenario=payload.get("scenario", "default"),
        tenant_id=user.tenant_id,
        created_by=user.id,
        environment={
            "state": env_cfg.get("state", {}),
            "config": env_cfg.get("config", {}),
        },
        agents=agent_specs,
        steps=payload.get("steps", 10),
        metadata=payload.get("metadata", {}),
    )
    return spec


def list_simulation_runs(tenant_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(SimulationRun)
            .where(SimulationRun.c.tenant_id == tenant_id)
            .order_by(desc(SimulationRun.c.created_at))
            .offset(offset)
            .limit(limit)
        ).fetchall()

        return [
            {
                "id": row.id,
                "name": row.name,
                "scenario": row.scenario,
                "status": row.status,
                "steps": row.steps_executed,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "metadata": row.metadata,
            }
            for row in rows
        ]


def get_simulation_run(run_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    with SessionLocal() as session:
        row = session.execute(
            select(SimulationRun).where(
                (SimulationRun.c.id == run_id) & (SimulationRun.c.tenant_id == tenant_id)
            )
        ).fetchone()
        if not row:
            return None

        agents = session.execute(
            select(SimulationAgentState).where(SimulationAgentState.c.run_id == run_id)
        ).fetchall()

        return {
            "id": row.id,
            "name": row.name,
            "scenario": row.scenario,
            "status": row.status,
            "steps": row.steps_executed,
            "config": row.config,
            "metadata": row.metadata,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "agents": [
                {
                    "agent_id": agent.agent_id,
                    "agent_type": agent.agent_type,
                    "state": agent.state,
                    "updated_at": agent.updated_at,
                }
                for agent in agents
            ],
        }


def fetch_run_events(
    run_id: int,
    tenant_id: str,
    *,
    last_event_id: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        query = (
            select(SimulationEvent)
            .join(SimulationRun, SimulationRun.c.id == SimulationEvent.c.run_id)
            .where(
                SimulationEvent.c.run_id == run_id,
                SimulationRun.c.tenant_id == tenant_id,
            )
            .order_by(SimulationEvent.c.id)
        )
        if last_event_id is not None:
            query = query.where(SimulationEvent.c.id > last_event_id)
        query = query.limit(limit)
        rows = session.execute(query).fetchall()
        return [
            {
                "id": row.id,
                "step_index": row.step_index,
                "event_type": row.event_type,
                "agent_id": row.agent_id,
                "payload": row.payload,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def read_event_stream(run_id: int, last_id: str = "0-0", count: int = 100) -> List[Dict[str, Any]]:
    stream = SimulationEventStream(DEFAULT_REDIS_URL)
    return stream.read(run_id, last_id=last_id, count=count)


def evaluate_simulation_run(
    run_id: int,
    tenant_id: str,
    assertions: List[Dict[str, Any]],
    *,
    event_limit: int = 5000,
) -> Optional[Dict[str, Any]]:
    """Load persisted events and evaluate assertions (post-run / CI gate)."""

    run = get_simulation_run(run_id, tenant_id)
    if not run:
        return None
    events = fetch_run_events(run_id, tenant_id, last_event_id=None, limit=min(event_limit, 10_000))
    passed, results = evaluate_simulation_assertions(events, run, assertions)
    return {
        "run_id": run_id,
        "passed": passed,
        "assertion_count": len(results),
        "results": results,
        "events_used": len(events),
    }

