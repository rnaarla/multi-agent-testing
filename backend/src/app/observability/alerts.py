"""Alerting configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List


RUNBOOK_URL = "https://github.com/example-org/multi-agent-testing/blob/main/backend/docs/runbooks.md"


@dataclass(frozen=True)
class AlertRule:
    """Representation of a Prometheus alert rule."""

    name: str
    expr: str
    for_: str
    labels: Dict[str, str]
    annotations: Dict[str, str]


def default_alert_rules() -> List[AlertRule]:
    """Return the default alert rules used by the platform."""

    return [
        AlertRule(
            name="HighRequestLatency95",
            expr="histogram_quantile(0.95, sum(rate(app_http_request_latency_seconds_bucket[5m])) by (le)) > 1",
            for_="5m",
            labels={"severity": "warning"},
            annotations={
                "summary": "P95 API latency above 1s",
                "runbook": RUNBOOK_URL + "#api-latency-spikes",
            },
        ),
        AlertRule(
            name="RunFailuresSpike",
            expr="sum(rate(app_run_outcomes_total{status=~\"failed|error\"}[10m])) > 5",
            for_="10m",
            labels={"severity": "critical"},
            annotations={
                "summary": "Runs failing at an elevated rate",
                "runbook": RUNBOOK_URL + "#run-failure-investigation",
            },
        ),
        AlertRule(
            name="CostAnomaly",
            expr="sum(increase(app_run_cost_usd_total[1h])) > 100",
            for_="15m",
            labels={"severity": "critical"},
            annotations={
                "summary": "Run cost increased by more than $100 in an hour",
                "runbook": RUNBOOK_URL + "#cost-anomalies",
            },
        ),
    ]


def serialize_prometheus_rules(rules: List[AlertRule]) -> Dict[str, List[Dict]]:
    """Serialize rules to a Prometheus-compatible rule group."""

    return {
        "groups": [
            {
                "name": "multi_agent_testing",
                "interval": "30s",
                "rules": [
                    {
                        "alert": rule.name,
                        "expr": rule.expr,
                        "for": rule.for_,
                        "labels": rule.labels,
                        "annotations": rule.annotations,
                    }
                    for rule in rules
                ],
            }
        ]
    }


def build_incident_payload(rule: AlertRule) -> Dict[str, str]:
    """Construct a payload sent to incident tooling for the rule."""

    return {
        "title": f"[Alert] {rule.name}",
        "summary": rule.annotations.get("summary", ""),
        "severity": rule.labels.get("severity", "warning"),
        "runbook": rule.annotations.get("runbook", RUNBOOK_URL),
    }

