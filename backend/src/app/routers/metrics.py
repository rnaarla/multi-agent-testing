"""
Metrics API router for test run analytics.

Provides:
- Aggregated metrics across runs
- Latency percentiles
- Cost tracking
- Drift detection
- Pass/fail trends
"""

from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy import and_

from app.database import SessionLocal
from app.models import TestRun, TestGraph, TestGraphVersion
from app.auth import User, Permission, permission_dependency

router = APIRouter()

def _graph_for_tenant(db, graph_id: int, tenant_id: str):
    graph = db.execute(
        TestGraph.select().where(
            and_(TestGraph.c.id == graph_id, TestGraph.c.tenant_id == tenant_id)
        )
    ).fetchone()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    return graph


@router.get("/summary")
def get_metrics_summary(
    user: User = Depends(permission_dependency(Permission.METRICS_READ))
):
    """Get overall metrics summary across all runs."""
    db = SessionLocal()
    
    runs = db.execute(
        TestRun.select().where(TestRun.c.tenant_id == user.tenant_id)
    ).fetchall()
    
    if not runs:
        return {
            "total_runs": 0,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "pass_rate": 0.0,
            "avg_latency_ms": 0.0,
            "total_cost_usd": 0.0,
            "latency_p50": 0.0,
            "latency_p95": 0.0,
            "latency_p99": 0.0
        }
    
    total = len(runs)
    passed = sum(1 for r in runs if r.status == "passed")
    failed = sum(1 for r in runs if r.status == "failed")
    error = sum(1 for r in runs if r.status == "error")
    
    latencies = sorted([r.latency_ms for r in runs if r.latency_ms])
    costs = [r.cost_usd for r in runs if r.cost_usd]
    
    def percentile(data, p):
        if not data:
            return 0.0
        k = (len(data) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        return data[f] + (k - f) * (data[c] - data[f]) if c != f else data[f]
    
    return {
        "total_runs": total,
        "passed": passed,
        "failed": failed,
        "error": error,
        "pass_rate": round(passed / total * 100, 2) if total > 0 else 0.0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "total_cost_usd": round(sum(costs), 4),
        "latency_p50": round(percentile(latencies, 50), 2),
        "latency_p95": round(percentile(latencies, 95), 2),
        "latency_p99": round(percentile(latencies, 99), 2)
    }


@router.get("/by-graph/{graph_id}")
def get_metrics_by_graph(
    graph_id: int,
    user: User = Depends(permission_dependency(Permission.METRICS_READ))
):
    """Get metrics for a specific graph."""
    db = SessionLocal()
    
    _graph_for_tenant(db, graph_id, user.tenant_id)
    runs = db.execute(
        TestRun.select().where(
            and_(TestRun.c.graph_id == graph_id, TestRun.c.tenant_id == user.tenant_id)
        )
    ).fetchall()
    
    if not runs:
        raise HTTPException(status_code=404, detail="No runs found for this graph")
    
    latencies = sorted([r.latency_ms for r in runs if r.latency_ms])
    costs = [r.cost_usd for r in runs if r.cost_usd]
    
    # Calculate trend (compare last 10 vs previous 10)
    recent_runs = runs[-10:] if len(runs) >= 10 else runs
    older_runs = runs[-20:-10] if len(runs) >= 20 else []
    
    recent_pass_rate = sum(1 for r in recent_runs if r.status == "passed") / len(recent_runs) if recent_runs else 0
    older_pass_rate = sum(1 for r in older_runs if r.status == "passed") / len(older_runs) if older_runs else recent_pass_rate
    
    trend = "stable"
    if recent_pass_rate > older_pass_rate + 0.1:
        trend = "improving"
    elif recent_pass_rate < older_pass_rate - 0.1:
        trend = "degrading"
    
    return {
        "graph_id": graph_id,
        "total_runs": len(runs),
        "passed": sum(1 for r in runs if r.status == "passed"),
        "failed": sum(1 for r in runs if r.status == "failed"),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "total_cost_usd": round(sum(costs), 4),
        "trend": trend,
        "recent_pass_rate": round(recent_pass_rate * 100, 2)
    }


@router.get("/trends")
def get_trends(
    days: int = Query(default=7, ge=1, le=90),
    graph_id: Optional[int] = None,
    user: User = Depends(permission_dependency(Permission.METRICS_READ))
):
    """Get metrics trends over time."""
    db = SessionLocal()
    
    query = TestRun.select().where(TestRun.c.tenant_id == user.tenant_id)
    if graph_id:
        _graph_for_tenant(db, graph_id, user.tenant_id)
        query = query.where(TestRun.c.graph_id == graph_id)
    
    runs = db.execute(query).fetchall()
    buckets = {}
    for run in runs:
        day = (run.completed_at or run.created_at).date() if run.completed_at else datetime.now(UTC).date()
        if day not in buckets:
            buckets[day] = []
        buckets[day].append(run)

    trend_data = []
    for day in sorted(buckets.keys())[-days:]:
        day_runs = buckets[day]
        avg_latency = sum(r.latency_ms or 0 for r in day_runs) / len(day_runs)
        avg_cost = sum(r.cost_usd or 0 for r in day_runs) / len(day_runs)
        trend_data.append({
            "date": day.isoformat(),
            "runs": len(day_runs),
            "passed": sum(1 for r in day_runs if r.status == "passed"),
            "failed": sum(1 for r in day_runs if r.status == "failed"),
            "avg_latency_ms": round(avg_latency, 2),
            "avg_cost_usd": round(avg_cost, 4),
        })

    return {"trends": trend_data}


@router.get("/latency-distribution")
def get_latency_distribution(
    graph_id: Optional[int] = None,
    user: User = Depends(permission_dependency(Permission.METRICS_READ))
):
    """Get latency distribution histogram."""
    db = SessionLocal()
    
    query = TestRun.select().where(TestRun.c.tenant_id == user.tenant_id)
    if graph_id:
        _graph_for_tenant(db, graph_id, user.tenant_id)
        query = query.where(TestRun.c.graph_id == graph_id)
    
    runs = db.execute(query).fetchall()
    latencies = [r.latency_ms for r in runs if r.latency_ms]
    
    if not latencies:
        return {"buckets": [], "counts": []}
    
    # Create histogram buckets
    min_lat = min(latencies)
    max_lat = max(latencies)
    bucket_size = (max_lat - min_lat) / 10 if max_lat > min_lat else 10
    
    buckets = []
    counts = []
    
    for i in range(10):
        bucket_start = min_lat + i * bucket_size
        bucket_end = bucket_start + bucket_size
        count = sum(1 for l in latencies if bucket_start <= l < bucket_end)
        buckets.append(f"{int(bucket_start)}-{int(bucket_end)}ms")
        counts.append(count)
    
    return {
        "buckets": buckets,
        "counts": counts,
        "min": round(min_lat, 2),
        "max": round(max_lat, 2),
        "mean": round(sum(latencies) / len(latencies), 2)
    }


@router.get("/assertions")
def get_assertion_metrics(
    graph_id: Optional[int] = None,
    user: User = Depends(permission_dependency(Permission.METRICS_READ))
):
    """Get assertion pass/fail breakdown."""
    db = SessionLocal()
    
    query = TestRun.select().where(TestRun.c.tenant_id == user.tenant_id)
    if graph_id:
        _graph_for_tenant(db, graph_id, user.tenant_id)
        query = query.where(TestRun.c.graph_id == graph_id)
    
    runs = db.execute(query).fetchall()
    
    assertion_stats = {}
    
    for run in runs:
        results = run.results or {}
        if isinstance(results, list):
            for assertion in results:
                if isinstance(assertion, dict):
                    aid = assertion.get("assertion_id", "unknown")
                    if aid not in assertion_stats:
                        assertion_stats[aid] = {"passed": 0, "failed": 0}
                    if assertion.get("passed"):
                        assertion_stats[aid]["passed"] += 1
                    else:
                        assertion_stats[aid]["failed"] += 1
    
    return {
        "assertions": [
            {
                "id": aid,
                "passed": stats["passed"],
                "failed": stats["failed"],
                "pass_rate": round(stats["passed"] / (stats["passed"] + stats["failed"]) * 100, 2)
                if stats["passed"] + stats["failed"] > 0 else 0
            }
            for aid, stats in assertion_stats.items()
        ]
    }


@router.get("/cost-breakdown")
def get_cost_breakdown(
    user: User = Depends(permission_dependency(Permission.METRICS_READ))
):
    """Get cost breakdown by graph and provider."""
    db = SessionLocal()
    
    runs = db.execute(
        TestRun.select().where(TestRun.c.tenant_id == user.tenant_id)
    ).fetchall()
    graphs = db.execute(
        TestGraph.select().where(TestGraph.c.tenant_id == user.tenant_id)
    ).fetchall()
    
    graph_names = {g.id: g.name for g in graphs}
    
    cost_by_graph = {}
    for run in runs:
        gid = run.graph_id
        name = graph_names.get(gid, f"Graph {gid}")
        if name not in cost_by_graph:
            cost_by_graph[name] = 0.0
        cost_by_graph[name] += run.cost_usd or 0.0
    
    return {
        "by_graph": [
            {"name": name, "cost_usd": round(cost, 4)}
            for name, cost in sorted(cost_by_graph.items(), key=lambda x: -x[1])
        ],
        "total_cost_usd": round(sum(cost_by_graph.values()), 4)
    }


@router.get("/drift")
def detect_drift(
    graph_id: int,
    threshold: float = 0.15,
    user: User = Depends(permission_dependency(Permission.METRICS_READ))
):
    """Detect behavioral drift for a graph."""
    db = SessionLocal()
    
    _graph_for_tenant(db, graph_id, user.tenant_id)
    runs = db.execute(
        TestRun.select().where(
            and_(TestRun.c.graph_id == graph_id, TestRun.c.tenant_id == user.tenant_id)
        )
    ).fetchall()
    
    if len(runs) < 10:
        return {
            "drift_detected": False,
            "message": "Insufficient data for drift detection (need at least 10 runs)",
            "runs_analyzed": len(runs)
        }
    
    # Compare recent vs baseline
    baseline = runs[:len(runs) // 2]
    recent = runs[len(runs) // 2:]
    
    baseline_pass_rate = sum(1 for r in baseline if r.status == "passed") / len(baseline)
    recent_pass_rate = sum(1 for r in recent if r.status == "passed") / len(recent)
    
    baseline_latency = sum(r.latency_ms or 0 for r in baseline) / len(baseline)
    recent_latency = sum(r.latency_ms or 0 for r in recent) / len(recent)
    
    pass_rate_drift = abs(recent_pass_rate - baseline_pass_rate)
    latency_drift = abs(recent_latency - baseline_latency) / baseline_latency if baseline_latency > 0 else 0
    
    drift_detected = pass_rate_drift > threshold or latency_drift > threshold
    
    return {
        "drift_detected": drift_detected,
        "metrics": {
            "pass_rate": {
                "baseline": round(baseline_pass_rate * 100, 2),
                "recent": round(recent_pass_rate * 100, 2),
                "drift": round(pass_rate_drift * 100, 2)
            },
            "latency": {
                "baseline": round(baseline_latency, 2),
                "recent": round(recent_latency, 2),
                "drift_percent": round(latency_drift * 100, 2)
            }
        },
        "threshold": threshold,
        "runs_analyzed": len(runs)
    }


@router.get("/analytics/dashboard")
def analytics_dashboard(
    user: User = Depends(permission_dependency(Permission.METRICS_READ)),
):
    """Aggregated analytics view for dashboards."""

    db = SessionLocal()
    runs = db.execute(
        TestRun.select().where(TestRun.c.tenant_id == user.tenant_id)
    ).fetchall()

    if not runs:
        return {
            "cost": {"total": 0.0, "by_graph": []},
            "latency": {"p95": 0.0, "trend": []},
            "drift": {"graphs": []},
            "safety": {"violations": 0, "runs_with_failures": 0},
        }

    graphs = db.execute(
        TestGraph.select().where(TestGraph.c.tenant_id == user.tenant_id)
    ).fetchall()
    graph_lookup = {g.id: g.name for g in graphs}

    cost_by_graph = {}
    latency_trend = []
    drift_candidates = {}
    violations = 0
    runs_with_failures = 0
    latencies = []

    for run in runs:
        graph_name = graph_lookup.get(run.graph_id, f"Graph {run.graph_id}")
        cost_by_graph.setdefault(graph_name, 0.0)
        cost_by_graph[graph_name] += run.cost_usd or 0.0

        latencies.append(run.latency_ms or 0.0)

        day = (run.completed_at or run.created_at).date() if run.completed_at else datetime.now(UTC).date()
        drift_candidates.setdefault(run.graph_id, []).append(run)
        latency_trend.append(
            {
                "date": day.isoformat(),
                "graph": graph_name,
                "latency_ms": run.latency_ms or 0.0,
                "status": run.status,
            }
        )

        results = run.results or {}
        if isinstance(results, dict):
            violations += len(results.get("contract_violations", []))
            if results.get("contract_violations"):
                runs_with_failures += 1

    def percentile(data, p):
        if not data:
            return 0.0
        data = sorted(data)
        k = (len(data) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        return data[f] + (k - f) * (data[c] - data[f]) if c != f else data[f]

    drift_summaries = []
    for graph_id, candidate_runs in drift_candidates.items():
        if len(candidate_runs) < 4:
            continue
        baseline = candidate_runs[: len(candidate_runs) // 2]
        recent = candidate_runs[len(candidate_runs) // 2 :]
        baseline_latency = sum(r.latency_ms or 0 for r in baseline) / len(baseline)
        recent_latency = sum(r.latency_ms or 0 for r in recent) / len(recent)
        drift_percent = (
            abs(recent_latency - baseline_latency) / baseline_latency * 100 if baseline_latency else 0.0
        )
        drift_summaries.append(
            {
                "graph_id": graph_id,
                "graph": graph_lookup.get(graph_id, f"Graph {graph_id}"),
                "latency_baseline_ms": round(baseline_latency, 2),
                "latency_recent_ms": round(recent_latency, 2),
                "latency_drift_percent": round(drift_percent, 2),
            }
        )

    return {
        "cost": {
            "total": round(sum(cost_by_graph.values()), 4),
            "by_graph": [
                {"graph": name, "cost_usd": round(cost, 4)}
                for name, cost in sorted(cost_by_graph.items(), key=lambda x: -x[1])
            ],
        },
        "latency": {"p95": round(percentile(latencies, 95), 2), "trend": latency_trend},
        "drift": {"graphs": drift_summaries},
        "safety": {
            "violations": violations,
            "runs_with_failures": runs_with_failures,
        },
    }
