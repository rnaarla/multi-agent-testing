from datetime import UTC, datetime, timedelta

from app.services.user_testing import (
    RunControlAction,
    RunControlStore,
    build_run_timeline,
)


def test_build_run_timeline_orders_events():
    base = datetime.now(UTC)
    run = {
        "started_at": base - timedelta(seconds=5),
        "completed_at": base,
        "status": "passed",
        "latency_ms": 123.4,
        "cost_usd": 0.42,
        "execution_mode": "simulation",
        "seed": 123,
    }

    agent_outputs = [
        {
            "created_at": base - timedelta(seconds=4),
            "node_id": "n1",
            "agent_type": "llm",
            "latency_ms": 10.0,
            "tokens_in": 100,
            "tokens_out": 50,
            "provider": "mock",
        },
        {
            "created_at": base - timedelta(seconds=2),
            "node_id": "n2",
            "agent_type": "tool",
            "latency_ms": 12.0,
            "tokens_in": 10,
            "tokens_out": 5,
            "provider": "mock",
        },
    ]

    assertions = [
        {
            "created_at": base - timedelta(seconds=1),
            "assertion_id": "assert-latency",
            "target_node": "n2",
            "passed": True,
            "message": "Latency within thresholds",
        }
    ]

    violations = [
        {
            "created_at": base - timedelta(seconds=3),
            "contract_id": "c1",
            "source_node": "n1",
            "target_node": "n2",
            "field": "payload",
        }
    ]

    timeline = build_run_timeline(run, agent_outputs, assertions, violations)
    event_types = [event["type"] for event in timeline]

    assert event_types == [
        "run_started",
        "agent_output",
        "contract_violation",
        "agent_output",
        "assertion",
        "run_completed",
    ]
    assert timeline[0]["details"]["mode"] == "simulation"
    assert timeline[-1]["details"]["status"] == "passed"


def test_run_control_store_tracks_actions():
    store = RunControlStore()
    record = store.apply(run_id=99, action=RunControlAction.PAUSE, note="QA hold")

    retrieved = store.get(99)
    assert retrieved == record
    assert retrieved.note == "QA hold"

    store.reset()
    assert store.get(99) is None

