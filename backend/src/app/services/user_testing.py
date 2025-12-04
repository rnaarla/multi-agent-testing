"""Utilities powering the user testing interface (timelines, run controls)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    return str(value)


def build_run_timeline(
    run: Dict[str, Any],
    agent_outputs: Iterable[Dict[str, Any]],
    assertions: Iterable[Dict[str, Any]],
    contract_violations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compose a chronological timeline for a test run."""

    events: List[Dict[str, Any]] = []

    started_at = run.get("started_at")
    if started_at:
        events.append(
            {
                "timestamp": _to_iso(started_at),
                "type": "run_started",
                "details": {
                    "mode": run.get("execution_mode"),
                    "seed": run.get("seed"),
                },
            }
        )

    for record in agent_outputs:
        events.append(
            {
                "timestamp": _to_iso(record.get("created_at")),
                "type": "agent_output",
                "node_id": record.get("node_id"),
                "agent_type": record.get("agent_type"),
                "latency_ms": record.get("latency_ms"),
                "tokens_in": record.get("tokens_in"),
                "tokens_out": record.get("tokens_out"),
                "provider": record.get("provider"),
            }
        )

    for record in assertions:
        events.append(
            {
                "timestamp": _to_iso(record.get("created_at")),
                "type": "assertion",
                "assertion_id": record.get("assertion_id"),
                "target_node": record.get("target_node"),
                "passed": record.get("passed"),
                "message": record.get("message"),
            }
        )

    for record in contract_violations:
        events.append(
            {
                "timestamp": _to_iso(record.get("created_at")),
                "type": "contract_violation",
                "contract_id": record.get("contract_id"),
                "source_node": record.get("source_node"),
                "target_node": record.get("target_node"),
                "field": record.get("field"),
            }
        )

    completed_at = run.get("completed_at")
    if completed_at:
        events.append(
            {
                "timestamp": _to_iso(completed_at),
                "type": "run_completed",
                "details": {
                    "status": run.get("status"),
                    "latency_ms": run.get("latency_ms"),
                    "cost_usd": run.get("cost_usd"),
                },
            }
        )

    events.sort(key=lambda item: item.get("timestamp") or "")
    return events


class RunControlAction(str, Enum):
    """Supported user testing actions on a run."""

    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    REPLAY = "replay"


@dataclass(frozen=True)
class ControlRecord:
    """Record of the last control action applied to a run."""

    run_id: int
    action: RunControlAction
    timestamp: str
    note: Optional[str] = None


class RunControlStore:
    """Thread-safe in-memory store for run control state."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._state: Dict[int, ControlRecord] = {}

    def apply(self, run_id: int, action: RunControlAction, note: Optional[str] = None) -> ControlRecord:
        record = ControlRecord(
            run_id=run_id,
            action=action,
            timestamp=datetime.now(UTC).isoformat(),
            note=note,
        )
        with self._lock:
            self._state[run_id] = record
        return record

    def get(self, run_id: int) -> Optional[ControlRecord]:
        with self._lock:
            return self._state.get(run_id)

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


_CONTROL_STORE = RunControlStore()


def get_control_store() -> RunControlStore:
    """Return the global run-control store singleton."""

    return _CONTROL_STORE

