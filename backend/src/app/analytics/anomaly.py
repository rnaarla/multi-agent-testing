"""Behavioral analytics and anomaly detection utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence


@dataclass
class MetricWindow:
    values: Sequence[float]

    def mean(self) -> float:
        return sum(self.values) / max(len(self.values), 1)

    def stdev(self) -> float:
        mean = self.mean()
        variance = sum((value - mean) ** 2 for value in self.values) / max(len(self.values), 1)
        return math.sqrt(variance)


@dataclass
class AnomalyResult:
    score: float
    thresholds: Sequence[float]
    anomalies: List[int]


class DriftAnalyzer:
    """Detect anomalies using a simple z-score approach."""

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold

    def analyze(self, baseline: MetricWindow, candidate: MetricWindow) -> AnomalyResult:
        mean = baseline.mean()
        stdev = baseline.stdev() or 1.0

        anomalies = []
        scores = []
        for idx, value in enumerate(candidate.values):
            z = abs(value - mean) / stdev
            scores.append(z)
            if z > self.threshold:
                anomalies.append(idx)

        score = max(scores) if scores else 0.0
        return AnomalyResult(score=score, thresholds=[self.threshold], anomalies=anomalies)


def detect_latency_anomalies(
    baseline: Iterable[float],
    candidate: Iterable[float],
    threshold: float = 3.0,
) -> AnomalyResult:
    analyzer = DriftAnalyzer(threshold=threshold)
    return analyzer.analyze(MetricWindow(list(baseline)), MetricWindow(list(candidate)))


@dataclass(frozen=True)
class AnomalyDetectionResult:
    indices: List[int]
    mean: float
    stddev: float
    threshold: float


def detect_zscore_anomalies(
    series: Sequence[float],
    z_threshold: float = 3.0,
) -> AnomalyDetectionResult:
    """Simple z-score anomaly detector."""

    if not series:
        return AnomalyDetectionResult(indices=[], mean=0.0, stddev=0.0, threshold=z_threshold)

    mean = sum(series) / len(series)
    variance = sum((value - mean) ** 2 for value in series) / len(series)
    stddev = math.sqrt(variance)

    if stddev == 0:
        return AnomalyDetectionResult(indices=[], mean=mean, stddev=0.0, threshold=z_threshold)

    anomalies = [
        idx
        for idx, value in enumerate(series)
        if abs(value - mean) / stddev >= z_threshold
    ]
    return AnomalyDetectionResult(indices=anomalies, mean=mean, stddev=stddev, threshold=z_threshold)


def moving_average(series: Sequence[float], window: int) -> List[float]:
    """Calculate moving average for smoothing."""

    if window <= 0:
        raise ValueError("window must be positive")
    if window > len(series):
        return list(series)

    output: List[float] = []
    for idx in range(len(series)):
        start = max(0, idx - window + 1)
        window_slice = series[start : idx + 1]
        output.append(sum(window_slice) / len(window_slice))
    return output

