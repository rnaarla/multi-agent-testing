"""
Test run execution API router.

Provides:
- Synchronous and asynchronous graph execution
- Run status tracking
- Results retrieval with full traces
- Webhook configuration
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends, Request, WebSocket
from pydantic import BaseModel
from sqlalchemy import and_

from app.services.executor import execute_graph
from app.services.run_persistence import persist_trace
from app.database import SessionLocal
from app.models import TestRun, TestGraph, TestGraphVersion
from app.utils.locks import redis_lock, RedisLockError
from app.workers.tasks import _mark_cancelled
from app.auth import User, Permission, permission_dependency, log_audit

router = APIRouter()


class ExecutionConfig(BaseModel):
    """Configuration for test execution."""
    provider: str = "mock"
    model: Optional[str] = None
    seed: Optional[int] = None
    mode: str = "normal"  # normal, replay, chaos, debug
    webhook_url: Optional[str] = None
    chaos_config: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[int] = None
    tenant_id: Optional[str] = None
    governance: Optional[Dict[str, Any]] = None


class AsyncExecutionResponse(BaseModel):
    """Response for async execution request."""
    run_id: str
    status: str
    message: str


def _get_graph_for_tenant(db, graph_id: int, tenant_id: str):
    return db.execute(
        TestGraph.select().where(
            and_(TestGraph.c.id == graph_id, TestGraph.c.tenant_id == tenant_id)
        )
    ).fetchone()


def _get_run_for_tenant(db, run_id: int, tenant_id: str):
    return db.execute(
        TestRun.select().where(
            and_(TestRun.c.id == run_id, TestRun.c.tenant_id == tenant_id)
        )
    ).fetchone()


@router.post("/{graph_id}/execute")
async def run_graph_sync(
    graph_id: int,
    config: Optional[ExecutionConfig] = None,
    request: Request = None,
    user: User = Depends(permission_dependency(Permission.RUN_CREATE))
):
    """Execute a test graph synchronously."""
    db = SessionLocal()
    config_model = config or ExecutionConfig()
    config_dict = config_model.model_dump()

    try:
        graph = _get_graph_for_tenant(db, graph_id, user.tenant_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph not found")

        graph_version = graph.version or 1
        config_model = config or ExecutionConfig()
        config_dict = config_model.model_dump()
        tenant_id = config_dict.get("tenant_id") or user.tenant_id
        config_dict["tenant_id"] = tenant_id

        lock_key = f"graph:{graph_id}:run"
        try:
            with redis_lock(lock_key, ttl=30):
                trace = execute_graph(graph.content, config_dict)
        except RedisLockError as exc:
            raise HTTPException(status_code=429, detail=str(exc))

        trace_dict = trace.to_dict()
        started_dt = datetime.fromisoformat(trace.started_at)
        completed_dt = datetime.fromisoformat(trace.completed_at) if trace.completed_at else None
        result_record = {
            "graph_id": graph_id,
            "graph_version": graph_version,
            "tenant_id": tenant_id,
            "status": trace.status,
            "results": trace_dict,
            "latency_ms": trace.total_latency_ms,
            "cost_usd": trace.total_cost_usd,
            "execution_mode": trace.mode.value,
            "seed": trace.seed,
            "provider": config_dict.get("provider"),
            "model": config_dict.get("model"),
            "started_at": started_dt,
            "completed_at": completed_dt,
            "metadata": {"execution_config": config_dict},
        }
        run_result = db.execute(TestRun.insert().values(**result_record))
        run_id = run_result.inserted_primary_key[0]
        persist_trace(db.connection(), run_id, trace_dict)
        db.commit()

        response = {
            "run_id": run_id,
            "status": trace.status,
            "latency_ms": trace.total_latency_ms,
            "cost_usd": trace.total_cost_usd,
            "assertions": trace_dict.get("assertion_results", []),
            "contract_violations": trace_dict.get("contract_violations", []),
            "agent_outputs": trace_dict.get("agent_outputs", []),
            "trace": trace_dict,
        }
        if request:
            await log_audit(
                user=user,
                action="run.execute.sync",
                resource_type="run",
                resource_id=run_id,
                details={
                    "graph_id": graph_id,
                    "graph_version": graph_version,
                    "mode": config_dict.get("mode", "normal")
                },
                request=request
            )
        return response
    finally:
        db.close()


@router.post("/{graph_id}/execute/async", response_model=AsyncExecutionResponse)
async def run_graph_async(
    graph_id: int,
    config: Optional[ExecutionConfig] = None,
    request: Request = None,
    user: User = Depends(permission_dependency(Permission.RUN_CREATE))
):
    """Queue a test graph for asynchronous execution."""
    db = SessionLocal()

    try:
        graph = _get_graph_for_tenant(db, graph_id, user.tenant_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph not found")

        graph_version = graph.version or 1
        config_model = config or ExecutionConfig()
        config_dict = config_model.model_dump()
        tenant_id = config_dict.get("tenant_id") or user.tenant_id
        config_dict["tenant_id"] = tenant_id

        db_run = db.execute(TestRun.insert().values(
            graph_id=graph_id,
            graph_version=graph_version,
            tenant_id=tenant_id,
            status="queued",
            results={},
            latency_ms=0,
            cost_usd=0,
            execution_mode=config_model.mode,
            seed=config_model.seed,
            webhook_url=config_model.webhook_url,
            provider=config_model.provider,
            model=config_model.model,
            metadata={"execution_config": config_dict},
        ))
        run_db_id = db_run.inserted_primary_key[0]
        db.commit()

        try:
            from app.workers.tasks import execute_graph_async
            execute_graph_async.delay(
                graph_id=graph_id,
                graph_content=graph.content,
                run_id=str(run_db_id),
                webhook_url=config_model.webhook_url,
                execution_config=config_dict,
            )
        except ImportError:
            return AsyncExecutionResponse(
                run_id=str(uuid.uuid4()),
                status="warning",
                message="Async workers not available. Use sync endpoint."
            )

        if request:
            await log_audit(
                user=user,
                action="run.execute.async",
                resource_type="run",
                resource_id=run_db_id,
                details={
                    "graph_id": graph_id,
                    "graph_version": graph_version,
                    "mode": config_model.mode
                },
                request=request
            )

        return AsyncExecutionResponse(
            run_id=str(run_db_id),
            status="queued",
            message="Execution queued. Check status with GET /runs/{run_id}"
        )
    finally:
        db.close()


@router.get("/")
def list_runs(
    graph_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(permission_dependency(Permission.RUN_READ))
):
    """List test runs with optional filtering."""
    db = SessionLocal()

    try:
        query = TestRun.select().where(TestRun.c.tenant_id == user.tenant_id)
        if graph_id:
            query = query.where(TestRun.c.graph_id == graph_id)
        if status:
            query = query.where(TestRun.c.status == status)

        rows = db.execute(query.limit(limit).offset(offset)).fetchall()
        return [
            {
                "id": r.id,
                "graph_id": r.graph_id,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "cost_usd": r.cost_usd
            }
            for r in rows
        ]
    finally:
        db.close()


@router.get("/{run_id}")
def get_run(
    run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ))
):
    """Get detailed information about a specific run."""
    db = SessionLocal()

    try:
        run = _get_run_for_tenant(db, run_id, user.tenant_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        return {
            "id": run.id,
            "graph_id": run.graph_id,
            "status": run.status,
            "results": run.results,
            "latency_ms": run.latency_ms,
            "cost_usd": run.cost_usd
        }
    finally:
        db.close()


@router.get("/{run_id}/trace")
def get_run_trace(
    run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ))
):
    """Get full execution trace for a run."""
    db = SessionLocal()

    try:
        run = _get_run_for_tenant(db, run_id, user.tenant_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        results = run.results or {}
        trace_blob = results.get("trace") if isinstance(results, dict) else {}
        if not trace_blob and isinstance(results, dict):
            trace_blob = results

        return {
            "run_id": run.id,
            "graph_id": run.graph_id,
            "status": run.status,
            "trace": trace_blob,
            "agent_outputs": trace_blob.get("agent_outputs", []),
            "assertions": trace_blob.get("assertion_results") or trace_blob.get("assertions", []),
            "contract_violations": trace_blob.get("contract_violations", [])
        }
    finally:
        db.close()


@router.delete("/{run_id}")
async def delete_run(
    run_id: int,
    request: Request,
    user: User = Depends(permission_dependency(Permission.RUN_CANCEL))
):
    """Delete a run record."""
    db = SessionLocal()

    try:
        result = db.execute(
            TestRun.delete().where(
                and_(TestRun.c.id == run_id, TestRun.c.tenant_id == user.tenant_id)
            )
        )
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Run not found")

        await log_audit(
            user=user,
            action="run.delete",
            resource_type="run",
            resource_id=run_id,
            details={},
            request=request
        )
        return {"deleted": run_id}
    finally:
        db.close()


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: int,
    request: Request,
    user: User = Depends(permission_dependency(Permission.RUN_CANCEL))
):
    """Request cancellation for a queued or running run."""
    db = SessionLocal()

    try:
        run = _get_run_for_tenant(db, run_id, user.tenant_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        if run.status in {"completed", "failed", "error", "cancelled"}:
            return {"run_id": run_id, "status": run.status}

        _mark_cancelled(str(run_id))
        db.execute(
            TestRun.update()
            .where(TestRun.c.id == run_id)
            .values(status="cancelled")
        )
        db.commit()

        await log_audit(
            user=user,
            action="run.cancel",
            resource_type="run",
            resource_id=run_id,
            details={},
            request=request
        )
        return {"run_id": run_id, "status": "cancelled"}
    finally:
        db.close()


@router.post("/{run_id}/replay")
async def replay_run(
    run_id: int,
    overrides: Optional[ExecutionConfig] = None,
    request: Request = None,
    user: User = Depends(permission_dependency(Permission.RUN_CREATE))
):
    """Replay a historical run deterministically using stored graph version."""
    db = SessionLocal()

    try:
        original = _get_run_for_tenant(db, run_id, user.tenant_id)
        if not original:
            raise HTTPException(status_code=404, detail="Run not found")

        graph_version = db.execute(
            TestGraphVersion.select()
            .where(TestGraphVersion.c.graph_id == original.graph_id)
            .where(TestGraphVersion.c.version == original.graph_version)
            .where(TestGraphVersion.c.tenant_id == user.tenant_id)
        ).fetchone()
        if not graph_version:
            raise HTTPException(status_code=404, detail="Graph version not found")

        base_config = ExecutionConfig(
            provider=original.provider or "mock",
            model=original.model,
            seed=original.seed,
            mode="replay",
        )
        if overrides:
            base_config = base_config.model_copy(
                update=overrides.model_dump(exclude_unset=True)
            )

        trace = execute_graph(graph_version.content, base_config.model_dump())
        run_result = db.execute(TestRun.insert().values(
            graph_id=original.graph_id,
            graph_version=graph_version.version,
            tenant_id=original.tenant_id,
            status=trace.status,
            results=trace.to_dict(),
            latency_ms=trace.total_latency_ms,
            cost_usd=trace.total_cost_usd,
            execution_mode="replay",
            seed=trace.seed,
        ))
        new_run_id = run_result.inserted_primary_key[0]
        persist_trace(db.connection(), new_run_id, trace.to_dict())
        db.commit()

        response = {"original_run": run_id, "replay_run": new_run_id, "status": trace.status}
        if request:
            await log_audit(
                user=user,
                action="run.replay",
                resource_type="run",
                resource_id=new_run_id,
                details={"original_run": run_id},
                request=request
            )
        return response
    finally:
        db.close()


@router.get("/{run_id}/diff/{other_run_id}")
def diff_runs(
    run_id: int,
    other_run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
):
    """Produce a simple diff between two run result payloads."""

    db = SessionLocal()
    try:
        primary = _get_run_for_tenant(db, run_id, user.tenant_id)
        secondary = _get_run_for_tenant(db, other_run_id, user.tenant_id)
        if not primary or not secondary:
            raise HTTPException(status_code=404, detail="Run not found")

        primary_map = dict(primary._mapping) if hasattr(primary, "_mapping") else {}
        secondary_map = dict(secondary._mapping) if hasattr(secondary, "_mapping") else {}

        results_a = primary_map.get("results") or {}
        results_b = secondary_map.get("results") or {}
        diff = []

        for field in ["status", "latency_ms", "cost_usd", "execution_mode", "provider", "model"]:
            primary_val = primary_map.get(field)
            secondary_val = secondary_map.get(field)
            diff.append(
                {
                    "field": field,
                    "primary": primary_val,
                    "secondary": secondary_val,
                    "changed": primary_val != secondary_val,
                }
            )

        keys = set(results_a.keys()) | set(results_b.keys())
        for key in keys:
            if results_a.get(key) != results_b.get(key):
                diff.append(
                    {
                        "field": key,
                        "primary": results_a.get(key),
                        "secondary": results_b.get(key),
                    }
                )
        return {"primary": run_id, "secondary": other_run_id, "diff": diff}
    finally:
        db.close()


@router.websocket("/stream/{run_id}")
async def stream_run_logs(websocket: WebSocket, run_id: int):
    """Stream run logs and node outputs to the Test Run Explorer."""

    await websocket.accept()
    db = SessionLocal()
    try:
        run = db.execute(TestRun.select().where(TestRun.c.id == run_id)).fetchone()
        if not run:
            await websocket.send_json({"event": "error", "message": "Run not found"})
            await websocket.close()
            return

        results = run.results or {}
        log_entries = results.get("logs") or []
        agent_outputs = results.get("agent_outputs") or []

        for idx, entry in enumerate(log_entries):
            payload = entry if isinstance(entry, dict) else {"message": entry}
            await websocket.send_json({"event": "log", "index": idx, "payload": payload})

        for idx, output in enumerate(agent_outputs):
            await websocket.send_json(
                {
                    "event": "node_output",
                    "index": idx,
                    "node_id": output.get("node_id"),
                    "payload": output,
                }
            )

        await websocket.send_json({"event": "complete"})
    finally:
        db.close()
        await websocket.close()
