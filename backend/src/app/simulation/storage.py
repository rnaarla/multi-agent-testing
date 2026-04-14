"""Persistence helpers for simulation runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, List, Optional

import json

import redis
from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import SimulationRun, SimulationEvent, SimulationAgentState


@dataclass
class SimulationRunRecord:
    run_id: int
    redis_stream_key: str


class SimulationEventStream:
    """Redis-backed event stream using XADD."""

    def __init__(self, redis_url: str, stream_prefix: str = "sim:run"):
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.stream_prefix = stream_prefix

    def _key(self, run_id: int) -> str:
        return f"{self.stream_prefix}:{run_id}"

    def append(self, run_id: int, event: Dict[str, Any]) -> str:
        key = self._key(run_id)
        return self.redis.xadd(key, {"payload": json_dump(event)})

    def read(self, run_id: int, last_id: str = "0-0", count: int = 100) -> List[Dict[str, Any]]:
        key = self._key(run_id)
        try:
            entries = self.redis.xrange(key, min=last_id, max="+", count=count)
        except redis.RedisError:
            return []
        results: List[Dict[str, Any]] = []
        for entry_id, data in entries:
            payload = data.get("payload")
            if not payload:
                continue
            try:
                results.append({"id": entry_id, "payload": json_load(payload)})
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                results.append({"id": entry_id, "payload": None, "decode_error": str(exc)})
        return results


def json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


def json_load(raw: str) -> Dict[str, Any]:
    return json.loads(raw)


class SimulationPersistence:
    """Handles durable storage of simulation runs and events."""

    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory

    def create_run(
        self,
        *,
        name: str,
        scenario: str,
        tenant_id: str,
        created_by: Optional[int],
        config: Dict[str, Any],
    ) -> SimulationRunRecord:
        with self._session_factory() as session:
            now = datetime.now(UTC)
            result = session.execute(
                insert(SimulationRun).values(
                    name=name,
                    scenario=scenario,
                    status="running",
                    tenant_id=tenant_id,
                    config=config,
                    started_at=now,
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                )
            )
            run_id = result.inserted_primary_key[0]
            session.commit()
            return SimulationRunRecord(run_id=run_id, redis_stream_key=f"sim:run:{run_id}")

    def log_event(
        self,
        *,
        run_id: int,
        step_index: int,
        agent_id: Optional[str],
        event_type: str,
        payload: Dict[str, Any],
    ) -> int:
        with self._session_factory() as session:
            event_id = self.log_event_with_session(
                session=session,
                run_id=run_id,
                step_index=step_index,
                agent_id=agent_id,
                event_type=event_type,
                payload=payload,
            )
            session.commit()
            return event_id

    def log_event_with_session(
        self,
        *,
        session: Session,
        run_id: int,
        step_index: int,
        agent_id: Optional[str],
        event_type: str,
        payload: Dict[str, Any],
    ) -> int:
        result = session.execute(
            insert(SimulationEvent).values(
                run_id=run_id,
                step_index=step_index,
                agent_id=agent_id,
                event_type=event_type,
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )
        return result.inserted_primary_key[0]

    def upsert_agent_state(
        self,
        *,
        session: Session,
        run_id: int,
        agent_id: str,
        agent_type: str,
        state: Dict[str, Any],
        last_event_id: Optional[int],
    ) -> None:
        existing = session.execute(
            SimulationAgentState.select().where(
                (SimulationAgentState.c.run_id == run_id) & (SimulationAgentState.c.agent_id == agent_id)
            )
        ).fetchone()

        now = datetime.now(UTC)
        if existing:
            session.execute(
                update(SimulationAgentState)
                .where(SimulationAgentState.c.id == existing.id)
                .values(state=state, last_event_id=last_event_id, updated_at=now, agent_type=agent_type)
            )
        else:
            session.execute(
                insert(SimulationAgentState).values(
                    run_id=run_id,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    state=state,
                    last_event_id=last_event_id,
                    created_at=now,
                    updated_at=now,
                )
            )

    def complete_run(self, run_id: int, status: str, steps: int) -> None:
        with self._session_factory() as session:
            session.execute(
                update(SimulationRun)
                .where(SimulationRun.c.id == run_id)
                .values(
                    status=status,
                    steps_executed=steps,
                    completed_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()

