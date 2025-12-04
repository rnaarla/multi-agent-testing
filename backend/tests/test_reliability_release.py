from pathlib import Path

import pytest
import yaml

from app.reliability import ReleaseMetrics, evaluate_release, gate_release, load_default_slos


def test_release_gate_passes_within_thresholds(tmp_path: Path, monkeypatch):
    slo_yaml = {
        "slos": [
            {
                "name": "default",
                "latency_ms_p95": 900,
                "latency_ms_p99": 1500,
                "availability": {"target": 0.99, "window_days": 30},
            }
        ]
    }
    slo_path = tmp_path / "slos.yaml"
    slo_path.write_text(yaml.dump(slo_yaml))

    monkeypatch.setattr(
        "app.reliability.slo._default_slo_path",
        lambda: slo_path,
    )

    metrics = ReleaseMetrics(
        latency_p95_ms=800,
        latency_p99_ms=1200,
        success_rate=0.992,
        active_incidents=0,
        regression_tests_passed=True,
    )

    decision = evaluate_release(metrics, slos=load_default_slos())
    assert decision.approved
    assert decision.reasons == []
    gate_release(metrics, slos=load_default_slos())


def test_release_gate_blocks_when_thresholds_exceeded(tmp_path: Path, monkeypatch):
    slo_yaml = {
        "slos": [
            {
                "name": "default",
                "latency_ms_p95": 600,
                "latency_ms_p99": 900,
                "availability": {"target": 0.995, "window_days": 30},
            }
        ]
    }
    slo_path = tmp_path / "slos.yaml"
    slo_path.write_text(yaml.dump(slo_yaml))
    monkeypatch.setattr(
        "app.reliability.slo._default_slo_path",
        lambda: slo_path,
    )

    metrics = ReleaseMetrics(
        latency_p95_ms=650,
        latency_p99_ms=1000,
        success_rate=0.98,
        active_incidents=1,
        regression_tests_passed=False,
    )

    decision = evaluate_release(metrics, slos=load_default_slos())
    assert not decision.approved
    assert "Active incidents present" in decision.reasons
    assert "Regression suite failed" in decision.reasons
    with pytest.raises(RuntimeError):
        gate_release(metrics, slos=load_default_slos())


def test_load_default_slos_from_repo(tmp_path: Path, monkeypatch):
    slo_yaml = {
        "slos": [
            {
                "name": "custom",
                "latency_ms_p95": 700,
                "latency_ms_p99": 1100,
                "availability": {"target": 0.99, "window_days": 7},
            }
        ]
    }
    slo_path = tmp_path / "slos.yaml"
    slo_path.write_text(yaml.dump(slo_yaml))
    monkeypatch.setattr("app.reliability.slo._default_slo_path", lambda: slo_path)

    slos = load_default_slos()
    assert len(slos) == 1
    assert slos[0].name == "custom"

