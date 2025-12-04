from typing import List

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from app.analytics.anomaly import (
    detect_latency_anomalies,
    detect_zscore_anomalies,
    moving_average,
)


class LatencyAnomalyRequest(BaseModel):
    baseline: List[float] = Field(..., description="Baseline latency samples (ms)")
    candidate: List[float] = Field(..., description="Candidate latency samples (ms)")
    threshold: float = Field(3.0, description="Z-score threshold for anomaly detection")


router = APIRouter()


@router.post("/anomalies/latency")
def latency_anomalies(payload: LatencyAnomalyRequest) -> dict:
    """Detect latency anomalies between baseline and candidate windows."""

    result = detect_latency_anomalies(payload.baseline, payload.candidate, threshold=payload.threshold)
    return {"score": result.score, "thresholds": result.thresholds, "anomalies": result.anomalies}


@router.post("/anomalies/series")
def series_anomalies(payload: dict = Body(...)) -> dict:
    """Run anomaly detection over an arbitrary numeric series."""

    series = payload.get("series") or []
    z_threshold = float(payload.get("z_threshold", 3.0))
    window = int(payload.get("smoothing_window", 0))

    processed = series
    if window and window > 0:
        processed = moving_average(series, window)

    result = detect_zscore_anomalies(processed, z_threshold=z_threshold)
    return {
        "anomaly_indices": result.indices,
        "mean": result.mean,
        "stddev": result.stddev,
        "threshold": result.threshold,
        "processed_series": processed,
    }

