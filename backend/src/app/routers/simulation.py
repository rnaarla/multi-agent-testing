"""API endpoints for agent-based simulations."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.auth import Permission, User, permission_dependency
from app.services.simulation_service import (
    start_simulation_run,
    list_simulation_runs,
    get_simulation_run,
    fetch_run_events,
    read_event_stream,
    evaluate_simulation_run,
)
from app.simulation.evaluation import MAX_EVAL_ASSERTION_COUNT
from app.simulation.validation import (
    MAX_AGENTS,
    MAX_SIMULATION_STEPS,
    SimulationValidationError,
)


router = APIRouter(prefix="/simulation", tags=["Simulation"])

_STREAM_CURSOR_RE = re.compile(r"^\d+-\d+$")


class AgentConfig(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    type: str = "generic"
    implementation: str = Field(default="rule", description="rule or llm")
    config: Dict[str, Any] = Field(default_factory=dict)
    personality: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_agent_id(cls, value: Any) -> str:
        if value is None:
            raise ValueError("agent id is required")
        text = str(value).strip()
        if not text:
            raise ValueError("agent id is required")
        return text


class EnvironmentConfig(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


class SimulationEvaluateRequest(BaseModel):
    """Assertions compatible with AssertionEngine (target = context key: run, simulation, or agent_id)."""

    assertions: List[Dict[str, Any]] = Field(..., min_length=1, max_length=MAX_EVAL_ASSERTION_COUNT)


class SimulationRunRequest(BaseModel):
    name: str = "simulation"
    scenario: str = "default"
    steps: int = Field(default=10, ge=1, le=MAX_SIMULATION_STEPS)
    environment: EnvironmentConfig = EnvironmentConfig()
    agents: List[AgentConfig] = Field(..., min_length=1, max_length=MAX_AGENTS)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_agent_ids(self) -> "SimulationRunRequest":
        ids = [agent.id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate agent ids")
        return self


@router.post("/run")
def launch_simulation(
    request: SimulationRunRequest,
    user: User = Depends(permission_dependency(Permission.RUN_CREATE)),
) -> Dict[str, Any]:
    """Start a simulation run synchronously."""

    try:
        result = start_simulation_run(request.model_dump(), user)
    except SimulationValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {"run_id": result["run_id"], "status": result["status"], "steps": result["steps"]}


@router.get("/runs")
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> List[Dict[str, Any]]:
    return list_simulation_runs(user.tenant_id, limit=limit, offset=offset)


@router.get("/runs/{run_id}")
def get_run(
    run_id: int = Path(..., ge=1),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> Dict[str, Any]:
    run = get_simulation_run(run_id, user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return run


@router.post("/runs/{run_id}/evaluate")
def evaluate_run(
    request: SimulationEvaluateRequest,
    run_id: int = Path(..., ge=1),
    event_limit: int = Query(5000, ge=1, le=10_000, description="Max simulation_events rows to load"),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> Dict[str, Any]:
    """Evaluate behavioral assertions against persisted simulation telemetry (CI / post-run gate)."""

    try:
        result = evaluate_simulation_run(
            run_id,
            user.tenant_id,
            request.assertions,
            event_limit=event_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return result


@router.get("/runs/{run_id}/events")
def get_run_events(
    run_id: int = Path(..., ge=1),
    after_id: Optional[int] = Query(None, ge=0, description="Fetch events after this ID"),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> List[Dict[str, Any]]:
    run = get_simulation_run(run_id, user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return fetch_run_events(run_id, user.tenant_id, last_event_id=after_id, limit=limit)


@router.get("/runs/{run_id}/stream")
def stream_events(
    run_id: int = Path(..., ge=1),
    last_id: str = Query("0-0", description="Redis stream offset"),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> List[Dict[str, Any]]:
    if not _STREAM_CURSOR_RE.match(last_id):
        raise HTTPException(status_code=400, detail="Invalid stream cursor")
    run = get_simulation_run(run_id, user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return read_event_stream(run_id, last_id=last_id, count=limit)

