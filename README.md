# Multi-Agent Behavioral Testing Platform

Multi-Agent Behavioral Testing Platform is an end-to-end lab for modelling, executing, monitoring, and governing complex AI workflows. The stack combines a FastAPI backend, structured observability, release guardrails, and collaboration tooling so engineering, QA, and compliance teams can operate at enterprise scale.

---

## ✨ Feature Highlights

**Execution & Orchestration**
- Behavioral graphs with contracts, assertions, deterministic replay, and chaos modes.
- Multi-cloud/provider routing (`openai`, `anthropic`, `azure`, `mock`) with regional fallbacks.
- Sync + async runs, WebSocket log streaming, and historical diffing.

**Governance & Reliability**
- PII/safety middleware, tenant-aware RBAC, immutable audit trails.
- Release guard evaluation (`/release/guard`) with SLO/error-budget checks and promotion CLI.
- Simulation mode & QA run controls (pause/resume/stop/replay) with timeline/compliance views.

**Observability & Analytics**
- OpenTelemetry tracing, structured request logs, Prometheus metrics & alert catalog.
- Analytics endpoints for anomaly detection, drift, cost/latency trends, worker health dashboards.

**Collaboration & DevEx**
- Slack webhook integration for run outcomes.
- Docker dev container, mock providers, load/contract fuzzing harnesses, OpenAPI snapshot tooling.
- CI gating (lint/type/tests/coverage) and infra-as-code scaffolding (Terraform backend module, promotion pipeline).

---

## 📦 Repository Layout

| Path | Purpose |
| ---- | ------- |
| `backend/src/app` | FastAPI application, services, runner, observability, reliability toolkits |
| `backend/tests` | Unit + integration suites (≥94% coverage) |
| `frontend/` | React workbench (execution studio dashboards, WIP) |
| `deploy/` | Deployment assets (multi-stage Dockerfile, promotion workflow, SLO catalog) |
| `iac/terraform/` | Terraform module + root example for managed deployments |
| `scripts/` | Devcontainer builder, release promotion CLI |
| `docker-compose.yaml` | Local stack (API, workers, frontend, supporting services) |
| `DevPlaybook.md` | Engineering playbook / CI-CD guidance |
| `checklist.md` | Enterprise readiness checklist |

---

## ⚡ Quick Start

### Option 1 – Docker Compose

```bash
git clone https://github.com/<your-org>/multi-agent-testing.git
cd multi-agent-testing

# Create a minimal environment file
cat <<EOF > .env
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/postgres
REDIS_URL=redis://redis:6379/0
JWT_SECRET=$(openssl rand -hex 32)
OPENAI_API_KEY=sk-placeholder
ANTHROPIC_API_KEY=anthropic-placeholder
EOF
docker compose up -d                    # api, postgres, redis, worker, frontend

curl http://localhost:8000/health       # verify backend is live
open http://localhost:5173              # frontend (if enabled in compose profile)

# (Optional) Seed demo data for the dashboard
docker compose exec backend python -m app.scripts.seed_demo_data
# Sign in with demo.admin@local / demo-password after seeding
```

> **Tip:** Provide `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. in `.env` to exercise real providers. Otherwise the system runs with deterministic mocks.

### Option 2 – Local Development

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload           # http://localhost:8000/docs

# Frontend (optional prototype studio)
cd ../frontend
npm install
npm run dev                             # http://localhost:5173
```

### Optional Tooling

```bash
# Generate OpenAPI schema snapshot (fails CI if drift detected)
cd backend && python scripts/generate_openapi.py

# Promote a release after guard evaluation
python scripts/promote_release.py --release-id v1.2 --environment staging
```

---

## ⚙️ Configuration

Key environment variables (all supported via `.env`, Compose, or Terraform):

| Variable | Description |
| -------- | ----------- |
| `DATABASE_URL`, `REDIS_URL` | Backing stores for API and Celery |
| `JWT_SECRET` | Signing secret for auth tokens |
| `SECRET_BACKEND` | `env`, `aws`, `gcp`, or `vault` secret manager selection |
| `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SAMPLING_RATIO` | OpenTelemetry tracing |
| `PROMETHEUS_MULTIPROC_DIR` | Enable Prometheus multiprocess metrics if using Gunicorn/Uvicorn workers |
| `RELEASE_GUARD_ENVIRONMENT` | Injectable deployment target for `/release/guard` checks |
| `SLACK_WEBHOOK_URL` | Enable Slack notifications through `/collab/slack/notify` |
| `OIDC_PROVIDER_CONFIG` / `_FILE` | JSON describing OIDC providers and tenant mappings |
| `GOVERNANCE_ENABLED`, `GOVERNANCE_DEFAULT_MIN_SCORE` | Baseline safety enforcement |
| `DEFAULT_PROVIDER_STRATEGY` | Controls provider registry fallback strategy |

