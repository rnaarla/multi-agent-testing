"""API endpoints for agent-based simulations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import Permission, User, permission_dependency
from app.services.simulation_service import (
    start_simulation_run,
    list_simulation_runs,
    get_simulation_run,
    fetch_run_events,
    read_event_stream,
)


router = APIRouter(prefix="/simulation", tags=["Simulation"])


class AgentConfig(BaseModel):
    id: str
    type: str = "generic"
    implementation: str = Field(default="rule", description="rule or llm")
    config: Dict[str, Any] = Field(default_factory=dict)
    personality: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class EnvironmentConfig(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


class SimulationRunRequest(BaseModel):
    name: str = "simulation"
    scenario: str = "default"
    steps: int = 10
    environment: EnvironmentConfig = EnvironmentConfig()
    agents: List[AgentConfig]
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/run", status_code=202)
def launch_simulation(
    request: SimulationRunRequest,
    user: User = Depends(permission_dependency(Permission.RUN_CREATE)),
) -> Dict[str, Any]:
    """Start a simulation run synchronously."""

    result = start_simulation_run(request.model_dump(), user)
    return {"run_id": result["run_id"], "status": result["status"], "steps": result["steps"]}


@router.get("/runs")
def list_runs(
    limit: int = Query(20, le=100),
    offset: int = 0,
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> List[Dict[str, Any]]:
    return list_simulation_runs(user.tenant_id, limit=limit, offset=offset)


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> Dict[str, Any]:
    run = get_simulation_run(run_id, user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return run


@router.get("/runs/{run_id}/events")
def get_run_events(
    run_id: int,
    after_id: Optional[int] = Query(None, description="Fetch events after this ID"),
    limit: int = Query(100, le=500),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> List[Dict[str, Any]]:
    run = get_simulation_run(run_id, user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return fetch_run_events(run_id, last_event_id=after_id, limit=limit)


@router.get("/runs/{run_id}/stream")
def stream_events(
    run_id: int,
    last_id: str = Query("0-0", description="Redis stream offset"),
    limit: int = Query(100, le=500),
    user: User = Depends(permission_dependency(Permission.RUN_READ)),
) -> List[Dict[str, Any]]:
    run = get_simulation_run(run_id, user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return read_event_stream(run_id, last_id=last_id, count=limit)

