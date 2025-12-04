# On-Call Runbooks

This document captures the operational runbooks referenced by automated alerts.
Each section is mapped in `app.observability.alerts` so incident tooling can link
directly into the relevant procedure.

## API Latency Spikes

1. Check the `app_http_request_latency_seconds` histogram in Grafana to confirm the spike.
2. Inspect recent deploys, background workers, and upstream dependencies (LLM providers).
3. Roll back the most recent deploy if latency started immediately after release.
4. If upstream latency is the culprit, throttle traffic via the execution scheduler.

## Run Failure Investigation

1. Inspect the `Run Failures` Grafana panel to identify failing graphs or tenants.
2. Drill into the governance / assertion logs via the `Test Run Explorer`.
3. If a new graph version regressed, revert to the previous version.
4. Communicate status in the incident channel and update the ticket.

## Cost Anomalies

1. Review the `Run Cost` dashboard for per-tenant spikes.
2. Validate whether long-running or repeated retries caused the increase.
3. Suspend affected graph executions via the execution studio if necessary.
4. Engage the finance contact if projected spend exceeds budget allowances.

