"""
Seed sample graphs, runs, and analytics so the frontend dashboard has data.

Execute with:
    docker compose exec backend python -m app.scripts.seed_demo_data

The script is safe to run multiple times; it refreshes the demo data set.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import List

from sqlalchemy import delete, insert, select, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import hash_password
from app.models import (
    AgentOutput,
    AssertionResult,
    MetricsDaily,
    TestGraph,
    TestGraphVersion,
    TestRun,
    User,
    metadata,
)


@dataclass(frozen=True)
class SeedConfig:
    database_url: str
    tenant_id: str = "demo"
    demo_user_email: str = "demo.admin@local"
    demo_user_name: str = "Demo Admin"
    graph_name: str = "Demo Customer Support Workflow"
    graph_description: str = "Sample workflow seeded for local dashboards."
    demo_runs: int = 8


def build_engine(cfg: SeedConfig) -> Engine:
    return create_engine(cfg.database_url, future=True, echo=False)


def ensure_schema(engine: Engine) -> None:
    metadata.create_all(engine)


def ensure_demo_user(session: Session, cfg: SeedConfig) -> int:
    existing = session.execute(
        select(User.c.id).where(User.c.email == cfg.demo_user_email)
    ).scalar_one_or_none()
    if existing:
        return existing

    password_hash = hash_password("demo-password")
    result = session.execute(
        insert(User).values(
            email=cfg.demo_user_email,
            password_hash=password_hash,
            name=cfg.demo_user_name,
            role="admin",
            is_active=True,
            tenant_id=cfg.tenant_id,
        )
    )
    session.commit()
    return result.inserted_primary_key[0]


def ensure_demo_graph(session: Session, cfg: SeedConfig, owner_id: int) -> int:
    existing_graph = session.execute(
        select(TestGraph.c.id).where(
            (TestGraph.c.name == cfg.graph_name)
            & (TestGraph.c.tenant_id == cfg.tenant_id)
        )
    ).scalar_one_or_none()

    graph_content = {
        "nodes": [
            {
                "id": "intake",
                "type": "prompt",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt": "Greet the customer and capture their issue.",
            },
            {
                "id": "triage",
                "type": "classifier",
                "provider": "anthropic",
                "model": "claude-3-opus",
                "labels": ["billing", "bug", "question"],
            },
            {
                "id": "resolver",
                "type": "tool",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "tool": "knowledge_base",
            },
        ],
        "edges": [
            {"source": "intake", "target": "triage"},
            {"source": "triage", "target": "resolver"},
        ],
        "assertions": [
            {
                "id": "assert-greeting",
                "type": "contains",
                "node_id": "intake",
                "value": "hello",
            },
            {
                "id": "assert-resolution",
                "type": "not_empty",
                "node_id": "resolver",
            },
        ],
    }

    if existing_graph:
        return existing_graph

    timestamp = datetime.now(UTC)
    result = session.execute(
        insert(TestGraph).values(
            name=cfg.graph_name,
            description=cfg.graph_description,
            content=graph_content,
            version=1,
            created_by=owner_id,
            tenant_id=cfg.tenant_id,
            created_at=timestamp,
            updated_at=timestamp,
            tags=["demo", "customer-support"],
        )
    )
    graph_id = result.inserted_primary_key[0]

    session.execute(
        insert(TestGraphVersion).values(
            graph_id=graph_id,
            version=1,
            content=graph_content,
            tenant_id=cfg.tenant_id,
            created_by=owner_id,
            created_at=timestamp,
            change_description="Initial seeded version",
        )
    )
    session.commit()
    return graph_id


def refresh_demo_runs(session: Session, cfg: SeedConfig, graph_id: int, owner_id: int) -> None:
    existing_run_ids: List[int] = [
        row[0]
        for row in session.execute(
            select(TestRun.c.id).where(TestRun.c.graph_id == graph_id)
        )
    ]

    if existing_run_ids:
        session.execute(delete(AgentOutput).where(AgentOutput.c.run_id.in_(existing_run_ids)))
        session.execute(delete(AssertionResult).where(AssertionResult.c.run_id.in_(existing_run_ids)))
        session.execute(delete(TestRun).where(TestRun.c.id.in_(existing_run_ids)))
        session.execute(delete(MetricsDaily).where(MetricsDaily.c.graph_id == graph_id))
        session.commit()

    base_time = datetime.now(UTC) - timedelta(hours=2)
    rng = random.Random(42)
    statuses = ["passed", "passed", "passed", "failed", "passed", "completed", "error", "passed"]
    modes = ["normal", "normal", "debug", "chaos", "replay", "simulation", "normal", "normal"]

    for idx in range(cfg.demo_runs):
        duration_ms = rng.randint(90, 450)
        cost = round(rng.uniform(0.01, 0.12), 4)
        started = base_time + timedelta(minutes=idx * 5)
        completed = started + timedelta(milliseconds=duration_ms * 3)
        status = statuses[idx % len(statuses)]
        mode = modes[idx % len(modes)]

        results_payload = {
            "summary": {
                "issue_type": rng.choice(["billing", "bug", "question"]),
                "confidence": round(rng.uniform(0.65, 0.98), 2),
            },
            "assertions": [
                {"id": "assert-greeting", "passed": True},
                {"id": "assert-resolution", "passed": status != "error"},
            ],
        }

        session.execute(
            insert(TestRun).values(
                graph_id=graph_id,
                graph_version=1,
                tenant_id=cfg.tenant_id,
                status=status,
                results=results_payload,
                latency_ms=duration_ms,
                cost_usd=cost,
                execution_mode=mode,
                provider="openai" if idx % 2 == 0 else "anthropic",
                model="gpt-4o-mini" if idx % 2 == 0 else "claude-3-opus",
                seed=idx + 123,
                assertions_passed=2 if status != "error" else 1,
                assertions_failed=0 if status != "error" else 1,
                tokens_in=rng.randint(150, 400),
                tokens_out=rng.randint(120, 300),
                triggered_by=owner_id,
                started_at=started,
                completed_at=completed,
                created_at=started,
            )
        )

    session.commit()

    runs = session.execute(
        select(
            TestRun.c.status,
            TestRun.c.latency_ms,
            TestRun.c.cost_usd,
            TestRun.c.tokens_in,
            TestRun.c.tokens_out,
        ).where(TestRun.c.graph_id == graph_id)
    ).all()

    total_runs = len(runs)
    passed_runs = sum(1 for r in runs if r.status in {"passed", "completed"})
    failed_runs = sum(1 for r in runs if r.status == "failed")
    error_runs = sum(1 for r in runs if r.status == "error")

    latencies = [r.latency_ms or 0 for r in runs]
    avg_latency = sum(latencies) / total_runs if total_runs else 0
    sorted_latency = sorted(latencies)

    def percentile(values: List[float], pct: float) -> float:
        if not values:
            return 0.0
        idx = int(round((len(values) - 1) * pct))
        return float(values[idx])

    session.execute(
        insert(MetricsDaily).values(
            date=datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0),
            graph_id=graph_id,
            total_runs=total_runs,
            passed_runs=passed_runs,
            failed_runs=failed_runs,
            error_runs=error_runs,
            avg_latency_ms=avg_latency,
            p50_latency_ms=percentile(sorted_latency, 0.5),
            p95_latency_ms=percentile(sorted_latency, 0.95),
            p99_latency_ms=percentile(sorted_latency, 0.99),
            total_cost_usd=sum(r.cost_usd or 0 for r in runs),
            total_tokens=sum((r.tokens_in or 0) + (r.tokens_out or 0) for r in runs),
        )
    )
    session.commit()


def main() -> None:
    cfg = SeedConfig(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@db:5432/agent_tests",
        ),
        tenant_id=os.getenv("TENANT_ID", "demo"),
        demo_runs=int(os.getenv("DEMO_RUNS", "8")),
    )

    engine = build_engine(cfg)
    ensure_schema(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        owner_id = ensure_demo_user(session, cfg)
        graph_id = ensure_demo_graph(session, cfg, owner_id)
        refresh_demo_runs(session, cfg, graph_id, owner_id)

    print(
        "Seed complete. Sign in with the seeded user "
        f"({cfg.demo_user_email} / demo-password) to view demo data."
    )


if __name__ == "__main__":
    main()

