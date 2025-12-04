"""Release gating logic using observability metrics and SLOs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from app.reliability.slo import ErrorBudget, SLOConfig, load_default_slos


@dataclass(frozen=True)
class ReleaseMetrics:
    """Metrics collected during pre-production verification."""

    latency_p95_ms: float
    latency_p99_ms: float
    success_rate: float
    active_incidents: int
    regression_tests_passed: bool
    slo_name: str = "default"


@dataclass(frozen=True)
class ReleaseDecision:
    """Outcome of a release evaluation."""

    approved: bool
    reasons: List[str]

    def raise_if_blocked(self) -> None:
        if not self.approved:
            raise RuntimeError("; ".join(self.reasons))


def _find_slo(configs: Iterable[SLOConfig], name: str) -> SLOConfig | None:
    for slo in configs:
        if slo.name == name:
            return slo
    return None


def evaluate_release(metrics: ReleaseMetrics, slos: Iterable[SLOConfig] | None = None) -> ReleaseDecision:
    """Evaluate a prospective release against SLOs and guardrails."""

    active_slos = list(slos or load_default_slos())
    slo = _find_slo(active_slos, metrics.slo_name) or _find_slo(active_slos, "default")

    reasons: List[str] = []

    if metrics.active_incidents > 0:
        reasons.append("Active incidents present")

    if not metrics.regression_tests_passed:
        reasons.append("Regression suite failed")

    if slo:
        if metrics.latency_p95_ms > slo.latency_ms_p95:
            reasons.append(f"P95 latency {metrics.latency_p95_ms}ms exceeds SLO {slo.latency_ms_p95}ms")
        if metrics.latency_p99_ms > slo.latency_ms_p99:
            reasons.append(f"P99 latency {metrics.latency_p99_ms}ms exceeds SLO {slo.latency_ms_p99}ms")
        if slo.availability.exhausted(metrics.success_rate):
            reasons.append(
                f"Success rate {metrics.success_rate:.3f} below availability target {slo.availability.target:.3f}"
            )
    else:
        reasons.append(f"SLO '{metrics.slo_name}' not defined")

    return ReleaseDecision(approved=not reasons, reasons=reasons)


def gate_release(metrics: ReleaseMetrics, slos: Iterable[SLOConfig] | None = None) -> None:
    """Raise if the release should be blocked."""

    decision = evaluate_release(metrics, slos=slos)
    decision.raise_if_blocked()

