"""
Celery-based background worker for async graph execution.

Provides:
- Background job queue for long-running tests
- Webhook notifications on completion
- Job status tracking
- Retry with exponential backoff
"""

from celery import Celery, states
from celery.signals import task_revoked
from typing import Dict, Any, Optional
import os
import requests
from datetime import UTC, datetime, timedelta
import redis
import structlog

from app.observability.metrics import record_run_outcome, worker_job_active
from app.observability.tracing import get_tracer

# Configure Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_redis_client = redis.Redis.from_url(REDIS_URL)

celery_app = Celery(
    "agent_testing",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.workers.tasks"]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3000,  # 50 min soft limit
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=86400,  # Results expire after 24 hours
)

# Task routing
celery_app.conf.task_routes = {
    "app.workers.tasks.execute_graph_async": {"queue": "graph_execution"},
    "app.workers.tasks.send_webhook": {"queue": "notifications"},
}

# Track cancellation requests via Redis keys
_CANCEL_KEY_PREFIX = "cancelled_run:"
logger = structlog.get_logger(__name__)
tracer = get_tracer("app.workers.tasks")


def _mark_cancelled(run_id: str) -> None:
    _redis_client.setex(f"{_CANCEL_KEY_PREFIX}{run_id}", 3600, "1")


def is_cancelled(run_id: str) -> bool:
    return _redis_client.exists(f"{_CANCEL_KEY_PREFIX}{run_id}") == 1


