#!/usr/bin/env python
"""
Release promotion helper that evaluates reliability guardrails.
"""

from __future__ import annotations

import argparse
import json

from app.reliability import ReleaseMetrics, gate_release, load_default_slos
from app.collaboration.slack import SlackNotifier


def _load_metrics(path: str | None) -> ReleaseMetrics:
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return ReleaseMetrics(**payload)

    # Default to mock metrics for CI verification runs.
    return ReleaseMetrics(
        latency_p95_ms=800,
        latency_p99_ms=1300,
        success_rate=0.992,
        active_incidents=0,
        regression_tests_passed=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate release guardrails.")
    parser.add_argument("--metrics", help="JSON file containing release metrics.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run verification gate prior to canary rollout.",
    )
    parser.add_argument(
        "--canary-check",
        action="store_true",
        help="Evaluate SLO adherence during canary.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Validate production promotion gate.",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send Slack notification when the gate passes.",
    )
    parser.add_argument(
        "--notification-message",
        default=None,
        help="Custom Slack notification message.",
    )

    args = parser.parse_args()
    metrics = _load_metrics(args.metrics)

    gate_release(metrics, slos=load_default_slos())

    if args.verify:
        message = "Verification gate passed."
    elif args.canary_check:
        message = "Canary gate passed."
    elif args.promote:
        message = "Promotion gate passed."
    else:
        message = "Release metrics validated."

    print(message)

    if args.notify:
        notifier = SlackNotifier()
        notifier.send_message(args.notification_message or message, metadata={"metrics": metrics.__dict__})


if __name__ == "__main__":
    main()

