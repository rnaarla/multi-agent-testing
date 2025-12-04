from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select

from app.auth import Permission, User, log_audit, permission_dependency
from app.database import SessionLocal
from app.models import (
    AgentOutput,
    AssertionResult,
    ContractViolation,
    ExecutionTrace,
    SafetyViolation,
    TestRun,
)
from app.runner.run_graph import ExecutionMode
from app.services.executor import execute_graph
from app.services.user_testing import (
    RunControlAction,
    build_run_timeline,
    get_control_store,
)


router = APIRouter()


class SimulationRequest(BaseModel):
    graph: Dict[str, Any]
    execution_config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class RunControlRequest(BaseModel):
    action: RunControlAction
    note: Optional[str] = None


def _ensure_tenant(run_row: Dict[str, Any], user: User) -> None:
    if run_row.get("tenant_id") != user.tenant_id:
        raise HTTPException(status_code=404, detail="Run not found")


def _row_to_dict(row) -> Dict[str, Any]:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if isinstance(row, dict):
        return row
    return dict(row)


@router.get("/runs/history")
def run_history(
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
):
    """Return recent runs for the QA review interface."""

    db = SessionLocal()
    try:
        query = select(TestRun).where(TestRun.c.tenant_id == user.tenant_id)
        if status:
            query = query.where(TestRun.c.status == status)
        query = query.order_by(desc(TestRun.c.created_at)).limit(limit)
        rows = db.execute(query).fetchall()
        runs: List[Dict[str, Any]] = []
        for row in rows:
            data = _row_to_dict(row)
            runs.append(
                {
                    "id": data["id"],
                    "graph_id": data["graph_id"],
                    "status": data["status"],
                    "execution_mode": data.get("execution_mode"),
                    "latency_ms": data.get("latency_ms"),
                    "cost_usd": data.get("cost_usd"),
                    "created_at": data.get("created_at").isoformat() if data.get("created_at") else None,
                    "completed_at": data.get("completed_at").isoformat() if data.get("completed_at") else None,
                }
            )
        return {"runs": runs, "count": len(runs)}
    finally:
        db.close()


@router.get("/runs/{run_id}/timeline")
def run_timeline(
    run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
):
    """Produce an execution timeline for a run."""

    db = SessionLocal()
    try:
        run = db.execute(
            select(TestRun).where(
                and_(TestRun.c.id == run_id, TestRun.c.tenant_id == user.tenant_id)
            )
        ).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        run_data = _row_to_dict(run)

        agent_outputs = [
            _row_to_dict(row)
            for row in db.execute(
                select(AgentOutput).where(AgentOutput.c.run_id == run_id).order_by(AgentOutput.c.created_at)
            ).fetchall()
        ]
        assertions = [
            _row_to_dict(row)
            for row in db.execute(
                select(AssertionResult).where(AssertionResult.c.run_id == run_id).order_by(AssertionResult.c.created_at)
            ).fetchall()
        ]
        violations = [
            _row_to_dict(row)
            for row in db.execute(
                select(ContractViolation).where(ContractViolation.c.run_id == run_id).order_by(ContractViolation.c.created_at)
            ).fetchall()
        ]

        timeline = build_run_timeline(run_data, agent_outputs, assertions, violations)
        return {
            "run_id": run_id,
            "timeline": timeline,
            "summary": {
                "status": run_data.get("status"),
                "latency_ms": run_data.get("latency_ms"),
                "cost_usd": run_data.get("cost_usd"),
                "assertions_passed": run_data.get("assertions_passed"),
                "assertions_failed": run_data.get("assertions_failed"),
                "contract_violations": run_data.get("contract_violations"),
            },
        }
    finally:
        db.close()


@router.get("/runs/{run_id}/assertions")
def run_assertions(
    run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
):
    """Return assertion outcomes for a run."""

    db = SessionLocal()
    try:
        run = db.execute(
            select(TestRun.c.id, TestRun.c.tenant_id).where(TestRun.c.id == run_id)
        ).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        _ensure_tenant(_row_to_dict(run), user)

        rows = db.execute(
            select(AssertionResult).where(AssertionResult.c.run_id == run_id).order_by(AssertionResult.c.created_at)
        ).fetchall()
        assertions = [
            {
                "assertion_id": row.assertion_id,
                "assertion_type": row.assertion_type,
                "target_node": row.target_node,
                "passed": row.passed,
                "message": row.message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        return {"run_id": run_id, "assertions": assertions}
    finally:
        db.close()


@router.get("/runs/{run_id}/compliance")
def run_compliance(
    run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
):
    """Return safety/compliance violations for a run."""

    db = SessionLocal()
    try:
        run = db.execute(
            select(TestRun.c.id, TestRun.c.tenant_id).where(TestRun.c.id == run_id)
        ).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        _ensure_tenant(_row_to_dict(run), user)

        rows = db.execute(
            select(SafetyViolation).where(SafetyViolation.c.run_id == run_id).order_by(SafetyViolation.c.created_at)
        ).fetchall()
        violations = [
            {
                "violation_type": row.violation_type,
                "severity": row.severity,
                "details": row.details,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        return {"run_id": run_id, "violations": violations}
    finally:
        db.close()


@router.post("/runs/{run_id}/control")
async def run_control(
    run_id: int,
    payload: RunControlRequest,
    request: Request,
    user: User = Depends(permission_dependency(Permission.RUN_CANCEL)),
):
    """Apply a control action (pause/resume/stop/replay) to a run."""

    db = SessionLocal()
    try:
        run = db.execute(
            select(TestRun.c.id, TestRun.c.tenant_id, TestRun.c.status).where(TestRun.c.id == run_id)
        ).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        run_data = _row_to_dict(run)
        _ensure_tenant(run_data, user)

        store = get_control_store()
        record = store.apply(run_id, payload.action, payload.note)

        await log_audit(
            user=user,
            action=f"run.{payload.action.value}",
            resource_type="test_run",
            resource_id=run_id,
            details={"note": payload.note, "status": run_data.get("status")},
            request=request,
        )

        return {"run_id": run_id, "action": record.action.value, "timestamp": record.timestamp, "note": record.note}
    finally:
        db.close()


@router.post("/simulations")
def simulate_run(
    payload: SimulationRequest,
    user: User = Depends(permission_dependency(Permission.RUN_CREATE)),
):
    """Execute a graph simulation without persisting results."""

    config = dict(payload.execution_config or {})
    config["mode"] = config.get("mode") or ExecutionMode.SIMULATION.value
    if config["mode"] == ExecutionMode.NORMAL.value:
        config["mode"] = ExecutionMode.SIMULATION.value

    trace = execute_graph(payload.graph, execution_config=config)
    result = trace.to_dict()
    result["mode"] = config["mode"]
    result["simulated"] = True
    result["tenant_id"] = user.tenant_id
    return {"trace": result}


@router.get("/runs/{run_id}/replay")
def replay_trace(
    run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
):
    """Return the persisted execution trace for replay."""

    db = SessionLocal()
    try:
        row = db.execute(
            select(ExecutionTrace.c.trace_data, TestRun.c.tenant_id)
            .join(TestRun, ExecutionTrace.c.run_id == TestRun.c.id)
            .where(ExecutionTrace.c.run_id == run_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Replay trace not found")

        trace_data = row.trace_data if hasattr(row, "trace_data") else row[0]
        tenant_id = row.tenant_id if hasattr(row, "tenant_id") else row[1]
        if tenant_id != user.tenant_id:
            raise HTTPException(status_code=404, detail="Replay trace not found")

        return {"run_id": run_id, "trace": trace_data}
    finally:
        db.close()