See `backend/src/app/config.py` and `deploy/slos.yaml` for exhaustive knobs.

---

## 🧭 Workflow Guide

1. **Author Graphs** – Upload YAML via `/graphs/upload`, or build programmatically using `/graphs/builder/generate`.
2. **Execute Runs** – Fire synchronous `/runs/{graph_id}/execute` or async `/runs/{graph_id}/execute/async`. Stream live logs via `/runs/stream/{run_id}`.
3. **Compare Outcomes** – Diff historical executions with `/runs/{run_id}/diff/{other_id}`.
4. **QA & Replay** – Use `/user-testing/runs/history`, `/timeline`, `/assertions`, `/compliance`, and `/replay` to review behaviour. Apply control actions (`pause/resume/stop/replay`) with `/user-testing/runs/{id}/control`.
5. **Monitor** – Scrape metrics at `/metrics/prometheus`; query analytics endpoints `/analytics/anomalies/latency` and `/analytics/anomalies/series` for drift.
6. **Release Safely** – Call `/release/guard` or run `scripts/promote_release.py` to enforce SLO/error-budget policies before promotion.
7. **Alert & Collaborate** – Configure `SLACK_WEBHOOK_URL` and hit `/collab/slack/notify` for engineering broadcast.

---

## 🔍 Testing & Quality Gates

```bash
cd backend
pytest --cov=app                       # complete suite (targets ≥89% coverage, currently ~95%)
pytest -m "not load"                   # skip long-running load tests
pytest tests/test_user_testing_router.py::test_replay_endpoint  # focused smoke

# Load / soak harness (opt-in)
pytest -m load tests/test_load_harness.py
```

- OpenAPI drift is caught by `tests/test_openapi_schema.py` – run `python scripts/generate_openapi.py` if you intentionally change the API surface.
- CI gating (`.github/workflows/ci.yaml`) enforces lint, type check, unit/integration tests, and coverage thresholds.
- DevContainer (`.devcontainer/`) ensures reproducible VS Code / Codespaces environments.

---

## 🚀 Deployment & Operations

- **Docker**: `deploy/backend.Dockerfile` is a multi-stage build hardened for production. Pair with `docker-compose.yaml` for local orchestration or a minimal staging footprint.
- **Terraform**: `iac/terraform/` contains a root example plus reusable module wiring VPC, Postgres, Redis, ECS/Kubernetes inputs, and observability sinks.
- **Promotion Pipeline**: `deploy/promotion.yaml` describes a canary/blue-green promotion workflow driven by release guard status, artifact provenance, and rollback triggers.
- **SLOs & Alerts**: `deploy/slos.yaml` enumerates service SLOs; `backend/src/app/observability/alerts.py` exports Prometheus alert definitions with links to runbooks in `backend/docs/runbooks.md`.

Enable OTEL exporters and Prometheus scraping in your runtime to populate Grafana/Alertmanager dashboards. Release guard integrates those metrics to veto risky promotions.

---

## 🔐 Security & Compliance Notes

- Tenant-scoped RBAC (Admin, Operator, Viewer, API) with OIDC SSO onboarding.
- Secrets resolved dynamically via environment, AWS/GCP Secret Manager, or Vault.
- Audit log retains tamper-evident hashes (chain-of-custody) and is parameterized by tenant.
- Governance middleware sanitises inputs/outputs, enforces minimum safety scores, and blocks policy violations when configured.

---

## 🗺 Roadmap Snapshot

- [x] Multi-tenant support with OIDC, release guardrails, analytics, QA interface.
- [ ] Production-ready React execution studio (drag-and-drop builder, live inspector).
- [ ] TimescaleDB-backed long-term metrics + anomaly fingerprinting.
- [ ] Managed Helm chart & GitOps pipeline.
- [ ] Expanded collaboration suite (notebook authoring, artifact annotations).

See `checklist.md` for the full enterprise-readiness tracker.

---

## 🤝 Contributing

1. Fork the repository and create a feature branch (`git checkout -b feature/my-feature`).
2. Keep tests green (`pytest --cov=app`) and update documentation/OpenAPI snapshots when behaviour changes.
3. Ensure lint/type gates pass before opening a PR.
4. Submit the PR; CI enforces coverage and quality gates automatically.

---

## 📄 License

MIT License – see [LICENSE](LICENSE) for details.

---

## 🙌 Acknowledgements

Built with FastAPI, Pydantic, Celery, SQLAlchemy, Prometheus, OpenTelemetry, React, Vite, and a stack of engineering patterns inspired by large-scale AI testing programs.
