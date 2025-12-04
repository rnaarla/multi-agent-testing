"""Service Level Objective definitions for deployment gating."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import yaml


@dataclass(frozen=True)
class ErrorBudget:
    """Represents an error budget window."""

    target: float  # e.g. 0.98 means 98% success
    window_days: int

    def exhausted(self, success_rate: float) -> bool:
        """Return True when the observed success rate violates the budget."""

        return success_rate < self.target


@dataclass(frozen=True)
class SLOConfig:
    """SLO definition for a service endpoint."""

    name: str
    latency_ms_p95: float
    latency_ms_p99: float
    availability: ErrorBudget
    notes: str = ""


def _default_slo_path() -> Path:
    """Best-effort attempt to locate the default SLO catalog."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "deploy" / "slos.yaml"
        if candidate.exists():
            return candidate
    # Fall back to sibling lookup so callers can detect missing file cleanly.
    return current.parent / "slos.yaml"


def load_default_slos(path: Path | None = None) -> List[SLOConfig]:
    """Load the default SLO catalog from disk."""

    source = path or _default_slo_path()
    if not source.exists():
        return []

    raw = yaml.safe_load(source.read_text()) or {}
    configs: List[SLOConfig] = []
    for entry in raw.get("slos", []):
        availability = entry.get("availability", {})
        configs.append(
            SLOConfig(
                name=entry["name"],
                latency_ms_p95=entry.get("latency_ms_p95", 800),
                latency_ms_p99=entry.get("latency_ms_p99", 1200),
                availability=ErrorBudget(
                    target=availability.get("target", 0.99),
                    window_days=availability.get("window_days", 30),
                ),
                notes=entry.get("notes", ""),
            )
        )
    return configs

