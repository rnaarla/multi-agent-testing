from types import SimpleNamespace

import app.services.run_persistence as persistence


def test_persist_trace_inserts_related_rows(monkeypatch):
    calls = []

    class FakeConn:
        def execute(self, statement, params=None):
            calls.append((statement, params))

    saved = []
    monkeypatch.setattr(persistence, "artifact_storage", SimpleNamespace(save_json=lambda run_id, name, payload: saved.append((run_id, name, payload))))

    trace = {
        "graph_hash": "abc",
        "agent_outputs": [{"agent": "planner"}],
        "assertion_results": [{"assertion": "latency"}],
        "contract_violations": [{"rule": "pii"}],
    }

    conn = FakeConn()
    persistence.persist_trace(conn, 42, trace)

    assert len(calls) == 4
    assert calls[1][1][0]["run_id"] == 42
    assert calls[2][1][0]["run_id"] == 42
    assert calls[3][1][0]["run_id"] == 42

    assert saved == [(42, "trace", trace)]
