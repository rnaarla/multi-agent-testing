from fastapi import APIRouter, Body

from app.reliability import ReleaseMetrics, evaluate_release, load_default_slos


router = APIRouter()


@router.post("/guard")
def evaluate_release_guard(payload: ReleaseMetrics = Body(...)) -> dict:
    """Evaluate release guardrails using provided metrics."""

    decision = evaluate_release(payload, slos=load_default_slos())
    return {"approved": decision.approved, "reasons": decision.reasons}

