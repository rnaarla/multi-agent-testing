# Multi-Agent Behavioral Testing Platform

[![CI/CD Pipeline](https://github.com/YOUR_ORG/multi-agent-testing/actions/workflows/ci.yaml/badge.svg)](https://github.com/YOUR_ORG/multi-agent-testing/actions/workflows/ci.yaml)

An enterprise-grade framework for evaluating multi-agent systems through behavioral test graphs. The platform combines a Python-based execution engine, FastAPI service layer, React frontend, and PostgreSQL persistence to enable comprehensive testing, monitoring, and governance of AI agent workflows.

## 🚀 Features

### Core Capabilities
- **Behavioral Test Graphs**: Define agent workflows in YAML with nodes, edges, contracts, and assertions
- **Deterministic Execution**: Seed-controlled runs with full replay capability
- **Contract Validation**: Enforce input/output contracts between agent nodes
- **Multi-Provider Support**: OpenAI, Anthropic, Azure OpenAI, Google Gemini, Ollama
- **Async Execution**: Background workers with webhook notifications

### Governance & Safety
- **PII Detection**: Automatic detection and redaction of sensitive data
- **Policy Engine**: Rule-based content filtering and compliance checks
- **Safety Scoring**: Comprehensive safety assessment for agent outputs
- **Audit Logging**: Full traceability of all operations
- **SSO & Tenant Isolation**: Enforce per-tenant RBAC with OIDC SSO and tamper-evident audit trails

### Observability
- **Metrics Dashboard**: Latency tracking, cost accounting, pass rates
- **Drift Detection**: Automatic detection of behavioral regression
- **Execution Traces**: Full visibility into agent execution steps

## 📋 Prerequisites

- Docker & Docker Compose
- Node.js 20+ (for local frontend development)
- Python 3.11+ (for local backend development)

## 🛠️ Quick Start

### Using Docker Compose

```bash
# Clone the repository
git clone https://github.com/YOUR_ORG/multi-agent-testing.git
cd multi-agent-testing

# Create environment file
cat > .env << EOF
JWT_SECRET=$(openssl rand -hex 32)
OPENAI_API_KEY=your-key-here
ANTHROPIC_API_KEY=your-key-here
EOF

# Start all services
docker compose up -d

# Check health
curl http://localhost:8000/health
```

The services will be available at:
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Frontend**: http://localhost:5173
- **Flower (Celery UI)**: http://localhost:5555 (use `--profile monitoring`)

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## 📖 Usage

### Define a Test Graph

Create a YAML file defining your agent workflow:

```yaml
# test-graph.yaml
id: customer-support-flow
name: Customer Support Agent Test

nodes:
  - id: intent-classifier
    type: classifier
    config:

### Run Lifecycle Controls

```bash
# Cancel a queued or running execution
curl -X POST http://localhost:8000/runs/42/cancel

# Deterministically replay a historical run (optionally overriding config)
      provider: openai
  -H "Content-Type: application/json" \
  -d '{"provider":"openai","model":"gpt-4o-mini"}'
```

Background jobs automatically detect orphaned or long-running executions,
requeue safe workloads, and mark stale runs as failed so you can replay them
with guaranteed version pinning and artifact recovery.
      model: gpt-4o-mini
      system_prompt: "Classify customer intent"

  - id: response-generator
    type: responder
    config:
      provider: anthropic
      model: claude-3-haiku-20240307
    inputs: [intent-classifier]

edges:
  - from: intent-classifier
    to: response-generator

contracts:
  - id: intent-output
    source: intent-classifier
    required_fields: [intent, confidence]
    types:
      intent: string
      confidence: float
    constraints:
      confidence:
        min: 0
        max: 1

assertions:
  - id: high-confidence
    type: greater_than
    target: intent-classifier
    field: confidence
    expected: 0.8

  - id: response-quality
    type: semantic_similarity
    target: response-generator
    field: response
    expected: "helpful customer response"
    config:
      threshold: 0.7

  - id: latency-check
    type: latency_under
    target: response-generator
    expected: 5000
```

### Upload and Execute

```bash
# Upload graph
curl -X POST http://localhost:8000/graphs/upload \
  -F "file=@test-graph.yaml"

# Execute graph
curl -X POST http://localhost:8000/runs/1/execute

# Check results
curl http://localhost:8000/runs/1

# Get metrics
curl http://localhost:8000/metrics/summary
```

### Async Execution with Webhooks

```bash
curl -X POST http://localhost:8000/runs/1/execute/async \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "model": "gpt-4o-mini",
    "webhook_url": "https://your-webhook.com/callback"
  }'
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                          │
│                     http://localhost:5173                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Backend API (FastAPI)                        │
│                     http://localhost:8000                        │
├─────────────────────────────────────────────────────────────────┤
│  /graphs     - Test graph management                             │
│  /runs       - Test execution                                    │
│  /metrics    - Analytics & drift detection                       │
│  /auth       - Authentication & RBAC                             │
└─────────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Runner     │    │   Workers    │    │  Providers   │
│   Engine     │    │   (Celery)   │    │   Registry   │
├──────────────┤    ├──────────────┤    ├──────────────┤
│ - Assertions │    │ - Async exec │    │ - OpenAI     │
│ - Contracts  │    │ - Webhooks   │    │ - Anthropic  │
│ - State      │    │ - Scheduling │    │ - Azure      │
│   Machine    │    │              │    │ - Ollama     │
└──────────────┘    └──────────────┘    └──────────────┘
        │                    │                    
        ▼                    ▼                    
┌─────────────────────────────────────────────────────────────────┐
│                         Data Layer                               │
├────────────────────────────┬────────────────────────────────────┤
│     PostgreSQL             │           Redis                     │
│     (Persistence)          │           (Job Queue)               │
└────────────────────────────┴────────────────────────────────────┘
```

## 🧪 Testing

```bash
# Run backend tests
cd backend
pytest app/ -v --cov=app

# Run frontend tests
cd frontend
npm test

# Run integration tests
docker compose up -d
./scripts/integration-tests.sh
```

## 📊 API Reference

### Graphs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/graphs` | GET | List all graphs |
| `/graphs` | POST | Create graph from JSON |
| `/graphs/upload` | POST | Upload YAML graph |
| `/graphs/{id}` | GET | Get graph details |
| `/graphs/{id}` | PUT | Update graph |
| `/graphs/{id}` | DELETE | Delete graph |
| `/graphs/{id}/validate` | GET | Validate graph structure |
| `/graphs/{id}/export` | GET | Export graph (yaml/json/mermaid) |

### Runs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/runs` | GET | List all runs |
| `/runs/{graph_id}/execute` | POST | Execute graph sync |
| `/runs/{graph_id}/execute/async` | POST | Execute graph async |
| `/runs/{id}` | GET | Get run details |
| `/runs/{id}/trace` | GET | Get execution trace |

### Metrics

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/metrics/summary` | GET | Overall metrics |
| `/metrics/by-graph/{id}` | GET | Graph-specific metrics |
| `/metrics/trends` | GET | Metrics over time |
| `/metrics/drift` | GET | Drift detection |

## 🔐 Security

### Authentication

The platform supports JWT tokens and API keys:

```bash
# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"secret"}'

# Use token
curl http://localhost:8000/graphs \
  -H "Authorization: Bearer <token>"

# Or use API key
curl http://localhost:8000/graphs \
  -H "X-API-Key: mat_xxxxx"
```

### Roles

| Role | Permissions |
|------|-------------|
| `admin` | Full access |
| `operator` | Create/run tests, view all |
| `viewer` | Read-only access |
| `api` | Programmatic access |

### SSO & Tenant Isolation

- **OIDC Login**: Configure one or more OpenID Connect providers by setting `OIDC_PROVIDER_CONFIG` or pointing `OIDC_PROVIDER_CONFIG_FILE` at a JSON document. Each provider maps OIDC claims to a local tenant and role.
- **Tenant-Aware APIs**: All `/graphs`, `/runs`, and `/metrics` routes automatically scope queries to the authenticated tenant. Cross-tenant access attempts return 404 responses.
- **Audit Trails**: Audit log entries store the tenant identifier so compliance teams can export per-tenant activity with integrity guarantees.

Example provider configuration:

```json
{
  "okta": {
    "issuer": "https://your-domain.okta.com/oauth2/default",
    "client_id": "OKTA_CLIENT_ID",
    "client_secret": "OKTA_CLIENT_SECRET",
    "redirect_uri": "https://app.example.com/oidc/callback",
    "scopes": ["openid", "profile", "email", "groups"],
    "tenant_claim": "tid",
    "role_claim": "groups",
    "default_role": "viewer",
    "default_tenant": "default"
  }
}
```

Set `tenant_claim` to the claim containing your directory/tenant identifier and `role_claim` to the claim that carries authorization groups. The backend automatically provisions users on first login, pins them to the resolved tenant, and issues JWTs that downstream services can validate.

## 🚢 Deployment

### Kubernetes

```bash
# Apply Kubernetes manifests
kubectl apply -f k8s/

# Or use Helm
helm install agent-testing ./helm/agent-testing
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | Required |
| `REDIS_URL` | Redis connection | Required |
| `JWT_SECRET` | JWT signing key | Required |
| `OPENAI_API_KEY` | OpenAI API key | Optional |
| `ANTHROPIC_API_KEY` | Anthropic API key | Optional |
| `CORS_ORIGINS` | Allowed origins | `*` |
| `ARTIFACTS_S3_BUCKET` | (Optional) bucket for execution artifacts | Local disk |
| `ARTIFACTS_S3_PREFIX` | S3 key prefix for artifacts | `artifacts/` |
| `ARTIFACT_STORAGE_DIR` | Local artifact path when no bucket set | `storage/artifacts` |
| `CELERY_AUTOSCALE_MIN` | Minimum Celery worker pool size | `4` |
| `CELERY_AUTOSCALE_MAX` | Maximum Celery worker pool size | `16` |
| `CELERY_MAX_TASKS_PER_CHILD` | Worker recycling threshold | `100` |
| `SECRET_BACKEND` | Secrets backend (`env`, `aws`, `gcp`, `vault`) | `env` |
| `SECRET_CACHE_TTL_SECONDS` | Seconds to cache resolved secrets | `300` |
| `AUDIT_LOG_RETENTION_DAYS` | Retention policy for immutable audit logs | `365` |
| `GOVERNANCE_ENABLED` | Toggle PII/safety middleware by default | `true` |
| `GOVERNANCE_DEFAULT_MIN_SCORE` | Minimum safety score before blocking output | `0.3` |
| `GOVERNANCE_BLOCK_POLICY_VIOLATIONS` | Block critical policy violations automatically | `false` |
| `OIDC_PROVIDER_CONFIG` | JSON string describing one or more OIDC providers (see example above) | unset |
| `OIDC_PROVIDER_CONFIG_FILE` | Path to JSON file with OIDC provider configs (alternative to env string) | unset |

> **Secrets**: set `SECRET_BACKEND=aws`, `gcp`, or `vault` plus the respective
> credentials (`AWS_REGION`, `GCP_PROJECT`, `VAULT_ADDR`, `VAULT_TOKEN`) to have
> API keys and JWT secrets resolved dynamically. Install
> `google-cloud-secret-manager` for GCP or `hvac` for Vault when using those
> providers.

> **Governance**: execution requests can override `tenant_id` and
> `governance={...}` in the run config to dial policies per tenant while the
> defaults above ensure MAANG-grade guardrails are always active.

#### Horizontal Worker Scaling

- Workers start with Celery autoscaling enabled (configure via the env vars
  above). Locally you can scale concurrent containers with
  `docker compose up --scale worker=4` to test burst capacity.

#### Artifact Snapshotting

- Every execution trace is persisted in PostgreSQL **and** exported as JSON
  artifacts. Point the platform at an S3 bucket via `ARTIFACTS_S3_BUCKET` or
  keep the defaults to write under `storage/artifacts/` for local audits.

## 📈 Roadmap

- [ ] Interactive graph editor (drag & drop)
- [ ] TimescaleDB for metrics time-series
- [ ] S3/GCS for log storage
- [ ] Kubernetes Helm chart
- [ ] OpenTelemetry tracing
- [ ] GraphQL API
- [x] Multi-tenant support (OIDC SSO + tenant isolation)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open a Pull Request

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/)
- [React](https://react.dev/)
- [Celery](https://docs.celeryq.dev/)
- [PostgreSQL](https://www.postgresql.org/)
