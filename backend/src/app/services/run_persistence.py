"""Utilities for persisting execution traces and artifacts."""

from typing import Sequence

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from app.models import (
    ExecutionTrace as ExecutionTraceTable,
    AgentOutput as AgentOutputTable,
    AssertionResult as AssertionResultTable,
    ContractViolation as ContractViolationTable,
)
from app.services.artifact_storage import artifact_storage


def _bulk_insert(conn: Connection, table, rows: Sequence[dict]) -> None:
    if not rows:
        return
    conn.execute(insert(table), rows)


def persist_trace(conn: Connection, run_id: int, trace_dict: dict) -> None:
    """Persist execution artifacts for a run."""

    conn.execute(
        ExecutionTraceTable.insert().values(
            run_id=run_id,
            trace_data=trace_dict,
            graph_hash=trace_dict.get("graph_hash"),
        )
    )

    agent_rows = trace_dict.get("agent_outputs", [])
    for row in agent_rows:
        row["run_id"] = run_id
    _bulk_insert(conn, AgentOutputTable, agent_rows)

    assertion_rows = trace_dict.get("assertion_results", [])
    for row in assertion_rows:
        row["run_id"] = run_id
    _bulk_insert(conn, AssertionResultTable, assertion_rows)

    violation_rows = trace_dict.get("contract_violations", [])
    for row in violation_rows:
        row["run_id"] = run_id
    _bulk_insert(conn, ContractViolationTable, violation_rows)

    artifact_storage.save_json(run_id, "trace", trace_dict)
