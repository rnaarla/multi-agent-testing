"""Post-run assertion evaluation over persisted simulation events."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Tuple

from app.runner.assertions import AssertionEngine

MAX_EVAL_ASSERTION_COUNT = 100


def build_simulation_assertion_context(
    events: List[Dict[str, Any]],
    run_detail: Dict[str, Any],
) -> Dict[str, Any]:
    """Map simulation DB events + run row into AssertionEngine context keys."""

    ctx: Dict[str, Any] = {
        "run": {
            "id": run_detail.get("id"),
            "status": run_detail.get("status"),
            "steps": run_detail.get("steps"),
            "scenario": run_detail.get("scenario"),
            "name": run_detail.get("name"),
        },
        "simulation": {
            "events": events,
            "event_count": len(events),
        },
    }
    for ev in events:
        aid = ev.get("agent_id")
        payload = ev.get("payload")
        if not aid or not isinstance(payload, dict):
            continue
        row = dict(payload)
        action = payload.get("action")
        if isinstance(action, dict):
            row["action_type"] = action.get("type")
        ctx[aid] = row
    return ctx


def evaluate_simulation_assertions(
    events: List[Dict[str, Any]],
    run_detail: Dict[str, Any],
    assertions: List[Dict[str, Any]],
) -> Tuple[bool, List[Dict[str, Any]]]:
    if len(assertions) > MAX_EVAL_ASSERTION_COUNT:
        raise ValueError(f"Too many assertions (max {MAX_EVAL_ASSERTION_COUNT})")

    engine = AssertionEngine()
    context = build_simulation_assertion_context(events, run_detail)
    results = engine.evaluate(assertions, context, [])
    payload = [asdict(r) for r in results]
    passed = all(r.passed for r in results)
    return passed, payload