@task_revoked.connect
def _handle_revoked_request(request=None, terminated=None, signum=None, expired=None, **kwargs):
    if request and request.kwargs and request.kwargs.get("run_id"):
        _mark_cancelled(request.kwargs["run_id"])


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def execute_graph_async(
    self,
    graph_id: int,
    graph_content: Dict[str, Any],
    run_id: str,
    webhook_url: Optional[str] = None,
    execution_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute a test graph asynchronously.
    
    Args:
        graph_id: Database ID of the graph
        graph_content: Graph definition
        run_id: Unique run identifier
        webhook_url: Optional URL to notify on completion
        execution_config: Optional execution configuration
        
    Returns:
        Execution results dictionary
    """
    from app.database import SessionLocal
    from app.models import TestRun
    from app.services.executor import execute_graph
    from app.services.run_persistence import persist_trace
    
    with worker_job_active(), tracer.start_as_current_span(
        "worker.execute_graph",
        attributes={"run.id": run_id, "graph.id": graph_id},
    ):
        logger.info("worker.run.accepted", run_id=run_id, graph_id=graph_id)

        # Update task state
        self.update_state(
            state="RUNNING",
            meta={
                "run_id": run_id,
                "graph_id": graph_id,
                "started_at": datetime.now(UTC).isoformat(),
            },
        )

        try:
            if is_cancelled(run_id):
                logger.info("worker.run.cancelled", run_id=run_id)
                self.update_state(state=states.REVOKED, meta={"run_id": run_id})
                record_run_outcome(status="cancelled")
                return {"status": "cancelled", "run_id": run_id}

            db = SessionLocal()
            try:
                updated = db.execute(
                    TestRun.update()
                    .where(TestRun.c.id == int(run_id))
                    .where(TestRun.c.status.in_(["queued", "retry", "running"]))
                    .values(status="running", started_at=datetime.now(UTC))
                )
                db.commit()
                if updated.rowcount == 0:
                    logger.info("worker.run.skipped", run_id=run_id)
                    record_run_outcome(status="skipped")
                    return {"status": "skipped", "run_id": run_id}
            finally:
                db.close()

            config = dict(execution_config or {})
            trace_result = execute_graph(graph_content, config)
            result = trace_result.to_dict()

            # Update database
            db = SessionLocal()
            try:
                completed_dt = (
                    datetime.fromisoformat(trace_result.completed_at)
                    if trace_result.completed_at
                    else datetime.now(UTC)
                )
                db.execute(
                    TestRun.update()
                    .where(TestRun.c.id == int(run_id))
                    .values(
                        status=trace_result.status,
                        results=result,
                        latency_ms=trace_result.total_latency_ms,
                        cost_usd=trace_result.total_cost_usd,
                        provider=config.get("provider"),
                        model=config.get("model"),
                        completed_at=completed_dt,
                    )
                )
                persist_trace(db.connection(), int(run_id), result)
                db.commit()
            finally:
                db.close()

            record_run_outcome(status=trace_result.status, cost_usd=trace_result.total_cost_usd)
            logger.info(
                "worker.run.completed",
                run_id=run_id,
                status=trace_result.status,
                latency_ms=trace_result.total_latency_ms,
                cost_usd=trace_result.total_cost_usd,
            )

            # Send webhook notification
            if webhook_url:
                send_webhook.delay(
                    webhook_url,
                    {
                        "event": "run_completed",
                        "run_id": run_id,
                        "graph_id": graph_id,
                        "status": trace_result.status,
                        "latency_ms": trace_result.total_latency_ms,
                        "cost_usd": trace_result.total_cost_usd,
                        "passed_assertions": sum(1 for r in trace_result.assertion_results if r.passed),
                        "total_assertions": len(trace_result.assertion_results),
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                )

            return result

        except Exception as e:
            logger.error("worker.run.error", run_id=run_id, error=str(e))
            record_run_outcome(status="error")
            db = SessionLocal()
            try:
                db.execute(
                    TestRun.update()
                    .where(TestRun.c.id == int(run_id))
                    .values(status="error", error_message=str(e))
                )
                db.commit()
            finally:
                db.close()

            if webhook_url:
                send_webhook.delay(
                    webhook_url,
                    {
                        "event": "run_failed",
                        "run_id": run_id,
                        "graph_id": graph_id,
                        "error": str(e),
                        "retry_count": self.request.retries,
                    },
                )

            raise


@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=30
)
def send_webhook(
    self,
    url: str,
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Send webhook notification.
    
    Args:
        url: Webhook URL
        payload: Notification payload
        
    Returns:
        Response status
    """
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        
        return {
            "status": "sent",
            "status_code": response.status_code,
            "url": url
        }
        
    except requests.RequestException as e:
        # Retry on failure
        raise self.retry(exc=e)


@celery_app.task
def cleanup_old_runs(days: int = 30) -> Dict[str, Any]:
    """
    Cleanup old run data.
    
    Args:
        days: Number of days to retain
        
    Returns:
        Cleanup statistics
    """
    from app.database import SessionLocal
    from app.models import TestRun
    from datetime import timedelta
    
    cutoff = datetime.now(UTC) - timedelta(days=days)
    
    db = SessionLocal()
    try:
        # This would need a created_at column to work properly
        # For now, just return stats
        total_runs = db.execute(TestRun.select()).fetchall()
        return {
            "total_runs": len(total_runs),
            "retention_days": days,
            "cleaned": 0  # Placeholder
        }
    finally:
        db.close()


@celery_app.task
def recover_orphan_runs(
    queued_timeout_minutes: int = 5,
    running_timeout_minutes: int = 30
) -> Dict[str, Any]:
    """Detect and recover runs stuck in queued/running state."""
    from app.database import SessionLocal
    from app.models import TestRun, TestGraph, TestGraphVersion
    from sqlalchemy import and_

    now = datetime.now(UTC)
    queue_cutoff = now - timedelta(minutes=queued_timeout_minutes)
    running_cutoff = now - timedelta(minutes=running_timeout_minutes)

    db = SessionLocal()
    recovered = {"requeued": 0, "marked_failed": 0}
    try:
        queued_runs = db.execute(
            TestRun.select()
            .where(TestRun.c.status == "queued")
            .where(TestRun.c.created_at < queue_cutoff)
        ).fetchall()
        for run in queued_runs:
            graph_version = db.execute(
                TestGraphVersion.select()
                .where(TestGraphVersion.c.graph_id == run.graph_id)
                .where(TestGraphVersion.c.version == run.graph_version)
                .where(TestGraphVersion.c.tenant_id == run.tenant_id)
            ).fetchone()
            graph_row = graph_version or db.execute(
                TestGraph.select().where(
                    and_(TestGraph.c.id == run.graph_id, TestGraph.c.tenant_id == run.tenant_id)
                )
            ).fetchone()
            if not graph_row:
                continue
            graph_content = graph_row.content
            stored_config = {}
            if isinstance(run.metadata, dict):
                stored_config = run.metadata.get("execution_config", {}) or {}
            fallback_config = {
                "provider": run.provider,
                "model": run.model,
                "seed": run.seed,
                "mode": run.execution_mode or "normal",
                "tenant_id": run.tenant_id,
            }
            execution_payload = {**fallback_config, **stored_config}
            execution_payload.setdefault("tenant_id", run.tenant_id)
            db.execute(
                TestRun.update()
                .where(TestRun.c.id == run.id)
                .values(status="retry", started_at=None, created_at=now)
            )
            execute_graph_async.delay(
                graph_id=run.graph_id,
                graph_content=graph_content,
                run_id=str(run.id),
                webhook_url=run.webhook_url,
                execution_config=execution_payload,
            )
            recovered["requeued"] += 1

        running_runs = db.execute(
            TestRun.select()
            .where(TestRun.c.status == "running")
            .where(TestRun.c.started_at.isnot(None))
            .where(TestRun.c.started_at < running_cutoff)
        ).fetchall()
        for run in running_runs:
            db.execute(
                TestRun.update()
                .where(TestRun.c.id == run.id)
                .values(status="error", error_message="Run exceeded max execution window")
            )
            recovered["marked_failed"] += 1
        db.commit()
    finally:
        db.close()

    return recovered


# Celery beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "cleanup-old-runs": {
        "task": "workers.tasks.cleanup_old_runs",
        "schedule": 86400,  # Daily
        "args": (30,)  # 30 day retention
    },
    "recover-orphan-runs": {
        "task": "workers.tasks.recover_orphan_runs",
        "schedule": 300,  # Every 5 minutes
        "args": (5, 30)
    }
}
